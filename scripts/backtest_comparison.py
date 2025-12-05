#!/usr/bin/env python3
"""
Backtest Comparativo: Estrategias PERRIS
- Conservadora: TP 0.28% / SL 0.9%
- Agresiva: TP 0.5% / SL 0.3%
- Equilibrada: TP 0.4% / SL 0.4%
"""

import sys
sys.path.insert(0, '/Users/laurazapata/Desktop/PERRIS')

import pandas as pd
import numpy as np
from pathlib import Path

EXPOSURE_USD = 128
COMMISSION_RATE = 0.0005

STRATEGIES = {
    'Conservadora (0.28%/0.9%)': {'tp': 0.0028, 'sl': 0.009},
    'Agresiva (0.5%/0.3%)': {'tp': 0.005, 'sl': 0.003},
    'Equilibrada (0.4%/0.4%)': {'tp': 0.004, 'sl': 0.004},
    'Sniper (0.6%/0.5%)': {'tp': 0.006, 'sl': 0.005},
}

def load_historical_data():
    data_path = Path('/Users/laurazapata/Desktop/PERRIS/data/historical')
    all_data = {}
    for csv_file in data_path.glob('*_15m.csv'):
        symbol = csv_file.stem.replace('_15m', '')
        df = pd.read_csv(csv_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        all_data[symbol] = df
    return all_data

def calculate_indicators(df):
    df = df.copy()
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()
    df['ATR_PCT'] = df['ATR'] / df['close']
    
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff().abs() * -1
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm < 0), 0).abs()
    
    tr_smooth = tr.rolling(window=14).sum()
    plus_di = 100 * (plus_dm.rolling(window=14).sum() / tr_smooth)
    minus_di = 100 * (minus_dm.rolling(window=14).sum() / tr_smooth)
    
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
    df['ADX'] = dx.rolling(window=14).mean()
    
    return df

def check_entry_signal(df, idx, direction):
    if idx < 50:
        return False
    
    row = df.iloc[idx]
    
    if row['ATR_PCT'] < 0.0015:
        return False
    
    if row['ADX'] < 15:
        return False
    
    if direction == 'LONG':
        if not (row['EMA_9'] > row['EMA_21'] > row['EMA_50']):
            return False
        if row['RSI'] > 75:
            return False
        return True
    else:
        if not (row['EMA_9'] < row['EMA_21'] < row['EMA_50']):
            return False
        if row['RSI'] < 25:
            return False
        return True

def simulate_trade(df, entry_idx, direction, tp_pct, sl_pct):
    entry_price = df.iloc[entry_idx]['close']
    entry_time = df.iloc[entry_idx]['timestamp']
    
    if direction == 'LONG':
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)
    else:
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)
    
    size = EXPOSURE_USD / entry_price
    max_candles = min(96, len(df) - entry_idx - 1)
    
    exit_reason = 'TIMEOUT'
    exit_price = df.iloc[min(entry_idx + max_candles, len(df) - 1)]['close']
    candles_held = max_candles
    
    for i in range(1, max_candles + 1):
        candle = df.iloc[entry_idx + i]
        
        if direction == 'LONG':
            if candle['low'] <= sl_price:
                exit_reason = 'SL'
                exit_price = sl_price
                candles_held = i
                break
            if candle['high'] >= tp_price:
                exit_reason = 'TP'
                exit_price = tp_price
                candles_held = i
                break
        else:
            if candle['high'] >= sl_price:
                exit_reason = 'SL'
                exit_price = sl_price
                candles_held = i
                break
            if candle['low'] <= tp_price:
                exit_reason = 'TP'
                exit_price = tp_price
                candles_held = i
                break
    
    if direction == 'LONG':
        pnl = (exit_price - entry_price) * size
    else:
        pnl = (entry_price - exit_price) * size
    
    commission = (size * entry_price + size * exit_price) * COMMISSION_RATE
    net_pnl = pnl - commission
    
    return {
        'net_pnl': net_pnl,
        'exit_reason': exit_reason,
        'candles_held': candles_held
    }

def run_strategy_backtest(all_data, tp_pct, sl_pct):
    trades = []
    
    for symbol, df in all_data.items():
        df = calculate_indicators(df)
        i = 50
        cooldown = 0
        
        while i < len(df) - 1:
            if cooldown > 0:
                cooldown -= 1
                i += 1
                continue
            
            for direction in ['LONG', 'SHORT']:
                if check_entry_signal(df, i, direction):
                    trade = simulate_trade(df, i, direction, tp_pct, sl_pct)
                    trades.append(trade)
                    cooldown = trade['candles_held'] + 1
                    break
            
            i += 1
    
    return trades

