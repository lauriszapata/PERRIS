import ccxt
import time
from config import Config
from modules.logger import logger

class BinanceClient:
    def __init__(self):
        try:
            self.exchange = ccxt.binanceusdm({
                'apiKey': Config.API_KEY,
                'secret': Config.API_SECRET,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',
                    'adjustForTimeDifference': True,
                }
            })
            # Check connection (optional, can be done in health check)
            # self.exchange.load_markets() 
        except Exception as e:
            logger.critical(f"Failed to initialize Binance Client: {e}")
            raise
    
    def _retry_call(self, func, *args, **kwargs):
        """
        Retry a function call with exponential backoff.
        Retries up to MAX_RETRIES times with delays: 1s, 2s, 4s
        """
        max_retries = Config.MAX_RETRIES
        delay = Config.RETRY_DELAY
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API call failed after {max_retries} retries: {e}")
                    raise


    def fetch_ohlcv(self, symbol, timeframe=Config.TIMEFRAME, limit=500):
        try:
            return self._retry_call(self.exchange.fetch_ohlcv, symbol, timeframe, limit=limit)
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol} after retries: {e}")
            return None

    def get_market_price(self, symbol):
        try:
            ticker = self._retry_call(self.exchange.fetch_ticker, symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"Error fetching price for {symbol} after retries: {e}")
            return None

    def get_order_book(self, symbol, limit=5):
        try:
            return self.exchange.fetch_order_book(symbol, limit)
        except Exception as e:
            logger.error(f"Error fetching order book for {symbol}: {e}")
            return None

    def get_funding_rate(self, symbol):
        try:
            funding = self.exchange.fetch_funding_rate(symbol)
            return funding['fundingRate']
        except Exception as e:
            logger.error(f"Error fetching funding rate for {symbol}: {e}")
            return None

    def set_leverage(self, symbol, leverage=Config.LEVERAGE):
        try:
            self.exchange.set_leverage(leverage, symbol)
        except Exception as e:
            logger.error(f"Error setting leverage for {symbol}: {e}")

    def create_order(self, symbol, type, side, amount, price=None, params={}):
        try:
            # Use retry helper with exponential backoff
            order = self._retry_call(self.exchange.create_order, symbol, type, side, amount, price, params)
            return order
        except Exception as e:
            logger.error(f"Failed to create order for {symbol} after retries: {e}")
            return None

    def cancel_order(self, order_id, symbol):
        try:
            self.exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")

    def get_open_orders(self, symbol):
        try:
            return self.exchange.fetch_open_orders(symbol)
        except Exception as e:
            logger.error(f"Error fetching open orders for {symbol}: {e}")
            return []
    
    def cancel_all_orders(self, symbol):
        """
        Cancel all open orders for a symbol.
        Used for cleanup when no positions are active.
        """
        try:
            open_orders = self.get_open_orders(symbol)
            if not open_orders:
                return 0
            
            cancelled_count = 0
            for order in open_orders:
                try:
                    self.exchange.cancel_order(order['id'], symbol)
                    cancelled_count += 1
                    logger.info(f"🧹 Cancelled order {order['id']} ({order['type']}) for {symbol}")
                except Exception as e:
                    logger.warning(f"Failed to cancel order {order['id']}: {e}")
            
            return cancelled_count
        except Exception as e:
            logger.error(f"Error cancelling all orders for {symbol}: {e}")
            return 0


    def get_balance(self):
        try:
            return self.exchange.fetch_balance()
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return None
    
    def get_server_time(self):
        try:
            return self.exchange.fetch_time()
        except Exception as e:
            logger.error(f"Error fetching server time: {e}")
            return None

    def get_all_positions(self):
        try:
            positions = self.exchange.fetch_positions()
            # Filter for active positions (size != 0)
            active_positions = [p for p in positions if float(p['contracts']) > 0]
            return active_positions
        except Exception as e:
            logger.error(f"Error fetching all positions: {e}")
            return None

    def get_position(self, symbol):
        try:
            # Fetch positions for specific symbol
            positions = self.exchange.fetch_positions([symbol])
            return positions
        except Exception as e:
            logger.error(f"Error fetching position for {symbol}: {e}")
            return []
