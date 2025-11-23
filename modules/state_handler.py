import json
import os
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
