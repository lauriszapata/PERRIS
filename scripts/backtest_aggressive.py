#!/usr/bin/env python3
"""
Backtest de Estrategia Agresiva: TP 0.5% / SL 0.3%
Analiza el último mes de datos históricos
"""

import sys
sys.path.insert(0, '/Users/laurazapata/Desktop/PERRIS')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Configuración de la estrategia agresiva
TP_PCT = 0.005  # 0.5%
SL_PCT = 0.003  # 0.3%
EXPOSURE_USD = 128  # $128 USD por trade
COMMISSION_RATE = 0.0005  # 0.05% taker fee

def load_historical_data():
    """Carga todos los archivos históricos disponibles"""
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
    """Calcula indicadores básicos para señales"""
    df = df.copy()
    
    # EMAs
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()
    df['ATR_PCT'] = df['ATR'] / df['close']
    
    # ADX
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
    """Verifica señales de entrada simplificadas"""
    if idx < 50:
        return False
    
    row = df.iloc[idx]
    
    # Filtro ATR mínimo (0.15%)
    if row['ATR_PCT'] < 0.0015:
        return False
    
    # ADX > 15 (tendencia)
    if row['ADX'] < 15:
        return False
    
    if direction == 'LONG':
        # EMA 9 > EMA 21 > EMA 50
        if not (row['EMA_9'] > row['EMA_21'] > row['EMA_50']):
            return False
        # RSI no sobrecomprado
        if row['RSI'] > 75:
            return False
        return True
    else:  # SHORT
        # EMA 9 < EMA 21 < EMA 50
        if not (row['EMA_9'] < row['EMA_21'] < row['EMA_50']):
            return False
        # RSI no sobrevendido
        if row['RSI'] < 25:
            return False
        return True

def simulate_trade(df, entry_idx, direction):
    """Simula un trade con TP/SL fijos"""
    entry_price = df.iloc[entry_idx]['close']
    entry_time = df.iloc[entry_idx]['timestamp']
    
    if direction == 'LONG':
        tp_price = entry_price * (1 + TP_PCT)
        sl_price = entry_price * (1 - SL_PCT)
    else:
        tp_price = entry_price * (1 - TP_PCT)
        sl_price = entry_price * (1 + SL_PCT)
    
    size = EXPOSURE_USD / entry_price
    
    # Buscar salida en las siguientes velas (máx 96 velas = 24 horas)
    max_candles = min(96, len(df) - entry_idx - 1)
    
    for i in range(1, max_candles + 1):
        candle = df.iloc[entry_idx + i]
        
        if direction == 'LONG':
            # Check SL primero (worst case)
            if candle['low'] <= sl_price:
                pnl = (sl_price - entry_price) * size
                exit_reason = 'SL'
                exit_price = sl_price
                break
            # Check TP
            if candle['high'] >= tp_price:
                pnl = (tp_price - entry_price) * size
                exit_reason = 'TP'
                exit_price = tp_price
                break
        else:  # SHORT
            # Check SL primero
            if candle['high'] >= sl_price:
                pnl = (entry_price - sl_price) * size
                exit_reason = 'SL'
                exit_price = sl_price
                break
            # Check TP
            if candle['low'] <= tp_price:
                pnl = (entry_price - tp_price) * size
                exit_reason = 'TP'
                exit_price = tp_price
                break
    else:
        # Timeout - cerrar al precio actual
        exit_candle = df.iloc[min(entry_idx + max_candles, len(df) - 1)]
        exit_price = exit_candle['close']
        if direction == 'LONG':
            pnl = (exit_price - entry_price) * size
        else:
            pnl = (entry_price - exit_price) * size
        exit_reason = 'TIMEOUT'
    
    # Comisiones
    commission = (size * entry_price + size * exit_price) * COMMISSION_RATE
    net_pnl = pnl - commission
    
    return {
        'entry_time': entry_time,
        'exit_time': df.iloc[min(entry_idx + i if 'i' in dir() else entry_idx + max_candles, len(df) - 1)]['timestamp'],
        'direction': direction,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'size': size,
        'pnl': pnl,
        'commission': commission,
        'net_pnl': net_pnl,
        'exit_reason': exit_reason,
        'candles_held': i if exit_reason != 'TIMEOUT' else max_candles
    }

