from modules.logger import logger

class NewsFilter:
    """Placeholder news filter.
    In production this could call an external API (e.g., ForexFactory) and return False
    during high‑impact news windows.
    For now it always returns True (no blocking news).
    """
    @staticmethod
    def check_news():
        # TODO: integrate real news API
        logger.info("NewsFilter: no news blocking (placeholder)")
        return True
