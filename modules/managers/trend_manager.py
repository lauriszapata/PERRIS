from modules.logger import logger

class TrendManager:
    @staticmethod
    def check_trend(df, direction):
        """
        Check trend conditions based on EMAs.
        """
        try:
            # Get last row
            last = df.iloc[-1]
            
            # 1. EMA9 vs EMA21
            ema_cross = False
            if direction == "LONG":
                ema_cross = last['EMA9'] > last['EMA21']
            else:
                ema_cross = last['EMA9'] < last['EMA21']
            
            # 2. Trend Local (EMA50)
            trend_local = False
            if direction == "LONG":
                trend_local = last['close'] > last['EMA50']
            else:
                trend_local = last['close'] < last['EMA50']
            
            # 3. Trend Major (REMOVED: Too strict/lagging for 15m scalping)
            # trend_major = False
            # if direction == "LONG":
            #     trend_major = last['EMA20'] > last['EMA50']
            # else:
            #     trend_major = last['EMA20'] < last['EMA50']
                
            return ema_cross and trend_local # Removed trend_major
            
        except Exception as e:
            logger.error(f"Error checking trend: {e}")
            return False
