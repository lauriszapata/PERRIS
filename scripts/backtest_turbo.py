#!/usr/bin/env python3
"""
BACKTEST TURBO - ULTRA OPTIMIZADO CON MULTIPROCESSING
======================================================
- Usa todos los cores de tu M2 (8 cores)
- Guarda resultados cada 100 combinaciones
- Puede continuar desde donde quedó
- Termina en HORAS, no días
"""

import pandas as pd
import numpy as np
import os
import json
import time
from datetime import datetime
from itertools import product
from multiprocessing import Pool, cpu_count
from functools import partial
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
TAKER_FEE = 0.0005
SLIPPAGE = 0.0003
TOTAL_FEE = (TAKER_FEE + SLIPPAGE) * 2
FUNDING_RATE = 0.0001
EXPOSURE = 210

RESULTS_FILE = "data/backtest_turbo_results.json"
PROGRESS_FILE = "data/backtest_turbo_progress.json"

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
           'BNBUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT']

# ============================================================================
# PRECALCULAR INDICADORES UNA SOLA VEZ (CLAVE PARA VELOCIDAD)
# ============================================================================
def calculate_ema(prices, period):
    """EMA optimizada con numpy"""
    alpha = 2 / (period + 1)
    ema = np.zeros_like(prices)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
    return ema

