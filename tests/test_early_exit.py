import unittest
from unittest.mock import MagicMock
import pandas as pd
from modules.execution.bot_logic import BotLogic
from modules.managers.atr_manager import ATRManager
from config import Config

class TestEarlyExit(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.state = MagicMock()
        self.executor = MagicMock()
        self.bot = BotLogic(self.client, self.state, self.executor)
        
        # Mock State
        self.state.state = {'positions': {}}
        self.state.get_position.return_value = None
        
        # Mock Config
        Config.TAKE_PROFIT_LEVELS = []

    def test_early_invalidation_short(self):
        # Setup SHORT position
        # Entry: 100, ATR: 2
        # Early Exit Threshold: 100 + (1.5 * 2) = 103
        
        symbol = "BTC/USDT"
        position = {
            "direction": "SHORT",
            "entry_price": 100.0,
            "size": 1.0,
            "sl_price": 106.0, # 3 ATR initial stop
            "atr_entry": 2.0,
            "p_min": 100.0,
            "entry_time": 0,
            "p_max": 100.0 # Not used for short but needed for dict
        }
        
        # Create DF where price hits 104 (above 103 threshold)
        df = pd.DataFrame({
            'timestamp': [1, 2, 3],
            'open': [100, 102, 104],
            'high': [101, 103, 105],
            'low': [99, 101, 103],
            'close': [100, 102, 104], # Current close 104
            'volume': [100, 100, 100],
            'ATR': [2.0, 2.0, 2.0],
            'EMA20': [100, 100, 100],
            'EMA50': [100, 100, 100],
            'EMA200': [100, 100, 100]
        })
        
        # Run manage_position
        self.bot._manage_position(symbol, position, df)
        
        # Verify Close Called
        self.executor.close_position.assert_called_with(symbol, "SHORT", 1.0)
        self.state.clear_position.assert_called_with(symbol)

    def test_atr_manager_trailing_tightened(self):
        # Verify multiplier is 1.5
        # LONG: P_max - 1.5 * ATR
        # P_max: 100, ATR: 2 -> SL: 97
        
        sl = ATRManager.calculate_trailing_stop(90, 100, 2.0, "LONG", 95)
        self.assertEqual(sl, 97.0)
        
        # SHORT: P_min + 1.5 * ATR
        # P_min: 100, ATR: 2 -> SL: 103
        sl = ATRManager.calculate_trailing_stop(110, 100, 2.0, "SHORT", 105)
        self.assertEqual(sl, 103.0)

if __name__ == '__main__':
    unittest.main()
