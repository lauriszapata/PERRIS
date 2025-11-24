import unittest
from unittest.mock import MagicMock
import time
from modules.execution.bot_logic import BotLogic
from config import Config

class TestRealTimeEarlyExit(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.state = MagicMock()
        self.executor = MagicMock()
        self.bot = BotLogic(self.client, self.state, self.executor)
        self.bot.last_monitor_log = 0
        
        # Mock State
        self.state.state = {'positions': {}}
        
        # Mock Config
        Config.TAKE_PROFIT_LEVELS = []

    def test_real_time_early_invalidation_short(self):
        # Setup SHORT position
        # Entry: 100, ATR: 2
        # Early Exit Threshold: 100 + (1.5 * 2) = 103
        
        symbol = "BTC/USDT"
        pos_data = {
            "direction": "SHORT",
            "entry_price": 100.0,
            "size": 1.0,
            "sl_price": 106.0,
            "atr_entry": 2.0,
            "p_min": 100.0,
            "entry_time": time.time(),
            "p_max": 100.0
        }
        self.state.state['positions'] = {symbol: pos_data}
        
        # Mock Market Price > 103 (e.g., 104)
        self.client.get_market_price.return_value = 104.0
        
        # Run monitor_positions
        self.bot._monitor_positions()
        
        # Verify Close Called
        self.executor.close_position.assert_called_with(symbol, "SHORT", 1.0)
        self.state.clear_position.assert_called_with(symbol)

    def test_real_time_early_invalidation_long(self):
        # Setup LONG position
        # Entry: 100, ATR: 2
        # Early Exit Threshold: 100 - (1.5 * 2) = 97
        
        symbol = "ETH/USDT"
        pos_data = {
            "direction": "LONG",
            "entry_price": 100.0,
            "size": 1.0,
            "sl_price": 94.0,
            "atr_entry": 2.0,
            "p_max": 100.0,
            "entry_time": time.time(),
            "p_min": 100.0
        }
        self.state.state['positions'] = {symbol: pos_data}
        
        # Mock Market Price < 97 (e.g., 96)
        self.client.get_market_price.return_value = 96.0
        
        # Run monitor_positions
        self.bot._monitor_positions()
        
        # Verify Close Called
        self.executor.close_position.assert_called_with(symbol, "LONG", 1.0)
        self.state.clear_position.assert_called_with(symbol)

if __name__ == '__main__':
    unittest.main()
