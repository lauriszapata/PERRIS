"""
Backtest "Sniper" Strategy - WINNER 3X
Objetivo: Replicar la configuración ganadora (+730 USD/año) con 3x Leverage.
Estrategia:
1. TP: 100% al +1.5% (Fijo).
2. SL: 100% al -3.0% (Fijo).
3. Breakeven: Al +1.0%.
4. Leverage: 3x (Exposure $150 * 3 = $450 Total).
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os
import calendar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import Config
from modules.backtest.data_loader import DataLoader
from modules.indicators import Indicators

# CONFIGURATION
BACKTEST_CONFIG = {
    'TRADING_START_HOUR': 0, 'TRADING_END_HOUR': 23, 'TRADING_END_MINUTE': 59,
    'FIXED_EXPOSURE_USD': 150, # Margin
    'LEVERAGE': 3,             # 3x Leverage -> $450 Position
    # SNIPER PARAMS
    'TP_PCT': 0.015,       # 1.5% Target
    'SL_PCT': 0.030,       # 3.0% Stop
    'BREAKEVEN_PCT': 0.010,# 1.0% Trigger
    # Extreme Criteria
    'ADX_MIN': 25, 
    'VOLUME_MIN_MULTIPLIER': 1.3, 
    'VOLATILITY_MAX': 0.025,
}

# Top 50 Liquid Symbols (Minus Blacklist)
TOP_50_CANDIDATES = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "TRX/USDT", "DOT/USDT",
    "LINK/USDT", "POL/USDT", "LTC/USDT", "SHIB/USDT", "UNI/USDT", "BCH/USDT", "XLM/USDT", "NEAR/USDT", "ATOM/USDT", "XMR/USDT",
    "ETC/USDT", "FIL/USDT", "HBAR/USDT", "ARB/USDT", "OP/USDT", "APT/USDT", "RENDER/USDT", "INJ/USDT", "STX/USDT", "SUI/USDT",
    "IMX/USDT", "LDO/USDT", "GRT/USDT", "VET/USDT", "MKR/USDT", "AAVE/USDT", "SNX/USDT", "ALGO/USDT", "SAND/USDT", "MANA/USDT",
    "EOS/USDT", "THETA/USDT", "AXS/USDT", "FTM/USDT", "FLOW/USDT", "QNT/USDT", "CRV/USDT", "RUNE/USDT", "EGLD/USDT", "CHZ/USDT",
    "TIA/USDT", "PEPE/USDT", "WLD/USDT", "FET/USDT", "SEI/USDT"
]
# Blacklist from the winning run
SYMBOL_BLACKLIST = ["POL/USDT", "NEAR/USDT", "APT/USDT", "TRX/USDT", "LINK/USDT", "TIA/USDT", "BNB/USDT", "BCH/USDT", "OP/USDT", "DOT/USDT"]
SYMBOLS = [s for s in TOP_50_CANDIDATES if s not in SYMBOL_BLACKLIST][:50]

class EntrySignalsExtreme:
    @staticmethod
    def check_signals(df, direction):
        results = {}
        try:
            last = df.iloc[-1]
            from modules.managers.trend_manager import TrendManager
            results['Trend'] = {'status': TrendManager.check_trend(df, direction)}
            results['ADX'] = {'status': last['ADX'] >= BACKTEST_CONFIG['ADX_MIN']}
            results['RSI'] = {'status': last['RSI'] > 35 if direction == "LONG" else 30 < last['RSI'] < 55}
            results['MACD'] = {'status': last['MACD_line'] > last['MACD_signal'] if direction == "LONG" else last['MACD_line'] < last['MACD_signal']}
            results['Volume'] = {'status': last['volume'] >= BACKTEST_CONFIG['VOLUME_MIN_MULTIPLIER'] * last['Vol_SMA20']}
            results['Volatility'] = {'status': (last['ATR']/last['close']) < BACKTEST_CONFIG['VOLATILITY_MAX']}
            results['MTF_Trend'] = {'status': True, 'optional': True}
            results['Structure'] = {'status': True, 'optional': True}
            standard_entry = all(r['status'] for k, r in results.items() if not r.get('optional', False))
            if not standard_entry:
                # Fast Fallback
                fast_trend_ok = (last['EMA8'] > last['EMA20']) if direction == "LONG" else (last['EMA8'] < last['EMA20'])
                if fast_trend_ok and results['MACD']['status'] and results['RSI']['status'] and results['Volume']['status'] and results['Volatility']['status']:
                    return True, results
            return standard_entry, results
        except: return False, {}

class SniperBacktester:
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
        self.fixed_exposure_usd = BACKTEST_CONFIG['FIXED_EXPOSURE_USD']
        self.leverage = BACKTEST_CONFIG['LEVERAGE']
    
    def run_backtest(self, data_map, start_date, end_date):
        prepared_data = {}
        for symbol, df in data_map.items():
            df = df.copy()
            df = Indicators.calculate_all(df)
            df = df[(df['timestamp'] >= start_date) & (df['timestamp'] <= end_date)]
            if len(df) > 50: prepared_data[symbol] = df
        
        if not prepared_data: return
        
        all_timestamps = set()
        for df in prepared_data.values(): all_timestamps.update(df['timestamp'].tolist())
        timeline = sorted(all_timestamps)
        
        for current_time in timeline:
            current_prices = {}
            for symbol, df in prepared_data.items():
                df_slice = df[df['timestamp'] <= current_time]
                if len(df_slice) > 0: current_prices[symbol] = df_slice.iloc[-1]
            
            self._monitor_positions(current_time, current_prices, prepared_data)
            
            if len(self.open_positions) < self.max_open_symbols:
                self._look_for_entries(current_time, current_prices, prepared_data)
        
        if self.open_positions:
            for symbol in list(self.open_positions.keys()):
                if symbol in current_prices:
                    self._close_position(symbol, current_prices[symbol]['close'], current_time, "END")
    
    def _monitor_positions(self, current_time, current_prices, data_map):
        for symbol in list(self.open_positions.keys()):
            if symbol not in current_prices: continue
            pos = self.open_positions[symbol]
            r = current_prices[symbol]
            
            # SL Check
            if pos['direction'] == 'LONG' and r['low'] <= pos['sl']:
                self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                continue
            elif pos['direction'] == 'SHORT' and r['high'] >= pos['sl']:
                self._close_position(symbol, pos['sl'], current_time, "STOP_LOSS")
                continue
            
            # TP Check (Fixed 1.5%)
            price = r['high'] if pos['direction'] == 'LONG' else r['low']
            pnl_pct = (price - pos['entry_price']) / pos['entry_price'] if pos['direction'] == 'LONG' else (pos['entry_price'] - price) / pos['entry_price']
            
            if pnl_pct >= BACKTEST_CONFIG['TP_PCT']:
                # TP HIT -> Close ALL
                self._close_position(symbol, price, current_time, "TAKE_PROFIT")
                continue
            
            # Breakeven
            current_pnl_pct = (r['close'] - pos['entry_price']) / pos['entry_price'] if pos['direction'] == 'LONG' else (pos['entry_price'] - r['close']) / pos['entry_price']
            
            if not pos.get('breakeven_triggered', False) and current_pnl_pct >= BACKTEST_CONFIG['BREAKEVEN_PCT']:
                pos['sl'] = max(pos['sl'], pos['entry_price'] * 1.001) if pos['direction'] == 'LONG' else min(pos['sl'], pos['entry_price'] * 0.999)
                pos['breakeven_triggered'] = True

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
            lok, _ = EntrySignalsExtreme.check_signals(dfs, "LONG")
            if lok: cands.append({'symbol': symbol, 'direction': 'LONG', 'row': cr, 'score': cr['ADX']})
            sok, _ = EntrySignalsExtreme.check_signals(dfs, "SHORT")
            if sok: cands.append({'symbol': symbol, 'direction': 'SHORT', 'row': cr, 'score': cr['ADX']})
        
        if cands:
            cands.sort(key=lambda x: x['score'], reverse=True)
            self._open_position(cands[0]['symbol'], cands[0]['direction'], cands[0]['row'], ct)

    def _open_position(self, symbol, direction, row, entry_time):
        ep = row['close']
        sl = ep * (1 - BACKTEST_CONFIG['SL_PCT']) if direction == 'LONG' else ep * (1 + BACKTEST_CONFIG['SL_PCT'])
        # Size = Margin * Leverage / Price
        size = (self.fixed_exposure_usd * self.leverage) / ep
        self.open_positions[symbol] = {'symbol': symbol, 'direction': direction, 'entry_price': ep, 'entry_time': entry_time, 'initial_size': size, 'current_size': size, 'sl': sl, 'breakeven_triggered': False}

def main():
    print(f"\n{'='*80}\n🔬 BACKTEST SNIPER - WINNER 3X (Jan - Nov 2025)\n{'='*80}\n")
    loader = DataLoader()
    
    # Download data for the whole year once
    print("📡 Downloading data for 2025...")
    data_map = {}
    for symbol in SYMBOLS:
        try:
            df = loader.fetch_data_range(symbol, "2025-01-01", "2025-11-25", Config.TIMEFRAME)
            if df is not None and len(df) > 0: data_map[symbol] = df
        except: pass
    
    if not data_map: return print("❌ No data.")
    
    print(f"📊 Data loaded for {len(data_map)} symbols.")
    
    total_pnl = 0
    monthly_results = []
    
    # Loop through months
    for month in range(1, 12):
        start_date = datetime(2025, month, 1)
        # Calculate end date (last day of month)
        last_day = calendar.monthrange(2025, month)[1]
        end_date = datetime(2025, month, last_day, 23, 59, 59)
        
        # Limit November to current date
        if month == 11:
            end_date = datetime(2025, 11, 25, 23, 59, 59)
            
        print(f"\n🗓️  Running {start_date.strftime('%B %Y')}...")
        
        backtester = SniperBacktester(initial_balance=10000)
        backtester.run_backtest(data_map, start_date, end_date)
        
        if not backtester.closed_trades:
            print("   No trades.")
            monthly_results.append({'Month': start_date.strftime('%B'), 'PnL': 0, 'Trades': 0, 'WinRate': 0, 'PF': 0})
            continue
            
        df = pd.DataFrame(backtester.closed_trades)
        pnl = df['net_pnl'].sum()
        trades = len(df)
        wins = len(df[df['net_pnl'] > 0])
        wr = (wins / trades * 100) if trades > 0 else 0
        gp = df[df['net_pnl'] > 0]['net_pnl'].sum()
        gl = abs(df[df['net_pnl'] <= 0]['net_pnl'].sum())
        pf = gp / gl if gl > 0 else 0
        
        print(f"   PnL: ${pnl:,.2f} | Trades: {trades} | WR: {wr:.1f}% | PF: {pf:.2f}")
        monthly_results.append({'Month': start_date.strftime('%B'), 'PnL': pnl, 'Trades': trades, 'WinRate': wr, 'PF': pf})
        total_pnl += pnl

    print(f"\n{'='*80}\n📊 SUMMARY 2025\n{'='*80}\n")
    print(f"💰 Total Year PnL: ${total_pnl:,.2f}")
    
    print("\n📅 Monthly Breakdown:")
    print(f"{'Month':<15} {'PnL':<15} {'Trades':<10} {'Win Rate':<10} {'PF':<10}")
    print("-" * 60)
    for r in monthly_results:
        print(f"{r['Month']:<15} ${r['PnL']:<15.2f} {r['Trades']:<10} {r['WinRate']:<10.1f}% {r['PF']:<10.2f}")
        
    # Save full report
    pd.DataFrame(monthly_results).to_csv("/Users/laurazapata/Desktop/BACKTEST_WINNER_3X.csv", index=False)
    print(f"\n💾 /Users/laurazapata/Desktop/BACKTEST_WINNER_3X.csv\n")

if __name__ == "__main__":
    main()
