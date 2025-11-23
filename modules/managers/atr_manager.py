from config import Config

class ATRManager:
    @staticmethod
    def calculate_initial_stop(entry_price, atr_entry, direction):
        """
        Calculate initial Stop Loss (OPTIMIZED for 15min).
        SL_inicial = entry_price - 1.5 × ATR_entry (for LONG)
        SL_inicial = entry_price + 1.5 × ATR_entry (for SHORT)
        1.5x gives enough room for 15min noise while keeping risk controlled
        """
        if direction == "LONG":
            sl = entry_price - (1.5 * atr_entry)  # 1.5x optimal for 15min
            # Limit check: distance between 0.5% and 2.0% (appropriate for 15min)
            dist_pct = (entry_price - sl) / entry_price
            if dist_pct < 0.005:
                sl = entry_price * (1 - 0.005)
            elif dist_pct > 0.02:
                sl = entry_price * (1 - 0.02)
            return sl
        else:
            sl = entry_price + (1.5 * atr_entry)  # 1.5x optimal for 15min
            # Limit check
            dist_pct = (sl - entry_price) / entry_price
            if dist_pct < 0.005:
                sl = entry_price * (1 + 0.005)
            elif dist_pct > 0.02:
                sl = entry_price * (1 + 0.02)
            return sl

    @staticmethod
    def calculate_trailing_stop(current_sl, extreme_price, current_atr, direction, entry_price):
        """
        Trailing ATR:
        LONG: SL_propuesto = P_max - 1.8 × ATR_actual
        SHORT: SL_propuesto = P_min + 1.8 × ATR_actual
        """
        if direction == "LONG":
            sl_prop = extreme_price - (1.8 * current_atr)
            # Before P1 (handled in logic), do not allow SL > entry - fees.
            # We return the proposed SL, the logic will handle the constraint.
            return max(current_sl, sl_prop)
        else:
            sl_prop = extreme_price + (1.8 * current_atr)
            return min(current_sl, sl_prop)
