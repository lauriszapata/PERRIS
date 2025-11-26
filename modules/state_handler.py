import json
import os
import time
from modules.logger import logger
from config import Config

class StateHandler:
    def __init__(self, file_path=Config.STATE_FILE):
        self.file_path = file_path
        self.state = self._load_state()

    def _load_state(self):
        if not os.path.exists(self.file_path):
            return self._default_state()
        
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return self._default_state()

    def _default_state(self):
        return {
            "positions": {}, # symbol -> position_data
            "daily_pnl": 0.0,
            "last_reset_time": None,
            "trades_last_hour": [], # list of timestamps
            "last_trade_per_symbol": {}, # symbol -> timestamp of last trade close
            "is_paused": False,
            "pause_reason": None,
            "pause_until": None
        }

    def save_state(self):
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def get_position(self, symbol):
        return self.state["positions"].get(symbol)

    def set_position(self, symbol, data):
        self.state["positions"][symbol] = data
        self.save_state()

    def clear_position(self, symbol):
        if symbol in self.state["positions"]:
            del self.state["positions"][symbol]
            # Automatically record cooldown when closing a position
            self.record_symbol_trade_close(symbol, time.time())
            self.save_state()

    def update_daily_pnl(self, amount):
        self.state["daily_pnl"] += amount
        self.save_state()
    
    def reset_daily_pnl(self):
        self.state["daily_pnl"] = 0.0
        self.save_state()

    def add_trade_timestamp(self, timestamp):
        self.state["trades_last_hour"].append(timestamp)
        self.save_state()
    
    def cleanup_old_trades(self, current_time):
        # Remove trades older than 1 hour (3600 seconds)
        cutoff = current_time - 3600  # seconds
        self.state["trades_last_hour"] = [t for t in self.state["trades_last_hour"] if t > cutoff]
        self.save_state()
    
    def record_symbol_trade_close(self, symbol, timestamp):
        """Record when a trade for this symbol was closed"""
        if "last_trade_per_symbol" not in self.state:
            self.state["last_trade_per_symbol"] = {}
        self.state["last_trade_per_symbol"][symbol] = timestamp
        self.save_state()
    
    def check_symbol_cooldown(self, symbol, current_time):
        """Check if symbol is still in cooldown period"""
        if "last_trade_per_symbol" not in self.state:
            self.state["last_trade_per_symbol"] = {}
            return True  # No cooldown data, allow trade
        
        last_trade_time = self.state["last_trade_per_symbol"].get(symbol)
        if not last_trade_time:
            return True  # Never traded this symbol, allow
        
        cooldown_seconds = Config.SYMBOL_COOLDOWN_MINUTES * 60
        time_since_last = current_time - last_trade_time
        
        if time_since_last < cooldown_seconds:
            remaining_minutes = (cooldown_seconds - time_since_last) / 60
            logger.info(f"⏳ Symbol Cooldown: {symbol} - Wait {remaining_minutes:.1f} more minutes")
            return False
        
        return True


