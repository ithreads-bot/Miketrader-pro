# trader.py — Mike Trader Pro Cloud (FIXED NoneType ERROR)
# =========================================================

import requests
import time
import random
import threading
from datetime import datetime
from collections import deque

from mike_config import *

class BotState:
    def __init__(self):
        self.status = "STOPPED"
        self.mode = TRADING_MODE
        self.capital = PAPER_CAPITAL if TRADING_MODE == "PAPER" else REAL_CAPITAL
        self.daily_pl = 0.0
        self.total_pl = 0.0
        self.positions = []
        self.trade_history = []
        self.agent_scores = {}
        self.agent_weights = AGENT_WEIGHTS.copy()
        self.price_history = {}
        self.scan_count = 0
        self.last_trade_time = None
        self.daily_loss = 0.0
        self.logs = deque(maxlen=200)
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {msg}"
        self.logs.append(entry)
        if VERBOSE:
            print(entry)

    def get_status_dict(self):
        with self.lock:
            return {
                "status": self.status,
                "mode": self.mode,
                "capital": round(self.capital, 2),
                "daily_pl": round(self.daily_pl, 2),
                "total_pl": round(self.total_pl, 2),
                "positions": len(self.positions),
                "max_positions": MAX_POSITIONS,
                "scan_count": self.scan_count,
                "daily_loss": round(self.daily_loss, 2),
                "logs": list(self.logs)[-20:],
                "agents": self.get_agent_summary(),
                "last_trade": self.last_trade_time or "Never"
            }

    def get_agent_summary(self):
        summary = {}
        for name in ["Trend", "Momentum", "Volatility", "SupportResist", "MeanReversion"]:
            scores = self.agent_scores.get(name, {"wins": 0, "losses": 0, "pl": 0.0, "streak": 0})
            total = scores.get("wins", 0) + scores.get("losses", 0)
            win_rate = (scores["wins"] / total * 100) if total > 0 else 0
            weight = self.agent_weights.get(name, 1.0)
            summary[name] = {
                "wins": scores.get("wins", 0),
                "losses": scores.get("losses", 0),
                "win_rate": round(win_rate, 1),
                "pl": round(scores.get("pl", 0.0), 2),
                "streak": scores.get("streak", 0),
                "weight": round(weight, 2)
            }
        return summary

state = BotState()

def fetch_prices():
    try:
        ids = ",".join(COINS)
        url = f"{COINGECKO_API_URL}/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            prices = {}
            for coin in COINS:
                if coin in data and "usd" in data[coin]:
                    prices[coin] = {
                        "price": data[coin]["usd"],
                        "change_24h": data[coin].get("usd_24h_change", 0) or 0
                    }
            return prices
        elif resp.status_code == 429:
            state.log("⚠️ Rate limit — waiting...")
            time.sleep(30)
            return {}
        else:
            return {}
    except Exception as e:
        state.log(f"⚠️ Error: {e}")
        return {}

def compute_agent_scores(prices):
    signals = {}
    for coin, data in prices.items():
        price = data["price"]
        change_24h = data.get("change_24h", 0) or 0
        
        if coin not in state.price_history:
            state.price_history[coin] = deque(maxlen=100)
        state.price_history[coin].append(price)
        hist = list(state.price_history[coin])
        
        trend_score = 50
        trend_dir = "NEUTRAL"
        if abs(change_24h) > 1:
            trend_score = 55 + min(abs(change_24h) * 2, 30)
            trend_dir = "UP" if change_24h > 0 else "DOWN"
        
        mom_score = 50
        mom_dir = "NEUTRAL"
        if len(hist) >= 3:
            recent = ((hist[-1] - hist[-3]) / hist[-3]) * 100 if hist[-3] != 0 else 0
            if abs(recent) > 0.2:
                mom_score = 55 + min(abs(recent) * 10, 30)
                mom_dir = "UP" if recent > 0 else "DOWN"
        elif abs(change_24h) > 0.5:
            mom_score = 52 + min(abs(change_24h), 15)
            mom_dir = "UP" if change_24h > 0 else "DOWN"
        
        vol_score = 50
        vol_dir = "NEUTRAL"
        if abs(change_24h) > 2:
            vol_score = 58 + min(abs(change_24h), 25)
            vol_dir = "UP" if change_24h > 0 else "DOWN"
        elif abs(change_24h) > 0.5:
            vol_score = 52 + min(abs(change_24h) * 2, 10)
            vol_dir = "UP" if change_24h > 0 else "DOWN"
        
        sr_score = 50
        sr_dir = "NEUTRAL"
        if len(hist) >= 5:
            recent = hist[-5:]
            high, low = max(recent), min(recent)
            if high > low:
                pos = (price - low) / (high - low)
                if pos > 0.8 and change_24h < 0:
                    sr_score = 58; sr_dir = "DOWN"
                elif pos < 0.2 and change_24h > 0:
                    sr_score = 58; sr_dir = "UP"
        
        mr_score = 50
        mr_dir = "NEUTRAL"
        if len(hist) >= 5:
            avg = sum(hist[-5:]) / 5
            if avg > 0:
                dev = ((price - avg) / avg) * 100
                if abs(dev) > 0.3:
                    mr_score = 55 + min(abs(dev) * 5, 25)
                    mr_dir = "DOWN" if dev > 0 else "UP"
        
        signals[coin] = {
            "price": price,
            "change_24h": change_24h,
            "agents": {
                "Trend": {"score": int(trend_score), "dir": trend_dir},
                "Momentum": {"score": int(mom_score), "dir": mom_dir},
                "Volatility": {"score": int(vol_score), "dir": vol_dir},
                "SupportResist": {"score": int(sr_score), "dir": sr_dir},
                "MeanReversion": {"score": int(mr_score), "dir": mr_dir}
            }
        }
    return signals