def main():
    print("=" * 70)
    print("🎯 COMPARACIÓN DE ESTRATEGIAS PERRIS")
    print("=" * 70)
    
    all_data = load_historical_data()
    print(f"\n📊 Datos cargados: {len(all_data)} pares\n")
    
    results = []
    
    for name, params in STRATEGIES.items():
        tp = params['tp']
        sl = params['sl']
        ratio = tp / sl
        breakeven_wr = 1 / (1 + ratio) * 100
        
        trades = run_strategy_backtest(all_data, tp, sl)
        
        if trades:
            df = pd.DataFrame(trades)
            total_trades = len(df)
            winners = len(df[df['net_pnl'] > 0])
            win_rate = winners / total_trades * 100
            total_pnl = df['net_pnl'].sum()
            tp_hits = len(df[df['exit_reason'] == 'TP'])
            sl_hits = len(df[df['exit_reason'] == 'SL'])
        else:
            total_trades = 0
            win_rate = 0
            total_pnl = 0
            tp_hits = 0
            sl_hits = 0
        
        results.append({
            'name': name,
            'tp': tp * 100,
            'sl': sl * 100,
            'ratio': ratio,
            'breakeven_wr': breakeven_wr,
            'trades': total_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'tp_hits': tp_hits,
            'sl_hits': sl_hits,
            'margin': win_rate - breakeven_wr
        })
    
    # Mostrar resultados
    print("-" * 70)
    print(f"{'ESTRATEGIA':<30} {'RATIO':<8} {'WR NEED':<8} {'WR REAL':<8} {'PnL':<12} {'MARGEN':<8}")
    print("-" * 70)
    
    for r in results:
        margin_str = f"+{r['margin']:.1f}%" if r['margin'] > 0 else f"{r['margin']:.1f}%"
        status = "✅" if r['margin'] > 0 else "❌"
        print(f"{r['name']:<30} {r['ratio']:.2f}:1   {r['breakeven_wr']:.1f}%    {r['win_rate']:.1f}%    ${r['total_pnl']:>9.2f}  {margin_str} {status}")
    
    print("-" * 70)
    
    # Mejor estrategia
    best = max(results, key=lambda x: x['total_pnl'])
    print(f"\n🏆 MEJOR ESTRATEGIA: {best['name']}")
    print(f"   PnL: ${best['total_pnl']:.2f}")
    print(f"   Win Rate: {best['win_rate']:.1f}%")
    print(f"   Trades: {best['trades']}")
    
    # Análisis adicional
    print("\n" + "=" * 70)
    print("📊 ANÁLISIS DETALLADO")
    print("-" * 70)
    
    for r in results:
        print(f"\n{r['name']}:")
        print(f"   TP: {r['tp']:.2f}% | SL: {r['sl']:.2f}%")
        print(f"   Ratio: {r['ratio']:.2f}:1")
        print(f"   TP Hits: {r['tp_hits']} | SL Hits: {r['sl_hits']}")
        print(f"   Win Rate: {r['win_rate']:.1f}% (necesario: {r['breakeven_wr']:.1f}%)")
        print(f"   PnL Total: ${r['total_pnl']:.2f}")
        if r['margin'] > 0:
            print(f"   ✅ Rentable con margen de +{r['margin']:.1f}%")
        else:
            print(f"   ❌ No rentable, déficit de {r['margin']:.1f}%")
    
    print("\n" + "=" * 70)
    print("💡 CONCLUSIÓN")
    print("-" * 70)
    
    profitable = [r for r in results if r['total_pnl'] > 0]
    if profitable:
        print(f"\n✅ Estrategias rentables: {len(profitable)}")
        for p in profitable:
            print(f"   - {p['name']}: ${p['total_pnl']:.2f}")
    else:
        print("\n⚠️ Ninguna estrategia es rentable con los criterios de entrada actuales.")
        print("   El problema NO es el TP/SL, sino las SEÑALES DE ENTRADA.")
        print("\n   RECOMENDACIONES:")
        print("   1. Filtrar mejor las entradas (confirmar tendencia)")
        print("   2. Añadir filtros de volumen/momentum")
        print("   3. Solo operar en horarios de alta liquidez")
        print("   4. Considerar trailing stop en vez de TP fijo")

if __name__ == '__main__':
    main()
