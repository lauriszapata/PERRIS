import csv
import os
import time
from datetime import datetime
from modules.logger import logger

class CSVManager:
    DATA_DIR = "data"
    ENTRIES_FILE = os.path.join(DATA_DIR, "entries.csv")
    CLOSURES_FILE = os.path.join(DATA_DIR, "closures.csv")
    FINANCE_FILE = os.path.join(DATA_DIR, "finance.csv")

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
    def log_entry(symbol, direction, entry_price, size, sl_price, atr, indicators):
        """
        Log trade entry with all technical parameters.
        indicators: dict of indicator values (RSI, ADX, etc.)
        """
        headers = [
            "timestamp", "datetime", "symbol", "direction", "entry_price", "size", 
            "sl_price", "atr", "risk_usd", "rsi", "adx", "macd_line", "macd_signal", "volume"
        ]
        
        row = {
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "size": size,
            "sl_price": sl_price,
            "atr": atr,
            "risk_usd": abs(entry_price - sl_price) * size,
            "rsi": indicators.get('RSI', 0),
            "adx": indicators.get('ADX', 0),
            "macd_line": indicators.get('MACD_line', 0),
            "macd_signal": indicators.get('MACD_signal', 0),
            "volume": indicators.get('volume', 0)
        }
        
        CSVManager._write_row(CSVManager.ENTRIES_FILE, headers, row)

    @staticmethod
    def log_closure(symbol, direction, entry_price, exit_price, size, reason, pnl_usd, pnl_pct, duration_sec):
        """
        Log trade closure (partial or full).
        """
        headers = [
            "timestamp", "datetime", "symbol", "direction", "entry_price", "exit_price", 
            "size", "reason", "pnl_usd", "pnl_pct", "duration_sec", "duration_min"
        ]
        
        row = {
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "reason": reason,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "duration_sec": duration_sec,
            "duration_min": duration_sec / 60
        }
        
        CSVManager._write_row(CSVManager.CLOSURES_FILE, headers, row)

    @staticmethod
    def log_finance(symbol, direction, size, entry_price, exit_price, pnl_usd, duration_sec, commission_rate=0.0005):
        """
        Log financial metrics (MBA style).
        """
        headers = [
            "timestamp", "datetime", "symbol", "direction", "transaction_type", 
            "revenue", "cogs", "gross_profit", "ebitda", "net_income", 
            "capital_deployed", "roi_pct", "eva", "notes"
        ]
        
        # Financial Calculations
        # Revenue: Positive PnL (if winning)
        # COGS: Negative PnL (if losing) + Commissions
        
        transaction_value = size * exit_price
        commission_cost = transaction_value * commission_rate # Approx taker fee
        
        if pnl_usd >= 0:
            revenue = pnl_usd
            cogs = commission_cost
        else:
            revenue = 0
            cogs = abs(pnl_usd) + commission_cost
            
        gross_profit = revenue - cogs
        ebitda = gross_profit # Assuming no other opex for the bot per trade
        net_income = ebitda # Assuming no taxes/interest
        
        capital_deployed = size * entry_price / 3 # Assuming 3x leverage
        roi_pct = (net_income / capital_deployed) * 100 if capital_deployed > 0 else 0
        
        # EVA: Net Income - (Capital * Cost of Capital * Time)
        # Cost of Capital assumption: 10% annual
        cost_of_capital_annual = 0.10
        time_years = duration_sec / (365 * 24 * 3600)
        capital_charge = capital_deployed * cost_of_capital_annual * time_years
        eva = net_income - capital_charge
        
        row = {
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "direction": direction,
            "transaction_type": "CLOSE",
            "revenue": round(revenue, 4),
            "cogs": round(cogs, 4),
            "gross_profit": round(gross_profit, 4),
            "ebitda": round(ebitda, 4),
            "net_income": round(net_income, 4),
            "capital_deployed": round(capital_deployed, 4),
            "roi_pct": round(roi_pct, 4),
            "eva": round(eva, 6),
            "notes": "Winning Trade" if pnl_usd > 0 else "Losing Trade"
        }
        
        CSVManager._write_row(CSVManager.FINANCE_FILE, headers, row)
