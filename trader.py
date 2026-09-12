# trader.py — Mike Trader Pro Cloud
# =========================================================
# LEARNING ENGINE v2 — MERGED + DEADLOCK FIX
#
# Merge of:
#   - Learning Engine v2 (best learning system)
#   - Deadlock fixes from Mike Trader Pro sessions:
#       1. 4-HOUR POSITION TIMEOUT (no more stuck trades)
#       2. SL 2% / TP 3% (faster trades, set in mike_config.py)
#       3. MAX_POSITIONS 5 (more action, set in mike_config.py)
#
#       v2.1 UPGRADES:
#       4. 💾 PERSISTENCE — learning auto-saved to
#          bot_state.json, survives restarts
#       5. 💸 FEES — 0.5% round-trip per trade
#          (paper results now match reality)
#       6. 🛡️ CRASH GUARD — no new trades while
#          BTC is dumping (-5% in 24h)
#
#       v2.2 UPGRADES:
#       7. 📈 CROSSOVER AGENT — EMA9/EMA21 cross +
#          RSI filter on real 15-minute Kraken
#          candles (the proven strategy)
#       8. 🌀 WHIPSAW GUARD — crossover agent
#          stands aside in sideways chop
#
# PAPER-FIRST VERSION
#
# Improvements:
# - Correct agent attribution
# - Performance-based learning
# - Recent + lifetime performance
# - Daily reset
# - Better short-term momentum
# - Trade journal
# - Cooldowns
# - Safer optimizer
# - Better logging
#
# IMPORTANT:
# This file does NOT execute real-money trades.
# "AUTO" remains paper execution until a separate broker
# execution layer is intentionally added.

import requests
import time
import threading
import json
import os
from datetime import datetime, date
from collections import deque

from mike_config import *


# =========================================================
# CONSTANTS
# =========================================================

AGENTS = [
    "Trend",
    "Momentum",
    "Volatility",
    "SupportResist",
    "MeanReversion",
    "Crossover"
]

DEFAULT_AGENT_STATS = {
    "wins": 0,
    "losses": 0,
    "pl": 0.0,
    "streak": 0,
    "trades": 0,
    "recent_results": [],
    "recent_pl": []
}

MIN_LEARNING_TRADES = 5
WEIGHT_MIN = 0.50
WEIGHT_MAX = 2.50

WEIGHT_UP_FACTOR = 1.08
WEIGHT_DOWN_FACTOR = 0.92

TRADE_COOLDOWN_SECONDS = 300


# =========================================================
# GLOBAL STATE
# =========================================================

class BotState:

    def __init__(self):

        self.status = "STOPPED"

        self.mode = TRADING_MODE

        self.capital = (
            PAPER_CAPITAL
            if TRADING_MODE == "PAPER"
            else REAL_CAPITAL
        )

        self.starting_capital = self.capital

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

        self.current_day = date.today()

        self.btc_change_24h = 0.0

        self.last_trade_by_coin = {}

        self.logs = deque(maxlen=500)

        self.running = False

        self.thread = None

        self.lock = threading.RLock()

        # Initialize every agent
        for agent in AGENTS:
            self.agent_scores[agent] = self._new_agent_stats()

    def _new_agent_stats(self):
        return {
            "wins": 0,
            "losses": 0,
            "pl": 0.0,
            "streak": 0,
            "trades": 0,
            "recent_results": deque(maxlen=20),
            "recent_pl": deque(maxlen=20)
        }

    def log(self, msg):

        timestamp = datetime.now().strftime("%H:%M:%S")

        entry = f"[{timestamp}] {msg}"

        self.logs.append(entry)

        if VERBOSE:
            print(entry)

    def reset_daily_if_needed(self):

        today = date.today()

        if today != self.current_day:

            self.log(
                f"📅 New trading day — "
                f"resetting daily P/L and daily loss."
            )

            self.current_day = today

            self.daily_pl = 0.0

            self.daily_loss = 0.0

    def get_status_dict(self):

        with self.lock:

            self.reset_daily_if_needed()

            return {
                "status": self.status,
                "mode": self.mode,
                "capital": round(self.capital, 2),
                "starting_capital": round(
                    self.starting_capital, 2
                ),
                "daily_pl": round(self.daily_pl, 2),
                "total_pl": round(self.total_pl, 2),
                "positions": len(self.positions),
                "max_positions": MAX_POSITIONS,
                "scan_count": self.scan_count,
                "daily_loss": round(
                    self.daily_loss, 2
                ),
                "logs": list(self.logs)[-25:],
                "agents": self.get_agent_summary(),
                "last_trade": (
                    self.last_trade_time
                    or "Never"
                )
            }

    def get_agent_summary(self):

        summary = {}

        for name in AGENTS:

            scores = self.agent_scores.get(
                name,
                self._new_agent_stats()
            )

            total = (
                scores.get("wins", 0)
                + scores.get("losses", 0)
            )

            if total > 0:

                win_rate = (
                    scores["wins"]
                    / total
                    * 100
                )

            else:

                win_rate = 0

            recent = list(
                scores.get(
                    "recent_results",
                    []
                )
            )

            recent_wr = (
                sum(recent)
                / len(recent)
                * 100
                if recent
                else 0
            )

            summary[name] = {

                "wins": scores.get(
                    "wins", 0
                ),

                "losses": scores.get(
                    "losses", 0
                ),

                "trades": scores.get(
                    "trades", 0
                ),

                "win_rate": round(
                    win_rate, 1
                ),

                "recent_win_rate": round(
                    recent_wr, 1
                ),

                "pl": round(
                    scores.get(
                        "pl", 0.0
                    ),
                    2
                ),

                "streak": scores.get(
                    "streak", 0
                ),

                "weight": round(
                    self.agent_weights.get(
                        name,
                        1.0
                    ),
                    2
                )
            }

        return summary


