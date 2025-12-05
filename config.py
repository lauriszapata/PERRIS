import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # Bot Identity
    BOT_NAME = "PERRIS_ETHUSDT_OPTIMIZADO"  # 🎯 +$736 en 4 meses con Vol 1.5x + DI
    
    # API Keys
    API_KEY = os.getenv("BINANCE_API_KEY")
    API_SECRET = os.getenv("BINANCE_API_SECRET")
    
    # Fees
    COMMISSION_RATE = 0.0005 # 0.05% (Standard Binance Futures)

    # ============================================================================
    # 🎯 CONFIGURACIÓN MÁS CONSISTENTE: 12/14 MESES POSITIVOS
    # ============================================================================
    # 
    # BACKTEST VERIFICADO:
    # → 12 de 14 meses positivos (86%)
    # → PnL: $121.48 en 14 meses (con $210 exposición)
    # → Win Rate: 47.5%
    # → Max Drawdown: -$67
    # → ~1.2 trades/día
    # 
    # CON 20X LEVERAGE:
    # → Cada WIN (8%): $210 * 0.08 * 20 = $336 🚀
    # → Cada LOSS (2%): $210 * 0.02 * 20 = $84
    # → Ratio: 4:1 (TP 8% / SL 2%)
    # 
    # ⚠️ RIESGO: MUY ALTO - 20x puede liquidarte rápido
    # ============================================================================
    
    # 🎯 SOLO ETHUSDT - El único consistentemente rentable en backtests
    # Backtest 4 meses (Ago-Nov 2025): +$736 con filtros mejorados
    SYMBOLS = [
        "ETH/USDT",   # Ethereum - El ganador
    ]
    TIMEFRAME = "15m"
    
    # --- Trading Parameters 10X ---
    LEVERAGE = 10  # 10x Leverage - Máximo seguro para $700
    MAX_OPEN_SYMBOLS = 1  # Solo 1 posición para controlar riesgo
    RISK_PER_TRADE = 0.02  # 2% risk per trade
    
    # ============================================================================
    # 💰 EXPOSICIÓN CONSERVADORA CON 10X
    # ============================================================================
    # 
    # Tu cuenta:     ~$700 USDT
    # Exposición:    $210 (30% del balance) x 10x = $2,100 posición
    # Cada WIN:      $168 (8% de $2,100)
    # Cada LOSS:     $42 (2% de $2,100)
    # Ratio:         4:1 (TP 8% / SL 2%)
    #
    FIXED_TRADE_EXPOSURE_USD = 210  # 30% de tu cuenta
    # ============================================================================
    
    # Risk Management - CONTROLADO
    DAILY_DRAWDOWN_LIMIT = -0.15  # -15% daily limit ($105 max pérdida diaria)
    MAX_TRADES_PER_HOUR = 2 # Pocos trades = más selectivos
    RISK_PER_TRADE_PCT = 0 # Set to 0 to use FIXED_TRADE_EXPOSURE_USD
    MAX_TOTAL_EXPOSURE_USD = 210  # 1 posición x $210
    MIN_NOTIONAL_USD = 100 # Minimum order value
    SYMBOL_COOLDOWN_MINUTES = 60  # 1 hora cooldown - del backtest
    MAX_POSITION_DURATION_MINUTES = 480 # 8 horas max (32 velas de 15m)
    
    # --- Trading Schedule: 12-22 UTC (del backtest) ---
    TRADING_HOURS_START = 12  # 12:00 UTC
    TRADING_HOURS_END = 22    # 22:00 UTC
    TRADING_DAYS = [0, 1, 2, 3, 4, 5, 6] # All days
    
    # --- Profit Taking: TP 8% (del backtest) ---
    TP_LEVELS = [
        {"pct": 0.08, "close_pct": 1.0, "name": "TP_8PCT"}, # 8% -> Close 100%
    ]
    
    # --- Stop Loss: 2% (del backtest) ---
    FIXED_SL_PCT = 0.02  # 2% Stop Loss (Ratio 4:1)
    BREAKEVEN_TRIGGER_PCT = 0.04  # BE al 4% de ganancia
    DEFAULT_SL_ATR_MULTIPLIER = 1.5
    
    # --- Trailing Stop ---
    TRAILING_STOP_ENABLED = True
    TRAILING_STOP_STEP = 0.01  # Update SL every 1% price movement
    
    # --- Dynamic Scalping (DISABLED) ---
    DYNAMIC_SCALPING_START = 0.030
    DYNAMIC_SCALPING_INCREMENT = 0.005
    DYNAMIC_SCALPING_CLOSE_PCT = 0.25
    
    # --- Filters MEJORADOS (Vol 1.5x + DI Confirmation) ---
    # Backtest: +$736 en 4 meses, DD $168, 75 trades
    ATR_MIN_PCT = 0.001
    ATR_MAX_PCT = 0.03
    MAX_SPREAD_PCT = 0.15
    MAX_FUNDING_RATE = 0.002
    ADX_MIN = 20  # ADX 20 del backtest ganador
    VOLUME_MIN_MULTIPLIER = 1.5  # 🔥 MEJORADO: Vol > 1.5x Media (antes 0.8)
    DI_CONFIRMATION = True  # 🔥 NUEVO: +DI > -DI para LONG, -DI > +DI para SHORT
    
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
    
    # === MODO REAL ===
    # True = Solo simula trades (no ejecuta en Binance)
    # False = Ejecuta trades reales
    DRY_RUN = False  # 🟢 MODO REAL ACTIVADO

    @staticmethod
    def validate():
        if not Config.API_KEY or not Config.API_SECRET:
            raise ValueError("API_KEY and API_SECRET must be set in .env file")
