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
        
        # If amount is None (close all), fetch current position size
        if amount is None:
            try:
                positions = self.client.get_position(symbol)
                target_side = 'long' if direction == 'LONG' else 'short'
                active_pos = None
                
                for p in positions:
                    # Check for positive size and matching side (if available/relevant)
                    if float(p['contracts']) > 0:
                        # In Hedge Mode, side is crucial. In One-Way, usually only one pos.
                        pos_side = p.get('side')
                        # If side is present, it must match. If not present, we assume it's the one.
                        if pos_side:
                            if pos_side.lower() == target_side:
                                active_pos = p
                                break
                        else:
                            active_pos = p
                            break
                
                if active_pos:
                    amount = float(active_pos['contracts'])
                    logger.info(f"Fetched full position size for {symbol}: {amount}")
                else:
                    logger.warning(f"No active {direction} position found for {symbol}, cannot close.")
                    return None
            except Exception as e:
                logger.error(f"Failed to fetch position size for closing: {e}")
                return None

        params = {'reduceOnly': True}
        order = self.client.create_order(symbol, 'market', side, amount, params=params)
        
        if order:
            logger.info(f"Close order created: {order['id']}")
            return order
        else:
            logger.error("Failed to create close order")
            return None

    def _create_identified_order(self, symbol, type, side, amount, params={}):
        """
        Standardized method for creating identified orders (TP/SL).
        """
        logger.info(f"Creating identified order: {symbol} {type} {side} {params}")
        
        # Retry logic for identified orders
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                # amount is None for closePosition=True orders in many contexts, 
                # but let's pass what is given.
                order = self.client.create_order(symbol, type, side, amount, price=None, params=params)
                if order:
                    logger.info(f"{type} order created: {order.get('id')}")
                    return order
                else:
                    logger.error(f"Failed to create {type} order (no response).")
            except Exception as e:
                err_msg = str(e)
                # Handle specific Binance errors if needed, e.g. "Reach max stop order limit"
                if "Reach max stop order limit" in err_msg and attempt < max_retries:
                    logger.warning(f"Max stop order limit reached, cancelling existing STOP orders and retrying (attempt {attempt})")
                    try:
                        open_orders = self.client.get_open_orders(symbol)
                        for o in open_orders:
                            if o.get('type') in ['STOP_MARKET', 'TAKE_PROFIT_MARKET']:
                                self.client.cancel_order(o['id'], symbol)
                    except Exception as ce:
                        logger.warning(f"Additional cancel attempt failed: {ce}")
                    continue
                else:
                    logger.error(f"Error creating {type} order: {e}")
                    break
        return None

    def set_stop_loss(self, symbol, direction, stop_price):
        """
        Set or update Stop Loss using standardized structure.
        """
        reduce_side = 'sell' if direction == 'LONG' else 'buy'

        logger.info(f"Setting SL for {symbol} {direction} at {stop_price}")

        # First, try to cancel any existing STOP orders for this symbol to avoid conflicts.
        try:
            open_orders = self.client.get_open_orders(symbol)
            for o in open_orders:
                if o.get('type') == 'STOP_MARKET':
                    self.client.cancel_order(o['id'], symbol)
        except Exception as e:
            logger.warning(f"Could not cancel existing SLs: {e}")

        # Standardized SL Order Structure
        return self._create_identified_order(
            symbol,
            "STOP_MARKET",  # ← TIPO ESPECÍFICO DE BINANCE
            reduce_side,
            None, # Amount is None for closePosition=True
            params={
                "workingType": "MARK_PRICE", 
                "closePosition": True,
                "stopPrice": stop_price,
                "priceProtect": True
            }
        )

    def set_take_profit(self, symbol, direction, tp_price):
        """
        Set Take Profit using standardized structure.
        """
        reduce_side = 'sell' if direction == 'LONG' else 'buy'
        
        logger.info(f"Setting TP for {symbol} {direction} at {tp_price}")

        # Standardized TP Order Structure
        return self._create_identified_order(
            symbol,
            "TAKE_PROFIT_MARKET",  # ← TIPO ESPECÍFICO DE BINANCE
            reduce_side,
            None,
            params={
                "workingType": "MARK_PRICE", 
                "closePosition": True,
                "stopPrice": tp_price
            }
        )

