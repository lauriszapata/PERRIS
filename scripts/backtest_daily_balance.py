"""
Daily Balance Backtest - Jan 1 to Nov 25, 2025
Strategy: High Reward 3x (TP 2.5%, SL 3.0%, Lev 3x)
Parameters:
- Start Balance: $1000
- Exposure per Trade: $130
- Leverage: 3x
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import Config
from modules.backtest.data_loader import DataLoader
from modules.indicators import Indicators

# SYMBOLS (Top 40)
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "TRX/USDT", "DOT/USDT",
    "POL/USDT", "LINK/USDT", "LTC/USDT", "BCH/USDT", "ATOM/USDT", "UNI/USDT", "ETC/USDT", "FIL/USDT", "NEAR/USDT", "XMR/USDT",
    "XLM/USDT", "HBAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "RENDER/USDT", "INJ/USDT", "STX/USDT", "SUI/USDT", "IMX/USDT",
    "LDO/USDT", "GRT/USDT", "VET/USDT", "MKR/USDT", "AAVE/USDT", "SNX/USDT", "ALGO/USDT", "SAND/USDT", "MANA/USDT", "EOS/USDT"
]

class DailyBacktester:
    def __init__(self, data_map):
        self.data_map = data_map
        self.commission_rate = 0.00045
        self.balance = 1000.0
        self.exposure = 130.0
        self.leverage = 3
        self.tp_pct = 0.025
        self.sl_pct = 0.030
        self.trades = []
        self.daily_stats = {} # date -> {pnl, trades, balance}
        
    def run(self):
        # Collect all timestamps
        all_timestamps = set()
        for df in self.data_map.values():
            all_timestamps.update(df['timestamp'].tolist())
        timeline = sorted(list(all_timestamps))
        
        open_positions = {} # symbol -> pos
        max_open = 1
        cooldowns = {}
        
        print(f"🗓️  Simulating {len(timeline)} candles...")
        
        for current_time in timeline:
            current_date = current_time.date()
            if current_date not in self.daily_stats:
                self.daily_stats[current_date] = {'pnl': 0.0, 'trades': 0, 'balance': self.balance}
            
            # 1. Check Exits
            for symbol in list(open_positions.keys()):
                pos = open_positions[symbol]
                try:
                    # Check against current candle (assuming we have close data for this timestamp)
                    # In a real event loop, we'd check High/Low of the candle that *ends* at current_time?
                    # Or starts? Let's assume current_time is the CLOSE time.
                    row = self.data_map[symbol].loc[self.data_map[symbol]['timestamp'] == current_time].iloc[0]
                except: continue
                
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
                    # Calculate PnL
                    # Size is in COIN. 
                    # PnL = (Exit - Entry) * Size
                    raw_pnl = (exit_price - pos['entry_price']) * pos['size'] if pos['direction'] == 'LONG' else (pos['entry_price'] - exit_price) * pos['size']
                    
                    # Commission: Entry + Exit
                    # Entry Comm was already paid? Usually we deduct from balance on event.
                    # Let's deduct full roundtrip here for simplicity.
                    notional_entry = pos['entry_price'] * pos['size']
                    notional_exit = exit_price * pos['size']
                    comm = (notional_entry + notional_exit) * self.commission_rate
                    
                    net_pnl = raw_pnl - comm
                    self.balance += net_pnl
                    
                    self.trades.append({
                        'time': current_time,
                        'symbol': symbol,
                        'pnl': net_pnl,
                        'reason': reason
                    })
                    
                    # Update Daily Stats
                    self.daily_stats[current_date]['pnl'] += net_pnl
                    self.daily_stats[current_date]['trades'] += 1
                    self.daily_stats[current_date]['balance'] = self.balance
                    
                    del open_positions[symbol]
                    cooldowns[symbol] = current_time + timedelta(minutes=30)

            # 2. Check Entries
            if len(open_positions) < max_open:
                candidates = []
                for symbol, df in self.data_map.items():
                    if symbol in open_positions: continue
                    if symbol in cooldowns and current_time < cooldowns[symbol]: continue
                    
                    try:
                        row = df.loc[df['timestamp'] == current_time].iloc[0]
                    except: continue
                    
                    # Signal Logic (High Reward 3x)
                    # ADX >= 25, Vol >= 1.3, ATR < 2.5%
                    if row['ADX'] < 25: continue
                    if row['volume'] < 1.3 * row['Vol_SMA20']: continue
                    if (row['ATR'] / row['close']) > 0.025: continue
                    
                    if row['EMA50'] > row['EMA200'] and row['MACD_line'] > row['MACD_signal'] and row['RSI'] > 35:
                        candidates.append({'symbol': symbol, 'dir': 'LONG', 'price': row['close'], 'score': row['ADX']})
                    elif row['EMA50'] < row['EMA200'] and row['MACD_line'] < row['MACD_signal'] and 30 < row['RSI'] < 55:
                        candidates.append({'symbol': symbol, 'dir': 'SHORT', 'price': row['close'], 'score': row['ADX']})
                
                if candidates:
                    candidates.sort(key=lambda x: x['score'], reverse=True)
                    best = candidates[0]
                    
                    ep = best['price']
                    # Position Sizing
                    # Exposure $130 * 3x Leverage = $390 Notional?
                    # Or Exposure $130 IS the margin?
                    # User said "130 usd de exposicion". Usually means Position Size = $130.
                    # If Leverage is 3x, Margin = $130 / 3 = $43.33.
                    # Let's assume "Exposure" = Total Position Value (Notional).
                    # So Size = 130 / Price.
                    
                    # WAIT: In previous chats "Exposure" was defined as "Fixed Trade Exposure USD".
                    # If user says "130 exposure", they likely mean the total value of the trade is $130.
                    # With 3x leverage, this uses $43.33 of balance.
                    
                    size = self.exposure / ep
                    
                    tp = ep * (1 + self.tp_pct) if best['dir'] == 'LONG' else ep * (1 - self.tp_pct)
                    sl = ep * (1 - self.sl_pct) if best['dir'] == 'LONG' else ep * (1 + self.sl_pct)
                    
                    open_positions[best['symbol']] = {
                        'entry_price': ep,
                        'size': size,
                        'tp': tp,
                        'sl': sl,
                        'direction': best['dir'],
                        'entry_time': current_time
                    }
            
            # Update EOD Balance for the day (carry over if no trades)
            self.daily_stats[current_date]['balance'] = self.balance

        return self.daily_stats

def main():
    print("🚀 Loading Data...")
    loader = DataLoader()
    data_map = {}
    
    # Load data (Top 40)
    for symbol in SYMBOLS:
        try:
            df = loader.fetch_data_range(symbol, "2025-01-01", "2025-11-25", Config.TIMEFRAME)
            if df is not None and len(df) > 100:
                df = Indicators.calculate_all(df)
                data_map[symbol] = df
        except: pass
        
    print(f"✅ Loaded {len(data_map)} symbols.")
    
    bt = DailyBacktester(data_map)
    stats = bt.run()
    
    print(f"\n{'='*60}")
    print(f"{'Date':<15} {'Daily PnL':<15} {'Balance':<15} {'Trades':<10}")
    print(f"{'-'*60}")
    
    sorted_dates = sorted(stats.keys())
    
    total_pnl = 0
    
    for date in sorted_dates:
        s = stats[date]
        # Only print days with activity or significant changes?
        # User asked "dia a dia".
        print(f"{date}      ${s['pnl']:<14.2f} ${s['balance']:<14.2f} {s['trades']:<10}")
        total_pnl += s['pnl']
        
    print(f"{'='*60}")
    print(f"START BALANCE: $1000.00")
    print(f"END BALANCE:   ${bt.balance:.2f}")
    print(f"TOTAL PnL:     ${bt.balance - 1000:.2f}")
    print(f"RETURN:        {(bt.balance - 1000)/1000:.1%}")
    
    # Save to CSV
    csv_path = os.path.expanduser("~/Desktop/daily_report_2025.csv")
    print(f"\n💾 Saving report to {csv_path}...")
    
    data = []
    for date in sorted_dates:
        s = stats[date]
        data.append({
            'Date': date,
            'Daily_PnL': s['pnl'],
            'Balance': s['balance'],
            'Trades': s['trades']
        })
    
    df_out = pd.DataFrame(data)
    df_out.to_csv(csv_path, index=False)
    print("✅ Report saved.")

if __name__ == "__main__":
    main()