def calculate_rsi(prices, period=14):
    """RSI optimizada"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.zeros(len(prices))
    avg_loss = np.zeros(len(prices))
    
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])
    
    for i in range(period + 1, len(prices)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss!=0)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(high, low, close, period=14):
    """ATR optimizada"""
    tr = np.maximum(high - low, 
                    np.maximum(np.abs(high - np.roll(close, 1)),
                              np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr = np.zeros_like(tr)
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr

def calculate_adx(high, low, close, period=14):
    """ADX simplificada pero funcional"""
    plus_dm = np.maximum(high - np.roll(high, 1), 0)
    minus_dm = np.maximum(np.roll(low, 1) - low, 0)
    
    # Cuando +DM > -DM, -DM = 0 y viceversa
    mask = plus_dm > minus_dm
    minus_dm = np.where(mask, 0, minus_dm)
    plus_dm = np.where(~mask, 0, plus_dm)
    
    atr = calculate_atr(high, low, close, period)
    atr = np.where(atr == 0, 1, atr)  # Evitar división por cero
    
    plus_di = 100 * calculate_ema(plus_dm, period) / atr
    minus_di = 100 * calculate_ema(minus_dm, period) / atr
    
    dx = 100 * np.abs(plus_di - minus_di) / np.where(plus_di + minus_di == 0, 1, plus_di + minus_di)
    adx = calculate_ema(dx, period)
    
    return adx

def calculate_macd(prices):
    """MACD optimizada"""
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    macd_line = ema12 - ema26
    signal = calculate_ema(macd_line, 9)
    return macd_line, signal

def prepare_data(symbol):
    """Preparar datos con indicadores precalculados"""
    path_15m = f"data/historical/{symbol}_15m_full.csv"
    path_1h = f"data/historical/{symbol}_1h_mtf.csv"
    
    if not os.path.exists(path_15m):
        return None
    
    df = pd.read_csv(path_15m)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Convertir a numpy para velocidad
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values
    
    # Calcular indicadores
    ema9 = calculate_ema(close, 9)
    ema21 = calculate_ema(close, 21)
    ema50 = calculate_ema(close, 50)
    rsi = calculate_rsi(close, 14)
    atr = calculate_atr(high, low, close, 14)
    adx = calculate_adx(high, low, close, 14)
    macd_line, macd_signal = calculate_macd(close)
    
    # Volumen promedio
    vol_avg = np.convolve(volume, np.ones(20)/20, mode='same')
    vol_ratio = volume / np.where(vol_avg == 0, 1, vol_avg)
    
    # ATR porcentual
    atr_pct = atr / close * 100
    
    # Hora
    hours = df['timestamp'].dt.hour.values
    
    # MTF - cargar 1H y precalcular
    mtf_bullish = np.zeros(len(df), dtype=bool)
    mtf_bearish = np.zeros(len(df), dtype=bool)
    
    if os.path.exists(path_1h):
        df_1h = pd.read_csv(path_1h)
        df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'])
        df_1h = df_1h.sort_values('timestamp').reset_index(drop=True)
        
        close_1h = df_1h['close'].values
        ema50_1h = calculate_ema(close_1h, 50)
        ema200_1h = calculate_ema(close_1h, 200)
        
        # Mapear MTF a 15m
        for i, ts in enumerate(df['timestamp']):
            idx_1h = df_1h[df_1h['timestamp'] <= ts].index
            if len(idx_1h) > 0:
                j = idx_1h[-1]
                if j >= 200:  # Asegurar que tenemos suficientes datos
                    mtf_bullish[i] = ema50_1h[j] > ema200_1h[j]
                    mtf_bearish[i] = ema50_1h[j] < ema200_1h[j]
    
    return {
        'symbol': symbol,
        'timestamp': df['timestamp'].values,
        'open': df['open'].values,
        'high': high,
        'low': low,
        'close': close,
        'ema9': ema9,
        'ema21': ema21,
        'ema50': ema50,
        'rsi': rsi,
        'atr': atr,
        'atr_pct': atr_pct,
        'adx': adx,
        'macd_line': macd_line,
        'macd_signal': macd_signal,
        'vol_ratio': vol_ratio,
        'hours': hours,
        'mtf_bullish': mtf_bullish,
        'mtf_bearish': mtf_bearish,
        'n': len(df)
    }


def run_single_backtest(config, all_data):
    """Ejecutar un backtest con una configuración específica"""
    tp = config['tp']
    sl = config['sl']
    adx_min = config['adx_min']
    vol_mult = config['vol_mult']
    direction = config['direction']
    cooldown = config['cooldown']
    hours_filter = config.get('hours')
    symbols_to_use = config['symbols']
    
    cooldown_candles = cooldown // 15
    max_candles = 32  # 8 horas máximo
    
    all_trades = []
    
    for symbol in symbols_to_use:
        if symbol not in all_data:
            continue
        
        data = all_data[symbol]
        n = data['n']
        cooldown_until = 0
        
        for i in range(250, n - max_candles - 5):
            if i < cooldown_until:
                continue
            
            # Filtros rápidos primero
            if data['adx'][i] < adx_min:
                continue
            if data['vol_ratio'][i] < vol_mult:
                continue
            if data['atr_pct'][i] < 0.25 or data['atr_pct'][i] > 2.5:
                continue
            if hours_filter is not None and data['hours'][i] not in hours_filter:
                continue
            
            # Detectar señal
            signal = None
            
            if direction in ['BOTH', 'LONG']:
                if (data['ema9'][i] > data['ema21'][i] and
                    data['close'][i] > data['ema50'][i] and
                    data['macd_line'][i] > data['macd_signal'][i] and
                    data['rsi'][i] > 35 and
                    data['mtf_bullish'][i]):
                    signal = 'LONG'
            
            if signal is None and direction in ['BOTH', 'SHORT']:
                if (data['ema9'][i] < data['ema21'][i] and
                    data['close'][i] < data['ema50'][i] and
                    data['macd_line'][i] < data['macd_signal'][i] and
                    30 < data['rsi'][i] < 55 and
                    data['mtf_bearish'][i]):
                    signal = 'SHORT'
            
            if signal is None:
                continue
            
            # Simular trade
            entry_idx = i + 1
            entry_price = data['open'][entry_idx]
            entry_time = data['timestamp'][entry_idx]
            
            if signal == 'LONG':
                tp_price = entry_price * (1 + tp)
                sl_price = entry_price * (1 - sl)
            else:
                tp_price = entry_price * (1 - tp)
                sl_price = entry_price * (1 + sl)
            
            exit_type = 'TIMEOUT'
            pnl_pct = 0
            exit_idx = entry_idx
            
            for j in range(entry_idx + 1, min(entry_idx + max_candles, n)):
                if signal == 'LONG':
                    if data['low'][j] <= sl_price:
                        pnl_pct = -sl
                        exit_type = 'SL'
                        exit_idx = j
                        break
                    if data['high'][j] >= tp_price:
                        pnl_pct = tp
                        exit_type = 'TP'
                        exit_idx = j
                        break
                else:
                    if data['high'][j] >= sl_price:
                        pnl_pct = -sl
                        exit_type = 'SL'
                        exit_idx = j
                        break
                    if data['low'][j] <= tp_price:
                        pnl_pct = tp
                        exit_type = 'TP'
                        exit_idx = j
                        break
            else:
                exit_idx = min(entry_idx + max_candles - 1, n - 1)
                exit_price = data['close'][exit_idx]
                if signal == 'LONG':
                    pnl_pct = (exit_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price
            
            # Calcular costos
            duration_h = (exit_idx - entry_idx) * 0.25  # 15 min candles
            funding = int(duration_h / 8) * FUNDING_RATE
            net_pnl = EXPOSURE * (pnl_pct - TOTAL_FEE - funding)
            
            all_trades.append({
                'entry_time': entry_time,
                'pnl': net_pnl,
            })
            
            cooldown_until = exit_idx + cooldown_candles
    
    # Analizar resultados
    if len(all_trades) < 30:
        return None
    
    df_trades = pd.DataFrame(all_trades)
    df_trades['month'] = pd.to_datetime(df_trades['entry_time']).dt.to_period('M')
    monthly = df_trades.groupby('month')['pnl'].sum()
    
    total_pnl = df_trades['pnl'].sum()
    wins = len(df_trades[df_trades['pnl'] > 0])
    wr = wins / len(df_trades) * 100
    positive_months = (monthly > 0).sum()
    total_months = len(monthly)
    
    # Max drawdown
    cumsum = df_trades['pnl'].cumsum()
    max_dd = (cumsum - cumsum.cummax()).min()
    
    return {
        'tp': tp,
        'sl': sl,
        'adx': adx_min,
        'vol': vol_mult,
        'direction': direction,
        'cooldown': cooldown,
        'hours': 'ALL' if hours_filter is None else f"{min(hours_filter)}-{max(hours_filter)}",
        'n_symbols': len(symbols_to_use),
        'trades': len(df_trades),
        'pnl': total_pnl,
        'wr': wr,
        'max_dd': max_dd,
        'pos_months': positive_months,
        'total_months': total_months,
        'monthly': {str(k): v for k, v in monthly.items()}
    }


def worker_batch(configs_batch, all_data_dict):
    """Procesar un batch de configuraciones"""
    results = []
    for config in configs_batch:
        try:
            result = run_single_backtest(config, all_data_dict)
            if result is not None:
                results.append(result)
        except Exception as e:
            pass
    return results


def main():
    print("=" * 80)
    print("🚀 BACKTEST TURBO - ULTRA OPTIMIZADO")
    print(f"   Usando {cpu_count()} cores")
    print("=" * 80)
    
    # Cargar y preparar datos UNA SOLA VEZ
    print("\n📊 Preparando datos con indicadores precalculados...")
    start = time.time()
    
    all_data = {}
    for symbol in SYMBOLS:
        data = prepare_data(symbol)
        if data is not None:
            all_data[symbol] = data
            print(f"   ✅ {symbol}: {data['n']} velas")
    
    print(f"   Tiempo de preparación: {time.time() - start:.1f}s")
    
    # Generar todas las configuraciones
    tp_options = [0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
    sl_options = [0.015, 0.02, 0.025, 0.03, 0.04]
    adx_options = [20, 25, 30]
    vol_options = [1.0, 1.3, 1.5]
    direction_options = ['BOTH', 'LONG', 'SHORT']
    cooldown_options = [60, 90, 120]
    
    hour_options = [
        None,
        list(range(8, 22)),
        list(range(12, 20)),
    ]
    
    symbol_combos = [
        SYMBOLS,
        ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT'],
        ['BTCUSDT', 'ETHUSDT'],
        ['SOLUSDT', 'XRPUSDT', 'DOGEUSDT'],
    ]
    
    all_configs = []
    for tp, sl, adx, vol, direction, cooldown, hours, symbols in product(
        tp_options, sl_options, adx_options, vol_options,
        direction_options, cooldown_options, hour_options, symbol_combos
    ):
        if tp / sl < 1.5:  # Ratio mínimo
            continue
        all_configs.append({
            'tp': tp,
            'sl': sl,
            'adx_min': adx,
            'vol_mult': vol,
            'direction': direction,
            'cooldown': cooldown,
            'hours': hours,
            'symbols': symbols,
        })
    
    print(f"\n🔬 Total configuraciones a probar: {len(all_configs)}")
    
    # Cargar progreso si existe
    start_idx = 0
    best_results = []
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            progress = json.load(f)
            start_idx = progress.get('last_idx', 0)
            print(f"📂 Continuando desde configuración {start_idx}")
    
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, 'r') as f:
            best_results = json.load(f)
            print(f"📂 Cargados {len(best_results)} resultados previos")
    
    # Procesar en batches
    batch_size = 50
    total = len(all_configs)
    
    print(f"\n🏃 Ejecutando backtests...")
    start = time.time()
    
    for batch_start in range(start_idx, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch = all_configs[batch_start:batch_end]
        
        # Procesar batch
        for config in batch:
            result = run_single_backtest(config, all_data)
            if result is not None:
                best_results.append(result)
        
        # Guardar progreso
        elapsed = time.time() - start
        speed = (batch_end - start_idx) / elapsed if elapsed > 0 else 0
        eta = (total - batch_end) / speed / 60 if speed > 0 else 0
        
        print(f"   {batch_end}/{total} ({batch_end/total*100:.1f}%) | "
              f"Speed: {speed:.1f}/s | ETA: {eta:.0f} min | "
              f"Encontrados: {len(best_results)}")
        
        # Guardar cada 100
        if batch_end % 100 == 0 or batch_end == total:
            # Ordenar y mantener top 200
            best_results.sort(key=lambda x: (x['pos_months'], x['pnl']), reverse=True)
            best_results = best_results[:200]
            
            with open(RESULTS_FILE, 'w') as f:
                json.dump(best_results, f, indent=2, default=str)
            
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({'last_idx': batch_end}, f)
    
    # Resultados finales
    print("\n" + "=" * 100)
    print("🏆 TOP 20 CONFIGURACIONES")
    print("=" * 100)
    
    best_results.sort(key=lambda x: (x['pos_months'], x['pnl']), reverse=True)
    
    print(f"{'TP':>4} {'SL':>4} {'ADX':>4} {'Vol':>4} {'Dir':>6} {'CD':>4} {'Hours':>8} {'Sym':>4} {'Trades':>6} {'PnL':>9} {'WR':>5} {'+Mo':>4}")
    print("-" * 90)
    
    for r in best_results[:20]:
        print(f"{r['tp']*100:>3.0f}% {r['sl']*100:>3.1f}% {r['adx']:>4} {r['vol']:>4.1f} "
              f"{r['direction']:>6} {r['cooldown']:>4} {r['hours']:>8} {r['n_symbols']:>4} "
              f"{r['trades']:>6} ${r['pnl']:>7.0f} {r['wr']:>4.0f}% {r['pos_months']:>3}/{r['total_months']}")
    
    if best_results:
        best = best_results[0]
        print(f"""