def get_consensus(signals):
    trades = []
    for coin, data in signals.items():
        agents = data["agents"]
        up_votes = down_votes = 0
        up_score = down_score = 0
        total_score = 0
        
        for name, info in agents.items():
            w = state.agent_weights.get(name, 1.0)
            total_score += info["score"] * w
            if info["dir"] == "UP":
                up_votes += w; up_score += info["score"] * w
            elif info["dir"] == "DOWN":
                down_votes += w; down_score += info["score"] * w
        
        tw = sum(state.agent_weights.values())
        avg_score = total_score / tw if tw > 0 else 50
        
        if up_votes > down_votes * 1.05:
            direction = "UP"
            edge = (up_score / up_votes) * (up_votes / tw) if up_votes > 0 else 0
        elif down_votes > up_votes * 1.05:
            direction = "DOWN"
            edge = (down_score / down_votes) * (down_votes / tw) if down_votes > 0 else 0
        else:
            direction = "NEUTRAL"
            edge = 0
        
        if edge >= MIN_EDGE and avg_score >= MIN_CONFIDENCE and direction != "NEUTRAL":
            trades.append({
                "coin": coin,
                "symbol": COIN_SYMBOLS.get(coin, coin.upper()),
                "price": data["price"],
                "direction": direction,
                "edge": round(edge, 1),
                "confidence": round(avg_score, 1),
                "change_24h": data["change_24h"],
                "agents": agents
            })
    
    trades.sort(key=lambda x: x["edge"], reverse=True)
    return trades

def execute_paper_trade(trade):
    symbol = trade["symbol"]
    direction = trade["direction"]
    price = trade["price"]
    position_size = (state.capital * POSITION_SIZE_PCT) / 100
    
    if len(state.positions) >= MAX_POSITIONS:
        return False
    if state.daily_loss >= DAILY_LOSS_LIMIT:
        return False
    if state.total_pl <= -TOTAL_LOSS_LIMIT:
        return False
    
    leading = max(trade["agents"], key=lambda k: trade["agents"][k]["score"])
    
    position = {
        "id": len(state.trade_history) + len(state.positions) + 1,
        "symbol": symbol,
        "direction": direction,
        "entry_price": price,
        "current_price": price,
        "size": position_size,
        "stop_loss": price * (1 - STOP_LOSS_PCT/100) if direction == "UP" else price * (1 + STOP_LOSS_PCT/100),
        "take_profit": price * (1 + TAKE_PROFIT_PCT/100) if direction == "UP" else price * (1 - TAKE_PROFIT_PCT/100),
        "entry_time": datetime.now(),
        "edge": trade["edge"],
        "leading_agent": leading,
        "change_24h_at_entry": trade["change_24h"]
    }
    
    state.positions.append(position)
    state.last_trade_time = datetime.now().strftime("%H:%M:%S")
    
    emoji = "📈" if direction == "UP" else "📉"
    state.log(f"{emoji} TRADE #{position['id']}: {symbol} {direction} @ ${price:.4f} | Size: ${position_size:.2f} | Edge: {trade['edge']:.1f} | 24h: {trade['change_24h']:+.2f}%")
    return True

def check_positions(prices):
    closed = []
    for pos in state.positions[:]:
        symbol = pos["symbol"]
        coin = None
        for c, s in COIN_SYMBOLS.items():
            if s == symbol:
                coin = c; break
        
        if coin not in prices:
            continue
        
        current_price = prices[coin]["price"]
        pos["current_price"] = current_price
        direction = pos["direction"]
        entry = pos["entry_price"]
        size = pos["size"]
        
        if direction == "UP":
            pnl_pct = ((current_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current_price) / entry) * 100
        
        pnl_dollar = size * (pnl_pct / 100)
        
        if pnl_pct <= -STOP_LOSS_PCT:
            state.log(f"🛑 STOP LOSS: {symbol} @ ${current_price:.4f} | Loss: ${abs(pnl_dollar):.2f}")
            close_position(pos, pnl_dollar, "STOP_LOSS")
            closed.append(pos)
        elif pnl_pct >= TAKE_PROFIT_PCT:
            state.log(f"🎯 TAKE PROFIT: {symbol} @ ${current_price:.4f} | Profit: ${pnl_dollar:.2f}")
            close_position(pos, pnl_dollar, "TAKE_PROFIT")
            closed.append(pos)
    
    return closed

