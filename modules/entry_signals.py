from modules.managers.trend_manager import TrendManager
from modules.managers.structure_manager import StructureManager
from modules.logger import logger
from config import Config
import pandas as pd
from modules.managers.structure_manager import StructureManager
from modules.logger import logger

class EntrySignals:
    @staticmethod
    def check_mtf_trend(client, symbol, direction):
        """
        Check trend on higher timeframe (1H).
        """
        try:
            ohlcv = client.fetch_ohlcv(symbol, timeframe=Config.MTF_TIMEFRAME, limit=200)
            if not ohlcv: return False
            
            df_mtf = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_mtf['close'] = df_mtf['close'].astype(float)
            
            # VALIDATE: Ensure data from Binance contains no NaN
            from modules.utils.validation import ensure_no_nan
            ensure_no_nan(df_mtf['close'].values, f"MTF close prices for {symbol}")
            
            # Simple EMA Trend on MTF
            df_mtf.ta.ema(length=50, append=True)
            df_mtf.ta.ema(length=200, append=True)
            
            last = df_mtf.iloc[-1]
            ema50 = last['EMA_50']
            ema200 = last['EMA_200']
            
            if direction == "LONG":
                return ema50 > ema200
            else:
                return ema50 < ema200
        except Exception as e:
            logger.error(f"MTF Trend Check Error: {e}")
            return True # Fail open or closed? Let's fail safe (False) usually, but for now True to not block if API fails? 
            # Better fail safe:
            return False

    @staticmethod
    def check_signals(df, direction, client=None, symbol=None):
        """
        Check the 8 indicators and return detailed results.
        """
        results = {}
        try:
            last = df.iloc[-1]
            
            # 1, 2, 3. Trend
            trend_ok = TrendManager.check_trend(df, direction)
            results['Trend'] = {'status': trend_ok, 'value': 'Pass' if trend_ok else 'Fail'}
            
            # 4. ADX (Institutional: Strong Trend > 20, lowered from 25 to reduce lag)
            adx_val = last['ADX']
            results['ADX'] = {'status': adx_val >= 20, 'value': f"{adx_val:.2f}", 'threshold': ">= 20"}
            
            # 5. RSI (Widened to 35-65 to catch more moves)
            rsi_val = last['RSI']
            if direction == "LONG":
                results['RSI'] = {'status': rsi_val > 35, 'value': f"{rsi_val:.2f}", 'threshold': "> 35"}
            else:
                results['RSI'] = {'status': 30 < rsi_val < 55, 'value': f"{rsi_val:.2f}", 'threshold': "30-55"}
            
            # 6. MACD (Changed to Signal Cross for earlier entry)
            macd_line = last['MACD_line']
            macd_signal = last['MACD_signal']
            
            if direction == "LONG":
                # Bullish Cross: Line > Signal
                results['MACD'] = {'status': macd_line > macd_signal, 'value': f"L:{macd_line:.4f}/S:{macd_signal:.4f}", 'threshold': "Line > Sig"}
            else:
                # Bearish Cross: Line < Signal
                results['MACD'] = {'status': macd_line < macd_signal, 'value': f"L:{macd_line:.4f}/S:{macd_signal:.4f}", 'threshold': "Line < Sig"}
            
            # 7. Volume
            vol = last['volume']
            vol_avg = last['Vol_SMA20']
            results['Volume'] = {'status': vol >= 1.0 * vol_avg, 'value': f"{vol:.2f}", 'threshold': f">= {1.0*vol_avg:.2f}"}

            # 8. Volatility (Institutional: Avoid extreme chaos)
            atr_val = last['ATR']
            close_val = last['close']
            volatility_pct = atr_val / close_val
            # Max 3% volatility per candle to avoid unpredictable slippage/wicks
            results['Volatility'] = {'status': volatility_pct < 0.03, 'value': f"{volatility_pct:.2%}", 'threshold': "< 3%"}
            
            # 9. MTF Trend (1H)
            if client and symbol:
                mtf_ok = EntrySignals.check_mtf_trend(client, symbol, direction)
                results['MTF_Trend'] = {'status': mtf_ok, 'value': 'Pass' if mtf_ok else 'Fail', 'threshold': f"1H {direction}"}
            else:
                results['MTF_Trend'] = {'status': True, 'value': 'Skipped (No Client)', 'optional': True}
            
            # 8. Structure (OPTIONAL for 15min - changes too quickly)
            # Tracked but not required for entry
            structure = StructureManager.detect_structure(df)
            if direction == "LONG":
                structure_ok = bool(structure.get('HL'))
                results['Structure'] = {'status': True, 'value': 'HL' if structure_ok else 'No HL (optional)', 'optional': True}
            else:
                structure_ok = bool(structure.get('LH'))
                results['Structure'] = {'status': True, 'value': 'LH' if structure_ok else 'No LH (optional)', 'optional': True}
            
            # --- FINAL DECISION LOGIC ---
            # Standard Entry: All Filters Pass
            standard_entry = all(r['status'] for k, r in results.items() if not r.get('optional', False))
            
            # Early Entry (Fast Indicators Priority):
            # If Trend (Long Term) Fails, but Fast Trend + MACD + RSI + Volatility are GOOD -> ALLOW
            if not standard_entry:
                # Check Fast Trend (EMA8 > EMA20)
                ema8 = last['EMA8']
                ema20 = last['EMA20']
                fast_trend_ok = (ema8 > ema20) if direction == "LONG" else (ema8 < ema20)
                
                # Critical Fast Indicators
                macd_ok = results['MACD']['status']
                rsi_ok = results['RSI']['status']
                vol_ok = results['Volume']['status']
                volatility_ok = results['Volatility']['status']
                
                if fast_trend_ok and macd_ok and rsi_ok and vol_ok and volatility_ok:
                    logger.info(f"🚀 EARLY ENTRY TRIGGERED: Fast Trend + MACD + RSI valid (ignoring Long Term Trend/MTF)")
                    return True, results

            return standard_entry, results
            
        except Exception as e:
            logger.error(f"Error checking signals: {e}")
            return False, {'Error': str(e)}
