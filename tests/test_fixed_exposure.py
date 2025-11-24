import unittest
from unittest.mock import MagicMock
from modules.managers.risk_manager import RiskManager
from config import Config

class TestFixedExposure(unittest.TestCase):
    def setUp(self):
        # Mock Config
        Config.FIXED_TRADE_EXPOSURE_USD = 125
        Config.MAX_TOTAL_EXPOSURE_USD = 390
        Config.LEVERAGE = 1
        Config.MAX_OPEN_SYMBOLS = 3
        
        # Mock Client
        self.client = MagicMock()
        self.client.exchange.market.return_value = {
            'limits': {'amount': {'min': 0.001}}
        }

    def test_fixed_exposure_sizing(self):
        # Scenario 1: Tight Stop (Should not affect size)
        entry = 100
        sl = 99
        balance = 1000
        current_positions = {}
        
        size_tight = RiskManager.calculate_position_size(entry, sl, balance, self.client, "ETH/USDT", current_positions)
        exposure_tight = size_tight * entry
        
        self.assertAlmostEqual(exposure_tight, 125.0, places=1)
        
        # Scenario 2: Wide Stop (Should not affect size)
        sl_wide = 90
        size_wide = RiskManager.calculate_position_size(entry, sl_wide, balance, self.client, "ETH/USDT", current_positions)
        exposure_wide = size_wide * entry
        
        self.assertAlmostEqual(exposure_wide, 125.0, places=1)
        
        # Ensure sizes are identical (since entry price is same)
        self.assertEqual(size_tight, size_wide)

if __name__ == '__main__':
    unittest.main()
