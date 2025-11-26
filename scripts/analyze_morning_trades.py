"""
Analizar trades solo en horario de la mañana (5:00 AM - 11:50 AM Colombia)
"""

import pandas as pd
import numpy as np

# Load the CSV
csv_path = "/Users/laurazapata/Desktop/BACKTEST_TRADES_NOV18-24.csv"
df = pd.read_csv(csv_path)

# Convert timestamps to datetime
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['exit_time'] = pd.to_datetime(df['exit_time'])

# Filter by morning hours (5:00 AM - 11:50 AM Colombia time)
# Since the data is already in Colombia timezone (UTC-5), we just filter by hour
morning_trades = df[
    (df['entry_time'].dt.hour >= 5) & 
    (df['entry_time'].dt.hour < 12) &
    ~((df['entry_time'].dt.hour == 11) & (df['entry_time'].dt.minute >= 50))
]

print("="*80)
print("📊 ANÁLISIS: TRADES SOLO EN HORARIO MAÑANA (5:00 AM - 11:50 AM)")
print("="*80)
print()

if len(morning_trades) == 0:
    print("❌ No hay trades en este horario.")
else:
    # Calculate metrics
    total_pnl = morning_trades['net_pnl'].sum()
    total_commission = morning_trades['commission'].sum()
    total_trades = len(morning_trades)
    winning_trades = len(morning_trades[morning_trades['net_pnl'] > 0])
    losing_trades = len(morning_trades[morning_trades['net_pnl'] <= 0])
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    
    # Profit Factor
    gross_profit = morning_trades[morning_trades['net_pnl'] > 0]['net_pnl'].sum()
    gross_loss = abs(morning_trades[morning_trades['net_pnl'] <= 0]['net_pnl'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Average trade
    avg_pnl = morning_trades['net_pnl'].mean()
    
    # Print results
    print(f"💰 Total PnL: ${total_pnl:,.2f}")
    print(f"💵 PnL Promedio por Trade: ${avg_pnl:,.2f}")
    print()
    print(f"📊 Estadísticas:")
    print(f"   Total Trades: {total_trades}")
    print(f"   Ganadores: {winning_trades} ({win_rate*100:.1f}%)")
    print(f"   Perdedores: {losing_trades} ({(1-win_rate)*100:.1f}%)")
    print()
    print(f"💪 Performance:")
    print(f"   Profit Factor: {profit_factor:.2f}")
    print(f"   Win Rate: {win_rate*100:.1f}%")
    print()
    print(f"💸 Costos:")
    print(f"   Comisiones Totales: ${total_commission:.2f}")
    print()
    
    # Per-Symbol breakdown (top 10)
    print("📋 Top Símbolos (Mañana):")
    symbol_stats = morning_trades.groupby('symbol').agg({
        'net_pnl': ['sum', 'count', 'mean'],
    }).round(2)
    symbol_stats.columns = ['Total PnL', 'Trades', 'Avg PnL']
    symbol_stats = symbol_stats.sort_values('Total PnL', ascending=False)
    print(symbol_stats.head(10).to_string())
    print()
    
    # Compare with full day
    full_day_pnl = df['net_pnl'].sum()
    full_day_trades = len(df)
    
    print("="*80)
    print("📊 COMPARACIÓN: MAÑANA vs TODO EL DÍA")
    print("="*80)
    print()
    print(f"{'Métrica':<30} {'Mañana':<20} {'Todo el Día':<20}")
    print("-"*70)
    print(f"{'Total PnL':<30} ${total_pnl:<19.2f} ${full_day_pnl:<19.2f}")
    print(f"{'Total Trades':<30} {total_trades:<20} {full_day_trades:<20}")
    print(f"{'Win Rate':<30} {win_rate*100:<19.1f}% {(len(df[df['net_pnl']>0])/len(df)*100):<19.1f}%")
    print(f"{'Profit Factor':<30} {profit_factor:<19.2f} {(df[df['net_pnl']>0]['net_pnl'].sum()/abs(df[df['net_pnl']<=0]['net_pnl'].sum())):<19.2f}")
    print(f"{'Avg PnL/Trade':<30} ${avg_pnl:<19.2f} ${df['net_pnl'].mean():<19.2f}")
    print()
    
    # Percentage of total
    pct_trades = (total_trades / full_day_trades) * 100
    pct_pnl = (total_pnl / full_day_pnl) * 100 if full_day_pnl != 0 else 0
    
    print(f"📊 La mañana representa:")
    print(f"   {pct_trades:.1f}% de los trades totales ({total_trades} de {full_day_trades})")
    print(f"   {pct_pnl:.1f}% del PnL total (${total_pnl:.2f} de ${full_day_pnl:.2f})")
    print()
    
    # Save filtered trades
    morning_csv = "/Users/laurazapata/Desktop/BACKTEST_MORNING_TRADES.csv"
    morning_trades.to_csv(morning_csv, index=False)
    print(f"💾 Trades de la mañana guardados en: {morning_csv}")

print()
print("="*80)
