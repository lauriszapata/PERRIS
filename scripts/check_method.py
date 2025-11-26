import ccxt
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config

def check_method():
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

    if hasattr(exchange, 'load_time_difference'):
        print("✅ exchange.load_time_difference() exists.")
        try:
            exchange.load_time_difference()
            print("✅ exchange.load_time_difference() executed successfully.")
            print(f"New time difference: {exchange.options.get('timeDifference')}")
        except Exception as e:
            print(f"❌ Error executing load_time_difference: {e}")
    else:
        print("❌ exchange.load_time_difference() does NOT exist.")

if __name__ == "__main__":
    check_method()