# =========================================================
# STATE PERSISTENCE 💾
# Saves all learning to disk (bot_state.json) so the bot
# NEVER loses its memory when the server restarts.
# Delete bot_state.json to factory-reset the bot.
# =========================================================

def save_state():

    try:

        data = {

            "version": 1,

            "saved_at":
                datetime.now().isoformat(),

            "current_day":
                str(date.today()),

            "capital":
                state.capital,

            "starting_capital":
                state.starting_capital,

            "daily_pl":
                state.daily_pl,

            "total_pl":
                state.total_pl,

            "daily_loss":
                state.daily_loss,

            "scan_count":
                state.scan_count,

            "agent_weights":
                dict(state.agent_weights),

            "agent_scores": {

                name: {

                    "wins":
                        s.get("wins", 0),

                    "losses":
                        s.get("losses", 0),

                    "pl":
                        s.get("pl", 0.0),

                    "streak":
                        s.get("streak", 0),

                    "trades":
                        s.get("trades", 0),

                    "recent_results":
                        list(
                            s.get(
                                "recent_results",
                                []
                            )
                        ),

                    "recent_pl":
                        list(
                            s.get(
                                "recent_pl",
                                []
                            )
                        )

                }

                for name, s in state.agent_scores.items()
            },

            "price_history": {

                coin: list(hist)[-200:]

                for coin, hist
                in state.price_history.items()
            },

            "trade_history":
                list(state.trade_history)[-300:]
        }

        with open(STATE_FILE, "w") as f:

            json.dump(data, f, indent=1)

    except Exception as e:

        state.log(
            f"⚠️ Could not save state: {e}"
        )


def load_state():

    if not os.path.exists(STATE_FILE):

        state.log(
            "🆕 No saved state found — "
            "starting fresh."
        )

        return

    try:

        with open(STATE_FILE) as f:

            data = json.load(f)

        state.capital = data.get(
            "capital",
            state.capital
        )

        state.starting_capital = data.get(
            "starting_capital",
            state.starting_capital
        )

        state.total_pl = data.get(
            "total_pl",
            0.0
        )

        state.scan_count = data.get(
            "scan_count",
            0
        )

        # Only restore DAILY counters if the saved
        # state is from today — otherwise daily
        # limits would carry over incorrectly.
        saved_day = data.get(
            "current_day",
            ""
        )

        if saved_day == str(date.today()):

            state.daily_pl = data.get(
                "daily_pl",
                0.0
            )

            state.daily_loss = data.get(
                "daily_loss",
                0.0
            )

        else:

            state.log(
                "📅 Saved state is from a previous "
                "day — daily counters reset."
            )

        saved_weights = data.get(
            "agent_weights",
            {}
        )

        for name, w in saved_weights.items():

            if name in state.agent_weights:

                state.agent_weights[name] = w

        saved_scores = data.get(
            "agent_scores",
            {}
        )

        for name, s in saved_scores.items():

            stats = state._new_agent_stats()

            stats["wins"] = s.get("wins", 0)

            stats["losses"] = s.get("losses", 0)

            stats["pl"] = s.get("pl", 0.0)

            stats["streak"] = s.get("streak", 0)

            stats["trades"] = s.get("trades", 0)

            for r in s.get(
                "recent_results",
                []
            ):

                stats["recent_results"].append(r)

            for p in s.get(
                "recent_pl",
                []
            ):

                stats["recent_pl"].append(p)

            state.agent_scores[name] = stats

        saved_hist = data.get(
            "price_history",
            {}
        )

        for coin, hist in saved_hist.items():

            state.price_history[coin] = deque(
                hist[-200:],
                maxlen=200
            )

        state.trade_history = list(
            data.get(
                "trade_history",
                []
            )
        )

        total_trades = sum(

            s.get("trades", 0)

            for s in state.agent_scores.values()
        )

        state.log(
            f"💾 LEARNING RESTORED: "
            f"{total_trades} trades | "
            f"Capital ${state.capital:.2f} | "
            f"Total P/L ${state.total_pl:+.2f}"
        )

        weights_str = " | ".join(

            f"{a}:"
            f"{state.agent_weights.get(a, 1.0):.2f}x"

            for a in AGENTS
        )

        state.log(
            f"💾 Weights restored: {weights_str}"
        )

    except Exception as e:

        state.log(
            f"⚠️ Could not load saved state "
            f"(starting fresh): {e}"
        )


state = BotState()


# =========================================================
# RESTORE SAVED LEARNING ON STARTUP
# =========================================================

load_state()



# =========================================================
# PRICE DATA
# =========================================================

