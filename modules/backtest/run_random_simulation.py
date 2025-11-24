import random
from datetime import datetime, timedelta
from modules.backtest.data_loader import DataLoader
from modules.backtest.backtester import Backtester
from config import Config

def run_random_simulation():
    # 1. Pick Random Date in last year
    end_limit = datetime.now() - timedelta(days=7)
    start_limit = datetime.now() - timedelta(days=365)
    
    days_range = (end_limit - start_limit).days
    random_days = random.randint(0, days_range)
    
    start_date = start_limit + timedelta(days=random_days)
    end_date = start_date + timedelta(days=7)
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    print(f"--- Running Random Simulation: {start_str} to {end_str} ---")
    
    loader = DataLoader()
    data_map = {}
    
    # Load data for all symbols for this range
    for symbol in Config.SYMBOLS:
        df = loader.fetch_data_range(symbol, start_str, end_str)
        if df is not None and not df.empty:
            data_map[symbol] = df
            
    if not data_map:
        print("No data found for this range.")
        return

    # 2. Run Backtest
    total_pnl = 0
    total_trades = 0
    
    results = {}
    
    for symbol, df in data_map.items():
        backtester = Backtester(initial_balance=10000)
        metrics = backtester.run(df)
        if metrics['trades'] > 0:
            results[symbol] = metrics
            total_pnl += metrics['total_pnl']
            total_trades += metrics['trades']
            
    # 3. Report
    print(f"\n=== Simulation Results ({start_str} to {end_str}) ===")
    print(f"Total Trades: {total_trades}")
    print(f"Total PnL: ${total_pnl:.2f}")
    
    if total_trades > 0:
        avg_pnl = total_pnl / total_trades
        print(f"Avg PnL per Trade: ${avg_pnl:.2f}")
        print(f"Avg Trades per Day: {total_trades / 7:.1f}")
        
    print("--------------------------------")
    sorted_res = sorted(results.items(), key=lambda x: x[1]['total_pnl'], reverse=True)
    for sym, m in sorted_res[:5]:
        print(f"{sym}: ${m['total_pnl']:.2f} ({m['trades']} trades)")

if __name__ == "__main__":
    run_random_simulation()
