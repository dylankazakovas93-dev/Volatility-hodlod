#!/usr/bin/env python3
"""Generate a self-contained HTML report for the locked NQ level-fade strategy.

Reads the saved 2018-2026 ledgers (Standard and BE60 SAL-A) and produces a
single HTML file with:
  - overall WR + PF summary per variant
  - year-by-year table: frequency, net pts, PF, true WR, avg/median stop size
  - full trade list per variant, filterable by year and sortable by column

Usage:
    python3 scripts/generate_trade_report.py
"""
from __future__ import annotations

import json

import pandas as pd

STANDARD_CSV = "data/nq_standard_ledger_2018_2026.csv"
BE60_CSV = "data/nq_be60_sala_ledger_2018_2026.csv"
OUT_HTML = "out/nq_strategy_report.html"


def true_wr(tp: int, sl: int) -> float:
    return tp / (tp + sl) * 100 if (tp + sl) else 0.0


def profit_factor(s: pd.Series) -> float:
    g = float(s[s > 0].sum())
    l = float(-s[s < 0].sum())
    return g / l if l > 0 else float("inf")


def year_summary(df: pd.DataFrame, pnl_col: str, exit_col: str) -> list[dict]:
    rows = []
    for yr, sub in df.groupby("year"):
        pts = sub[pnl_col]
        tp = int((sub[exit_col] == "TP").sum())
        sl = int((sub[exit_col] == "SL").sum())
        be = int((sub[exit_col] == "BE").sum()) if "BE" in sub[exit_col].values else 0
        rows.append({
            "year": int(yr),
            "n": int(len(sub)),
            "net": round(float(pts.sum()), 1),
            "pf": round(profit_factor(pts), 3) if profit_factor(pts) != float("inf") else None,
            "twr": round(true_wr(tp, sl), 1),
            "tp": tp, "sl": sl, "be": be,
            "avg_stop": round(float(sub["cap"].mean()), 2),
            "med_stop": round(float(sub["cap"].median()), 2),
        })
    return rows


def overall_summary(df: pd.DataFrame, pnl_col: str, exit_col: str) -> dict:
    pts = df[pnl_col]
    tp = int((df[exit_col] == "TP").sum())
    sl = int((df[exit_col] == "SL").sum())
    be = int((df[exit_col] == "BE").sum()) if "BE" in df[exit_col].values else 0
    return {
        "n": int(len(df)),
        "net": round(float(pts.sum()), 1),
        "pf": round(profit_factor(pts), 3),
        "twr": round(true_wr(tp, sl), 1),
        "tp": tp, "sl": sl, "be": be,
        "avg_stop": round(float(df["cap"].mean()), 2),
        "med_stop": round(float(df["cap"].median()), 2),
        "raw_wr": round(float((pts > 0).mean() * 100), 1),
    }


def trades_json(df: pd.DataFrame, pnl_col: str, exit_col: str) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        out.append({
            "date": r["sess_date"],
            "year": int(r["year"]),
            "side": r["side"],
            "entry_ts": str(r["touched_at"])[:19],
            "level": round(float(r["level"]), 2),
            "anchor": round(float(r["anchor"]), 2),
            "stop": round(float(r["cap"]), 3),
            "pnl": round(float(r[pnl_col]), 2),
            "exit": r[exit_col],
        })
    return out


