# trader.py — Mike Trader Pro Cloud (FIXED — Actually Trades!)
# ============================================================

import requests
import json
import time
import random
import threading
from datetime import datetime, timedelta
from collections import deque

# ─── Config Import ───
from mike_config import *

# ─── Global State ───
class BotState:
    def __init__(self):
        self.status = "STOPPED"           # STOPPED, RUNNING, PAUSED
        self.mode = TRADING_MODE          # SIGNAL, PAPER, AUTO
        self.capital = PAPER_CAPITAL if TRADING_MODE == "PAPER" else REAL_CAPITAL
        self.daily_pl = 0.0
        self.total_pl = 0.0
        self.positions = []               # Active trades
        self.trade_history = []           # Closed trades
        self.agent_scores = {}            # Win/loss per agent
        self.agent_weights = AGENT_WEIGHTS.copy()
        self.price_history = {}           # {coin: [prices]}
        self.scan_count = 0
        self.last_scan_time = None
        self.last_trade_time = None
        self.daily_loss = 0.0
        self.logs = deque(maxlen=200)     # Last 200 log messages
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

# ─── Initialize State ───
state = BotState()

# ─── Price Fetching ───
def fetch_prices():
    """Fetch current prices for all coins from CoinGecko."""
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
                        "change_24h": data[coin].get("usd_24h_change", 0)
                    }
            return prices
        elif resp.status_code == 429:
            state.log("⚠️ CoinGecko rate limit hit — waiting...")
            time.sleep(30)
            return {}
        else:
            state.log(f"⚠️ CoinGecko error: {resp.status_code}")
            return {}
    except Exception as e:
        state.log(f"⚠️ Price fetch error: {e}")
        return {}

# ─── Technical Analysis Agents ───
def compute_agent_scores(prices):
    """Run all 5 agents and return scores + direction for each coin."""
    signals = {}

    for coin, data in prices.items():
        price = data["price"]
        change_24h = data.get("change_24h", 0)

        # Update price history
        if coin not in state.price_history:
            state.price_history[coin] = deque(maxlen=50)
        state.price_history[coin].append(price)
        hist = list(state.price_history[coin])

        # ─── Trend Agent ───
        trend_score = 50
        trend_dir = "NEUTRAL"
        if len(hist) >= 10:
            sma_short = sum(hist[-5:]) / 5
            sma_long = sum(hist[-10:]) / 10
            if sma_short > sma_long * 1.005:
                trend_score = 65 + min(abs(change_24h) * 2, 25)
                trend_dir = "UP"
            elif sma_short < sma_long * 0.995:
                trend_score = 65 + min(abs(change_24h) * 2, 25)
                trend_dir = "DOWN"

        # ─── Momentum Agent ───
        mom_score = 50
        mom_dir = "NEUTRAL"
        if len(hist) >= 3:
            mom = ((hist[-1] - hist[-3]) / hist[-3]) * 100 if hist[-3] != 0 else 0
            if abs(mom) > 0.5:
                mom_score = 60 + min(abs(mom) * 5, 30)
                mom_dir = "UP" if mom > 0 else "DOWN"

        # ─── Volatility Agent ───
        vol_score = 50
        vol_dir = "NEUTRAL"
        if len(hist) >= 10:
            returns = [(hist[i] - hist[i-1]) / hist[i-1] * 100 for i in range(1, len(hist))]
            if len(returns) > 1:
                avg_ret = sum(returns) / len(returns)
                volatility = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                if volatility > 1.5:
                    vol_score = 60 + min(volatility * 5, 30)
                    vol_dir = "UP" if returns[-1] > 0 else "DOWN"

        # ─── Support/Resistance Agent ───
        sr_score = 50
        sr_dir = "NEUTRAL"
        if len(hist) >= 15:
            recent = hist[-15:]
            high = max(recent)
            low = min(recent)
            range_size = high - low
            if range_size > 0:
                position = (price - low) / range_size
                if position > 0.85:
                    sr_score = 65
                    sr_dir = "DOWN"  # Near resistance → expect pullback
                elif position < 0.15:
                    sr_score = 65
                    sr_dir = "UP"    # Near support → expect bounce

        # ─── Mean Reversion Agent ───
        mr_score = 50
        mr_dir = "NEUTRAL"
        if len(hist) >= 20:
            sma20 = sum(hist[-20:]) / 20
            deviation = ((price - sma20) / sma20) * 100
            if abs(deviation) > 1.5:
                mr_score = 60 + min(abs(deviation) * 3, 30)
                mr_dir = "DOWN" if deviation > 0 else "UP"

        signals[coin] = {
            "price": price,
            "change_24h": change_24h,
            "agents": {
                "Trend": {"score": trend_score, "dir": trend_dir},
                "Momentum": {"score": mom_score, "dir": mom_dir},
                "Volatility": {"score": vol_score, "dir": vol_dir},
                "SupportResist": {"score": sr_score, "dir": sr_dir},
                "MeanReversion": {"score": mr_score, "dir": mr_dir}
            }
        }

    return signals

