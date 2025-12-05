#!/usr/bin/env python3
"""
BACKTEST PROFESIONAL DEFINITIVO V2
===================================
- Guarda resultados parciales cada 1000 combinaciones
- Puede continuar desde donde quedó
- Sin look-ahead bias
- Comisiones reales
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
import os
import json
from datetime import datetime
from itertools import product
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# COSTOS REALES
# ============================================================================
TAKER_FEE = 0.0005
SLIPPAGE = 0.0003
TOTAL_FEE = (TAKER_FEE + SLIPPAGE) * 2
FUNDING_RATE = 0.0001

EXPOSURE = 210  # $210 por trade

# Archivo para guardar progreso
PROGRESS_FILE = "data/backtest_progress.json"
RESULTS_FILE = "data/backtest_results.json"

# ============================================================================
# SÍMBOLOS
# ============================================================================
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
           'BNBUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT']

# ============================================================================
# CARGAR DATOS
# ============================================================================
def load_data():
    data_15m = {}
    data_1h = {}
    
    for symbol in SYMBOLS:
        path_15m = f"data/historical/{symbol}_15m_full.csv"
        if os.path.exists(path_15m):
            df = pd.read_csv(path_15m)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp').reset_index(drop=True)
            data_15m[symbol] = df
        
        path_1h = f"data/historical/{symbol}_1h_mtf.csv"
        if os.path.exists(path_1h):
            df = pd.read_csv(path_1h)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('timestamp').reset_index(drop=True)
            data_1h[symbol] = df
    
    return data_15m, data_1h


def calculate_indicators_15m(df):
    df = df.copy()
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['RSI'] = ta.rsi(df['close'], length=14)
    
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['MACD_line'] = macd['MACD_12_26_9']
    df['MACD_signal'] = macd['MACDs_12_26_9']
    
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14']
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['ATR_pct'] = df['ATR'] / df['close'] * 100
    df['vol_avg'] = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_avg']
    df['range_12'] = df['high'].rolling(12).max() - df['low'].rolling(12).min()
    df['hour'] = df['timestamp'].dt.hour
    
    return df


def calculate_indicators_1h(df):
    df = df.copy()
    df['EMA50_1h'] = ta.ema(df['close'], length=50)
    df['EMA200_1h'] = ta.ema(df['close'], length=200)
    return df


def get_mtf_trend(df_1h, timestamp):
    mask = df_1h['timestamp'] <= timestamp
    if not mask.any():
        return None
    
    idx = df_1h[mask].index[-1]
    row = df_1h.iloc[idx]
    
    if pd.isna(row['EMA50_1h']) or pd.isna(row['EMA200_1h']):
        return None
    
    return "BULLISH" if row['EMA50_1h'] > row['EMA200_1h'] else "BEARISH"


def check_signal(row, df_1h, config):
    required = ['EMA9', 'EMA21', 'EMA50', 'RSI', 'ADX', 'MACD_line', 'MACD_signal', 
                'ATR', 'ATR_pct', 'vol_ratio', 'range_12']
    for col in required:
        if pd.isna(row[col]):
            return None
    
    adx_min = config['adx_min']
    vol_mult = config['vol_mult']
    atr_min = config['atr_min']
    atr_max = config['atr_max']
    hours = config.get('hours', None)
    direction_filter = config.get('direction', 'BOTH')
    
    if hours is not None and row['hour'] not in hours:
        return None
    
    if row['ATR_pct'] < atr_min or row['ATR_pct'] > atr_max:
        return None
    
    if row['range_12'] < 0.6 * row['ATR']:
        return None
    
    if row['ADX'] < adx_min:
        return None
    
    if row['vol_ratio'] < vol_mult:
        return None
    
    mtf_trend = get_mtf_trend(df_1h, row['timestamp'])
    
    long_signal = False
    if direction_filter in ['LONG', 'BOTH']:
        ema_cross_long = row['EMA9'] > row['EMA21']
        trend_local_long = row['close'] > row['EMA50']
        macd_long = row['MACD_line'] > row['MACD_signal']
        rsi_long = row['RSI'] > 35
        mtf_long = mtf_trend == "BULLISH" if mtf_trend else False
        
        if ema_cross_long and trend_local_long and macd_long and rsi_long and mtf_long:
            long_signal = True
        elif ema_cross_long and macd_long and rsi_long and row['ADX'] >= 30 and row['vol_ratio'] >= 1.5:
            long_signal = True
    
    short_signal = False
    if direction_filter in ['SHORT', 'BOTH']:
        ema_cross_short = row['EMA9'] < row['EMA21']
        trend_local_short = row['close'] < row['EMA50']
        macd_short = row['MACD_line'] < row['MACD_signal']
        rsi_short = 30 < row['RSI'] < 55
        mtf_short = mtf_trend == "BEARISH" if mtf_trend else False
        
        if ema_cross_short and trend_local_short and macd_short and rsi_short and mtf_short:
            short_signal = True
        elif ema_cross_short and macd_short and rsi_short and row['ADX'] >= 30 and row['vol_ratio'] >= 1.5:
            short_signal = True
    
    if long_signal:
        return "LONG"
    elif short_signal:
        return "SHORT"
    return None


def simulate_trade(df, signal_idx, direction, tp_pct, sl_pct, max_candles):
    entry_idx = signal_idx + 1
    if entry_idx >= len(df):
        return None
    
    entry_price = df.iloc[entry_idx]['open']
    entry_time = df.iloc[entry_idx]['timestamp']
    
    if direction == "LONG":
        tp_price = entry_price * (1 + tp_pct)
        sl_price = entry_price * (1 - sl_pct)
    else:
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)
    
    exit_type = "TIMEOUT"
    pnl_pct = 0
    i = entry_idx
    
    for i in range(entry_idx + 1, min(entry_idx + max_candles, len(df))):
        candle = df.iloc[i]
        high, low = candle['high'], candle['low']
        
        if direction == "LONG":
            if low <= sl_price:
                pnl_pct = -sl_pct
                exit_type = "SL"
                break
            if high >= tp_price:
                pnl_pct = tp_pct
                exit_type = "TP"
                break
        else:
            if high >= sl_price:
                pnl_pct = -sl_pct
                exit_type = "SL"
                break
            if low <= tp_price:
                pnl_pct = tp_pct
                exit_type = "TP"
                break
    else:
        i = min(entry_idx + max_candles - 1, len(df) - 1)
        exit_price = df.iloc[i]['close']
        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
    
    exit_time = df.iloc[i]['timestamp']
    duration_h = (exit_time - entry_time).total_seconds() / 3600
    funding = int(duration_h / 8) * FUNDING_RATE
    
    net_pnl_pct = pnl_pct - TOTAL_FEE - funding
    
    return {
        'exit_idx': i,
        'entry_time': entry_time,
        'direction': direction,
        'exit_type': exit_type,
        'pnl_usd': EXPOSURE * net_pnl_pct,
        'duration_h': duration_h,
    }


def run_backtest(data_15m, data_1h, config, symbols_to_use):
    all_trades = []
    cooldown_candles = config['cooldown'] // 15
    max_candles = config['max_duration'] // 15
    
    for symbol in symbols_to_use:
        if symbol not in data_15m or symbol not in data_1h:
            continue
        
        df_15m = data_15m[symbol]
        df_1h = data_1h[symbol]
        cooldown_until = 0
        
        for i in range(250, len(df_15m) - max_candles - 5):
            if i < cooldown_until:
                continue
            
            row = df_15m.iloc[i]
            signal = check_signal(row, df_1h, config)
            
            if signal is None:
                continue
            
            result = simulate_trade(df_15m, i, signal, config['tp'], config['sl'], max_candles)
            
            if result is None:
                continue
            
            result['symbol'] = symbol
            all_trades.append(result)
            cooldown_until = result['exit_idx'] + cooldown_candles
    
    return all_trades


def analyze_results(trades):
    if not trades:
        return None
    
    df = pd.DataFrame(trades)
    df = df.sort_values('entry_time').reset_index(drop=True)
    
    total = len(df)
    wins = len(df[df['pnl_usd'] > 0])
    wr = wins / total * 100 if total > 0 else 0
    total_pnl = df['pnl_usd'].sum()
    
    cumsum = df['pnl_usd'].cumsum()
    max_dd = (cumsum - cumsum.cummax()).min()
    
    df['month'] = df['entry_time'].dt.to_period('M')
    monthly = df.groupby('month')['pnl_usd'].sum()
    positive_months = (monthly > 0).sum()
    total_months = len(monthly)
    
    return {
        'trades': total,
        'win_rate': wr,
        'total_pnl': total_pnl,
        'max_dd': max_dd,
        'positive_months': positive_months,
        'total_months': total_months,
        'monthly_detail': {str(k): v for k, v in monthly.items()},
    }


def save_progress(tested, best_configs):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({'tested': tested, 'count': len(best_configs)}, f)
    
    # Guardar solo las mejores 100
    top_100 = sorted(best_configs, key=lambda x: (x['positive_months'], x['total_pnl']), reverse=True)[:100]
    with open(RESULTS_FILE, 'w') as f:
        json.dump(top_100, f, indent=2, default=str)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return None


def main():
    print("=" * 80)
    print("🔬 BACKTEST PROFESIONAL DEFINITIVO V2 - CON GUARDADO DE PROGRESO")
    print("=" * 80)
    
    print("\n📥 Cargando datos...")
    data_15m_raw, data_1h_raw = load_data()
    
    print("📊 Calculando indicadores...")
    data_15m = {}
    data_1h = {}
    
    for symbol in SYMBOLS:
        if symbol in data_15m_raw:
            data_15m[symbol] = calculate_indicators_15m(data_15m_raw[symbol])
            print(f"   {symbol}: {len(data_15m[symbol])} velas 15m")
        if symbol in data_1h_raw:
            data_1h[symbol] = calculate_indicators_1h(data_1h_raw[symbol])
    
    # Parámetros
    tp_options = [0.03, 0.04, 0.05, 0.06, 0.08]
    sl_options = [0.015, 0.02, 0.025, 0.03]
    adx_options = [20, 25, 30]
    vol_options = [1.0, 1.3, 1.5]
    direction_options = ['BOTH', 'LONG', 'SHORT']
    cooldown_options = [60, 90, 120]
    
    hour_options = [
        None,
        list(range(8, 22)),
        list(range(12, 20)),
        list(range(0, 8)) + list(range(20, 24)),
    ]
    
    symbol_combos = [
        SYMBOLS,
        ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT'],
        ['BTCUSDT', 'ETHUSDT'],
        ['SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'ADAUSDT'],
        ['AVAXUSDT', 'LINKUSDT', 'DOTUSDT'],
    ]
    
    # Cargar resultados previos si existen
    best_configs = []
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, 'r') as f:
            best_configs = json.load(f)
        print(f"\n📂 Cargados {len(best_configs)} resultados previos")
    
    # Verificar progreso previo
    progress = load_progress()
    start_from = 0
    if progress:
        start_from = progress['tested']
        print(f"📍 Continuando desde combinación {start_from}")
    
    all_combos = list(product(
        tp_options, sl_options, adx_options, vol_options,
        direction_options, cooldown_options, hour_options, symbol_combos
    ))
    
    total_combos = len(all_combos)
    print(f"\n🔬 Total combinaciones: {total_combos}")
    print(f"   Comenzando desde: {start_from}")
    
    for idx, (tp, sl, adx, vol, direction, cooldown, hours, symbols_use) in enumerate(all_combos):
        if idx < start_from:
            continue
        
        if (idx + 1) % 500 == 0:
            print(f"   Probando {idx + 1}/{total_combos}... ({(idx + 1)/total_combos*100:.1f}%)")
            save_progress(idx + 1, best_configs)
        
        if tp / sl < 1.5:
            continue
        
        config = {
            'tp': tp,
            'sl': sl,
            'adx_min': adx,
            'vol_mult': vol,
            'direction': direction,
            'cooldown': cooldown,
            'hours': hours,
            'max_duration': 480,
            'atr_min': 0.25,
            'atr_max': 2.5,
        }
        
        trades = run_backtest(data_15m, data_1h, config, symbols_use)
        
        if len(trades) < 30:
            continue
        
        results = analyze_results(trades)
        
        if results is None:
            continue
        
        best_configs.append({
            'tp': tp,
            'sl': sl,
            'adx': adx,
            'vol': vol,
            'direction': direction,
            'cooldown': cooldown,
            'hours': 'ALL' if hours is None else f"{min(hours)}-{max(hours)}",
            'symbols': len(symbols_use),
            'symbol_names': symbols_use,
            **results
        })
    
    # Guardar resultados finales
    save_progress(total_combos, best_configs)
    
    # Ordenar
    best_configs.sort(key=lambda x: (x['positive_months'], x['total_pnl']), reverse=True)
    
    # ============================================================================
    # RESULTADOS
    # ============================================================================
    print("\n" + "=" * 100)
    print("🏆 TOP 20 CONFIGURACIONES POR MESES POSITIVOS")
    print("=" * 100)
    print(f"{'TP':>4} {'SL':>4} {'ADX':>4} {'Vol':>4} {'Dir':>6} {'CD':>4} {'Hours':>8} {'Sym':>4} {'Trades':>6} {'PnL':>9} {'WR':>5} {'+Mo':>4} {'Tot':>4}")
    print("-" * 100)
    
    for cfg in best_configs[:20]:
        print(f"{cfg['tp']*100:>3.0f}% {cfg['sl']*100:>3.1f}% {cfg['adx']:>4} {cfg['vol']:>4.1f} {cfg['direction']:>6} {cfg['cooldown']:>4} {cfg['hours']:>8} {cfg['symbols']:>4} {cfg['trades']:>6} ${cfg['total_pnl']:>7.0f} {cfg['win_rate']:>4.0f}% {cfg['positive_months']:>4}/{cfg['total_months']}")
    
    if best_configs:
        best = best_configs[0]
        print(f"""