def fetch_prices():

    try:

        ids = ",".join(COINS)

        url = (
            f"{COINGECKO_API_URL}"
            f"/simple/price"
            f"?ids={ids}"
            f"&vs_currencies=usd"
            f"&include_24hr_change=true"
        )

        resp = requests.get(
            url,
            timeout=15
        )

        if resp.status_code == 200:

            data = resp.json()

            prices = {}

            for coin in COINS:

                if (
                    coin in data
                    and "usd" in data[coin]
                ):

                    prices[coin] = {

                        "price": data[coin]["usd"],

                        "change_24h": (
                            data[coin].get(
                                "usd_24h_change",
                                0
                            )
                            or 0
                        )
                    }

            return prices

        if resp.status_code == 429:

            state.log(
                "⚠️ CoinGecko rate limit."
            )

            return {}

        state.log(
            f"⚠️ Price API HTTP {resp.status_code}"
        )

        return {}

    except requests.RequestException as e:

        state.log(
            f"⚠️ Price API error: {e}"
        )

        return {}

    except Exception as e:

        state.log(
            f"⚠️ Unexpected price error: {e}"
        )

        return {}


# =========================================================
# SHORT-TERM HELPERS
# =========================================================

def percentage_change(old, new):

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100
    )


def short_term_return(hist, bars=3):

    if len(hist) <= bars:
        return 0.0

    old = hist[-bars - 1]

    new = hist[-1]

    return percentage_change(
        old,
        new
    )


def short_term_volatility(hist, bars=10):

    if len(hist) < bars + 1:
        return 0.0

    returns = []

    for i in range(
        len(hist) - bars,
        len(hist)
    ):

        old = hist[i - 1]

        new = hist[i]

        if old != 0:

            returns.append(
                percentage_change(
                    old,
                    new
                )
            )

    if not returns:
        return 0.0

    avg = sum(returns) / len(returns)

    variance = sum(
        (x - avg) ** 2
        for x in returns
    ) / len(returns)

    return variance ** 0.5


# =========================================================
# CROSSOVER STRATEGY 📈
# The proven momentum system as a 6th agent:
#   BUY  = EMA9 crosses ABOVE EMA21 + RSI > 50
#   SELL = EMA9 crosses BELOW EMA21 + RSI < 50
# Data: Kraken public 15-minute candles (free, no key).
# Plus a whipsaw guard: in sideways chop the agent
# stands aside instead of bleeding stop-losses.
# =========================================================

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"

# Latest candles per coin — refreshed every scan
KLINES = {}


def fetch_klines(coin):

    pair = KRAKEN_PAIRS.get(coin)

    if not pair:
        return []

    try:

        resp = requests.get(

            KRAKEN_OHLC_URL,

            params={
                "pair": pair,
                "interval": KRAKEN_TIMEFRAME_MINUTES,
            },

            timeout=15,
        )

        if resp.status_code != 200:
            return []

        data = resp.json()

        result = data.get("result", {})

        candles = None

        for key, value in result.items():

            if key != "last":

                candles = value

                break

        if not candles:
            return []

        # Each candle: [time, open, high, low, close,
        #              vwap, volume, count]
        closes = []

        for c in candles:

            try:

                closes.append(float(c[4]))

            except (ValueError, IndexError, TypeError):

                continue

        # Drop the still-forming candle
        return closes[:-1]

    except requests.RequestException:
        return []

    except Exception:
        return []


def fetch_all_klines():

    klines = {}

    for coin in COINS:

        closes = fetch_klines(coin)

        if closes:

            klines[coin] = closes

        # Stay well under Kraken's public rate limit
        time.sleep(0.35)

    return klines


def compute_ema(values, period):

    if len(values) < period:
        return []

    alpha = 2 / (period + 1)

    ema = [sum(values[:period]) / period]

    for v in values[period:]:

        ema.append(
            alpha * v
            + (1 - alpha) * ema[-1]
        )

    return ema


