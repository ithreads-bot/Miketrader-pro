# web/server.py — Mike Trader Pro Cloud Dashboard (FIXED)
# ========================================================

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template_string
from trader import state, start, stop, pause, resume, set_mode
import threading

app = Flask(__name__)

# ─── HTML Template ───
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Mike Trader Pro Cloud</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 16px;
            max-width: 600px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            color: #58a6ff;
            font-size: 1.3em;
            margin-bottom: 4px;
        }
        .subtitle {
            text-align: center;
            color: #8b949e;
            font-size: 0.8em;
            margin-bottom: 16px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 16px;
        }
        .stat-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 12px;
            text-align: center;
        }
        .stat-value {
            font-size: 1.4em;
            font-weight: bold;
            color: #58a6ff;
        }
        .stat-label {
            font-size: 0.7em;
            color: #8b949e;
            margin-top: 4px;
        }
        .status-running { color: #3fb950 !important; }
        .status-stopped { color: #f85149 !important; }
        .status-paused { color: #d29922 !important; }

        .mode-section {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 16px;
        }
        .mode-section h3 {
            text-align: center;
            font-size: 0.85em;
            color: #8b949e;
            margin-bottom: 10px;
        }
        .mode-buttons {
            display: flex;
            gap: 8px;
        }
        .mode-btn {
            flex: 1;
            padding: 10px;
            border: 1px solid #30363d;
            border-radius: 8px;
            background: #21262d;
            color: #c9d1d9;
            font-size: 0.8em;
            cursor: pointer;
            text-align: center;
        }
        .mode-btn.active {
            border-color: #58a6ff;
            background: #1f6feb22;
            color: #58a6ff;
        }
        .mode-btn.signal-active { border-color: #d29922; background: #d2992222; color: #d29922; }
        .mode-btn.paper-active { border-color: #3fb950; background: #3fb95022; color: #3fb950; }
        .mode-btn.auto-active { border-color: #f85149; background: #f8514922; color: #f85149; }

        .controls-section {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 16px;
        }
        .controls-section h3 {
            text-align: center;
            font-size: 0.85em;
            color: #8b949e;
            margin-bottom: 10px;
        }
        .control-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }
        .ctrl-btn {
            padding: 12px;
            border: none;
            border-radius: 8px;
            font-size: 0.9em;
            font-weight: bold;
            cursor: pointer;
            color: white;
        }
        .btn-start { background: #238636; }
        .btn-stop { background: #da3633; }
        .btn-pause { background: #d29922; }
        .btn-resume { background: #1f6feb; }
        .ctrl-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        .agents-section {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 16px;
        }
        .agents-section h3 {
            text-align: center;
            font-size: 0.85em;
            color: #8b949e;
            margin-bottom: 10px;
        }
        .agent-card {
            background: #21262d;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 8px;
        }
        .agent-name {
            font-weight: bold;
            font-size: 0.9em;
            margin-bottom: 4px;
        }
        .agent-stats {
            font-size: 0.75em;
            color: #8b949e;
        }
        .agent-stats .win { color: #3fb950; }
        .agent-stats .loss { color: #f85149; }
        .agent-bar {
            height: 4px;
            background: #30363d;
            border-radius: 2px;
            margin-top: 6px;
            overflow: hidden;
        }
        .agent-bar-fill {
            height: 100%;
            background: #58a6ff;
            border-radius: 2px;
            transition: width 0.3s;
        }

        .logs-section {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 12px;
        }
        .logs-section h3 {
            text-align: center;
            font-size: 0.85em;
            color: #8b949e;
            margin-bottom: 10px;
        }
        .log-entry {
            font-size: 0.7em;
            color: #8b949e;
            padding: 3px 0;
            border-bottom: 1px solid #21262d;
            font-family: monospace;
        }
        .log-entry:last-child { border-bottom: none; }

        .info-bar {
            text-align: center;
            font-size: 0.7em;
            color: #484f58;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #21262d;
        }
    </style>
</head>
<body>
    <h1>⚡ MIKE TRADER PRO CLOUD</h1>
    <div class="subtitle" id="mode-display">⚡ MODE: PAPER ⚡</div>

    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value" id="status">STOPPED</div>
            <div class="stat-label">Status</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="capital">$1000.00</div>
            <div class="stat-label">Capital</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="daily-pl">$0.00</div>
            <div class="stat-label">Daily P&L</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="positions">0</div>
            <div class="stat-label">Positions</div>
        </div>
    </div>

    <div class="mode-section">
        <h3>📊 TRADING MODE</h3>
        <div class="mode-buttons">
            <button class="mode-btn" id="btn-signal" onclick="setMode('SIGNAL')">📡 SIGNAL</button>
            <button class="mode-btn" id="btn-paper" onclick="setMode('PAPER')">📊 PAPER</button>
            <button class="mode-btn" id="btn-auto" onclick="setMode('AUTO')">🔴 AUTO</button>
        </div>
    </div>

    <div class="controls-section">
        <h3>🎮 CONTROLS</h3>
        <div class="control-buttons">
            <button class="ctrl-btn btn-start" id="btn-start" onclick="controlBot('start')">▶️ START</button>
            <button class="ctrl-btn btn-stop" id="btn-stop" onclick="controlBot('stop')">⏹️ STOP</button>
            <button class="ctrl-btn btn-pause" id="btn-pause" onclick="controlBot('pause')">⏸️ PAUSE</button>
            <button class="ctrl-btn btn-resume" id="btn-resume" onclick="controlBot('resume')">▶️ RESUME</button>
        </div>
    </div>

    <div class="agents-section">
        <h3>🧠 AGENT SCORECARD (Auto-Optimizing)</h3>
        <div id="agents-container"></div>
    </div>

    <div class="logs-section">
        <h3>📋 ACTIVITY LOG</h3>
        <div id="logs-container"></div>
    </div>

    <div class="info-bar">
        Mike Trader Pro v5.4 | Cloud Edition | Auto-Refresh: 3s
    </div>

    <script>
        let currentStatus = "STOPPED";
        let currentMode = "PAPER";

        async function updateDashboard() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();

                currentStatus = data.status;
                currentMode = data.mode;

                // Update stats
                const statusEl = document.getElementById('status');
                statusEl.textContent = data.status;
                statusEl.className = 'stat-value';
                if (data.status === 'RUNNING') statusEl.classList.add('status-running');
                else if (data.status === 'STOPPED') statusEl.classList.add('status-stopped');
                else statusEl.classList.add('status-paused');

                document.getElementById('capital').textContent = '$' + data.capital.toFixed(2);
                document.getElementById('daily-pl').textContent = (data.daily_pl >= 0 ? '+' : '') + '$' + data.daily_pl.toFixed(2);
                document.getElementById('daily-pl').style.color = data.daily_pl >= 0 ? '#3fb950' : '#f85149';
                document.getElementById('positions').textContent = data.positions + '/' + data.max_positions;

                // Update mode display
                document.getElementById('mode-display').textContent = '⚡ MODE: ' + data.mode + ' ⚡';

                // Update mode buttons
                document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.remove('active', 'signal-active', 'paper-active', 'auto-active'));
                if (data.mode === 'SIGNAL') document.getElementById('btn-signal').classList.add('active', 'signal-active');
                else if (data.mode === 'PAPER') document.getElementById('btn-paper').classList.add('active', 'paper-active');
                else if (data.mode === 'AUTO') document.getElementById('btn-auto').classList.add('active', 'auto-active');

                // Update agents
                const agentsContainer = document.getElementById('agents-container');
                agentsContainer.innerHTML = '';
                for (const [name, stats] of Object.entries(data.agents)) {
                    const winRate = stats.win_rate || 0;
                    const barWidth = Math.min(winRate, 100);
                    const barColor = winRate > 50 ? '#3fb950' : (winRate > 30 ? '#d29922' : '#f85149');

                    const div = document.createElement('div');
                    div.className = 'agent-card';
                    div.innerHTML = `
                        <div class="agent-name">${name}</div>
                        <div class="agent-stats">
                            <span class="win">${stats.wins}W</span> / 
                            <span class="loss">${stats.losses}L</span> 
                            (${winRate}%) | Streak: ${stats.streak} | P&L: $${stats.pl.toFixed(2)} | ⚖️ Weight: ${stats.weight}x
                        </div>
                        <div class="agent-bar">
                            <div class="agent-bar-fill" style="width: ${barWidth}%; background: ${barColor};"></div>
                        </div>
                    `;
                    agentsContainer.appendChild(div);
                }

                // Update logs
                const logsContainer = document.getElementById('logs-container');
                logsContainer.innerHTML = '';
                (data.logs || []).forEach(log => {
                    const div = document.createElement('div');
                    div.className = 'log-entry';
                    div.textContent = log;
                    logsContainer.appendChild(div);
                });

            } catch (e) {
                console.error('Update error:', e);
            }
        }

        async function controlBot(action) {
            try {
                const resp = await fetch('/api/' + action, {method: 'POST'});
                const data = await resp.json();
                console.log(action + ':', data);
                updateDashboard();
            } catch (e) {
                console.error('Control error:', e);
            }
        }

        async function setMode(mode) {
            try {
                const resp = await fetch('/api/mode/' + mode, {method: 'POST'});
                const data = await resp.json();
                console.log('Mode:', data);
                updateDashboard();
            } catch (e) {
                console.error('Mode error:', e);
            }
        }

        // Initial load and auto-refresh
        updateDashboard();
        setInterval(updateDashboard, 3000);
    </script>
</body>
</html>
"""

# ─── Auto-start bot when server loads ───
print("🚀 Starting Mike Trader Pro Cloud...")
start()

# ─── Routes ───
@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route("/api/status")
def status():
    return jsonify(state.get_status_dict())

@app.route("/api/start", methods=["POST"])
def api_start():
    return jsonify(start())

@app.route("/api/stop", methods=["POST"])
def api_stop():
    return jsonify(stop())

@app.route("/api/pause", methods=["POST"])
def api_pause():
    return jsonify(pause())

@app.route("/api/resume", methods=["POST"])
def api_resume():
    return jsonify(resume())

@app.route("/api/mode/<mode>", methods=["POST"])
def api_mode(mode):
    return jsonify(set_mode(mode))

# ─── Run ───
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