# ─── Consensus Engine ───
def get_consensus(signals):
    """Combine agent scores into a final trade decision."""
    trades = []

    for coin, data in signals.items():
        agents = data["agents"]

        # Weighted average score
        total_weight = 0
        weighted_score = 0
        up_votes = 0
        down_votes = 0

        for name, info in agents.items():
            weight = state.agent_weights.get(name, 1.0)
            weighted_score += info["score"] * weight
            total_weight += weight
            if info["dir"] == "UP":
                up_votes += weight
            elif info["dir"] == "DOWN":
                down_votes += weight

        avg_score = weighted_score / total_weight if total_weight > 0 else 50

        # Direction: majority vote
        if up_votes > down_votes * 1.2:
            direction = "UP"
            edge = avg_score * (up_votes / total_weight)
        elif down_votes > up_votes * 1.2:
            direction = "DOWN"
            edge = avg_score * (down_votes / total_weight)
        else:
            direction = "NEUTRAL"
            edge = 0

        # Only trade if edge is strong enough
        if edge >= MIN_EDGE and avg_score >= MIN_CONFIDENCE:
            trades.append({
                "coin": coin,
                "symbol": COIN_SYMBOLS.get(coin, coin.upper()),
                "price": data["price"],
                "direction": direction,
                "edge": round(edge, 1),
                "confidence": round(avg_score, 1),
                "agents": agents
            })

    # Sort by edge (best trades first)
    trades.sort(key=lambda x: x["edge"], reverse=True)
    return trades

# ─── Trade Execution ───
def execute_paper_trade(trade):
    """Execute a paper trade."""
    symbol = trade["symbol"]
    direction = trade["direction"]
    price = trade["price"]

    # Position size
    position_size = (state.capital * POSITION_SIZE_PCT) / 100

    # Check limits
    if len(state.positions) >= MAX_POSITIONS:
        state.log(f"⛔ Max positions reached ({MAX_POSITIONS})")
        return False

    if state.daily_loss >= DAILY_LOSS_LIMIT:
        state.log(f"⛔ Daily loss limit reached (${state.daily_loss:.2f})")
        return False

    if state.total_pl <= -TOTAL_LOSS_LIMIT:
        state.log(f"⛔ Total loss limit reached (${state.total_pl:.2f})")
        return False

    # Create position
    position = {
        "id": len(state.trade_history) + len(state.positions) + 1,
        "symbol": symbol,
        "direction": direction,
        "entry_price": price,
        "size": position_size,
        "stop_loss": price * (1 - STOP_LOSS_PCT/100) if direction == "UP" else price * (1 + STOP_LOSS_PCT/100),
        "take_profit": price * (1 + TAKE_PROFIT_PCT/100) if direction == "UP" else price * (1 - TAKE_PROFIT_PCT/100),
        "entry_time": datetime.now(),
        "edge": trade["edge"],
        "leading_agent": max(trade["agents"], key=lambda k: trade["agents"][k]["score"])
    }

    state.positions.append(position)
    state.last_trade_time = datetime.now().strftime("%H:%M:%S")

    emoji = "📈" if direction == "UP" else "📉"
    state.log(f"{emoji} PAPER TRADE: {symbol} {direction} @ ${price:.4f} | Size: ${position_size:.2f} | Edge: {trade['edge']:.1f}")

    return True

def check_positions(prices):
    """Check if any positions hit stop loss or take profit."""
    closed = []

    for pos in state.positions[:]:
        symbol = pos["symbol"]
        coin = None
        for c, s in COIN_SYMBOLS.items():
            if s == symbol:
                coin = c
                break

        if coin not in prices:
            continue

        current_price = prices[coin]["price"]
        direction = pos["direction"]
        entry = pos["entry_price"]
        size = pos["size"]

        # Calculate P&L
        if direction == "UP":
            pnl_pct = ((current_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current_price) / entry) * 100

        pnl_dollar = size * (pnl_pct / 100)

        # Check stop loss
        if pnl_pct <= -STOP_LOSS_PCT:
            state.log(f"🛑 STOP LOSS: {symbol} @ ${current_price:.4f} | Loss: ${abs(pnl_dollar):.2f}")
            close_position(pos, pnl_dollar, "STOP_LOSS")
            closed.append(pos)

        # Check take profit
        elif pnl_pct >= TAKE_PROFIT_PCT:
            state.log(f"🎯 TAKE PROFIT: {symbol} @ ${current_price:.4f} | Profit: ${pnl_dollar:.2f}")
            close_position(pos, pnl_dollar, "TAKE_PROFIT")
            closed.append(pos)

    return closed

