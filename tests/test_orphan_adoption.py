import unittest
from unittest.mock import MagicMock
import time
from modules.execution.bot_logic import BotLogic

class TestOrphanAdoption(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_state = MagicMock()
        self.mock_executor = MagicMock()
        
        # Mock state dictionary
        self.mock_state.state = {'positions': {}}
        
        self.bot = BotLogic(self.mock_client, self.mock_state, self.mock_executor)
        
        # Mock Config
        self.bot.last_monitor_log = 0

    def test_adopt_orphan_in_monitor(self):
        # Setup: No local positions
        self.mock_state.state['positions'] = {}
        
        # Mock Binance returning a position
        mock_position = {
            'symbol': 'BTC/USDT',
            'contracts': 0.1,
            'side': 'long',
            'entryPrice': 50000.0,
            'markPrice': 50500.0,
            'unrealizedPnl': 50.0,
            'percentage': 1.0,
            'notional': 5000.0
        }
        self.mock_client.get_all_positions.return_value = [mock_position]
        self.mock_client.fetch_ohlcv.return_value = [] # Mock empty OHLCV for simplicity
        self.mock_client.get_open_orders.return_value = []
        
        # Run monitor
        self.bot._monitor_positions()
        
        # Verify set_position was called (adoption happened)
        self.mock_state.set_position.assert_called()
        
        # Verify the arguments passed to set_position
        args, _ = self.mock_state.set_position.call_args
        symbol = args[0]
        pos_data = args[1]
        
        self.assertEqual(symbol, 'BTC/USDT')
        self.assertEqual(pos_data['size'], 0.1)
        self.assertEqual(pos_data['entry_price'], 50000.0)
        self.assertEqual(pos_data['direction'], 'LONG')
        
        print("✅ Orphan adoption test passed!")

if __name__ == '__main__':
    unittest.main()
