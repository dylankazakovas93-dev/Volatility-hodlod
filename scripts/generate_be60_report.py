#!/usr/bin/env python3
"""Thorough self-contained HTML report for the BE60 SAL-A variant of the locked
NQ level-fade strategy (2018-2026), with two tabs:

  * All Entries          - the full ledger (19:00-11:00 ET, skip 11:00-15:00)
  * 00:00-11:00 ET only  - drops the 19:00-24:00 evening entries

Win-rate honesty rule (per user spec):
  - A BE scratch is "nothing gained or lost" and is split in two:
        be_dd     = instant-fire BE while UNDERWATER at the min-60 checkpoint
                    (a rescued would-be loss).  COUNTS as a non-win.
        be_profit = BE that came from a profit state and pulled back to entry
                    (a given-up winner).  EXCLUDED from the win-rate entirely.
  - Adjusted WR = wins / (wins + SL losses + be_dd)
        wins = trades with realized pnl > 0 (TP + any positive cutoff).
  - Because be_dd scratches net exactly 0 (not -1R), the breakeven win rate for
    this metric is NOT 50% -- it is losses/(wins+losses+be_dd). Both numbers are
    shown so the metric can't be misread.
  - True WR = TP / (TP + SL) is also shown (all BE excluded, standard view).

Reads data/nq_be60_sala_enriched_2018_2026.csv (built by build_be60_enriched.py).

Usage:
    python3 scripts/generate_be60_report.py
"""
from __future__ import annotations

import json
import os

import pandas as pd