def run_backtest():
    """Ejecuta el backtest completo"""
    print("=" * 60)
    print("🎯 BACKTEST ESTRATEGIA AGRESIVA")
    print(f"   TP: {TP_PCT*100:.2f}% | SL: {SL_PCT*100:.2f}% | Ratio: {TP_PCT/SL_PCT:.2f}:1")
    print(f"   Exposición: ${EXPOSURE_USD} USD por trade")
    print("=" * 60)
    
    all_data = load_historical_data()
    print(f"\n📊 Datos cargados: {len(all_data)} pares")
    
    all_trades = []
    
    for symbol, df in all_data.items():
        df = calculate_indicators(df)
        
        i = 50  # Skip warmup
        cooldown = 0
        
        while i < len(df) - 1:
            if cooldown > 0:
                cooldown -= 1
                i += 1
                continue
            
            # Buscar señal
            for direction in ['LONG', 'SHORT']:
                if check_entry_signal(df, i, direction):
                    trade = simulate_trade(df, i, direction)
                    trade['symbol'] = symbol
                    all_trades.append(trade)
                    cooldown = trade['candles_held'] + 1  # No overlapping trades
                    break
            
            i += 1
    
    if not all_trades:
        print("\n❌ No se generaron trades con los criterios actuales")
        return
    
    # Análisis
    df_trades = pd.DataFrame(all_trades)
    df_trades = df_trades.sort_values('entry_time')
    
    print(f"\n📈 RESULTADOS DEL BACKTEST")
    print("-" * 50)
    
    total_trades = len(df_trades)
    winners = df_trades[df_trades['net_pnl'] > 0]
    losers = df_trades[df_trades['net_pnl'] <= 0]
    
    win_rate = len(winners) / total_trades * 100
    total_pnl = df_trades['net_pnl'].sum()
    total_commission = df_trades['commission'].sum()
    
    # Por tipo de salida
    tp_trades = df_trades[df_trades['exit_reason'] == 'TP']
    sl_trades = df_trades[df_trades['exit_reason'] == 'SL']
    timeout_trades = df_trades[df_trades['exit_reason'] == 'TIMEOUT']
    
    print(f"\n📊 ESTADÍSTICAS GENERALES:")
    print(f"   Total Trades: {total_trades}")
    print(f"   Win Rate: {win_rate:.1f}%")
    print(f"   PnL Total: ${total_pnl:.2f}")
    print(f"   Comisiones: ${total_commission:.2f}")
    print(f"   PnL Promedio: ${total_pnl/total_trades:.2f}")
    
    print(f"\n📊 DESGLOSE POR SALIDA:")
    print(f"   TP Hits: {len(tp_trades)} ({len(tp_trades)/total_trades*100:.1f}%)")
    print(f"   SL Hits: {len(sl_trades)} ({len(sl_trades)/total_trades*100:.1f}%)")
    print(f"   Timeouts: {len(timeout_trades)} ({len(timeout_trades)/total_trades*100:.1f}%)")
    
    if len(winners) > 0:
        avg_win = winners['net_pnl'].mean()
        print(f"\n   💚 Ganancia Promedio: ${avg_win:.2f}")
    if len(losers) > 0:
        avg_loss = losers['net_pnl'].mean()
        print(f"   🔴 Pérdida Promedio: ${avg_loss:.2f}")
    
    # Por símbolo
    print(f"\n📊 TOP 5 MEJORES PARES:")
    by_symbol = df_trades.groupby('symbol')['net_pnl'].agg(['sum', 'count']).sort_values('sum', ascending=False)
    for symbol, row in by_symbol.head(5).iterrows():
        print(f"   {symbol}: ${row['sum']:.2f} ({int(row['count'])} trades)")
    
    print(f"\n📊 TOP 5 PEORES PARES:")
    for symbol, row in by_symbol.tail(5).iterrows():
        print(f"   {symbol}: ${row['sum']:.2f} ({int(row['count'])} trades)")
    
    # Comparación con estrategia anterior
    print("\n" + "=" * 60)
    print("📊 COMPARACIÓN CON ESTRATEGIA ANTERIOR (0.28%/0.9%)")
    print("-" * 50)
    
    # Calcular con parámetros anteriores para comparar
    OLD_TP = 0.0028
    OLD_SL = 0.009
    
    # Simular con win rate actual
    # Con ratio 1:3.2 necesitas 76.2% WR para break even
    # Con ratio 1.67:1 necesitas 37.5% WR para break even
    
    old_ratio = OLD_SL / OLD_TP  # 3.21
    new_ratio = TP_PCT / SL_PCT  # 1.67
    
    old_breakeven_wr = old_ratio / (1 + old_ratio) * 100  # 76.2%
    new_breakeven_wr = 1 / (1 + new_ratio) * 100  # 37.5%
    
    print(f"\n   Estrategia Anterior (0.28%/0.9%):")
    print(f"   - Ratio: 1:{old_ratio:.1f} (desfavorable)")
    print(f"   - Win Rate necesario: {old_breakeven_wr:.1f}%")
    
    print(f"\n   Estrategia Agresiva (0.5%/0.3%):")
    print(f"   - Ratio: {new_ratio:.1f}:1 (favorable)")
    print(f"   - Win Rate necesario: {new_breakeven_wr:.1f}%")
    print(f"   - Tu Win Rate actual: {win_rate:.1f}%")
    
    if win_rate > new_breakeven_wr:
        margin = win_rate - new_breakeven_wr
        print(f"\n   ✅ Margen de seguridad: +{margin:.1f}% sobre breakeven")
    else:
        margin = new_breakeven_wr - win_rate
        print(f"\n   ⚠️ Déficit: -{margin:.1f}% bajo breakeven")
    
    print("\n" + "=" * 60)
    
    # Guardar resultados
    output_file = '/Users/laurazapata/Desktop/PERRIS/data/backtest_aggressive_results.csv'
    df_trades.to_csv(output_file, index=False)
    print(f"\n💾 Resultados guardados en: {output_file}")
    
    return df_trades

if __name__ == '__main__':
    run_backtest()
