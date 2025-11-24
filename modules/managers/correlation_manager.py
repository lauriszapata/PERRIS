import pandas as pd
from config import Config
from modules.logger import logger

class CorrelationManager:
    @staticmethod
    def check_correlation(new_symbol, current_positions, client, threshold=0.75):
        """
        Check if the new_symbol is highly correlated with any currently open position.
        Returns False if correlation is too high (risk concentration).
        """
        try:
            if not current_positions:
                return True

            # Fetch history for new symbol
            # We need enough data points for meaningful correlation (e.g., 100 candles)
            new_data = client.fetch_ohlcv(new_symbol, limit=100)
            if not new_data:
                logger.warning(f"Could not fetch data for correlation check: {new_symbol}")
                return True # Fail open or closed? Let's fail open but log warning
            
            df_new = pd.DataFrame(new_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_new['close'] = df_new['close'].astype(float)
            returns_new = df_new['close'].pct_change().dropna()

            for pos_symbol in current_positions:
                if pos_symbol == new_symbol:
                    continue # Should not happen if logic is correct elsewhere
                
                # Fetch history for existing position symbol
                # Optimization: In a real system, we might cache this
                pos_data = client.fetch_ohlcv(pos_symbol, limit=100)
                if not pos_data:
                    continue
                
                df_pos = pd.DataFrame(pos_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_pos['close'] = df_pos['close'].astype(float)
                returns_pos = df_pos['close'].pct_change().dropna()

                # Align dataframes on index (timestamp) if needed, but for now assuming similar fetch times/intervals
                # Simple correlation of last N overlapping returns
                min_len = min(len(returns_new), len(returns_pos))
                corr = returns_new.tail(min_len).corr(returns_pos.tail(min_len))
                
                logger.info(f"Correlation {new_symbol} vs {pos_symbol}: {corr:.2f}")

                if corr > threshold:
                    logger.warning(f"Correlation Check Failed: {new_symbol} vs {pos_symbol} = {corr:.2f} > {threshold}")
                    return False
            
            return True

        except Exception as e:
            logger.error(f"Error in CorrelationManager: {e}")
            return True # Fail open to avoid blocking trading on error, but log it.