═══════════════════════════════════════════════════════════════════════════════════════════════
🏆 MEJOR CONFIGURACIÓN ENCONTRADA
═══════════════════════════════════════════════════════════════════════════════════════════════

📊 PARÁMETROS:
   TP:              {best['tp']*100:.0f}%
   SL:              {best['sl']*100:.1f}%
   ADX mínimo:      {best['adx']}
   Volumen mínimo:  {best['vol']}x
   Dirección:       {best['direction']}
   Cooldown:        {best['cooldown']} min
   Horarios:        {best['hours']}
   Símbolos:        {best['symbol_names']}
   
📈 RESULTADOS:
   Total Trades:    {best['trades']}
   PnL Neto:        ${best['total_pnl']:.2f}
   Win Rate:        {best['win_rate']:.1f}%
   Max Drawdown:    ${best['max_dd']:.2f}
   Meses Positivos: {best['positive_months']}/{best['total_months']}

📅 DETALLE MENSUAL:
""")
        for month, pnl in best['monthly_detail'].items():
            icon = "✅" if pnl > 0 else "❌"
            print(f"   {month} {icon} ${pnl:>8.2f}")
        
        monthly_avg = best['total_pnl'] / best['total_months']
        print(f"""
💰 PROYECCIÓN CON $698:
   ROI Anual:       {(best['total_pnl']/698)*100:.1f}%
   ROI Mensual:     {(monthly_avg/698)*100:.1f}%

═══════════════════════════════════════════════════════════════════════════════════════════════
""")
    
    print(f"\n✅ Resultados guardados en: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
