import pandas as pd
import numpy as np
from config import Config
from modules.logger import logger

class AdaptiveTuner:
    def __init__(self):
        self.trade_history = []
        self.window_size = 20 # Number of trades to evaluate
        self.partial_history = [] # Track partial close effectiveness
        self.active_partials = {} # symbol -> partial data for current position
        
    def update_partial(self, symbol, level_name, partial_pnl_usd, current_total_pnl):
        """
        Track when a partial close happens.
        Args:
            symbol: Trading pair
            level_name: 'P1', 'P2', etc.
            partial_pnl_usd: USD profit from this partial
            current_total_pnl: Accumulated PnL so far (for context)
        """
        if symbol not in self.active_partials:
            self.active_partials[symbol] = {
                'levels_hit': [],
                'partial_pnl_usd': 0,
                'partial_count': 0
            }
        
        self.active_partials[symbol]['levels_hit'].append(level_name)
        self.active_partials[symbol]['partial_pnl_usd'] += partial_pnl_usd
        self.active_partials[symbol]['partial_count'] += 1
        
        logger.info(f"🧠 Partial recorded: {level_name} @ +${partial_pnl_usd:.2f} (Total from partials: ${current_total_pnl:.2f})")
    
    def update_trade(self, pnl, max_pnl, entry_time, symbol=None, partial_data=None):
        """
        Add a closed trade to history and trigger tuning.
        Args:
            pnl: Net PnL percentage (after fees)
            max_pnl: Maximum favorable excursion percentage during the trade
            entry_time: Timestamp of entry
            symbol: Trading pair (needed for partial data lookup)
            partial_data: Optional dict with partial close info:
                {
                    'partial_pnl_usd': Total USD from partials,
                    'final_pnl_usd': Total USD including remaining position,
                    'levels_hit': ['P1', 'P2']
                }
        """
        trade_record = {'pnl': pnl, 'max_pnl': max_pnl, 'time': entry_time}
        
        # Add partial data if available
        if partial_data:
            trade_record['partial_data'] = partial_data
            # Calculate efficiency: what % of profit came from partials
            if partial_data['final_pnl_usd'] != 0:
                efficiency = partial_data['partial_pnl_usd'] / partial_data['final_pnl_usd']
                trade_record['partial_efficiency'] = efficiency
            else:
                trade_record['partial_efficiency'] = 0
        
        # Clear active partials for this symbol
        if symbol and symbol in self.active_partials:
            del self.active_partials[symbol]
        
        self.trade_history.append(trade_record)
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
        
        # --- PARTIAL EFFECTIVENESS ANALYSIS ---
        self._analyze_partial_effectiveness(recent_trades)
    
    def _analyze_partial_effectiveness(self, recent_trades):
        """
        Analyze how effective partial profit-taking has been.
        """
        trades_with_partials = [t for t in recent_trades if 'partial_data' in t]
        
        if len(trades_with_partials) < 5:
            # Not enough data yet
            return
        
        # Calculate metrics
        efficiencies = [t.get('partial_efficiency', 0) for t in trades_with_partials]
        avg_efficiency = np.mean(efficiencies)
        
        # Check if letting position run helps or hurts
        let_run_helped = 0
        let_run_hurt = 0
        
        for t in trades_with_partials:
            pd = t.get('partial_data', {})
            partial_pnl = pd.get('partial_pnl_usd', 0)
            final_pnl = pd.get('final_pnl_usd', 0)
            remaining_pnl = final_pnl - partial_pnl
            
            if remaining_pnl > 0:
                let_run_helped += 1
            elif remaining_pnl < 0:
                let_run_hurt += 1
        
        total_let_run = let_run_helped + let_run_hurt
        let_run_success_rate = let_run_helped / total_let_run if total_let_run > 0 else 0
        
        # Log insights
        logger.info(f"🧠 Partial Learning (last {len(trades_with_partials)} trades with partials):")
        logger.info(f"   📊 Avg Partial Efficiency: {avg_efficiency:.1%} (partials contribute {avg_efficiency:.1%} of total profit)")
        logger.info(f"   📈 Let-Run Success Rate: {let_run_success_rate:.1%} (remaining position helps {let_run_success_rate:.1%} of time)")
        
        # Generate recommendations (Phase 1: just insights, no auto-changes)
        if avg_efficiency > 0.8:
            logger.info(f"   💡 Insight: Partials capturing most profits. Remaining position rarely adds value.")
            logger.info(f"   💡 Suggestion: Consider more aggressive partial closes or tighter trailing stop.")
        elif avg_efficiency < 0.4:
            logger.info(f"   💡 Insight: Significant profits from remaining position. Partials limiting upside.")
            logger.info(f"   💡 Suggestion: Consider reducing early partial percentages to let winners run.")
        elif let_run_success_rate < 0.3:
            logger.info(f"   💡 Insight: Remaining position often worsens results ({let_run_success_rate:.1%} success).")
            logger.info(f"   💡 Suggestion: Consider closing larger percentages at early levels (P1-P2).")
        else:
            logger.info(f"   ✅ Current partial strategy appears balanced.")
    def get_state(self):
        """
        Return the current state of the tuner for persistence.
        """
        return {
            "trade_history": self.trade_history,
            "partial_history": self.partial_history,
            "active_partials": self.active_partials,
            "current_risk": Config.RISK_PER_TRADE_PCT,
            "current_atr_min": Config.ATR_MIN_PCT
        }

    def set_state(self, state):
        """
        Restore the tuner state from persistence.
        """
        if not state: return
        
        self.trade_history = state.get("trade_history", [])
        self.partial_history = state.get("partial_history", [])
        self.active_partials = state.get("active_partials", {})
        
        # Restore Tuned Parameters
        saved_risk = state.get("current_risk")
        if saved_risk:
            Config.RISK_PER_TRADE_PCT = saved_risk
            logger.info(f"ML: Restored Risk Parameter: {Config.RISK_PER_TRADE_PCT:.1%}")
            
        saved_atr_min = state.get("current_atr_min")
        if saved_atr_min:
            Config.ATR_MIN_PCT = saved_atr_min
            logger.info(f"ML: Restored ATR Filter: {Config.ATR_MIN_PCT:.2%}")
