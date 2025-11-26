"""
Backtest SUPER-OPTIMIZADO - Marzo 2025
MAX 1 POSICIÓN SIMULTÁNEA (vs 3)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import Config
from modules.backtest.data_loader import DataLoader
from modules.indicators import Indicators

SUPER_OPTIMIZED_CONFIG = {
    'TRADING_START_HOUR': 5,
    'TRADING_END_HOUR': 11,
    'TRADING_END_MINUTE': 50,
    'SL_ATR_MULTIPLIER': 4.0,
    'TRAILING_SL_ATR_MULTIPLIER': 2.0,
    'FIXED_EXPOSURE_USD': 150,
    'TP_LEVELS': [
        {"pct": 0.020, "close_pct": 0.30, "name": "P1"},
        {"pct": 0.035, "close_pct": 0.30, "name": "P2"},
    ],
    'DYNAMIC_SCALPING_START': 0.050,
    'DYNAMIC_SCALPING_INCREMENT': 0.010,
    'DYNAMIC_SCALPING_CLOSE_PCT': 0.10,
    'ADX_MIN': 25,
    'VOLUME_MIN_MULTIPLIER': 1.3,
    'VOLATILITY_MAX': 0.025,
}

SYMBOL_BLACKLIST_EXPANDED = [
    "POL/USDT", "NEAR/USDT", "APT/USDT", "TRX/USDT", "LINK/USDT",
    "TIA/USDT", "BNB/USDT", "BCH/USDT", "OP/USDT", "DOT/USDT"
]

SUPER_OPTIMIZED_SYMBOLS = [s for s in Config.SYMBOLS if s not in SYMBOL_BLACKLIST_EXPANDED]

class ATRManagerSuperOptimized:
    @staticmethod
    def calculate_initial_stop(entry_price, atr_entry, direction):
        multiplier = SUPER_OPTIMIZED_CONFIG['SL_ATR_MULTIPLIER']
        if direction == "LONG":
            sl = entry_price - (multiplier * atr_entry)
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
        multiplier = SUPER_OPTIMIZED_CONFIG['TRAILING_SL_ATR_MULTIPLIER']
        if direction == "LONG":
            sl_prop = extreme_price - (multiplier * current_atr)
            return max(current_sl, sl_prop)
        else:
            sl_prop = extreme_price + (multiplier * current_atr)
            return min(current_sl, sl_prop)

class EntrySignalsSuperOptimized:
    @staticmethod
    def check_signals(df, direction):
        results = {}
        try:
            last = df.iloc[-1]
            from modules.managers.trend_manager import TrendManager
            trend_ok = TrendManager.check_trend(df, direction)
            results['Trend'] = {'status': trend_ok}
            
            adx_val = last['ADX']
            results['ADX'] = {'status': adx_val >= SUPER_OPTIMIZED_CONFIG['ADX_MIN']}
            
            rsi_val = last['RSI']
            if direction == "LONG":
                results['RSI'] = {'status': rsi_val > 35}
            else:
                results['RSI'] = {'status': 30 < rsi_val < 55}
            
            macd_line = last['MACD_line']
            macd_signal = last['MACD_signal']
            if direction == "LONG":
                results['MACD'] = {'status': macd_line > macd_signal}
            else:
                results['MACD'] = {'status': macd_line < macd_signal}
            
            vol = last['volume']
            vol_avg = last['Vol_SMA20']
            results['Volume'] = {'status': vol >= SUPER_OPTIMIZED_CONFIG['VOLUME_MIN_MULTIPLIER'] * vol_avg}
            
            atr_val = last['ATR']
            close_val = last['close']
            volatility_pct = atr_val / close_val
            results['Volatility'] = {'status': volatility_pct < SUPER_OPTIMIZED_CONFIG['VOLATILITY_MAX']}
            
            results['MTF_Trend'] = {'status': True, 'optional': True}
            results['Structure'] = {'status': True, 'optional': True}
            
            standard_entry = all(r['status'] for k, r in results.items() if not r.get('optional', False))
            
            if not standard_entry:
                ema8 = last['EMA8']
                ema20 = last['EMA20']
                fast_trend_ok = (ema8 > ema20) if direction == "LONG" else (ema8 < ema20)
                if fast_trend_ok and results['MACD']['status'] and results['RSI']['status'] and results['Volume']['status'] and results['Volatility']['status']:
                    return True, results
            
            return standard_entry, results
        except Exception as e:
            return False, {'Error': str(e)}

class SinglePositionBacktester:
    def __init__(self, initial_balance=10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.commission_rate = Config.COMMISSION_RATE
        
        self.open_positions = {}
        self.closed_trades = []
        self.equity_curve = []
        self.symbol_cooldowns = {}
        
        self.max_open_symbols = 1  # SOLO 1 POSICIÓN
        self.cooldown_minutes = Config.SYMBOL_COOLDOWN_MINUTES
        self.fixed_exposure_usd = SUPER_OPTIMIZED_CONFIG['FIXED_EXPOSURE_USD']
        self.leverage = Config.LEVERAGE
    
    def is_trading_hours(self, timestamp):
        hour = timestamp.hour
        minute = timestamp.minute
        if hour < SUPER_OPTIMIZED_CONFIG['TRADING_START_HOUR']:
            return False
        if hour > SUPER_OPTIMIZED_CONFIG['TRADING_END_HOUR']:
            return False
        if hour == SUPER_OPTIMIZED_CONFIG['TRADING_END_HOUR'] and minute >= SUPER_OPTIMIZED_CONFIG['TRADING_END_MINUTE']:
            return False
        return True
    
    def run_backtest(self, data_map, start_date, end_date):
        print(f"\n{'='*80}")
        print(f"🔬 BACKTEST: 1 POSICIÓN SIMULTÁNEA - MARZO 2025")
        print(f"{'='*80}")
        print(f"MAX POSITIONS: 1 (vs 3)")
        print(f"Horario: 5:00 AM - 11:50 AM")
        print(f"SL: {SUPER_OPTIMIZED_CONFIG['SL_ATR_MULTIPLIER']}x ATR")
        print(f"Símbolos: {len(SUPER_OPTIMIZED_SYMBOLS)} (blacklist: 10)")
        print(f"{'='*80}\n")
        
        prepared_data = {}
        for symbol, df in data_map.items():
            df = df.copy()
            df = Indicators.calculate_all(df)
            df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]
            if len(df) > 50:
                prepared_data[symbol] = df
        
        if not prepared_data:
            print("❌ No data.")
            return
        
        all_timestamps = set()
        for df in prepared_data.values():
            all_timestamps.update(df['timestamp'].tolist())
        timeline = sorted(all_timestamps)
        
        print(f"📊 Data: {len(prepared_data)} symbols, {len(timeline)} candles\n")
        
        for current_time in timeline:
            if not self.is_trading_hours(current_time):
                current_prices = {}
                for symbol, df in prepared_data.items():
                    df_slice = df[df['timestamp'] <= current_time]
                    if len(df_slice) > 0:
                        current_prices[symbol] = df_slice.iloc[-1]
                self._record_equity(current_time, current_prices)
                self._monitor_positions(current_time, current_prices, prepared_data)
                continue
            
            current_prices = {}
            for symbol, df in prepared_data.items():
                df_slice = df[df['timestamp'] <= current_time]
                if len(df_slice) > 0:
                    current_prices[symbol] = df_slice.iloc[-1]
            
            self._record_equity(current_time, current_prices)
            self._monitor_positions(current_time, current_prices, prepared_data)
            
            if len(self.open_positions) < self.max_open_symbols:
                self._look_for_entries(current_time, current_prices, prepared_data)
        
        if self.open_positions:
            for symbol in list(self.open_positions.keys()):
                if symbol in current_prices:
                    self._close_position(symbol, current_prices[symbol]['close'], current_time, "END")
        
        return self._generate_report()
    
    def _monitor_positions(self, current_time, current_prices, data_map):
        for symbol in list(self.open_positions.keys()):
            if symbol not in current_prices:
                continue
            pos = self.open_positions[symbol]
            current_row = current_prices[symbol]
            current_price = current_row['close']
            current_high = current_row['high']
            current_low = current_row['low']
            current_atr = current_row['ATR']
            
            if pos['direction'] == 'LONG':
                if current_low <= pos['sl']:
                    self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                    continue
            else:
                if current_high >= pos['sl']:
                    self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                    continue
            
            self._check_tp(symbol, pos, current_price, current_high, current_low, current_time)
            if symbol not in self.open_positions:
                continue
            
            if pos['direction'] == 'LONG':
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
            else:
                pnl_pct = (pos['entry_price'] - current_price) / pos['entry_price']
            
            if not pos.get('breakeven_triggered', False):
                if pnl_pct >= Config.BREAKEVEN_TRIGGER_PCT:
                    if pos['direction'] == 'LONG':
                        pos['sl'] = max(pos['sl'], pos['entry_price'] * 1.001)
                    else:
                        pos['sl'] = min(pos['sl'], pos['entry_price'] * 0.999)
                    pos['breakeven_triggered'] = True
            
            if pos['direction'] == 'LONG':
                if current_high > pos['highest_price']:
                    pos['highest_price'] = current_high
                    new_sl = ATRManagerSuperOptimized.calculate_trailing_stop(pos['sl'], pos['highest_price'], current_atr, 'LONG', pos['entry_price'])
                    pos['sl'] = max(pos['sl'], new_sl)
            else:
                if current_low < pos['lowest_price']:
                    pos['lowest_price'] = current_low
                    new_sl = ATRManagerSuperOptimized.calculate_trailing_stop(pos['sl'], pos['lowest_price'], current_atr, 'SHORT', pos['entry_price'])
                    pos['sl'] = min(pos['sl'], new_sl)
    
    def _check_tp(self, symbol, pos, current_price, current_high, current_low, current_time):
        if pos['direction'] == 'LONG':
            price_to_check = current_high
            pnl_pct = (price_to_check - pos['entry_price']) / pos['entry_price']
        else:
            price_to_check = current_low
            pnl_pct = (pos['entry_price'] - price_to_check) / pos['entry_price']
        
        for level in SUPER_OPTIMIZED_CONFIG['TP_LEVELS']:
            level_key = level['name']
            if level_key not in pos['tp_triggered']:
                if pnl_pct >= level['pct']:
                    self._close_partial(symbol, pos, level['close_pct'], price_to_check, current_time, level_key)
                    pos['tp_triggered'].add(level_key)
        
        if pnl_pct >= SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_START']:
            dynamic_levels = int((pnl_pct - SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_START']) / SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_INCREMENT'])
            for n in range(dynamic_levels + 1):
                level_pct = SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_START'] + (n * SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_INCREMENT'])
                level_key = f"D{n+1}"
                if level_key not in pos['tp_triggered'] and pnl_pct >= level_pct:
                    self._close_partial(symbol, pos, SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_CLOSE_PCT'], price_to_check, current_time, level_key)
                    pos['tp_triggered'].add(level_key)
    
    def _close_partial(self, symbol, pos, close_pct, exit_price, exit_time, reason):
        size_to_close = pos['current_size'] * close_pct
        if size_to_close < 0.01:
            return
        if pos['direction'] == 'LONG':
            pnl = (exit_price - pos['entry_price']) * size_to_close
        else:
            pnl = (pos['entry_price'] - exit_price) * size_to_close
        entry_value = pos['entry_price'] * size_to_close
        exit_value = exit_price * size_to_close
        commission = (entry_value + exit_value) * self.commission_rate
        net_pnl = pnl - commission
        pos['current_size'] -= size_to_close
        self.closed_trades.append({'symbol': symbol, 'direction': pos['direction'], 'entry_time': pos['entry_time'], 'exit_time': exit_time, 'entry_price': pos['entry_price'], 'exit_price': exit_price, 'size': size_to_close, 'pnl': pnl, 'commission': commission, 'net_pnl': net_pnl, 'exit_reason': f"TP_{reason}", 'partial': True})
        self.balance += net_pnl
        if pos['current_size'] < 0.01:
            self._close_position(symbol, exit_price, exit_time, f"TP_{reason}_FINAL")
    
    def _close_position(self, symbol, exit_price, exit_time, reason):
        if symbol not in self.open_positions:
            return
        pos = self.open_positions[symbol]
        if pos['direction'] == 'LONG':
            pnl = (exit_price - pos['entry_price']) * pos['current_size']
        else:
            pnl = (pos['entry_price'] - exit_price) * pos['current_size']
        entry_value = pos['entry_price'] * pos['current_size']
        exit_value = exit_price * pos['current_size']
        commission = (entry_value + exit_value) * self.commission_rate
        net_pnl = pnl - commission
        self.closed_trades.append({'symbol': symbol, 'direction': pos['direction'], 'entry_time': pos['entry_time'], 'exit_time': exit_time, 'entry_price': pos['entry_price'], 'exit_price': exit_price, 'size': pos['current_size'], 'pnl': pnl, 'commission': commission, 'net_pnl': net_pnl, 'exit_reason': reason, 'partial': False})
        self.balance += net_pnl
        self.symbol_cooldowns[symbol] = exit_time
        del self.open_positions[symbol]
    
    def _look_for_entries(self, current_time, current_prices, data_map):
        candidates = []
        for symbol, df in data_map.items():
            if symbol in self.open_positions:
                continue
            if symbol in self.symbol_cooldowns:
                cooldown_end = self.symbol_cooldowns[symbol] + timedelta(minutes=self.cooldown_minutes)
                if current_time < cooldown_end:
                    continue
            df_slice = df[df['timestamp'] <= current_time].copy()
            if len(df_slice) < 50:
                continue
            current_row = df_slice.iloc[-1]
            long_ok, _ = EntrySignalsSuperOptimized.check_signals(df_slice, "LONG")
            if long_ok:
                candidates.append({'symbol': symbol, 'direction': 'LONG', 'row': current_row, 'score': current_row['ADX']})
            short_ok, _ = EntrySignalsSuperOptimized.check_signals(df_slice, "SHORT")
            if short_ok:
                candidates.append({'symbol': symbol, 'direction': 'SHORT', 'row': current_row, 'score': current_row['ADX']})
        
        if candidates:
            # Take BEST opportunity (highest ADX)
            candidates.sort(key=lambda x: x['score'], reverse=True)
            best = candidates[0]
            self._open_position(best['symbol'], best['direction'], best['row'], current_time)
    
    def _open_position(self, symbol, direction, row, entry_time):
        entry_price = row['close']
        atr = row['ATR']
        sl = ATRManagerSuperOptimized.calculate_initial_stop(entry_price, atr, direction)
        size = (self.fixed_exposure_usd * self.leverage) / entry_price
        self.open_positions[symbol] = {'symbol': symbol, 'direction': direction, 'entry_price': entry_price, 'entry_time': entry_time, 'initial_size': size, 'current_size': size, 'sl': sl, 'highest_price': entry_price if direction == 'LONG' else float('inf'), 'lowest_price': entry_price if direction == 'SHORT' else float('inf'), 'tp_triggered': set(), 'breakeven_triggered': False}
    
    def _record_equity(self, current_time, current_prices):
        total_equity = self.balance
        for symbol, pos in self.open_positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]['close']
                if pos['direction'] == 'LONG':
                    unrealized = (current_price - pos['entry_price']) * pos['current_size']
                else:
                    unrealized = (pos['entry_price'] - current_price) * pos['current_size']
                total_equity += unrealized
        self.equity_curve.append({'timestamp': current_time, 'equity': total_equity})
    
    def _generate_report(self):
        print(f"\n{'='*80}")
        print(f"📊 RESULTADOS - 1 POSICIÓN (MARZO 2025)")
        print(f"{'='*80}\n")
        if not self.closed_trades:
            print("❌ No trades.")
            return
        df_trades = pd.DataFrame(self.closed_trades)
        total_pnl = df_trades['net_pnl'].sum()
        total_commission = df_trades['commission'].sum()
        total_trades = len(df_trades)
        winning_trades = len(df_trades[df_trades['net_pnl'] > 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(df_trades[df_trades['net_pnl'] <= 0]['net_pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        returns = df_trades['net_pnl'] / self.initial_balance
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(total_trades) if np.std(returns) > 0 else 0
        equity_series = pd.Series([e['equity'] for e in self.equity_curve])
        rolling_max = equity_series.expanding().max()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        df_trades['duration'] = (df_trades['exit_time'] - df_trades['entry_time']).dt.total_seconds() / 3600
        avg_duration = df_trades['duration'].mean()
        
        print(f"💰 Total PnL: ${total_pnl:,.2f} ({(total_pnl/self.initial_balance)*100:.2f}%)")
        print(f"💵 Final Balance: ${self.balance:,.2f}")
        print(f"📈 Return: {((self.balance - self.initial_balance) / self.initial_balance) * 100:.2f}%")
        print(f"\n📊 Trade Statistics:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Winning: {winning_trades} ({win_rate*100:.1f}%)")
        print(f"\n💪 Performance Metrics:")
        print(f"   Profit Factor: {profit_factor:.2f}")
        print(f"   Sharpe Ratio: {sharpe:.2f}")
        print(f"   Max Drawdown: {max_drawdown*100:.2f}%")
        print(f"   Avg Duration: {avg_duration:.1f}h")
        print(f"\n💸 Costs:")
        print(f"   Total Commissions: ${total_commission:.2f}")
        
        print(f"\n📋 Per-Symbol:")
        symbol_stats = df_trades.groupby('symbol').agg({'net_pnl': ['sum', 'count', 'mean']}).round(2)
        symbol_stats.columns = ['Total PnL', 'Trades', 'Avg PnL']
        symbol_stats = symbol_stats.sort_values('Total PnL', ascending=False)
        print(symbol_stats.to_string())
        
        csv_filename = f"/Users/laurazapata/Desktop/BACKTEST_1POS_MARZO2025.csv"
        df_trades.to_csv(csv_filename, index=False)
        print(f"\n💾 Trade log: {csv_filename}\n{'='*80}\n")

def main():
    start_date = datetime(2025, 3, 1, 0, 0, 0)
    end_date = datetime(2025, 3, 31, 23, 59, 59)
    
    print("\n🚀 Backtest: 1 POSICIÓN - MARZO 2025\n")
    
    loader = DataLoader()
    print("📡 Downloading data...")
    
    data_map = {}
    for symbol in SUPER_OPTIMIZED_SYMBOLS:
        try:
            df = loader.fetch_data_range(symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), Config.TIMEFRAME)
            if df is not None and len(df) > 0:
                data_map[symbol] = df
                print(f"   ✅ {symbol}: {len(df)} candles")
        except Exception as e:
            print(f"   ❌ {symbol}: {e}")
    
    if not data_map:
        print("\n❌ No data.")
        return
    
    print(f"\n✅ Data loaded: {len(data_map)} symbols\n")
    
    backtester = SinglePositionBacktester(initial_balance=10000)
    backtester.run_backtest(data_map, start_date, end_date)
    print("\n✅ Done!")

if __name__ == "__main__":
    main()
