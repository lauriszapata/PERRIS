from config import Config
from modules.logger import logger

class LiquiditySpreadFilters:
    @staticmethod
    def check_spread(order_book):
        """
        Check if spread (ask - bid) / price < 0.03%.
        """
        try:
            bid = order_book['bids'][0][0]
            ask = order_book['asks'][0][0]
            price = (bid + ask) / 2
            
            spread_pct = ((ask - bid) / price) * 100
            
            if spread_pct > Config.MAX_SPREAD_PCT:
                logger.info(f"Spread Filter Failed: Spread {spread_pct:.4f}% > {Config.MAX_SPREAD_PCT}%")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Error checking spread: {e}")
            return False

    @staticmethod
    def check_liquidity(order_book, required_size):
        """
        Check if liquidity in top 5 levels covers the required order size.
        """
        try:
            # Check bids for selling (Short) and asks for buying (Long)
            # Since we don't know direction yet, we check both or just general depth.
            # Let's check both sides have enough depth.
            
            bids_vol = sum([b[1] for b in order_book['bids'][:5]])
            asks_vol = sum([a[1] for a in order_book['asks'][:5]])
            
            if bids_vol < required_size or asks_vol < required_size:
                logger.info(f"Liquidity Filter Failed: Bids {bids_vol:.2f} or Asks {asks_vol:.2f} < Required {required_size:.2f}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Error checking liquidity: {e}")
            return False
