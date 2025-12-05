#!/usr/bin/env python3
"""
Backtest para la configuración CONSERVADORA
- 4 símbolos: SOL, LINK, AVAX, ARB
- TP 4% / SL 2%
- Exposición $210 (30%)
- Breakeven a 1.2%
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime
import os
import sys

# Añadir path del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configuración actual del bot
CONFIG = {
    "symbols": ["SOLUSDT", "LINKUSDT", "AVAXUSDT", "ARBUSDT"],
    "exposure": 210,      # $210 (30% de $698)
    "tp_pct": 0.04,       # 4%
    "sl_pct": 0.02,       # 2%
    "leverage": 3,
    "commission": 0.0005, # 0.05%
    "breakeven_pct": 0.012,  # 1.2%
    "adx_min": 20,
    "cooldown_minutes": 30,
    "max_duration_minutes": 480,  # 8 horas
}


def load_data(symbol):
    """Cargar datos históricos"""
    path = f"data/historical/{symbol}_15m.csv"
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def calculate_indicators(df):
    """Calcular todos los indicadores"""
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['MACD_line'] = macd['MACD_12_26_9']
    df['MACD_signal'] = macd['MACDs_12_26_9']
    
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14']
    
    df['vol_avg'] = df['volume'].rolling(20).mean()
    return df


def check_long_signal(row):
    """Verificar señal LONG"""
    if pd.isna(row['EMA50']) or pd.isna(row['ADX']):
        return False
    
    trend = row['EMA9'] > row['EMA21'] > row['EMA50']
    adx_ok = row['ADX'] >= CONFIG['adx_min']
    rsi_ok = row['RSI'] > 35
    macd_ok = row['MACD_line'] > row['MACD_signal']
    volume_ok = row['volume'] >= row['vol_avg']
    
    return trend and adx_ok and rsi_ok and macd_ok and volume_ok


def check_short_signal(row):
    """Verificar señal SHORT"""
    if pd.isna(row['EMA50']) or pd.isna(row['ADX']):
        return False
    
    trend = row['EMA9'] < row['EMA21'] < row['EMA50']
    adx_ok = row['ADX'] >= CONFIG['adx_min']
    rsi_ok = 30 < row['RSI'] < 55
    macd_ok = row['MACD_line'] < row['MACD_signal']
    volume_ok = row['volume'] >= row['vol_avg']
    
    return trend and adx_ok and rsi_ok and macd_ok and volume_ok


def simulate_trade(df, entry_idx, direction, entry_price):
    """Simular un trade con TP/SL/Breakeven"""
    if direction == "LONG":
        tp_price = entry_price * (1 + CONFIG['tp_pct'])
        sl_price = entry_price * (1 - CONFIG['sl_pct'])
        be_trigger = entry_price * (1 + CONFIG['breakeven_pct'])
    else:
        tp_price = entry_price * (1 - CONFIG['tp_pct'])
        sl_price = entry_price * (1 + CONFIG['sl_pct'])
        be_trigger = entry_price * (1 - CONFIG['breakeven_pct'])
    
    be_activated = False
    max_candles = CONFIG['max_duration_minutes'] // 15  # 480 / 15 = 32 velas
    
    for i in range(entry_idx + 1, min(entry_idx + max_candles, len(df))):
        candle = df.iloc[i]
        high, low = candle['high'], candle['low']
        
        if direction == "LONG":
            # Check breakeven trigger
            if not be_activated and high >= be_trigger:
                be_activated = True
                sl_price = entry_price * 1.001  # Move SL to BE + buffer
            
            # Check TP hit
            if high >= tp_price:
                return i, "TP", CONFIG['tp_pct'], i - entry_idx
            
            # Check SL hit
            if low <= sl_price:
                if be_activated:
                    return i, "BE", 0.001, i - entry_idx
                return i, "SL", -CONFIG['sl_pct'], i - entry_idx
        else:  # SHORT
            # Check breakeven trigger
            if not be_activated and low <= be_trigger:
                be_activated = True
                sl_price = entry_price * 0.999
            
            # Check TP hit
            if low <= tp_price:
                return i, "TP", CONFIG['tp_pct'], i - entry_idx
            
            # Check SL hit
            if high >= sl_price:
                if be_activated:
                    return i, "BE", 0.001, i - entry_idx
                return i, "SL", -CONFIG['sl_pct'], i - entry_idx
    
    # Max duration reached
    final_close = df.iloc[min(entry_idx + max_candles - 1, len(df) - 1)]['close']
    if direction == "LONG":
        pnl_pct = (final_close - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - final_close) / entry_price
    
    return min(entry_idx + max_candles - 1, len(df) - 1), "TIMEOUT", pnl_pct, max_candles


def run_backtest():
    """Ejecutar backtest para todos los símbolos"""
    all_trades = []
    
    for symbol in CONFIG['symbols']:
        print(f"\n📊 Backtesting {symbol}...")
        df = load_data(symbol)
        
        if df is None:
            print(f"   ❌ No data found for {symbol}")
            continue
        
        df = calculate_indicators(df)
        
        # Filter to 2025 data
        df = df[df['timestamp'] >= '2025-01-01'].reset_index(drop=True)
        
        if len(df) < 100:
            print(f"   ❌ Insufficient data for {symbol}")
            continue
        
        print(f"   📅 Data: {df['timestamp'].iloc[0].date()} to {df['timestamp'].iloc[-1].date()}")
        print(f"   📈 Candles: {len(df)}")
        
        cooldown_until = 0
        symbol_trades = 0
        
        for i in range(60, len(df) - 50):
            if i < cooldown_until:
                continue
            
            row = df.iloc[i]
            
            # Check signals
            long_signal = check_long_signal(row)
            short_signal = check_short_signal(row)
            
            if not long_signal and not short_signal:
                continue
            
            direction = "LONG" if long_signal else "SHORT"
            entry_price = row['close']
            
            # Simulate trade
            exit_idx, exit_type, pnl_pct, duration = simulate_trade(df, i, direction, entry_price)
            
            # Calculate PnL with commission
            commission = CONFIG['commission'] * 2  # Entry + Exit
            net_pnl_pct = pnl_pct - commission
            pnl_usd = CONFIG['exposure'] * net_pnl_pct
            
            all_trades.append({
                'symbol': symbol,
                'entry_time': row['timestamp'],
                'direction': direction,
                'entry_price': entry_price,
                'exit_type': exit_type,
                'pnl_pct': net_pnl_pct,
                'pnl_usd': pnl_usd,
                'duration_candles': duration,
            })
            
            symbol_trades += 1
            
            # Set cooldown
            cooldown_candles = CONFIG['cooldown_minutes'] // 15
            cooldown_until = exit_idx + cooldown_candles
        
        print(f"   ✅ Trades: {symbol_trades}")
    
    return all_trades


def main():
    print("=" * 70)
    print("🔬 BACKTEST: CONFIGURACIÓN CONSERVADORA")
    print("=" * 70)
    print(f"""
