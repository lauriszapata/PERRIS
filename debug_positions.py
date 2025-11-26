
from modules.binance_client import BinanceClient
from modules.logger import logger
import logging

# Configure logger to print to console
logging.basicConfig(level=logging.INFO)

def check_positions():
    client = BinanceClient()
    positions = client.get_all_positions()
    
    print("\n=== BINANCE POSITIONS DEBUG ===")
    if positions:
        for p in positions:
            print(f"Symbol: {p['symbol']}")
            print(f"  Size: {p['contracts']}")
            print(f"  Side: {p['side']}")
            print(f"  Entry: {p['entryPrice']}")
            print(f"  PnL: {p['unrealizedPnl']}")
            print("-" * 30)
    else:
        print("No active positions found (get_all_positions returned empty/None).")
        
    # Also check raw fetch to see if filtering is the issue
    print("\n=== RAW POSITIONS CHECK ===")
    try:
        raw_positions = client.exchange.fetch_positions()
        active_raw = [p for p in raw_positions if float(p['contracts']) > 0]
        print(f"Total raw positions fetched: {len(raw_positions)}")
        print(f"Active raw positions (contracts > 0): {len(active_raw)}")
        for p in active_raw:
             print(f"RAW: {p['symbol']} Size: {p['contracts']}")
    except Exception as e:
        print(f"Error fetching raw positions: {e}")

    print("\n=== OHLCV CHECK ===")
    try:
        # Test with standard symbol
        print("Fetching OHLCV for AVAX/USDT...")
        ohlcv = client.fetch_ohlcv("AVAX/USDT")
        print(f"Success! Got {len(ohlcv)} candles.")
    except Exception as e:
        print(f"Failed for AVAX/USDT: {e}")
        
    try:
        # Test with colon symbol
        print("Fetching OHLCV for AVAX/USDT:USDT...")
        ohlcv = client.fetch_ohlcv("AVAX/USDT:USDT")
        print(f"Success! Got {len(ohlcv)} candles.")
    except Exception as e:
        print(f"Failed for AVAX/USDT:USDT: {e}")


if __name__ == "__main__":
    check_positions()
