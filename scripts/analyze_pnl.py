import sys
import os
import pandas as pd
sys.path.append(os.getcwd())

from config import Config

def analyze_pnl():
    closures_file = "data/closures.csv"
    if not os.path.exists(closures_file):
        print("No closures.csv found.")
        return

    print(f"Loading {closures_file}...")
    df = pd.read_csv(closures_file)
    
    # Ensure numeric columns
    cols = ['entry_price', 'exit_price', 'size', 'pnl_usd']
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    print(f"\n--- Analyzing {len(df)} Trades with Commission Rate: {Config.COMMISSION_RATE*100:.4f}% ---")
    
    total_recorded_pnl = 0
    total_real_pnl = 0
    total_commissions = 0
    
    results = []
    
    for index, row in df.iterrows():
        symbol = row['symbol']
        direction = row['direction']
        entry = row['entry_price']
        exit_price = row['exit_price']
        size = row['size']
        recorded_pnl = row['pnl_usd']
        
        # Calculate Commission
        # Entry Commission
        entry_comm = (size * entry) * Config.COMMISSION_RATE
        # Exit Commission
        exit_comm = (size * exit_price) * Config.COMMISSION_RATE
        
        total_comm = entry_comm + exit_comm
        
        # Calculate Real PnL (Gross PnL - Commissions)
        # Re-calculate Gross PnL to be sure
        if direction == "LONG":
            gross_pnl = (exit_price - entry) * size
        else:
            gross_pnl = (entry - exit_price) * size
            
        real_net_pnl = gross_pnl - total_comm
        
        diff = real_net_pnl - recorded_pnl
        
        total_recorded_pnl += recorded_pnl
        total_real_pnl += real_net_pnl
        total_commissions += total_comm
        
        results.append({
            'symbol': symbol,
            'direction': direction,
            'gross_pnl': gross_pnl,
            'commissions': total_comm,
            'real_net_pnl': real_net_pnl,
            'recorded_pnl': recorded_pnl,
            'diff': diff
        })

    results_df = pd.DataFrame(results)
    
    print("\n=== SUMMARY ===")
    print(f"Total Recorded PnL: {total_recorded_pnl:.2f} USD")
    print(f"Total Real PnL:     {total_real_pnl:.2f} USD")
    print(f"Total Commissions:  {total_commissions:.2f} USD")
    print(f"Difference:         {total_real_pnl - total_recorded_pnl:.2f} USD")
    
    print("\n=== TOP 5 DISCREPANCIES ===")
    results_df['abs_diff'] = results_df['diff'].abs()
    top_diffs = results_df.sort_values('abs_diff', ascending=False).head(5)
    print(top_diffs[['symbol', 'direction', 'real_net_pnl', 'recorded_pnl', 'diff']])
    
    # Save report
    results_df.to_csv("data/pnl_analysis_report.csv", index=False)
    print("\nDetailed report saved to data/pnl_analysis_report.csv")

if __name__ == "__main__":
    analyze_pnl()