📊 Parámetros:
   Símbolos:    {', '.join(CONFIG['symbols'])}
   Exposición:  ${CONFIG['exposure']}
   TP:          {CONFIG['tp_pct']*100}%
   SL:          {CONFIG['sl_pct']*100}%
   Ratio:       {CONFIG['tp_pct']/CONFIG['sl_pct']}:1
   Leverage:    {CONFIG['leverage']}x
   Breakeven:   {CONFIG['breakeven_pct']*100}%
""")
    
    # Run backtest
    trades = run_backtest()
    
    # Results
    print("\n" + "=" * 70)
    print("📊 RESULTADOS DEL BACKTEST")
    print("=" * 70)
    
    if not trades:
        print("❌ No trades generated")
        return
    
    df_trades = pd.DataFrame(trades)
    
    # Overall stats
    total_trades = len(df_trades)
    wins = len(df_trades[df_trades['pnl_usd'] > 0])
    losses = len(df_trades[df_trades['pnl_usd'] < 0])
    
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    total_pnl = df_trades['pnl_usd'].sum()
    avg_win = df_trades[df_trades['pnl_usd'] > 0]['pnl_usd'].mean() if wins > 0 else 0
    avg_loss = df_trades[df_trades['pnl_usd'] < 0]['pnl_usd'].mean() if losses > 0 else 0
    
    # Max drawdown
    cumulative = df_trades['pnl_usd'].cumsum()
    running_max = cumulative.cummax()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()
    
    # Streaks
    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    
    for pnl in df_trades['pnl_usd']:
        if pnl > 0:
            if current_streak > 0:
                current_streak += 1
            else:
                current_streak = 1
            max_win_streak = max(max_win_streak, current_streak)
        elif pnl < 0:
            if current_streak < 0:
                current_streak -= 1
            else:
                current_streak = -1
            max_loss_streak = min(max_loss_streak, current_streak)
    
    print(f"""
