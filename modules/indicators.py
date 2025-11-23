import pandas as pd
import pandas_ta as ta
from modules.logger import logger

class Indicators:
    @staticmethod
    def calculate_all(df):
        """
        Calculate all necessary indicators for the strategy.
        df: DataFrame with columns ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        try:
            # Ensure correct types
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['volume'] = df['volume'].astype(float)

            # EMAs
            df['EMA8'] = ta.ema(df['close'], length=8)
            df['EMA20'] = ta.ema(df['close'], length=20)
            df['EMA21'] = ta.ema(df['close'], length=21)
            df['EMA50'] = ta.ema(df['close'], length=50)
            df['EMA200'] = ta.ema(df['close'], length=200)

            # RSI
            df['RSI'] = ta.rsi(df['close'], length=14)

            # MACD
            macd = ta.macd(df['close'])
            df['MACD_line'] = macd['MACD_12_26_9']
            df['MACD_signal'] = macd['MACDs_12_26_9']
            df['MACD_hist'] = macd['MACDh_12_26_9']

            # ADX
            adx = ta.adx(df['high'], df['low'], df['close'], length=14)
            df['ADX'] = adx['ADX_14']

            # ATR
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

            # Volume Average
            df['Vol_SMA20'] = ta.sma(df['volume'], length=20)
            
            # Range (High - Low)
            df['Range'] = df['high'] - df['low']

            # Drop NaNs to ensure data integrity
            # We need to keep enough data, but drop the initial rows where indicators are calculating
            # EMA200 needs 200 rows.
            df.dropna(inplace=True)

            return df
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return df
