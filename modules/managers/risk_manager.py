from config import Config
from modules.logger import logger
from modules.managers.correlation_manager import CorrelationManager

class RiskManager:
    @staticmethod
    def check_daily_stop(daily_pnl, balance):
        """
        If equity drops -3% in the day -> pause.
        """
        if balance == 0: 
            return False
            
        pnl_pct = daily_pnl / balance
        if pnl_pct <= Config.DAILY_DRAWDOWN_LIMIT:
            logger.warning(f"Daily Stop Hit: PnL {pnl_pct:.2%} <= {Config.DAILY_DRAWDOWN_LIMIT:.2%}")
            return False
        return True

    @staticmethod
    def check_max_symbols(open_positions):
        if len(open_positions) >= Config.MAX_OPEN_SYMBOLS:
            logger.info(f"Max Symbols Reached: {len(open_positions)} >= {Config.MAX_OPEN_SYMBOLS}")
            return False
        return True

    @staticmethod
    def check_trade_frequency(trades_last_hour, daily_pnl=0):
        # HOURLY TRADE LIMIT DISABLED - Always allow trades
        # if len(trades_last_hour) >= Config.MAX_TRADES_PER_HOUR:
        #     if daily_pnl > 0:
        #         logger.info(f"⚡ Frequency limit reached ({len(trades_last_hour)}) but Daily PnL is positive ({daily_pnl:.2f}). ALLOWING trade.")
        #         return True
        #     # Only log when we are actually rejecting the trade
        #     logger.info(f"Max Trades Per Hour Reached: {len(trades_last_hour)}")
        #     return False
        return True

    @staticmethod
    def check_portfolio_correlation(new_symbol, current_positions, client):
        """
        Check if adding new_symbol increases portfolio correlation risk beyond limits.
        """
        return CorrelationManager.check_correlation(new_symbol, current_positions, client)

    @staticmethod
    def calculate_position_size(entry_price, sl_price, balance, client, symbol, current_positions):
        """
        Calculate position size based on risk or fixed exposure.
        Now includes:
        - Total portfolio exposure validation
        - Exchange minimum order size validation
        - Commission buffer
        
        Args:
            entry_price: Entry price for the position
            sl_price: Stop-loss price
            balance: Available USDT balance
            client: BinanceClient instance to fetch market limits
            symbol: Trading pair symbol
            current_positions: Dict of currently open positions
        
        Returns:
            Position size in base currency units, or 0 if checks fail
        """
        try:
            # 1. Calculate current total exposure from open positions
            total_current_exposure = 0
            for pos_symbol, pos_data in current_positions.items():
                total_current_exposure += pos_data['size'] * pos_data['entry_price']
            logger.info(f"Current total exposure: {total_current_exposure:.2f} USD")

            # 2. Determine size based on risk percentage if configured, else fixed exposure
            if getattr(Config, "RISK_PER_TRADE_PCT", None) and Config.RISK_PER_TRADE_PCT > 0:
                # Risk‑based sizing
                risk_amount = balance * Config.RISK_PER_TRADE_PCT
                price_distance = abs(entry_price - sl_price)
                if price_distance == 0:
                    logger.warning("SL price equals entry price; cannot calculate risk‑based size.")
                    return 0
                size = risk_amount / price_distance
                exposure = size * entry_price
                logger.info(
                    f"⚖️ Risk‑based sizing: Risk ${risk_amount:.2f} / Distance {price_distance:.4f} => Size {size:.4f}, Exposure {exposure:.2f} USD"
                )
            else:
                # Fixed exposure sizing (default)
                target_exposure = Config.FIXED_TRADE_EXPOSURE_USD
                size = target_exposure / entry_price
                exposure = size * entry_price
                logger.info(
                    f"⚖️ Fixed Exposure Sizing: Target {target_exposure:.2f} USD | Entry {entry_price:.4f} | Size {size:.4f} | Exposure {exposure:.2f} USD"
                )

            # 3. Enforce total exposure limit
            if total_current_exposure + exposure > Config.MAX_TOTAL_EXPOSURE_USD:
                available_exposure = Config.MAX_TOTAL_EXPOSURE_USD - total_current_exposure
                if available_exposure <= 0:
                    logger.warning(
                        f"⚠️  Total exposure limit reached! Current: {total_current_exposure:.2f} >= Limit: {Config.MAX_TOTAL_EXPOSURE_USD}"
                    )
                    return 0
                logger.warning(
                    f"⚠️  Adjusting size to fit total exposure limit. Calculated: {exposure:.2f}, Available: {available_exposure:.2f}"
                )
                exposure = available_exposure
                size = exposure / entry_price

            # 4. Add commission buffer and check required margin
            commission_buffer = 1.001
            required_margin = (exposure * commission_buffer) / Config.LEVERAGE
            
            if balance < required_margin:
                # User requested: "bajas hasta que se pueda colocar la posicion"
                # Calculate max affordable exposure
                max_affordable_exposure = (balance * Config.LEVERAGE) / commission_buffer
                
                logger.warning(
                    f"⚠️ Insufficient balance for target exposure {exposure:.2f} USD. "
                    f"Adjusting down to max affordable: {max_affordable_exposure:.2f} USD (Balance: {balance:.2f})"
                )
                
                exposure = max_affordable_exposure
                size = exposure / entry_price

            # 5. Validate against exchange minimum order size and notional
            try:
                market_info = client.exchange.market(symbol)
                min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0)
                
                # Check Min Amount
                if min_amount and size < min_amount:
                    logger.warning(
                        f"Calculated size {size:.6f} is below exchange minimum {min_amount:.6f} for {symbol}. Adjusting to minimum."
                    )
                    size = min_amount
                    exposure = size * entry_price
                
                # Check Min Notional (Value)
                min_notional = Config.MIN_NOTIONAL_USD
                if exposure < min_notional:
                    # Add 5% buffer to avoid rejection due to price fluctuations
                    safe_min_notional = min_notional * 1.05
                    logger.warning(
                        f"Calculated exposure {exposure:.2f} USD is below minimum notional {min_notional} USD. Adjusting to {safe_min_notional:.2f} USD."
                    )
                    size = safe_min_notional / entry_price
                    exposure = safe_min_notional
                
                # Re-check Balance and Max Exposure after adjustments
                required_margin = (exposure * commission_buffer) / Config.LEVERAGE
                if balance < required_margin:
                    logger.warning(
                        f"Insufficient balance for minimum order size. Required: {required_margin:.2f}, Balance: {balance:.2f}"
                    )
                    return 0
                if total_current_exposure + exposure > Config.MAX_TOTAL_EXPOSURE_USD:
                    logger.warning(
                        f"Minimum order size would exceed total exposure limit. Required: {exposure:.2f}, Available: {Config.MAX_TOTAL_EXPOSURE_USD - total_current_exposure:.2f}"
                    )
                    return 0
            except Exception as e:
                logger.warning(f"Could not fetch market limits for {symbol}: {e}. Proceeding with calculated size.")

            logger.info(f"✅ Position size calculated: {size:.6f} {symbol.split('/')[0]} (Exposure: {size * entry_price:.2f} USD)")
            return size
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0
