from modules.logger import logger

class StructureManager:
    @staticmethod
    def get_last_swings(df):
        """
        Find the most recent Swing High and Swing Low.
        Uses a 5-candle fractal (High/Low surrounded by 2 lower highs/higher lows).
        Returns: {'swing_high': price, 'swing_low': price}
        """
        try:
            if len(df) < 10:
                return None
            
            # We need to find the *last* confirmed swing.
            # A swing at index `i` is confirmed at `i+2`.
            # So we iterate backwards from len(df)-3 down to 2.
            
            last_swing_high = None
            last_swing_low = None
            
            # Iterate backwards
            for i in range(len(df) - 3, 1, -1):
                # Check for Swing High
                # High[i] > High[i-1], High[i] > High[i-2], High[i] > High[i+1], High[i] > High[i+2]
                if last_swing_high is None:
                    if (df['high'].iloc[i] > df['high'].iloc[i-1] and
                        df['high'].iloc[i] > df['high'].iloc[i-2] and
                        df['high'].iloc[i] > df['high'].iloc[i+1] and
                        df['high'].iloc[i] > df['high'].iloc[i+2]):
                        last_swing_high = df['high'].iloc[i]
                
                # Check for Swing Low
                # Low[i] < Low[i-1], Low[i] < Low[i-2], Low[i] < Low[i+1], Low[i] < Low[i+2]
                if last_swing_low is None:
                    if (df['low'].iloc[i] < df['low'].iloc[i-1] and
                        df['low'].iloc[i] < df['low'].iloc[i-2] and
                        df['low'].iloc[i] < df['low'].iloc[i+1] and
                        df['low'].iloc[i] < df['low'].iloc[i+2]):
                        last_swing_low = df['low'].iloc[i]
                
                if last_swing_high is not None and last_swing_low is not None:
                    break
            
            return {
                'swing_high': last_swing_high,
                'swing_low': last_swing_low
            }
            
        except Exception as e:
            logger.error(f"Error detecting swings: {e}")
            return None

    @staticmethod
    def detect_structure(df):
        """
        Detect market structure (HH, HL, LH, LL).
        Returns a dict with boolean flags.
        """
        try:
            swings = StructureManager.get_last_swings(df)
            if not swings:
                return {}
            
            # Simple logic: 
            # If Close > Swing High -> HH (Potential)
            # If Close > Swing Low -> HL (Potential)
            # This is a simplified placeholder.
            # For the purpose of the existing EntrySignals call:
            # structure.get('HL') -> Higher Low (Bullish)
            # structure.get('LH') -> Lower High (Bearish)
            
            # We need at least 2 swings to determine HH/HL properly.
            # For now, we will return True for both to avoid blocking the optional filter,
            # or implement a slightly better check if possible.
            
            # Let's just return what EntrySignals expects based on current price vs swing
            last_close = df['close'].iloc[-1]
            swing_high = swings['swing_high']
            swing_low = swings['swing_low']
            
            res = {}
            if swing_low and last_close > swing_low:
                res['HL'] = True # Price is above last low, potentially making a higher low
            if swing_high and last_close < swing_high:
                res['LH'] = True # Price is below last high, potentially making a lower high
                
            return res
            
        except Exception as e:
            logger.error(f"Error detecting structure: {e}")
            return {}
