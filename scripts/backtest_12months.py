#!/usr/bin/env python3
"""
BÚSQUEDA ULTRA-RÁPIDA - OBJETIVO: 12 MESES POSITIVOS
Guarda progreso cada 500 combinaciones
Usa Numba para máxima velocidad
"""

import pandas as pd
import numpy as np
import os
import json
import time
from numba import jit
import warnings
warnings.filterwarnings('ignore')

TAKER_FEE = 0.0005
SLIPPAGE = 0.0003
TOTAL_FEE = (TAKER_FEE + SLIPPAGE) * 2
FUNDING_RATE = 0.0001
EXPOSURE = 210

RESULTS_FILE = "data/backtest_12m_results.json"
PROGRESS_FILE = "data/backtest_12m_progress.json"

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
           'BNBUSDT', 'ADAUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT']

@jit(nopython=True, cache=True)
def calc_ema_fast(prices, period):
    n = len(prices)
    ema = np.empty(n)
    alpha = 2.0 / (period + 1)
    ema[0] = prices[0]
    for i in range(1, n):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
    return ema

@jit(nopython=True, cache=True)
def calc_rsi_fast(prices, period=14):
    n = len(prices)
    rsi = np.zeros(n)
    gains = np.zeros(n)
    losses = np.zeros(n)
    
    for i in range(1, n):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains[i] = diff
        else:
            losses[i] = -diff
    
    avg_gain = np.mean(gains[1:period+1])
    avg_loss = np.mean(losses[1:period+1])
    
    for i in range(period, n):
        avg_gain = (avg_gain * (period-1) + gains[i]) / period
        avg_loss = (avg_loss * (period-1) + losses[i]) / period
        if avg_loss > 0:
            rsi[i] = 100 - 100 / (1 + avg_gain / avg_loss)
        else:
            rsi[i] = 100
    return rsi

@jit(nopython=True, cache=True)
def calc_atr_fast(high, low, close, period=14):
    n = len(high)
    tr = np.zeros(n)
    atr = np.zeros(n)
    
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], 
                   abs(high[i] - close[i-1]), 
                   abs(low[i] - close[i-1]))
    
    atr[period-1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
    return atr

@jit(nopython=True, cache=True)
def calc_adx_fast(high, low, close, period=14):
    n = len(high)
    adx = np.zeros(n)
    
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    
    for i in range(1, n):
        up = high[i] - high[i-1]
        down = low[i-1] - low[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down
    
    atr = calc_atr_fast(high, low, close, period)
    
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    
    sum_plus = np.sum(plus_dm[1:period+1])
    sum_minus = np.sum(minus_dm[1:period+1])
    
    for i in range(period, n):
        sum_plus = sum_plus - sum_plus/period + plus_dm[i]
        sum_minus = sum_minus - sum_minus/period + minus_dm[i]
        
        if atr[i] > 0:
            plus_di[i] = 100 * sum_plus / period / atr[i]
            minus_di[i] = 100 * sum_minus / period / atr[i]
        
        if plus_di[i] + minus_di[i] > 0:
            dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i])
    
    adx[2*period-1] = np.mean(dx[period:2*period])
    for i in range(2*period, n):
        adx[i] = (adx[i-1] * (period-1) + dx[i]) / period
    
    return adx

