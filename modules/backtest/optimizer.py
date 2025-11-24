import itertools
import pandas as pd
from modules.backtest.data_loader import DataLoader
from modules.backtest.backtester import Backtester
from modules.logger import logger
from config import Config

class Optimizer:
    def __init__(self):
        self.loader = DataLoader()
        self.backtester = Backtester()
        self.results = []

    def optimize(self, days=30):
        """
        Run grid search optimization.
        """
        # 1. Load Data
        logger.info("Loading data for optimization...")
        data_map = self.loader.load_all_symbols(days=days)
        if not data_map:
            logger.error("No data found for optimization.")
            return

        # 2. Define Grid
        param_grid = {
            'ATR_MIN_PCT': [0.15, 0.20, 0.25],
            'RISK_PER_TRADE_PCT': [0.005, 0.01, 0.015], # 0.5%, 1%, 1.5%
            'MAX_OPEN_SYMBOLS': [3, 5]
        }
        
        keys, values = zip(*param_grid.items())
        combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]
        
        logger.info(f"Starting optimization with {len(combinations)} combinations...")

        # 3. Run Backtests
        for i, params in enumerate(combinations):
            total_pnl = 0
            total_trades = 0
            sharpes = []
            
            for symbol, df in data_map.items():
                # Run backtest for this symbol with these params
                metrics = self.backtester.run(df, params)
                total_pnl += metrics['total_pnl']
                total_trades += metrics['trades']
                sharpes.append(metrics['sharpe'])
            
            avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0
            
            result = {
                'params': params,
                'total_pnl': total_pnl,
                'avg_sharpe': avg_sharpe,
                'total_trades': total_trades
            }
            self.results.append(result)
            logger.info(f"Combo {i+1}/{len(combinations)}: Sharpe={avg_sharpe:.2f}, PnL={total_pnl:.2f}")

        # 4. Find Best
        best_result = max(self.results, key=lambda x: x['avg_sharpe'])
        logger.info(f"Optimization Complete. Best Params: {best_result['params']}")
        logger.info(f"Best Sharpe: {best_result['avg_sharpe']:.2f}, Total PnL: {best_result['total_pnl']:.2f}")
        
        return best_result

if __name__ == "__main__":
    opt = Optimizer()
    opt.optimize()
