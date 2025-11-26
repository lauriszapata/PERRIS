import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.execution.bot_logic import BotLogic

class TestOrphanAdoption(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_state = MagicMock()
        self.mock_executor = MagicMock()
        
        # Mock state dictionary
        self.mock_state.state = {'positions': {}}
        
        self.bot = BotLogic(self.mock_client, self.mock_state, self.mock_executor)

    def test_orphan_adoption_long(self):
        # Setup Orphan Position (LONG)
        self.mock_client.get_all_positions.return_value = [{
            'symbol': 'BTC/USDT',
            'contracts': 1.0,
            'side': 'long',
            'entryPrice': 100.0,
            'unrealizedPnl': 0,
            'percentage': 0,
            'markPrice': 100.0,
            'notional': 100.0
        }]
        
        # Mock OHLCV for ATR calculation (fallback to 1% if fails, but let's mock it)
        self.mock_client.fetch_ohlcv.return_value = [
            [1000, 100, 101, 99, 100, 10] # Dummy candle
        ]
        
        # Mock Open Orders (Empty - so it places new ones)
        self.mock_client.get_open_orders.return_value = []
        
        # Run Sync
        self.bot._sync_positions()
        
        # Verify Adoption
        # 1. Check set_position called
        self.mock_state.set_position.assert_called()
        args, _ = self.mock_state.set_position.call_args
        symbol, data = args
        self.assertEqual(symbol, 'BTC/USDT')
        self.assertEqual(data['direction'], 'LONG')
        
        # 2. Verify SL (3% below 100 = 97)
        self.mock_executor.set_stop_loss.assert_called_with('BTC/USDT', 'LONG', 97.0)
        
        # 3. Verify TP (1% above 100 = 101)
        self.mock_executor.set_take_profit.assert_called_with('BTC/USDT', 'LONG', 101.0)

    def test_orphan_adoption_short(self):
        # Setup Orphan Position (SHORT)
        self.mock_client.get_all_positions.return_value = [{
            'symbol': 'ETH/USDT',
            'contracts': 10.0,
            'side': 'short',
            'entryPrice': 200.0,
            'unrealizedPnl': 0,
            'percentage': 0,
            'markPrice': 200.0,
            'notional': 2000.0
        }]
        
        self.mock_client.fetch_ohlcv.return_value = [] # Fail OHLCV to trigger fallback
        self.mock_client.get_open_orders.return_value = []
        
        # Run Sync
        self.bot._sync_positions()
        
        # Verify Adoption
        # 1. Check set_position called
        self.mock_state.set_position.assert_called()
        args, _ = self.mock_state.set_position.call_args
        symbol, data = args
        self.assertEqual(symbol, 'ETH/USDT')
        self.assertEqual(data['direction'], 'SHORT')
        
        # 2. Verify SL (3% above 200 = 206)
        self.mock_executor.set_stop_loss.assert_called_with('ETH/USDT', 'SHORT', 206.0)
        
        # 3. Verify TP (1% below 200 = 198)
        self.mock_executor.set_take_profit.assert_called_with('ETH/USDT', 'SHORT', 198.0)

    def test_orphan_adoption_existing_orders_lowercase(self):
        # Setup Orphan Position with EXISTING orders (lowercase types)
        self.mock_client.get_all_positions.return_value = [{
            'symbol': 'SOL/USDT',
            'contracts': 10.0,
            'side': 'long',
            'entryPrice': 50.0,
            'unrealizedPnl': 0,
            'percentage': 0,
            'markPrice': 50.0,
            'notional': 500.0
        }]
        
        self.mock_client.fetch_ohlcv.return_value = [] 
        
        # Mock Open Orders with LOWERCASE types
        self.mock_client.get_open_orders.return_value = [
            {'id': '1', 'type': 'stop_market', 'stopPrice': 48.5, 'side': 'sell'},
            {'id': '2', 'type': 'take_profit_market', 'stopPrice': 50.5, 'side': 'sell'}
        ]
        
        # Run Sync
        self.bot._sync_positions()
        
        # Verify Adoption
        self.mock_state.set_position.assert_called()
        
        # Verify NO new orders placed (because they already exist)
        self.mock_executor.set_stop_loss.assert_not_called()
        self.mock_executor.set_take_profit.assert_not_called()

if __name__ == '__main__':
    unittest.main()
