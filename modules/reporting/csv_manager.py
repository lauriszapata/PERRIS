import csv
import os
import time
from datetime import datetime
from modules.logger import logger

class CSVManager:
    # Set Data Directory to Desktop
    DATA_DIR = os.path.join(os.path.expanduser("~"), "Desktop")
    
    # Define File Names
    ABIERTOS_FILE = os.path.join(DATA_DIR, "ABIERTOS.csv")
    CERRADOS_FILE = os.path.join(DATA_DIR, "CERRADOS.csv")

    @staticmethod
    def _ensure_dir():
        if not os.path.exists(CSVManager.DATA_DIR):
            os.makedirs(CSVManager.DATA_DIR)

    @staticmethod
    def _write_row(filepath, headers, row_dict):
        CSVManager._ensure_dir()
        file_exists = os.path.isfile(filepath)
        
        try:
            with open(filepath, mode='a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row_dict)
        except Exception as e:
            logger.error(f"Failed to write to CSV {filepath}: {e}")

    @staticmethod
    def log_entry(symbol, entry_time, margin, exposure, leverage, criteria):
        """
        Log trade entry to ABIERTOS.csv
        criteria: dict of criteria values (e.g., {'RSI': 30, 'ADX': 25})
        """
        headers = [
            "fecha_hora", "simbolo", "margen_usd", "exposicion_usd", "leverage", 
            "criterios_cumplidos"
        ]
        
        # Format criteria as a string
        criteria_str = "; ".join([f"{k}={v}" for k, v in criteria.items()])
        
        row = {
            "fecha_hora": datetime.fromtimestamp(entry_time).strftime("%Y-%m-%d %H:%M:%S"),
            "simbolo": symbol,
            "margen_usd": round(margin, 2),
            "exposicion_usd": round(exposure, 2),
            "leverage": leverage,
            "criterios_cumplidos": criteria_str
        }
        
        CSVManager._write_row(CSVManager.ABIERTOS_FILE, headers, row)

    @staticmethod
    def log_closure(symbol, close_time, pnl_usd, margin, leverage, exposure, duration_sec, info):
        """
        Log trade closure to CERRADOS.csv
        """
        headers = [
            "fecha_hora", "simbolo", "pnl_binance_usd", "margen_usd", "leverage", 
            "exposicion_usd", "tiempo_cierre_sec", "tiempo_cierre_human", "info_adicional"
        ]
        
        # Format duration
        duration_human = time.strftime("%H:%M:%S", time.gmtime(duration_sec))
        
        row = {
            "fecha_hora": datetime.fromtimestamp(close_time).strftime("%Y-%m-%d %H:%M:%S"),
            "simbolo": symbol,
            "pnl_binance_usd": round(pnl_usd, 4),
            "margen_usd": round(margin, 2),
            "leverage": leverage,
            "exposicion_usd": round(exposure, 2),
            "tiempo_cierre_sec": int(duration_sec),
            "tiempo_cierre_human": duration_human,
            "info_adicional": info
        }
        
        CSVManager._write_row(CSVManager.CERRADOS_FILE, headers, row)
