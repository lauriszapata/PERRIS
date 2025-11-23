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
            
            # 4. ADX (optimal for 15min trending moves)
            adx_val = last['ADX']
            results['ADX'] = {'status': adx_val >= 15, 'value': f"{adx_val:.2f}", 'threshold': ">= 15"}
            
            # 5. RSI (widened from 45-55 to 40-60 for more signals)
            rsi_val = last['RSI']
            if direction == "LONG":
                results['RSI'] = {'status': rsi_val > 40, 'value': f"{rsi_val:.2f}", 'threshold': "> 40"}
            else:
                results['RSI'] = {'status': rsi_val < 60, 'value': f"{rsi_val:.2f}", 'threshold': "< 60"}
            
            # 6. MACD
            macd_hist = last['MACD_hist']
            if direction == "LONG":
                results['MACD'] = {'status': macd_hist > 0, 'value': f"{macd_hist:.4f}", 'threshold': "> 0"}
            else:
                results['MACD'] = {'status': macd_hist < 0, 'value': f"{macd_hist:.4f}", 'threshold': "< 0"}
            
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
