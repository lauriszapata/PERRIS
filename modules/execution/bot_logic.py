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
        
        # Enforce Fixed Leverage (1x) on Startup
        logger.info("🔧 Enforcing 1x Leverage for all symbols...")
        for symbol in Config.SYMBOLS:
            self.client.set_leverage(symbol, 1)
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

        # We need current prices for all open positions
        # Fetching ticker is faster than OHLCV
        for symbol, pos_data in positions.items():
            try:
                current_price = self.client.get_market_price(symbol)
                if not current_price: continue
                
                self._check_partials(symbol, pos_data, current_price)
            
                direction = pos_data['direction']
                entry_price = pos_data['entry_price']
                atr_entry = pos_data['atr_entry']
                size = pos_data['size']
                sl_price = pos_data['sl_price']
                
                # --- BREAKEVEN TRIGGER ---
                # If profit > BREAKEVEN_TRIGGER_PCT (0.6%), move SL to Entry
                # Only if SL is not already at or better than Entry
                pnl_pct_current = (current_price - entry_price) / entry_price if direction == "LONG" else (entry_price - current_price) / entry_price
                
                if pnl_pct_current >= Config.BREAKEVEN_TRIGGER_PCT:
                    is_breakeven = False
                    if direction == "LONG":
                        if sl_price < entry_price: # SL is below entry (risk)
                            new_sl = entry_price * 1.002 # Entry + 0.2% buffer (covers fees)
                            self.executor.set_stop_loss(symbol, direction, new_sl)
                            pos_data['sl_price'] = new_sl
                            self.state.set_position(symbol, pos_data)
                            logger.info(f"🛡️ BREAKEVEN TRIGGERED for {symbol}: SL moved to {new_sl:.4f} (Profit {pnl_pct_current:.2%})")
                    else: # SHORT
                        if sl_price > entry_price: # SL is above entry (risk)
                            new_sl = entry_price * 0.998 # Entry - 0.2% buffer (covers fees)
                            self.executor.set_stop_loss(symbol, direction, new_sl)
                            pos_data['sl_price'] = new_sl
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
                            
                            CSVManager.log_closure(symbol, direction, entry_price, exit_price, actual_size, "Early Invalidation (Real-Time)", pnl_usd, pnl_pct, duration)
                            CSVManager.log_finance(symbol, direction, actual_size, entry_price, exit_price, pnl_usd, duration)
                            
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
                    entry = pos_data['entry_price']
                    direction = pos_data['direction']
                    sl = pos_data['sl_price']
                    
                    if direction == "LONG":
                        pnl_pct = (current_price - entry) / entry * 100
                        dist_sl = (current_price - sl) / current_price * 100
                    else:
                        pnl_pct = (entry - current_price) / entry * 100
                        dist_sl = (sl - current_price) / current_price * 100
                        
                    logger.info(f"👀 MONITOR {symbol} {direction}: Price {current_price:.4f} | PnL: {pnl_pct:+.2f}% | Dist to SL: {dist_sl:.2f}%")
                
            except Exception as e:
                logger.error(f"Error monitoring {symbol}: {e}")
        
        if should_log:
            self.last_monitor_log = now

    def _check_partials(self, symbol, pos_data, current_price):
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
        
        # 1. Check FIXED levels first (P1-P6)
        for i, level_config in enumerate(Config.TAKE_PROFIT_LEVELS):
            level_name = f"p{i+1}"
            target_pct = level_config['pct']
            close_pct = level_config['close_pct']
            display_name = level_config['name']
            
            # Skip if already taken
            if partials.get(level_name, False):
                continue
            
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
                        CSVManager.log_closure(
                            symbol, direction, entry, actual_exit_price, actual_closed_amount, 
                            f"Partial {display_name}", actual_profit_usd, actual_pnl_pct, 
                            time.time() - pos_data['entry_time']
                        )
                        CSVManager.log_finance(
                            symbol, direction, actual_closed_amount, entry, actual_exit_price, 
                            actual_profit_usd, time.time() - pos_data['entry_time']
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
        
        logger.info(f"Starting loop for {len(symbols_to_process)} symbols")
        rejection_stats = Counter()
        
        active_positions_count = 0
        total_unrealized_pnl = 0.0
        
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
                    # Calculate Unrealized PnL
                    entry_price = position['entry_price']
                    size = position['size']
                    direction = position['direction']
                    
                    if direction == "LONG":
                        pnl = (current_price - entry_price) * size
                    else:
                        pnl = (entry_price - current_price) * size
                        
                    total_unrealized_pnl += pnl
                    
                    self._manage_position(symbol, position, df)
                elif symbol in target_symbols and allow_entries:
                    # Only look for NEW entries if the symbol is in our target list AND entries are allowed
                    self._look_for_entry(symbol, df, rejection_stats)
                    
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue
        
        # Log Summary
        logger.info("=== 📉 TOP 3 REJECTION REASONS ===")
        for reason, count in rejection_stats.most_common(3):
            logger.info(f"  ❌ {reason}: {count} times")
        logger.info("====================================")
        
        # Log Active Positions Summary
        if active_positions_count > 0:
            logger.info(f"📊 ACTIVE POSITIONS: {active_positions_count}")
            logger.info(f"💰 UNREALIZED PnL: {total_unrealized_pnl:.2f} USDT")
            logger.info("====================================")
        else:
            logger.info("💤 NO ACTIVE POSITIONS")
            logger.info("====================================")

    def _look_for_entry(self, symbol, df, stats):
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
                self._execute_entry(symbol, direction, df) # Pass full DF to get current price for execution
                return # Only take one trade at a time

    def _execute_entry(self, symbol, direction, df):
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
        self.client.set_leverage(symbol, 1)
        
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
                "last_sl_update": time.time()  # Track when SL was last updated
            }
            self.state.set_position(symbol, pos_data)
            
            # Record trade timestamp for frequency tracking
            self.state.add_trade_timestamp(time.time())
            logger.info(f"✅ Trade timestamp recorded. Total trades in last hour: {len(self.state.state['trades_last_hour'])}")
            
            # Set Initial SL
            self.executor.set_stop_loss(symbol, direction, sl_price)
            
            # Log to CSV with ACTUAL execution price
            try:
                # Extract indicator values for logging
                indicators = {
                    'RSI': last['RSI'],
                    'ADX': last['ADX'],
                    'MACD_line': last['MACD_line'],
                    'MACD_signal': last['MACD_signal'],
                    'volume': last['volume']
                }
                CSVManager.log_entry(symbol, direction, actual_entry_price, actual_size, sl_price, atr, indicators)
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
        
        # Update P_max / P_min using Closed Candle data
        if direction == "LONG":
            if closed_high > position['p_max']:
                position['p_max'] = closed_high
        else:
            if closed_low < position['p_min']:
                position['p_min'] = closed_low
            
        # --- EXIT CONDITIONS (Priority Order) ---
        
        # 0. Early Invalidation (Moved to Real-Time Monitor)
        
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
                
                CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "ATR Extreme", pnl_usd, pnl_pct, duration)
                CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                
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
                        
                        CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Structure Break (Swing Low)", pnl_usd, pnl_pct, duration)
                        CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                        
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
                        
                        CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Structure Break (Swing High)", pnl_usd, pnl_pct, duration)
                        CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                        
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
        
        # 3. MACD Reversal Exit (New)
        # If MACD Histogram flips against us, it's a strong sign of momentum loss.
        macd_hist = closed_candle['MACD_hist']
        macd_hist_prev = prev_closed_candle['MACD_hist']
        
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
                
                CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "MACD Reversal", pnl_usd, pnl_pct, duration)
                CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                
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
                
                CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Hard Cross Exit", pnl_usd, pnl_pct, duration)
                CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                
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
                
                CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Hard Cross Exit", pnl_usd, pnl_pct, duration)
                CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                
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
                
                CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Stagnation Exit", pnl_usd, current_pnl_pct, duration)
                CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                
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
                    
                    CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Time Limit", pnl_usd, pnl_pct, duration)
                    CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                
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
                        
                        CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Soft Trend Exit", pnl_usd, pnl_pct, duration)
                        CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                        
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
                        
                        CSVManager.log_closure(symbol, direction, entry_price, exit_price, position['size'], "Soft Trend Exit", pnl_usd, pnl_pct, duration)
                        CSVManager.log_finance(symbol, direction, position['size'], entry_price, exit_price, pnl_usd, duration)
                        
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
