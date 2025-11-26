import time
import pandas as pd
from collections import Counter
from config import Config
from modules.logger import logger
from modules.indicators import Indicators
from modules.entry_signals import EntrySignals
from modules.managers.risk_manager import RiskManager
from modules.managers.atr_manager import ATRManager
from modules.managers.structure_manager import StructureManager
from modules.filters.volatility import VolatilityFilters
from modules.filters.liquidity import LiquiditySpreadFilters
from modules.filters.funding import FundingFilter
from modules.filters.health_check import HealthCheck
from modules.filters.time_filter import TimeFilter
from modules.filters.news_filter import NewsFilter
from modules.reporting.csv_manager import CSVManager
from modules.ml.adaptive_tuner import AdaptiveTuner

class BotLogic:
    def __init__(self, client, state_handler, order_executor):
        self.client = client
        self.state = state_handler
        self.executor = order_executor
        self.tuner = AdaptiveTuner()
        
        # Restore Tuner State
        if 'tuner' in self.state.state:
            logger.info("🧠 Restoring Adaptive Tuner state...")
            self.tuner.set_state(self.state.state['tuner'])

    def run(self):
        logger.info("Bot started. Initializing Hybrid Frequency Loop...")
        
        # Sync Orphaned Positions
        self._sync_positions()
        
        # Enforce Fixed Leverage on Startup
        logger.info(f"🔧 Enforcing {Config.LEVERAGE}x Leverage for all symbols...")
        for symbol in Config.SYMBOLS:
            self.client.set_leverage(symbol, Config.LEVERAGE)
            time.sleep(0.1) # Avoid rate limits
        
        logger.info("✅ Health Check: 1s")
        logger.info("✅ Position Monitor: 2s")
        logger.info("✅ Strategy/Entry: 15m (Candle Close)")
        
        last_health_check = 0
        last_monitor_check = 0
        last_status_log = 0
        self.last_monitor_log = 0 # For detailed position logging
        last_strategy_run_candle = 0 # Track the timestamp of the last processed candle
        
        self.is_paused_latency = False
        self.good_latency_counter = 0
        
        while True:
            try:
                now = time.time()
                
                # Cleanup old trade timestamps (remove trades older than 1 hour)
                self.state.cleanup_old_trades(now)
                
                # 1. Health Check (Every 1s)
                if now - last_health_check >= 1:
                    latency = HealthCheck.get_latency(self.client)
                    
                    if self.is_paused_latency:
                        # We are paused, check if we can resume
                        if latency < Config.LATENCY_RESUME_MS:
                            self.good_latency_counter += 1
                            logger.info(f"Health Recovery: {latency:.2f}ms < {Config.LATENCY_RESUME_MS}ms ({self.good_latency_counter}/3)")
                            if self.good_latency_counter >= 3:
                                logger.info("✅ Latency stabilized. Resuming bot.")
                                self.is_paused_latency = False
                                self.good_latency_counter = 0
                        else:
                            self.good_latency_counter = 0 # Reset if one bad check
                            logger.warning(f"Still High Latency: {latency:.2f}ms. Waiting...")
                    else:
                        # We are running, check if we need to pause
                        if latency > Config.LATENCY_PAUSE_MS:
                            logger.warning(f"🛑 High Latency detected: {latency:.2f}ms > {Config.LATENCY_PAUSE_MS}ms. Pausing...")
                            self.is_paused_latency = True
                            self.good_latency_counter = 0
                            
                    last_health_check = now
                    
                # If paused by latency, skip strategy and monitoring (except maybe monitoring SL if critical?)
                # User said: "Pausar si latency > 800ms". Usually implies pausing new entries. 
                # Monitoring existing SL/TP should probably continue if possible, but if API is slow, it might fail.
                # Let's pause Strategy, but keep attempting Monitor (with timeout/error handling).
                if self.is_paused_latency:
                    time.sleep(1)
                    continue
                
                # 2. Position Monitor (Every 2s)
                # Checks SL, TP, Partials, and Early Invalidation in real-time
                if now - last_monitor_check >= 2:
                    self._monitor_positions()
                    last_monitor_check = now
                    
                # 3. Strategy (Every 15m Candle Close)
                # We check if we just passed a 15m mark (00, 15, 30, 45)
                # 15m = 900 seconds
                current_candle_timestamp = int(now // 900) * 900
                
                # If we haven't processed this candle yet, and we are slightly past the close (e.g. 5s buffer)
                # We want to run shortly after the close to get the closed candle data.
                # Let's say we run if we are within the first 60 seconds of the new candle
                time_into_candle = now % 900
                
                if current_candle_timestamp > last_strategy_run_candle and 5 <= time_into_candle < 60:
                    logger.info(f"⏰ 15m Candle Closed! Running Strategy for {time.strftime('%H:%M:%S', time.localtime(current_candle_timestamp))}...")
                    self._run_strategy_cycle()
                    last_strategy_run_candle = current_candle_timestamp
                
                # 4. Status Heartbeat (Every 60s)
                if now - last_status_log >= 60:
                    next_candle_time = current_candle_timestamp + 900
                    time_left = next_candle_time - now
                    if time_left < 0: time_left += 900 # Adjust if we are in the buffer zone
                    
                    logger.info(f"⏳ Waiting for next candle close in {time_left/60:.1f} minutes...")
                    last_status_log = now

                # Small sleep to prevent CPU burn, but fast enough for 1s checks
                time.sleep(0.1)
                
            except Exception as e:
                logger.critical(f"Unhandled exception in main loop: {e}")
                time.sleep(5)

    def _get_binance_position_data(self, symbol):
        """
        Fetch real-time position data (PnL, ROI, etc.) directly from Binance.
        Returns dict with unrealizedPnl, percentage (ROI), markPrice, contracts (size)
        """
        try:
            binance_positions = self.client.get_all_positions()
            if not binance_positions:
                return None
            
            for pos in binance_positions:
                if pos['symbol'] == symbol:
                    return {
                        'unrealizedPnl': float(pos.get('unrealizedPnl', 0)),
                        'percentage': float(pos.get('percentage', 0)),  # ROI%
                        'markPrice': float(pos.get('markPrice', 0)),
                        'contracts': float(pos.get('contracts', 0)),
                        'notional': float(pos.get('notional', 0))  # Exposure
                    }
            return None
        except Exception as e:
            logger.error(f"Error fetching Binance position data for {symbol}: {e}")
            return None

    def _sync_positions(self):
        """
        Sync local state with actual exchange positions.
        Adopts orphans and removes ghosts.
        """
        logger.info("🔄 Syncing positions with Binance...")
        exchange_positions = self.client.get_all_positions()
        
        if exchange_positions is None:
            logger.error("❌ Failed to fetch positions from Binance. Aborting sync to protect state.")
            return

        local_positions = self.state.state['positions']
        
        # 1. Adopt Orphans (Exchange has it, Local doesn't)
        for pos in exchange_positions:
            symbol = pos['symbol']
            size = float(pos['contracts'])
            direction = "LONG" if pos['side'] == 'long' else "SHORT"
            entry_price = float(pos['entryPrice'])
            
            if symbol not in local_positions:
                logger.warning(f"👶 Found ORPHAN position: {symbol} {direction} Size: {size}")
                
                # Reconstruct state
                try:
                    ohlcv = self.client.fetch_ohlcv(symbol)
                    if ohlcv:
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        df = Indicators.calculate_all(df)
                        current_atr = df.iloc[-1]['ATR']
                    else:
                        current_atr = entry_price * 0.01 # Fallback 1%
                except:
                    current_atr = entry_price * 0.01
                
                # Check for existing SL order
                sl_price = entry_price * (0.99 if direction == "LONG" else 1.01) # Default 1% SL
                open_orders = self.client.get_open_orders(symbol)
                for o in open_orders:
                    if o['type'] == 'STOP_MARKET':
                        sl_price = float(o['stopPrice'])
                        break
                
                pos_data = {
                    "direction": direction,
                    "entry_price": entry_price,
                    "size": size,
                    "sl_price": sl_price,
                    "atr_entry": current_atr, # Best guess
                    "p_max": entry_price, 
                    "p_min": entry_price,
                    "partials": {"p1": False, "p2": False}, # Assume not taken
                    "entry_time": time.time() # Unknown, set to now
                }
                self.state.set_position(symbol, pos_data)
                logger.info(f"✅ Adopted {symbol}. SL: {sl_price}")

        # 2. Remove Ghosts (Local has it, Exchange doesn't)
        exchange_symbols = [p['symbol'] for p in exchange_positions]
        local_symbols = list(local_positions.keys())
        
        for symbol in local_symbols:
            if symbol not in exchange_symbols:
                logger.warning(f"👻 Found GHOST position in state: {symbol}. Removing...")
                self.state.clear_position(symbol)
                
                # Also clean up active_partials in tuner
                if symbol in self.tuner.active_partials:
                    logger.info(f"🧹 Cleaning active_partials for ghost position: {symbol}")
                    del self.tuner.active_partials[symbol]

    def _monitor_positions(self):
        """
        Monitor active positions for Partials, SL, TP.
        Runs every 3 seconds.
        Also cleans orphaned orders when no positions exist.
        """
        positions = self.state.state['positions']
        
        # Clean up orphaned orders when no positions (every 30s to avoid spam)
        if not positions:
            now = time.time()
            if not hasattr(self, 'last_cleanup_time'):
                self.last_cleanup_time = 0
            
            if now - self.last_cleanup_time >= 30:  # Only cleanup every 30 seconds
                total_cancelled = 0
                for symbol in Config.SYMBOLS:
                    cancelled = self.client.cancel_all_orders(symbol)
                    total_cancelled += cancelled
                
                if total_cancelled > 0:
                    logger.info(f"🧹 Cleaned up {total_cancelled} orphaned orders (no active positions)")
                
                self.last_cleanup_time = now
            return

        now = time.time()
        should_log = (now - self.last_monitor_log) >= 20

        # FETCH REAL POSITIONS FROM BINANCE (every 2 seconds)
        # Instead of calculating PnL locally, read actual data from exchange
        try:
            binance_positions = self.client.get_all_positions()
            if binance_positions is None:
                logger.warning("⚠️ Failed to fetch positions from Binance for monitoring")
                return
        except Exception as e:
            logger.error(f"Error fetching positions from Binance: {e}")
            return
        
        # Process each position from Binance
        for binance_pos in binance_positions:
            symbol = binance_pos['symbol']
            
            # Skip if we don't have this position in local state
            if symbol not in positions:
                continue
            
            pos_data = positions[symbol]
            
            try:
                # Extract REAL data from Binance
                current_price = float(binance_pos.get('markPrice', 0))
                unrealized_pnl = float(binance_pos.get('unrealizedPnl', 0))
                pnl_percentage = float(binance_pos.get('percentage', 0))
                actual_size = float(binance_pos.get('contracts', 0))
                
                if current_price == 0:
                    logger.warning(f"⚠️ Invalid price from Binance for {symbol}")
                    continue
                
                # Update size if different (could have been reduced by partials outside our tracking)
                if abs(actual_size - pos_data['size']) > 0.001:
                    logger.info(f"🔄 Syncing size for {symbol}: Local {pos_data['size']:.6f} -> Binance {actual_size:.6f}")
                    pos_data['size'] = actual_size
                    self.state.set_position(symbol, pos_data)
                
                self._check_partials(symbol, pos_data, current_price, should_log)
            
                direction = pos_data['direction']
                entry_price = pos_data['entry_price']
                atr_entry = pos_data['atr_entry']
                size = actual_size
                sl_price = pos_data['sl_price']
                
                # --- BREAKEVEN TRIGGER ---
                # If profit > BREAKEVEN_TRIGGER_PCT (0.8%), move SL to Entry
                # Only if SL is not already at or better than Entry
                pnl_pct_current = pnl_percentage / 100  # Binance returns percentage as number (e.g., 1.5 for 1.5%)
                
                if pnl_pct_current >= Config.BREAKEVEN_TRIGGER_PCT:
                    is_breakeven = False
                    if direction == "LONG":
                        if sl_price < entry_price: # SL is below entry (risk)
                            new_sl = entry_price * 1.002 # Entry + 0.2% buffer (covers fees)
                            self.executor.set_stop_loss(symbol, direction, new_sl)
                            pos_data['sl_price'] = new_sl
                            pos_data['sl_moved_count'] = pos_data.get('sl_moved_count', 0) + 1
                            self.state.set_position(symbol, pos_data)
                            logger.info(f"🛡️ BREAKEVEN TRIGGERED for {symbol}: SL moved to {new_sl:.4f} (Profit {pnl_pct_current:.2%})")
                    else: # SHORT
                        if sl_price > entry_price: # SL is above entry (risk)
                            new_sl = entry_price * 0.998 # Entry - 0.2% buffer (covers fees)
                            self.executor.set_stop_loss(symbol, direction, new_sl)
                            pos_data['sl_price'] = new_sl
                            pos_data['sl_moved_count'] = pos_data.get('sl_moved_count', 0) + 1
                            self.state.set_position(symbol, pos_data)
                            logger.info(f"🛡️ BREAKEVEN TRIGGERED for {symbol}: SL moved to {new_sl:.4f} (Profit {pnl_pct_current:.2%})")

                # --- REAL-TIME EARLY INVALIDATION (1.5 ATR) ---
                # Check if price moved > 1.5 ATR against us
                
                early_exit_triggered = False
                if direction == "LONG":
                    if current_price < entry_price - (1.5 * atr_entry):
                        logger.info(f"🚨 REAL-TIME EXIT: Early Invalidation (Price {current_price:.4f} < Entry {entry_price:.4f} - 1.5 ATR)")
                        early_exit_triggered = True
                else: # SHORT
                    if current_price > entry_price + (1.5 * atr_entry):
                        logger.info(f"🚨 REAL-TIME EXIT: Early Invalidation (Price {current_price:.4f} > Entry {entry_price:.4f} + 1.5 ATR)")
                        early_exit_triggered = True
                
                if early_exit_triggered:
                    close_order = self.executor.close_position(symbol, direction, size)
                    
                    # Log Closure with ACTUAL exit price
                    if close_order:
                        try:
                            # Get ACTUAL exit price from Binance
                            exit_price = close_order.get('average') or close_order.get('price') or current_price
                            actual_size = close_order.get('filled') or size
                            
                            logger.info(f"✅ Early Exit Filled | Exit: {exit_price:.4f} | Size: {actual_size:.6f}")
                            
                            pnl_usd = (exit_price - entry_price) * actual_size if direction == "LONG" else (entry_price - exit_price) * actual_size
                            pnl_pct = (exit_price - entry_price) / entry_price if direction == "LONG" else (entry_price - exit_price) / entry_price
                            duration = time.time() - pos_data['entry_time']
                            
                            # Log Closure (CERRADOS)
                            leverage = Config.LEVERAGE
                            exposure = actual_size * entry_price
                            margin = exposure / leverage
                            
                            CSVManager.log_closure(
                                symbol=symbol,
                                close_time=time.time(),
                                pnl_usd=pnl_usd,
                                margin=margin,
                                leverage=leverage,
                                exposure=exposure,
                                duration_sec=duration,
                                info="Early Invalidation (Real-Time)"
                            )
                            
                            # ML Update (Total PnL - Commissions)
                            total_pnl_usd = pnl_usd + pos_data.get('accumulated_pnl', 0.0)
                            
                            # Commission Calculation (Entry + Exit Volume * Rate)
                            total_volume = (actual_size * entry_price) + (exit_price * actual_size)
                            commission = total_volume * Config.COMMISSION_RATE
                            net_pnl_usd = total_pnl_usd - commission
                            
                            initial_margin = (actual_size * entry_price) / Config.LEVERAGE
                            net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                            
                            # Max PnL Calculation
                            if direction == "LONG":
                                max_pnl_pct = (pos_data['p_max'] - entry_price) / entry_price
                            else:
                                max_pnl_pct = (entry_price - pos_data['p_min']) / entry_price
                            
                            # Build partial data for ML
                            partial_data = {
                                'partial_pnl_usd': pos_data.get('accumulated_pnl', 0),
                                'final_pnl_usd': total_pnl_usd,
                                'levels_hit': [k for k, v in pos_data.get('partials', {}).items() if v]
                            }
                            
                            logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                            self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                            
                            # Save Tuner State
                            self.state.state['tuner'] = self.tuner.get_state()
                            self.state.save_state()
                        except Exception as e:
                            logger.error(f"Failed to log closure CSV: {e}")
                    self.state.clear_position(symbol)
                    continue # Skip logging and next steps for this symbol
                
                if should_log:
                    # Display REAL data from Binance
                    sl = pos_data['sl_price']
                    
                    if direction == "LONG":
                        dist_sl = (current_price - sl) / current_price * 100
                    else:
                        dist_sl = (sl - current_price) / current_price * 100
                    
                    # Show REAL Binance PnL (not calculated)
                    logger.info(
                        f"👀 MONITOR {symbol} {direction}: "
                        f"Price {current_price:.4f} | "
                        f"PnL: {pnl_percentage:+.2f}% ({unrealized_pnl:+.2f} USD) [Binance] | "
                        f"Dist to SL: {dist_sl:.2f}% | "
                        f"Size: {actual_size:.6f}"
                    )
                    # For now, the logs inside _check_partials are fine as they are info level.
                    # To avoid spam, we should wrap the "Waiting" logs in _check_partials with a check or rate limit.
                    # But the user ASKED for detailed logs. So spam is better than silence.
                    # But the user ASKED for detailed logs. So spam is better than silence.
                
            except Exception as e:
                logger.error(f"Error monitoring {symbol}: {e}")
        
        if should_log:
            self.last_monitor_log = now

    def _check_partials(self, symbol, pos_data, current_price, should_log=False):
        """
        INFINITE SCALPING STRATEGY:
        - Fixed levels (P1-P6) secure base profits at 0.3%, 0.4%, 0.5%, 0.6%, 0.8%, 1.0%
        - After P6, dynamically generates levels EVERY 0.1% indefinitely
        - Never closes 100% - always leaves position for SL to manage
        - Allows unlimited profit on strong trending moves
        """
        direction = pos_data['direction']
        entry = pos_data['entry_price']
        partials = pos_data.get('partials', {})
        
        # Initialize partials dict if not present
        if not partials:
            partials = {f"p{i+1}": False for i in range(len(Config.TAKE_PROFIT_LEVELS))}
            pos_data['partials'] = partials
            
        # Initialize accumulated PnL if not present
        if 'accumulated_pnl' not in pos_data:
            pos_data['accumulated_pnl'] = 0.0
        
        # Track the highest dynamic level taken
        if 'last_dynamic_level' not in pos_data:
            pos_data['last_dynamic_level'] = 0
        
        # Calculate current PnL percentage
        if direction == "LONG":
            pnl_pct = (current_price - entry) / entry
        else:  # SHORT
            pnl_pct = (entry - current_price) / entry
        
        executed_any = False
        
        # Log status of partials
        next_target_log = "None"
        
        # 1. Check FIXED levels first (P1-P6)
        for i, level_config in enumerate(Config.TAKE_PROFIT_LEVELS):
            level_name = f"p{i+1}"
            target_pct = level_config['pct']
            close_pct = level_config['close_pct']
            display_name = level_config['name']
            
            # Skip if already taken
            if partials.get(level_name, False):
                continue
            
            # Found the next untaken level
            if next_target_log == "None":
                 if direction == "LONG":
                     tgt_price = entry * (1 + target_pct)
                 else:
                     tgt_price = entry * (1 - target_pct)
                 next_target_log = f"{display_name} ({target_pct:.1%}) at {tgt_price:.4f}"
                 
                 # Log waiting status (only if not about to execute and should_log is True)
                 if pnl_pct < target_pct and should_log:
                     logger.info(f"⏳ Waiting for {display_name}: Current PnL {pnl_pct:.2%} < Target {target_pct:.1%} (Dist: {abs(target_pct-pnl_pct):.2%})")
            
            # Check if this level is hit
            if pnl_pct >= target_pct:
                # Calculate price at which this level was hit
                if direction == "LONG":
                    target_price = entry * (1 + target_pct)
                else:
                    target_price = entry * (1 - target_pct)
                
                # Calculate profit in USD
                position_value = pos_data['size'] * entry
                profit_usd = position_value * target_pct
                
                logger.info(
                    f"💰 {display_name} HIT for {symbol} {direction}! "
                    f"Price: {current_price:.4f} (Target: {target_price:.4f}), "
                    f"PnL: {pnl_pct:.2%} ({profit_usd:.2f} USD)"
                )
                
                # Close the specified percentage
                amount = pos_data['size'] * close_pct
                close_order = self.executor.close_position(symbol, direction, amount)
                
                # Check if close was successful
                if close_order:
                    # Get ACTUAL exit price from Binance order response
                    actual_exit_price = close_order.get('average') or close_order.get('price') or current_price
                    actual_closed_amount = close_order.get('filled') or amount
                    
                    # Log the actual execution details
                    logger.info(f"✅ Partial Close Filled | Exit: {actual_exit_price:.4f} | Amount: {actual_closed_amount:.6f}")
                    
                    # Recalculate PnL with ACTUAL exit price
                    if direction == "LONG":
                        actual_pnl_pct = (actual_exit_price - entry) / entry
                        actual_profit_usd = (actual_exit_price - entry) * actual_closed_amount
                    else:
                        actual_pnl_pct = (entry - actual_exit_price) / entry
                        actual_profit_usd = (entry - actual_exit_price) * actual_closed_amount
                    
                    # Update position size to reflect the actual close
                    pos_data['size'] -= actual_closed_amount
                    logger.info(f"📉 Updated position size: {pos_data['size']:.6f} remaining ({(pos_data['size']/(pos_data['size']+actual_closed_amount)*100):.1f}% of previous)")
                    
                    partials[level_name] = True
                    executed_any = True
                    
                    # Record partial close timestamp
                    self.state.add_trade_timestamp(time.time())
                    
                    # Accumulate Realized PnL
                    pos_data['accumulated_pnl'] += actual_profit_usd
                    logger.info(f"💰 Accumulated PnL for {symbol}: {pos_data['accumulated_pnl']:.2f} USD (Actual: {actual_profit_usd:.2f} USD from this partial)")
                    
                    # Log Partial Closure to CSV with ACTUAL values
                    try:
                        # Log Closure (CERRADOS)
                        leverage = Config.LEVERAGE
                        exposure = actual_closed_amount * entry
                        margin = exposure / leverage
                        duration = time.time() - pos_data['entry_time']

                        CSVManager.log_closure(
                            symbol=symbol,
                            close_time=time.time(),
                            pnl_usd=actual_profit_usd,
                            margin=margin,
                            leverage=leverage,
                            exposure=exposure,
                            duration_sec=duration,
                            info=f"Partial {display_name}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to log partial CSV: {e}")
                    
                    # Update stop-loss (progressive profit protection)
                    if i == 0:  # P1: Move SL to break-even
                        if direction == "LONG":
                            new_sl = entry * 1.001
                        else:
                            new_sl = entry * 0.999
                        
                        if (direction == "LONG" and new_sl > pos_data['sl_price']) or \
                           (direction == "SHORT" and new_sl < pos_data['sl_price']):
                            logger.info(f"🛡️ Moving SL to Break-Even: {new_sl:.4f}")
                            self.executor.set_stop_loss(symbol, direction, new_sl)
                            pos_data['sl_price'] = new_sl
                            pos_data['last_sl_update'] = time.time()
                            pos_data['sl_moved_count'] = pos_data.get('sl_moved_count', 0) + 1
                    
                    else:  # P2+: Move SL to previous level price
                        prev_level_pct = Config.TAKE_PROFIT_LEVELS[i-1]['pct']
                        if direction == "LONG":
                            new_sl = entry * (1 + prev_level_pct)
                        else:
                            new_sl = entry * (1 - prev_level_pct)
                        
                        if (direction == "LONG" and new_sl > pos_data['sl_price']) or \
                           (direction == "SHORT" and new_sl < pos_data['sl_price']):
                            logger.info(f"🛡️ Moving SL to P{i} Level: {new_sl:.4f} ({prev_level_pct:.1%})")
                            self.executor.set_stop_loss(symbol, direction, new_sl)
                            pos_data['sl_price'] = new_sl
                            pos_data['last_sl_update'] = time.time()
                            pos_data['sl_moved_count'] = pos_data.get('sl_moved_count', 0) + 1
                    
                    # Save updated position
                    self.state.set_position(symbol, pos_data)
                    
                    # Send partial data to ML
                    self.tuner.update_partial(
                        symbol=symbol,
                        level_name=display_name,
                        partial_pnl_usd=profit_usd,
                        current_total_pnl=pos_data['accumulated_pnl']
                    )
                    
                    # Log remaining position
                    total_closed = sum(Config.TAKE_PROFIT_LEVELS[j]['close_pct'] 
                                      for j in range(i+1) if partials.get(f"p{j+1}", False))
                    remaining_pct = 100 * (1 - total_closed)
                    logger.info(f"📊 Remaining position: {remaining_pct:.0f}%")
                else:
                    # Partial close failed - sync with exchange
                    logger.warning(f"⚠️ Partial close failed for {symbol}. Syncing position with exchange...")
                    try:
                        # Fetch actual position from exchange
                        positions = self.client.get_position(symbol)
                        target_side = 'long' if direction == 'LONG' else 'short'
                        
                        actual_size = 0
                        for p in positions:
                            if float(p['contracts']) > 0:
                                pos_side = p.get('side')
                                if pos_side and pos_side.lower() == target_side:
                                    actual_size = float(p['contracts'])
                                    break
                                elif not pos_side:
                                    actual_size = float(p['contracts'])
                                    break
                        
                        if actual_size > 0:
                            logger.info(f"🔄 Synced position size: {actual_size:.6f} (was {pos_data['size']:.6f})")
                            pos_data['size'] = actual_size
                            self.state.set_position(symbol, pos_data)
                        else:
                            logger.warning(f"❌ No position found on exchange for {symbol}. Clearing local state.")
                            self.state.clear_position(symbol)
                            return False
                    except Exception as e:
                        logger.error(f"Failed to sync position after failed close: {e}")
                
                # Only execute one level per check
                break
        
        # 2. Check DYNAMIC levels (after all fixed levels are done)
        all_fixed_done = all(partials.get(f"p{i+1}", False) for i in range(len(Config.TAKE_PROFIT_LEVELS)))
        
        if all_fixed_done and not executed_any:
            # Calculate the next dynamic level to check
            next_dynamic_level = pos_data['last_dynamic_level'] + 1
            dynamic_target_pct = Config.DYNAMIC_SCALPING_START + (next_dynamic_level * Config.DYNAMIC_SCALPING_INCREMENT)
            
            if direction == "LONG":
                 tgt_price = entry * (1 + dynamic_target_pct)
            else:
                 tgt_price = entry * (1 - dynamic_target_pct)
            
            if next_target_log == "None":
                next_target_log = f"Dynamic D{next_dynamic_level} ({dynamic_target_pct:.1%}) at {tgt_price:.4f}"
                if pnl_pct < dynamic_target_pct and should_log:
                     logger.info(f"⏳ Waiting for Dynamic D{next_dynamic_level}: Current PnL {pnl_pct:.2%} < Target {dynamic_target_pct:.1%} (Dist: {abs(dynamic_target_pct-pnl_pct):.2%})")
            
            # Check if we've hit this dynamic level
            if pnl_pct >= dynamic_target_pct:
                if direction == "LONG":
                    target_price = entry * (1 + dynamic_target_pct)
                else:
                    target_price = entry * (1 - dynamic_target_pct)
                
                position_value = pos_data['size'] * entry
                profit_usd = position_value * dynamic_target_pct
                
                logger.info(
                    f"🚀 DYNAMIC LEVEL D{next_dynamic_level} HIT for {symbol} {direction}! "
                    f"Price: {current_price:.4f} (Target: {target_price:.4f}), "
                    f"PnL: {pnl_pct:.2%} ({profit_usd:.2f} USD)"
                )
                
                # Close the dynamic percentage (5%)
                amount = pos_data['size'] * Config.DYNAMIC_SCALPING_CLOSE_PCT
                close_order = self.executor.close_position(symbol, direction, amount)
                
                # Check if close was successful
                if close_order:
                    # Get ACTUAL exit price from Binance order response
                    actual_exit_price = close_order.get('average') or close_order.get('price') or current_price
                    actual_closed_amount = close_order.get('filled') or amount
                    
                    # Log the actual execution details
                    logger.info(f"✅ Dynamic Close Filled | Exit: {actual_exit_price:.4f} | Amount: {actual_closed_amount:.6f}")
                    
                    # Recalculate PnL with ACTUAL exit price
                    if direction == "LONG":
                        actual_profit_usd = (actual_exit_price - entry) * actual_closed_amount
                    else:
                        actual_profit_usd = (entry - actual_exit_price) * actual_closed_amount
                    
                    # Update position size to reflect the actual close
                    pos_data['size'] -= actual_closed_amount
                    logger.info(f"📉 Updated position size: {pos_data['size']:.6f} remaining ({(pos_data['size']/(pos_data['size']+actual_closed_amount)*100):.1f}% of previous)")
                    
                    pos_data['last_dynamic_level'] = next_dynamic_level
                    executed_any = True
                    
                    # Record partial close timestamp
                    self.state.add_trade_timestamp(time.time())
                    
                    # Accumulate Realized PnL
                    pos_data['accumulated_pnl'] += actual_profit_usd
                    logger.info(f"💰 Accumulated PnL for {symbol}: {pos_data['accumulated_pnl']:.2f} USD (Actual: {actual_profit_usd:.2f} USD from this dynamic partial)")
                    
                    # Move SL to previous dynamic level
                    prev_dynamic_pct = Config.DYNAMIC_SCALPING_START + ((next_dynamic_level - 1) * Config.DYNAMIC_SCALPING_INCREMENT)
                    if direction == "LONG":
                        new_sl = entry * (1 + prev_dynamic_pct)
                    else:
                        new_sl = entry * (1 - prev_dynamic_pct)
                    
                    if (direction == "LONG" and new_sl > pos_data['sl_price']) or \
                       (direction == "SHORT" and new_sl < pos_data['sl_price']):
                        logger.info(f"🛡️ Moving SL to D{next_dynamic_level-1} Level: {new_sl:.4f} ({prev_dynamic_pct:.1%})")
                        self.executor.set_stop_loss(symbol, direction, new_sl)
                        pos_data['sl_price'] = new_sl
                        pos_data['last_sl_update'] = time.time()
                        pos_data['sl_moved_count'] = pos_data.get('sl_moved_count', 0) + 1
                    
                    # Save updated position
                    self.state.set_position(symbol, pos_data)
                    
                    # Send partial data to ML
                    self.tuner.update_partial(
                        symbol=symbol,
                        level_name=f"D{next_dynamic_level}",
                        partial_pnl_usd=actual_profit_usd,
                        current_total_pnl=pos_data['accumulated_pnl']
                    )
                    
                    # Calculate remaining position
                    total_fixed_closed = sum(level['close_pct'] for level in Config.TAKE_PROFIT_LEVELS)
                    total_dynamic_closed = next_dynamic_level * Config.DYNAMIC_SCALPING_CLOSE_PCT
                    remaining_pct = 100 * (1 - total_fixed_closed - total_dynamic_closed)
                    logger.info(f"📊 Remaining position: {remaining_pct:.0f}% (Dynamic level {next_dynamic_level})")
                else:
                    # Dynamic partial close failed - sync with exchange
                    logger.warning(f"⚠️ Dynamic partial close failed for {symbol}. Syncing position with exchange...")
                    try:
                        # Fetch actual position from exchange
                        positions = self.client.get_position(symbol)
                        target_side = 'long' if direction == 'LONG' else 'short'
                        
                        actual_size = 0
                        for p in positions:
                            if float(p['contracts']) > 0:
                                pos_side = p.get('side')
                                if pos_side and pos_side.lower() == target_side:
                                    actual_size = float(p['contracts'])
                                    break
                                elif not pos_side:
                                    actual_size = float(p['contracts'])
                                    break
                        
                        if actual_size > 0:
                            logger.info(f"🔄 Synced position size: {actual_size:.6f} (was {pos_data['size']:.6f})")
                            pos_data['size'] = actual_size
                            self.state.set_position(symbol, pos_data)
                        else:
                            logger.warning(f"❌ No position found on exchange for {symbol}. Clearing local state.")
                            self.state.clear_position(symbol)
                            return False
                    except Exception as e:
                        logger.error(f"Failed to sync position after failed dynamic close: {e}")
        
        return executed_any

    def _run_strategy_cycle(self):
        # 1. Health Checks
        if not HealthCheck.check_latency(self.client):
            return
        
        # 2. News Filter Check
        if not NewsFilter.check_news():
            logger.warning("📰 High-impact news detected! Skipping strategy cycle.")
            return
        
        # 3. Trade Frequency Check (DISABLED)
        # if not RiskManager.check_trade_frequency(self.state.state['trades_last_hour'], self.state.state['daily_pnl']):
        #     logger.warning("🛑 Trade frequency limit reached! Skipping new entries.")
        #     return

        # 4. Update Daily PnL (reset if new day)
        # Check if we need to reset daily PnL (at 00:00 UTC)
        current_time_utc = time.gmtime(time.time())
        if self.state.state['last_reset_time']:
            last_reset = time.gmtime(self.state.state['last_reset_time'])
            if current_time_utc.tm_mday != last_reset.tm_mday:
                logger.info("🔄 New Day! Resetting Daily PnL.")
                self.state.reset_daily_pnl()
                self.state.state['last_reset_time'] = time.time()
                self.state.save_state()
        else:
             self.state.state['last_reset_time'] = time.time()
             self.state.save_state()

        # 5. Check Daily Stop
        balance_data = self.client.get_balance()
        if balance_data:
            usdt_balance = balance_data['USDT']['total'] # Use total balance (wallet balance)
            if not RiskManager.check_daily_stop(self.state.state['daily_pnl'], usdt_balance):
                logger.warning("🛑 Daily Stop Hit! Pausing strategy for today.")
                return
        
        # 6. Check Time Filter (Global)
        allow_entries = True
        if not TimeFilter.check_daily_close_window():
            logger.info("⏸️ Daily Close Window (23:45-00:15 UTC). New entries paused.")
            allow_entries = False
        
        # 6. Process each symbol
        # We must process Config.SYMBOLS (for entries) AND any active positions (for management)
        # even if they are not in the config list (e.g. orphans from other pairs).
        active_symbols = set(self.state.state['positions'].keys())
        target_symbols = set(Config.SYMBOLS)
        symbols_to_process = target_symbols.union(active_symbols)
        
        # OPPORTUNITY COST LOGIC:
        # We scan ALL symbols even if full. If we find a BETTER opportunity, we switch.
        
        logger.info(f"Starting loop for {len(symbols_to_process)} symbols")
        rejection_stats = Counter()
        
        active_positions_count = 0
        total_unrealized_pnl = 0.0
        
        # Track best opportunity found in this cycle
        best_opportunity = None
        
        for symbol in symbols_to_process:
            try:
                # Fetch Data
                ohlcv = self.client.fetch_ohlcv(symbol)
                if not ohlcv:
                    continue
                    
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = Indicators.calculate_all(df)
                
                # Ensure we have enough data for EMA200
                if pd.isna(df.iloc[-1]['EMA200']):
                    logger.warning(f"[{symbol}] Not enough data for EMA200. Fetched {len(df)} rows.")
                    continue

                current_price = df.iloc[-1]['close']
                
                # Check existing position
                position = self.state.get_position(symbol)
                
                if position:
                    active_positions_count += 1
                    
                    # Get Real PnL from Binance (preferred over calculation)
                    binance_data = self._get_binance_position_data(symbol)
                    if binance_data:
                        pnl = binance_data['unrealizedPnl']
                        pnl_pct = binance_data['percentage'] / 100  # Convert to decimal
                        logger.info(f"📊 {symbol} Position | PnL: ${pnl:.2f} ({pnl_pct:.2%}) | From Binance")
                    else:
                        # Fallback to calculation if Binance data unavailable
                        entry_price = position['entry_price']
                        size = position['size']
                        direction = position['direction']
                        
                        if direction == "LONG":
                            pnl = (current_price - entry_price) * size
                        else:
                            pnl = (entry_price - current_price) * size
                        logger.info(f"📊 {symbol} Position | PnL: ${pnl:.2f} (Calculated)")
                        
                    total_unrealized_pnl += pnl
                    
                    self._manage_position(symbol, position, df)
                    continue # Skip entry check for this symbol
                
                # Only look for NEW entries if the symbol is in our target list AND entries are allowed
                if symbol in target_symbols and allow_entries and not self.state.state['positions']:
                    # Use iloc[-2] for SIGNALS (Closed Candle)
                    # Use iloc[-1] for CURRENT PRICE (Execution/Context)
                    closed_candle = df.iloc[-2]
                    current_candle = df.iloc[-1]
                    
                    atr = closed_candle['ATR']
                    price = closed_candle['close']  # Price for signal checks is the close of the candle
                    current_price = current_candle['close']
                    
                    logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"📊 ANALYZING {symbol}")
                    logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"  • Closed Candle Price: {price:.4f}")
                    logger.info(f"  • Current Price: {current_price:.4f}")
                    logger.info(f"  • ATR: {atr:.4f} ({atr/price:.2%})")
                    
                    # Volatility Filter Check (ATR)
                    atr_check_pass = VolatilityFilters.check_atr(atr, price)
                    atr_min = Config.ATR_MIN_PCT
                    atr_max = Config.ATR_MAX_PCT
                    atr_pct = atr / price * 100  # Convert to percentage for display
                    if atr_check_pass:
                        logger.info(f"  ✅ ATR Filter: {atr_pct:.2%} (Range: {atr_min:.2%} - {atr_max:.2%})")
                    else:
                        logger.info(f"  ❌ ATR Filter: {atr_pct:.2%} OUT OF RANGE (Need: {atr_min:.2%} - {atr_max:.2%})")
                        rejection_stats['Volatility (ATR)'] += 1
                        continue  # Skip this symbol
                    
                    # Volatility Filter Check (Range Extreme)
                    range_check_pass = VolatilityFilters.check_range_extreme(df.iloc[:-1], atr)
                    if range_check_pass:
                        logger.info(f"  ✅ Range Filter: Sufficient volatility")
                    else:
                        logger.info(f"  ❌ Range Filter: Low volatility detected")
                        rejection_stats['Volatility (Range)'] += 1
                        continue  # Skip this symbol
                    
                    # Order Book Check
                    ob = self.client.get_order_book(symbol)
                    if not ob:
                        logger.info(f"  ❌ Order Book: Failed to fetch")
                        continue
                    
                    spread_check_pass = LiquiditySpreadFilters.check_spread(ob)
                    if spread_check_pass:
                        # Calculate actual spread
                        bid = ob['bids'][0][0]
                        ask = ob['asks'][0][0]
                        spread_pct = (ask - bid) / bid * 100
                        logger.info(f"  ✅ Spread: {spread_pct:.3f}% (Max: {Config.MAX_SPREAD_PCT*100:.3f}%)")
                    else:
                        logger.info(f"  ❌ Spread: Too high (Max: {Config.MAX_SPREAD_PCT*100:.3f}%)")
                        rejection_stats['Spread High'] += 1
                        continue  # Skip this symbol
                    
                    # Funding Rate
                    funding = self.client.get_funding_rate(symbol)
                    logger.info(f"  📊 Funding Rate: {funding:.4%}")

                    # Check Signals
                    # We pass the DF excluding the last open candle to ensure all indicators (Trend, Structure) use closed data
                    df_closed = df.iloc[:-1]
                    
                    logger.info(f"")
                    logger.info(f"  🔍 CHECKING ENTRY SIGNALS...")
                    
                    for direction in ["LONG", "SHORT"]:
                        # Signal Check
                        ok, details = EntrySignals.check_signals(df_closed, direction)
                        
                        # Log Details - ALWAYS show parameter by parameter
                        logger.info(f"")
                        logger.info(f"  {'═' * 44}")
                        logger.info(f"  📈 {direction} SIGNAL BREAKDOWN:")
                        logger.info(f"  {'═' * 44}")
                        for k, v in details.items():
                            status_icon = "✅" if v.get('status') else "❌"
                            value_str = v.get('value')
                            threshold_str = v.get('threshold', '')
                            
                            if threshold_str:
                                logger.info(f"    {status_icon} {k}: {value_str} (Requirement: {threshold_str})")
                            else:
                                logger.info(f"    {status_icon} {k}: {value_str}")
                            
                            # Track signal failures
                            if not v.get('status'):
                                rejection_stats[f"Signal: {k}"] += 1
                        
                        # If signal is OK, proceed with opportunity scoring and potential entry
                        if ok:
                            logger.info(f"")
                            logger.info(f"  🚀 ✅ ENTRY SIGNAL CONFIRMED: {direction}")
                            
                            # Calculate Score for this opportunity
                            score = EntrySignals.calculate_score(details)
                            logger.info(f"  ⭐ Opportunity Score: {score}/100")
                            logger.info(f"")
                            
                            # If we are NOT full, execute immediately
                            if RiskManager.check_max_symbols(self.state.state['positions']):
                                self._execute_entry(symbol, direction, df, details)
                                # Log immediate confirmation
                                logger.info(f"✅ Position opened! Monitor will track every 2 seconds.")
                                logger.info(f"📊 ACTIVE POSITIONS: 1")
                                return # Take one trade per cycle
                            else:
                                # We are FULL. Check if this is a better opportunity.
                                # We only consider switching if we haven't found a better one yet
                                if best_opportunity is None or score > best_opportunity['score']:
                                    best_opportunity = {
                                        'symbol': symbol,
                                        'direction': direction,
                                        'score': score,
                                        'df': df,
                                        'details': details
                                    }
                                    logger.info(f"  💡 Best opportunity updated: {symbol} {direction} (Score: {score})")
                        else:
                            logger.info(f"")
                            logger.info(f"  ❌ {direction} SIGNAL REJECTED")
                    
                    logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"")
                
                # The original `_look_for_entry` call is now effectively inlined and expanded here.
                # The `continue` from the snippet would skip the rest of the loop for this symbol,
                # which is not what `_look_for_entry` does (it just returns).
                # So, removing the `continue` here to allow the loop to naturally proceed to the next symbol
                # or the opportunity switching logic.
                    
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
        
        # End of Symbol Loop
        
        # OPPORTUNITY SWITCHING CHECK
        # If we found a great opportunity but were full, check if we should swap.
        if best_opportunity:
            self._check_opportunity_switch(best_opportunity)

        # Log Summary
        logger.info("=== 📉 TOP 3 REJECTION REASONS ===")
        for reason, count in rejection_stats.most_common(3):
            logger.info(f"  ❌ {reason}: {count} times")
        logger.info("====================================")
        
        # Log Active Positions Summary
        if active_positions_count > 0:
            logger.info(f"📊 ACTIVE POSITIONS: {active_positions_count}")
            logger.info(f"💰 UNREALIZED PnL: {total_unrealized_pnl:.2f} USDT (from Binance)")
            logger.info("====================================")
        else:
            logger.info("💤 NO ACTIVE POSITIONS")
            logger.info("====================================")

    def _look_for_entry(self, symbol, df, stats):
        # Symbol Cooldown Check
        if not self.state.check_symbol_cooldown(symbol, time.time()):
            stats['Symbol Cooldown'] += 1
            return
        
        # Time Filters - Moved to Global Check in _run_strategy_cycle
        # if not TimeFilter.check_daily_close_window():
        #     logger.info("Filter Fail: Daily Close Window (23:45-00:15 UTC)")
        #     return

        # Filters
        # Use iloc[-2] for SIGNALS (Closed Candle)
        # Use iloc[-1] for CURRENT PRICE (Execution/Context)
        closed_candle = df.iloc[-2]
        current_candle = df.iloc[-1]
        
        atr = closed_candle['ATR']
        price = closed_candle['close'] # Price for signal checks is the close of the candle
        current_price = current_candle['close']
        
        logger.info(f"--- Analyzing {symbol} Closed: {price:.2f} (ATR: {atr:.2f}) | Current: {current_price:.2f} ---")
        
        # Volatility (Check against Closed Candle data)
        if not VolatilityFilters.check_atr(atr, price):
            logger.info(f"Filter Fail: ATR {atr:.2f} ({atr/price:.2%}) out of range")
            stats['Volatility (ATR)'] += 1
            return
            
        if not VolatilityFilters.check_range_extreme(df.iloc[:-1], atr): # Exclude current open candle for range check
            logger.info("Filter Fail: Range Extreme (Low Volatility)")
            stats['Volatility (Range)'] += 1
            return
            
        # Order Book
        ob = self.client.get_order_book(symbol)
        if not ob: return
        
        if not LiquiditySpreadFilters.check_spread(ob):
            logger.info("Filter Fail: Spread too high")
            stats['Spread High'] += 1
            return
            
        # Funding
        funding = self.client.get_funding_rate(symbol)
        logger.info(f"Funding Rate: {funding:.4%}")
        
        # Check Signals
        # We pass the DF excluding the last open candle to ensure all indicators (Trend, Structure) use closed data
        df_closed = df.iloc[:-1]
        
        for direction in ["LONG", "SHORT"]:
            # Funding Check - DISABLED for 15min (funding charged every 8H, not relevant for 1-3H trades)
            # if not FundingFilter.check_funding(funding, direction):
            #     logger.info(f"Filter Fail: Funding {funding:.4%} bad for {direction}")
            #     stats[f'Funding ({direction})'] += 1
            #     continue
                
            # Signal Check
            ok, details = EntrySignals.check_signals(df_closed, direction)
            
            # Log Details
            log_msg = f"Signal Check {direction}:\n"
            for k, v in details.items():
                status_icon = "✅" if v.get('status') else "❌"
                log_msg += f"  {status_icon} {k}: {v.get('value')} (Req: {v.get('threshold', '')})\n"
                
                # Track signal failures
                if not v.get('status'):
                    stats[f"Signal: {k}"] += 1
            
            logger.info(log_msg)
            
            if ok:
                logger.info(f"🚀 ENTRY SIGNAL FOUND: {direction}")
                
                # Calculate Score for this opportunity
                score = EntrySignals.calculate_score(details)
                logger.info(f"⭐ Opportunity Score for {symbol}: {score}")
                
                # If we are NOT full, execute immediately
                if RiskManager.check_max_symbols(self.state.state['positions']):
                    self._execute_entry(symbol, direction, df, details)
                    return # Take one trade per cycle
                else:
                    # We are FULL. Check if this is a better opportunity.
                    # We only consider switching if we haven't found a better one yet
                    if best_opportunity is None or score > best_opportunity['score']:
                        best_opportunity = {
                            'symbol': symbol,
                            'direction': direction,
                            'score': score,
                            'df': df,
                            'details': details
                        }
                        
        # End of Symbol Loop
        
        # OPPORTUNITY SWITCHING CHECK
        # If we found a great opportunity but were full, check if we should swap.
        if best_opportunity:
            self._check_opportunity_switch(best_opportunity)

    def _calculate_position_health(self, symbol, pos_data, current_price, df):
        """
        Calculate health score (0-100) for current position.
        Higher score = healthier position that should be kept.
        """
        score = 0
        details = {}
        
        direction = pos_data['direction']
        entry_price = pos_data['entry_price']
        entry_time = pos_data['entry_time']
        
        # Calculate current PnL%
        if direction == "LONG":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price
        
        # 1. PnL TREND (30 pts) - Is it improving?
        pnl_history = pos_data.get('pnl_history', [])
        if len(pnl_history) >= 2:
            # Compare last pnl with previous
            if pnl_history[-1] > pnl_history[-2]:
                score += 30
                details['PnL Trend'] = f"✅ Growing ({pnl_history[-2]:.2%} → {pnl_history[-1]:.2%})"
            elif pnl_history[-1] > pnl_history[-2] - 0.001:  # Stable (within 0.1%)
                score += 15
                details['PnL Trend'] = f"⚖️ Stable ({pnl_history[-1]:.2%})"
            else:
                details['PnL Trend'] = f"❌ Declining ({pnl_history[-2]:.2%} → {pnl_history[-1]:.2%})"
        else:
            # First evaluation, give partial credit if positive
            if pnl_pct > 0:
                score += 15
                details['PnL Trend'] = f"⚖️ New position ({pnl_pct:.2%})"
            else:
                details['PnL Trend'] = f"⚖️ New position ({pnl_pct:.2%})"
        
        # 2. SL MOVEMENTS (25 pts) - Has it achieved profit?
        sl_moved = pos_data.get('sl_moved_count', 0)
        if sl_moved >= 3:
            score += 25
            details['SL History'] = f"✅ Moved {sl_moved}x (strong profit)"
        elif sl_moved >= 1:
            score += 15
            details['SL History'] = f"✅ Moved {sl_moved}x"
        else:
            details['SL History'] = "❌ No moves yet"
        
        # 3. TECHNICAL MOMENTUM (25 pts) - Direction alignment
        try:
            last_candle = df.iloc[-1]
            macd_line = last_candle['MACD_line']
            macd_signal = last_candle['MACD_signal']
            rsi = last_candle['RSI']
            ema8 = last_candle['EMA8']
            ema20 = last_candle['EMA20']
            
            momentum_score = 0
            momentum_details = []
            
            # MACD alignment
            if direction == "LONG":
                if macd_line > macd_signal:
                    momentum_score += 10
                    momentum_details.append("MACD✅")
                else:
                    momentum_details.append("MACD❌")
            else:  # SHORT
                if macd_line < macd_signal:
                    momentum_score += 10
                    momentum_details.append("MACD✅")
                else:
                    momentum_details.append("MACD❌")
            
            # RSI (not overbought/oversold)
            if direction == "LONG":
                if 45 < rsi < 70:
                    momentum_score += 8
                    momentum_details.append(f"RSI✅({rsi:.0f})")
                else:
                    momentum_details.append(f"RSI⚖️({rsi:.0f})")
            else:  # SHORT
                if 30 < rsi < 55:
                    momentum_score += 8
                    momentum_details.append(f"RSI✅({rsi:.0f})")
                else:
                    momentum_details.append(f"RSI⚖️({rsi:.0f})")
            
            # EMA alignment
            if direction == "LONG":
                if ema8 > ema20:
                    momentum_score += 7
                    momentum_details.append("EMA✅")
                else:
                    momentum_details.append("EMA❌")
            else:  # SHORT
                if ema8 < ema20:
                    momentum_score += 7
                    momentum_details.append("EMA✅")
                else:
                    momentum_details.append("EMA❌")
            
            score += momentum_score
            details['Momentum'] = f"{', '.join(momentum_details)}"
        except Exception as e:
            details['Momentum'] = "❌ Error calculating"
        
        # 4. TIME FACTOR (20 pts) - Penalize stagnation
        age_minutes = (time.time() - entry_time) / 60
        if age_minutes < 15:
            score += 20
            details['Time Factor'] = f"✅ Fresh ({age_minutes:.1f}m)"
        elif age_minutes < 30:
            score += 10
            details['Time Factor'] = f"⚖️ Moderate ({age_minutes:.1f}m)"
        else:
            # After 30 min, score depends on performance
            if pnl_pct > 0.003:  # If >0.3% profit, age doesn't matter much
                score += 15
                details['Time Factor'] = f"✅ Mature but profitable ({age_minutes:.1f}m, +{pnl_pct:.2%})"
            else:
                details['Time Factor'] = f"❌ Stagnant ({age_minutes:.1f}m, {pnl_pct:.2%})"
        
        return score, details

    def _check_opportunity_switch(self, new_opp):
        """
        Intelligent Position Evaluation & Switching.
        Only switches if current position is unhealthy AND new opportunity is significantly better.
        Displays detailed evaluation every 15 minutes.
        """
        new_symbol = new_opp['symbol']
        new_score = new_opp['score']
        new_direction = new_opp['direction']
        
        logger.info("=" * 60)
        logger.info("📊 POSITION EVALUATION (Every 15m)")
        logger.info("=" * 60)
        
        # Iterate through current positions
        for current_symbol, pos_data in self.state.state['positions'].items():
            entry_price = pos_data['entry_price']
            direction = pos_data['direction']
            entry_time = pos_data['entry_time']
            age_minutes = (time.time() - entry_time) / 60
            
            # Get current price and fetch DF for analysis
            try:
                ohlcv = self.client.fetch_ohlcv(current_symbol)
                if not ohlcv:
                    logger.warning(f"Could not fetch OHLCV for {current_symbol}, skipping evaluation.")
                    continue
                    
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df = Indicators.calculate_all(df)
                current_price = df.iloc[-1]['close']
            except Exception as e:
                logger.warning(f"Error fetching data for {current_symbol}: {e}")
                continue
            
            # Calculate current PnL
            if direction == "LONG":
                pnl_pct = (current_price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - current_price) / entry_price
            
            pnl_usd = pnl_pct * (pos_data['size'] * entry_price)
            
            # Update PnL history
            pnl_history = pos_data.get('pnl_history', [])
            pnl_history.append(pnl_pct)
            if len(pnl_history) > 5:  # Keep last 5 evaluations
                pnl_history = pnl_history[-5:]
            pos_data['pnl_history'] = pnl_history
            pos_data['last_evaluation_time'] = time.time()
            self.state.set_position(current_symbol, pos_data)
            
            # Calculate Position Health
            health_score, health_details = self._calculate_position_health(current_symbol, pos_data, current_price, df)
            
            # Log Current Position Evaluation
            logger.info(f"\nCurrent Position: {current_symbol} {direction}")
            logger.info(f"  • Entry: {entry_price:.4f} | Current: {current_price:.4f} | PnL: {pnl_pct:+.2%} ({pnl_usd:+.2f} USD)")
            logger.info(f"  • Age: {age_minutes:.1f}m | SL Moved: {pos_data.get('sl_moved_count', 0)}x")
            logger.info(f"  • Health Score: {health_score}/100")
            for key, value in health_details.items():
                logger.info(f"    - {key}: {value}")
            
            # Log Alternative Opportunity
            logger.info(f"\nAlternative Opportunity:")
            logger.info(f"  • {new_symbol} {new_direction} - Score: {new_score}/100")
            
            # DECISION LOGIC
            # NEVER switch if:
            # 1. SL has moved (position has achieved profit)
            # 2. Position is less than 15 min old
            # 3. Health score is >= 60 (healthy position)
            # 4. Current PnL is > 0.3%
            
            sl_moved = pos_data.get('sl_moved_count', 0)
            
            if sl_moved > 0:
                logger.info(f"\n✅ DECISION: KEEP {current_symbol}")
                logger.info(f"REASON: SL moved {sl_moved}x - Position has achieved profit")
                logger.info("=" * 60)
                return
            
            if pnl_pct > 0.003:
                logger.info(f"\n✅ DECISION: KEEP {current_symbol}")
                logger.info(f"REASON: Profitable position ({pnl_pct:+.2%})")
                logger.info("=" * 60)
                return
            
            if age_minutes < 15:
                logger.info(f"\n✅ DECISION: KEEP {current_symbol}")
                logger.info(f"REASON: Too fresh ({age_minutes:.1f}m < 15m minimum)")
                logger.info("=" * 60)
                return
            
            if health_score >= 60:
                logger.info(f"\n✅ DECISION: KEEP {current_symbol}")
                logger.info(f"REASON: Healthy position (Score {health_score} >= 60)")
                logger.info("=" * 60)
                return
            
            # Consider switching ONLY if:
            # - Position age >= 30 min without growth
            # - Health score < 40 (unhealthy)
            # - New opportunity score >= 80 (very strong)
            # - New score > Health score + 30 (significantly better)
            
            MIN_AGE_FOR_SWITCH = 30  # minutes
            MAX_HEALTH_TO_SWITCH = 40
            MIN_NEW_SCORE = 80
            SCORE_DIFF_REQUIRED = 30
            
            can_switch = (
                age_minutes >= MIN_AGE_FOR_SWITCH and
                health_score < MAX_HEALTH_TO_SWITCH and
                new_score >= MIN_NEW_SCORE and
                new_score > health_score + SCORE_DIFF_REQUIRED
            )
            
            if can_switch:
                logger.info(f"\n♻️ DECISION: SWITCH {current_symbol} → {new_symbol}")
                logger.info(f"REASON:")
                logger.info(f"  • Age: {age_minutes:.1f}m >= {MIN_AGE_FOR_SWITCH}m")
                logger.info(f"  • Health: {health_score} < {MAX_HEALTH_TO_SWITCH} (unhealthy)")
                logger.info(f"  • New Score: {new_score} >= {MIN_NEW_SCORE} (very strong)")
                logger.info(f"  • Score Diff: {new_score - health_score} > {SCORE_DIFF_REQUIRED}")
                logger.info("=" * 60)
                
                # Execute Switch
                logger.info(f"👋 Closing {current_symbol}...")
                self.executor.close_position(current_symbol, direction, pos_data['size'])
                self.state.clear_position(current_symbol)
                
                logger.info(f"🚀 Opening {new_symbol}...")
                self._execute_entry(new_opp['symbol'], new_opp['direction'], new_opp['df'], new_opp['details'])
                return
            else:
                logger.info(f"\n✅ DECISION: KEEP {current_symbol}")
                logger.info(f"REASON: Switch criteria not met")
                if age_minutes < MIN_AGE_FOR_SWITCH:
                    logger.info(f"  • Age: {age_minutes:.1f}m < {MIN_AGE_FOR_SWITCH}m")
                if health_score >= MAX_HEALTH_TO_SWITCH:
                    logger.info(f"  • Health: {health_score} >= {MAX_HEALTH_TO_SWITCH}")
                if new_score < MIN_NEW_SCORE:
                    logger.info(f"  • New Score: {new_score} < {MIN_NEW_SCORE}")
                if new_score <= health_score + SCORE_DIFF_REQUIRED:
                    logger.info(f"  • Score Diff: {new_score - health_score} <= {SCORE_DIFF_REQUIRED}")
                logger.info("=" * 60)
                return
        
        logger.info("\n✋ No position to evaluate.")
        logger.info("=" * 60)

    def _execute_entry(self, symbol, direction, df, signal_details=None):
        # Risk Check
        if not RiskManager.check_max_symbols(self.state.state['positions']):
            return

        # Correlation Check
        if not RiskManager.check_portfolio_correlation(symbol, self.state.state['positions'], self.client):
            logger.warning(f"Entry rejected for {symbol}: High correlation with existing portfolio.")
            return
            
        balance_data = self.client.get_balance()
        if not balance_data: return
        
        usdt_balance = balance_data['USDT']['free']
        
        last = df.iloc[-1]
        atr = last['ATR']
        entry_price = last['close']
        
        sl_price = ATRManager.calculate_initial_stop(entry_price, atr, direction)
        
        # Calculate Size with Fixed Exposure (now includes total exposure check and min size validation)
        position_size = RiskManager.calculate_position_size(
            entry_price, 
            sl_price, 
            usdt_balance,
            self.client,
            symbol,
            self.state.state['positions']
        )
        
        if position_size <= 0:
            logger.error("Position size 0, aborting entry.")
            return

        logger.info(f"Executing {direction} | Size: {position_size:.4f} | Estimated Entry: {entry_price} | SL: {sl_price}")
        
        # Enforce Leverage again before entry (Safety)
        leverage = Config.LEVERAGE # Default to Config leverage (usually 1 or 3)
        self.client.set_leverage(symbol, leverage)
        
        # Execute
        order = self.executor.open_position(symbol, direction, position_size)
        if order:
            # Get ACTUAL fill price from Binance order response
            # CCXT normalizes the response; 'average' contains the actual fill price
            actual_entry_price = order.get('average') or order.get('price') or entry_price
            actual_size = order.get('filled') or position_size
            
            # Log the actual execution details
            logger.info(f"✅ Order Filled | Actual Entry: {actual_entry_price:.4f} | Actual Size: {actual_size:.6f}")
            
            # Save State with ACTUAL values from Binance
            pos_data = {
                "direction": direction,
                "entry_price": actual_entry_price,  # Use actual fill price from Binance
                "size": actual_size,  # Use actual filled size from Binance
                "sl_price": sl_price,
                "atr_entry": atr,
                "p_max": actual_entry_price, # Track highest favorable price (for trailing)
                "p_min": actual_entry_price, # Track lowest favorable price (for trailing)
                "partials": {f"p{i+1}": False for i in range(len(Config.TAKE_PROFIT_LEVELS))},  # Dynamic based on config
                "entry_time": time.time(),
                "last_sl_update": time.time(),  # Track when SL was last updated
                # Health tracking for intelligent switching
                "sl_moved_count": 0,  # How many times SL was moved (profit indicator)
                "pnl_history": [],  # Track PnL % at each 15min evaluation
                "last_evaluation_time": time.time()  # Last time we evaluated this position
            }
            self.state.set_position(symbol, pos_data)
            
            # Record trade timestamp for frequency tracking
            self.state.add_trade_timestamp(time.time())
            logger.info(f"✅ Trade timestamp recorded. Total trades in last hour: {len(self.state.state['trades_last_hour'])}")
            
            # Set Initial SL
            self.executor.set_stop_loss(symbol, direction, sl_price)

            # Set Take Profit
            # SNIPER STRATEGY: Set Fixed TP immediately
            # Check if we have a single "TP_FINAL" level configured
            is_sniper_mode = len(Config.TP_LEVELS) == 1 and Config.TP_LEVELS[0].get('name') == 'TP_FINAL'
            
            if is_sniper_mode:
                tp_pct = Config.TP_LEVELS[0]['pct']
                if direction == "LONG":
                    tp_price = actual_entry_price * (1 + tp_pct)
                else:
                    tp_price = actual_entry_price * (1 - tp_pct)
                
                logger.info(f"🎯 Setting SNIPER TP at {tp_price:.4f} (+{tp_pct:.2%})")
                self.executor.set_take_profit(symbol, direction, tp_price)
            else:
                # Fallback / Legacy: Use a default emergency TP if not in Sniper mode
                # Since EMERGENCY_TP_PCT was removed, we use a hardcoded safe value (e.g. 20%)
                safe_tp_pct = 0.20
                if direction == "LONG":
                    tp_price = actual_entry_price * (1 + safe_tp_pct)
                else:
                    tp_price = actual_entry_price * (1 - safe_tp_pct)
                
                logger.info(f"🚀 Setting Safety Hard TP at {tp_price:.4f} (+{safe_tp_pct:.0%})")
                self.executor.set_take_profit(symbol, direction, tp_price)
            
            # Log to CSV (ABIERTOS)
            try:
                # Calculate Metrics
                exposure = actual_size * actual_entry_price
                margin = exposure / leverage
                
                # Prepare Criteria
                criteria = {}
                if signal_details:
                    for k, v in signal_details.items():
                        criteria[k] = v.get('value', 'N/A')
                else:
                    # Fallback if no details passed
                    criteria = {
                        'RSI': last['RSI'],
                        'ADX': last['ADX']
                    }

                CSVManager.log_entry(
                    symbol=symbol,
                    entry_time=time.time(),
                    margin=margin,
                    exposure=exposure,
                    leverage=leverage,
                    criteria=criteria
                )
            except Exception as e:
                logger.error(f"Failed to log entry CSV: {e}")


    def _manage_position(self, symbol, position, df):
        # Use Closed Candle for Logic (Trend, Structure, Trailing Update)
        closed_candle = df.iloc[-2]
        # Previous closed candle (for slope calculation)
        prev_closed_candle = df.iloc[-3]
        
        # We track P_max/P_min based on the CLOSED candle's High/Low to avoid noise
        closed_high = closed_candle['high']
        closed_low = closed_candle['low']
        closed_close = closed_candle['close']
        closed_atr = closed_candle['ATR']
        
        direction = position['direction']
        entry_price = position['entry_price']
        atr_entry = position['atr_entry']
        entry_time = position['entry_time']
        logger.info(f"🔧 Managing position for {symbol}: direction={direction}, entry_price={entry_price}")
        
        # Update P_max / P_min using Closed Candle data
        if direction == "LONG":
            if closed_high > position['p_max']:
                position['p_max'] = closed_high
        else:
            if closed_low < position['p_min']:
                position['p_min'] = closed_low
        logger.info(f"📈 Updated P_max/P_min: P_max={position.get('p_max')}, P_min={position.get('p_min')}")
            
        # --- EXIT CONDITIONS (Priority Order) ---
        
        # 0. Early Invalidation (Moved to Real-Time Monitor)
        
        logger.info("🔎 Checking ATR Extreme condition")
        # 1. ATR Extreme (ATR_actual > 1.8 * ATR_entry)
        if closed_atr > 1.8 * atr_entry:
            logger.info(f"🚨 EXIT: ATR Extreme ({closed_atr:.2f} > 1.8x {atr_entry:.2f})")
            self.executor.close_position(symbol, direction, position['size'])
            
            # Log Closure
            try:
                exit_price = closed_close
                pnl_usd = (exit_price - entry_price) * position['size'] if direction == "LONG" else (entry_price - exit_price) * position['size']
                pnl_pct = (exit_price - entry_price) / entry_price if direction == "LONG" else (entry_price - exit_price) / entry_price
                duration = time.time() - entry_time
                
                # Log Closure (CERRADOS)
                leverage = Config.LEVERAGE
                exposure = position['size'] * entry_price
                margin = exposure / leverage
                
                CSVManager.log_closure(
                    symbol=symbol,
                    close_time=time.time(),
                    pnl_usd=pnl_usd,
                    margin=margin,
                    leverage=leverage,
                    exposure=exposure,
                    duration_sec=duration,
                    info="ATR Extreme"
                )
                
                # ML Update (Total PnL - Commissions)
                total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                
                # Commission Calculation
                total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                commission = total_volume * 0.0005
                net_pnl_usd = total_pnl_usd - commission
                
                initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                
                # Max PnL Calculation
                if direction == "LONG":
                    max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                else:
                    max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                # Build partial data for ML
                partial_data = {
                    'partial_pnl_usd': position.get('accumulated_pnl', 0),
                    'final_pnl_usd': total_pnl_usd,
                    'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                }
                
                logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                
                # Save Tuner State
                self.state.state['tuner'] = self.tuner.get_state()
                self.state.save_state()
            except Exception as e:
                logger.error(f"Failed to log closure CSV: {e}")

            self.state.clear_position(symbol)
            return

        logger.info("🔎 Checking Structure Break condition")
        # 2. Structure Break (Swing High/Low)
        swings = StructureManager.get_last_swings(df)
        if swings:
            if direction == "LONG":
                # Bullish Structure Break: Close < Last Swing Low
                if swings['swing_low'] and closed_close < swings['swing_low']:
                    logger.info(f"📉 EXIT: Structure Break (Close {closed_close:.2f} < Swing Low {swings['swing_low']:.2f})")
                    self.executor.close_position(symbol, direction, position['size'])
                    
                    # Log Closure
                    try:
                        exit_price = closed_close
                        pnl_usd = (exit_price - entry_price) * position['size']
                        pnl_pct = (exit_price - entry_price) / entry_price
                        duration = time.time() - entry_time
                        
                        # Log Closure (CERRADOS)
                        leverage = Config.LEVERAGE
                        exposure = position['size'] * entry_price
                        margin = exposure / leverage
                        
                        CSVManager.log_closure(
                            symbol=symbol,
                            close_time=time.time(),
                            pnl_usd=pnl_usd,
                            margin=margin,
                            leverage=leverage,
                            exposure=exposure,
                            duration_sec=duration,
                            info="Structure Break (Swing Low)"
                        )
                        
                        # ML Update (Total PnL - Commissions)
                        total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                        
                        # Commission Calculation
                        total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                        commission = total_volume * 0.0005
                        net_pnl_usd = total_pnl_usd - commission
                        
                        initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                        net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                        
                        # Max PnL Calculation
                        if direction == "LONG":
                            max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                        else:
                            max_pnl_pct = (entry_price - position['p_min']) / entry_price
                        
                        # Build partial data for ML
                        partial_data = {
                            'partial_pnl_usd': position.get('accumulated_pnl', 0),
                            'final_pnl_usd': total_pnl_usd,
                            'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                        }
                        
                        logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                        self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                        
                        # Save Tuner State
                        self.state.state['tuner'] = self.tuner.get_state()
                        self.state.save_state()
                    except Exception as e:
                        logger.error(f"Failed to log closure CSV: {e}")

                    self.state.clear_position(symbol)
                    return
            else: # SHORT
                # Bearish Structure Break: Close > Last Swing High
                if swings['swing_high'] and closed_close > swings['swing_high']:
                    logger.info(f"📈 EXIT: Structure Break (Close {closed_close:.2f} > Swing High {swings['swing_high']:.2f})")
                    self.executor.close_position(symbol, direction, position['size'])
                    
                    # Log Closure
                    try:
                        exit_price = closed_close
                        pnl_usd = (entry_price - exit_price) * position['size']
                        pnl_pct = (entry_price - exit_price) / entry_price
                        duration = time.time() - entry_time
                        
                        # Log Closure (CERRADOS)
                        leverage = Config.LEVERAGE
                        exposure = position['size'] * entry_price
                        margin = exposure / leverage
                        
                        CSVManager.log_closure(
                            symbol=symbol,
                            close_time=time.time(),
                            pnl_usd=pnl_usd,
                            margin=margin,
                            leverage=leverage,
                            exposure=exposure,
                            duration_sec=duration,
                            info="Structure Break (Swing High)"
                        )
                        
                        # ML Update (Total PnL - Commissions)
                        total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                        
                        # Commission Calculation (Entry + Exit Volume * 0.05%)
                        total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                        commission = total_volume * 0.0005
                        net_pnl_usd = total_pnl_usd - commission
                        
                        initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                        net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                        
                        # Max PnL Calculation
                        if direction == "LONG":
                            max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                        else:
                            max_pnl_pct = (entry_price - position['p_min']) / entry_price
                        
                        # Build partial data for ML
                        partial_data = {
                            'partial_pnl_usd': position.get('accumulated_pnl', 0),
                            'final_pnl_usd': total_pnl_usd,
                            'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                        }
                        
                        logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                        self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                        
                        # Save Tuner State
                        self.state.state['tuner'] = self.tuner.get_state()
                        self.state.save_state()
                    except Exception as e:
                        logger.error(f"Failed to log closure CSV: {e}")

                    self.state.clear_position(symbol)
                    return
        
        logger.info("🔎 Checking MACD Reversal condition")
        # 3. MACD Reversal Exit (New)
        # If MACD Histogram flips against us, it's a strong sign of momentum loss.
        macd_hist = closed_candle.get('MACD_hist', 0)
        macd_hist_prev = prev_closed_candle.get('MACD_hist', 0)
        
        # Check for Reversal
        macd_reversal = False
        if direction == "LONG":
            # Bullish trade, but Hist becomes negative or drops significantly
            if macd_hist < 0 and macd_hist < macd_hist_prev:
                macd_reversal = True
                logger.info(f"📉 EXIT: MACD Reversal (Hist {macd_hist:.4f} < 0)")
        else:
            # Bearish trade, but Hist becomes positive or rises significantly
            if macd_hist > 0 and macd_hist > macd_hist_prev:
                macd_reversal = True
                logger.info(f"📈 EXIT: MACD Reversal (Hist {macd_hist:.4f} > 0)")
                
        if macd_reversal:
            self.executor.close_position(symbol, direction, position['size'])
            
            # Log Closure
            try:
                exit_price = closed_close
                pnl_usd = (exit_price - entry_price) * position['size'] if direction == "LONG" else (entry_price - exit_price) * position['size']
                pnl_pct = (exit_price - entry_price) / entry_price if direction == "LONG" else (entry_price - exit_price) / entry_price
                duration = time.time() - entry_time
                
                # Log Closure (CERRADOS)
                leverage = Config.LEVERAGE
                exposure = position['size'] * entry_price
                margin = exposure / leverage
                
                CSVManager.log_closure(
                    symbol=symbol,
                    close_time=time.time(),
                    pnl_usd=pnl_usd,
                    margin=margin,
                    leverage=leverage,
                    exposure=exposure,
                    duration_sec=duration,
                    info="MACD Reversal"
                )
                
                # ML Update
                total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                commission = total_volume * 0.0005
                net_pnl_usd = total_pnl_usd - commission
                initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                
                if direction == "LONG":
                    max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                else:
                    max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                partial_data = {
                    'partial_pnl_usd': position.get('accumulated_pnl', 0),
                    'final_pnl_usd': total_pnl_usd,
                    'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                }
                
                self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                self.state.state['tuner'] = self.tuner.get_state()
                self.state.save_state()
            except Exception as e:
                logger.error(f"Failed to log closure CSV: {e}")

            self.state.clear_position(symbol)
            return

        logger.info("🔎 Checking Hard EMA20 vs EMA50 cross condition")
        # 4. Hard Exit (EMA20 vs EMA50 Cross)
        ema20 = closed_candle['EMA20']
        ema50 = closed_candle['EMA50']
        
        if direction == "LONG" and ema20 < ema50:
            logger.info(f"📉 EXIT: Hard Cross EMA20 < EMA50 ({ema20:.2f} < {ema50:.2f})")
            self.executor.close_position(symbol, direction, position['size'])
            
            # Log Closure
            try:
                exit_price = closed_close
                pnl_usd = (exit_price - entry_price) * position['size']
                pnl_pct = (exit_price - entry_price) / entry_price
                duration = time.time() - entry_time
                
                # Log Closure (CERRADOS)
                leverage = Config.LEVERAGE
                exposure = position['size'] * entry_price
                margin = exposure / leverage
                
                CSVManager.log_closure(
                    symbol=symbol,
                    close_time=time.time(),
                    pnl_usd=pnl_usd,
                    margin=margin,
                    leverage=leverage,
                    exposure=exposure,
                    duration_sec=duration,
                    info="Hard Cross Exit"
                )
                
                # ML Update (Total PnL - Commissions)
                total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                
                # Commission Calculation
                total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                commission = total_volume * 0.0005
                net_pnl_usd = total_pnl_usd - commission
                
                initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                
                # Max PnL Calculation
                if direction == "LONG":
                    max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                else:
                    max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                # Build partial data for ML
                partial_data = {
                    'partial_pnl_usd': position.get('accumulated_pnl', 0),
                    'final_pnl_usd': total_pnl_usd,
                    'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                }
                
                logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                
                # Save Tuner State
                self.state.state['tuner'] = self.tuner.get_state()
                self.state.save_state()
            except Exception as e:
                logger.error(f"Failed to log closure CSV: {e}")

            self.state.clear_position(symbol)
            return
        elif direction == "SHORT" and ema20 > ema50:
            logger.info(f"📈 EXIT: Hard Cross EMA20 > EMA50 ({ema20:.2f} > {ema50:.2f})")
            self.executor.close_position(symbol, direction, position['size'])
            
            # Log Closure
            try:
                exit_price = closed_close
                pnl_usd = (entry_price - exit_price) * position['size']
                pnl_pct = (entry_price - exit_price) / entry_price
                duration = time.time() - entry_time
                
                # Log Closure (CERRADOS)
                leverage = Config.LEVERAGE
                exposure = position['size'] * entry_price
                margin = exposure / leverage
                
                CSVManager.log_closure(
                    symbol=symbol,
                    close_time=time.time(),
                    pnl_usd=pnl_usd,
                    margin=margin,
                    leverage=leverage,
                    exposure=exposure,
                    duration_sec=duration,
                    info="Hard Cross Exit"
                )
                
                # ML Update (Total PnL - Commissions)
                total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                
                # Commission Calculation
                total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                commission = total_volume * 0.0005
                net_pnl_usd = total_pnl_usd - commission
                
                initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                
                # Max PnL Calculation
                if direction == "LONG":
                    max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                else:
                    max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                # Build partial data for ML
                partial_data = {
                    'partial_pnl_usd': position.get('accumulated_pnl', 0),
                    'final_pnl_usd': total_pnl_usd,
                    'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                }
                
                logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                
                # Save Tuner State
                self.state.state['tuner'] = self.tuner.get_state()
                self.state.save_state()
            except Exception as e:
                logger.error(f"Failed to log closure CSV: {e}")

            self.state.clear_position(symbol)
            return

        logger.info("🔎 Checking Stagnation Exit condition (>45m & negative PnL)")
        # 5. Stagnation Exit (>45m & Negative PnL)
        # If trade is open for 3 candles (45m) and is losing money, cut it.
        time_elapsed = time.time() - entry_time
        current_pnl_pct = (closed_close - entry_price) / entry_price if direction == "LONG" else (entry_price - closed_close) / entry_price
        
        if time_elapsed > 45 * 60 and current_pnl_pct < 0:
            logger.info(f"⏳ EXIT: Stagnation (Negative PnL {current_pnl_pct:.2%} after 45m)")
            self.executor.close_position(symbol, direction, position['size'])
            
            # Log Closure
            try:
                exit_price = closed_close
                pnl_usd = (exit_price - entry_price) * position['size'] if direction == "LONG" else (entry_price - exit_price) * position['size']
                duration = time.time() - entry_time
                
                # Log Closure (CERRADOS)
                leverage = Config.LEVERAGE
                exposure = position['size'] * entry_price
                margin = exposure / leverage
                
                CSVManager.log_closure(
                    symbol=symbol,
                    close_time=time.time(),
                    pnl_usd=pnl_usd,
                    margin=margin,
                    leverage=leverage,
                    exposure=exposure,
                    duration_sec=duration,
                    info="Stagnation Exit"
                )
                
                # ML Update (Total PnL - Commissions)
                total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                
                # Commission Calculation
                total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                commission = total_volume * 0.0005
                net_pnl_usd = total_pnl_usd - commission
                
                initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                
                # Max PnL Calculation
                if direction == "LONG":
                    max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                else:
                    max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                # Build partial data for ML
                partial_data = {
                    'partial_pnl_usd': position.get('accumulated_pnl', 0),
                    'final_pnl_usd': total_pnl_usd,
                    'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                }
                
                logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                
                # Save Tuner State
                self.state.state['tuner'] = self.tuner.get_state()
                self.state.save_state()
            except Exception as e:
                logger.error(f"Failed to log closure CSV: {e}")

            self.state.clear_position(symbol)
            return

        logger.info("🔎 Checking Time Exit condition (>40 candles & low PnL)")
        # 6. Time Exit (>40 candles and |PnL| < 0.2%)
        # 40 candles * 15 min = 600 min = 36000 seconds
        time_elapsed = time.time() - entry_time
        if time_elapsed > 36000:
            # Calculate PnL %
            pnl_pct = (closed_close - entry_price) / entry_price if direction == "LONG" else (entry_price - closed_close) / entry_price
            if abs(pnl_pct) < 0.002:
                logger.info(f"⏳ EXIT: Time Limit (>40 candles) & Low PnL ({pnl_pct:.2%})")
                self.executor.close_position(symbol, direction, position['size'])
                
                # Log Closure
                try:
                    exit_price = closed_close
                    pnl_usd = (exit_price - entry_price) * position['size'] if direction == "LONG" else (entry_price - exit_price) * position['size']
                    duration = time.time() - entry_time
                    
                    # Log Closure (CERRADOS)
                    leverage = Config.LEVERAGE
                    exposure = position['size'] * entry_price
                    margin = exposure / leverage
                    
                    CSVManager.log_closure(
                        symbol=symbol,
                        close_time=time.time(),
                        pnl_usd=pnl_usd,
                        margin=margin,
                        leverage=leverage,
                        exposure=exposure,
                        duration_sec=duration,
                        info="Time Limit"
                    )
                
                    # ML Update (Total PnL - Commissions)
                    total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                    
                    # Commission Calculation
                    total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                    commission = total_volume * 0.0005
                    net_pnl_usd = total_pnl_usd - commission
                    
                    initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                    net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                    
                    # Max PnL Calculation
                    if direction == "LONG":
                        max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                    else:
                        max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                    # Build partial data for ML
                    partial_data = {
                        'partial_pnl_usd': position.get('accumulated_pnl', 0),
                        'final_pnl_usd': total_pnl_usd,
                        'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                    }
                    
                    logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                    self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                    
                    # Save Tuner State
                    self.state.state['tuner'] = self.tuner.get_state()
                    self.state.save_state()
                except Exception as e:
                    logger.error(f"Failed to log closure CSV: {e}")

                self.state.clear_position(symbol)
                return

        logger.info("🔎 Checking Soft Trend Exit condition with MACD filter")
        # 7. Soft Exit (Slope EMA20) - WITH MACD FILTER
        # Slope = EMA20_current - EMA20_prev
        ema20_prev = prev_closed_candle['EMA20']
        slope = ema20 - ema20_prev
        
        # Check MACD Momentum (if strong, skip soft exit)
        macd_strong = False
        if direction == "LONG":
            # Strong Bullish Momentum: Hist > 0 and Rising
            if macd_hist > 0 and macd_hist > macd_hist_prev:
                macd_strong = True
        else:
            # Strong Bearish Momentum: Hist < 0 and Falling (more negative)
            if macd_hist < 0 and macd_hist < macd_hist_prev:
                macd_strong = True
        
        if macd_strong:
            logger.info(f"💪 MACD Strong Momentum ({macd_hist:.4f}). Skipping Soft Exit checks.")
        else:
            if direction == "LONG":
                # "pendiente EMA20 <= 0 durante 2 velas y cierre < EMA20"
                if slope <= 0 and closed_close < ema20:
                     logger.info(f"📉 EXIT: Soft Trend (Slope <= 0 & Close < EMA20)")
                     self.executor.close_position(symbol, direction, position['size'])
                     
                     # Log Closure
                     try:
                        exit_price = closed_close
                        pnl_usd = (exit_price - entry_price) * position['size']
                        pnl_pct = (exit_price - entry_price) / entry_price
                        duration = time.time() - entry_time
                        
                        # Log Closure (CERRADOS)
                        leverage = Config.LEVERAGE
                        exposure = position['size'] * entry_price
                        margin = exposure / leverage
                        
                        CSVManager.log_closure(
                            symbol=symbol,
                            close_time=time.time(),
                            pnl_usd=pnl_usd,
                            margin=margin,
                            leverage=leverage,
                            exposure=exposure,
                            duration_sec=duration,
                            info="Soft Trend Exit"
                        )
                        
                        # ML Update (Total PnL - Commissions)
                        total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                        
                        # Commission Calculation
                        total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                        commission = total_volume * 0.0005
                        net_pnl_usd = total_pnl_usd - commission
                        
                        initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                        net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                        
                        # Max PnL Calculation
                        if direction == "LONG":
                            max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                        else:
                            max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                        # Build partial data for ML
                        partial_data = {
                            'partial_pnl_usd': position.get('accumulated_pnl', 0),
                            'final_pnl_usd': total_pnl_usd,
                            'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                        }
                        
                        logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                        self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                        
                        # Save Tuner State
                        self.state.state['tuner'] = self.tuner.get_state()
                        self.state.save_state()
                     except Exception as e:
                        logger.error(f"Failed to log closure CSV: {e}")
    
                     self.state.clear_position(symbol)
                     return
            elif direction == "SHORT":
                # "pendiente >= 0 dos velas y cierre > EMA20"
                if slope >= 0 and closed_close > ema20:
                     logger.info(f"📈 EXIT: Soft Trend (Slope >= 0 & Close > EMA20)")
                     self.executor.close_position(symbol, direction, position['size'])
                     
                     # Log Closure
                     try:
                        exit_price = closed_close
                        pnl_usd = (entry_price - exit_price) * position['size']
                        pnl_pct = (entry_price - exit_price) / entry_price
                        duration = time.time() - entry_time
                        
                        # Log Closure (CERRADOS)
                        leverage = Config.LEVERAGE
                        exposure = position['size'] * entry_price
                        margin = exposure / leverage
                        
                        CSVManager.log_closure(
                            symbol=symbol,
                            close_time=time.time(),
                            pnl_usd=pnl_usd,
                            margin=margin,
                            leverage=leverage,
                            exposure=exposure,
                            duration_sec=duration,
                            info="Soft Trend Exit"
                        )
                        
                        # ML Update (Total PnL - Commissions)
                        total_pnl_usd = pnl_usd + position.get('accumulated_pnl', 0.0)
                        
                        # Commission Calculation
                        total_volume = (position['size'] * entry_price) + (exit_price * position['size'])
                        commission = total_volume * 0.0005
                        net_pnl_usd = total_pnl_usd - commission
                        
                        initial_margin = (position['size'] * entry_price) / Config.LEVERAGE
                        net_roi_pct = net_pnl_usd / initial_margin if initial_margin > 0 else 0
                        
                        # Max PnL Calculation
                        if direction == "LONG":
                            max_pnl_pct = (position['p_max'] - entry_price) / entry_price
                        else:
                            max_pnl_pct = (entry_price - position['p_min']) / entry_price
                
                        # Build partial data for ML
                        partial_data = {
                            'partial_pnl_usd': position.get('accumulated_pnl', 0),
                            'final_pnl_usd': total_pnl_usd,
                            'levels_hit': [k for k, v in position.get('partials', {}).items() if v]
                        }
                        
                        logger.info(f"🧠 ML Update: Net PnL {net_pnl_usd:.2f} USD (Comm: {commission:.2f}) | ROI {net_roi_pct:.2%} | Max {max_pnl_pct:.2%}")
                        self.tuner.update_trade(net_roi_pct, max_pnl_pct, time.time(), symbol=symbol, partial_data=partial_data)
                        
                        # Save Tuner State
                        self.state.state['tuner'] = self.tuner.get_state()
                        self.state.save_state()
                     except Exception as e:
                        logger.error(f"Failed to log closure CSV: {e}")
    
                     self.state.clear_position(symbol)
                     return

        logger.info("🔎 Updating Trailing Stop based on latest ATR and price")
        # 6. Trailing Stop Update (On Closed Candle)
        new_sl = ATRManager.calculate_trailing_stop(
            position['sl_price'], 
            position['p_max'] if direction == "LONG" else position['p_min'],
            closed_atr,
            direction,
            position['entry_price']
        )
        
        if direction == "LONG":
            if new_sl > position['sl_price']:
                logger.info(f"Moving SL for LONG (Closed Candle Update): {position['sl_price']} -> {new_sl}")
                self.executor.set_stop_loss(symbol, direction, new_sl)
                position['sl_price'] = new_sl
                position['last_sl_update'] = time.time()
        else:
            if new_sl < position['sl_price']:
                logger.info(f"Moving SL for SHORT (Closed Candle Update): {position['sl_price']} -> {new_sl}")
                self.executor.set_stop_loss(symbol, direction, new_sl)
                position['sl_price'] = new_sl
                position['last_sl_update'] = time.time()
                
        self.state.set_position(symbol, position)
        logger.info(f"✅ Position for {symbol} held. Age: {(time.time()-entry_time)/60:.1f}m, Current PnL: {(closed_close-entry_price)/entry_price if direction=='LONG' else (entry_price-closed_close)/entry_price:.2%}")


