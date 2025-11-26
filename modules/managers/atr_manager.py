from config import Config

class ATRManager:
    @staticmethod
    def calculate_initial_stop(entry_price, atr_entry, direction):
        """
        Calculate initial stop loss price.
        SNIPER STRATEGY: Use Fixed % if configured, otherwise ATR.
        """
        if hasattr(Config, 'FIXED_SL_PCT') and Config.FIXED_SL_PCT > 0:
            if direction == "LONG":
                return entry_price * (1 - Config.FIXED_SL_PCT)
            else:
                return entry_price * (1 + Config.FIXED_SL_PCT)
        
        # Fallback to ATR logic
        multiplier = Config.DEFAULT_SL_ATR_MULTIPLIER
        if direction == "LONG":
            sl = entry_price - (multiplier * atr_entry)
            # Safety check: SL not too close (0.5%) or too far (20%)
            dist_pct = (entry_price - sl) / entry_price
            if dist_pct < 0.005:
                sl = entry_price * (1 - 0.005)
            elif dist_pct > 0.20:
                sl = entry_price * (1 - 0.20)
            return sl
        else:
            sl = entry_price + (multiplier * atr_entry)
            dist_pct = (sl - entry_price) / entry_price
            if dist_pct < 0.005:
                sl = entry_price * (1 + 0.005)
            elif dist_pct > 0.20:
                sl = entry_price * (1 + 0.20)
            return sl

    @staticmethod
    def calculate_trailing_stop(current_sl, extreme_price, current_atr, direction, entry_price):
        """
        Trailing ATR:
        LONG: SL_propuesto = P_max - 1.5 × ATR_actual
        SHORT: SL_propuesto = P_min + 1.5 × ATR_actual
        """
        if direction == "LONG":
            sl_prop = extreme_price - (1.5 * current_atr)
            # Before P1 (handled in logic), do not allow SL > entry - fees.
            # We return the proposed SL, the logic will handle the constraint.
            return max(current_sl, sl_prop)
        else:
            sl_prop = extreme_price + (1.5 * current_atr)
            return min(current_sl, sl_prop)
