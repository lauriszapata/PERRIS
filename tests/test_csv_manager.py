import unittest
import os
import csv
import shutil
import time
from modules.reporting.csv_manager import CSVManager

class TestCSVManager(unittest.TestCase):
    TEST_DIR = "tests/data"
    
    def setUp(self):
        # Override DATA_DIR for testing
        CSVManager.DATA_DIR = self.TEST_DIR
        CSVManager.ABIERTOS_FILE = os.path.join(self.TEST_DIR, "ABIERTOS.csv")
        CSVManager.CERRADOS_FILE = os.path.join(self.TEST_DIR, "CERRADOS.csv")
        
        if os.path.exists(self.TEST_DIR):
            shutil.rmtree(self.TEST_DIR)
        os.makedirs(self.TEST_DIR)

    def tearDown(self):
        if os.path.exists(self.TEST_DIR):
            shutil.rmtree(self.TEST_DIR)

    def test_log_entry(self):
        criteria = {'RSI': 30, 'ADX': 25}
        CSVManager.log_entry(
            symbol="BTC/USDT", 
            entry_time=time.time(), 
            margin=100.0, 
            exposure=100.0, 
            leverage=1, 
            criteria=criteria
        )
        
        self.assertTrue(os.path.exists(CSVManager.ABIERTOS_FILE))
        
        with open(CSVManager.ABIERTOS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['simbolo'], "BTC/USDT")
            self.assertIn("RSI=30", rows[0]['criterios_cumplidos'])
            self.assertEqual(rows[0]['margen_usd'], "100.0")

    def test_log_closure(self):
        CSVManager.log_closure(
            symbol="ETH/USDT", 
            close_time=time.time(), 
            pnl_usd=10.5, 
            margin=100.0, 
            leverage=1, 
            exposure=100.0, 
            duration_sec=3600, 
            info="TP Hit"
        )
        
        self.assertTrue(os.path.exists(CSVManager.CERRADOS_FILE))
        
        with open(CSVManager.CERRADOS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['pnl_binance_usd'], "10.5")
            self.assertEqual(rows[0]['info_adicional'], "TP Hit")
            self.assertEqual(rows[0]['tiempo_cierre_human'], "01:00:00")

if __name__ == '__main__':
    unittest.main()
