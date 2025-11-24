import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock
from modules.entry_signals import EntrySignals
from modules.execution.bot_logic import BotLogic
from config import Config

class TestOptimization(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.state = MagicMock()
        self.executor = MagicMock()
        self.bot = BotLogic(self.client, self.state, self.executor)
        
        # Mock Config
        Config.LEVERAGE = 1
        Config.TAKE_PROFIT_LEVELS = []

    def test_early_entry_signal(self):
        # Create a DF where Long Term Trend (EMA50 vs EMA200) is BAD
        # But Fast Trend (EMA8 vs EMA20) is GOOD + MACD + RSI are GOOD
        
        data = {
            'close': [100] * 10,
            'high': [101] * 10,
            'low': [99] * 10,
            'volume': [1000] * 10,
            'EMA8': [105] * 10,   # Fast Trend Bullish
            'EMA20': [100] * 10,
            'EMA21': [100] * 10,
            'EMA50': [90] * 10,   # Long Term Bearish (simulated fail)
            'EMA200': [110] * 10, 
            'ADX': [22] * 10,     # > 20 (Pass)
            'RSI': [60] * 10,     # > 35 (Pass)
            'MACD_line': [0.5] * 10,
            'MACD_signal': [0.1] * 10, # Bullish Cross
            'Vol_SMA20': [500] * 10,
            'ATR': [1] * 10
        }
        df = pd.DataFrame(data)
        
        # Mock TrendManager to FAIL Long Term Trend
        with unittest.mock.patch('modules.managers.trend_manager.TrendManager.check_trend', return_value=False):
            ok, results = EntrySignals.check_signals(df, "LONG")
            
            # Should be True because of Early Entry Logic
            self.assertTrue(ok, "Early Entry should trigger even if TrendManager fails")
            self.assertTrue(results['MACD']['status'])
            self.assertTrue(results['RSI']['status'])

    def test_macd_reversal_exit(self):
        # Simulate a LONG position
        position = {
            'direction': 'LONG',
            'entry_price': 100,
            'size': 1,
            'sl_price': 99,
            'p_max': 105,
            'p_min': 100,
            'atr_entry': 1,
            'entry_time': 0,
            'partials': {}
        }
        
        # Row 0: Prev Closed (Small Negative)
        row0 = {
            'MACD_hist': -0.1, 
            'EMA20': 101, 'EMA50': 100, 'high': 105, 'low': 100, 'close': 102, 'ATR': 1
        }
        # Row 1: Closed Candle (Big Negative -> Reversal)
        row1 = {
            'MACD_hist': -0.5, 
            'EMA20': 101, 'EMA50': 100, 'high': 105, 'low': 100, 'close': 102, 'ATR': 1
        }
        # Row 2: Current Open Candle (Irrelevant for this check)
        row2 = {
            'MACD_hist': -0.6, 
            'EMA20': 101, 'EMA50': 100, 'high': 105, 'low': 100, 'close': 102, 'ATR': 1
        }
    
        df = pd.DataFrame([row0, row1, row2]) # Row 1 is closed_candle, Row 0 is prev_closed
        
        # Mock executor close
        self.bot.executor.close_position.return_value = True
        
        # Run manage
        self.bot._manage_position("ETH/USDT", position, df)
        
        # Should call close_position
        self.bot.executor.close_position.assert_called()

if __name__ == '__main__':
    unittest.main()
