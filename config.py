import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Bot Identity
    BOT_NAME = "PERRIS_SNIPER_3X_WINNER"
    
    # API Keys
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_API_SECRET")
    
    # Fees
    COMMISSION_RATE = 0.00045 # 0.045% (Standard 0.05% - 10% BNB Discount)

    # Trading Parameters
    SYMBOLS = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT",
        "DOGE/USDT", "ADA/USDT", "AVAX/USDT",
        "LTC/USDT", "ATOM/USDT",
        "UNI/USDT", "ETC/USDT", "FIL/USDT", "XMR/USDT",
        "XLM/USDT", "HBAR/USDT", "ARB/USDT",
        "RENDER/USDT", "INJ/USDT", "STX/USDT", "SUI/USDT"
    ]
    TIMEFRAME = "15m"
    # --- Trading Parameters ---
    LEVERAGE = 1  # 1x Leverage (Safe)
    MAX_OPEN_SYMBOLS = 1  # Single simultaneous position
    RISK_PER_TRADE = 0.015  # 1.5% risk per trade
    FIXED_TRADE_EXPOSURE_USD = 450  # Fixed $450 exposure
    
    # Risk Management
    DAILY_DRAWDOWN_LIMIT = -0.03  # -3%
    MAX_TRADES_PER_HOUR = 6 # Allow up to 6 positions per hour
    RISK_PER_TRADE_PCT = 0 # Set to 0 to use FIXED_TRADE_EXPOSURE_USD
    # MAX_EXPOSURE_USD = 500 # DEPRECATED
    MAX_TOTAL_EXPOSURE_USD = 2000  # Increased to allow full exposure
    MIN_NOTIONAL_USD = 100 # Minimum order value (Binance requirement)
    SYMBOL_COOLDOWN_MINUTES = 30  # Wait 30 minutes before re-entering same symbol
    
    # --- Profit Taking ---
    # Single Fixed TP at 0.28%
    TP_LEVELS = [
        {"pct": 0.0028, "close_pct": 1.0, "name": "TP_FINAL"}, # 0.28% -> Close 100%
    ]
    
    # --- Stop Loss ---
    FIXED_SL_PCT = 0.010  # 1.0% Fixed Stop Loss
    BREAKEVEN_TRIGGER_PCT = 0.010  # Move to BE at 1.0% profit
    DEFAULT_SL_ATR_MULTIPLIER = 2.5 # Fallback if Fixed SL is disabled
    
    # --- Trailing Stop ---
    TRAILING_STOP_ENABLED = False # Disabled
    TRAILING_STOP_STEP = 0.001  # Update SL every 0.1% price movement
    
    # --- Dynamic Scalping (DISABLED) ---
    DYNAMIC_SCALPING_START = 0.050  # 5.0%
    DYNAMIC_SCALPING_INCREMENT = 0.010
    DYNAMIC_SCALPING_CLOSE_PCT = 0.10
    
    # --- Filters (EXTREME CRITERIA) ---
    ATR_MIN_PCT = 0.0025 # Min 0.25% volatility (Avoid dead markets)
    ATR_MAX_PCT = 0.025  # Max 2.5% volatility per candle
    MAX_SPREAD_PCT = 0.01 # Relaxed from 0.002 to 0.01 (1%) to match backtest
    MAX_FUNDING_RATE = 0.0005
    ADX_MIN = 25  # Strong Trend Only
    VOLUME_MIN_MULTIPLIER = 1.3  # 30% above average volume
    
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
