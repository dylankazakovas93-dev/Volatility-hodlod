#!/usr/bin/env python3
"""Generate a thorough, self-contained HTML report for the BE60 SAL-A variant
of the locked NQ level-fade strategy (2018-2026).

Honesty rule: WR and PF are computed from the *realized PnL sign* of every
trade, never from the exit-reason label.
  - WIN     = pnl_be60 >  +0.10
  - LOSS    = pnl_be60 <  -0.10   (this includes ANY exit type that nets a
                                    real loss -- a BE or cutoff that somehow
                                    closed underwater would count here, NOT
                                    be dropped as "nothing")
  - SCRATCH = |pnl_be60| <= 0.10  (true breakeven, excluded from WR denominator
                                    but contributes 0 to PF either way)

True WR  = WIN / (WIN + LOSS)
PF       = sum(positive pnl) / abs(sum(negative pnl))

Sections: overall summary, year-by-year, side breakdown, monthly heatmap,
equity curve, stop-size distribution, exit composition by year, and a
filterable/sortable full trade list.

Usage:
    python3 scripts/generate_be60_report.py
"""
from __future__ import annotations

import json
import os

import pandas as pd

BE60_CSV = "data/nq_be60_sala_ledger_2018_2026.csv"
OUT_HTML = "out/nq_be60_report.html"

WIN_THRESH = 0.1
LOSS_THRESH = -0.1


def classify(pnl: float) -> str:
    if pnl > WIN_THRESH:
        return "WIN"
    if pnl < LOSS_THRESH:
        return "LOSS"
    return "SCRATCH"


def profit_factor(s: pd.Series) -> float | None:
    g = float(s[s > 0].sum())
    l = float(-s[s < 0].sum())
    if l <= 0:
        return None
    return g / l


def true_wr(s: pd.Series) -> float:
    wins = int((s > WIN_THRESH).sum())
    losses = int((s < LOSS_THRESH).sum())
    return wins / (wins + losses) * 100 if (wins + losses) else 0.0


def max_drawdown(s: pd.Series) -> float:
    eq = s.cumsum()
    return float((eq - eq.cummax()).min()) if not s.empty else 0.0


def max_losing_streak(s: pd.Series) -> int:
    streak = best = 0
    for v in s:
        streak = streak + 1 if v < LOSS_THRESH else 0
        best = max(best, streak)
    return best


def block_stats(df: pd.DataFrame) -> dict:
    p = df["pnl_be60"]
    wins = int((df["result"] == "WIN").sum())
    losses = int((df["result"] == "LOSS").sum())
    scratches = int((df["result"] == "SCRATCH").sum())
    pf = profit_factor(p)
    return {
        "n": int(len(df)),
        "net": round(float(p.sum()), 2),
        "pf": round(pf, 3) if pf is not None else None,
        "twr": round(true_wr(p), 1),
        "raw_wr": round(float((p > 0).mean() * 100), 1) if len(df) else 0.0,
        "wins": wins, "losses": losses, "scratches": scratches,
        "tp": int((df["exit_be60"] == "TP").sum()),
        "sl": int((df["exit_be60"] == "SL").sum()),
        "be": int((df["exit_be60"] == "BE").sum()),
        "cutoff": int((df["exit_be60"] == "cutoff").sum()),
        "avg_stop": round(float(df["cap"].mean()), 2) if len(df) else 0.0,
        "med_stop": round(float(df["cap"].median()), 2) if len(df) else 0.0,
        "max_dd": round(max_drawdown(p), 1),
        "max_streak": max_losing_streak(p),
    }


def year_table(df: pd.DataFrame) -> list[dict]:
    rows = []
    for yr, sub in df.groupby("year"):
        s = block_stats(sub)
        s["year"] = int(yr)
        rows.append(s)
    return rows


def side_table(df: pd.DataFrame) -> list[dict]:
    rows = []
    for side, sub in df.groupby("side"):
        s = block_stats(sub)
        s["side"] = side
        rows.append(s)
    return rows


