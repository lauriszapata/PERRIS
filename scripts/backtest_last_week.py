"""
Backtest para la Semana Pasada (18-24 Nov 2025)
Replica exactamente la lógica actual del bot con prevención de look-ahead bias.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import Config
from modules.backtest.data_loader import DataLoader
from modules.indicators import Indicators
from modules.entry_signals import EntrySignals
from modules.managers.atr_manager import ATRManager
from modules.logger import logger


class ExactBotBacktester:
    """
    Backtest que replica exactamente la lógica del bot actual.
    """
    
    def __init__(self, initial_balance=10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.commission_rate = Config.COMMISSION_RATE  # 0.045%
        
        # Portfolio tracking
        self.open_positions = {}  # {symbol: position_data}
        self.closed_trades = []
        self.equity_curve = []
        
        # Cooldown tracking
        self.symbol_cooldowns = {}  # {symbol: exit_timestamp}
        
        # Config
        self.max_open_symbols = Config.MAX_OPEN_SYMBOLS  # 3
        self.cooldown_minutes = Config.SYMBOL_COOLDOWN_MINUTES  # 30
        self.fixed_exposure_usd = Config.FIXED_TRADE_EXPOSURE_USD  # 125 USD
        self.leverage = Config.LEVERAGE  # 1x
        
    def run_backtest(self, data_map, start_date, end_date):
        """
        Run backtest across multiple symbols with portfolio constraints.
        
        Args:
            data_map: {symbol: df with OHLCV data}
            start_date: datetime
            end_date: datetime
        """
        print(f"\n{'='*80}")
        print(f"🔬 BACKTEST: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print(f"{'='*80}")
        print(f"Config: Leverage={self.leverage}x, Exposure=${self.fixed_exposure_usd}, Max Symbols={self.max_open_symbols}")
        print(f"        SL=2.5 ATR, TP=Infinite Scalping, Commission={self.commission_rate:.3%}")
        print(f"{'='*80}\n")
        
        # Prepare data: Calculate indicators for each symbol (once)
        prepared_data = {}
        for symbol, df in data_map.items():
            df = df.copy()
            df = Indicators.calculate_all(df)
            
            # Filter to date range
            df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]
            
            if len(df) > 50:  # Need enough data
                prepared_data[symbol] = df
        
        if not prepared_data:
            print("❌ No data available for backtest period.")
            return
        
        # Create unified timeline (all timestamps from all symbols)
        all_timestamps = set()
        for df in prepared_data.values():
            all_timestamps.update(df['timestamp'].tolist())
        
        timeline = sorted(all_timestamps)
        
        print(f"📊 Data loaded: {len(prepared_data)} symbols, {len(timeline)} candles")
        print(f"📅 Period: {timeline[0]} to {timeline[-1]}\n")
        
        # Simulate candle by candle
        for i, current_time in enumerate(timeline):
            # Get current price data for all symbols
            current_prices = {}
            for symbol, df in prepared_data.items():
                # CRITICAL: Only use data UP TO current_time (no look-ahead)
                df_slice = df[df['timestamp'] <= current_time]
                if len(df_slice) > 0:
                    current_prices[symbol] = df_slice.iloc[-1]
            
            # Update equity curve
            self._record_equity(current_time, current_prices)
            
            # 1. Monitor and manage existing positions
            self._monitor_positions(current_time, current_prices, prepared_data)
            
            # 2. Look for new entries (if we have capacity)
            if len(self.open_positions) < self.max_open_symbols:
                self._look_for_entries(current_time, current_prices, prepared_data)
        
        # Close any remaining positions at the end
        if self.open_positions:
            print(f"\n⚠️  Closing {len(self.open_positions)} remaining positions at end of backtest...")
            for symbol in list(self.open_positions.keys()):
                if symbol in current_prices:
                    self._close_position(symbol, current_prices[symbol]['close'], current_time, "END_OF_BACKTEST")
        
        return self._generate_report()
    
    def _monitor_positions(self, current_time, current_prices, data_map):
        """Monitor and manage open positions (SL, TP, trailing)."""
        for symbol in list(self.open_positions.keys()):
            if symbol not in current_prices:
                continue
            
            pos = self.open_positions[symbol]
            current_row = current_prices[symbol]
            current_price = current_row['close']
            current_high = current_row['high']
            current_low = current_row['low']
            current_atr = current_row['ATR']
            
            # Calculate PnL
            if pos['direction'] == 'LONG':
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
            else:
                pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price']
            
            # 1. Check Stop Loss
            if pos['direction'] == 'LONG':
                if current_low <= pos['sl']:
                    self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                    continue
            else:
                if current_high >= pos['sl']:
                    self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                    continue
            
            # 2. Check Take Profit (Infinite Scalping)
            self._check_infinite_scalping_tp(symbol, pos, current_price, current_high, current_low, current_time)
            
            # If position was closed by TP, skip trailing
            if symbol not in self.open_positions:
                continue
            
            # 3. Breakeven Check
            if not pos.get('breakeven_triggered', False):
                if pnl_pct >= Config.BREAKEVEN_TRIGGER_PCT:  # 0.8%
                    if pos['direction'] == 'LONG':
                        pos['sl'] = max(pos['sl'], pos['entry_price'] * 1.001)
                    else:
                        pos['sl'] = min(pos['sl'], pos['entry_price'] * 0.999)
                    pos['breakeven_triggered'] = True
            
            # 4. Trailing Stop
            if pos['direction'] == 'LONG':
                if current_high > pos['highest_price']:
                    pos['highest_price'] = current_high
                    new_sl = ATRManager.calculate_trailing_stop(
                        pos['sl'], pos['highest_price'], current_atr, 'LONG', pos['entry_price']
                    )
                    pos['sl'] = max(pos['sl'], new_sl)
            else:
                if current_low < pos['lowest_price']:
                    pos['lowest_price'] = current_low
                    new_sl = ATRManager.calculate_trailing_stop(
                        pos['sl'], pos['lowest_price'], current_atr, 'SHORT', pos['entry_price']
                    )
                    pos['sl'] = min(pos['sl'], new_sl)
    
    def _check_infinite_scalping_tp(self, symbol, pos, current_price, current_high, current_low, current_time):
        """
        Infinite Scalping TP Strategy:
        - P1-P4: Fixed levels (1.2%, 1.6%, 2.0%, 2.5%) → Close 20% each
        - Dynamic: Every 0.5% after P4 → Close 5% each
        - Never closes 100%
        """
        if pos['direction'] == 'LONG':
            price_to_check = current_high
        else:
            price_to_check = current_low
        
        # Calculate current PnL %
        if pos['direction'] == 'LONG':
            pnl_pct = (price_to_check - pos['entry_price']) / pos['entry_price']
        else:
            pnl_pct = (pos['entry_price'] - price_to_check) / pos['entry_price']
        
        # Fixed TP Levels (P1-P4)
        fixed_levels = Config.TAKE_PROFIT_LEVELS  # From config
        for level in fixed_levels:
            level_key = level['name']
            if level_key not in pos['tp_triggered']:
                if pnl_pct >= level['pct']:
                    # Trigger TP
                    close_pct = level['close_pct']
                    self._close_partial(symbol, pos, close_pct, price_to_check, current_time, level_key)
                    pos['tp_triggered'].add(level_key)
        
        # Dynamic Scalping Levels (after P4)
        if pnl_pct >= Config.DYNAMIC_SCALPING_START:
            # Calculate which dynamic level we're at
            dynamic_levels_passed = int((pnl_pct - Config.DYNAMIC_SCALPING_START) / Config.DYNAMIC_SCALPING_INCREMENT)
            
            # Check each dynamic level
            for n in range(dynamic_levels_passed + 1):
                level_pct = Config.DYNAMIC_SCALPING_START + (n * Config.DYNAMIC_SCALPING_INCREMENT)
                level_key = f"D{n+1}"  # D1, D2, D3...
                
                if level_key not in pos['tp_triggered'] and pnl_pct >= level_pct:
                    # Trigger Dynamic TP
                    close_pct = Config.DYNAMIC_SCALPING_CLOSE_PCT  # 5%
                    self._close_partial(symbol, pos, close_pct, price_to_check, current_time, level_key)
                    pos['tp_triggered'].add(level_key)
    
    def _close_partial(self, symbol, pos, close_pct, exit_price, exit_time, reason):
        """Close a portion of the position."""
        # Calculate portion to close
        size_to_close = pos['current_size'] * close_pct
        
        # Minimum size check (don't close dust)
        if size_to_close < 0.01:  # Arbitrary minimum
            return
        
        # Calculate PnL for this partial
        if pos['direction'] == 'LONG':
            pnl = (exit_price - pos['entry_price']) * size_to_close
        else:
            pnl = (pos['entry_price'] - exit_price) * size_to_close
        
        # Calculate commission
        entry_value = pos['entry_price'] * size_to_close
        exit_value = exit_price * size_to_close
        commission = (entry_value + exit_value) * self.commission_rate
        
        net_pnl = pnl - commission
        
        # Update position size
        pos['current_size'] -= size_to_close
        
        # Record partial close
        self.closed_trades.append({
            'symbol': symbol,
            'direction': pos['direction'],
            'entry_time': pos['entry_time'],
            'exit_time': exit_time,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'size': size_to_close,
            'pnl': pnl,
            'commission': commission,
            'net_pnl': net_pnl,
            'exit_reason': f"TP_{reason}",
            'partial': True
        })
        
        self.balance += net_pnl
        
        # If position is too small, close the rest
        if pos['current_size'] < 0.01:
            self._close_position(symbol, exit_price, exit_time, f"TP_{reason}_FINAL")
    
    def _close_position(self, symbol, exit_price, exit_time, reason):
        """Fully close a position."""
        if symbol not in self.open_positions:
            return
        
        pos = self.open_positions[symbol]
        
        # Calculate final PnL
        if pos['direction'] == 'LONG':
            pnl = (exit_price - pos['entry_price']) * pos['current_size']
        else:
            pnl = (pos['entry_price'] - exit_price) * pos['current_size']
        
        # Commission
        entry_value = pos['entry_price'] * pos['current_size']
        exit_value = exit_price * pos['current_size']
        commission = (entry_value + exit_value) * self.commission_rate
        
        net_pnl = pnl - commission
        
        # Record trade
        self.closed_trades.append({
            'symbol': symbol,
            'direction': pos['direction'],
            'entry_time': pos['entry_time'],
            'exit_time': exit_time,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'size': pos['current_size'],
            'pnl': pnl,
            'commission': commission,
            'net_pnl': net_pnl,
            'exit_reason': reason,
            'partial': False
        })
        
        self.balance += net_pnl
        
        # Set cooldown
        self.symbol_cooldowns[symbol] = exit_time
        
        # Remove position
        del self.open_positions[symbol]
    
    def _look_for_entries(self, current_time, current_prices, data_map):
        """Look for entry signals across all symbols."""
        # Evaluate all symbols
        candidates = []
        
        for symbol, df in data_map.items():
            # Skip if already in position
            if symbol in self.open_positions:
                continue
            
            # Skip if in cooldown
            if symbol in self.symbol_cooldowns:
                cooldown_end = self.symbol_cooldowns[symbol] + timedelta(minutes=self.cooldown_minutes)
                if current_time < cooldown_end:
                    continue
            
            # Get current data (NO LOOK-AHEAD)
            df_slice = df[df['timestamp'] <= current_time].copy()
            if len(df_slice) < 50:  # Need enough history
                continue
            
            current_row = df_slice.iloc[-1]
            
            # Check entry signals for LONG
            long_ok, long_details = EntrySignals.check_signals(df_slice, "LONG")
            if long_ok:
                score = EntrySignals.calculate_score(long_details)
                candidates.append({
                    'symbol': symbol,
                    'direction': 'LONG',
                    'score': score,
                    'row': current_row,
                    'df': df_slice
                })
            
            # Check entry signals for SHORT
            short_ok, short_details = EntrySignals.check_signals(df_slice, "SHORT")
            if short_ok:
                score = EntrySignals.calculate_score(short_details)
                candidates.append({
                    'symbol': symbol,
                    'direction': 'SHORT',
                    'score': score,
                    'row': current_row,
                    'df': df_slice
                })
        
        # Take best candidates up to available slots
        if candidates:
            candidates.sort(key=lambda x: x['score'], reverse=True)
            slots_available = self.max_open_symbols - len(self.open_positions)
            
            for candidate in candidates[:slots_available]:
                self._open_position(
                    candidate['symbol'],
                    candidate['direction'],
                    candidate['row'],
                    current_time
                )
    
    def _open_position(self, symbol, direction, row, entry_time):
        """Open a new position."""
        entry_price = row['close']
        atr = row['ATR']
        
        # Calculate SL
        sl = ATRManager.calculate_initial_stop(entry_price, atr, direction)
        
        # Calculate position size based on fixed exposure
        # Exposure = entry_price * size / leverage
        # size = (exposure * leverage) / entry_price
        size = (self.fixed_exposure_usd * self.leverage) / entry_price
        
        # Position data
        position = {
            'symbol': symbol,
            'direction': direction,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'initial_size': size,
            'current_size': size,
            'sl': sl,
            'highest_price': entry_price if direction == 'LONG' else float('inf'),
            'lowest_price': entry_price if direction == 'SHORT' else float('inf'),
            'tp_triggered': set(),  # Track which TP levels hit
            'breakeven_triggered': False
        }
        
        self.open_positions[symbol] = position
        
        print(f"📈 ENTRY: {symbol} {direction} @ ${entry_price:.4f} | Size: {size:.4f} | SL: ${sl:.4f} | Time: {entry_time}")
    
    def _record_equity(self, current_time, current_prices):
        """Record equity curve."""
        total_equity = self.balance
        
        # Add unrealized PnL from open positions
        for symbol, pos in self.open_positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]['close']
                if pos['direction'] == 'LONG':
                    unrealized = (current_price - pos['entry_price']) * pos['current_size']
                else:
                    unrealized = (pos['entry_price'] - current_price) * pos['current_size']
                total_equity += unrealized
        
        self.equity_curve.append({
            'timestamp': current_time,
            'equity': total_equity,
            'balance': self.balance,
            'open_positions': len(self.open_positions)
        })
    
    def _generate_report(self):
        """Generate comprehensive backtest report."""
        print(f"\n{'='*80}")
        print(f"📊 BACKTEST RESULTS")
        print(f"{'='*80}\n")
        
        if not self.closed_trades:
            print("❌ No trades executed during backtest period.")
            return
        
        # Convert trades to DataFrame
        df_trades = pd.DataFrame(self.closed_trades)
        
        # Overall Metrics
        total_pnl = df_trades['net_pnl'].sum()
        total_commission = df_trades['commission'].sum()
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades['net_pnl'] > 0])
        losing_trades = len(df_trades[df_trades['net_pnl'] <= 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Profit Factor
        gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(df_trades[df_trades['net_pnl'] <= 0]['net_pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Sharpe Ratio (simplified)
        returns = df_trades['net_pnl'] / self.initial_balance
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(total_trades) if np.std(returns) > 0 else 0
        
        # Max Drawdown
        equity_series = pd.Series([e['equity'] for e in self.equity_curve])
        rolling_max = equity_series.expanding().max()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        # Average Trade Duration
        df_trades['duration'] = (df_trades['exit_time'] - df_trades['entry_time']).dt.total_seconds() / 3600  # hours
        avg_duration = df_trades['duration'].mean()
        
        # Print Report
        print(f"💰 Total PnL: ${total_pnl:,.2f} ({(total_pnl/self.initial_balance)*100:.2f}%)")
        print(f"💵 Final Balance: ${self.balance:,.2f}")
        print(f"📈 Return: {((self.balance - self.initial_balance) / self.initial_balance) * 100:.2f}%")
        print(f"\n📊 Trade Statistics:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Winning: {winning_trades} ({win_rate*100:.1f}%)")
        print(f"   Losing: {losing_trades} ({(1-win_rate)*100:.1f}%)")
        print(f"   Win Rate: {win_rate*100:.1f}%")
        print(f"\n💪 Performance Metrics:")
        print(f"   Profit Factor: {profit_factor:.2f}")
        print(f"   Sharpe Ratio: {sharpe:.2f}")
        print(f"   Max Drawdown: {max_drawdown*100:.2f}%")
        print(f"   Avg Trade Duration: {avg_duration:.1f} hours")
        print(f"\n💸 Costs:")
        print(f"   Total Commissions: ${total_commission:.2f}")
        print(f"   Commission Rate: {self.commission_rate:.3%}")
        
        # Per-Symbol Breakdown
        print(f"\n📋 Per-Symbol Breakdown:")
        symbol_stats = df_trades.groupby('symbol').agg({
            'net_pnl': ['sum', 'count', 'mean'],
        }).round(2)
        symbol_stats.columns = ['Total PnL', 'Trades', 'Avg PnL']
        symbol_stats = symbol_stats.sort_values('Total PnL', ascending=False)
        print(symbol_stats.to_string())
        
        # Save Trade Log
        csv_filename = f"/Users/laurazapata/Desktop/BACKTEST_TRADES_NOV18-24.csv"
        df_trades.to_csv(csv_filename, index=False)
        print(f"\n💾 Trade log saved to: {csv_filename}")
        
        print(f"\n{'='*80}\n")
        
        return {
            'total_pnl': total_pnl,
            'final_balance': self.balance,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'sharpe': sharpe,
            'max_drawdown': max_drawdown,
            'trades_df': df_trades
        }


def main():
    """Main backtest execution."""
    # Date range: Semana pasada (18-24 Nov 2025)
    # NOTE: User timestamp is Nov 25, so last week is roughly Nov 18-24
    start_date = datetime(2025, 11, 18, 0, 0, 0)
    end_date = datetime(2025, 11, 24, 23, 59, 59)
    
    print("\n🚀 Starting Backtest for Last Week...")
    print(f"📅 Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}\n")
    
    # Load data
    loader = DataLoader()
    print("📡 Downloading historical data...")
    
    data_map = {}
    for symbol in Config.SYMBOLS:
        try:
            df = loader.fetch_data_range(
                symbol,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
                Config.TIMEFRAME
            )
            if df is not None and len(df) > 0:
                data_map[symbol] = df
                print(f"   ✅ {symbol}: {len(df)} candles")
            else:
                print(f"   ⚠️  {symbol}: No data")
        except Exception as e:
            print(f"   ❌ {symbol}: Error - {e}")
    
    if not data_map:
        print("\n❌ No data available. Cannot run backtest.")
        return
    
    print(f"\n✅ Data loaded for {len(data_map)} symbols\n")
    
    # Run backtest
    backtester = ExactBotBacktester(initial_balance=10000)
    results = backtester.run_backtest(data_map, start_date, end_date)
    
    print("\n✅ Backtest completed!")


if __name__ == "__main__":
    main()