ENRICHED_CSV = "data/nq_be60_sala_enriched_2018_2026.csv"
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
    return g / l if l > 0 else None


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
    wins = int((p > WIN_THRESH).sum())
    losses = int((p < LOSS_THRESH).sum())          # all SL exits
    scratches = int((p.abs() <= WIN_THRESH).sum())
    be_dd = int(((df["exit_be60"] == "BE") & df["be_dd"]).sum())
    be_profit = int(((df["exit_be60"] == "BE") & ~df["be_dd"]).sum())
    tp = int((df["exit_be60"] == "TP").sum())
    sl = int((df["exit_be60"] == "SL").sum())

    adj_denom = wins + losses + be_dd
    adj_wr = wins / adj_denom * 100 if adj_denom else 0.0
    adj_be = losses / adj_denom * 100 if adj_denom else 0.0   # breakeven WR for this metric
    true_wr = tp / (tp + sl) * 100 if (tp + sl) else 0.0

    pf = profit_factor(p)
    return {
        "n": int(len(df)),
        "net": round(float(p.sum()), 2),
        "pf": round(pf, 3) if pf is not None else None,
        "adj_wr": round(adj_wr, 1),
        "adj_be": round(adj_be, 1),
        "true_wr": round(true_wr, 1),
        "wins": wins, "losses": losses, "scratches": scratches,
        "be_dd": be_dd, "be_profit": be_profit,
        "tp": tp, "sl": sl,
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
    cats = pd.cut(df["cap"], bins=edges, labels=labels, right=True, include_lowest=True)
    rows = []
    for lab in labels:
        sub = df[cats == lab]
        if sub.empty:
            rows.append({"bucket": lab, "n": 0, "net": 0.0, "pf": None, "adj_wr": 0.0})
            continue
        s = block_stats(sub)
        rows.append({"bucket": lab, "n": s["n"], "net": s["net"], "pf": s["pf"], "adj_wr": s["adj_wr"]})
    return rows


def monthly_table(df: pd.DataFrame) -> dict:
    d = df.copy()
    d["month"] = pd.to_datetime(d["sess_date"]).dt.month
    if d.empty:
        return {"years": [], "data": {}}
    pivot = d.pivot_table(index="year", columns="month", values="pnl_be60", aggfunc="sum", fill_value=0.0)
    pivot = pivot.reindex(columns=range(1, 13), fill_value=0.0)
    years = sorted(pivot.index.tolist())
    return {
        "years": [int(y) for y in years],
        "data": {int(y): [round(float(pivot.loc[y, m]), 1) for m in range(1, 13)] for y in years},
    }


def equity_curve(df: pd.DataFrame) -> dict:
    d = df.sort_values("touched_at").reset_index(drop=True)
    eq = d["pnl_be60"].cumsum()
    markers, seen = [], set()
    for i, yr in enumerate(d["year"]):
        if yr not in seen:
            seen.add(yr)
            markers.append({"i": i, "year": int(yr)})
    return {"equity": [round(float(v), 1) for v in eq], "markers": markers}


def trades_json(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.sort_values("touched_at").iterrows():
        exit_lbl = r["exit_be60"]
        # distinguish the two BE kinds in the trade table
        if exit_lbl == "BE":
            exit_lbl = "BE-dd" if r["be_dd"] else "BE-prof"
        out.append({
            "date": r["sess_date"],
            "year": int(r["year"]),
            "side": r["side"],
            "entry_ts": str(r["touched_at"])[:19],
            "level": round(float(r["level"]), 2),
            "anchor": round(float(r["anchor"]), 2),
            "stop": round(float(r["cap"]), 3),
            "mae": round(float(r["mae"]), 1),
            "mfe": round(float(r["mfe"]), 1),
            "pnl": round(float(r["pnl_be60"]), 2),
            "exit": exit_lbl,
            "result": r["result"],
        })
    return out


def make_dashboard(df: pd.DataFrame) -> dict:
    return {
        "overall": block_stats(df),
        "yearly": year_table(df),
        "by_side": side_table(df),
        "stop_buckets": stop_buckets(df),
        "monthly": monthly_table(df),
        "equity": equity_curve(df),
        "trades": trades_json(df),
    }


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
    font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; font-size: 14px;
  }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 28px 0 10px; color: var(--accent); }
  .subtitle { color: var(--muted); margin-bottom: 16px; font-size: 13px; }
  .config-box {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; margin-bottom: 18px; font-size: 13px; color: var(--muted); line-height: 1.6;
  }
  .config-box code { color: var(--text); }
  .config-box .honesty { color: var(--be); }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab-btn {
    background: var(--panel); border: 1px solid var(--border); color: var(--muted);
    padding: 9px 20px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .tab-btn.active { color: var(--text); border-color: var(--accent); background: #1d2230; }
  .summary-cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 16px; min-width: 110px;
  }
  .card.hl { border-color: var(--accent); }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 20px; font-weight: 700; margin-top: 2px; }
  .card .sub { color: var(--muted); font-size: 11px; margin-top: 2px; }
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
  select { background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; font-size: 13px; }
  .trade-wrap { max-height: 600px; overflow: auto; border-radius: 8px; border: 1px solid var(--border); }
  .trade-wrap table { border: none; border-radius: 0; }
  .exit-tp { color: var(--green); font-weight: 600; }
  .exit-sl { color: var(--red); font-weight: 600; }
  .exit-be-dd { color: #ff9d5c; font-weight: 600; }
  .exit-be-prof { color: var(--be); font-weight: 600; }
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
<div class="subtitle">2018-01-01 &rarr; 2026-06-07 &middot; lineDays=20 &middot; session-stop after first <em>real</em> loss</div>

<div class="config-box">
  <strong>Config:</strong> <code>TP = SL = min(1.5 &times; previous completed 1h range, 200)</code> &mdash; 1:1 RR, capped 200 pts.
  <strong>BE60:</strong> stop &rarr; entry after 60 one-minute bars (fires immediately if already underwater at bar 60).
  <strong>SAL-A:</strong> a BE scratch does not stop the session; only a real loss does.<br>
  <span class="honesty"><strong>Win-rate rule:</strong> a BE scratch nets 0 and is split:
  <strong>BE-dd</strong> = fired while underwater at the min-60 checkpoint (a rescued would-be loss) &rarr; counts as a non-win;
  <strong>BE-prof</strong> = came from profit then pulled back to entry (a given-up winner) &rarr; excluded entirely.
  <strong>Adjusted WR = wins / (wins + SL + BE-dd)</strong>.
  Because BE-dd scratches cost 0 (not &minus;1R), this metric's breakeven is <em>not</em> 50% &mdash; it is
  losses/(wins+losses+BE-dd), shown on the card. True WR = TP/(TP+SL) is also shown (all BE excluded).
  The old "raw WR" (counting every BE as a non-win) is intentionally dropped as misleading.</span>
</div>

<div class="tabs">
  <button class="tab-btn active" id="tab-all" onclick="setTab('all')">All Entries (19:00&ndash;11:00 ET)</button>
  <button class="tab-btn" id="tab-morning" onclick="setTab('morning')">00:00&ndash;11:00 ET only</button>
</div>

<div id="overall-cards"></div>

<h2>Year-by-Year</h2>
<div class="table-wrap"><table id="year-table"><thead><tr>
  <th>Year</th><th>Freq (n)</th><th>Net pts</th><th>PF</th>
  <th>Adj WR</th><th>(breakeven)</th><th>True WR</th>
  <th>Win</th><th>SL Loss</th><th>BE-dd</th><th>BE-prof</th>
  <th>Avg Stop</th><th>Med Stop</th><th>Max DD</th><th>Max Loss Streak</th>
</tr></thead><tbody></tbody></table></div>

<div class="grid2">
  <div>
    <h2>By Side</h2>
    <div class="table-wrap"><table id="side-table"><thead><tr>
      <th>Side</th><th>Freq (n)</th><th>Net pts</th><th>PF</th><th>Adj WR</th><th>True WR</th>
      <th>Win</th><th>SL Loss</th><th>BE-dd</th><th>BE-prof</th>
    </tr></thead><tbody></tbody></table></div>

    <h2>Stop-Size Distribution</h2>
    <div class="table-wrap"><table id="stop-table"><thead><tr>
      <th>Stop Bucket (pts)</th><th>Freq (n)</th><th>Net pts</th><th>PF</th><th>Adj WR</th>
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
  <label>Year: <select id="yearfilter" onchange="renderTradeRows()"><option value="all">All</option></select></label>
  <label>Side: <select id="sidefilter" onchange="renderTradeRows()"><option value="all">All</option><option value="upper">upper (short)</option><option value="lower">lower (long)</option></select></label>
  <label>Exit: <select id="exitfilter" onchange="renderTradeRows()"><option value="all">All</option><option value="TP">TP</option><option value="SL">SL</option><option value="BE-dd">BE-dd</option><option value="BE-prof">BE-prof</option><option value="cutoff">cutoff</option></select></label>
  <label>Result: <select id="resultfilter" onchange="renderTradeRows()"><option value="all">All</option><option value="WIN">WIN</option><option value="LOSS">LOSS</option><option value="SCRATCH">SCRATCH</option></select></label>
  <span class="count" id="trade-count"></span>
</div>
<div class="trade-wrap"><table id="trade-table"><thead><tr></tr></thead><tbody></tbody></table></div>

<footer>Generated from data/nq_be60_sala_enriched_2018_2026.csv. BE-dd = underwater at min-60 (rescued loss); BE-prof = given-up winner.</footer>

<script>
const DATA = __DATA_JSON__;
let ACTIVE = 'all';
let SORT = { col: null, dir: 1 };

function cur() { return DATA[ACTIVE]; }
function fmtPts(v) {
  if (v === null || v === undefined) return '&mdash;';
  const cls = v > 0 ? 'pos' : (v < 0 ? 'neg' : '');
  return `<span class="${cls}">${v.toFixed(1)}</span>`;
}
function fmtPF(v) { return (v === null || v === undefined) ? '&infin;' : v.toFixed(3); }
function exitClass(e) {
  if (e === 'TP') return 'exit-tp';
  if (e === 'SL') return 'exit-sl';
  if (e === 'BE-dd') return 'exit-be-dd';
  if (e === 'BE-prof') return 'exit-be-prof';
  return '';
}
function resultClass(r) { return r === 'WIN' ? 'res-win' : (r === 'LOSS' ? 'res-loss' : 'res-scratch'); }

function renderOverall() {
  const o = cur().overall;
  let html = '<div class="summary-cards">';
  html += `<div class="card"><div class="label">Trades</div><div class="value">${o.n}</div></div>`;
  html += `<div class="card"><div class="label">Net pts</div><div class="value">${fmtPts(o.net)}</div></div>`;
  html += `<div class="card"><div class="label">Profit Factor</div><div class="value">${fmtPF(o.pf)}</div></div>`;
  html += `<div class="card hl"><div class="label">Adjusted WR</div><div class="value">${o.adj_wr}%</div><div class="sub">breakeven ${o.adj_be}% &middot; profitable above it</div></div>`;
  html += `<div class="card"><div class="label">True WR (TP/(TP+SL))</div><div class="value">${o.true_wr}%</div><div class="sub">all BE excluded</div></div>`;
  html += `<div class="card"><div class="label">Win / SL Loss</div><div class="value">${o.wins} / ${o.losses}</div></div>`;
  html += `<div class="card"><div class="label">BE-dd / BE-prof</div><div class="value">${o.be_dd} / ${o.be_profit}</div><div class="sub">rescued / given-up</div></div>`;
  html += `<div class="card"><div class="label">Cutoff (win)</div><div class="value">${o.cutoff}</div></div>`;
  html += `<div class="card"><div class="label">Avg / Med Stop</div><div class="value">${o.avg_stop} / ${o.med_stop}</div></div>`;
  html += `<div class="card"><div class="label">Max Drawdown</div><div class="value neg">${o.max_dd}</div></div>`;
  html += `<div class="card"><div class="label">Max Loss Streak</div><div class="value">${o.max_streak}</div></div>`;
  html += '</div>';
  document.getElementById('overall-cards').innerHTML = html;
}

function renderYearTable() {
  const tbody = document.querySelector('#year-table tbody');
  let html = '';
  const rowHtml = (y, isTotal) =>
    `<tr${isTotal ? ' class="total-row"' : ''}><td>${isTotal ? 'ALL' : y.year}</td><td>${y.n}</td><td>${fmtPts(y.net)}</td><td>${fmtPF(y.pf)}</td>`
    + `<td>${y.adj_wr}%</td><td class="count">${y.adj_be}%</td><td>${y.true_wr}%</td>`
    + `<td class="res-win">${y.wins}</td><td class="res-loss">${y.losses}</td>`
    + `<td class="exit-be-dd">${y.be_dd}</td><td class="exit-be-prof">${y.be_profit}</td>`
    + `<td>${y.avg_stop}</td><td>${y.med_stop}</td><td class="neg">${y.max_dd}</td><td>${y.max_streak}</td></tr>`;
  for (const y of cur().yearly) html += rowHtml(y, false);
  html += rowHtml(cur().overall, true);
  tbody.innerHTML = html;
}

function renderSideTable() {
  const tbody = document.querySelector('#side-table tbody');
  let html = '';
  for (const s of cur().by_side) {
    html += `<tr><td>${s.side}</td><td>${s.n}</td><td>${fmtPts(s.net)}</td><td>${fmtPF(s.pf)}</td>`
          + `<td>${s.adj_wr}%</td><td>${s.true_wr}%</td>`
          + `<td class="res-win">${s.wins}</td><td class="res-loss">${s.losses}</td>`
          + `<td class="exit-be-dd">${s.be_dd}</td><td class="exit-be-prof">${s.be_profit}</td></tr>`;
  }
  tbody.innerHTML = html;
}

function renderStopTable() {
  const tbody = document.querySelector('#stop-table tbody');
  let html = '';
  for (const b of cur().stop_buckets) {
    html += `<tr><td>${b.bucket}</td><td>${b.n}</td><td>${fmtPts(b.net)}</td><td>${fmtPF(b.pf)}</td><td>${b.adj_wr}%</td></tr>`;
  }
  tbody.innerHTML = html;
}

function renderMonthly() {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  document.querySelector('#monthly-table thead tr').innerHTML =
    '<th>Year</th>' + months.map(m => `<th>${m}</th>`).join('') + '<th>Total</th>';
  const mo = cur().monthly;
  let maxAbs = 1;
  for (const y of mo.years) for (const v of mo.data[y]) maxAbs = Math.max(maxAbs, Math.abs(v));
  const heatColor = v => {
    if (v === 0) return 'transparent';
    const a = (0.15 + 0.55 * Math.min(Math.abs(v) / maxAbs, 1)).toFixed(2);
    return v > 0 ? `rgba(61,220,132,${a})` : `rgba(255,92,92,${a})`;
  };
  let html = '';
  for (const y of mo.years) {
    const row = mo.data[y];
    const total = row.reduce((a, b) => a + b, 0);
    html += `<tr><td>${y}</td>`;
    for (const v of row) html += `<td class="heat" style="background:${heatColor(v)}">${v.toFixed(0)}</td>`;
    html += `<td><strong>${fmtPts(Math.round(total * 10) / 10)}</strong></td></tr>`;
  }
  document.querySelector('#monthly-table tbody').innerHTML = html;
}

function renderEquity() {
  const c = document.getElementById('equity-canvas');
  const ctx = c.getContext('2d');
  const eq = cur().equity.equity, markers = cur().equity.markers;
  const W = c.width, H = c.height, pad = 36;
  const minV = Math.min(0, ...eq), maxV = Math.max(...eq, 1);
  const xS = (W - 2*pad) / Math.max(1, eq.length - 1), yS = (H - 2*pad) / (maxV - minV || 1);
  const xOf = i => pad + i * xS, yOf = v => H - pad - (v - minV) * yS;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#2a2e3a'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(pad, yOf(0)); ctx.lineTo(W - pad, yOf(0)); ctx.stroke();
  ctx.fillStyle = '#9aa0ad'; ctx.font = '10px sans-serif';
  for (const m of markers) {
    const x = xOf(m.i);
    ctx.strokeStyle = '#1f2330';
    ctx.beginPath(); ctx.moveTo(x, pad); ctx.lineTo(x, H - pad); ctx.stroke();
    ctx.fillText(String(m.year), x + 2, pad + 10);
  }
  ctx.strokeStyle = '#4f8cff'; ctx.lineWidth = 1.5; ctx.beginPath();
  eq.forEach((v, i) => { const x = xOf(i), y = yOf(v); i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); });
  ctx.stroke();
  ctx.fillStyle = '#9aa0ad';
  ctx.fillText(maxV.toFixed(0), 2, yOf(maxV) + 4);
  ctx.fillText(minV.toFixed(0), 2, yOf(minV) + 4);
  ctx.fillText('0', 2, yOf(0) + 4);
}

