# mike_config.py — Mike Trader Pro Cloud Configuration
# ================================================

import os

# ─── Trading Mode ───
TRADING_MODE = "PAPER"

# ─── Capital ───
PAPER_CAPITAL = 1000.0
REAL_CAPITAL = 20.0

# ─── Risk Limits ───
MAX_POSITIONS = 3
POSITION_SIZE_PCT = 10
STOP_LOSS_PCT = 3.0
TAKE_PROFIT_PCT = 5.0
DAILY_LOSS_LIMIT = 20.0
TOTAL_LOSS_LIMIT = 50.0

# ─── Scan Settings ───
SCAN_INTERVAL_SECONDS = 60
# LOWERED THRESHOLDS — trades will actually fire!
MIN_CONFIDENCE = 40
MIN_EDGE = 40

# ─── Trading Pairs ───
COINS = [
    "bitcoin", "ethereum", "ripple", "solana",
    "cardano", "polkadot", "chainlink", "matic-network"
]
COIN_SYMBOLS = {
    "bitcoin": "BTC", "ethereum": "ETH", "ripple": "XRP", "solana": "SOL",
    "cardano": "ADA", "polkadot": "DOT", "chainlink": "LINK", "matic-network": "MATIC"
}

# ─── CoinGecko API ───
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"

# ─── Agent Weights ───
AGENT_WEIGHTS = {
    "Trend": 1.0,
    "Momentum": 1.0,
    "Volatility": 1.0,
    "SupportResist": 1.0,
    "MeanReversion": 1.0
}

VERBOSE = True