@jit(nopython=True, cache=True)
def simulate_trades(opens, highs, lows, closes, hours, months,
                   ema9, ema21, ema50, rsi, adx, macd_line, macd_sig,
                   tp, sl, adx_min, direction, hour_start, hour_end,
                   rsi_long_min, rsi_long_max, rsi_short_min, rsi_short_max,
                   max_trades_day, cooldown_candles):
    
    n = len(closes)
    max_candles = 32
    
    month_pnl = np.zeros(50)
    month_ids = np.zeros(50, dtype=np.int32)
    n_months = 0
    
    trades = 0
    wins = 0
    total_pnl = 0.0
    max_dd = 0.0
    cumsum = 0.0
    peak = 0.0
    
    cooldown_until = 0
    current_day = -1
    trades_today = 0
    
    for i in range(250, n - max_candles - 5):
        if i < cooldown_until:
            continue
        
        day = i // 96
        if day != current_day:
            current_day = day
            trades_today = 0
        
        if trades_today >= max_trades_day:
            continue
        
        if adx[i] < adx_min:
            continue
        
        hour = hours[i]
        if hour_start <= hour_end:
            if hour < hour_start or hour > hour_end:
                continue
        else:
            if hour < hour_start and hour > hour_end:
                continue
        
        signal = 0
        
        if direction >= 0:
            if (ema9[i] > ema21[i] and closes[i] > ema50[i] and
                macd_line[i] > macd_sig[i] and
                rsi_long_min < rsi[i] < rsi_long_max):
                signal = 1
        
        if signal == 0 and direction <= 0:
            if (ema9[i] < ema21[i] and closes[i] < ema50[i] and
                macd_line[i] < macd_sig[i] and
                rsi_short_min < rsi[i] < rsi_short_max):
                signal = -1
        
        if signal == 0:
            continue
        
        entry_idx = i + 1
        entry_price = opens[entry_idx]
        
        if signal == 1:
            tp_price = entry_price * (1 + tp)
            sl_price = entry_price * (1 - sl)
        else:
            tp_price = entry_price * (1 - tp)
            sl_price = entry_price * (1 + sl)
        
        pnl_pct = 0.0
        exit_idx = entry_idx
        
        for j in range(entry_idx + 1, min(entry_idx + max_candles, n)):
            if signal == 1:
                if lows[j] <= sl_price:
                    pnl_pct = -sl
                    exit_idx = j
                    break
                if highs[j] >= tp_price:
                    pnl_pct = tp
                    exit_idx = j
                    break
            else:
                if highs[j] >= sl_price:
                    pnl_pct = -sl
                    exit_idx = j
                    break
                if lows[j] <= tp_price:
                    pnl_pct = tp
                    exit_idx = j
                    break
        else:
            exit_idx = min(entry_idx + max_candles - 1, n - 1)
            if signal == 1:
                pnl_pct = (closes[exit_idx] - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - closes[exit_idx]) / entry_price
        
        duration_h = (exit_idx - entry_idx) * 0.25
        funding = int(duration_h / 8) * FUNDING_RATE
        net_pnl = EXPOSURE * (pnl_pct - TOTAL_FEE - funding)
        
        trades += 1
        total_pnl += net_pnl
        if net_pnl > 0:
            wins += 1
        
        cumsum += net_pnl
        if cumsum > peak:
            peak = cumsum
        dd = cumsum - peak
        if dd < max_dd:
            max_dd = dd
        
        month_id = months[entry_idx]
        found = False
        for m in range(n_months):
            if month_ids[m] == month_id:
                month_pnl[m] += net_pnl
                found = True
                break
        if not found and n_months < 50:
            month_ids[n_months] = month_id
            month_pnl[n_months] = net_pnl
            n_months += 1
        
        trades_today += 1
        cooldown_until = exit_idx + cooldown_candles
    
    pos_months = 0
    for m in range(n_months):
        if month_pnl[m] > 0:
            pos_months += 1
    
    wr = 0.0
    if trades > 0:
        wr = 100.0 * wins / trades
    
    return trades, total_pnl, wr, max_dd, pos_months, n_months, month_pnl[:n_months], month_ids[:n_months]


def prepare_data(symbol):
    path_15m = f"data/historical/{symbol}_15m_full.csv"
    if not os.path.exists(path_15m):
        path_15m = f"data/historical/{symbol}_15m.csv"
    if not os.path.exists(path_15m):
        return None
    
    df = pd.read_csv(path_15m)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    close = df['close'].values.astype(np.float64)
    high = df['high'].values.astype(np.float64)
    low = df['low'].values.astype(np.float64)
    opens = df['open'].values.astype(np.float64)
    
    ema9 = calc_ema_fast(close, 9)
    ema21 = calc_ema_fast(close, 21)
    ema50 = calc_ema_fast(close, 50)
    rsi = calc_rsi_fast(close, 14)
    adx = calc_adx_fast(high, low, close, 14)
    
    ema12 = calc_ema_fast(close, 12)
    ema26 = calc_ema_fast(close, 26)
    macd_line = ema12 - ema26
    macd_sig = calc_ema_fast(macd_line, 9)
    
    hours = df['timestamp'].dt.hour.values.astype(np.int32)
    months = (df['timestamp'].dt.year * 100 + df['timestamp'].dt.month).values.astype(np.int32)
    
    return {
        'opens': opens, 'highs': high, 'lows': low, 'closes': close,
        'hours': hours, 'months': months,
        'ema9': ema9, 'ema21': ema21, 'ema50': ema50,
        'rsi': rsi, 'adx': adx, 'macd_line': macd_line, 'macd_sig': macd_sig,
        'n': len(df)
    }