function rebuildYearFilter() {
  const sel = document.getElementById('yearfilter');
  sel.innerHTML = '<option value="all">All</option>';
  const years = [...new Set(cur().trades.map(t => t.year))].sort();
  for (const y of years) { const o = document.createElement('option'); o.value = y; o.textContent = y; sel.appendChild(o); }
}

function renderTradeHeader() {
  const cols = [
    ['date','Session Date'], ['year','Year'], ['side','Side'], ['entry_ts','Entry (ET)'],
    ['level','Level'], ['anchor','Anchor (1h range)'], ['stop','Stop Size'],
    ['mae','MAE'], ['mfe','MFE'], ['pnl','PnL'], ['exit','Exit'], ['result','Result']
  ];
  document.querySelector('#trade-table thead tr').innerHTML =
    cols.map(([k, lab]) => `<th onclick="sortTrades('${k}')">${lab}</th>`).join('');
}

function renderTradeRows() {
  const yr = document.getElementById('yearfilter').value;
  const side = document.getElementById('sidefilter').value;
  const exitf = document.getElementById('exitfilter').value;
  const resf = document.getElementById('resultfilter').value;
  let rows = cur().trades.slice();
  if (yr !== 'all') rows = rows.filter(t => String(t.year) === yr);
  if (side !== 'all') rows = rows.filter(t => t.side === side);
  if (exitf !== 'all') rows = rows.filter(t => t.exit === exitf);
  if (resf !== 'all') rows = rows.filter(t => t.result === resf);
  if (SORT.col) {
    rows.sort((a, b) => {
      let av = a[SORT.col], bv = b[SORT.col];
      if (typeof av === 'string') return av.localeCompare(bv) * SORT.dir;
      return (av - bv) * SORT.dir;
    });
  }
  let html = '';
  for (const t of rows) {
    html += `<tr><td>${t.date}</td><td>${t.year}</td><td>${t.side}</td><td>${t.entry_ts}</td>`
          + `<td>${t.level}</td><td>${t.anchor}</td><td>${t.stop}</td>`
          + `<td class="neg">${t.mae}</td><td class="pos">${t.mfe}</td>`
          + `<td>${fmtPts(t.pnl)}</td><td class="${exitClass(t.exit)}">${t.exit}</td>`
          + `<td class="${resultClass(t.result)}">${t.result}</td></tr>`;
  }
  document.querySelector('#trade-table tbody').innerHTML = html;
  document.getElementById('trade-count').textContent = `${rows.length} trades`;
}

