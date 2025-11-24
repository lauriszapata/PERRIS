import pandas as pd
import numpy as np
from config import Config
from modules.logger import logger

class AdaptiveTuner:
    def __init__(self):
        self.trade_history = []
        self.window_size = 20 # Number of trades to evaluate
        
    def update_trade(self, pnl, max_pnl, entry_time):
        """
        Add a closed trade to history and trigger tuning.
        Args:
            pnl: Net PnL percentage (after fees)
            max_pnl: Maximum favorable excursion percentage during the trade
            entry_time: Timestamp of entry
        """
        self.trade_history.append({'pnl': pnl, 'max_pnl': max_pnl, 'time': entry_time})
        if len(self.trade_history) > 100:
            self.trade_history.pop(0) # Keep last 100
            
        self._tune_parameters()

    def _tune_parameters(self):
        """
        Analyze recent performance and adjust Config parameters.
        """
        if len(self.trade_history) < self.window_size:
            return

        recent_trades = self.trade_history[-self.window_size:]
        pnls = [t['pnl'] for t in recent_trades]
        
        # Calculate Metrics
        avg_pnl = np.mean(pnls)
        std_pnl = np.std(pnls)
        sharpe = avg_pnl / std_pnl if std_pnl != 0 else 0
        
        logger.info(f"ML Tuning: Rolling Sharpe (last {self.window_size}) = {sharpe:.2f}")
        
        # --- EFFICIENCY METRIC (Wasted Opportunities) ---
        # A trade is "wasted" if it reached > 0.5% profit but closed negative
        wasted_count = 0
        losing_trades = 0
        for t in recent_trades:
            if t['pnl'] < 0:
                losing_trades += 1
                if t['max_pnl'] > 0.005: # Reached 0.5% profit
                    wasted_count += 1
        
        wasted_ratio = wasted_count / losing_trades if losing_trades > 0 else 0
        
        if wasted_ratio > 0.5:
            logger.warning(f"⚠️  ML: High Wasted Opportunity Ratio ({wasted_ratio:.1%}). {wasted_count}/{losing_trades} losses were profitable > 0.5%.")
        
        # --- RISK ADJUSTMENT LOGIC ---
        
        current_risk = Config.RISK_PER_TRADE_PCT
        
        if sharpe > 2.0:
            # Stable performance -> Increase Risk slightly
            new_risk = min(current_risk * 1.05, 0.02) # Max 2%
            if new_risk != current_risk:
                logger.info(f"ML: Performance Stable (Sharpe {sharpe:.2f}). Increasing Risk: {current_risk:.1%} -> {new_risk:.1%}")
                Config.RISK_PER_TRADE_PCT = new_risk
                
        elif sharpe < 1.0:
            # Unstable -> Decrease Risk... BUT CHECK EFFICIENCY FIRST
            
            if wasted_ratio > 0.5:
                # If we are losing because we don't take profits, reducing risk is NOT the fix.
                # The entries are good (they go green). The exit is the problem.
                logger.info(f"ML: Sharpe Low ({sharpe:.2f}) but Wasted Ratio High ({wasted_ratio:.1%}). MAINTAINING RISK (Entries are good). Suggestion: Tighten Trailing Stop.")
            else:
                # Genuine bad performance (bad entries) -> Decrease Risk
                new_risk = max(current_risk * 0.9, 0.005) # Min 0.5%
                if new_risk != current_risk:
                    logger.info(f"ML: Performance Unstable (Sharpe {sharpe:.2f}). Decreasing Risk: {current_risk:.1%} -> {new_risk:.1%}")
                    Config.RISK_PER_TRADE_PCT = new_risk
                 
        # Logic for Volatility Filter Adjustment (ATR_MIN_PCT)
        # If we are getting stopped out a lot (low Win Rate), maybe increase ATR filter
        wins = len([p for p in pnls if p > 0])
        win_rate = wins / len(pnls)
        
        if win_rate < 0.4:
            # Too many losses, maybe market is choppy/noisy
            current_atr_min = Config.ATR_MIN_PCT
            new_atr_min = min(current_atr_min * 1.1, 0.5) # Max 0.5%
            if new_atr_min != current_atr_min:
                logger.info(f"ML: Low Win Rate ({win_rate:.1%}). Tightening ATR Filter: {current_atr_min:.2%} -> {new_atr_min:.2%}")
                Config.ATR_MIN_PCT = new_atr_min
        elif win_rate > 0.6:
            # High win rate, maybe we are missing trades? Relax filter slightly
            current_atr_min = Config.ATR_MIN_PCT
            new_atr_min = max(current_atr_min * 0.95, 0.1) # Min 0.1%
            if new_atr_min != current_atr_min:
                logger.info(f"ML: High Win Rate ({win_rate:.1%}). Relaxing ATR Filter: {current_atr_min:.2%} -> {new_atr_min:.2%}")
                Config.ATR_MIN_PCT = new_atr_min
    def get_state(self):
        """
        Return the current state of the tuner for persistence.
        """
        return {
            "trade_history": self.trade_history,
            "current_risk": Config.RISK_PER_TRADE_PCT,
            "current_atr_min": Config.ATR_MIN_PCT
        }

    def set_state(self, state):
        """
        Restore the tuner state from persistence.
        """
        if not state: return
        
        self.trade_history = state.get("trade_history", [])
        
        # Restore Tuned Parameters
        saved_risk = state.get("current_risk")
        if saved_risk:
            Config.RISK_PER_TRADE_PCT = saved_risk
            logger.info(f"ML: Restored Risk Parameter: {Config.RISK_PER_TRADE_PCT:.1%}")
            
        saved_atr_min = state.get("current_atr_min")
        if saved_atr_min:
            Config.ATR_MIN_PCT = saved_atr_min
            logger.info(f"ML: Restored ATR Filter: {Config.ATR_MIN_PCT:.2%}")
