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
        
        # --- PROFIT FACTOR & KELLY CRITERION ---
        # Calculate Profit Factor (more direct measure of profitability than Sharpe)
        gross_profit = sum([t['pnl'] for t in recent_trades if t['pnl'] > 0])
        gross_loss = abs(sum([t['pnl'] for t in recent_trades if t['pnl'] < 0]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        logger.info(f"📊 ML Metrics: Profit Factor = {profit_factor:.2f} | Sharpe = {sharpe:.2f} | Win Rate = {win_rate:.1%}")
        
        # Calculate Kelly Criterion for optimal position sizing
        wins = [t['pnl'] for t in recent_trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in recent_trades if t['pnl'] < 0]
        
        kelly_pct = 0
        kelly_conservative = 0
        expectancy = 0
        
        if wins and losses:
            avg_win = np.mean(wins)
            avg_loss = np.mean(losses)
            rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            
            # Kelly Formula: W - ((1-W) / R)
            # W = Win Rate, R = Avg Win / Avg Loss
            if rr_ratio > 0:
                kelly_pct = win_rate - ((1 - win_rate) / rr_ratio)
                kelly_conservative = kelly_pct * 0.5  # Half Kelly for safety
                
                # Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
                expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
                
                logger.info(f"🎲 Kelly Criterion: Full = {kelly_pct:.1%} | Conservative = {kelly_conservative:.1%} | Expectancy = {expectancy:.4f}")
        
        # --- RISK ADJUSTMENT LOGIC (Kelly + Profit Factor based) ---
        current_risk = Config.RISK_PER_TRADE_PCT
        new_risk = current_risk
        
        # Decision Matrix:
        # 1. Profit Factor > 1.5 + Kelly suggests higher → INCREASE (proven edge)
        # 2. Profit Factor < 1.0 → DECREASE immediately (losing money)
        # 3. 1.0 <= Profit Factor <= 1.5 → Maintain or slight adjustment based on Kelly
        
        if profit_factor > 1.5 and kelly_conservative > 0:
            # System is profitable AND Kelly suggests we can risk more
            if kelly_conservative > current_risk:
                # Kelly suggests higher risk - increase towards it gradually
                new_risk = min(kelly_conservative, current_risk * 1.15, 0.02)  # Cap at 2%
                logger.info(f"🚀 ML: Profit Factor {profit_factor:.2f} > 1.5 & Kelly {kelly_conservative:.1%} > current. Increasing risk: {current_risk:.1%} → {new_risk:.1%}")
                Config.RISK_PER_TRADE_PCT = new_risk
            else:
                logger.info(f"✅ ML: Profit Factor {profit_factor:.2f} healthy. Current risk {current_risk:.1%} appropriate per Kelly.")
                
        elif profit_factor < 1.0:
            # Losing money - reduce risk immediately
            if kelly_conservative > 0:
                new_risk = max(kelly_conservative * 0.5, 0.003)  # Use half of Kelly or 0.3% min
            else:
                new_risk = 0.003  # Minimal risk when no edge
            
            logger.warning(f"⚠️ ML: Profit Factor {profit_factor:.2f} < 1.0 (losing). Decreasing risk: {current_risk:.1%} → {new_risk:.1%}")
            Config.RISK_PER_TRADE_PCT = new_risk
            
        elif 1.0 <= profit_factor <= 1.5:
            # Marginal profitability - adjust conservatively based on Kelly
            if kelly_conservative > 0:
                # Move towards Kelly recommendation slowly
                if kelly_conservative > current_risk * 1.2:
                    new_risk = min(current_risk * 1.05, kelly_conservative * 0.8, 0.015)
                    logger.info(f"📈 ML: Profit Factor {profit_factor:.2f} marginal. Slight increase: {current_risk:.1%} → {new_risk:.1%}")
                    Config.RISK_PER_TRADE_PCT = new_risk
                elif kelly_conservative < current_risk * 0.8:
                    new_risk = max(current_risk * 0.95, kelly_conservative * 1.2, 0.003)
                    logger.info(f"📉 ML: Profit Factor {profit_factor:.2f} marginal. Slight decrease: {current_risk:.1%} → {new_risk:.1%}")
                    Config.RISK_PER_TRADE_PCT = new_risk
                else:
                    logger.info(f"⚖️ ML: Profit Factor {profit_factor:.2f} marginal. Maintaining risk {current_risk:.1%}")
            else:
                # Kelly negative but Profit Factor > 1.0 (strange case)
                # Likely high win rate but bad RR ratio
                logger.warning(f"⚠️ ML: Profit Factor {profit_factor:.2f} > 1.0 but Kelly {kelly_pct:.1%} negative. Check R:R ratio.")
                logger.info(f"💡 Suggestion: Improve avg win/loss ratio (currently {rr_ratio:.2f})")
                
        # Legacy Sharpe-based fallback (only if Kelly data insufficient)
        elif len(wins) < 3 or len(losses) < 3:
            logger.info(f"ℹ️ ML: Insufficient data for Kelly ({len(wins)} wins, {len(losses)} losses). Using Sharpe fallback.")
            if sharpe > 2.0:
                new_risk = min(current_risk * 1.05, 0.02)
                if new_risk != current_risk:
                    logger.info(f"ML: Performance Stable (Sharpe {sharpe:.2f}). Increasing Risk: {current_risk:.1%} → {new_risk:.1%}")
                    Config.RISK_PER_TRADE_PCT = new_risk
            elif sharpe < 1.0 and wasted_ratio < 0.5:
                new_risk = max(current_risk * 0.9, 0.005)
                if new_risk != current_risk:
                    logger.info(f"ML: Performance Unstable (Sharpe {sharpe:.2f}). Decreasing Risk: {current_risk:.1%} → {new_risk:.1%}")
                    Config.RISK_PER_TRADE_PCT = new_risk
                  
        # Logic for Volatility Filter Adjustment (ATR_MIN_PCT)
        # Keep existing ATR filter logic as it's complementary
        
        if win_rate < 0.4:
            # Too many losses, maybe market is choppy/noisy
            current_atr_min = Config.ATR_MIN_PCT
            new_atr_min = min(current_atr_min * 1.1, 0.5) # Max 0.5%
            if new_atr_min != current_atr_min:
                logger.info(f"ML: Low Win Rate ({win_rate:.1%}). Tightening ATR Filter: {current_atr_min:.2%} → {new_atr_min:.2%}")
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
