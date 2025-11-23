import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # API Keys
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_API_SECRET")

    # Trading Parameters
    SYMBOLS = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "TRX/USDT", "DOT/USDT",
        "POL/USDT", "LINK/USDT", "LTC/USDT", "BCH/USDT", "ATOM/USDT",  # POL (was MATIC)
        "UNI/USDT", "ETC/USDT", "FIL/USDT", "NEAR/USDT", "XMR/USDT",
        "XLM/USDT", "HBAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT",
        "RENDER/USDT", "INJ/USDT", "STX/USDT", "SUI/USDT", "TIA/USDT"  # Updated symbols
    ]
    TIMEFRAME = "15m"
    LEVERAGE = 3  # Reduced from 10x for safer trading
    
    # Risk Management
    MAX_OPEN_SYMBOLS = 3
    DAILY_DRAWDOWN_LIMIT = -0.03  # -3%
    MAX_TRADES_PER_HOUR = 3
    MAX_EXPOSURE_USD = 500 # Max exposure per trade in USD
    MAX_TOTAL_EXPOSURE_USD = 1000  # Max total portfolio exposure (all positions combined)
    
    # Profit Taking - INFINITE SCALPING STRATEGY (Optimized for better R:R)
    # Fixed levels secure base profits with smaller closes, then dynamic levels every 0.1% forever
    TAKE_PROFIT_LEVELS = [
        {"pct": 0.003, "close_pct": 0.05, "name": "P1"},  # 0.3% -> 1.5 USD -> close 5% (was 10%)
        {"pct": 0.004, "close_pct": 0.05, "name": "P2"},  # 0.4% -> 2.0 USD -> close 5%
        {"pct": 0.005, "close_pct": 0.05, "name": "P3"},  # 0.5% -> 2.5 USD -> close 5%
        {"pct": 0.006, "close_pct": 0.05, "name": "P4"},  # 0.6% -> 3.0 USD -> close 5%
        {"pct": 0.008, "close_pct": 0.05, "name": "P5"},  # 0.8% -> 4.0 USD -> close 5%
        {"pct": 0.010, "close_pct": 0.05, "name": "P6"},  # 1.0% -> 5.0 USD -> close 5%
    ]
    # After P6: Only 30% closed (was 60%), 70% remains for infinite scalping (better R:R)
    
    # Dynamic infinite scalping (after fixed levels)
    DYNAMIC_SCALPING_START = 0.010  # Start at 1.0% (after P6)
    DYNAMIC_SCALPING_INCREMENT = 0.001  # Every 0.1% additional
    DYNAMIC_SCALPING_CLOSE_PCT = 0.05  # Close 5% each time (can take 14 more levels now instead of 8)
    # This allows the position to ride indefinitely, taking small profits every 0.1%
    # SL will eventually close it, or it keeps taking profits forever on a runner!
    
    # Filters
    ATR_MIN_PCT = 0.20
    ATR_MAX_PCT = 2.5
    MAX_SPREAD_PCT = 0.03
    MAX_FUNDING_RATE = 0.03 # +/- 0.03%
    
    # Paths
    STATE_FILE = "bot_state.json"
    LOG_FILE = "bot_trading.log"

    # Health Check
    LATENCY_PAUSE_MS = 800
    LATENCY_RESUME_MS = 500
    MAX_DATA_DELAY_SEC = 2
    
    # Retry Logic
    MAX_RETRIES = 3
    RETRY_DELAY = 1 # seconds

    @staticmethod
    def validate():
        if not Config.API_KEY or not Config.API_SECRET:
            raise ValueError("API_KEY and API_SECRET must be set in .env file")
