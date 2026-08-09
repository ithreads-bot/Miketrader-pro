import requests
import time
import threading
import json
import os
from datetime import datetime
from collections import deque
import mike_config as config

AGENT_SCORECARD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_scores.json")

class MikeTrader:
    def __init__(self):
        self.running = False
        self.paused = False
        self.mode = config.TRADING_MODE
        self.capital = config.PAPER_CAPITAL if self.mode == "PAPER" else config.LIVE_CAPITAL
        self.positions = []
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.price_history = {c["symbol"]: deque(maxlen=50) for c in config.COINS}
        self.last_scan = "Never"
        self.benched_agents = set()
        self.agent_scores = self.load_agent_scores()
        self.agent_weights = self.calc_weights()
        
    def load_agent_scores(self):
        if os.path.exists(AGENT_SCORECARD_FILE):
            try:
                with open(AGENT_SCORECARD_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            "Trend": {"wins": 0, "losses": 0, "streak": 0, "total_pnl": 0.0},
            "Momentum": {"wins": 0, "losses": 0, "streak": 0, "total_pnl": 0.0},
            "Volatility": {"wins": 0, "losses": 0, "streak": 0, "total_pnl": 0.0},
            "SupportResist": {"wins": 0, "losses": 0, "streak": 0, "total_pnl": 0.0},
            "MeanReversion": {"wins": 0, "losses": 0, "streak": 0, "total_pnl": 0.0},
        }
    
    def save_agent_scores(self):
        with open(AGENT_SCORECARD_FILE, 'w') as f:
            json.dump(self.agent_scores, f, indent=2)
    
    def calc_weights(self):
        weights = {}
        for agent, scores in self.agent_scores.items():
            total = scores["wins"] + scores["losses"]
            if total < 3:
                weights[agent] = 1.0
            else:
                win_rate = scores["wins"] / total
                weights[agent] = 0.3 + (win_rate * 1.7)
            if scores["streak"] <= -5:
                self.benched_agents.add(agent)
                weights[agent] = 0.0
            elif scores["streak"] > -3 and agent in self.benched_agents:
                self.benched_agents.discard(agent)
        return weights
    
    def update_agent_scores(self, agents_used, trade_pnl):
        for agent in agents_used:
            if agent not in self.agent_scores:
                continue
            if trade_pnl > 0:
                self.agent_scores[agent]["wins"] += 1
                self.agent_scores[agent]["streak"] = max(1, self.agent_scores[agent]["streak"] + 1)
            else:
                self.agent_scores[agent]["losses"] += 1
                self.agent_scores[agent]["streak"] = min(-1, self.agent_scores[agent]["streak"] - 1)
            self.agent_scores[agent]["total_pnl"] += trade_pnl
        self.save_agent_scores()
        self.agent_weights = self.calc_weights()
    
    def start(self):
        self.running = True
        print(f"[{self.now()}] Bot STARTED in {self.mode} mode", flush=True)
        self.print_agent_scorecard()
        
    def stop(self):
        self.running = False
        print(f"[{self.now()}] Bot STOPPED", flush=True)
        
    def pause(self):
        self.paused = True
        print(f"[{self.now()}] Bot PAUSED", flush=True)
        
    def resume(self):
        self.paused = False
        print(f"[{self.now()}] Bot RESUMED", flush=True)
        
    def now(self):
        return datetime.now().strftime("%H:%M:%S")
    
    def fetch_all_prices(self):
        ids = ",".join([c["coingecko_id"] for c in config.COINS])
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        try:
            print(f"[{self.now()}] Fetching prices...", flush=True)
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            prices = {}
            for coin in config.COINS:
                cid = coin["coingecko_id"]
                if cid not in data:
                    continue
                coin_data = data[cid]
                if isinstance(coin_data, dict):
                    price = coin_data.get("usd")
                    change = coin_data.get("usd_24h_change", 0)
                else:
                    continue
                if price is None:
                    continue
                prices[coin["symbol"]] = {
                    "price": float(price),
                    "change_24h": float(change) if change is not None else 0
                }
                print(f"  {coin['symbol']}: ${price}", flush=True)
            print(f"[{self.now()}] Fetched {len(prices)}/{len(config.COINS)} prices", flush=True)
            return prices
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                print(f"[{self.now()}] RATE LIMITED. Waiting...", flush=True)
            else:
                print(f"[{self.now()}] HTTP Error {e.response.status_code}", flush=True)
            return {}
        except Exception as e:
            print(f"[{self.now()}] Price fetch error: {e}", flush=True)
            return {}
    
    def ema(self, prices, period):
        if len(prices) < period:
            return prices[-1] if prices else 0
        k = 2 / (period + 1)
        ema_val = sum(prices[:period]) / period
        for p in prices[period:]:
            ema_val = p * k + ema_val * (1 - k)
        return ema_val
    
    def analyze_pair(self, symbol, price_data):
        history = self.price_history[symbol]
        history.append(price_data["price"])
        if len(history) < 15:
            return {"score": 50, "signal": "HOLD", "agents": {}, "agents_used": []}
        prices = list(history)
        ema_fast = self.ema(prices, 5)
        ema_slow = self.ema(prices, 12)
        trend_raw = 85 if ema_fast > ema_slow * 1.002 else 15 if ema_fast < ema_slow * 0.998 else 50
        change = price_data["change_24h"] or 0
        momentum_raw = 85 if change > 3 else 70 if change > 1 else 30 if change < -1 else 15 if change < -3 else 50
        recent = prices[-10:]
        vol = (max(recent) - min(recent)) / min(recent) * 100 if min(recent) > 0 else 0
        vol_raw = 75 if vol > 2 else 50
        if max(recent) != min(recent):
            pos = (prices[-1] - min(recent)) / (max(recent) - min(recent))
            sr_raw = 85 if pos < 0.25 else 15 if pos > 0.75 else 50
        else:
            sr_raw = 50
        mean = sum(prices[-20:]) / len(prices[-20:])
        dev = (prices[-1] - mean) / mean * 100 if mean > 0 else 0
        mr_raw = 85 if dev < -2 else 15 if dev > 2 else 50
        raw_scores = {
            "Trend": trend_raw, "Momentum": momentum_raw,
            "Volatility": vol_raw, "SupportResist": sr_raw,
            "MeanReversion": mr_raw
        }
        weighted_scores = {}
        for agent, raw in raw_scores.items():
            w = self.agent_weights.get(agent, 1.0)
            if agent in self.benched_agents:
                weighted_scores[agent] = 50
            else:
                deviation = raw - 50
                weighted_scores[agent] = 50 + (deviation * w)
        avg_score = sum(weighted_scores.values()) / len(weighted_scores)
        if avg_score >= config.MIN_EDGE:
            signal = "BUY"
            agents_used = [a for a, s in weighted_scores.items() if s > 60]
        elif avg_score <= (100 - config.MIN_EDGE):
            signal = "SELL"
            agents_used = [a for a, s in weighted_scores.items() if s < 40]
        else:
            signal = "HOLD"
            agents_used = []
        return {
            "score": avg_score, "signal": signal,
            "agents": weighted_scores, "agents_used": agents_used,
            "raw_agents": raw_scores
        }
    
    def run_scan(self):
        print(f"\n{'='*60}", flush=True)
        print(f"[{self.now()}] MARKET SCAN", flush=True)
        prices = self.fetch_all_prices()
        if not prices:
            print(f"[{self.now()}] No price data", flush=True)
            return
        self.last_scan = self.now()
        signals = []
        for coin in config.COINS:
            sym = coin["symbol"]
            if sym not in prices:
                continue
            analysis = self.analyze_pair(sym, prices[sym])
            price = prices[sym]["price"]
            emoji = "BUY" if analysis["signal"] == "BUY" else "SELL" if analysis["signal"] == "SELL" else "HOLD"
            print(f"{emoji} {sym:10s} ${price:>10.4f} | Score: {analysis['score']:>5.1f} | {analysis['signal']}", flush=True)
            for agent, score in analysis["agents"].items():
                w = self.agent_weights.get(agent, 1.0)
                status = "B" if agent in self.benched_agents else " "
                print(f"      {status}{agent:15s} {score:.0f} (w:{w:.1f})", flush=True)
            if analysis["signal"] in ["BUY", "SELL"]:
                signals.append({
                    "symbol": sym, "price": price, "signal": analysis["signal"],
                    "score": analysis["score"], "agents": analysis["agents"],
                    "agents_used": analysis["agents_used"]
                })
        if self.mode in ["PAPER", "AUTO"] and signals:
            self.execute_paper_trades(signals)
        self.update_positions(prices)
        self.print_status()
        print(f"{'='*60}\n", flush=True)
    
    def execute_paper_trades(self, signals):
        for pos in self.positions[:]:
            for sig in signals:
                if pos["symbol"] == sig["symbol"] and pos["direction"] != sig["signal"]:
                    self.close_position(pos, sig["price"], "Signal Reversed")
                    break
        open_count = len(self.positions)
        for sig in sorted(signals, key=lambda x: abs(x["score"]-50), reverse=True):
            if open_count >= config.MAX_POSITIONS:
                break
            if any(p["symbol"] == sig["symbol"] for p in self.positions):
                continue
            size = self.capital * config.POSITION_SIZE_PCT
            if size < 1.0:
                continue
            pos = {
                "symbol": sig["symbol"], "entry": sig["price"],
                "direction": sig["signal"], "size": size,
                "opened": self.now(), "pnl": 0.0, "current": sig["price"],
                "agents_used": sig["agents_used"]
            }
            self.positions.append(pos)
            open_count += 1
            agent_str = ", ".join(sig["agents_used"]) if sig["agents_used"] else "Consensus"
            print(f"[{self.now()}] PAPER: {sig['signal']} {sig['symbol']} @ ${sig['price']:,.4f} | Agents: {agent_str}", flush=True)
    
    def update_positions(self, prices):
        for pos in self.positions[:]:
            sym = pos["symbol"]
            if sym not in prices:
                continue
            current = prices[sym]["price"]
            if pos["direction"] == "BUY":
                pnl_pct = (current - pos["entry"]) / pos["entry"] * 100
            else:
                pnl_pct = (pos["entry"] - current) / pos["entry"] * 100
            pos["pnl"] = pos["size"] * (pnl_pct / 100)
            pos["current"] = current
            if pnl_pct <= -config.STOP_LOSS_PCT:
                self.close_position(pos, current, f"Stop Loss ({pnl_pct:.1f}%)")
            elif pnl_pct >= config.TAKE_PROFIT_PCT:
                self.close_position(pos, current, f"Take Profit (+{pnl_pct:.1f}%)")
    
    def close_position(self, pos, exit_price, reason):
        pnl = pos["pnl"]
        self.capital += pnl
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.positions.remove(pos)
        agents_used = pos.get("agents_used", [])
        self.update_agent_scores(agents_used, pnl)
        print(f"[{self.now()}] CLOSED: {pos['symbol']} | P&L: ${pnl:+.2f} | {reason}", flush=True)
    
    def print_status(self):
        print(f"\nCapital: ${self.capital:.2f} | Daily: ${self.daily_pnl:+.2f} | Total: ${self.total_pnl:+.2f}", flush=True)
        print(f"Open: {len(self.positions)}/{config.MAX_POSITIONS}", flush=True)
        for pos in self.positions:
            print(f"   {pos['symbol']} {pos['direction']} | Entry: ${pos['entry']:,.4f} | Now: ${pos['current']:,.4f} | P&L: ${pos['pnl']:+.2f}", flush=True)
    
    def print_agent_scorecard(self):
        print(f"\n{'='*60}", flush=True)
        print("AGENT SCORECARD", flush=True)
        for agent, scores in self.agent_scores.items():
            total = scores["wins"] + scores["losses"]
            if total > 0:
                wr = scores["wins"] / total * 100
                status = "BENCHED" if agent in self.benched_agents else f"w:{self.agent_weights.get(agent, 1.0):.1f}"
                print(f"  {agent:15s} {scores['wins']}W/{scores['losses']}L ({wr:.0f}%) | Streak: {scores['streak']:+d} | P&L: ${scores['total_pnl']:+.2f} | {status}", flush=True)
            else:
                print(f"  {agent:15s} No trades yet | w:1.0", flush=True)
        print(f"{'='*60}\n", flush=True)
    
    def get_agent_data(self):
        result = []
        for agent, scores in self.agent_scores.items():
            total = scores["wins"] + scores["losses"]
            wr = (scores["wins"] / total * 100) if total > 0 else 0
            result.append({
                "name": agent, "wins": scores["wins"], "losses": scores["losses"],
                "win_rate": round(wr, 1), "streak": scores["streak"],
                "pnl": round(scores["total_pnl"], 2),
                "weight": round(self.agent_weights.get(agent, 1.0), 2),
                "benched": agent in self.benched_agents
            })
        return result