📈 RESUMEN GENERAL:
─────────────────────────────────────────────────────────────────────
  Total Trades:      {total_trades}
  Wins:              {wins} ({win_rate:.1f}%)
  Losses:            {losses}
  
💰 RENTABILIDAD:
─────────────────────────────────────────────────────────────────────
  PnL Total:         ${total_pnl:.2f}
  Promedio Win:      ${avg_win:.2f}
  Promedio Loss:     ${avg_loss:.2f}
  Max Drawdown:      ${max_dd:.2f}
  
📊 RACHAS:
─────────────────────────────────────────────────────────────────────
  Mayor racha wins:  {max_win_streak}
  Mayor racha losses:{abs(max_loss_streak)}

📋 POR TIPO DE SALIDA:
─────────────────────────────────────────────────────────────────────""")
    
    for exit_type in ['TP', 'SL', 'BE', 'TIMEOUT']:
        subset = df_trades[df_trades['exit_type'] == exit_type]
        if len(subset) > 0:
            print(f"  {exit_type:8} → {len(subset):3} trades | ${subset['pnl_usd'].sum():>8.2f} | Avg: ${subset['pnl_usd'].mean():>6.2f}")
    
    print(f"""
📋 POR SÍMBOLO:
─────────────────────────────────────────────────────────────────────""")
    
    for symbol in CONFIG['symbols']:
        subset = df_trades[df_trades['symbol'] == symbol]
        if len(subset) > 0:
            wr = len(subset[subset['pnl_usd'] > 0]) / len(subset) * 100
            print(f"  {symbol:10} → {len(subset):3} trades | ${subset['pnl_usd'].sum():>8.2f} | WR: {wr:.1f}%")
    
    # Monthly breakdown
    df_trades['month'] = pd.to_datetime(df_trades['entry_time']).dt.to_period('M')
    monthly = df_trades.groupby('month')['pnl_usd'].agg(['count', 'sum']).round(2)
    
    print(f"""
📅 POR MES (2025):
─────────────────────────────────────────────────────────────────────""")
    for month, row in monthly.iterrows():
        print(f"  {month} → {int(row['count']):3} trades | ${row['sum']:>8.2f}")
    
    # Projection
    months_data = len(monthly)
    avg_monthly = total_pnl / months_data if months_data > 0 else 0
    
    print(f"""
═══════════════════════════════════════════════════════════════════════
🎯 PROYECCIÓN (basada en {months_data} meses de data):
═══════════════════════════════════════════════════════════════════════
  Promedio mensual:  ${avg_monthly:.2f}
  Proyección anual:  ${avg_monthly * 12:.2f}
  
  Con tu cuenta de $698:
  → ROI mensual:     {(avg_monthly / 698) * 100:.1f}%
  → ROI anual:       {(avg_monthly * 12 / 698) * 100:.1f}%
═══════════════════════════════════════════════════════════════════════
""")
    
    # Final verdict
    if win_rate >= 34 and total_pnl > 0:
        print("✅ CONFIGURACIÓN VALIDADA - Rentable y conservadora")
    elif win_rate >= 34:
        print("⚠️ Win Rate OK pero PnL bajo - Revisar filtros")
    else:
        print("❌ Win Rate < 34% - Configuración necesita ajustes")


if __name__ == "__main__":
    main()
