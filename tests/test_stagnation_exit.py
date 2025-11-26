import unittest
from unittest.mock import MagicMock
import time
import pandas as pd
from modules.execution.bot_logic import BotLogic
from config import Config

class TestStagnationExit(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.state = MagicMock()
        self.executor = MagicMock()
        self.bot = BotLogic(self.client, self.state, self.executor)
        
        # Mock State
        self.state.state = {'positions': {}}
        self.state.get_position.return_value = None
        
        # Mock Config
        Config.TP_LEVELS = []

    def test_stagnation_exit_triggered(self):
        # Setup position open for 50 mins with negative PnL
        symbol = "BTC/USDT"
        entry_time = time.time() - (50 * 60) # 50 mins ago
        entry_price = 100.0
        
        position = {
            "direction": "LONG",
            "entry_price": entry_price,
            "size": 1.0,
            "sl_price": 90.0,
            "atr_entry": 1.0,
            "p_max": 100.0,
            "entry_time": entry_time,
            "p_min": 100.0
        }
        
        # Current price 99 (Loss)
        df = pd.DataFrame({
            'timestamp': [1]*10,
            'open': [100]*10,
            'high': [100]*10,
            'low': [99]*10,
            'close': [99]*10, # Close 99 < Entry 100
            'volume': [100]*10,
            'ATR': [1.0]*10,
            'EMA20': [100]*10,
            'EMA50': [100]*10,
            'EMA200': [100]*10
        })
        
        self.bot._manage_position(symbol, position, df)
        
        # Verify Close Called
        self.executor.close_position.assert_called_with(symbol, "LONG", 1.0)
        self.state.clear_position.assert_called_with(symbol)

    def test_stagnation_exit_not_triggered_positive_pnl(self):
        # Setup position open for 50 mins with POSITIVE PnL
        symbol = "BTC/USDT"
        entry_time = time.time() - (50 * 60) # 50 mins ago
        entry_price = 100.0
        
        position = {
            "direction": "LONG",
            "entry_price": entry_price,
            "size": 1.0,
            "sl_price": 90.0,
            "atr_entry": 1.0,
            "p_max": 100.0,
            "entry_time": entry_time,
            "p_min": 100.0
        }
        
        # Current price 101 (Profit)
        df = pd.DataFrame({
            'timestamp': [1]*10,
            'open': [100]*10,
            'high': [101]*10,
            'low': [100]*10,
            'close': [101]*10, # Close 101 > Entry 100
            'volume': [100]*10,
            'ATR': [1.0]*10,
            'EMA20': [100]*10,
            'EMA50': [100]*10,
            'EMA200': [100]*10
        })
        
        self.bot._manage_position(symbol, position, df)
        
        # Verify Close NOT Called
        self.executor.close_position.assert_not_called()

if __name__ == '__main__':
    unittest.main()
