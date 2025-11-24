import unittest
import pandas as pd
import numpy as np
from modules.entry_signals import EntrySignals
from modules.indicators import Indicators

class TestSignalsRelaxed(unittest.TestCase):
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
        
        # Calculate indicators
        self.df = Indicators.calculate_all(self.df)

    def test_adx_relaxed(self):
        # Force ADX to 12 (should pass now, failed before)
        self.df.loc[self.df.index[-1], 'ADX'] = 12
        
        # We need to mock other signals to pass to isolate ADX
        # But EntrySignals checks everything.
        # Let's just check the result dictionary for ADX specifically.
        
        ok, results = EntrySignals.check_signals(self.df, "LONG")
        
        # ADX should be PASS (>= 10)
        self.assertTrue(results['ADX']['status'], f"ADX 12 should pass. Result: {results['ADX']}")

    def test_macd_signal_cross(self):
        # Force MACD Line > Signal but Hist < 0 (impossible mathematically but for testing logic)
        # Actually, if Line > Signal, Hist IS > 0.
        # The change was: check Line > Signal instead of Hist > 0.
        # Wait, Hist = Line - Signal. So Hist > 0 IS Line > Signal.
        # The change was effectively semantic? 
        # Ah, the previous check was `macd_hist > 0`. 
        # My new check is `macd_line > macd_signal`.
        # These are mathematically identical: `Line - Signal > 0` <=> `Line > Signal`.
        # HOWEVER, maybe I wanted to allow a "turning up" even if below zero?
        # No, the plan said "Line > Signal (Signal Cross)".
        # If the previous code was `macd_hist > 0`, it was already checking for a bullish configuration.
        # Maybe the user meant "Crossed recently"? 
        # But `Line > Signal` is the standard "Bullish" state.
        # Let's verify it works.
        
        self.df.loc[self.df.index[-1], 'MACD_line'] = 0.5
        self.df.loc[self.df.index[-1], 'MACD_signal'] = 0.4
        # Hist would be 0.1
        
        ok, results = EntrySignals.check_signals(self.df, "LONG")
        self.assertTrue(results['MACD']['status'])

    def test_rsi_widened(self):
        # RSI 38 (should pass LONG now, failed before < 40)
        # Wait, previous was > 40. Now > 35.
        # So 38 should pass.
        self.df.loc[self.df.index[-1], 'RSI'] = 38
        
        ok, results = EntrySignals.check_signals(self.df, "LONG")
        self.assertTrue(results['RSI']['status'], f"RSI 38 should pass LONG (>35). Result: {results['RSI']}")

if __name__ == '__main__':
    unittest.main()