def main():
    print("=" * 70)
    print("🚀 BÚSQUEDA ULTRA-RÁPIDA - OBJETIVO: 12 MESES POSITIVOS")
    print("=" * 70)
    
    completed = set()
    best_results = []
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
            completed = set(progress.get('completed', []))
            print(f"   📂 Retomando desde {len(completed)} combinaciones")
    
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            best_results = json.load(f)
            print(f"   📊 {len(best_results)} resultados previos")
    
    print("\n📊 Preparando datos...")
    all_data = {}
    for symbol in SYMBOLS:
        data = prepare_data(symbol)
        if data is not None:
            all_data[symbol] = data
            print(f"   ✅ {symbol}: {data['n']:,} velas")
    
    configs = []
    
    for tp in [0.02, 0.025, 0.03, 0.04, 0.05, 0.06, 0.08]:
        for sl in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04]:
            if tp / sl < 1.3:
                continue
            for adx_min in [15, 20, 25, 30]:
                for direction in [0, 1, -1]:
                    for hour_start, hour_end in [(0, 23), (6, 18), (8, 20), (12, 22), (14, 20)]:
                        for rsi_long_min, rsi_long_max in [(30, 75), (35, 70), (40, 65)]:
                            for rsi_short_min, rsi_short_max in [(25, 60), (30, 55), (35, 50)]:
                                for max_trades in [1, 2, 3, 5]:
                                    for cooldown in [4, 8, 12]:
                                        for sym_set in [SYMBOLS, ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'], ['BTCUSDT'], ['ETHUSDT']]:
                                            cfg_id = f"{tp}_{sl}_{adx_min}_{direction}_{hour_start}_{hour_end}_{rsi_long_min}_{rsi_long_max}_{rsi_short_min}_{rsi_short_max}_{max_trades}_{cooldown}_{len(sym_set)}"
                                            if cfg_id not in completed:
                                                configs.append({
                                                    'id': cfg_id,
                                                    'tp': tp, 'sl': sl, 'adx_min': adx_min,
                                                    'direction': direction,
                                                    'hour_start': hour_start, 'hour_end': hour_end,
                                                    'rsi_long_min': rsi_long_min, 'rsi_long_max': rsi_long_max,
                                                    'rsi_short_min': rsi_short_min, 'rsi_short_max': rsi_short_max,
                                                    'max_trades': max_trades, 'cooldown': cooldown,
                                                    'symbols': sym_set
                                                })
    
    print(f"\n🔬 {len(configs):,} combinaciones pendientes")
    
    start_time = time.time()
    tested = 0
    new_completed = []
    
    for cfg in configs:
        tested += 1
        
        total_trades = 0
        total_pnl = 0.0
        total_wins = 0
        all_months = {}
        worst_dd = 0.0
        
        for symbol in cfg['symbols']:
            if symbol not in all_data:
                continue
            
            d = all_data[symbol]
            trades, pnl, wr, dd, pos_m, n_m, m_pnl, m_ids = simulate_trades(
                d['opens'], d['highs'], d['lows'], d['closes'],
                d['hours'], d['months'],
                d['ema9'], d['ema21'], d['ema50'], d['rsi'], d['adx'],
                d['macd_line'], d['macd_sig'],
                cfg['tp'], cfg['sl'], cfg['adx_min'], cfg['direction'],
                cfg['hour_start'], cfg['hour_end'],
                cfg['rsi_long_min'], cfg['rsi_long_max'],
                cfg['rsi_short_min'], cfg['rsi_short_max'],
                cfg['max_trades'], cfg['cooldown']
            )
            
            total_trades += trades
            total_pnl += pnl
            total_wins += int(trades * wr / 100)
            if dd < worst_dd:
                worst_dd = dd
            
            for i in range(len(m_pnl)):
                mid = int(m_ids[i])
                if mid not in all_months:
                    all_months[mid] = 0
                all_months[mid] += m_pnl[i]
        
        if total_trades < 20:
            new_completed.append(cfg['id'])
            continue
        
        pos_months = sum(1 for v in all_months.values() if v > 0)
        total_months = len(all_months)
        wr = 100 * total_wins / total_trades if total_trades > 0 else 0
        
        if pos_months >= 8:
            dir_str = 'BOTH' if cfg['direction'] == 0 else ('LONG' if cfg['direction'] == 1 else 'SHORT')
            result = {
                'tp': cfg['tp'], 'sl': cfg['sl'], 'adx': cfg['adx_min'],
                'dir': dir_str, 'hours': f"{cfg['hour_start']}-{cfg['hour_end']}",
                'rsi': f"L{cfg['rsi_long_min']}-{cfg['rsi_long_max']}/S{cfg['rsi_short_min']}-{cfg['rsi_short_max']}",
                'max_td': cfg['max_trades'], 'cd': cfg['cooldown'],
                'symbols': len(cfg['symbols']),
                'trades': total_trades, 'pnl': round(total_pnl, 2),
                'wr': round(wr, 1), 'dd': round(worst_dd, 2),
                'pos': pos_months, 'total': total_months,
                'monthly': {str(k): round(v, 2) for k, v in sorted(all_months.items())}
            }
            best_results.append(result)
        
        new_completed.append(cfg['id'])
        
        if tested % 500 == 0:
            elapsed = time.time() - start_time
            speed = tested / elapsed
            best_pos = max([r['pos'] for r in best_results]) if best_results else 0
            
            best_results.sort(key=lambda x: (x['pos'], x['pnl']), reverse=True)
            best_results = best_results[:300]
            
            with open(RESULTS_FILE, 'w') as f:
                json.dump(best_results, f, indent=2)
            
            all_completed = list(completed) + new_completed
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({'completed': all_completed, 'tested': len(all_completed)}, f)
            
            print(f"   {tested:,} probadas | {speed:.0f}/s | "
                  f"Mejor: {best_pos} meses | Top: {len(best_results)} | 💾 Guardado")
    
    best_results.sort(key=lambda x: (x['pos'], x['pnl']), reverse=True)
    with open(RESULTS_FILE, 'w') as f:
        json.dump(best_results[:200], f, indent=2)
    
    all_completed = list(completed) + new_completed
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({'completed': all_completed, 'tested': len(all_completed)}, f)
    
    print("\n" + "=" * 70)
    print("🏆 TOP 20 CONFIGURACIONES")
    print("=" * 70)
    
    for i, r in enumerate(best_results[:20]):
        print(f"{i+1:2}. {r['pos']:2}/{r['total']} meses | "
              f"TP {r['tp']*100:.0f}% SL {r['sl']*100:.1f}% | "
              f"${r['pnl']:>7.0f} | WR {r['wr']:.0f}% | "
              f"{r['dir']:5} | {r['hours']}")
    
    if best_results:
        best = best_results[0]
        print(f"\n{'='*70}")
        print(f"🏆 MEJOR: {best['pos']}/{best['total']} MESES POSITIVOS")
        print(f"{'='*70}")
        print(f"   TP: {best['tp']*100:.0f}%  SL: {best['sl']*100:.1f}%")
        print(f"   ADX: {best['adx']}  Dir: {best['dir']}")
        print(f"   Hours: {best['hours']}  RSI: {best['rsi']}")
        print(f"   Trades: {best['trades']}  PnL: ${best['pnl']:.2f}")
        print(f"\n📅 Mensual:")
        for m, p in best['monthly'].items():
            icon = "✅" if p > 0 else "❌"
            print(f"   {m}: {icon} ${p:>8.2f}")
    
    print(f"\n⏱️ Tiempo: {(time.time() - start_time)/60:.1f} min")
    print(f"💾 Guardado en: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