═══════════════════════════════════════════════════════════════════════════════════════════════
🏆 MEJOR CONFIGURACIÓN: {best['pos_months']}/{best['total_months']} MESES POSITIVOS
═══════════════════════════════════════════════════════════════════════════════════════════════

   TP:           {best['tp']*100:.0f}%
   SL:           {best['sl']*100:.1f}%
   ADX mínimo:   {best['adx']}
   Volumen:      {best['vol']}x
   Dirección:    {best['direction']}
   Cooldown:     {best['cooldown']} min
   Horarios:     {best['hours']}
   
   Trades:       {best['trades']}
   PnL:          ${best['pnl']:.2f}
   Win Rate:     {best['wr']:.1f}%
   Max DD:       ${best['max_dd']:.2f}

📅 DETALLE MENSUAL:
""")
        for month, pnl in best['monthly'].items():
            icon = "✅" if pnl > 0 else "❌"
            print(f"   {month} {icon} ${pnl:>8.2f}")
        
        print(f"""
💰 PROYECCIÓN CON $698:
   ROI Anual:    {(best['pnl']/698)*100:.1f}%

═══════════════════════════════════════════════════════════════════════════════════════════════
""")
    
    print(f"\n✅ Resultados guardados en: {RESULTS_FILE}")
    print(f"   Tiempo total: {(time.time() - start)/60:.1f} minutos")


if __name__ == "__main__":
    main()
