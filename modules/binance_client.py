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
                if "-2022" in str(e):
                    # ReduceOnly order rejected; do not retry further
                    logger.error(f"ReduceOnly error encountered: {e}. Not retrying.")
                    raise
                if attempt < max_retries - 1:
                    wait_time = delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"API call failed after {max_retries} retries: {e}")
                    raise


    def fetch_ohlcv(self, symbol, timeframe=Config.TIMEFRAME, limit=500):
        try:
            data = self._retry_call(self.exchange.fetch_ohlcv, symbol, timeframe, limit=limit)
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(data, f"OHLCV data for {symbol}")
            return data
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol} after retries: {e}")
            return None

    def get_market_price(self, symbol):
        try:
            ticker = self._retry_call(self.exchange.fetch_ticker, symbol)
            price = ticker['last']
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(price, f"Market price for {symbol}")
            return price
        except Exception as e:
            logger.error(f"Error fetching price for {symbol} after retries: {e}")
            return None

    def get_order_book(self, symbol, limit=5):
        try:
            ob = self.exchange.fetch_order_book(symbol, limit)
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(ob, f"Order book for {symbol}")
            return ob
        except Exception as e:
            logger.error(f"Error fetching order book for {symbol}: {e}")
            return None

    def get_funding_rate(self, symbol):
        try:
            funding = self.exchange.fetch_funding_rate(symbol)
            rate = funding['fundingRate']
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(rate, f"Funding rate for {symbol}")
            return rate
        except Exception as e:
            logger.error(f"Error fetching funding rate for {symbol}: {e}")
            return None

    def set_leverage(self, symbol, leverage=Config.LEVERAGE):
        try:
            self.exchange.set_leverage(leverage, symbol)
            # No direct return value, but ensure no exception means success
        except Exception as e:
            logger.error(f"Error setting leverage for {symbol}: {e}")

    def create_order(self, symbol, type, side, amount, price=None, params={}):
        try:
            # Use retry helper with exponential backoff
            order = self._retry_call(self.exchange.create_order, symbol, type, side, amount, price, params)
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(order, f"Created order for {symbol}")
            return order
        except Exception as e:
            # Handle "ReduceOnly Order is rejected" (Code -2022)
            # This happens if position is already closed or size mismatch
            if "-2022" in str(e):
                logger.warning(f"⚠️ ReduceOnly rejected for {symbol}. Verifying if position is already closed and side matches...")
                try:
                    # Check actual position on Binance
                    positions = self.get_position(symbol)
                    is_closed = True
                    # Determine the intended direction from the 'side' of the order
                    direction = 'LONG' if side.lower() == 'buy' else 'SHORT'
                    
                    for p in positions:
                        # Ensure the position matches the intended side
                        pos_side = p.get('side')
                        contracts = float(p.get('contracts', 0))
                        if contracts > 0:
                            if pos_side:
                                if (direction == 'LONG' and pos_side.lower() == 'long') or (direction == 'SHORT' and pos_side.lower() == 'short'):
                                    is_closed = False
                                    break
                            else:
                                # No side info, assume matching
                                is_closed = False
                                break
                    
                    if is_closed:
                        logger.info(f"✅ Position for {symbol} is ALREADY_CLOSED on Binance. Proceeding with state cleanup.")
                        # Return a dummy order object to satisfy the caller and allow cleanup
                        return {'id': 'ALREADY_CLOSED', 'status': 'closed', 'filled': amount}
                    else:
                        logger.error(f"❌ Position {symbol} exists but ReduceOnly failed. Attempting normal market order...")
                        # If position still exists, try to close with a normal market order (without reduceOnly)
                        try:
                            # Directly create a market order without reduceOnly to avoid recursion
                            normal_order = self.exchange.create_order(symbol, 'market', side, amount)
                            if normal_order:
                                logger.info(f"Close order created (normal market): {normal_order['id']}")
                                return normal_order
                            else:
                                logger.error("Failed to create normal market close order.")
                                return None
                        except Exception as normal_e:
                            logger.error(f"Failed to create normal market close order after ReduceOnly rejection: {normal_e}")
                            return None
                except Exception as ve:
                    logger.error(f"Failed to verify position status after ReduceOnly error: {ve}")
                    return None
            else:
                logger.error(f"Failed to create order for {symbol} after retries: {e}")
                return None

    def cancel_order(self, order_id, symbol):
        try:
            self.exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")

    def get_open_orders(self, symbol):
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(orders, f"Open orders for {symbol}")
            return orders
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
            bal = self.exchange.fetch_balance()
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(bal, "Account balance")
            return bal
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return None
    
    def get_server_time(self):
        try:
            t = self.exchange.fetch_time()
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(t, "Server time")
            return t
        except Exception as e:
            logger.error(f"Error fetching server time: {e}")
            return None

    def get_all_positions(self):
        try:
            positions = self.exchange.fetch_positions()
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(positions, "All positions")
            # Filter for active positions (size != 0)
            active_positions = []
            for p in positions:
                if float(p['contracts']) > 0:
                    # Normalize symbol: Remove :USDT suffix if present
                    if p['symbol'].endswith(':USDT'):
                        p['symbol'] = p['symbol'].replace(':USDT', '')
                    active_positions.append(p)
            return active_positions
        except Exception as e:
            logger.error(f"Error fetching all positions: {e}")
            return None

    def get_position(self, symbol):
        try:
            # Fetch positions for specific symbol
            # CCXT might expect the colon format for fetching, but we should try both or rely on fetch_positions filtering
            # Ideally, fetch_positions([symbol]) works, but if symbol is AVAX/USDT and exchange expects AVAX/USDT:USDT...
            # Let's try fetching all and filtering, or just handle the return.
            # For safety, let's fetch all (cached usually) or just the specific one if we trust the input.
            
            # If we pass AVAX/USDT, ccxt might need AVAX/USDT:USDT. 
            # But let's assume the input symbol is correct for the request, and we just normalize the output.
            positions = self.exchange.fetch_positions([symbol])
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(positions, f"Positions for {symbol}")
            
            # Normalize symbols in the result
            for p in positions:
                if p['symbol'].endswith(':USDT'):
                    p['symbol'] = p['symbol'].replace(':USDT', '')
                    
            return positions
        except Exception as e:
            logger.error(f"Error fetching position for {symbol}: {e}")
            return []
