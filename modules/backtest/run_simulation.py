import pandas as pd
import numpy as np
from modules.backtest.data_loader import DataLoader
from modules.backtest.backtester import Backtester
from modules.logger import logger
from config import Config

def run_simulation(days=7):
    print(f"--- Running Simulation for Last {days} Days ---")
    print(f"Config: Risk={Config.RISK_PER_TRADE_PCT:.1%}, ATR_Min={Config.ATR_MIN_PCT:.1%}, Max_Sym={Config.MAX_OPEN_SYMBOLS}")
    
    loader = DataLoader()
    
    # 1. Load Data
    data_map = loader.load_all_symbols(days=days)
    if not data_map:
        print("No data found.")
        return

    # 2. Run Backtest
    total_pnl = 0
    total_trades = 0
    all_trades = []
    
    # We need to simulate the portfolio constraint (MAX_OPEN_SYMBOLS)
    # The simple Backtester runs per symbol independently. 
    
    results = {}
    
    for symbol, df in data_map.items():
        backtester = Backtester(initial_balance=10000) # New instance per symbol
        metrics = backtester.run(df)
        if metrics['trades'] > 0:
            results[symbol] = metrics
            total_pnl += metrics['total_pnl']
            total_trades += metrics['trades']
            # Collect all trade PnLs for global Sharpe
            # (This is approximate as we don't have the time-series of equity combined)
            
    # 3. Report
    print(f"\n=== Simulation Results (Last {days} Days) ===")
    print(f"Total Trades: {total_trades}")
    print(f"Total PnL: ${total_pnl:.2f}")
    
    if total_trades > 0:
        avg_pnl = total_pnl / total_trades
        print(f"Avg PnL per Trade: ${avg_pnl:.2f}")
        
        # Win Rate
        # We need to aggregate win/loss from all symbols. 
        # The backtester returns metrics but not raw trade list in the return dict.
        # Let's trust the PnL for now.
        
    print("--------------------------------")
    # Top Performers
    sorted_res = sorted(results.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
    for sym, m in sorted_res[:5]:
        print(f"{sym}: ${m['total_pnl']:.2f} ({m['trades']} trades)")
        
if __name__ == "__main__":
    run_simulation()
