import unittest
from unittest.mock import MagicMock
import pandas as pd
from modules.execution.bot_logic import BotLogic
from modules.managers.structure_manager import StructureManager
from config import Config

class TestStructureExit(unittest.TestCase):
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

    def test_structure_manager_swings(self):
        # Create a DF with a clear Swing High and Swing Low
        # Swing High at index 2 (105)
        # Swing Low at index 6 (95)
        data = {
            'high': [100, 102, 105, 102, 100, 98, 96, 98, 100, 102],
            'low':  [98,  100, 103, 100, 98,  96, 95, 96, 98,  100],
            'close': [99, 101, 104, 101, 99,  97, 96, 97, 99,  101],
            'volume': [100]*10,
            'ATR': [1.0]*10,
            'EMA20': [100]*10,
            'EMA50': [100]*10,
            'EMA200': [100]*10
        }
        df = pd.DataFrame(data)
        
        swings = StructureManager.get_last_swings(df)
        self.assertIsNotNone(swings)
        self.assertEqual(swings['swing_high'], 105) # Index 2
        self.assertEqual(swings['swing_low'], 95)   # Index 6

    def test_structure_exit_short(self):
        # Setup SHORT position
        symbol = "BTC/USDT"
        position = {
            "direction": "SHORT",
            "entry_price": 100.0,
            "size": 1.0,
            "sl_price": 110.0,
            "atr_entry": 1.0,
            "p_min": 100.0,
            "entry_time": 0,
            "p_max": 100.0
        }
        
        # Create DF where Close > Swing High
        # Swing High is 105.
        # We need the "closed candle" (index -2) to break the structure.
        # Index -1 is "current open", Index -2 is "last closed".
        # So index 8 must be > 105.
        data = {
            'high': [100, 102, 105, 102, 100, 98, 96, 98, 106, 106], # Index 8 High 106
            'low':  [98,  100, 103, 100, 98,  96, 95, 96, 104, 104],
            'close': [99, 101, 104, 101, 99,  97, 96, 97, 106, 106], # Index 8 Close 106 > 105
            'volume': [100]*10,
            'ATR': [1.0]*10,
            'EMA20': [100]*10,
            'EMA50': [100]*10,
            'EMA200': [100]*10
        }
        df = pd.DataFrame(data)
        
        # Run manage_position
        self.bot._manage_position(symbol, position, df)
        
        # Verify Close Called
        self.executor.close_position.assert_called_with(symbol, "SHORT", 1.0)
        self.state.clear_position.assert_called_with(symbol)

if __name__ == '__main__':
    unittest.main()