function sortTrades(col) {
  if (SORT.col === col) SORT.dir = -SORT.dir; else { SORT.col = col; SORT.dir = 1; }
  renderTradeRows();
}

function renderAll() {
  renderOverall(); renderYearTable(); renderSideTable(); renderStopTable();
  renderMonthly(); renderEquity(); rebuildYearFilter(); renderTradeRows();
}

function setTab(key) {
  ACTIVE = key; SORT = { col: null, dir: 1 };
  document.getElementById('tab-all').classList.toggle('active', key === 'all');
  document.getElementById('tab-morning').classList.toggle('active', key === 'morning');
  renderAll();
}

renderTradeHeader();
renderAll();
</script>
</body>
</html>
"""


def main():
    df = pd.read_csv(ENRICHED_CSV)
    df["be_dd"] = df["be_dd"].astype(str).str.lower().isin(["true", "1"])
    df["result"] = df["pnl_be60"].apply(classify)

    et = pd.to_datetime(df["touched_at"], utc=True).dt.tz_convert("America/New_York")
    hour = et.dt.hour
    morning = df[(hour >= 0) & (hour < 11)].copy()

    data = {"all": make_dashboard(df), "morning": make_dashboard(morning)}

    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    os.makedirs("out", exist_ok=True)
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"Wrote {OUT_HTML}  ({os.path.getsize(OUT_HTML)/1024:.0f} KB)")
    for k in ("all", "morning"):
        o = data[k]["overall"]
        print(f"  {k:8} n={o['n']:5} net={o['net']:>9} pf={o['pf']} "
              f"adjWR={o['adj_wr']}% (be {o['adj_be']}%) trueWR={o['true_wr']}% "
              f"BE-dd={o['be_dd']} BE-prof={o['be_profit']}")


if __name__ == "__main__":
    main()
