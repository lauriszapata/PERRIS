#!/usr/bin/env python3
"""
Backtest Optimizado: Buscando la configuración ganadora
"""

import sys
sys.path.insert(0, '/Users/laurazapata/Desktop/PERRIS')

import pandas as pd
import numpy as np
from pathlib import Path
from itertools import product

EXPOSURE_USD = 128
COMMISSION_RATE = 0.0005

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
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
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
    
    # Volume MA
    df['VOL_MA'] = df['volume'].rolling(window=20).mean()
    df['VOL_RATIO'] = df['volume'] / df['VOL_MA']
    
    # Momentum
    df['MOM'] = df['close'].pct_change(periods=5) * 100
    
    return df

def check_entry_signal_strict(df, idx, direction, adx_min=25, rsi_buffer=10, vol_ratio_min=1.0, require_ema200=True):
    """Señales de entrada más estrictas"""
    if idx < 200:
        return False
    
    row = df.iloc[idx]
    
    # Filtro ATR mínimo más alto
    if row['ATR_PCT'] < 0.002:  # 0.2% mínimo
        return False
    
    # ADX más alto = tendencia más fuerte
    if row['ADX'] < adx_min:
        return False
    
    # Volumen por encima del promedio
    if row['VOL_RATIO'] < vol_ratio_min:
        return False
    
    if direction == 'LONG':
        # EMA stack completo
        if not (row['EMA_9'] > row['EMA_21'] > row['EMA_50']):
            return False
        # Precio sobre EMA200 para confirmar tendencia alcista
        if require_ema200 and row['close'] < row['EMA_200']:
            return False
        # RSI no sobrecomprado pero con momentum
        if row['RSI'] > (70 - rsi_buffer) or row['RSI'] < 40:
            return False
        # Momentum positivo
        if row['MOM'] < 0:
            return False
        return True
    else:  # SHORT
        if not (row['EMA_9'] < row['EMA_21'] < row['EMA_50']):
            return False
        if require_ema200 and row['close'] > row['EMA_200']:
            return False
        if row['RSI'] < (30 + rsi_buffer) or row['RSI'] > 60:
            return False
        if row['MOM'] > 0:
            return False
        return True

def simulate_trade(df, entry_idx, direction, tp_pct, sl_pct):
    entry_price = df.iloc[entry_idx]['close']
    
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

def run_optimization():
    print("=" * 70)
    print("🔍 OPTIMIZACIÓN DE ESTRATEGIA PERRIS")
    print("=" * 70)
    
    all_data = load_historical_data()
    print(f"\n📊 Datos cargados: {len(all_data)} pares")
    
    # Pre-calcular indicadores
    print("📈 Calculando indicadores...")
    for symbol in all_data:
        all_data[symbol] = calculate_indicators(all_data[symbol])
    
    # Grid de parámetros a probar
    tp_values = [0.004, 0.005, 0.006, 0.007, 0.008]  # 0.4% - 0.8%
    sl_values = [0.003, 0.004, 0.005, 0.006]  # 0.3% - 0.6%
    adx_values = [20, 25, 30]
    vol_ratios = [0.8, 1.0, 1.2]
    
    results = []
    total_combos = len(tp_values) * len(sl_values) * len(adx_values) * len(vol_ratios)
    print(f"\n🔄 Probando {total_combos} combinaciones...")
    
    combo_count = 0
    for tp, sl, adx, vol in product(tp_values, sl_values, adx_values, vol_ratios):
        combo_count += 1
        
        trades = []
        for symbol, df in all_data.items():
            i = 200
            cooldown = 0
            
            while i < len(df) - 1:
                if cooldown > 0:
                    cooldown -= 1
                    i += 1
                    continue
                
                for direction in ['LONG', 'SHORT']:
                    if check_entry_signal_strict(df, i, direction, adx_min=adx, vol_ratio_min=vol):
                        trade = simulate_trade(df, i, direction, tp, sl)
                        trades.append(trade)
                        cooldown = trade['candles_held'] + 1
                        break
                
                i += 1
        
        if trades:
            df_trades = pd.DataFrame(trades)
            total_pnl = df_trades['net_pnl'].sum()
            total_trades = len(df_trades)
            win_rate = len(df_trades[df_trades['net_pnl'] > 0]) / total_trades * 100
            ratio = tp / sl
            
            results.append({
                'tp': tp * 100,
                'sl': sl * 100,
                'adx': adx,
                'vol': vol,
                'ratio': ratio,
                'trades': total_trades,
                'win_rate': win_rate,
                'pnl': total_pnl,
                'pnl_per_trade': total_pnl / total_trades
            })
    
    print(f"\n✅ Optimización completada")
    
    # Ordenar por PnL
    results.sort(key=lambda x: x['pnl'], reverse=True)
    
    print("\n" + "=" * 70)
    print("🏆 TOP 10 MEJORES CONFIGURACIONES")
    print("-" * 70)
    print(f"{'TP%':<6} {'SL%':<6} {'ADX':<5} {'VOL':<5} {'RATIO':<7} {'TRADES':<8} {'WR%':<7} {'PnL':<12} {'$/TRADE':<10}")
    print("-" * 70)
    
    for r in results[:10]:
        status = "✅" if r['pnl'] > 0 else "❌"
        print(f"{r['tp']:.2f}  {r['sl']:.2f}  {r['adx']:<5} {r['vol']:<5.1f} {r['ratio']:.2f}:1  {r['trades']:<8} {r['win_rate']:.1f}%   ${r['pnl']:>9.2f}  ${r['pnl_per_trade']:.3f} {status}")
    
    # Análisis de la mejor
    if results[0]['pnl'] > 0:
        best = results[0]
        print("\n" + "=" * 70)
        print("🎯 CONFIGURACIÓN GANADORA ENCONTRADA!")
        print("-" * 70)
        print(f"   TP: {best['tp']:.2f}%")
        print(f"   SL: {best['sl']:.2f}%")
        print(f"   ADX mínimo: {best['adx']}")
        print(f"   Volume Ratio mínimo: {best['vol']}")
        print(f"   Ratio: {best['ratio']:.2f}:1")
        print(f"   Win Rate: {best['win_rate']:.1f}%")
        print(f"   PnL Total: ${best['pnl']:.2f}")
        print(f"   PnL por trade: ${best['pnl_per_trade']:.3f}")
    else:
        print("\n" + "=" * 70)
        print("⚠️ NO SE ENCONTRÓ CONFIGURACIÓN RENTABLE")
        print("-" * 70)
        print("   La mejor configuración aún tiene pérdidas.")
        print("   Sugerencias:")
        print("   1. Necesitas mejores señales de entrada")
        print("   2. Considera agregar confirmación de tendencia en TF superior")
        print("   3. Solo operar en rangos horarios específicos")
        print("   4. Filtrar pares con bajo rendimiento histórico")
    
    # Guardar todos los resultados
    pd.DataFrame(results).to_csv('/Users/laurazapata/Desktop/PERRIS/data/optimization_results.csv', index=False)
    print(f"\n💾 Resultados guardados en optimization_results.csv")

if __name__ == '__main__':
    run_optimization()
