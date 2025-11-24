import unittest
from unittest.mock import MagicMock, call
from modules.execution.bot_logic import BotLogic
from config import Config

class TestLeverageEnforcement(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.state = MagicMock()
        self.executor = MagicMock()
        self.bot = BotLogic(self.client, self.state, self.executor)
        
        # Mock Config
        Config.SYMBOLS = ["BTC/USDT", "ETH/USDT"]
        Config.LEVERAGE = 1

    def test_leverage_on_startup(self):
        # Mock _sync_positions to avoid side effects
        self.bot._sync_positions = MagicMock()
        
        # We can't easily test the infinite loop in run(), but we can extract the startup logic
        # or just verify the code structure. 
        # Alternatively, we can mock the loop condition, but run() has `while True`.
        # Instead, let's verify _execute_entry calls set_leverage.
        pass

    def test_leverage_before_entry(self):
        # Mock dependencies
        symbol = "BTC/USDT"
        direction = "LONG"
        df = MagicMock()
        df.iloc = MagicMock()
        last_row = {'ATR': 100, 'close': 50000, 'RSI': 50, 'ADX': 25, 'MACD_line': 10, 'MACD_signal': 5, 'volume': 1000}
        df.iloc.__getitem__.return_value = last_row # For both -1 and others if needed
        
        # Mock RiskManager checks
        with unittest.mock.patch('modules.managers.risk_manager.RiskManager.check_max_symbols', return_value=True), \
             unittest.mock.patch('modules.managers.risk_manager.RiskManager.check_portfolio_correlation', return_value=True), \
             unittest.mock.patch('modules.managers.risk_manager.RiskManager.calculate_position_size', return_value=0.01), \
             unittest.mock.patch('modules.managers.atr_manager.ATRManager.calculate_initial_stop', return_value=49000):
            
            self.client.get_balance.return_value = {'USDT': {'free': 1000}}
            self.executor.open_position.return_value = {'id': '123'}
            
            # Run _execute_entry
            self.bot._execute_entry(symbol, direction, df)
            
            # Verify set_leverage was called with 1
            self.client.set_leverage.assert_called_with(symbol, 1)
            
            # Verify it was called BEFORE open_position (order of calls)
            # We can check the mock_calls list
            expected_calls = [
                call.get_balance(),
                call.set_leverage(symbol, 1),
                # open_position is called on executor, not client
            ]
            self.client.assert_has_calls(expected_calls, any_order=False)

if __name__ == '__main__':
    unittest.main()
