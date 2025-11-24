import unittest
from modules.managers.atr_manager import ATRManager

class TestATRManager(unittest.TestCase):
    def test_calculate_initial_stop_long(self):
        # Entry: 100, ATR: 1
        # Target SL: 100 - (3 * 1) = 97
        # Distance: (100-97)/100 = 3%
        # Limits: 0.5% to 10%
        # 3% is within limits
        entry = 100
        atr = 1
        direction = "LONG"
        
        sl = ATRManager.calculate_initial_stop(entry, atr, direction)
        self.assertAlmostEqual(sl, 97.0)

    def test_calculate_initial_stop_short(self):
        # Entry: 100, ATR: 1
        # Target SL: 100 + (3 * 1) = 103
        # Distance: (103-100)/100 = 3%
        # Limits: 0.5% to 10%
        # 3% is within limits
        entry = 100
        atr = 1
        direction = "SHORT"
        
        sl = ATRManager.calculate_initial_stop(entry, atr, direction)
        self.assertAlmostEqual(sl, 103.0)

    def test_calculate_initial_stop_min_limit(self):
        # Entry: 100, ATR: 0.1
        # Target SL: 100 - (3 * 0.1) = 99.7
        # Distance: 0.3%
        # Min limit is 0.5% -> SL should be 99.5
        entry = 100
        atr = 0.1
        direction = "LONG"
        
        sl = ATRManager.calculate_initial_stop(entry, atr, direction)
        self.assertAlmostEqual(sl, 99.5)

    def test_calculate_initial_stop_max_limit(self):
        # Entry: 100, ATR: 5
        # Target SL: 100 - (3 * 5) = 85
        # Distance: 15%
        # Max limit is 10% -> SL should be 90
        entry = 100
        atr = 5
        direction = "LONG"
        
        sl = ATRManager.calculate_initial_stop(entry, atr, direction)
        self.assertAlmostEqual(sl, 90.0)

if __name__ == '__main__':
    unittest.main()