def close_position(pos, pnl_dollar, reason):
    """Close a position and update stats."""
    state.positions.remove(pos)
    state.capital += pnl_dollar
    state.daily_pl += pnl_dollar
    state.total_pl += pnl_dollar

    if pnl_dollar < 0:
        state.daily_loss += abs(pnl_dollar)

    # Update agent scores
    agent = pos.get("leading_agent", "Trend")
    if agent not in state.agent_scores:
        state.agent_scores[agent] = {"wins": 0, "losses": 0, "pl": 0.0, "streak": 0}

    if pnl_dollar > 0:
        state.agent_scores[agent]["wins"] += 1
        state.agent_scores[agent]["streak"] = max(state.agent_scores[agent]["streak"] + 1, 1)
    else:
        state.agent_scores[agent]["losses"] += 1
        state.agent_scores[agent]["streak"] = min(state.agent_scores[agent]["streak"] - 1, -1)

    state.agent_scores[agent]["pl"] += pnl_dollar

    # Auto-optimize weights
    optimize_weights()

    # Record trade
    state.trade_history.append({
        "symbol": pos["symbol"],
        "direction": pos["direction"],
        "entry": pos["entry_price"],
        "exit": pos["entry_price"] * (1 + pnl_dollar/pos["size"]/100) if pos["size"] > 0 else pos["entry_price"],
        "pnl": round(pnl_dollar, 2),
        "reason": reason,
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent
    })

def optimize_weights():
    """Adjust agent weights based on performance."""
    for agent, scores in state.agent_scores.items():
        total = scores.get("wins", 0) + scores.get("losses", 0)
        if total >= 3:
            win_rate = scores["wins"] / total
            if win_rate > 0.6:
                state.agent_weights[agent] = min(state.agent_weights.get(agent, 1.0) * 1.1, 2.0)
            elif win_rate < 0.4:
                state.agent_weights[agent] = max(state.agent_weights.get(agent, 1.0) * 0.9, 0.5)

# ─── Main Trading Loop ───
def run_scan():
    """Run one complete scan cycle."""
    with state.lock:
        state.scan_count += 1
        state.last_scan_time = datetime.now().strftime("%H:%M:%S")
        state.log(f"🔍 Scan #{state.scan_count} started...")

        # 1. Fetch prices
        prices = fetch_prices()
        if not prices:
            state.log("❌ No price data — skipping scan")
            return

        state.log(f"✅ Fetched {len(prices)} prices")

        # 2. Check existing positions
        closed = check_positions(prices)
        if closed:
            state.log(f"📊 Closed {len(closed)} position(s)")

        # 3. Run agents
        signals = compute_agent_scores(prices)

        # 4. Get consensus
        trades = get_consensus(signals)

        if trades:
            state.log(f"🎯 Found {len(trades)} trade setup(s)")
            for t in trades[:MAX_POSITIONS - len(state.positions)]:
                if execute_paper_trade(t):
                    state.log(f"   → {t['symbol']} {t['direction']} | Edge: {t['edge']:.1f} | Conf: {t['confidence']:.1f}")
        else:
            state.log("😴 No trade setups this scan")

        # 5. Summary
        state.log(f"💰 Capital: ${state.capital:.2f} | Daily P&L: ${state.daily_pl:+.2f} | Positions: {len(state.positions)}/{MAX_POSITIONS}")

def trading_loop():
    """Main loop that runs continuously."""
    state.log("🚀 Mike Trader Pro Cloud — Starting trading loop...")
    state.log(f"   Mode: {state.mode} | Capital: ${state.capital:.2f} | Interval: {SCAN_INTERVAL_SECONDS}s")

    while state.running:
        if state.status == "RUNNING":
            try:
                run_scan()
            except Exception as e:
                state.log(f"💥 Scan error: {e}")

        # Sleep between scans
        for _ in range(SCAN_INTERVAL_SECONDS):
            if not state.running:
                break
            time.sleep(1)

# ─── Control Methods ───
def start():
    if state.status == "RUNNING":
        return {"message": "Bot is already running"}
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
        state.log(f"🔄 Mode changed to {mode}")
        return {"message": f"Mode set to {mode}", "mode": mode}
    return {"error": "Invalid mode"}

# ─── Auto-start on import (for Railway) ───
if __name__ == "__main__":
    start()
    while True:
        time.sleep(1)
