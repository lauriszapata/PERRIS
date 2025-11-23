import unittest
import pandas as pd
import numpy as np
from modules.indicators import Indicators
from modules.entry_signals import EntrySignals
from modules.filters.volatility import VolatilityFilters

class TestBotLogic(unittest.TestCase):
    def setUp(self):
        # Create dummy data
        dates = pd.date_range(start='2023-01-01', periods=300, freq='15min')
        self.df = pd.DataFrame({
            'timestamp': dates,
            'open': np.random.rand(300) * 100 + 10000,
            'high': np.random.rand(300) * 100 + 10100,
            'low': np.random.rand(300) * 100 + 9900,
            'close': np.random.rand(300) * 100 + 10000,
            'volume': np.random.rand(300) * 1000
        })
        
        # Ensure high > low
        self.df['high'] = np.maximum(self.df['high'], self.df['close'])
        self.df['high'] = np.maximum(self.df['high'], self.df['open'])
        self.df['low'] = np.minimum(self.df['low'], self.df['close'])
        self.df['low'] = np.minimum(self.df['low'], self.df['open'])

    def test_indicators(self):
        df = Indicators.calculate_all(self.df.copy())
        self.assertIn('EMA8', df.columns)
        self.assertIn('RSI', df.columns)
        self.assertIn('ATR', df.columns)
        self.assertFalse(df['EMA8'].isnull().all())

    def test_volatility_filter(self):
        # Mock ATR and Price
        atr = 200
        price = 10000
        # 2% -> OK
        self.assertTrue(VolatilityFilters.check_atr(atr, price))
        
        # 0.1% -> Fail
        atr_low = 10
        self.assertFalse(VolatilityFilters.check_atr(atr_low, price))

    def test_entry_signals(self):
        # Create a scenario where signals might pass
        df = self.df.copy()
        df = Indicators.calculate_all(df)
        
        # Force trends
        # We can't easily force all 8 indicators without complex data manipulation
        # But we can run the check and ensure it doesn't crash
        ok, details = EntrySignals.check_signals(df, "LONG")
        print(f"Signal Check Result: {ok}")
        for k, v in details.items():
            print(f"  {k}: {v}")
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(details, dict)

if __name__ == '__main__':
    unittest.main()
