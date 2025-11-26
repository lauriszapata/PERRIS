import pytest
from config import Config

def test_sniper_config():
    """Verify Sniper Strategy Configuration"""
    assert Config.LEVERAGE == 3
    assert Config.MAX_OPEN_SYMBOLS == 1
    assert Config.FIXED_TRADE_EXPOSURE_USD == 150
    assert Config.FIXED_SL_PCT == 0.030
    assert Config.BREAKEVEN_TRIGGER_PCT == 0.010
    
    # Verify TP Levels
    assert len(Config.TP_LEVELS) == 1
    assert Config.TP_LEVELS[0]['name'] == 'TP_FINAL'
    assert Config.TP_LEVELS[0]['pct'] == 0.025
    assert Config.TP_LEVELS[0]['close_pct'] == 1.0

def test_extreme_filters():
    """Verify Extreme Entry Filters"""
    assert Config.ADX_MIN == 25
    assert Config.VOLUME_MIN_MULTIPLIER == 1.3
    assert Config.ATR_MAX_PCT == 0.025
