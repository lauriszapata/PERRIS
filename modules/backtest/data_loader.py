import os
import pandas as pd
import time
from datetime import datetime, timedelta
from config import Config
from modules.binance_client import BinanceClient
from modules.logger import logger

class DataLoader:
    def __init__(self):
        self.client = BinanceClient()
        self.data_dir = "data/historical"
        os.makedirs(self.data_dir, exist_ok=True)

    def fetch_data(self, symbol, days=30, timeframe=Config.TIMEFRAME):
        """
        Fetch historical data for a symbol.
        Try to load from cache first, if not fresh, fetch from API.
        """
        safe_symbol = symbol.replace("/", "")
        filename = f"{self.data_dir}/{safe_symbol}_{timeframe}.csv"
        
        # Check cache
        if os.path.exists(filename):
            df = pd.read_csv(filename)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            last_time = df['timestamp'].iloc[-1]
            if datetime.now() - last_time < timedelta(hours=1):
                logger.info(f"Loaded cached data for {symbol}")
                return df
        
        # Fetch from API
        logger.info(f"Fetching {days} days of data for {symbol}...")
        # Calculate limit based on timeframe (approx)
        # 15m = 4 per hour * 24 * 30 = 2880 candles
        # Binance limit is usually 1000, so we might need pagination or just fetch max allowed for now
        # For simplicity in this iteration, we fetch max limit 1000 which is ~10 days of 15m.
        # To get 30 days, we need pagination.
        
        all_candles = []
        since = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        
        while True:
            candles = self.client.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not candles:
                break
            
            all_candles.extend(candles)
            since = candles[-1][0] + 1 # Next timestamp
            
            if len(candles) < 1000:
                break
            
            time.sleep(0.5) # Rate limit nice
            
        if not all_candles:
            return None
            
        df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Save to cache
        df.to_csv(filename, index=False)
        df.to_csv(filename, index=False)
        return df

    def fetch_data_range(self, symbol, start_str, end_str, timeframe=Config.TIMEFRAME):
        """
        Fetch data for a specific range. No caching for random ranges to avoid clutter.
        start_str, end_str: "YYYY-MM-DD"
        """
        start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_str, "%Y-%m-%d")
        
        since = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)
        
        logger.info(f"Fetching data for {symbol} from {start_str} to {end_str}...")
        
        all_candles = []
        
        while True:
            candles = self.client.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not candles:
                break
            
            # Filter candles beyond end_ts
            valid_candles = [c for c in candles if c[0] <= end_ts]
            all_candles.extend(valid_candles)
            
            if len(valid_candles) < len(candles): # We reached the end
                break
                
            since = candles[-1][0] + 1
            
            if len(candles) < 1000:
                break
            
            time.sleep(0.2)
            
        if not all_candles:
            return None
            
        df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    def load_all_symbols(self, days=30):
        data = {}
        for symbol in Config.SYMBOLS:
            df = self.fetch_data(symbol, days)
            if df is not None:
                data[symbol] = df
        return data
