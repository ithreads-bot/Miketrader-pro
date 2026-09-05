# mike_config.py — Mike Trader Pro Cloud Configuration
# ================================================

import os

# ─── Trading Mode ───
# "SIGNAL" = alerts only (manual trading)
# "PAPER"  = fake money trades ($1000 test capital)
# "AUTO"   = real money trades (connects to exchange API)
TRADING_MODE = "PAPER"

# ─── Capital ───
PAPER_CAPITAL = 1000.0          # Fake money for testing
REAL_CAPITAL = 20.0             # Real money (only used in AUTO mode)

# ─── Risk Limits ───
MAX_POSITIONS = 5               # Max open trades at once (was 3)
POSITION_SIZE_PCT = 10          # % of capital per trade
STOP_LOSS_PCT = 2.0             # 2% stop loss (was 3% — faster trades)
TAKE_PROFIT_PCT = 3.0           # 3% take profit (was 5% — faster trades)
POSITION_TIMEOUT_SECONDS = 14400  # Auto-close trades open longer than 4 hours (prevents deadlock)
DAILY_LOSS_LIMIT = 20.0         # Max $20 loss per day
TOTAL_LOSS_LIMIT = 50.0         # Max $50 total loss

# ─── Scan Settings ───
SCAN_INTERVAL_SECONDS = 60      # How often to scan (was 90, now faster)
MIN_CONFIDENCE = 55             # Minimum agent score to trade (was higher, now 55)
MIN_EDGE = 60                   # Minimum combined edge to trade (was 75, now 60)

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
# No API key needed for free tier (rate limited)

# ─── Agent Weights (Auto-Optimizer will adjust these) ───
AGENT_WEIGHTS = {
    "Trend": 1.0,
    "Momentum": 1.0,
    "Volatility": 1.0,
    "SupportResist": 1.0,
    "MeanReversion": 1.0
}

# ─── Fees (Paper Trading Realism) ───
FEE_PCT = 0.5                   # Round-trip fee % per trade (exchange fee + slippage)

# ─── Market Crash Guard ───
CRASH_GUARD_ENABLED = True      # Skip NEW trades when market is crashing
CRASH_GUARD_BTC_DROP = -5.0     # Pause new trades if BTC 24h change is worse than this

# ─── State Persistence (NEVER lose learning again) ───
STATE_FILE = "bot_state.json"   # Bot memory file — weights, stats, capital, history
SAVE_EVERY_SCANS = 10           # Auto-save every N scans + every trade close + on stop

# ─── Logging ───
VERBOSE = True