def stop_buckets(df: pd.DataFrame) -> list[dict]:
    edges = [0, 25, 50, 75, 100, 125, 150, 175, 200, 1e9]
    labels = ["0-25", "25-50", "50-75", "75-100", "100-125", "125-150", "150-175", "175-200", "200 (cap)"]
    rows = []
    cats = pd.cut(df["cap"], bins=edges, labels=labels, right=True, include_lowest=True)
    for lab in labels:
        sub = df[cats == lab]
        if sub.empty:
            rows.append({"bucket": lab, "n": 0, "net": 0.0, "pf": None, "twr": 0.0})
            continue
        s = block_stats(sub)
        rows.append({"bucket": lab, "n": s["n"], "net": s["net"], "pf": s["pf"], "twr": s["twr"]})
    return rows


def monthly_table(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["month"] = pd.to_datetime(df["sess_date"]).dt.month
    pivot = df.pivot_table(index="year", columns="month", values="pnl_be60", aggfunc="sum", fill_value=0.0)
    pivot = pivot.reindex(columns=range(1, 13), fill_value=0.0)
    years = sorted(pivot.index.tolist())
    return {
        "years": [int(y) for y in years],
        "data": {int(y): [round(float(pivot.loc[y, m]), 1) for m in range(1, 13)] for y in years},
    }


def equity_curve(df: pd.DataFrame) -> dict:
    df = df.sort_values("touched_at").reset_index(drop=True)
    eq = df["pnl_be60"].cumsum()
    # year-boundary marker indices (first trade of each year)
    markers = []
    seen = set()
    for i, yr in enumerate(df["year"]):
        if yr not in seen:
            seen.add(yr)
            markers.append({"i": i, "year": int(yr)})
    return {
        "equity": [round(float(v), 1) for v in eq],
        "markers": markers,
    }


def trades_json(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.sort_values("touched_at").iterrows():
        out.append({
            "date": r["sess_date"],
            "year": int(r["year"]),
            "side": r["side"],
            "entry_ts": str(r["touched_at"])[:19],
            "level": round(float(r["level"]), 2),
            "anchor": round(float(r["anchor"]), 2),
            "stop": round(float(r["cap"]), 3),
            "pnl": round(float(r["pnl_be60"]), 2),
            "exit": r["exit_be60"],
            "result": r["result"],
        })
    return out


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NQ BE60 SAL-A &mdash; Detailed Strategy Report</title>
<style>
  :root {
    --bg: #0f1117; --panel: #171a23; --border: #2a2e3a;
    --text: #e4e6eb; --muted: #9aa0ad; --accent: #4f8cff;
    --green: #3ddc84; --red: #ff5c5c; --be: #f5c542;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: var(--bg); color: var(--text);
    font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    font-size: 14px;
  }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 28px 0 10px; color: var(--accent); }
  h3 { font-size: 13px; margin: 18px 0 8px; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
  .subtitle { color: var(--muted); margin-bottom: 20px; font-size: 13px; }
  .config-box {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: var(--muted); line-height: 1.6;
  }
  .config-box code { color: var(--text); }
  .config-box .honesty { color: var(--be); }
  .summary-cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 16px; min-width: 110px;
  }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 20px; font-weight: 700; margin-top: 2px; }
  .pos { color: var(--green); }
  .neg { color: var(--red); }
  table {
    width: 100%; border-collapse: collapse; background: var(--panel);
    border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
  }
  th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--border); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  th { color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .03em;
       cursor: pointer; user-select: none; position: sticky; top: 0; background: #1d2230; }
  th:hover { color: var(--text); }
  tbody tr:hover { background: #1c2030; }
  tbody tr.total-row { font-weight: 700; background: #1a1e2a; }
  .table-wrap { overflow-x: auto; margin-bottom: 24px; }
  .controls { display: flex; gap: 10px; align-items: center; margin: 16px 0 8px; flex-wrap: wrap; }
  select, input[type=text] {
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px 10px; font-size: 13px;
  }
  .trade-wrap { max-height: 600px; overflow: auto; border-radius: 8px; border: 1px solid var(--border); }
  .trade-wrap table { border: none; border-radius: 0; }
  .exit-tp { color: var(--green); font-weight: 600; }
  .exit-sl { color: var(--red); font-weight: 600; }
  .exit-be { color: var(--be); font-weight: 600; }
  .res-win { color: var(--green); font-weight: 600; }
  .res-loss { color: var(--red); font-weight: 600; }
  .res-scratch { color: var(--be); font-weight: 600; }
  .count { color: var(--muted); font-size: 12px; margin-left: 8px; }
  .heat { text-align: center; border-radius: 4px; padding: 4px 6px; }
  canvas { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; max-width: 100%; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
  footer { margin-top: 30px; color: var(--muted); font-size: 11px; }
</style>
</head>
<body>

<h1>NQ Level-Fade Strategy &mdash; BE60 SAL-A Detailed Report</h1>
<div class="subtitle">2018-01-01 &rarr; 2026-06-07 &middot; lineDays=20 &middot; entries 19:00&ndash;11:00 ET (skip 11:00&ndash;15:00) &middot; session-stop after first <em>real</em> loss</div>

<div class="config-box">
  <strong>Config:</strong> <code>TP = SL = min(1.5 &times; previous completed 1h range, 200)</code> &mdash; 1:1 RR, capped at 200 pts.<br>
  <strong>BE60 SAL-A:</strong> stop moves to entry after 60 one-minute bars (fires immediately even if already underwater at bar 60).
  A breakeven scratch (exactly 0&nbsp;pts) does <em>not</em> count as a loss for the session stop-after-loss rule, so the session keeps trading after a BE.<br>
  <span class="honesty"><strong>Honesty rule for this report:</strong> Win/Loss/PF/WR are computed from each trade's <em>realized PnL sign</em>,
  not from its exit-reason label. WIN = pnl &gt; +0.1, LOSS = pnl &lt; &minus;0.1, SCRATCH = |pnl| &le; 0.1.
  Any BE or session-cutoff exit that closed at a real loss would be counted as a LOSS here &mdash; never dropped as "nothing."
  In this dataset every BE exit is an exact 0.0 scratch and all 23 cutoff exits are positive, so True WR (TP/(TP+SL)) and the
  PnL-sign WR agree to within the cutoff wins.</span><br>
  <strong>Stop size</strong> = the capped risk distance (<code>min(1.5&times;anchor, 200)</code>) for that trade &mdash; identical definition to the Standard variant.
</div>

<div id="overall-cards"></div>

<h2>Year-by-Year</h2>
<div class="table-wrap"><table id="year-table"><thead><tr>
  <th>Year</th><th>Freq (n)</th><th>Net pts</th><th>PF</th><th>True WR</th><th>Raw WR</th>
  <th>Win</th><th>Loss</th><th>Scratch</th>
  <th>TP</th><th>SL</th><th>BE</th><th>Cutoff</th>
  <th>Avg Stop</th><th>Med Stop</th><th>Max DD</th><th>Max Loss Streak</th>
</tr></thead><tbody></tbody></table></div>

<div class="grid2">
  <div>
    <h2>By Side</h2>
    <div class="table-wrap"><table id="side-table"><thead><tr>
      <th>Side</th><th>Freq (n)</th><th>Net pts</th><th>PF</th><th>True WR</th><th>Raw WR</th>
      <th>Win</th><th>Loss</th><th>Scratch</th><th>Avg Stop</th><th>Med Stop</th>
    </tr></thead><tbody></tbody></table></div>

    <h2>Stop-Size Distribution</h2>
    <div class="table-wrap"><table id="stop-table"><thead><tr>
      <th>Stop Bucket (pts)</th><th>Freq (n)</th><th>Net pts</th><th>PF</th><th>True WR</th>
    </tr></thead><tbody></tbody></table></div>
  </div>
  <div>
    <h2>Equity Curve</h2>
    <canvas id="equity-canvas" width="560" height="320"></canvas>
  </div>
</div>

<h2>Monthly Net PnL Heatmap</h2>
<div class="table-wrap"><table id="monthly-table"><thead><tr></tr></thead><tbody></tbody></table></div>

<h2>All Trades</h2>
<div class="controls">
  <label>Year: <select id="yearfilter" onchange="filterTrades()"><option value="all">All</option></select></label>
  <label>Side: <select id="sidefilter" onchange="filterTrades()"><option value="all">All</option><option value="upper">upper (short)</option><option value="lower">lower (long)</option></select></label>
  <label>Exit: <select id="exitfilter" onchange="filterTrades()"><option value="all">All</option><option value="TP">TP</option><option value="SL">SL</option><option value="BE">BE</option><option value="cutoff">cutoff</option></select></label>
  <label>Result: <select id="resultfilter" onchange="filterTrades()"><option value="all">All</option><option value="WIN">WIN</option><option value="LOSS">LOSS</option><option value="SCRATCH">SCRATCH</option></select></label>
  <span class="count" id="trade-count"></span>
</div>
<div class="trade-wrap"><table id="trade-table"><thead><tr></tr></thead><tbody></tbody></table></div>

<footer>Generated from data/nq_be60_sala_ledger_2018_2026.csv &mdash; 2018-2026, n trades reflects post-SAL-A ledger.</footer>

<script>
const DATA = __DATA_JSON__;

function fmtPts(v) {
  if (v === null || v === undefined) return '&mdash;';
  const cls = v > 0 ? 'pos' : (v < 0 ? 'neg' : '');
  return `<span class="${cls}">${v.toFixed(1)}</span>`;
}
function fmtPF(v) {
  if (v === null || v === undefined) return '&infin;';
  return v.toFixed(3);
}
function exitClass(e) {
  if (e === 'TP') return 'exit-tp';
  if (e === 'SL') return 'exit-sl';
  if (e === 'BE') return 'exit-be';
  return '';
}
function resultClass(r) {
  if (r === 'WIN') return 'res-win';
  if (r === 'LOSS') return 'res-loss';
  return 'res-scratch';
}

// ── overall cards ─────────────────────────────────────────────
function renderOverall() {
  const o = DATA.overall;
  let html = '<div class="summary-cards">';
  html += `<div class="card"><div class="label">Trades</div><div class="value">${o.n}</div></div>`;
  html += `<div class="card"><div class="label">Net pts</div><div class="value">${fmtPts(o.net)}</div></div>`;
  html += `<div class="card"><div class="label">Profit Factor</div><div class="value">${fmtPF(o.pf)}</div></div>`;
  html += `<div class="card"><div class="label">True WR (Win/(Win+Loss))</div><div class="value">${o.twr}%</div></div>`;
  html += `<div class="card"><div class="label">Raw WR (pnl&gt;0)</div><div class="value">${o.raw_wr}%</div></div>`;
  html += `<div class="card"><div class="label">Win / Loss / Scratch</div><div class="value">${o.wins} / ${o.losses} / ${o.scratches}</div></div>`;
  html += `<div class="card"><div class="label">TP / SL / BE / Cutoff</div><div class="value">${o.tp} / ${o.sl} / ${o.be} / ${o.cutoff}</div></div>`;
  html += `<div class="card"><div class="label">Avg / Med Stop</div><div class="value">${o.avg_stop} / ${o.med_stop}</div></div>`;
  html += `<div class="card"><div class="label">Max Drawdown</div><div class="value neg">${o.max_dd}</div></div>`;
  html += `<div class="card"><div class="label">Max Loss Streak</div><div class="value">${o.max_streak}</div></div>`;
  html += '</div>';
  document.getElementById('overall-cards').innerHTML = html;
}

// ── year table ────────────────────────────────────────────────
function renderYearTable() {
  const tbody = document.querySelector('#year-table tbody');
  let html = '';
  for (const y of DATA.yearly) {
    html += `<tr><td>${y.year}</td><td>${y.n}</td><td>${fmtPts(y.net)}</td><td>${fmtPF(y.pf)}</td>`
          + `<td>${y.twr}%</td><td>${y.raw_wr}%</td>`
          + `<td class="res-win">${y.wins}</td><td class="res-loss">${y.losses}</td><td class="res-scratch">${y.scratches}</td>`
          + `<td>${y.tp}</td><td>${y.sl}</td><td>${y.be}</td><td>${y.cutoff}</td>`
          + `<td>${y.avg_stop}</td><td>${y.med_stop}</td><td class="neg">${y.max_dd}</td><td>${y.max_streak}</td></tr>`;
  }
  const o = DATA.overall;
  html += `<tr class="total-row"><td>ALL</td><td>${o.n}</td><td>${fmtPts(o.net)}</td><td>${fmtPF(o.pf)}</td>`
        + `<td>${o.twr}%</td><td>${o.raw_wr}%</td>`
        + `<td class="res-win">${o.wins}</td><td class="res-loss">${o.losses}</td><td class="res-scratch">${o.scratches}</td>`
        + `<td>${o.tp}</td><td>${o.sl}</td><td>${o.be}</td><td>${o.cutoff}</td>`
        + `<td>${o.avg_stop}</td><td>${o.med_stop}</td><td class="neg">${o.max_dd}</td><td>${o.max_streak}</td></tr>`;
  tbody.innerHTML = html;
}

// ── side table ────────────────────────────────────────────────
function renderSideTable() {
  const tbody = document.querySelector('#side-table tbody');
  let html = '';
  for (const s of DATA.by_side) {
    html += `<tr><td>${s.side}</td><td>${s.n}</td><td>${fmtPts(s.net)}</td><td>${fmtPF(s.pf)}</td>`
          + `<td>${s.twr}%</td><td>${s.raw_wr}%</td>`
          + `<td class="res-win">${s.wins}</td><td class="res-loss">${s.losses}</td><td class="res-scratch">${s.scratches}</td>`
          + `<td>${s.avg_stop}</td><td>${s.med_stop}</td></tr>`;
  }
  tbody.innerHTML = html;
}

// ── stop-size distribution ───────────────────────────────────
function renderStopTable() {
  const tbody = document.querySelector('#stop-table tbody');
  let html = '';
  for (const b of DATA.stop_buckets) {
    html += `<tr><td>${b.bucket}</td><td>${b.n}</td><td>${fmtPts(b.net)}</td><td>${fmtPF(b.pf)}</td><td>${b.twr}%</td></tr>`;
  }
  tbody.innerHTML = html;
}

// ── monthly heatmap ───────────────────────────────────────────
function renderMonthly() {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const thead = document.querySelector('#monthly-table thead tr');
  thead.innerHTML = '<th>Year</th>' + months.map(m => `<th>${m}</th>`).join('') + '<th>Total</th>';

  // find max abs value for color scaling
  let maxAbs = 1;
  for (const y of DATA.monthly.years) {
    for (const v of DATA.monthly.data[y]) maxAbs = Math.max(maxAbs, Math.abs(v));
  }
  function heatColor(v) {
    if (v === 0) return 'transparent';
    const t = Math.min(Math.abs(v) / maxAbs, 1);
    const alpha = 0.15 + 0.55 * t;
    return v > 0 ? `rgba(61,220,132,${alpha.toFixed(2)})` : `rgba(255,92,92,${alpha.toFixed(2)})`;
  }

  const tbody = document.querySelector('#monthly-table tbody');
  let html = '';
  for (const y of DATA.monthly.years) {
    const row = DATA.monthly.data[y];
    const total = row.reduce((a,b) => a+b, 0);
    html += `<tr><td>${y}</td>`;
    for (const v of row) {
      html += `<td class="heat" style="background:${heatColor(v)}">${v.toFixed(0)}</td>`;
    }
    html += `<td><strong>${fmtPts(Math.round(total*10)/10)}</strong></td></tr>`;
  }
  tbody.innerHTML = html;
}

// ── equity curve (canvas) ────────────────────────────────────
function renderEquity() {
  const c = document.getElementById('equity-canvas');
  const ctx = c.getContext('2d');
  const eq = DATA.equity.equity;
  const markers = DATA.equity.markers;
  const W = c.width, H = c.height, pad = 36;

  const minV = Math.min(0, ...eq);
  const maxV = Math.max(...eq);
  const xScale = (W - 2*pad) / Math.max(1, eq.length - 1);
  const yScale = (H - 2*pad) / (maxV - minV || 1);
  const xOf = i => pad + i * xScale;
  const yOf = v => H - pad - (v - minV) * yScale;

  ctx.clearRect(0, 0, W, H);

  // zero line
  ctx.strokeStyle = '#2a2e3a';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, yOf(0));
  ctx.lineTo(W - pad, yOf(0));
  ctx.stroke();

  // year markers
  ctx.fillStyle = '#9aa0ad';
  ctx.font = '10px sans-serif';
  for (const m of markers) {
    const x = xOf(m.i);
    ctx.strokeStyle = '#1f2330';
    ctx.beginPath();
    ctx.moveTo(x, pad);
    ctx.lineTo(x, H - pad);
    ctx.stroke();
    ctx.fillText(String(m.year), x + 2, pad + 10);
  }

  // equity line
  ctx.strokeStyle = '#4f8cff';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  eq.forEach((v, i) => {
    const x = xOf(i), y = yOf(v);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // axis labels
  ctx.fillStyle = '#9aa0ad';
  ctx.fillText(maxV.toFixed(0), 2, yOf(maxV) + 4);
  ctx.fillText(minV.toFixed(0), 2, yOf(minV) + 4);
  ctx.fillText('0', 2, yOf(0) + 4);
}

// ── trade list ────────────────────────────────────────────────
let STATE = { filtered: DATA.trades.slice(), sortCol: null, sortDir: 1 };

function renderTradeHeader() {
  const cols = [
    ['date','Session Date'], ['year','Year'], ['side','Side'], ['entry_ts','Entry (ET)'],
    ['level','Level'], ['anchor','Anchor (1h range)'], ['stop','Stop Size'],
    ['pnl','PnL'], ['exit','Exit'], ['result','Result']
  ];
  const tr = document.querySelector('#trade-table thead tr');
  tr.innerHTML = cols.map(([k, lab]) => `<th onclick="sortTrades('${k}')">${lab}</th>`).join('');
  const yearSel = document.getElementById('yearfilter');
  const years = [...new Set(DATA.trades.map(t => t.year))].sort();
  for (const y of years) {
    const opt = document.createElement('option');
    opt.value = y; opt.textContent = y;
    yearSel.appendChild(opt);
  }
}

function filterTrades() {
  const yr = document.getElementById('yearfilter').value;
  const side = document.getElementById('sidefilter').value;
  const exitf = document.getElementById('exitfilter').value;
  const resf = document.getElementById('resultfilter').value;
  let rows = DATA.trades;
  if (yr !== 'all') rows = rows.filter(t => String(t.year) === yr);
  if (side !== 'all') rows = rows.filter(t => t.side === side);
  if (exitf !== 'all') rows = rows.filter(t => t.exit === exitf);
  if (resf !== 'all') rows = rows.filter(t => t.result === resf);
  STATE.filtered = rows;
  renderTradeRows();
}

function renderTradeRows() {
  const rows = STATE.filtered;
  const tbody = document.querySelector('#trade-table tbody');
  let html = '';
  for (const t of rows) {
    html += `<tr><td>${t.date}</td><td>${t.year}</td><td>${t.side}</td><td>${t.entry_ts}</td>`
          + `<td>${t.level}</td><td>${t.anchor}</td><td>${t.stop}</td>`
          + `<td>${fmtPts(t.pnl)}</td><td class="${exitClass(t.exit)}">${t.exit}</td>`
          + `<td class="${resultClass(t.result)}">${t.result}</td></tr>`;
  }
  tbody.innerHTML = html;
  document.getElementById('trade-count').textContent = `${rows.length} trades`;
}

function sortTrades(col) {
  if (STATE.sortCol === col) STATE.sortDir = -STATE.sortDir; else { STATE.sortCol = col; STATE.sortDir = 1; }
  STATE.filtered.sort((a, b) => {
    let av = a[col], bv = b[col];
    if (typeof av === 'string') return av.localeCompare(bv) * STATE.sortDir;
    return (av - bv) * STATE.sortDir;
  });
  renderTradeRows();
}

renderOverall();
renderYearTable();
renderSideTable();
renderStopTable();
renderMonthly();
renderEquity();
renderTradeHeader();
renderTradeRows();
</script>
</body>
</html>
"""


def main():
    df = pd.read_csv(BE60_CSV, parse_dates=["touched_at"])
    df["result"] = df["pnl_be60"].apply(classify)

    data = {
        "overall": block_stats(df),
        "yearly": year_table(df),
        "by_side": side_table(df),
        "stop_buckets": stop_buckets(df),
        "monthly": monthly_table(df),
        "equity": equity_curve(df),
        "trades": trades_json(df),
    }

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    os.makedirs("out", exist_ok=True)
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"Wrote {OUT_HTML}  ({os.path.getsize(OUT_HTML)/1024:.0f} KB)")
    print(f"  overall: {data['overall']}")


if __name__ == "__main__":
    main()
