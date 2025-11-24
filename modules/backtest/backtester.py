import pandas as pd
import numpy as np
from modules.indicators import Indicators
from modules.entry_signals import EntrySignals
from modules.managers.atr_manager import ATRManager
from config import Config

class Backtester:
    def __init__(self, initial_balance=10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.commission_rate = 0.0005 # 0.05% Taker Fee
        self.trades = []
        self.trades = []
        self.equity_curve = []

    def run(self, df, params=None):
        """
        Run backtest on a single dataframe.
        params: dict of overrides for Config values (e.g. {'ATR_MIN_PCT': 0.5})
        """
        # Apply params overrides if any (mocking Config)
        # In a real scenario, we'd pass these into the managers, but for now we rely on the modules using Config.
        # To support optimization, we might need to monkeypatch Config or refactor modules to accept params.
        # For this iteration, we will assume standard Config or simple monkeypatching.
        
        if params:
            for k, v in params.items():
                setattr(Config, k, v)

        # Calculate Indicators
        df = Indicators.calculate_all(df.copy())
        
        position = None # { 'type': 'LONG', 'entry_price': 0, 'size': 0, 'sl': 0, 'tp_levels': [] }
        
        for i in range(50, len(df)): # Skip warmup
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            
            # Record Equity
            current_equity = self.balance
            if position:
                pnl = (row['close'] - position['entry_price']) * position['size'] if position['type'] == 'LONG' else \
                      (position['entry_price'] - row['close']) * position['size']
                current_equity += pnl
            self.equity_curve.append({'timestamp': row['timestamp'], 'equity': current_equity})

            # Check Exit
            if position:
                self._check_exit(position, row)
                if position['status'] == 'CLOSED':
                    # Deduct commissions
                    entry_comm = position['size'] * position['entry_price'] * self.commission_rate
                    exit_comm = position['size'] * position['exit_price'] * self.commission_rate
                    net_pnl = position['pnl'] - entry_comm - exit_comm
                    position['net_pnl'] = net_pnl
                    position['commission'] = entry_comm + exit_comm
                    
                    self.balance += net_pnl
                    self.trades.append(position)
                    position = None
                    continue

            # Check Entry (only if no position)
            if not position:
                # Volatility Filter (Min ATR)
                atr_pct = row['ATR'] / row['close']
                if atr_pct < Config.ATR_MIN_PCT:
                    continue
                    
                # MTF Trend Check (Simulated)
                # We need to access higher timeframe data. 
                # For simplicity in this script, we will approximate MTF by checking if the 15m EMA 200 is trending? 
                # No, that's not accurate. 
                # Since we don't have 1H data loaded in the backtester easily without refactoring DataLoader,
                # We will skip MTF check in simulation for now but rely on the stricter ADX/RSI which ARE checked.
                # However, to be realistic, we should at least simulate the "filtering" effect.
                # Let's assume MTF filter cuts trades by 50% randomly? No, that's bad science.
                # Let's rely on the stricter ADX (25) and RSI which are implemented in EntrySignals.check_signals
                
                # Check Long
                long_ok, _ = EntrySignals.check_signals(df.iloc[:i+1], "LONG")
                if long_ok:
                    self._open_position(row, "LONG")
                    position = self.current_position
                    continue
                
                # Check Short
                short_ok, _ = EntrySignals.check_signals(df.iloc[:i+1], "SHORT")
                if short_ok:
                    self._open_position(row, "SHORT")
                    position = self.current_position

        return self._calculate_metrics()

    def _open_position(self, row, direction):
        try:
            atr = row['ATR']
            entry_price = row['close']
            sl = ATRManager.calculate_initial_stop(entry_price, atr, direction)
            
            # Risk Calculation
            risk_amt = self.balance * Config.RISK_PER_TRADE_PCT
            dist = abs(entry_price - sl)
            if dist == 0: return
            size = risk_amt / dist
            
            self.current_position = {
                'type': direction,
                'entry_price': entry_price,
                'size': size,
                'sl': sl,
                'status': 'OPEN',
                'pnl': 0,
                'entry_time': row['timestamp'],
                'highest_price': entry_price, # For trailing
                'lowest_price': entry_price
            }
        except Exception as e:
            # logger.error(f"Backtest Open Position Error: {e}")
            pass

    def _check_exit(self, pos, row):
        # 1. Check SL
        if pos['type'] == 'LONG':
            if row['low'] <= pos['sl']:
                pos['status'] = 'CLOSED'
                pos['exit_price'] = pos['sl']
                pos['pnl'] = (pos['sl'] - pos['entry_price']) * pos['size']
                return
            
            # Breakeven Check
            if not pos.get('breakeven_triggered', False):
                pnl_pct = (row['high'] - pos['entry_price']) / pos['entry_price']
                if pnl_pct >= Config.BREAKEVEN_TRIGGER_PCT:
                    pos['sl'] = max(pos['sl'], pos['entry_price'] * 1.001)
                    pos['breakeven_triggered'] = True

            # Update Trailing
            if row['high'] > pos['highest_price']:
                pos['highest_price'] = row['high']
                # Recalculate Trailing SL
                new_sl = ATRManager.calculate_trailing_stop(pos['sl'], pos['highest_price'], row['ATR'], "LONG", pos['entry_price'])
                pos['sl'] = max(pos['sl'], new_sl)

        else: # SHORT
            if row['high'] >= pos['sl']:
                pos['status'] = 'CLOSED'
                pos['exit_price'] = pos['sl']
                pos['pnl'] = (pos['entry_price'] - pos['sl']) * pos['size']
                return

            # Breakeven Check
            if not pos.get('breakeven_triggered', False):
                pnl_pct = (pos['entry_price'] - row['low']) / pos['entry_price']
                if pnl_pct >= Config.BREAKEVEN_TRIGGER_PCT:
                    pos['sl'] = min(pos['sl'], pos['entry_price'] * 0.999)
                    pos['breakeven_triggered'] = True

            # Update Trailing
            if row['low'] < pos['lowest_price']:
                pos['lowest_price'] = row['low']
                new_sl = ATRManager.calculate_trailing_stop(pos['sl'], pos['lowest_price'], row['ATR'], "SHORT", pos['entry_price'])
                pos['sl'] = min(pos['sl'], new_sl)

    def _calculate_metrics(self):
        if not self.trades:
            return {'sharpe': 0, 'total_pnl': 0, 'win_rate': 0, 'trades': 0}
            
        df_trades = pd.DataFrame(self.trades)
        total_pnl = df_trades['net_pnl'].sum()
        win_rate = len(df_trades[df_trades['net_pnl'] > 0]) / len(df_trades)
        
        # Sharpe (simplified based on trade returns)
        returns = df_trades['net_pnl'] / self.initial_balance
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(len(self.trades)) if np.std(returns) != 0 else 0
        
        return {
            'sharpe': sharpe,
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'trades': len(self.trades),
            'final_balance': self.balance
        }
