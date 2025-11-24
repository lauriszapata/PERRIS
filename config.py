import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # API Keys
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_API_SECRET")
    
    # Fees
    COMMISSION_RATE = 0.00045 # 0.045% (Standard 0.05% - 10% BNB Discount)

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
    MTF_TIMEFRAME = "1h" # Multi-Timeframe Trend Filter
    LEVERAGE = 1  # Fixed at 1x as requested
    
    # Risk Management
    MAX_OPEN_SYMBOLS = 1 # Only 1 position at a time
    DAILY_DRAWDOWN_LIMIT = -0.03  # -3%
    MAX_TRADES_PER_HOUR = 6 # Allow up to 6 positions per hour
    RISK_PER_TRADE_PCT = 0.005 
    # MAX_EXPOSURE_USD = 500 # DEPRECATED
    MAX_TOTAL_EXPOSURE_USD = 130  # Only 1 position × 130 USD max
    FIXED_TRADE_EXPOSURE_USD = 125 # Fixed exposure per trade: 125 USD (range 120-130 USD)
    
    # Profit Taking - INFINITE SCALPING STRATEGY (Optimized for better R:R)
    # Fixed levels secure base profits with smaller closes, then dynamic levels every 0.1% forever
    TAKE_PROFIT_LEVELS = [
        {"pct": 0.012, "close_pct": 0.20, "name": "P1"},  # 1.2% -> Covers fees + profit. Close 20%
        {"pct": 0.016, "close_pct": 0.20, "name": "P2"},  # 1.6%
        {"pct": 0.020, "close_pct": 0.20, "name": "P3"},  # 2.0%
        {"pct": 0.025, "close_pct": 0.20, "name": "P4"},  # 2.5%
        # Remaining 20% rides the dynamic scalper
    ]
    # After P6: Only 30% closed (was 60%), 70% remains for infinite scalping (better R:R)
    
    # Dynamic infinite scalping (after fixed levels)
    DYNAMIC_SCALPING_START = 0.025  # Start after P4
    DYNAMIC_SCALPING_INCREMENT = 0.005  # Every 0.5% (reduce noise)
    DYNAMIC_SCALPING_CLOSE_PCT = 0.05
    # This allows the position to ride indefinitely, taking small profits every 0.1%
    # SL will eventually close it, or it keeps taking profits forever on a runner!
    
    BREAKEVEN_TRIGGER_PCT = 0.008 # Move SL to Entry when profit > 0.8%
    
    # Filters
    # Filters
    ATR_MIN_PCT = 0.0025 # Corrected to 0.25% (was 0.25 which meant 25%)
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