def close_position(pos, pnl_dollar, reason):
    state.positions.remove(pos)
    state.capital += pnl_dollar
    state.daily_pl += pnl_dollar
    state.total_pl += pnl_dollar
    
    if pnl_dollar < 0:
        state.daily_loss += abs(pnl_dollar)
    
    agent = pos.get("leading_agent", "Trend")
    if agent not in state.agent_scores:
        state.agent_scores[agent] = {"wins": 0, "losses": 0, "pl": 0.0, "streak": 0}
    
    if pnl_dollar > 0:
        state.agent_scores[agent]["wins"] += 1
        state.agent_scores[agent]["streak"] = max(state.agent_scores[agent].get("streak", 0) + 1, 1)
    else:
        state.agent_scores[agent]["losses"] += 1
        state.agent_scores[agent]["streak"] = min(state.agent_scores[agent].get("streak", 0) - 1, -1)
    
    state.agent_scores[agent]["pl"] += pnl_dollar
    
    state.trade_history.append({
        "symbol": pos["symbol"],
        "direction": pos["direction"],
        "entry": pos["entry_price"],
        "exit": pos["current_price"],
        "pnl": round(pnl_dollar, 2),
        "reason": reason,
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent
    })

def run_scan():
    with state.lock:
        state.scan_count += 1
        state.log(f"🔍 Scan #{state.scan_count} started...")
        
        prices = fetch_prices()
        if not prices:
            state.log("❌ No price data")
            return
        
        state.log(f"✅ Fetched {len(prices)} prices")
        
        movers = sorted(prices.items(), key=lambda x: abs(x[1].get("change_24h", 0) or 0), reverse=True)[:3]
        for coin, data in movers:
            sym = COIN_SYMBOLS.get(coin, coin.upper())
            chg = data.get("change_24h", 0) or 0
            state.log(f"   📊 {sym}: ${data['price']:.4f} ({chg:+.2f}%)")
        
        closed = check_positions(prices)
        if closed:
            state.log(f"📊 Closed {len(closed)} position(s)")
        
        signals = compute_agent_scores(prices)
        trades = get_consensus(signals)
        
        if trades:
            state.log(f"🎯 Found {len(trades)} trade setup(s)")
            for t in trades[:MAX_POSITIONS - len(state.positions)]:
                if execute_paper_trade(t):
                    state.log(f"   → {t['symbol']} {t['direction']} | Edge: {t['edge']:.1f}")
        else:
            best = max(signals.items(), key=lambda x: max(a["score"] for a in x[1]["agents"].values()))
            best_score = max(a["score"] for a in best[1]["agents"].values())
            state.log(f"😴 No trades — best score: {best_score} (need {MIN_CONFIDENCE}+)")
        
        state.log(f"💰 Capital: ${state.capital:.2f} | Daily: ${state.daily_pl:+.2f} | Total: ${state.total_pl:+.2f} | Pos: {len(state.positions)}/{MAX_POSITIONS}")

def trading_loop():
    state.log("🚀 Mike Trader Pro Cloud — Starting...")
    state.log(f"   Mode: {state.mode} | Capital: ${state.capital:.2f} | Trade thresholds: {MIN_CONFIDENCE}+ / {MIN_EDGE}+")
    
    while state.running:
        if state.status == "RUNNING":
            try:
                run_scan()
            except Exception as e:
                state.log(f"💥 Error: {e}")
        
        for _ in range(SCAN_INTERVAL_SECONDS):
            if not state.running:
                break
            time.sleep(1)

def start():
    if state.status == "RUNNING":
        return {"message": "Already running"}
    state.status = "RUNNING"
    state.running = True
    if state.thread is None or not state.thread.is_alive():
        state.thread = threading.Thread(target=trading_loop, daemon=True)
        state.thread.start()
    state.log("▶️ Bot STARTED")
    return {"message": "Bot started", "status": state.status}

def stop():
    state.status = "STOPPED"
    state.running = False
    state.log("⏹️ Bot STOPPED")
    return {"message": "Bot stopped", "status": state.status}

def pause():
    state.status = "PAUSED"
    state.log("⏸️ Bot PAUSED")
    return {"message": "Bot paused", "status": state.status}

def resume():
    state.status = "RUNNING"
    state.log("▶️ Bot RESUMED")
    return {"message": "Bot resumed", "status": state.status}

def set_mode(mode):
    if mode in ["SIGNAL", "PAPER", "AUTO"]:
        state.mode = mode
        state.log(f"🔄 Mode: {mode}")
        return {"message": f"Mode: {mode}", "mode": mode}
    return {"error": "Invalid mode"}

if __name__ == "__main__":
    start()
    while True:
        time.sleep(1)
