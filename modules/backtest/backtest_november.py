import pandas as pd
import os, sys
# Ensure project root is in PYTHONPATH for module imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
if project_root not in sys.path:
    sys.path.append(project_root)
from modules.backtest.backtester import Backtester
from modules.backtest.data_loader import DataLoader
from config import Config

def run_november_backtest():
    loader = DataLoader()
    start_date = "2025-11-01"
    end_date = "2025-11-30"
    results = {}
    total_pnl = 0
    total_trades = 0
    for symbol in Config.SYMBOLS:
        df = loader.fetch_data_range(symbol, start_date, end_date)
        if df is None or df.empty:
            continue
        backtester = Backtester(initial_balance=10000)
        metrics = backtester.run(df)
        results[symbol] = metrics
        total_pnl += metrics.get('total_pnl', 0)
        total_trades += metrics.get('trades', 0)
    print("=== November Backtest Summary ===")
    print(f"Total Symbols Tested: {len(results)}")
    print(f"Total Trades: {total_trades}")
    print(f"Aggregate PnL: {total_pnl:.2f} USDT")
    if results:
        top = sorted(results.items(), key=lambda x: x[1].get('total_pnl', 0), reverse=True)[:5]
        print("Top 5 symbols by PnL:")
        for sym, m in top:
            print(f"{sym}: {m.get('total_pnl',0):.2f} USDT, Trades: {m.get('trades',0)}")

if __name__ == "__main__":
    run_november_backtest()