def build_variant(csv_path: str, pnl_col: str, exit_col: str) -> dict:
    df = pd.read_csv(csv_path, parse_dates=["touched_at"])
    return {
        "overall": overall_summary(df, pnl_col, exit_col),
        "yearly": year_summary(df, pnl_col, exit_col),
        "trades": trades_json(df, pnl_col, exit_col),
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NQ Level-Fade Strategy &mdash; tp_sl_cap200 Report</title>
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
  .subtitle { color: var(--muted); margin-bottom: 20px; font-size: 13px; }
  .config-box {
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: var(--muted);
  }
  .config-box code { color: var(--text); }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab-btn {
    background: var(--panel); border: 1px solid var(--border); color: var(--muted);
    padding: 8px 18px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600;
  }
  .tab-btn.active { color: var(--text); border-color: var(--accent); background: #1d2230; }
  .variant { display: none; }
  .variant.active { display: block; }
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
  .yearly-wrap { overflow-x: auto; margin-bottom: 24px; }
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
  .count { color: var(--muted); font-size: 12px; margin-left: 8px; }
  footer { margin-top: 30px; color: var(--muted); font-size: 11px; }
</style>
</head>
<body>

<h1>NQ Level-Fade Strategy &mdash; Locked Config Report</h1>
<div class="subtitle">2018-01-01 &rarr; 2026-06-07 &middot; lineDays=20 &middot; entries 19:00&ndash;11:00 ET (skip 11:00&ndash;15:00) &middot; session-stop after first real loss</div>

<div class="config-box">
  <strong>Config:</strong> <code>TP = SL = min(1.5 &times; previous completed 1h range, 200)</code> &mdash; 1:1 RR, capped at 200 pts.<br>
  <strong>Standard</strong>: fixed TP/SL, session stop-after-loss (SAL).
  <strong>BE60 SAL-A</strong>: stop moves to entry after 60 one-minute bars; a breakeven scratch (0&nbsp;pts) does <em>not</em> count as a loss for SAL, so the session keeps trading.
  &quot;Stop size&quot; = the capped risk distance (<code>min(1.5&times;anchor, 200)</code>) for that trade.
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="showVariant('standard')">Standard</button>
  <button class="tab-btn" onclick="showVariant('be60')">BE60 SAL-A</button>
</div>

<div id="standard" class="variant active"></div>
<div id="be60" class="variant"></div>

<footer>Generated from data/nq_standard_ledger_2018_2026.csv and data/nq_be60_sala_ledger_2018_2026.csv</footer>

<script>
const DATA = __DATA_JSON__;

function fmtPts(v) {
  if (v === null || v === undefined) return '&mdash;';
  const cls = v > 0 ? 'pos' : (v < 0 ? 'neg' : '');
  return `<span class="${cls}">${v.toFixed(1)}</span>`;
}
function fmtPF(v) {
  if (v === null) return '&infin;';
  return v.toFixed(3);
}
function exitClass(e) {
  if (e === 'TP') return 'exit-tp';
  if (e === 'SL') return 'exit-sl';
  if (e === 'BE') return 'exit-be';
  return '';
}

function renderVariant(key, label, d) {
  const o = d.overall;
  let html = '';

  // summary cards
  html += '<div class="summary-cards">';
  html += `<div class="card"><div class="label">Trades</div><div class="value">${o.n}</div></div>`;
  html += `<div class="card"><div class="label">Net pts</div><div class="value">${fmtPts(o.net)}</div></div>`;
  html += `<div class="card"><div class="label">Profit Factor</div><div class="value">${fmtPF(o.pf)}</div></div>`;
  html += `<div class="card"><div class="label">True WR (TP/(TP+SL))</div><div class="value">${o.twr}%</div></div>`;
  html += `<div class="card"><div class="label">Raw WR</div><div class="value">${o.raw_wr}%</div></div>`;
  html += `<div class="card"><div class="label">TP / SL / BE</div><div class="value">${o.tp} / ${o.sl} / ${o.be}</div></div>`;
  html += `<div class="card"><div class="label">Avg / Med Stop</div><div class="value">${o.avg_stop} / ${o.med_stop}</div></div>`;
  html += '</div>';

  // year-by-year table
  html += '<h2>Year-by-Year</h2>';
  html += '<div class="yearly-wrap"><table><thead><tr>';
  html += '<th>Year</th><th>Freq (n)</th><th>Net pts</th><th>PF</th><th>True WR</th>'
        + '<th>TP</th><th>SL</th><th>BE</th><th>Avg Stop</th><th>Median Stop</th>';
  html += '</tr></thead><tbody>';
  for (const y of d.yearly) {
    html += `<tr><td>${y.year}</td><td>${y.n}</td><td>${fmtPts(y.net)}</td><td>${fmtPF(y.pf)}</td>`
          + `<td>${y.twr}%</td><td>${y.tp}</td><td>${y.sl}</td><td>${y.be}</td>`
          + `<td>${y.avg_stop}</td><td>${y.med_stop}</td></tr>`;
  }
  html += '</tbody></table></div>';

  // trade list controls
  html += '<h2>All Trades</h2>';
  html += '<div class="controls">';
  html += `<label>Year: <select id="${key}-yearfilter" onchange="filterTrades('${key}')"><option value="all">All</option>`;
  const years = [...new Set(d.trades.map(t => t.year))].sort();
  for (const y of years) html += `<option value="${y}">${y}</option>`;
  html += '</select></label>';
  html += `<label>Side: <select id="${key}-sidefilter" onchange="filterTrades('${key}')"><option value="all">All</option><option value="upper">upper (short)</option><option value="lower">lower (long)</option></select></label>`;
  html += `<label>Exit: <select id="${key}-exitfilter" onchange="filterTrades('${key}')"><option value="all">All</option><option value="TP">TP</option><option value="SL">SL</option><option value="BE">BE</option><option value="cutoff">cutoff</option></select></label>`;
  html += `<span class="count" id="${key}-count"></span>`;
  html += '</div>';

  // trade table
  html += `<div class="trade-wrap"><table id="${key}-table"><thead><tr>`;
  const cols = [
    ['date','Session Date'], ['year','Year'], ['side','Side'], ['entry_ts','Entry (ET)'],
    ['level','Level'], ['anchor','Anchor (1h range)'], ['stop','Stop Size'], ['pnl','PnL'], ['exit','Exit']
  ];
  for (const [k, lab] of cols) html += `<th onclick="sortTrades('${key}','${k}')">${lab}</th>`;
  html += '</tr></thead><tbody></tbody></table></div>';

  return html;
}

function filterTrades(key) {
  const yr = document.getElementById(`${key}-yearfilter`).value;
  const side = document.getElementById(`${key}-sidefilter`).value;
  const exitf = document.getElementById(`${key}-exitfilter`).value;
  let rows = DATA[key].trades;
  if (yr !== 'all') rows = rows.filter(t => String(t.year) === yr);
  if (side !== 'all') rows = rows.filter(t => t.side === side);
  if (exitf !== 'all') rows = rows.filter(t => t.exit === exitf);
  STATE[key].filtered = rows;
  renderTradeRows(key);
}

function renderTradeRows(key) {
  const rows = STATE[key].filtered;
  const tbody = document.querySelector(`#${key}-table tbody`);
  let html = '';
  for (const t of rows) {
    html += `<tr><td>${t.date}</td><td>${t.year}</td><td>${t.side}</td><td>${t.entry_ts}</td>`
          + `<td>${t.level}</td><td>${t.anchor}</td><td>${t.stop}</td>`
          + `<td>${fmtPts(t.pnl)}</td><td class="${exitClass(t.exit)}">${t.exit}</td></tr>`;
  }
  tbody.innerHTML = html;
  document.getElementById(`${key}-count`).textContent = `${rows.length} trades`;
}

function sortTrades(key, col) {
  const st = STATE[key];
  if (st.sortCol === col) st.sortDir = -st.sortDir; else { st.sortCol = col; st.sortDir = 1; }
  st.filtered.sort((a, b) => {
    let av = a[col], bv = b[col];
    if (typeof av === 'string') { av = av.localeCompare(bv) ; return av * st.sortDir; }
    return (av - bv) * st.sortDir;
  });
  renderTradeRows(key);
}

function showVariant(key) {
  document.querySelectorAll('.variant').forEach(v => v.classList.remove('active'));
  document.getElementById(key).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
}

const STATE = {};
for (const [key, label] of [['standard','Standard'], ['be60','BE60 SAL-A']]) {
  document.getElementById(key).innerHTML = renderVariant(key, label, DATA[key]);
  STATE[key] = { filtered: DATA[key].trades.slice(), sortCol: null, sortDir: 1 };
  renderTradeRows(key);
}
</script>
</body>
</html>
"""


def main():
    data = {
        "standard": build_variant(STANDARD_CSV, "pnl_standard", "exit_standard"),
        "be60": build_variant(BE60_CSV, "pnl_be60", "exit_be60"),
    }
    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    import os
    os.makedirs("out", exist_ok=True)
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print(f"Wrote {OUT_HTML}  ({os.path.getsize(OUT_HTML)/1024:.0f} KB)")
    print(f"  standard: {data['standard']['overall']}")
    print(f"  be60:     {data['be60']['overall']}")


if __name__ == "__main__":
    main()
