from modules.binance_client import BinanceClient
from config import Config
import json

def debug_orders():
    client = BinanceClient()
    symbol = "ETH/USDT" # Or whatever symbol is active
    
    print(f"Fetching open orders for {symbol}...")
    orders = client.get_open_orders(symbol)
    
    print(f"Found {len(orders)} orders.")
    for o in orders:
        print(f"ID: {o['id']} | Type: {o['type']} | Side: {o['side']} | Price: {o['price']} | StopPrice: {o.get('stopPrice')} | Status: {o['status']}")
        # Print raw info to see if there's a 'type' field in 'info' that differs
        # print(json.dumps(o, indent=2))

if __name__ == "__main__":
    debug_orders()
