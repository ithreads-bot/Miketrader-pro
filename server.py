from flask import Flask, render_template_string, jsonify, request
import threading
import time
import sys
import os
from datetime import datetime
import socket

import mike_config as config
from trader import MikeTrader

app = Flask(__name__)
bot = MikeTrader()
auto_thread = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Mike Trader Pro Cloud</title>
    <style>
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e1a; color: #e0e6ed; margin: 0; padding: 12px;
            touch-action: manipulation;
        }
        .header { text-align: center; padding: 8px 0; border-bottom: 2px solid #1a2332; margin-bottom: 12px; }
        .header h1 { margin: 0; color: #00d4ff; font-size: 1.3em; }
        .status-bar { 
            display: flex; justify-content: space-around; background: #111827; 
            padding: 10px; border-radius: 10px; margin-bottom: 12px; flex-wrap: wrap;
        }
        .stat { text-align: center; padding: 4px; min-width: 65px; }
        .stat-value { font-size: 1.1em; font-weight: bold; color: #00d4ff; }
        .stat-label { font-size: 0.65em; color: #8899aa; margin-top: 2px; }
        .mode-section, .control-section, .log-section, .agent-section { 
            background: #111827; padding: 12px; border-radius: 10px; margin-bottom: 12px; 
        }
        .section-title { text-align: center; margin-bottom: 10px; color: #8899aa; font-size: 0.8em; font-weight: bold; }
        .mode-buttons, .control-buttons { display: flex; gap: 8px; justify-content: center; }
        .mode-btn, .ctrl-btn {
            flex: 1; padding: 12px 4px; border-radius: 8px; font-weight: bold;
            font-size: 0.75em; cursor: pointer; -webkit-appearance: none; border: 2px solid #334455;
            background: #1a2332; color: #8899aa;
        }
        .mode-btn.active-signal { border-color: #ffd700; color: #ffd700; box-shadow: 0 0 8px rgba(255,215,0,0.3); }
        .mode-btn.active-paper { border-color: #00ff88; color: #00ff88; box-shadow: 0 0 8px rgba(0,255,136,0.3); }
        .mode-btn.active-auto { border-color: #ff4444; color: #ff4444; box-shadow: 0 0 8px rgba(255,68,68,0.3); animation: pulse 2s infinite; }
        @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.6;} }
        .ctrl-btn { border: none; color: white; }
        .start { background: #00aa44; }
        .stop { background: #aa2222; }
        .pause { background: #ff8800; }
        .resume { background: #0066cc; }
        .ctrl-btn:disabled { opacity: 0.4; }
        .log-section { height: 220px; overflow-y: auto; -webkit-overflow-scrolling: touch; }
        .log-entry { font-family: monospace; font-size: 0.72em; line-height: 1.4; color: #ccd6e0; white-space: pre-wrap; word-break: break-word; }
        .current-mode { text-align: center; margin-top: 6px; font-weight: bold; font-size: 0.9em; }
        .agent-card {
            background: #1a2332; border-radius: 8px; padding: 8px; margin-bottom: 8px;
            border-left: 4px solid #334455;
        }
        .agent-card.hot { border-left-color: #00ff88; }
        .agent-card.cold { border-left-color: #ff4444; }
        .agent-card.benched { border-left-color: #555; opacity: 0.5; }
        .agent-name { font-weight: bold; font-size: 0.85em; }
        .agent-stats { font-size: 0.75em; color: #8899aa; margin-top: 3px; }
        .agent-bar-bg { background: #0a0e1a; height: 6px; border-radius: 3px; margin-top: 5px; overflow: hidden; }
        .agent-bar { height: 100%; border-radius: 3px; transition: width 0.5s; }
        .win-rate-good { color: #00ff88; }
        .win-rate-bad { color: #ff4444; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚡ MIKE TRADER PRO CLOUD</h1>
        <div class="current-mode" id="currentMode">⚡ MODE: {{mode}} ⚡</div>
    </div>
    
    <div class="status-bar">
        <div class="stat"><div class="stat-value" id="status">{{status}}</div><div class="stat-label">Status</div></div>
        <div class="stat"><div class="stat-value" id="capital">${{capital}}</div><div class="stat-label">Capital</div></div>
        <div class="stat"><div class="stat-value" id="daily">${{daily}}</div><div class="stat-label">Daily P&L</div></div>
        <div class="stat"><div class="stat-value" id="positions">{{positions}}</div><div class="stat-label">Positions</div></div>
    </div>
    
    <div class="mode-section">
        <div class="section-title">🎚️ TRADING MODE</div>
        <div class="mode-buttons">
            <button type="button" class="mode-btn {{'active-signal' if mode=='SIGNAL' else ''}}" onclick="setMode('SIGNAL')">📡 SIGNAL</button>
            <button type="button" class="mode-btn {{'active-paper' if mode=='PAPER' else ''}}" onclick="setMode('PAPER')">📊 PAPER</button>
            <button type="button" class="mode-btn {{'active-auto' if mode=='AUTO' else ''}}" onclick="setMode('AUTO')">🔴 AUTO</button>
        </div>
    </div>
    
    <div class="control-section">
        <div class="section-title">🎮 CONTROLS</div>
        <div class="control-buttons">
            <button type="button" class="ctrl-btn start" onclick="sendCmd('start')">▶️ START</button>
            <button type="button" class="ctrl-btn stop" onclick="sendCmd('stop')">⏹️ STOP</button>
            <button type="button" class="ctrl-btn pause" onclick="sendCmd('pause')">⏸️ PAUSE</button>
            <button type="button" class="ctrl-btn resume" onclick="sendCmd('resume')">▶️ RESUME</button>
        </div>
    </div>
    
    <div class="agent-section">
        <div class="section-title">🧠 AGENT SCORECARD (Auto-Optimizing)</div>
        <div id="agentCards"></div>
    </div>
    
    <div class="log-section" id="logBox">
        <div class="section-title">📋 ACTIVITY LOG</div>
        <div class="log-entry" id="logs">{{logs}}</div>
    </div>
    
    <script>
        let logs = [];
        function addLog(msg) {
            logs.push(msg);
            if (logs.length > 40) logs.shift();
            document.getElementById('logs').innerHTML = logs.join('\\n');
            document.getElementById('logBox').scrollTop = 999999;
        }
        
        async function sendCmd(cmd) {
            event.preventDefault(); event.stopPropagation();
            try {
                const r = await fetch('/api/' + cmd, {method: 'POST'});
                const d = await r.json();
                addLog(new Date().toLocaleTimeString() + ' — ' + d.message);
                updateStatus();
            } catch(e) { addLog('Error: ' + e); }
        }
        
        async function setMode(m) {
            event.preventDefault(); event.stopPropagation();
            try {
                const r = await fetch('/api/mode/' + m, {method: 'POST'});
                const d = await r.json();
                addLog(new Date().toLocaleTimeString() + ' — Mode: ' + m);
                updateStatus();
            } catch(e) { addLog('Error: ' + e); }
        }
        
        function renderAgents(agents) {
            let html = '';
            agents.forEach(a => {
                let cls = a.benched ? 'benched' : (a.win_rate >= 55 ? 'hot' : (a.win_rate < 45 && a.wins + a.losses > 5 ? 'cold' : ''));
                let wrCls = a.win_rate >= 55 ? 'win-rate-good' : (a.win_rate < 45 ? 'win-rate-bad' : '');
                let streakEmoji = a.streak >= 3 ? '🔥' : (a.streak <= -3 ? '❄️' : '');
                let barColor = a.win_rate >= 55 ? '#00ff88' : (a.win_rate < 45 ? '#ff4444' : '#8899aa');
                let status = a.benched ? '🚫 BENCHED' : `⚖️ Weight: ${a.weight}x`;
                
                html += `<div class="agent-card ${cls}">
                    <div class="agent-name">${a.name} ${streakEmoji}</div>
                    <div class="agent-stats">
                        <span class="${wrCls}">${a.wins}W / ${a.losses}L (${a.win_rate}%)</span> | 
                        Streak: ${a.streak > 0 ? '+' : ''}${a.streak} | 
                        P&L: $${a.pnl.toFixed(2)} | 
                        ${status}
                    </div>
                    <div class="agent-bar-bg"><div class="agent-bar" style="width:${a.win_rate}%; background:${barColor}"></div></div>
                </div>`;
            });
            document.getElementById('agentCards').innerHTML = html;
        }
        
        async function updateStatus() {
            try {
                const r = await fetch('/api/status');
                const d = await r.json();
                document.getElementById('status').innerText = d.status;
                document.getElementById('capital').innerText = '$' + d.capital.toFixed(2);
                document.getElementById('daily').innerText = '$' + d.daily_pnl.toFixed(2);
                document.getElementById('positions').innerText = d.positions;
                document.getElementById('currentMode').innerText = '⚡ MODE: ' + d.mode + ' ⚡';
                if (d.agents) renderAgents(d.agents);
            } catch(e) {}
        }
        setInterval(updateStatus, 2000);
        updateStatus();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    status = "RUNNING" if bot.running else "STOPPED"
    if bot.running and bot.paused: status = "PAUSED"
    return render_template_string(HTML_TEMPLATE,
        mode=bot.mode, status=status, capital=bot.capital,
        daily=bot.daily_pnl, positions=len(bot.positions), logs="Ready...")

@app.route("/api/status")
def api_status():
    status = "RUNNING" if bot.running else "STOPPED"
    if bot.running and bot.paused: status = "PAUSED"
    return jsonify({
        "status": status, "mode": bot.mode, "capital": bot.capital,
        "daily_pnl": bot.daily_pnl, "total_pnl": bot.total_pnl,
        "positions": len(bot.positions), "last_scan": bot.last_scan,
        "agents": bot.get_agent_data()
    })

@app.route("/api/start", methods=["POST"])
def api_start():
    if not bot.running:
        bot.start()
        start_auto_loop()
    return jsonify({"message": "Bot STARTED"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    bot.stop()
    return jsonify({"message": "Bot STOPPED"})

@app.route("/api/pause", methods=["POST"])
def api_pause():
    bot.pause()
    return jsonify({"message": "Bot PAUSED"})

@app.route("/api/resume", methods=["POST"])
def api_resume():
    bot.resume()
    return jsonify({"message": "Bot RESUMED"})

@app.route("/api/mode/<mode>", methods=["POST"])
def api_mode(mode):
    if mode in ["SIGNAL", "PAPER", "AUTO"]:
        bot.mode = mode
        if mode == "PAPER": bot.capital = config.PAPER_CAPITAL
        elif mode == "AUTO": bot.capital = config.LIVE_CAPITAL
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Mode switched to {mode}", flush=True)
        return jsonify({"message": f"Mode: {mode}"})
    return jsonify({"error": "Invalid"}), 400

def auto_loop():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-loop thread started", flush=True)
    scan_count = 0
    while True:
        try:
            if bot.running and not bot.paused:
                scan_count += 1
                label = "PAPER/AUTO TRADE" if bot.mode in ["PAPER","AUTO"] else "SIGNAL"
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🔄 {label} scan #{scan_count}", flush=True)
                bot.run_scan()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 😴 Sleeping {config.SCAN_INTERVAL}s...\n", flush=True)
            else:
                reason = "STOPPED" if not bot.running else "PAUSED"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Bot {reason}, waiting...", flush=True)
            time.sleep(config.SCAN_INTERVAL)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Auto-loop error: {e}", flush=True)
            time.sleep(10)

def start_auto_loop():
    global auto_thread
    if auto_thread is None or not auto_thread.is_alive():
        auto_thread = threading.Thread(target=auto_loop, daemon=True)
        auto_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Mike Trader Pro Cloud starting...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)