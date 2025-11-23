from modules.logger import logger
from config import Config

class OrderExecutor:
    def __init__(self, client):
        self.client = client

    def open_position(self, symbol, direction, amount, price=None):
        """
        Open a position with retries.
        """
        side = 'buy' if direction == 'LONG' else 'sell'
        logger.info(f"Opening {direction} position for {symbol}, amount: {amount}")
        
        # Market order for entry usually, or limit if price specified
        order_type = 'market' if price is None else 'limit'
        
        order = self.client.create_order(symbol, order_type, side, amount, price)
        if order:
            logger.info(f"Order created: {order['id']}")
            return order
        else:
            logger.error("Failed to create open order")
            return None

    def close_position(self, symbol, direction, amount=None):
        """
        Close a position (or partial). If amount is None, close all.
        """
        side = 'sell' if direction == 'LONG' else 'buy'
        logger.info(f"Closing {direction} position for {symbol}, amount: {amount if amount else 'ALL'}")
        # Dust handling: if amount is provided and its notional value is very small, close full position
        if amount is not None:
            try:
                price = self.client.get_market_price(symbol)
                notional = amount * price
                if notional < 5:  # USD threshold for dust
                    logger.info(f"Amount {amount} ({notional:.2f} USD) considered dust, closing full position.")
                    amount = None
            except Exception as e:
                logger.warning(f"Could not fetch price for dust check: {e}")
        params = {'reduceOnly': True}
        order = self.client.create_order(symbol, 'market', side, amount, params=params)
        
        if order:
            logger.info(f"Close order created: {order['id']}")
            return order
        else:
            logger.error("Failed to create close order")
            return None

    def set_stop_loss(self, symbol, direction, stop_price):
        """
        Set or update Stop Loss.
        """
        side = 'sell' if direction == 'LONG' else 'buy'
        
        logger.info(f"Setting SL for {symbol} {direction} at {stop_price}")
        
        # For Binance Futures, to close the entire position we use closePosition=True
        # When closePosition=True, quantity must not be sent (or sent as 0/None depending on lib version)
        # CCXT usually handles 'amount': None if 'closePosition': True is in params
        
        params = {
            'stopPrice': stop_price,
            'closePosition': True
        }
        
        # We pass amount=None. If this fails, it might be because CCXT version requires strict parameter handling
        # or we need to cancel previous SLs first.
        
        # First, let's try to cancel open STOP orders for this symbol to avoid "ReduceOnly" conflicts or clutter
        try:
            open_orders = self.client.get_open_orders(symbol)
            for o in open_orders:
                if o['type'] == 'STOP_MARKET':
                    self.client.cancel_order(o['id'], symbol)
        except Exception as e:
            logger.warning(f"Could not cancel existing SLs: {e}")

        # Now place new SL
        # Note: For STOP_MARKET, price is None (it triggers a market order)
        order = self.client.create_order(symbol, 'STOP_MARKET', side, amount=None, price=None, params=params)
        return order
