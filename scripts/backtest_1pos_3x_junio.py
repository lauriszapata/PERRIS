"""Backtest 1 Posición LEVERAGE 3X - Junio 2025"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import Config
from modules.backtest.data_loader import DataLoader
from modules.indicators import Indicators

SUPER_OPTIMIZED_CONFIG = {
    'TRADING_START_HOUR': 5, 'TRADING_END_HOUR': 11, 'TRADING_END_MINUTE': 50,
    'SL_ATR_MULTIPLIER': 4.0, 'TRAILING_SL_ATR_MULTIPLIER': 2.0, 'FIXED_EXPOSURE_USD': 150,
    'LEVERAGE': 3,  # 3X LEVERAGE
    'TP_LEVELS': [{"pct": 0.020, "close_pct": 0.30, "name": "P1"}, {"pct": 0.035, "close_pct": 0.30, "name": "P2"}],
    'DYNAMIC_SCALPING_START': 0.050, 'DYNAMIC_SCALPING_INCREMENT': 0.010, 'DYNAMIC_SCALPING_CLOSE_PCT': 0.10,
    'ADX_MIN': 25, 'VOLUME_MIN_MULTIPLIER': 1.3, 'VOLATILITY_MAX': 0.025,
}

SYMBOL_BLACKLIST_EXPANDED = ["POL/USDT", "NEAR/USDT", "APT/USDT", "TRX/USDT", "LINK/USDT", "TIA/USDT", "BNB/USDT", "BCH/USDT", "OP/USDT", "DOT/USDT"]
SUPER_OPTIMIZED_SYMBOLS = [s for s in Config.SYMBOLS if s not in SYMBOL_BLACKLIST_EXPANDED]

class ATRManagerSuperOptimized:
    @staticmethod
    def calculate_initial_stop(entry_price, atr_entry, direction):
        multiplier = SUPER_OPTIMIZED_CONFIG['SL_ATR_MULTIPLIER']
        if direction == "LONG":
            sl = entry_price - (multiplier * atr_entry)
            dist_pct = (entry_price - sl) / entry_price
            if dist_pct < 0.005: sl = entry_price * (1 - 0.005)
            elif dist_pct > 0.20: sl = entry_price * (1 - 0.20)
            return sl
        else:
            sl = entry_price + (multiplier * atr_entry)
            dist_pct = (sl - entry_price) / entry_price
            if dist_pct < 0.005: sl = entry_price * (1 + 0.005)
            elif dist_pct > 0.20: sl = entry_price * (1 + 0.20)
            return sl
    
    @staticmethod
    def calculate_trailing_stop(current_sl, extreme_price, current_atr, direction, entry_price):
        multiplier = SUPER_OPTIMIZED_CONFIG['TRAILING_SL_ATR_MULTIPLIER']
        if direction == "LONG":
            return max(current_sl, extreme_price - (multiplier * current_atr))
        else:
            return min(current_sl, extreme_price + (multiplier * current_atr))

class EntrySignalsSuperOptimized:
    @staticmethod
    def check_signals(df, direction):
        results = {}
        try:
            last = df.iloc[-1]
            from modules.managers.trend_manager import TrendManager
            results['Trend'] = {'status': TrendManager.check_trend(df, direction)}
            results['ADX'] = {'status': last['ADX'] >= SUPER_OPTIMIZED_CONFIG['ADX_MIN']}
            results['RSI'] = {'status': last['RSI'] > 35 if direction == "LONG" else 30 < last['RSI'] < 55}
            results['MACD'] = {'status': last['MACD_line'] > last['MACD_signal'] if direction == "LONG" else last['MACD_line'] < last['MACD_signal']}
            results['Volume'] = {'status': last['volume'] >= SUPER_OPTIMIZED_CONFIG['VOLUME_MIN_MULTIPLIER'] * last['Vol_SMA20']}
            results['Volatility'] = {'status': (last['ATR'] / last['close']) < SUPER_OPTIMIZED_CONFIG['VOLATILITY_MAX']}
            results['MTF_Trend'] = {'status': True, 'optional': True}
            results['Structure'] = {'status': True, 'optional': True}
            
            standard_entry = all(r['status'] for k, r in results.items() if not r.get('optional', False))
            
            if not standard_entry:
                fast_trend_ok = (last['EMA8'] > last['EMA20']) if direction == "LONG" else (last['EMA8'] < last['EMA20'])
                if fast_trend_ok and results['MACD']['status'] and results['RSI']['status'] and results['Volume']['status'] and results['Volatility']['status']:
                    return True, results
            return standard_entry, results
        except: return False, {}

class SinglePositionBacktester3x:
    def __init__(self, initial_balance=10000):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.commission_rate = Config.COMMISSION_RATE
        self.open_positions = {}
        self.closed_trades = []
        self.equity_curve = []
        self.symbol_cooldowns = {}
        self.max_open_symbols = 1
        self.cooldown_minutes = Config.SYMBOL_COOLDOWN_MINUTES
        self.fixed_exposure_usd = SUPER_OPTIMIZED_CONFIG['FIXED_EXPOSURE_USD']
        self.leverage = SUPER_OPTIMIZED_CONFIG['LEVERAGE']  # 3X
    
    def is_trading_hours(self, ts):
        h, m = ts.hour, ts.minute
        if h < SUPER_OPTIMIZED_CONFIG['TRADING_START_HOUR']: return False
        if h > SUPER_OPTIMIZED_CONFIG['TRADING_END_HOUR']: return False
        if h == SUPER_OPTIMIZED_CONFIG['TRADING_END_HOUR'] and m >= SUPER_OPTIMIZED_CONFIG['TRADING_END_MINUTE']: return False
        return True
    
    def run_backtest(self, data_map, start_date, end_date):
        print(f"\n{'='*80}\n🔬 1 POSICIÓN - LEVERAGE 3X - JUNIO 2025\n{'='*80}\n")
        
        prepared_data = {}
        for symbol, df in data_map.items():
            df = df.copy()
            df = Indicators.calculate_all(df)
            df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]
            if len(df) > 50: prepared_data[symbol] = df
        
        if not prepared_data: return print("❌ No data.")
        
        all_timestamps = set()
        for df in prepared_data.values(): all_timestamps.update(df['timestamp'].tolist())
        timeline = sorted(all_timestamps)
        
        print(f"📊 Data: {len(prepared_data)} symbols, {len(timeline)} candles\n")
        
        for current_time in timeline:
            current_prices = {}
            for symbol, df in prepared_data.items():
                df_slice = df[df['timestamp'] <= current_time]
                if len(df_slice) > 0: current_prices[symbol] = df_slice.iloc[-1]
            
            self._record_equity(current_time, current_prices)
            self._monitor_positions(current_time, current_prices, prepared_data)
            
            if self.is_trading_hours(current_time) and len(self.open_positions) < self.max_open_symbols:
                self._look_for_entries(current_time, current_prices, prepared_data)
        
        if self.open_positions:
            for symbol in list(self.open_positions.keys()):
                if symbol in current_prices:
                    self._close_position(symbol, current_prices[symbol]['close'], current_time, "END")
        
        return self._generate_report()
    
    def _monitor_positions(self, current_time, current_prices, data_map):
        for symbol in list(self.open_positions.keys()):
            if symbol not in current_prices: continue
            pos = self.open_positions[symbol]
            r = current_prices[symbol]
            
            if pos['direction'] == 'LONG' and r['low'] <= pos['sl']:
                self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                continue
            elif pos['direction'] == 'SHORT' and r['high'] >= pos['sl']:
                self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                continue
            
            self._check_tp(symbol, pos, r['close'], r['high'], r['low'], current_time)
            if symbol not in self.open_positions: continue
            
            pnl_pct = (r['close'] - pos['entry_price']) / pos['entry_price'] if pos['direction'] == 'LONG' else (pos['entry_price'] - r['close']) / pos['entry_price']
            
            if not pos.get('breakeven_triggered', False) and pnl_pct >= Config.BREAKEVEN_TRIGGER_PCT:
                pos['sl'] = max(pos['sl'], pos['entry_price'] * 1.001) if pos['direction'] == 'LONG' else min(pos['sl'], pos['entry_price'] * 0.999)
                pos['breakeven_triggered'] = True
            
            if pos['direction'] == 'LONG' and r['high'] > pos['highest_price']:
                pos['highest_price'] = r['high']
                pos['sl'] = max(pos['sl'], ATRManagerSuperOptimized.calculate_trailing_stop(pos['sl'], pos['highest_price'], r['ATR'], 'LONG', pos['entry_price']))
            elif pos['direction'] == 'SHORT' and r['low'] < pos['lowest_price']:
                pos['lowest_price'] = r['low']
                pos['sl'] = min(pos['sl'], ATRManagerSuperOptimized.calculate_trailing_stop(pos['sl'], pos['lowest_price'], r['ATR'], 'SHORT', pos['entry_price']))
    
    def _check_tp(self, symbol, pos, cp, ch, cl, ct):
        price = ch if pos['direction'] == 'LONG' else cl
        pnl_pct = (price - pos['entry_price']) / pos['entry_price'] if pos['direction'] == 'LONG' else (pos['entry_price'] - price) / pos['entry_price']
        
        for level in SUPER_OPTIMIZED_CONFIG['TP_LEVELS']:
            if level['name'] not in pos['tp_triggered'] and pnl_pct >= level['pct']:
                self._close_partial(symbol, pos, level['close_pct'], price, ct, level['name'])
                pos['tp_triggered'].add(level['name'])
        
        if pnl_pct >= SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_START']:
            n_levels = int((pnl_pct - SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_START']) / SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_INCREMENT'])
            for n in range(n_levels + 1):
                lpct = SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_START'] + (n * SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_INCREMENT'])
                lkey = f"D{n+1}"
                if lkey not in pos['tp_triggered'] and pnl_pct >= lpct:
                    self._close_partial(symbol, pos, SUPER_OPTIMIZED_CONFIG['DYNAMIC_SCALPING_CLOSE_PCT'], price, ct, lkey)
                    pos['tp_triggered'].add(lkey)
    
    def _close_partial(self, symbol, pos, close_pct, exit_price, exit_time, reason):
        size = pos['current_size'] * close_pct
        if size < 0.01: return
        pnl = (exit_price - pos['entry_price']) * size if pos['direction'] == 'LONG' else (pos['entry_price'] - exit_price) * size
        comm = (pos['entry_price'] * size + exit_price * size) * self.commission_rate
        net = pnl - comm
        pos['current_size'] -= size
        self.closed_trades.append({'symbol': symbol, 'direction': pos['direction'], 'entry_time': pos['entry_time'], 'exit_time': exit_time, 'entry_price': pos['entry_price'], 'exit_price': exit_price, 'size': size, 'pnl': pnl, 'commission': comm, 'net_pnl': net, 'exit_reason': f"TP_{reason}", 'partial': True})
        self.balance += net
        if pos['current_size'] < 0.01: self._close_position(symbol, exit_price, exit_time, f"TP_{reason}_FINAL")
    
    def _close_position(self, symbol, exit_price, exit_time, reason):
        if symbol not in self.open_positions: return
        pos = self.open_positions[symbol]
        pnl = (exit_price - pos['entry_price']) * pos['current_size'] if pos['direction'] == 'LONG' else (pos['entry_price'] - exit_price) * pos['current_size']
        comm = (pos['entry_price'] * pos['current_size'] + exit_price * pos['current_size']) * self.commission_rate
        net = pnl - comm
        self.closed_trades.append({'symbol': symbol, 'direction': pos['direction'], 'entry_time': pos['entry_time'], 'exit_time': exit_time, 'entry_price': pos['entry_price'], 'exit_price': exit_price, 'size': pos['current_size'], 'pnl': pnl, 'commission': comm, 'net_pnl': net, 'exit_reason': reason, 'partial': False})
        self.balance += net
        self.symbol_cooldowns[symbol] = exit_time
        del self.open_positions[symbol]
    
    def _look_for_entries(self, ct, cps, dm):
        cands = []
        for symbol, df in dm.items():
            if symbol in self.open_positions: continue
            if symbol in self.symbol_cooldowns and ct < self.symbol_cooldowns[symbol] + timedelta(minutes=self.cooldown_minutes): continue
            dfs = df[df['timestamp'] <= ct].copy()
            if len(dfs) < 50: continue
            cr = dfs.iloc[-1]
            lok, _ = EntrySignalsSuperOptimized.check_signals(dfs, "LONG")
            if lok: cands.append({'symbol': symbol, 'direction': 'LONG', 'row': cr, 'score': cr['ADX']})
            sok, _ = EntrySignalsSuperOptimized.check_signals(dfs, "SHORT")
            if sok: cands.append({'symbol': symbol, 'direction': 'SHORT', 'row': cr, 'score': cr['ADX']})
        
        if cands:
            cands.sort(key=lambda x: x['score'], reverse=True)
            self._open_position(cands[0]['symbol'], cands[0]['direction'], cands[0]['row'], ct)
    
    def _open_position(self, symbol, direction, row, entry_time):
        ep, atr = row['close'], row['ATR']
        sl = ATRManagerSuperOptimized.calculate_initial_stop(ep, atr, direction)
        size = (self.fixed_exposure_usd * self.leverage) / ep  # 3X LEVERAGE
        self.open_positions[symbol] = {'symbol': symbol, 'direction': direction, 'entry_price': ep, 'entry_time': entry_time, 'initial_size': size, 'current_size': size, 'sl': sl, 'highest_price': ep if direction == 'LONG' else float('inf'), 'lowest_price': ep if direction == 'SHORT' else float('inf'), 'tp_triggered': set(), 'breakeven_triggered': False}
    
    def _record_equity(self, ct, cps):
        te = self.balance
        for symbol, pos in self.open_positions.items():
            if symbol in cps:
                cp = cps[symbol]['close']
                unr = (cp - pos['entry_price']) * pos['current_size'] if pos['direction'] == 'LONG' else (pos['entry_price'] - cp) * pos['current_size']
                te += unr
        self.equity_curve.append({'timestamp': ct, 'equity': te})
    
    def _generate_report(self):
        print(f"\n{'='*80}\n📊 RESULTADOS JUNIO 2025 (LEVERAGE 3X)\n{'='*80}\n")
        if not self.closed_trades: return print("❌ No trades.")
        
        df = pd.DataFrame(self.closed_trades)
        pnl = df['net_pnl'].sum()
        totalt = len(df)
        wint = len(df[df['net_pnl'] > 0])
        wr = wint / totalt if totalt > 0 else 0
        gp = df[df['net_pnl'] > 0]['net_pnl'].sum()
        gl = abs(df[df['net_pnl'] <= 0]['net_pnl'].sum())
        pf = gp / gl if gl > 0 else float('inf')
        rets = df['net_pnl'] / self.initial_balance
        sh = (np.mean(rets) / np.std(rets)) * np.sqrt(totalt) if np.std(rets) > 0 else 0
        eq = pd.Series([e['equity'] for e in self.equity_curve])
        rm = eq.expanding().max()
        dd = (eq - rm) / rm
        mdd = dd.min()
        df['duration'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600
        
        print(f"💰 Total PnL: ${pnl:,.2f} ({(pnl/self.initial_balance)*100:.2f}%)")
        print(f"💵 Final Balance: ${self.balance:,.2f}")
        print(f"📈 Return: {((self.balance - self.initial_balance) / self.initial_balance) * 100:.2f}%")
        print(f"\n📊 Trade Statistics:")
        print(f"   Total Trades: {totalt}")
        print(f"   Winning: {wint} ({wr*100:.1f}%)")
        print(f"\n💪 Performance Metrics:")
        print(f"   Profit Factor: {pf:.2f}")
        print(f"   Sharpe Ratio: {sh:.2f}")
        print(f"   Max Drawdown: {mdd*100:.2f}%")
        print(f"   Avg Duration: {df['duration'].mean():.1f}h")
        print(f"\n💸 Costs: ${df['commission'].sum():.2f}")
        
        print(f"\n📋 Per-Symbol:")
        ss = df.groupby('symbol').agg({'net_pnl': ['sum', 'count', 'mean']}).round(2)
        ss.columns = ['Total PnL', 'Trades', 'Avg PnL']
        print(ss.sort_values('Total PnL', ascending=False).to_string())
        
        df.to_csv("/Users/laurazapata/Desktop/BACKTEST_1POS_3X_JUNIO2025.csv", index=False)
        print(f"\n💾 /Users/laurazapata/Desktop/BACKTEST_1POS_3X_JUNIO2025.csv\n{'='*80}\n")

start_date = datetime(2025, 6, 1, 0, 0, 0)
end_date = datetime(2025, 6, 30, 23, 59, 59)

print("\n🚀 Backtest: 1 POSICIÓN - LEVERAGE 3X - JUNIO 2025\n")

loader = DataLoader()
print("📡 Downloading data...")

data_map = {}
for symbol in SUPER_OPTIMIZED_SYMBOLS:
    try:
        df = loader.fetch_data_range(symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), Config.TIMEFRAME)
        if df is not None and len(df) > 0:
            data_map[symbol] = df
            print(f"   ✅ {symbol}")
    except Exception as e:
        print(f"   ❌ {symbol}: {e}")

if data_map:
    print(f"\n✅ {len(data_map)} symbols loaded\n")
    backtester = SinglePositionBacktester3x(initial_balance=10000)
    backtester.run_backtest(data_map, start_date, end_date)
else:
    print("\n❌ No data.")
