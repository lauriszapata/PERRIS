from config import Config
from modules.logger import logger

class FundingFilter:
    @staticmethod
    def check_funding(funding_rate, direction):
        """
        Evitar LONG si funding > +0.03%.
        Evitar SHORT si funding < –0.03%.
        """
        try:
            if direction == "LONG":
                if funding_rate > Config.MAX_FUNDING_RATE:
                    logger.info(f"Funding Filter Failed for LONG: Rate {funding_rate:.4f} > {Config.MAX_FUNDING_RATE}")
                    return False
            elif direction == "SHORT":
                if funding_rate < -Config.MAX_FUNDING_RATE:
                    logger.info(f"Funding Filter Failed for SHORT: Rate {funding_rate:.4f} < -{Config.MAX_FUNDING_RATE}")
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Error checking funding: {e}")
            return False
