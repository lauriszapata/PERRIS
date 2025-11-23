from modules.logger import logger

class StructureManager:
    @staticmethod
    def detect_structure(df):
        """
        Detect if the last swing was a Higher Low (HL) or Lower High (LH).
        This is a simplified implementation. A robust one would use pivot points.
        Here we check the last 5 candles to find local extrema.
        """
        try:
            # We need at least a few candles
            if len(df) < 10:
                return None, None
            
            # Use a window to find pivots
            # A simple pivot: a candle with lower lows on both sides (Low pivot)
            # or higher highs on both sides (High pivot)
            
            # We look for the most recent pivot
            # This is a basic implementation and might need refinement for "professional" use
            
            # Let's iterate backwards to find the last pivot
            last_pivot_type = None
            last_pivot_price = 0.0
            
            # Check for Low Pivot (HL candidate)
            # We need a low surrounded by higher lows
            # Let's check the last completed candle (index -2) and its neighbors
            
            # We need to scan back to find the most recent significant swing
            # For simplicity in this implementation, we will check if the recent price action suggests HL or LH
            # relative to the previous swing.
            
            # Better approach for "Last Swing":
            # 1. Identify pivots in the last N candles.
            # 2. Determine if the last pivot was a Low or High.
            # 3. Compare with the pivot before that.
            
            # Simplified for "Direct Implementation":
            # LONG requirement: Last swing = HL (Higher Low)
            # SHORT requirement: Last swing = LH (Lower High)
            
            # We will use a library function or manual loop if needed.
            # Since we have pandas, let's find local min/max.
            
            # Let's define a swing as a local extremum over a window of 5 candles (2 left, 2 right)
            # We look at the last 20 candles to find the most recent confirmed pivot.
            
            df = df.copy()
            df['is_low'] = df['low'][(df['low'].shift(1) > df['low']) & (df['low'].shift(-1) > df['low'])]
            df['is_high'] = df['high'][(df['high'].shift(1) < df['high']) & (df['high'].shift(-1) < df['high'])]
            
            # Find the last indices that are not NaN
            last_low_idx = df['is_low'].last_valid_index()
            last_high_idx = df['is_high'].last_valid_index()
            
            if last_low_idx is None or last_high_idx is None:
                return None, None
                
            # To confirm HL, we need the last low (L2) to be higher than the previous low (L1).
            # To confirm LH, we need the last high (H2) to be lower than the previous high (H1).
            
            # Let's find the last 2 lows and last 2 highs
            lows = df[df['is_low'].notna()]['low'].tail(2).values
            highs = df[df['is_high'].notna()]['high'].tail(2).values
            
            structure = {}
            
            if len(lows) >= 2:
                if lows[1] > lows[0]:
                    structure['HL'] = True # Higher Low
                    structure['HL_price'] = lows[1]
                else:
                    structure['HL'] = False
            
            if len(highs) >= 2:
                if highs[1] < highs[0]:
                    structure['LH'] = True # Lower High
                    structure['LH_price'] = highs[1]
                else:
                    structure['LH'] = False
            
            return structure
            
        except Exception as e:
            logger.error(f"Error detecting structure: {e}")
            return {}
