import os

TRADING_MODE = os.environ.get("TRADING_MODE", "PAPER")
PAPER_CAPITAL = float(os.environ.get("PAPER_CAPITAL", "1000"))
LIVE_CAPITAL = float(os.environ.get("LIVE_CAPITAL", "20"))

MAX_POSITIONS = int(os.environ.get("MAX_POSITIONS", "3"))
MIN_EDGE = int(os.environ.get("MIN_EDGE", "75"))
POSITION_SIZE_PCT = 0.10
STOP_LOSS_PCT = 3.0
TAKE_PROFIT_PCT = 5.0
DAILY_LOSS_LIMIT = 50.0

SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "90"))

COINS = [
    {"symbol": "BTC/USD",  "coingecko_id": "bitcoin",      "name": "Bitcoin"},
    {"symbol": "ETH/USD",  "coingecko_id": "ethereum",     "name": "Ethereum"},
    {"symbol": "XRP/USD",  "coingecko_id": "ripple",       "name": "XRP"},
    {"symbol": "SOL/USD",  "coingecko_id": "solana",       "name": "Solana"},
    {"symbol": "ADA/USD",  "coingecko_id": "cardano",      "name": "Cardano"},
    {"symbol": "DOT/USD",  "coingecko_id": "polkadot",     "name": "Polkadot"},
    {"symbol": "LINK/USD", "coingecko_id": "chainlink",    "name": "Chainlink"},
    {"symbol": "MATIC/USD","coingecko_id": "matic-network","name": "Polygon"},
]

KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
KRAKEN_SECRET = os.environ.get("KRAKEN_SECRET", "")

WEB_PORT = int(os.environ.get("PORT", "5000"))