def compute_rsi(closes, period):

    if len(closes) < period + 1:
        return 50.0

    gains = []

    losses = []

    for i in range(1, len(closes)):

        change = closes[i] - closes[i - 1]

        gains.append(max(change, 0))

        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period

    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):

        avg_gain = (
            avg_gain * (period - 1)
            + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - 100 / (1 + rs)


def crossover_signal(closes):
    """Returns (score, direction) for the EMA cross + RSI strategy."""

    neutral = (50, "NEUTRAL")

    needed = (
        CROSSOVER_SLOW_EMA
        + CROSSOVER_RSI_PERIOD
        + 10
    )

    if len(closes) < needed:
        return neutral

    ema_fast = compute_ema(
        closes,
        CROSSOVER_FAST_EMA,
    )

    ema_slow = compute_ema(
        closes,
        CROSSOVER_SLOW_EMA,
    )

    n = min(len(ema_fast), len(ema_slow))

    if n < CROSSOVER_LOOKBACK + 3:
        return neutral

    fast = ema_fast[-n:]

    slow = ema_slow[-n:]

    diffs = [

        f - s

        for f, s in zip(fast, slow)
    ]

    # =================================================
    # WHIPSAW GUARD 🌀
    # 3+ crosses in the last 8 candles = sideways
    # chop. Crossover systems bleed here — stand aside.
    # =================================================

    recent = diffs[-CROSSOVER_WHIPSAW_CANDLES:]

    cross_count = sum(

        1

        for i in range(1, len(recent))

        if (recent[i] > 0)
        != (recent[i - 1] > 0)
    )

    if cross_count >= CROSSOVER_MAX_RECENT_CROSSES:

        return neutral

    # Fresh cross within the last N candles?
    cross_up = False

    cross_down = False

    start = max(1, len(diffs) - CROSSOVER_LOOKBACK)

    for i in range(start, len(diffs)):

        if (

            diffs[i] > 0
            and diffs[i - 1] <= 0
        ):

            cross_up = True

        if (

            diffs[i] < 0
            and diffs[i - 1] >= 0
        ):

            cross_down = True

    rsi = compute_rsi(
        closes,
        CROSSOVER_RSI_PERIOD,
    )

    direction = "NEUTRAL"

    if cross_up and rsi > 50:

        direction = "UP"

    elif cross_down and rsi < 50:

        direction = "DOWN"

    if direction == "NEUTRAL":
        return neutral

    # Score by how strongly the EMAs are separating
    last_price = closes[-1]

    if last_price == 0:
        return neutral

    sep_pct = abs(diffs[-1]) / last_price * 100

    score = 62 + min(sep_pct * 25, 18)

    rsi_boost = min(abs(rsi - 50) / 50 * 8, 8)

    score += rsi_boost

    return (min(int(score), 90), direction)


# =========================================================
# AGENT ENGINE
# =========================================================

def compute_agent_scores(prices):

    signals = {}

    for coin, data in prices.items():

        price = data["price"]

        change_24h = (
            data.get(
                "change_24h",
                0
            )
            or 0
        )

        if coin not in state.price_history:

            state.price_history[coin] = deque(
                maxlen=200
            )

        state.price_history[coin].append(
            price
        )

        hist = list(
            state.price_history[coin]
        )

        # =================================================
        # TREND
        # =================================================

        trend_score = 50

        trend_dir = "NEUTRAL"

        if len(hist) >= 6:

            short = short_term_return(
                hist,
                5
            )

            if short > 0.20:

                trend_score = min(
                    55 + abs(short) * 12,
                    90
                )

                trend_dir = "UP"

            elif short < -0.20:

                trend_score = min(
                    55 + abs(short) * 12,
                    90
                )

                trend_dir = "DOWN"

            elif change_24h > 1:

                trend_score = min(
                    52 + change_24h * 2,
                    80
                )

                trend_dir = "UP"

            elif change_24h < -1:

                trend_score = min(
                    52 + abs(change_24h) * 2,
                    80
                )

                trend_dir = "DOWN"

        # =================================================
        # MOMENTUM
        # =================================================

        mom_score = 50

        mom_dir = "NEUTRAL"

        if len(hist) >= 4:

            short = short_term_return(
                hist,
                3
            )

            if short > 0.15:

                mom_score = min(
                    55 + abs(short) * 18,
                    90
                )

                mom_dir = "UP"

            elif short < -0.15:

                mom_score = min(
                    55 + abs(short) * 18,
                    90
                )

                mom_dir = "DOWN"

        # =================================================
        # VOLATILITY
        # =================================================

        vol_score = 50

        vol_dir = "NEUTRAL"

        volatility = short_term_volatility(
            hist,
            10
        )

        if volatility > 0.15:

            if short_term_return(
                hist,
                3
            ) > 0:

                vol_score = min(
                    55 + volatility * 10,
                    85
                )

                vol_dir = "UP"

            elif short_term_return(
                hist,
                3
            ) < 0:

                vol_score = min(
                    55 + volatility * 10,
                    85
                )

                vol_dir = "DOWN"

        # =================================================
        # SUPPORT / RESISTANCE
        # =================================================

        sr_score = 50

        sr_dir = "NEUTRAL"

        if len(hist) >= 10:

            recent = hist[-10:]

            high = max(recent)

            low = min(recent)

            if high > low:

                position = (
                    price - low
                ) / (
                    high - low
                )

                if position < 0.20:

                    sr_score = 62

                    sr_dir = "UP"

                elif position > 0.80:

                    sr_score = 62

                    sr_dir = "DOWN"

        # =================================================
        # MEAN REVERSION
        # =================================================

        mr_score = 50

        mr_dir = "NEUTRAL"

        if len(hist) >= 10:

            avg = sum(
                hist[-10:]
            ) / 10

            if avg > 0:

                deviation = (
                    (price - avg)
                    / avg
                    * 100
                )

                if deviation > 0.40:

                    mr_score = min(
                        55
                        + abs(deviation) * 8,
                        85
                    )

                    mr_dir = "DOWN"

                elif deviation < -0.40:

                    mr_score = min(
                        55
                        + abs(deviation) * 8,
                        85
                    )

                    mr_dir = "UP"

        # =================================================
        # CROSSOVER (EMA cross + RSI on Kraken 15m
        # candles — refreshed every scan)
        # =================================================

        co_score = 50

        co_dir = "NEUTRAL"

        klines_closes = KLINES.get(coin)

        if klines_closes:

            co_score, co_dir = crossover_signal(
                klines_closes
            )

        signals[coin] = {

            "price": price,

            "change_24h": change_24h,

            "short_return": round(
                short_term_return(
                    hist,
                    3
                ),
                4
            ),

            "volatility": round(
                volatility,
                4
            ),

            "agents": {

                "Trend": {
                    "score": int(
                        trend_score
                    ),
                    "dir": trend_dir
                },

                "Momentum": {
                    "score": int(
                        mom_score
                    ),
                    "dir": mom_dir
                },

                "Volatility": {
                    "score": int(
                        vol_score
                    ),
                    "dir": vol_dir
                },

                "SupportResist": {
                    "score": int(
                        sr_score
                    ),
                    "dir": sr_dir
                },

                "MeanReversion": {
                    "score": int(
                        mr_score
                    ),
                    "dir": mr_dir
                },

                "Crossover": {
                    "score": int(
                        co_score
                    ),
                    "dir": co_dir
                }
            }
        }

    return signals


# =========================================================
# CONSENSUS ENGINE
# =========================================================

def get_consensus(signals):

    trades = []

    for coin, data in signals.items():

        agents = data["agents"]

        up_votes = 0.0

        down_votes = 0.0

        weighted_total = 0.0

        total_weight = 0.0

        for name, info in agents.items():

            weight = state.agent_weights.get(
                name,
                1.0
            )

            weighted_total += (
                info["score"]
                * weight
            )

            total_weight += weight

            if info["dir"] == "UP":

                up_votes += weight

            elif info["dir"] == "DOWN":

                down_votes += weight

        if total_weight <= 0:
            continue

        avg_score = (
            weighted_total
            / total_weight
        )

        if up_votes > down_votes:

            direction = "UP"

        elif down_votes > up_votes:

            direction = "DOWN"

        else:

            direction = "NEUTRAL"

        if direction == "NEUTRAL":
            continue

        winning_agents = {}

        for name, info in agents.items():

            if info["dir"] == direction:

                weight = state.agent_weights.get(
                    name,
                    1.0
                )

                # Actual contribution
                contribution = (
                    info["score"]
                    * weight
                )

                winning_agents[name] = {
                    "score": info["score"],
                    "weight": weight,
                    "contribution": contribution
                }

        if not winning_agents:
            continue

        # =================================================
        # IMPORTANT:
        # Agent attribution now uses weighted contribution,
        # not raw score.
        # =================================================

        leading_agent = max(
            winning_agents,
            key=lambda name:
                winning_agents[name][
                    "contribution"
                ]
        )

        winning_contributions = [
            x["contribution"]
            for x in winning_agents.values()
        ]

        edge = (
            sum(winning_contributions)
            / len(winning_contributions)
        )

        confidence = avg_score

        # Additional agreement bonus
        agreement_ratio = (
            max(
                up_votes,
                down_votes
            )
            / total_weight
        )

        confidence += (
            agreement_ratio * 10
        )

        confidence = min(
            confidence,
            100
        )

        # Use config thresholds
        if (
            confidence < MIN_CONFIDENCE
            or edge < MIN_EDGE
        ):
            continue

        trades.append({

            "coin": coin,

            "symbol": COIN_SYMBOLS.get(
                coin,
                coin.upper()
            ),

            "price": data["price"],

            "direction": direction,

            "edge": round(
                edge,
                1
            ),

            "confidence": round(
                confidence,
                1
            ),

            "change_24h": data[
                "change_24h"
            ],

            "short_return": data[
                "short_return"
            ],

            "volatility": data[
                "volatility"
            ],

            "agents": agents,

            "leading_agent":
                leading_agent,

            "agent_contributions":
                winning_agents
        })

    trades.sort(
        key=lambda x: (
            x["confidence"],
            x["edge"]
        ),
        reverse=True
    )

    return trades


# =========================================================
# RISK CHECKS
# =========================================================

def can_trade(trade):

    state.reset_daily_if_needed()

    if len(state.positions) >= MAX_POSITIONS:

        return False, "MAX_POSITIONS"

    if (
        state.daily_loss
        >= DAILY_LOSS_LIMIT
    ):

        return False, "DAILY_LOSS_LIMIT"

    if (
        state.total_pl
        <= -TOTAL_LOSS_LIMIT
    ):

        return False, "TOTAL_LOSS_LIMIT"

    # =================================================
    # MARKET CRASH GUARD
    # Don't open new trades while BTC is dumping.
    # BTC 24h change is refreshed every scan.
    # Set in mike_config.py (CRASH_GUARD_*).
    # =================================================

    if (
        CRASH_GUARD_ENABLED
        and state.btc_change_24h
        <= CRASH_GUARD_BTC_DROP
    ):

        return False, "MARKET_CRASH_GUARD"

    symbol = trade["symbol"]

    # Duplicate position
    for pos in state.positions:

        if pos["symbol"] == symbol:

            return False, "ALREADY_OPEN"

    # Cooldown
    last_time = state.last_trade_by_coin.get(
        symbol
    )

    if last_time:

        elapsed = (
            datetime.now()
            - last_time
        ).total_seconds()

        if elapsed < TRADE_COOLDOWN_SECONDS:

            return False, "COOLDOWN"

    return True, "OK"


# =========================================================
# PAPER EXECUTION
# =========================================================

def execute_paper_trade(trade):

    allowed, reason = can_trade(
        trade
    )

    if not allowed:

        state.log(
            f"⛔ Trade rejected: {reason}"
        )

        return False

    symbol = trade["symbol"]

    direction = trade["direction"]

    price = trade["price"]

    leading_agent = trade[
        "leading_agent"
    ]

    position_size = (
        state.capital
        * POSITION_SIZE_PCT
        / 100
    )

    if position_size <= 0:
        return False

    if direction == "UP":

        stop_loss = (
            price
            * (
                1
                - STOP_LOSS_PCT
                / 100
            )
        )

        take_profit = (
            price
            * (
                1
                + TAKE_PROFIT_PCT
                / 100
            )
        )

    else:

        stop_loss = (
            price
            * (
                1
                + STOP_LOSS_PCT
                / 100
            )
        )

        take_profit = (
            price
            * (
                1
                - TAKE_PROFIT_PCT
                / 100
            )
        )

    trade_id = (
        len(state.trade_history)
        + len(state.positions)
        + 1
    )

    position = {

        "id": trade_id,

        "symbol": symbol,

        "coin": trade["coin"],

        "direction": direction,

        "entry_price": price,

        "current_price": price,

        "size": position_size,

        "stop_loss": stop_loss,

        "take_profit": take_profit,

        "entry_time": datetime.now(),

        "edge": trade["edge"],

        "confidence":
            trade["confidence"],

        "leading_agent":
            leading_agent,

        "change_24h_at_entry":
            trade["change_24h"],

        "short_return_at_entry":
            trade[
                "short_return"
            ],

        "volatility_at_entry":
            trade[
                "volatility"
            ],

        "agent_contributions":
            trade[
                "agent_contributions"
            ]
    }

    state.positions.append(
        position
    )

    state.last_trade_time = (
        datetime.now()
        .strftime("%H:%M:%S")
    )

    state.last_trade_by_coin[
        symbol
    ] = datetime.now()

    emoji = (
        "📈"
        if direction == "UP"
        else "📉"
    )

    state.log(
        f"{emoji} PAPER TRADE #{trade_id}: "
        f"{symbol} {direction} "
        f"@ ${price:.4f} | "
        f"Agent: {leading_agent} | "
        f"Conf: {trade['confidence']:.1f} | "
        f"Edge: {trade['edge']:.1f} | "
        f"Size: ${position_size:.2f}"
    )

    return True


# =========================================================
# POSITION MANAGEMENT
# =========================================================

def check_positions(prices):

    closed = []

    for pos in state.positions[:]:

        coin = pos["coin"]

        if coin not in prices:
            continue

        current_price = prices[
            coin
        ]["price"]

        pos["current_price"] = (
            current_price
        )

        entry = pos[
            "entry_price"
        ]

        size = pos["size"]

        direction = pos[
            "direction"
        ]

        if direction == "UP":

            pnl_pct = (
                (
                    current_price
                    - entry
                )
                / entry
                * 100
            )

        else:

            pnl_pct = (
                (
                    entry
                    - current_price
                )
                / entry
                * 100
            )

        pnl_dollar = (
            size
            * pnl_pct
            / 100
        )

        if (
            pnl_pct
            <= -STOP_LOSS_PCT
        ):

            state.log(
                f"🛑 STOP LOSS: "
                f"{pos['symbol']} "
                f"@ ${current_price:.4f} | "
                f"${pnl_dollar:.2f}"
            )

            close_position(
                pos,
                pnl_dollar,
                "STOP_LOSS"
            )

            closed.append(pos)

        elif (
            pnl_pct
            >= TAKE_PROFIT_PCT
        ):

            state.log(
                f"🎯 TAKE PROFIT: "
                f"{pos['symbol']} "
                f"@ ${current_price:.4f} | "
                f"+${pnl_dollar:.2f}"
            )

            close_position(
                pos,
                pnl_dollar,
                "TAKE_PROFIT"
            )

            closed.append(pos)

            continue

        # =================================================
        # POSITION TIMEOUT
        # Close trades sitting open too long (sideways
        # market). Frees slots so the bot never
        # deadlocks. Set POSITION_TIMEOUT_SECONDS in
        # mike_config.py (default 4 hours).
        # =================================================

        elapsed = (
            datetime.now()
            - pos["entry_time"]
        ).total_seconds()

        if elapsed > POSITION_TIMEOUT_SECONDS:

            state.log(
                f"⏰ TIMEOUT: "
                f"{pos['symbol']} closed after "
                f"{elapsed / 3600:.1f}h | "
                f"P/L ${pnl_dollar:+.2f} "
                f"({pnl_pct:+.2f}%)"
            )

            close_position(
                pos,
                pnl_dollar,
                "TIMEOUT"
            )

            closed.append(pos)

    return closed


# =========================================================
# CLOSE + LEARNING
# =========================================================

def close_position(
    pos,
    pnl_dollar,
    reason
):

    if pos not in state.positions:
        return

    state.positions.remove(
        pos
    )

    # =================================================
    # FEES
    # Round-trip exchange fee subtracted from every
    # closed trade, so paper results match real
    # trading. Set FEE_PCT in mike_config.py.
    # =================================================

    fee = (
        pos["size"]
        * FEE_PCT
        / 100
    )

    net_pnl = pnl_dollar - fee

    state.log(
        f"💸 Fee: ${fee:.2f} "
        f"({FEE_PCT}% round trip) | "
        f"Net P/L: ${net_pnl:+.2f}"
    )

    state.capital += net_pnl

    state.daily_pl += net_pnl

    state.total_pl += net_pnl

    if net_pnl < 0:

        state.daily_loss += abs(
            net_pnl
        )

    agent = pos.get(
        "leading_agent",
        "Trend"
    )

    if agent not in state.agent_scores:

        state.agent_scores[
            agent
        ] = state._new_agent_stats()

    scores = state.agent_scores[
        agent
    ]

    scores["trades"] += 1

    scores["pl"] += net_pnl

    if net_pnl > 0:

        scores["wins"] += 1

        scores["streak"] = max(
            scores.get(
                "streak",
                0
            ) + 1,
            1
        )

        result = 1

    else:

        scores["losses"] += 1

        scores["streak"] = min(
            scores.get(
                "streak",
                0
            ) - 1,
            -1
        )

        result = 0

    scores[
        "recent_results"
    ].append(result)

    scores[
        "recent_pl"
    ].append(net_pnl)

    # =====================================================
    # TRADE JOURNAL
    # =====================================================

    trade_record = {

        "id": pos["id"],

        "symbol": pos["symbol"],

        "direction":
            pos["direction"],

        "entry":
            pos["entry_price"],

        "exit":
            pos["current_price"],

        "pnl":
            round(
                net_pnl,
                2
            ),

        "fee":
            round(
                fee,
                2
            ),

        "reason":
            reason,

        "agent":
            agent,

        "confidence":
            pos.get(
                "confidence",
                0
            ),

        "edge":
            pos.get(
                "edge",
                0
            ),

        "entry_time":
            pos[
                "entry_time"
            ].strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "exit_time":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
    }

    state.trade_history.append(
        trade_record
    )

    state.log(
        f"🧠 LEARNING: "
        f"{agent} receives result "
        f"{'WIN' if result else 'LOSS'} "
        f"| Net P/L ${net_pnl:+.2f}"
    )

    optimize_weights()

    # =================================================
    # PERSISTENCE
    # Save learning progress on every closed trade,
    # so a restart never loses a single result.
    # =================================================

    save_state()


# =========================================================
# LEARNING ENGINE
# =========================================================

def optimize_weights():

    for agent in AGENTS:

        scores = state.agent_scores.get(
            agent
        )

        if not scores:
            continue

        total = scores.get(
            "trades",
            0
        )

        # Don't learn aggressively from
        # tiny samples.
        if total < MIN_LEARNING_TRADES:

            continue

        wins = scores.get(
            "wins",
            0
        )

        lifetime_wr = (
            wins
            / total
        )

        recent_results = list(
            scores.get(
                "recent_results",
                []
            )
        )

        if recent_results:

            recent_wr = (
                sum(
                    recent_results
                )
                / len(
                    recent_results
                )
            )

        else:

            recent_wr = lifetime_wr

        # Blend recent performance with
        # lifetime performance.
        blended_wr = (
            lifetime_wr * 0.60
            + recent_wr * 0.40
        )

        current_weight = (
            state.agent_weights.get(
                agent,
                1.0
            )
        )

        new_weight = (
            current_weight
        )

        if blended_wr >= 0.60:

            new_weight = (
                current_weight
                * WEIGHT_UP_FACTOR
            )

        elif blended_wr <= 0.40:

            new_weight = (
                current_weight
                * WEIGHT_DOWN_FACTOR
            )

        new_weight = max(
            WEIGHT_MIN,
            min(
                new_weight,
                WEIGHT_MAX
            )
        )

        if abs(
            new_weight
            - current_weight
        ) >= 0.01:

            state.agent_weights[
                agent
            ] = new_weight

            state.log(
                f"🧠 LEARNING: "
                f"{agent} "
                f"{current_weight:.2f}x → "
                f"{new_weight:.2f}x | "
                f"WR {blended_wr * 100:.1f}% "
                f"| Trades {total}"
            )


# =========================================================
# SCAN
# =========================================================

def run_scan():

    with state.lock:

        state.reset_daily_if_needed()

        state.scan_count += 1

        state.log(
            f"🔍 Scan #{state.scan_count} started..."
        )

        prices = fetch_prices()

        if not prices:

            state.log(
                "❌ No price data."
            )

            return

        state.log(
            f"✅ Fetched "
            f"{len(prices)} prices"
        )

        # Refresh BTC 24h change for the crash guard
        btc_data = prices.get("bitcoin")

        if btc_data:

            state.btc_change_24h = (
                btc_data.get("change_24h", 0)
                or 0
            )

        # =================================================
        # 15-MINUTE CANDLES (Kraken — powers the
        # Crossover agent's EMA/RSI strategy)
        # =================================================

        KLINES.clear()

        KLINES.update(fetch_all_klines())

        if KLINES:

            state.log(
                f"📈 Candles: "
                f"{len(KLINES)} coin(s) on "
                f"{KRAKEN_TIMEFRAME_MINUTES}m"
            )

        else:

            state.log(
                "⚠️ Candle data unavailable — "
                "Crossover agent idle"
            )

        # =================================================
        # PRICE DISPLAY
        # =================================================

        for coin, data in sorted(
            prices.items(),
            key=lambda x:
                abs(
                    x[1][
                        "change_24h"
                    ]
                ),
            reverse=True
        ):

            symbol = COIN_SYMBOLS.get(
                coin,
                coin.upper()
            )

            state.log(
                f"   📊 {symbol}: "
                f"${data['price']:.4f} "
                f"({data['change_24h']:+.2f}%)"
            )

        # =================================================
        # MANAGE EXISTING POSITIONS
        # =================================================

        closed = check_positions(
            prices
        )

        if closed:

            state.log(
                f"📊 Closed "
                f"{len(closed)} "
                f"position(s)"
            )

        # =================================================
        # ANALYZE
        # =================================================

        signals = compute_agent_scores(
            prices
        )

        trades = get_consensus(
            signals
        )

        available_slots = (
            MAX_POSITIONS
            - len(
                state.positions
            )
        )

        if trades and available_slots > 0:

            state.log(
                f"🎯 Found "
                f"{len(trades)} "
                f"qualified setup(s)"
            )

            executed = 0

            for trade in trades:

                if executed >= available_slots:
                    break

                if execute_paper_trade(
                    trade
                ):

                    executed += 1

                    state.log(
                        f"   → "
                        f"{trade['symbol']} "
                        f"{trade['direction']} | "
                        f"Lead: "
                        f"{trade['leading_agent']} | "
                        f"Conf: "
                        f"{trade['confidence']:.1f}"
                    )

        else:

            if available_slots <= 0:

                state.log(
                    "⏸️ No new trades — "
                    "maximum positions open."
                )

            else:

                best_coin = None

                best_score = -1

                for coin, signal in signals.items():

                    avg = sum(
                        a["score"]
                        for a in signal[
                            "agents"
                        ].values()
                    ) / len(
                        signal[
                            "agents"
                        ]
                    )

                    if avg > best_score:

                        best_score = avg

                        best_coin = coin

                if best_coin:

                    symbol = COIN_SYMBOLS.get(
                        best_coin,
                        best_coin.upper()
                    )

                    state.log(
                        f"😴 No qualified trades — "
                        f"best average: "
                        f"{symbol} "
                        f"{best_score:.1f}"
                    )

        # =================================================
        # WEIGHTS
        # =================================================

        weights = " | ".join(
            f"{agent}:"
            f"{state.agent_weights.get(agent, 1.0):.2f}x"
            for agent in AGENTS
        )

        state.log(
            f"⚖️ Weights: {weights}"
        )

        # =================================================
        # PERIODIC SAVE (every N scans)
        # =================================================

        if state.scan_count % SAVE_EVERY_SCANS == 0:

            save_state()

        # =================================================
        # CAPITAL
        # =================================================

        state.log(
            f"💰 Capital: "
            f"${state.capital:.2f} | "
            f"Daily: "
            f"${state.daily_pl:+.2f} | "
            f"Total: "
            f"${state.total_pl:+.2f} | "
            f"Pos: "
            f"{len(state.positions)}/"
            f"{MAX_POSITIONS}"
        )


# =========================================================
# TRADING LOOP
# =========================================================

def trading_loop():

    state.log(
        "🚀 Mike Trader Pro "
        "Learning Engine v2"
    )

    state.log(
        f"   Mode: {state.mode}"
    )

    state.log(
        f"   Capital: "
        f"${state.capital:.2f}"
    )

    state.log(
        "   🧠 Agent performance learning ENABLED"
    )

    state.log(
        "   🛡️ Paper execution only"
    )

    while state.running:

        if state.status == "RUNNING":

            try:

                run_scan()

            except Exception as e:

                state.log(
                    f"💥 Scan error: {e}"
                )

        for _ in range(
            SCAN_INTERVAL_SECONDS
        ):

            if not state.running:
                break

            time.sleep(1)


# =========================================================
# CONTROL
# =========================================================

def start():

    if state.status == "RUNNING":

        return {
            "message":
                "Already running"
        }

    state.status = "RUNNING"

    state.running = True

    if (
        state.thread is None
        or not state.thread.is_alive()
    ):

        state.thread = threading.Thread(
            target=trading_loop,
            daemon=True
        )

        state.thread.start()

    state.log(
        "▶️ Bot STARTED"
    )

    return {
        "message":
            "Bot started",
        "status":
            state.status
    }


def stop():

    state.status = "STOPPED"

    state.running = False

    save_state()

    state.log(
        "⏹️ Bot STOPPED"
    )

    return {
        "message":
            "Bot stopped",
        "status":
            state.status
    }


def pause():

    state.status = "PAUSED"

    state.log(
        "⏸️ Bot PAUSED"
    )

    return {
        "message":
            "Bot paused",
        "status":
            state.status
    }


def resume():

    state.status = "RUNNING"

    state.log(
        "▶️ Bot RESUMED"
    )

    return {
        "message":
            "Bot resumed",
        "status":
            state.status
    }


def set_mode(mode):

    allowed_modes = [
        "SIGNAL",
        "PAPER",
        "AUTO"
    ]

    if mode not in allowed_modes:

        return {
            "error":
                "Invalid mode"
        }

    # IMPORTANT:
    # AUTO does NOT connect to a broker.
    # It remains paper execution.

    state.mode = mode

    state.log(
        f"🔄 Mode changed to: "
        f"{mode}"
    )

    return {
        "message":
            f"Mode: {mode}",
        "mode":
            mode
    }


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    start()

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        stop()

        print(
            "\nMike Trader Pro stopped."
        )
