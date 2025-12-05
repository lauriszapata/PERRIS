import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import os
import sys

# Add root to path
sys.path.append(os.getcwd())

from config import Config
from modules.indicators import Indicators
from modules.entry_signals import EntrySignals
from modules.logger import logger
import logging
logging.getLogger("TradingBot").setLevel(logging.WARNING)

# --- Configuration Overrides for Backtest ---
# User Request: Optimize for Profitability
# - Increase ADX to 30 (Stronger Trend)
# - Widen SL to 0.5% Price Move (Give room to breathe)
# - Keep TP at 1% Price Move (2:1 Reward/Risk)

Config.ADX_MIN = 30 # Stricter Trend Filter

BACKTEST_CONFIG = {
    'LEVERAGE': 3,
    'MARGIN_USD': 100,
    'EXPOSURE_USD': 300,
    'TP_ROI': 0.03, # 3%
    'SL_ROI': 0.015, # 1.5% (at 3x)
    'TP_PRICE_MOVE': 0.01, # 1%
    'SL_PRICE_MOVE': 0.005, # 0.5% (Widened from 0.33%)
    'COMMISSION_RATE': 0.00045, # 0.045%
    'START_HOUR': 7,
    'END_HOUR': 15,
    'MAX_SYMBOLS': 15
}

def load_data():
    """Load data for top 15 symbols from Jan-Nov"""
    data_dir = "data/historical_full"
    data_map = {}
    all_timestamps = set()
    
    # Get top 15 symbols from Config
    symbols = Config.SYMBOLS[:BACKTEST_CONFIG['MAX_SYMBOLS']]
    
    print("Loading data...")
    for symbol in symbols:
        safe_symbol = symbol.replace("/", "")
        filename = f"{data_dir}/{safe_symbol}_15m_JanNov.csv"
        
        if os.path.exists(filename):
            df = pd.read_csv(filename)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            # Calculate Indicators ONCE
            df = Indicators.calculate_all(df)
            
            data_map[symbol] = df
            all_timestamps.update(df.index)
            print(f"Loaded {symbol}: {len(df)} candles")
        else:
            print(f"Warning: Data for {symbol} not found at {filename}")
            
    timeline = sorted(list(all_timestamps))
    return data_map, timeline

