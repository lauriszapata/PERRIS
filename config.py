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
    # --- Trading Parameters ---
    LEVERAGE = 3  # SNIPER STRATEGY: 3x Leverage (High Reward)
    MAX_OPEN_SYMBOLS = 1  # SNIPER STRATEGY: Focus on best opportunity
    RISK_PER_TRADE = 0.015  # 1.5% risk per trade
    FIXED_TRADE_EXPOSURE_USD = 450  # Fixed $450 exposure (~$150 margin @ 3x)
    
    # Risk Management
    DAILY_DRAWDOWN_LIMIT = -0.03  # -3%
    MAX_TRADES_PER_HOUR = 6 # Allow up to 6 positions per hour
    RISK_PER_TRADE_PCT = 0.005 
    # MAX_EXPOSURE_USD = 500 # DEPRECATED
    MAX_TOTAL_EXPOSURE_USD = 500  # Maximum total exposure in USD
    MIN_NOTIONAL_USD = 100 # Minimum order value (Binance requirement)
    SYMBOL_COOLDOWN_MINUTES = 30  # Wait 30 minutes before re-entering same symbol
    
    # --- Profit Taking (SNIPER STRATEGY) ---
    # Single Fixed TP at 1.5%
    TP_LEVELS = [
        {"pct": 0.025, "close_pct": 1.0, "name": "TP_FINAL"}, # 2.5% -> Close 100% (High Reward)
    ]
    
    # --- Stop Loss (SNIPER STRATEGY) ---
    FIXED_SL_PCT = 0.030  # 3.0% Fixed Stop Loss
    BREAKEVEN_TRIGGER_PCT = 0.010  # Move to BE at 1.0% profit
    DEFAULT_SL_ATR_MULTIPLIER = 2.5 # Fallback if Fixed SL is disabled
    
    # --- Dynamic Scalping (DISABLED FOR SNIPER) ---
    DYNAMIC_SCALPING_START = 0.050  # 5.0% (Unlikely to hit with 1.5% TP)
    DYNAMIC_SCALPING_INCREMENT = 0.010
    DYNAMIC_SCALPING_CLOSE_PCT = 0.10
    
    # --- Filters (EXTREME CRITERIA) ---
    ATR_MIN_PCT = 0.0025 # Min 0.25% volatility (Avoid dead markets)
    ATR_MAX_PCT = 0.025  # Max 2.5% volatility per candle
    MAX_SPREAD_PCT = 0.002
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
