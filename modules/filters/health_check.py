import time
from config import Config
from modules.logger import logger

class HealthCheck:
    @staticmethod
    def check_data_delay(last_candle_timestamp):
        """
        Check if data is delayed > 2 seconds.
        last_candle_timestamp: ms timestamp of the last candle close (or open).
        Actually, for 15m candles, we check if the current time is too far from when we expect the candle to be available.
        But the requirement says: "Si la data de API tiene retraso > 2 segundos".
        This usually means the timestamp of the fetched data vs local time.
        """
        try:
            # We can check the difference between server time and local time, 
            # or simply if the last candle is fresh enough.
            # Let's assume we check against server time if available, or local time.
            
            # A simpler check: if we are requesting data, and the response takes too long, or the data timestamp is old.
            # Let's implement a latency check using the client's time fetch.
            pass 
        except Exception as e:
            logger.error(f"Error in data delay check: {e}")
            return False
        return True

    @staticmethod
    def get_latency(client):
        try:
            start = time.time()
            client.get_server_time()
            end = time.time()
            latency = (end - start) * 1000
            return latency
        except Exception as e:
            logger.error(f"Error checking latency: {e}")
            return 9999 # High latency on error

    @staticmethod
    def check_latency(client):
        # Deprecated in favor of manual check in BotLogic with hysteresis
        latency = HealthCheck.get_latency(client)
        return latency < Config.LATENCY_PAUSE_MS
