from modules.managers.trend_manager import TrendManager
from modules.managers.structure_manager import StructureManager
from modules.logger import logger

class EntrySignals:
    @staticmethod
    def check_signals(df, direction):
        """
        Check the 8 indicators and return detailed results.
        """
        results = {}
        try:
            last = df.iloc[-1]
            
            # 1, 2, 3. Trend
            trend_ok = TrendManager.check_trend(df, direction)
            results['Trend'] = {'status': trend_ok, 'value': 'Pass' if trend_ok else 'Fail'}
            
            # 4. ADX (Relaxed to 10 to catch weaker trends)
            adx_val = last['ADX']
            results['ADX'] = {'status': adx_val >= 10, 'value': f"{adx_val:.2f}", 'threshold': ">= 10"}
            
            # 5. RSI (Widened to 35-65 to catch more moves)
            rsi_val = last['RSI']
            if direction == "LONG":
                results['RSI'] = {'status': rsi_val > 35, 'value': f"{rsi_val:.2f}", 'threshold': "> 35"}
            else:
                results['RSI'] = {'status': rsi_val < 65, 'value': f"{rsi_val:.2f}", 'threshold': "< 65"}
            
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
            results['Volume'] = {'status': vol >= 0.8 * vol_avg, 'value': f"{vol:.2f}", 'threshold': f">= {0.8*vol_avg:.2f}"}
            
            # 8. Structure (OPTIONAL for 15min - changes too quickly)
            # Tracked but not required for entry
            structure = StructureManager.detect_structure(df)
            if direction == "LONG":
                structure_ok = bool(structure.get('HL'))
                results['Structure'] = {'status': True, 'value': 'HL' if structure_ok else 'No HL (optional)', 'optional': True}
            else:
                structure_ok = bool(structure.get('LH'))
                results['Structure'] = {'status': True, 'value': 'LH' if structure_ok else 'No LH (optional)', 'optional': True}
            
            # Final Decision (exclude optional filters)
            all_pass = all(r['status'] for k, r in results.items() if not r.get('optional', False))
            return all_pass, results
            
        except Exception as e:
            logger.error(f"Error checking signals: {e}")
            return False, {'Error': str(e)}
