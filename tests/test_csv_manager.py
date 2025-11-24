import unittest
import os
import csv
import shutil
from modules.reporting.csv_manager import CSVManager

class TestCSVManager(unittest.TestCase):
    TEST_DIR = "tests/data"
    
    def setUp(self):
        # Override DATA_DIR for testing
        CSVManager.DATA_DIR = self.TEST_DIR
        CSVManager.ENTRIES_FILE = os.path.join(self.TEST_DIR, "entries.csv")
        CSVManager.CLOSURES_FILE = os.path.join(self.TEST_DIR, "closures.csv")
        CSVManager.FINANCE_FILE = os.path.join(self.TEST_DIR, "finance.csv")
        
        if os.path.exists(self.TEST_DIR):
            shutil.rmtree(self.TEST_DIR)
        os.makedirs(self.TEST_DIR)

    def tearDown(self):
        if os.path.exists(self.TEST_DIR):
            shutil.rmtree(self.TEST_DIR)

    def test_log_entry(self):
        indicators = {'RSI': 50, 'ADX': 20, 'MACD_line': 0.1, 'MACD_signal': 0.05, 'volume': 1000}
        CSVManager.log_entry("BTC/USDT", "LONG", 50000, 0.1, 49000, 100, indicators)
        
        self.assertTrue(os.path.exists(CSVManager.ENTRIES_FILE))
        
        with open(CSVManager.ENTRIES_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['symbol'], "BTC/USDT")
            self.assertEqual(rows[0]['rsi'], "50")

    def test_log_closure(self):
        CSVManager.log_closure("ETH/USDT", "SHORT", 3000, 2900, 1, "TP", 100, 0.033, 3600)
        
        self.assertTrue(os.path.exists(CSVManager.CLOSURES_FILE))
        
        with open(CSVManager.CLOSURES_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['pnl_usd'], "100")
            self.assertEqual(rows[0]['reason'], "TP")

    def test_log_finance(self):
        # Winning Trade
        # Size 1, Entry 100, Exit 110, PnL 10
        CSVManager.log_finance("SOL/USDT", "LONG", 1, 100, 110, 10, 3600)
        
        self.assertTrue(os.path.exists(CSVManager.FINANCE_FILE))
        
        with open(CSVManager.FINANCE_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['revenue'], "10")
            # COGS = Commission (1 * 110 * 0.0005 = 0.055)
            self.assertAlmostEqual(float(rows[0]['cogs']), 0.055, places=3)
            # EBITDA = 10 - 0.055 = 9.945
            self.assertAlmostEqual(float(rows[0]['ebitda']), 9.945, places=3)

if __name__ == '__main__':
    unittest.main()
