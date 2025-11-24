from config import Config
from modules.logger import logger

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
    def check_trade_frequency(trades_last_hour):
        if len(trades_last_hour) >= Config.MAX_TRADES_PER_HOUR:
            logger.info(f"Max Trades Per Hour Reached: {len(trades_last_hour)}")
            return False
        return True

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
                pos_exposure = pos_data['size'] * pos_data['entry_price']
                total_current_exposure += pos_exposure
            
            logger.info(f"Current total exposure: {total_current_exposure:.2f} USD")
            
            # 2. Check if adding new position would exceed MAX_TOTAL_EXPOSURE_USD
            # Calculate Risk Amount
            risk_amount = balance * Config.RISK_PER_TRADE_PCT
            
            # Calculate Position Size based on Risk
            # Risk = Size * |Entry - SL|
            # Size = Risk / |Entry - SL|
            price_diff = abs(entry_price - sl_price)
            if price_diff == 0:
                logger.error("Entry Price equals SL Price! Cannot calculate size.")
                return 0
                
            size = risk_amount / price_diff
            
            # Calculate Exposure for this size
            exposure = size * entry_price
            
            logger.info(f"⚖️ Risk-Based Sizing: Risk {risk_amount:.2f} USD (1%) | SL Dist {price_diff:.4f} | Size {size:.4f} | Exposure {exposure:.2f} USD")
            
            if total_current_exposure + exposure > Config.MAX_TOTAL_EXPOSURE_USD:
                logger.warning(
                    f"⚠️  Total exposure limit reached! "
                    f"Current: {total_current_exposure:.2f} + New: {exposure:.2f} "
                    f"= {total_current_exposure + exposure:.2f} > Limit: {Config.MAX_TOTAL_EXPOSURE_USD}"
                )
                # Optional: Scale down to fit exposure limit?
                # For now, just reject to be safe and maintain risk profile.
                return 0
            
            # 3. Add commission buffer (0.1% for maker/taker fees + slippage)
            commission_buffer = 1.001
            required_margin = (exposure * commission_buffer) / Config.LEVERAGE
            
            if balance < required_margin:
                logger.warning(
                    f"Insufficient balance for {exposure:.2f} USD exposure. "
                    f"Required Margin (with buffer): {required_margin:.2f}, Balance: {balance:.2f}"
                )
                return 0
            
            # 4. (Size already calculated)
            
            # 5. Validate against exchange minimum order size
            try:
                market_info = client.exchange.market(symbol)
                min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0)
                
                if min_amount and size < min_amount:
                    logger.warning(
                        f"Calculated size {size:.6f} is below exchange minimum {min_amount:.6f} for {symbol}. "
                        f"Adjusting to minimum."
                    )
                    size = min_amount
                    
                    # Recalculate exposure with adjusted size
                    adjusted_exposure = size * entry_price
                    adjusted_margin = (adjusted_exposure * commission_buffer) / Config.LEVERAGE
                    
                    # Re-check if we still have enough balance
                    if balance < adjusted_margin:
                        logger.warning(
                            f"Insufficient balance for minimum order size. "
                            f"Required: {adjusted_margin:.2f}, Balance: {balance:.2f}"
                        )
                        return 0
                    
                    # Re-check total exposure limit
                    if total_current_exposure + adjusted_exposure > Config.MAX_TOTAL_EXPOSURE_USD:
                        logger.warning(
                            f"Minimum order size would exceed total exposure limit. "
                            f"Required: {adjusted_exposure:.2f}, Available: {Config.MAX_TOTAL_EXPOSURE_USD - total_current_exposure:.2f}"
                        )
                        return 0
                        
            except Exception as e:
                logger.warning(f"Could not fetch market limits for {symbol}: {e}. Proceeding with calculated size.")
            
            logger.info(f"✅ Position size calculated: {size:.6f} {symbol.split('/')[0]} (Exposure: {size * entry_price:.2f} USD)")
            return size
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0

