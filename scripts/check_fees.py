import sys
import os
import time
sys.path.append(os.getcwd())

from modules.binance_client import BinanceClient
from config import Config

def check_fees():
    print("Initializing Binance Client...")
    client = BinanceClient()
    exchange = client.exchange
    
    symbol = "BTC/USDT"
    
    print(f"\n--- Checking Last 5 Trades for {symbol} ---")
    try:
        # Fetch my trades (usually contains fee info)
        trades = exchange.fetch_my_trades(symbol, limit=5)
        
        for trade in trades:
            print(f"\nTrade ID: {trade['id']}")
            print(f"Side: {trade['side']}")
            print(f"Price: {trade['price']}")
            print(f"Amount: {trade['amount']}")
            print(f"Cost: {trade['cost']}")
            
            if 'fee' in trade and trade['fee']:
                fee = trade['fee']
                print(f"Fee: {fee['cost']} {fee['currency']}")
                
                # Calculate effective rate
                if trade['cost'] > 0:
                    rate = fee['cost'] / trade['cost']
                    print(f"Effective Rate: {rate * 100:.4f}%")
            else:
                print("No fee info in trade object.")
                
    except Exception as e:
        print(f"Error fetching trades: {e}")

if __name__ == "__main__":
    check_fees()
