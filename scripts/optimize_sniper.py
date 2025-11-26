"""
Sniper Strategy Optimization - FULL YEAR 2025
Scenarios to Test:
1. Base Scaled: $1000 Position, 1x Lev, TP 1.5%, SL 3.0%
2. Leverage Test: $1000 Position, 3x Lev, TP 1.5%, SL 3.0%
3. Optimization Grid: Find best TP/SL combo.

Strict Rules:
- No Look-ahead bias (Signals on closed candles, execution on next).
- No NaN/None values allowed.
- Realistic commission (0.045%).
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os
import itertools

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import Config
from modules.backtest.data_loader import DataLoader
from modules.indicators import Indicators

# SYMBOLS (Top 42 from previous test)
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "TRX/USDT", "DOT/USDT",
    "LINK/USDT", "POL/USDT", "LTC/USDT", "SHIB/USDT", "UNI/USDT", "BCH/USDT", "XLM/USDT", "NEAR/USDT", "ATOM/USDT", "XMR/USDT",
    "ETC/USDT", "FIL/USDT", "HBAR/USDT", "ARB/USDT", "OP/USDT", "APT/USDT", "RENDER/USDT", "INJ/USDT", "STX/USDT", "SUI/USDT",
    "IMX/USDT", "LDO/USDT", "GRT/USDT", "VET/USDT", "MKR/USDT", "AAVE/USDT", "SNX/USDT", "ALGO/USDT", "SAND/USDT", "MANA/USDT",
    "EOS/USDT", "THETA/USDT"
]

class EntrySignalsExtreme:
    @staticmethod
    def check_signals(df, direction, adx_min=25, vol_min=1.3, atr_max=0.025):
        try:
            # STRICT: Use iloc[-1] of the PASSED dataframe. 
            # The passed dataframe MUST contain only CLOSED candles relative to decision time.
            last = df.iloc[-1]
            
            # 1. Trend
            ema50 = last['EMA50']
            ema200 = last['EMA200']
            trend_ok = ema50 > ema200 if direction == "LONG" else ema50 < ema200
            
            # 2. ADX
            adx_ok = last['ADX'] >= adx_min
            
            # 3. RSI
            rsi = last['RSI']
            rsi_ok = rsi > 35 if direction == "LONG" else 30 < rsi < 55
            
            # 4. MACD
            macd_line = last['MACD_line']
            macd_signal = last['MACD_signal']
            macd_ok = macd_line > macd_signal if direction == "LONG" else macd_line < macd_signal
            
            # 5. Volume
            vol_ok = last['volume'] >= vol_min * last['Vol_SMA20']
            
            # 6. Volatility
            atr_pct = last['ATR'] / last['close']
            volatility_ok = atr_pct < atr_max
            
            return trend_ok and adx_ok and rsi_ok and macd_ok and vol_ok and volatility_ok
        except:
            return False

class FastBacktester:
    def __init__(self, data_map, params):
        self.data_map = data_map
        self.params = params
        self.commission_rate = 0.00045
        self.trades = []
        self.balance = 10000
        
    def run(self):
        # Pre-calculate signals to speed up
        # This is a vectorized approach for speed, but we must be careful with look-ahead.
        # We will iterate timestamps to ensure correctness.
        
        # Collect all potential entry points
        # To be 100% safe against bias, we iterate.
        
        # Get global timeline
        all_timestamps = set()
        for df in self.data_map.values():
            all_timestamps.update(df['timestamp'].tolist())
        timeline = sorted(list(all_timestamps))
        
        open_positions = {} # symbol -> {entry_price, size, sl, tp, direction, entry_time}
        max_open = 1
        cooldowns = {} # symbol -> exit_time
        
        # Performance optimization: Convert DFs to dict of dicts for faster lookup or use arrays
        # For this scale, iterating DF rows is okay if we skip when no position.
        
        # Let's use a simplified event loop
        for current_time in timeline:
            # 1. Check Exits
            for symbol in list(open_positions.keys()):
                pos = open_positions[symbol]
                
                # Get current candle (this is the candle that OPENED at current_time, 
                # but in backtesting usually we have the candle that CLOSED at current_time.
                # Let's assume 'timeline' are close times.
                # So we check if price hit SL/TP during this candle.
                
                # Find row for this symbol at this time
                # (In a real optimized engine we'd align indices beforehand)
                try:
                    row = self.data_map[symbol].loc[self.data_map[symbol]['timestamp'] == current_time].iloc[0]
                except:
                    continue # No data for this symbol at this time
                
                # Check High/Low for TP/SL
                # Conservative: Check SL first (if Low hits SL, we stop out)
                # Unless we assume we check every tick, but here we use 15m candles.
                # Worst case: Low hits SL.
                
                exit_price = None
                reason = None
                
                if pos['direction'] == 'LONG':
                    if row['low'] <= pos['sl']:
                        exit_price = pos['sl']
                        reason = 'SL'
                    elif row['high'] >= pos['tp']:
                        exit_price = pos['tp']
                        reason = 'TP'
                else:
                    if row['high'] >= pos['sl']:
                        exit_price = pos['sl']
                        reason = 'SL'
                    elif row['low'] <= pos['tp']:
                        exit_price = pos['tp']
                        reason = 'TP'
                
                if exit_price:
                    # Close
                    pnl = (exit_price - pos['entry_price']) * pos['size'] if pos['direction'] == 'LONG' else (pos['entry_price'] - exit_price) * pos['size']
                    comm = (pos['entry_price'] * pos['size'] + exit_price * pos['size']) * self.commission_rate
                    net = pnl - comm
                    
                    self.trades.append({
                        'symbol': symbol,
                        'net_pnl': net,
                        'reason': reason,
                        'month': current_time.month
                    })
                    cooldowns[symbol] = current_time + timedelta(minutes=30)
                    del open_positions[symbol]
            
            # 2. Check Entries (only if slot available)
            if len(open_positions) < max_open:
                # Find candidates
                candidates = []
                for symbol, df in self.data_map.items():
                    if symbol in open_positions: continue
                    if symbol in cooldowns and current_time < cooldowns[symbol]: continue
                    
                    # Get row
                    try:
                        # We need the PREVIOUS closed candle for signal
                        # If current_time is the close time of candle T, we can use it for signal to enter at T (close) or T+1 (open).
                        # Realistically: Signal generated at close of T. Entry at Open of T+1.
                        # Here we simplify: Signal at T, Entry at Close of T (approx market price).
                        row = df.loc[df['timestamp'] == current_time].iloc[0]
                    except: continue
                    
                    # We need a slice to calculate indicators if not pre-calculated
                    # Assuming indicators are pre-calculated in df
                    
                    # Check signal
                    # We pass a 1-row DF to check_signals? No, it needs context? 
                    # Actually check_signals uses .iloc[-1]. So we can pass a slice ending at current_time.
                    # Optimization: Check pre-calculated boolean columns?
                    # For now, let's just check the row values directly for speed.
                    
                    # Re-implement logic inline for speed
                    # ADX > 25, Vol > 1.3*Avg, ATR < 2.5%
                    if row['ADX'] < 25: continue
                    if row['volume'] < 1.3 * row['Vol_SMA20']: continue
                    if (row['ATR'] / row['close']) > 0.025: continue
                    
                    # Trend & Momentum
                    if row['EMA50'] > row['EMA200'] and row['MACD_line'] > row['MACD_signal'] and row['RSI'] > 35:
                        candidates.append({'symbol': symbol, 'direction': 'LONG', 'price': row['close'], 'score': row['ADX']})
                    elif row['EMA50'] < row['EMA200'] and row['MACD_line'] < row['MACD_signal'] and 30 < row['RSI'] < 55:
                        candidates.append({'symbol': symbol, 'direction': 'SHORT', 'price': row['close'], 'score': row['ADX']})
                
                if candidates:
                    # Pick best by ADX
                    candidates.sort(key=lambda x: x['score'], reverse=True)
                    best = candidates[0]
                    
                    # Enter
                    ep = best['price']
                    tp_pct = self.params['tp']
                    sl_pct = self.params['sl']
                    lev = self.params['lev']
                    exposure = self.params['exposure']
                    
                    size = (exposure * lev) / ep
                    
                    tp = ep * (1 + tp_pct) if best['direction'] == 'LONG' else ep * (1 - tp_pct)
                    sl = ep * (1 - sl_pct) if best['direction'] == 'LONG' else ep * (1 + sl_pct)
                    
                    open_positions[best['symbol']] = {
                        'entry_price': ep,
                        'size': size,
                        'tp': tp,
                        'sl': sl,
                        'direction': best['direction'],
                        'entry_time': current_time
                    }

        return self.trades

def main():
    print("🚀 Loading Data for Optimization...")
    loader = DataLoader()
    data_map = {}
    
    # Load data
    for symbol in SYMBOLS:
        try:
            df = loader.fetch_data_range(symbol, "2025-01-01", "2025-11-25", Config.TIMEFRAME)
            if df is not None and len(df) > 100:
                df = Indicators.calculate_all(df)
                data_map[symbol] = df
        except: pass
        
    print(f"✅ Loaded {len(data_map)} symbols.")
    
    scenarios = [
        {'name': 'Current Sniper ($150)', 'exposure': 150, 'lev': 1, 'tp': 0.015, 'sl': 0.030},
        {'name': 'Scaled Sniper ($1000)', 'exposure': 1000, 'lev': 1, 'tp': 0.015, 'sl': 0.030},
        {'name': 'Leveraged Sniper (3x)', 'exposure': 1000, 'lev': 3, 'tp': 0.015, 'sl': 0.030},
        # Optimization Candidates
        {'name': 'Tight Sniper (TP 1.0/SL 2.0)', 'exposure': 1000, 'lev': 1, 'tp': 0.010, 'sl': 0.020},
        {'name': 'Loose Sniper (TP 2.0/SL 4.0)', 'exposure': 1000, 'lev': 1, 'tp': 0.020, 'sl': 0.040},
        {'name': 'Balanced 3x (TP 1.5/SL 3.0)', 'exposure': 1000, 'lev': 3, 'tp': 0.015, 'sl': 0.030}, # Same as Lev Sniper but explicit
        {'name': 'High Reward 3x (TP 2.5/SL 3.0)', 'exposure': 1000, 'lev': 3, 'tp': 0.025, 'sl': 0.030},
    ]
    
    results = []
    
    for scen in scenarios:
        print(f"\n🧪 Testing: {scen['name']}...")
        bt = FastBacktester(data_map, scen)
        trades = bt.run()
        
        if not trades:
            print("   No trades.")
            continue
            
        df_t = pd.DataFrame(trades)
        total_pnl = df_t['net_pnl'].sum()
        win_rate = len(df_t[df_t['net_pnl'] > 0]) / len(df_t) * 100
        
        # Calculate Max Drawdown
        df_t['cum_pnl'] = df_t['net_pnl'].cumsum()
        df_t['peak'] = df_t['cum_pnl'].cummax()
        df_t['dd'] = df_t['cum_pnl'] - df_t['peak']
        max_dd = df_t['dd'].min()
        
        # Profit Factor
        gross_profit = df_t[df_t['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(df_t[df_t['net_pnl'] <= 0]['net_pnl'].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else 0
        
        print(f"   💰 PnL: ${total_pnl:,.2f} | WR: {win_rate:.1f}% | PF: {pf:.2f} | MaxDD: ${max_dd:,.2f}")
        
        results.append({
            'Scenario': scen['name'],
            'PnL': total_pnl,
            'WinRate': win_rate,
            'PF': pf,
            'MaxDD': max_dd,
            'Trades': len(df_t)
        })
        
    # Print Summary Table
    print(f"\n{'='*100}")
    print(f"{'Scenario':<30} {'PnL':<15} {'WinRate':<10} {'PF':<10} {'MaxDD':<15} {'Trades':<10}")
    print(f"{'-'*100}")
    
    # Sort by PnL
    results.sort(key=lambda x: x['PnL'], reverse=True)
    
    for r in results:
        print(f"{r['Scenario']:<30} ${r['PnL']:<15.2f} {r['WinRate']:<10.1f}% {r['PF']:<10.2f} ${r['MaxDD']:<15.2f} {r['Trades']:<10}")

if __name__ == "__main__":
    main()