def main():
    data_map, timeline = load_data()
    print(f"Running optimization on {len(timeline)} steps...")

    # --- Parameter Sweep Configurations ---
    TEST_CONFIGS = [
        # Previous Best
        {'name': 'Higher Reward', 'TP': 0.015, 'SL': 0.005, 'ADX': 30}, # -$246
        
        # Aggressive Swing Trades (Larger Targets)
        {'name': 'Aggro 2.5%', 'TP': 0.025, 'SL': 0.008, 'ADX': 30}, # 2.5% TP
        {'name': 'Aggro 3%', 'TP': 0.03, 'SL': 0.01, 'ADX': 30}, # 3% TP
        {'name': 'Aggro 4%', 'TP': 0.04, 'SL': 0.012, 'ADX': 25}, # 4% TP, looser filter
        
        # High Quality with Better R:R
        {'name': 'Quality 2%', 'TP': 0.02, 'SL': 0.006, 'ADX': 40}, # Strict ADX
        {'name': 'Quality 2.5%', 'TP': 0.025, 'SL': 0.008, 'ADX': 40},
        
        # More Frequency
        {'name': 'Volume Play', 'TP': 0.02, 'SL': 0.008, 'ADX': 20}, # Lower ADX for more trades
    ]
    
    results = []

    for cfg in TEST_CONFIGS:
        print(f"\n--- Testing Config: {cfg['name']} (TP={cfg['TP']:.1%}, SL={cfg['SL']:.1%}, ADX={cfg['ADX']}) ---")
        
        # Apply Config
        Config.ADX_MIN = cfg['ADX']
        current_tp = cfg['TP']
        current_sl = cfg['SL']
        
        # Reset State
        balance = 10000 # Starting balance
        position = None
        trades = []
        total_commission = 0
        last_trade_time = {} # {symbol: timestamp}
        
        # Simulation Loop
        total_steps = len(timeline)
        for i, current_time in enumerate(timeline):
            if i % 10000 == 0:
                print(f"  Step {i}/{total_steps} ({i/total_steps:.1%}) - Balance: {balance:.2f}")
            
            # 1. Manage Existing Position
            if position:
                symbol = position['symbol']
                df = data_map.get(symbol)
                if df is None or current_time not in df.index:
                    continue
                    
                row = df.loc[current_time]
                
                # Check Exit
                exit_price = None
                exit_reason = None
                
                if position['type'] == 'LONG':
                    if row['low'] <= position['sl_price']:
                        exit_price = position['sl_price']
                        exit_reason = 'SL'
                    elif row['high'] >= position['tp_price']:
                        exit_price = position['tp_price']
                        exit_reason = 'TP'
                else: # SHORT
                    if row['high'] >= position['sl_price']:
                        exit_price = position['sl_price']
                        exit_reason = 'SL'
                    elif row['low'] <= position['tp_price']:
                        exit_price = position['tp_price']
                        exit_reason = 'TP'
                        
                if exit_price:
                    # Close Position
                    pnl = (exit_price - position['entry_price']) * position['size'] if position['type'] == 'LONG' else \
                          (position['entry_price'] - exit_price) * position['size']
                    
                    # Commission
                    exit_comm = exit_price * position['size'] * BACKTEST_CONFIG['COMMISSION_RATE']
                    entry_comm = position['entry_comm']
                    
                    net_pnl = pnl - exit_comm - entry_comm
                    total_commission += (exit_comm + entry_comm)
                    
                    balance += net_pnl
                    
                    trades.append({
                        'entry_time': position['entry_time'],
                        'exit_time': current_time,
                        'symbol': symbol,
                        'type': position['type'],
                        'entry_price': position['entry_price'],
                        'exit_price': exit_price,
                        'reason': exit_reason,
                        'gross_pnl': pnl,
                        'commission': entry_comm + exit_comm,
                        'net_pnl': net_pnl,
                        'balance': balance
                    })
                    
                    position = None
                    continue
        
            # 2. Check for New Entries (only if no position)
            if position is None:
                # Time Filter: 7am - 3pm
                if not (BACKTEST_CONFIG['START_HOUR'] <= current_time.hour < BACKTEST_CONFIG['END_HOUR']):
                    continue
                    
                candidates = []
                
                for symbol, df in data_map.items():
                    if current_time not in df.index:
                        continue
                    
                    # Cooldown Check
                    last_trade = last_trade_time.get(symbol, 0)
                    if last_trade != 0:
                        time_since_trade = (current_time - last_trade).total_seconds() / 60
                        if time_since_trade < Config.SYMBOL_COOLDOWN_MINUTES:
                            continue

                    # Get integer location for slicing
                    try:
                        idx = df.index.get_loc(current_time)
                        if isinstance(idx, slice):
                            idx = idx.stop - 1
                        if idx < 200: # Need warmup
                            continue
                            
                        sub_df = df.iloc[idx-200 : idx]
                        
                        if sub_df.empty: continue
                        
                        closed_candle = sub_df.iloc[-1]
                        atr = closed_candle['ATR']
                        price = closed_candle['close']
                        
                        # --- 1. Volatility Filter (ATR) ---
                        from modules.filters.volatility import VolatilityFilters
                        if not VolatilityFilters.check_atr(atr, price):
                            continue
                            
                        # --- 2. Volatility Filter (Range) ---
                        if not VolatilityFilters.check_range_extreme(sub_df, atr):
                            continue
                            
                        # --- 3. Spread Filter ---
                        # Skipped (No Order Book data)
                        
                        # --- 4. Signal Check ---
                        # Check LONG
                        long_ok, long_res = EntrySignals.check_signals(sub_df, "LONG")
                        if long_ok:
                            score = EntrySignals.calculate_score(long_res)
                            candidates.append({
                                'symbol': symbol,
                                'type': 'LONG',
                                'score': score,
                                'price': price,
                                'entry_price': df.iloc[idx]['open'],
                                'atr': atr
                            })
                            
                        # Check SHORT
                        short_ok, short_res = EntrySignals.check_signals(sub_df, "SHORT")
                        if short_ok:
                            score = EntrySignals.calculate_score(short_res)
                            candidates.append({
                                'symbol': symbol,
                                'type': 'SHORT',
                                'score': score,
                                'price': price,
                                'entry_price': df.iloc[idx]['open'],
                                'atr': atr
                            })
                            
                    except KeyError:
                        continue
                    except Exception as e:
                        continue
                
                # Select Best Candidate
                if candidates:
                    # Sort by score descending
                    candidates.sort(key=lambda x: x['score'], reverse=True)
                    best = candidates[0]
                    
                    # Open Position
                    entry_price = best['entry_price']
                    
                    # Size
                    size = BACKTEST_CONFIG['EXPOSURE_USD'] / entry_price
                    
                    # TP/SL
                    if best['type'] == 'LONG':
                        tp_price = entry_price * (1 + current_tp)
                        sl_price = entry_price * (1 - current_sl)
                    else:
                        tp_price = entry_price * (1 - current_tp)
                        sl_price = entry_price * (1 + current_sl)
                        
                    # Commission
                    entry_comm = size * entry_price * BACKTEST_CONFIG['COMMISSION_RATE']
                    
                    position = {
                        'symbol': best['symbol'],
                        'type': best['type'],
                        'entry_price': entry_price,
                        'size': size,
                        'entry_time': current_time,
                        'tp_price': tp_price,
                        'sl_price': sl_price,
                        'entry_comm': entry_comm
                    }
                    
                    # Update Cooldown
                    last_trade_time[best['symbol']] = current_time

        # End of Config Loop
        net_profit = balance - 10000
        win_rate = len([t for t in trades if t['net_pnl'] > 0]) / len(trades) if trades else 0
        print(f"  Result: Net Profit ${net_profit:.2f} | Win Rate {win_rate:.2%} | Trades {len(trades)}")
        results.append({'config': cfg, 'profit': net_profit, 'win_rate': win_rate, 'trades': len(trades)})

    # Summary
    print("\n=== OPTIMIZATION SUMMARY ===")
    results.sort(key=lambda x: x['profit'], reverse=True)
    for r in results:
        cfg = r['config']
        print(f"{cfg['name']:<15} | TP: {cfg['TP']:.1%} | SL: {cfg['SL']:.1%} | ADX: {cfg['ADX']} | Profit: ${r['profit']:>8.2f} | WR: {r['win_rate']:.2%} | Trades: {r['trades']}")


if __name__ == "__main__":
    main()
