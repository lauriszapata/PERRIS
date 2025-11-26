from config import Config
from modules.logger import logger

class VolatilityFilters:
    @staticmethod
    def check_atr(current_atr, current_price):
        """
        Check if ATR is within the allowed range [0.20%, 2.5%] of price.
        """
        if current_price == 0:
            return False
            
        atr_pct = current_atr / current_price
        
        if Config.ATR_MIN_PCT <= atr_pct <= Config.ATR_MAX_PCT:
            return True
        
        logger.info(f"Volatility Filter Failed: ATR% {atr_pct:.2f} not in [{Config.ATR_MIN_PCT}, {Config.ATR_MAX_PCT}]")
        return False

    @staticmethod
    def check_range_extreme(df, atr_entry):
        """
        Check if the last 12 candles have a total range < 0.6 * ATR_entry.
        This implies extremely low volatility/consolidation where breakouts might be fake or weak.
        """
        try:
            # Get last 12 candles
            last_12 = df.tail(12)
            total_range = last_12['high'].max() - last_12['low'].min()
            
            threshold = 0.6 * atr_entry
            
            if total_range < threshold:
                logger.info(f"Range Filter Failed: Total Range {total_range:.2f} < Threshold {threshold:.2f}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Error in check_range_extreme: {e}")
            return False
