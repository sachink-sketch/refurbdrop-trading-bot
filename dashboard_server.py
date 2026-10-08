#!/usr/bin/env python3
"""Live trading dashboard — reads log files, serves a web UI on port 5555."""
import re, json, os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

BASE   = Path(__file__).parent
LOGS   = BASE / "logs"
UP_LOG = LOGS / "crypto_upgraded_out.log"
WA_LOG = LOGS / "watch_out.log"


def _read(path: Path, tail: int = 400) -> str:
    """Read log, collapsing Rich's line-wrapped continuations into single lines."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
        collapsed = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Continuation lines: heavy indent, no timestamp, no log-level keyword
            is_cont = (
                len(line) - len(line.lstrip()) >= 20
                and not re.match(r'^\[[\d/]', line.lstrip())
                and not re.match(r'^\s{4,}(?:INFO|WARNING|ERROR|DEBUG)\s', line)
            )
            if is_cont:
                if collapsed:
                    collapsed[-1] = collapsed[-1].rstrip() + " " + stripped
                else:
                    collapsed.append(stripped)
            else:
                collapsed.append(line)
        return "\n".join(collapsed)
    except Exception:
        return ""


def parse_state() -> dict:
    up   = _read(UP_LOG)
    wa   = _read(WA_LOG)
    full = up + "\n" + wa

    # --- portfolio ---
    port_m = list(re.finditer(r"PORTFOLIO\s+USDT:\s*\$([0-9,\.]+).*?Total:\s*\$([0-9,\.]+)", full))
    usdt_bal = float(port_m[-1].group(1).replace(",","")) if port_m else 1000.0
    total    = float(port_m[-1].group(2).replace(",","")) if port_m else 1000.0

    # --- session P&L (upgraded bot) ---
    pnl_m = list(re.finditer(r"Session P&L:\s*([+\-][0-9\.]+%)\s*\(\$([+\-][0-9\.]+)\)", up))
    pnl_pct = pnl_m[-1].group(1) if pnl_m else "+0.00%"
    pnl_usd = float(pnl_m[-1].group(2).replace(",","")) if pnl_m else 0.0

    # --- watcher P&L ---
    w_pnl_m = list(re.finditer(r"Session P&L:\s*([+\-][0-9\.]+%)\s*\(\$([+\-][0-9\.]+)\)", wa))
    w_pnl_pct = w_pnl_m[-1].group(1) if w_pnl_m else "+0.00%"
    w_pnl_usd = float(w_pnl_m[-1].group(2).replace(",","")) if w_pnl_m else 0.0

    # watcher total from "Cycle N | Total: $X"
    w_total_m = list(re.finditer(r"Cycle \d+ \| Total: \$([0-9,\.]+)", wa))
    w_total = float(w_total_m[-1].group(1).replace(",","")) if w_total_m else 1000.0

    # --- cycle count ---
    cyc_m = list(re.finditer(r"CRYPTO Cycle #(\d+)", up))
    cycle = int(cyc_m[-1].group(1)) if cyc_m else 0

    wa_cyc = list(re.finditer(r"Cycle (\d+) \|", wa))
    w_cycle = int(wa_cyc[-1].group(1)) if wa_cyc else 0

    # --- open positions (upgraded bot) ---
    pos_m = list(re.finditer(
        r"\[([+\-])\] ([A-Z]+/[A-Z]+):\s*([0-9\.]+) @ \$([0-9,\.]+)\s*now \$([0-9,\.]+)\s*\(([+\-][0-9\.]+%)\)",
        up
    ))
    positions = []
    seen = set()
    for m in reversed(pos_m):
        pair = m.group(2)
        if pair not in seen:
            seen.add(pair)
            positions.append({
                "sign":  m.group(1),
                "pair":  pair,
                "qty":   m.group(3),
                "entry": m.group(4),
                "now":   m.group(5),
                "pnl":   m.group(6),
            })

    # --- open positions (watcher) ---
    # After collapsing, lines look like:
    # INFO  BNB/USDT: 0.105303 @  watch_positions.py:78 $759.71 now $758.80 (-0.12%)
    w_pos_m = list(re.finditer(
        r"([A-Z]+/[A-Z]+):\s*([0-9\.]+)\s*@\s*(?:watch_positions\.py:\d+\s*)?\$([0-9,\.]+)\s+now\s+\$([0-9,\.]+)\s+\(([+\-][0-9\.]+%)\)",
        wa
    ))
    w_positions = []
    w_seen = set()
    for m in reversed(w_pos_m):
        pair = m.group(1)
        if pair not in w_seen:
            w_seen.add(pair)
            w_positions.append({
                "pair":  pair,
                "qty":   m.group(2),
                "entry": m.group(3),
                "now":   m.group(4),
                "pnl":   m.group(5),
            })

    # --- signals feed (last 30 signal lines) ---
    sig_m = list(re.finditer(
        r"\[([0-9/: ]+)\].*?([A-Z]+/[A-Z]+)\s*->\s*(BUY|SELL|HOLD)\s*conf=(\d+)%",
        up
    ))
    signals = []
    for m in sig_m[-30:]:
        signals.append({
            "time":   m.group(1).strip(),
            "pair":   m.group(2),
            "action": m.group(3),
            "conf":   int(m.group(4)),
        })

    # --- trade events ---
    events = []
    for pat, label in [
        (r"TAKE PROFIT ([A-Z/]+):", "TAKE PROFIT"),
        (r"STOP LOSS ([A-Z/]+):",   "STOP LOSS"),
        (r"TRAILING STOP hit ([A-Z/]+):", "TRAIL STOP"),
        (r"TIME EXIT ([A-Z/]+):",   "TIME EXIT"),
        (r"CLOSED \[([A-Z]+)\] ([A-Z/]+):", None),
        (r"\[PAPER\] BUY ([A-Z/]+)",  "BUY"),
        (r"\[PAPER\] SELL ([A-Z/]+)", "SELL"),
    ]:
        for m in re.finditer(pat, full):
            events.append({"event": label or m.group(1), "pair": m.group(len(m.groups()))})

    # --- market status ---
    rh_log = LOGS / "bot.log"
    stock_events = []
    if rh_log.exists():
        rh_text = _read(rh_log, 100)
        for m in re.finditer(r"(BUY|SELL|TAKE PROFIT|STOP LOSS)\s+([A-Z]+)", rh_text):
            stock_events.append({"event": m.group(1), "ticker": m.group(2)})

    return {
        "ts":          datetime.now().strftime("%H:%M:%S"),
        "cycle":       cycle,
        "w_cycle":     w_cycle,
        "total":       total,
        "usdt_bal":    usdt_bal,
        "pnl_pct":     pnl_pct,
        "pnl_usd":     pnl_usd,
        "w_pnl_pct":   w_pnl_pct,
        "w_pnl_usd":   w_pnl_usd,
        "w_total":     w_total,
        "positions":   positions,
        "w_positions": w_positions,
        "signals":     signals,
        "events":      events[-10:],
        "stock_events": stock_events[-5:],
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>REFURBDROP Trading Bot</title>
<meta http-equiv="refresh" content="3">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',monospace;font-size:13px;min-height:100vh;padding:16px}
  h1{font-size:18px;color:#58a6ff;letter-spacing:2px;text-transform:uppercase;margin-bottom:16px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:16px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
  .card .label{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
  .card .val{font-size:22px;font-weight:700}
  .pos{color:#3fb950}.neg{color:#f85149}.neu{color:#8b949e}
  .tag{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;margin-right:4px}
  .tag-buy{background:#1a3c1a;color:#3fb950;border:1px solid #3fb950}
  .tag-sell{background:#3c1a1a;color:#f85149;border:1px solid #f85149}
  .tag-hold{background:#1f1f1f;color:#8b949e;border:1px solid #30363d}
  .tag-tp{background:#1a2f3c;color:#58a6ff;border:1px solid #58a6ff}
  .tag-sl{background:#3c1a1a;color:#f85149;border:1px solid #f85149}
  .tag-trail{background:#2d1a3c;color:#d2a8ff;border:1px solid #d2a8ff}
  .tag-time{background:#3c2a1a;color:#d29922;border:1px solid #d29922}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;padding:6px 8px;font-size:11px;color:#8b949e;border-bottom:1px solid #21262d;text-transform:uppercase}
  td{padding:6px 8px;border-bottom:1px solid #161b22}
  tr:hover td{background:#1c2128}
  .section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:12px}
  .section-title{font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;display:flex;align-items:center;gap:8px}
  .dot{width:8px;height:8px;border-radius:50%;background:#3fb950;display:inline-block;animation:pulse 1.5s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .conf-bar{display:inline-block;height:6px;border-radius:3px;margin-left:6px;vertical-align:middle}
  .ts{color:#30363d;font-size:11px;float:right;margin-top:-20px}
  .badge{background:#21262d;border-radius:4px;padding:1px 6px;font-size:11px;color:#8b949e}
</style>
</head>
<body>
<h1>&#x25CF; REFURBDROP Trading Bot — Live Dashboard</h1>
<div id="ts" class="ts"></div>
<div class="grid" id="cards"></div>
<div class="section">
  <div class="section-title"><span class="dot"></span> Open Positions — Upgraded Bot (5-slot, trailing stops)</div>
  <table>
    <tr><th>Pair</th><th>Qty</th><th>Entry</th><th>Current</th><th>P&L</th></tr>
    <tbody id="pos-body"></tbody>
  </table>
</div>
<div class="section">
  <div class="section-title"><span class="dot" style="background:#d29922"></span> Demo Positions Watcher (BNB + BTC)</div>
  <table>
    <tr><th>Pair</th><th>Qty</th><th>Entry</th><th>Current</th><th>P&L</th></tr>
    <tbody id="wpos-body"></tbody>
  </table>
</div>
<div class="section">
  <div class="section-title"><span class="dot" style="background:#58a6ff"></span> Signal Feed — Last Cycle</div>
  <table>
    <tr><th>Time</th><th>Pair</th><th>Signal</th><th>Confidence</th></tr>
    <tbody id="sig-body"></tbody>
  </table>
</div>
<script>
async function refresh(){
  try{
    const r=await fetch('/api/status');
    const d=await r.json();
    document.getElementById('ts').textContent='Last update: '+d.ts;
    // cards
    const pnlColor=d.pnl_usd>=0?'pos':'neg';
    const wColor=d.w_pnl_usd>=0?'pos':'neg';
    document.getElementById('cards').innerHTML=`
      <div class="card"><div class="label">Portfolio (Bot)</div><div class="val">$${d.total.toFixed(2)}</div></div>
      <div class="card"><div class="label">Session P&L (Bot)</div><div class="val ${pnlColor}">${d.pnl_pct} ($${d.pnl_usd>=0?'+':''}${d.pnl_usd.toFixed(2)})</div></div>
      <div class="card"><div class="label">Demo Watch P&L</div><div class="val ${wColor}">${d.w_pnl_pct} ($${d.w_pnl_usd>=0?'+':''}${d.w_pnl_usd.toFixed(2)})</div></div>
      <div class="card"><div class="label">Open Positions</div><div class="val">${d.positions.length} <span class="badge">of 5</span></div></div>
      <div class="card"><div class="label">Bot Cycle</div><div class="val">#${d.cycle}</div></div>
      <div class="card"><div class="label">Watcher Cycle</div><div class="val">#${d.w_cycle}</div></div>
    `;
    // positions
    const pb=document.getElementById('pos-body');
    if(d.positions.length===0){
      pb.innerHTML='<tr><td colspan="5" style="color:#8b949e;text-align:center;padding:12px">No open positions — scanning for signals...</td></tr>';
    } else {
      pb.innerHTML=d.positions.map(p=>{
        const cls=p.pnl.startsWith('+')?'pos':'neg';
        return `<tr><td><strong>${p.pair}</strong></td><td>${p.qty}</td><td>$${p.entry}</td><td>$${p.now}</td><td class="${cls}">${p.pnl}</td></tr>`;
      }).join('');
    }
    // watcher positions
    const wpb=document.getElementById('wpos-body');
    if(d.w_positions.length===0){
      wpb.innerHTML='<tr><td colspan="5" style="color:#3fb950;text-align:center;padding:12px">All demo positions closed!</td></tr>';
    } else {
      wpb.innerHTML=d.w_positions.map(p=>{
        const cls=p.pnl.startsWith('+')?'pos':'neg';
        return `<tr><td><strong>${p.pair}</strong></td><td>${p.qty}</td><td>$${p.entry}</td><td>$${p.now}</td><td class="${cls}">${p.pnl}</td></tr>`;
      }).join('');
    }
    // signals
    const tagMap={BUY:'tag-buy',SELL:'tag-sell',HOLD:'tag-hold'};
    document.getElementById('sig-body').innerHTML=d.signals.slice().reverse().map(s=>{
      const t=tagMap[s.action]||'tag-hold';
      const barW=Math.round(s.conf*1.4);
      const barC=s.action==='BUY'?'#3fb950':s.action==='SELL'?'#f85149':'#30363d';
      return `<tr><td style="color:#8b949e">${s.time}</td><td><strong>${s.pair}</strong></td>
        <td><span class="tag ${t}">${s.action}</span></td>
        <td>${s.conf}% <span class="conf-bar" style="width:${barW}px;background:${barC}"></span></td></tr>`;
    }).join('');
  }catch(e){console.error(e)}
}
refresh();
setInterval(refresh,3000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # silence access logs

    def do_GET(self):
        if self.path == "/api/status":
            data = json.dumps(parse_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("localhost", 5555), Handler)
    print("Dashboard running at http://localhost:5555  (Ctrl+C to stop)")
    server.serve_forever()
