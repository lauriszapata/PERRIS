import ccxt
import time
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def check_time_sync():
    print("Initializing Binance Client...")
    exchange = ccxt.binanceusdm({
        'apiKey': Config.API_KEY,
        'secret': Config.API_SECRET,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True,
        }
    })

    try:
        print("Fetching server time...")
        server_time = exchange.fetch_time()
        local_time = int(time.time() * 1000)
        diff = local_time - server_time
        
        print(f"Server Time: {server_time}")
        print(f"Local Time:  {local_time}")
        print(f"Difference:  {diff} ms")
        
        if abs(diff) > 1000:
            print("⚠️  Time difference is significant (> 1000ms)!")
        else:
            print("✅ Time difference is within acceptable range.")
            
        # Try a simple authenticated request
        print("\nAttempting authenticated request (fetch_balance)...")
        exchange.fetch_balance()
        print("✅ Authenticated request successful.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_time_sync()
