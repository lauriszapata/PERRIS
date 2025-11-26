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

        try:
            params = {'reduceOnly': True}
            order = self.client.create_order(symbol, 'market', side, amount, params=params)
            
            if order:
                logger.info(f"Close order created: {order['id']}")
                return order
            else:
                logger.error("Failed to create close order")
                return None
        except Exception as e:
            # Handle "ReduceOnly Order is rejected" (Code -2022)
            # This happens if position is already closed or size mismatch
            if "-2022" in str(e):
                logger.warning(f"⚠️ ReduceOnly rejected for {symbol}. Verifying if position is already closed...")
                max_retries = 2
                for attempt in range(1, max_retries + 1):
                    try:
                        # Check actual position on Binance
                        positions = self.client.get_position(symbol)
                        is_closed = True
                        for p in positions:
                            contracts = float(p.get('contracts', 0))
                            if contracts > 0:
                                # Verify side matches intended direction
                                pos_side = p.get('side')
                                target_side = 'long' if direction == 'LONG' else 'short'
                                if pos_side and pos_side.lower() != target_side:
                                    continue
                                is_closed = False
                                break
                        if is_closed:
                            logger.info(f"✅ Position for {symbol} is ALREADY CLOSED on Binance. Proceeding with state cleanup.")
                            # Return a dummy order object to satisfy the caller and allow cleanup
                            return {'id': 'ALREADY_CLOSED', 'status': 'closed', 'filled': amount}
                        else:
                            logger.error(f"❌ Position {symbol} exists but ReduceOnly failed. Attempting normal market order (attempt {attempt})...")
                            # Try normal market order without reduceOnly
                            normal_order = self.client.exchange.create_order(symbol, 'market', side, amount)
                            if normal_order:
                                logger.info(f"Close order created (normal market): {normal_order['id']}")
                                return normal_order
                            else:
                                logger.error("Failed to create normal market close order.")
                    except Exception as inner_e:
                        logger.error(f"Attempt {attempt} failed while handling ReduceOnly error: {inner_e}")
                        if attempt == max_retries:
                            raise
                        time.sleep(1)  # simple backoff between retries
                # If all retries exhausted
                logger.error(f"All retries exhausted for ReduceOnly handling on {symbol}.")
                return None
            else:
                logger.error(f"Failed to create close order: {e}")
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

        # CRITICAL: We MUST cancel existing STOP_MARKET orders before creating a new one.
        # Binance has a limit on open stop orders per symbol. If we don't cancel, we hit "Reach max stop order limit".
        try:
            open_orders = self.client.get_open_orders(symbol)
            for o in open_orders:
                o_type = o.get('type', '')
                o_info_type = o.get('info', {}).get('type', '')
                if o_type == 'STOP_MARKET' or o_info_type == 'STOP_MARKET':
                    logger.info(f"♻️ Replacing existing SL order {o['id']} for {symbol}")
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

        # CRITICAL: We MUST cancel existing TAKE_PROFIT_MARKET orders before creating a new one.
        try:
            open_orders = self.client.get_open_orders(symbol)
            for o in open_orders:
                o_type = o.get('type', '')
                o_info_type = o.get('info', {}).get('type', '')
                if o_type == 'TAKE_PROFIT_MARKET' or o_info_type == 'TAKE_PROFIT_MARKET':
                    logger.info(f"♻️ Replacing existing TP order {o['id']} for {symbol}")
                    self.client.cancel_order(o['id'], symbol)
        except Exception as e:
            logger.warning(f"Could not cancel existing TPs: {e}")

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

    def open_multiple_positions(self, positions):
        """
        Open several positions sequentially.
        `positions` should be an iterable of dicts or tuples containing:
            - symbol (str)
            - direction ('LONG' or 'SHORT')
            - amount (float)
            - optional price (float or None)
        Returns a list with the order objects (or None for failures).
        """
        orders = []
        for pos in positions:
            if isinstance(pos, dict):
                symbol = pos["symbol"]
                direction = pos["direction"]
                amount = pos["amount"]
                price = pos.get("price")
            else:
                # tuple/list format: (symbol, direction, amount, price?)
                symbol, direction, amount, *rest = pos
                price = rest[0] if rest else None
            order = self.open_position(symbol, direction, amount, price)
            orders.append(order)
        return orders
