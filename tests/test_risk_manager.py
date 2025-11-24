import unittest
from unittest.mock import MagicMock
from modules.managers.risk_manager import RiskManager
from config import Config

class TestRiskManager(unittest.TestCase):
    def setUp(self):
        # Mock Config
        Config.RISK_PER_TRADE_PCT = 0.01
        Config.MAX_TOTAL_EXPOSURE_USD = 1000
        Config.LEVERAGE = 1
        Config.MAX_OPEN_SYMBOLS = 3
        Config.MAX_TRADES_PER_HOUR = 3
        
        # Mock Client
        self.client = MagicMock()
        # Mock market limits
        self.client.exchange.market.return_value = {
            'limits': {'amount': {'min': 0.001}}
        }

    def test_calculate_position_size_risk_based(self):
        # Balance: 1000
        # Risk: 1% = 10 USD
        # Entry: 100
        # SL: 95 (Dist: 5)
        # Size = 10 / 5 = 2
        # Exposure = 2 * 100 = 200 USD
        
        balance = 1000
        entry = 100
        sl = 95
        symbol = "ETH/USDT"
        current_positions = {}
        
        size = RiskManager.calculate_position_size(entry, sl, balance, self.client, symbol, current_positions)
        
        self.assertAlmostEqual(size, 2.0)

    def test_calculate_position_size_tight_stop(self):
        # Balance: 1000
        # Risk: 1% = 10 USD
        # Entry: 100
        # SL: 99 (Dist: 1)
        # Size = 10 / 1 = 10
        # Exposure = 10 * 100 = 1000 USD (Hits Max Exposure Limit exactly)
        
        balance = 1000
        entry = 100
        sl = 99
        symbol = "ETH/USDT"
        current_positions = {}
        
        size = RiskManager.calculate_position_size(entry, sl, balance, self.client, symbol, current_positions)
        
        self.assertAlmostEqual(size, 10.0)

    def test_calculate_position_size_wide_stop(self):
        # Balance: 1000
        # Risk: 1% = 10 USD
        # Entry: 100
        # SL: 90 (Dist: 10)
        # Size = 10 / 10 = 1
        # Exposure = 1 * 100 = 100 USD
        
        balance = 1000
        entry = 100
        sl = 90
        symbol = "ETH/USDT"
        current_positions = {}
        
        size = RiskManager.calculate_position_size(entry, sl, balance, self.client, symbol, current_positions)
        
        self.assertAlmostEqual(size, 1.0)

    def test_calculate_position_size_exposure_limit(self):
        # Balance: 1000
        # Risk: 1% = 10 USD
        # Entry: 100
        # SL: 99.5 (Dist: 0.5)
        # Size = 10 / 0.5 = 20
        # Exposure = 20 * 100 = 2000 USD (Exceeds 1000 Limit)
        
        balance = 1000
        entry = 100
        sl = 99.5
        symbol = "ETH/USDT"
        current_positions = {}
        
        size = RiskManager.calculate_position_size(entry, sl, balance, self.client, symbol, current_positions)
        
        self.assertAlmostEqual(size, 10.0) # Should be clamped to 1000 USD exposure (1000/100 = 10)

if __name__ == '__main__':
    unittest.main()
