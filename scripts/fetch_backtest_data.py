import sys
import os
sys.path.append(os.getcwd())
import time
from modules.backtest.data_loader import DataLoader
from config import Config

def fetch_data():
    loader = DataLoader()
    
    # Top 15 symbols from Config
    symbols = Config.SYMBOLS[:15]
    
    start_date = "2024-01-01"
    end_date = "2024-11-27"
    
    print(f"--- Fetching Data for {len(symbols)} Symbols ---")
    print(f"Period: {start_date} to {end_date}")
    
    for symbol in symbols:
        print(f"Fetching {symbol}...")
        try:
            # We use fetch_data_range but we want to save it to a specific file for the backtest
            # The current data_loader saves to cache only in fetch_data, not fetch_data_range
            # So we will manually save it.
            df = loader.fetch_data_range(symbol, start_date, end_date)
            
            if df is not None:
                safe_symbol = symbol.replace("/", "")
                filename = f"data/historical_full/{safe_symbol}_15m_JanNov.csv"
                import os
                os.makedirs("data/historical_full", exist_ok=True)
                df.to_csv(filename, index=False)
                print(f"Saved {len(df)} candles to {filename}")
            else:
                print(f"Failed to fetch data for {symbol}")
                
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            
        time.sleep(1) # Be nice to API

if __name__ == "__main__":
    fetch_data()
