from datetime import datetime, timezone

class TimeFilter:
    @staticmethod
    def check_daily_close_window():
        """Daily close window filter disabled – always allow trading."""
        return True

    @staticmethod
    def check_news():
        """
        Placeholder for News Filter.
        Ideally requires an external API (e.g. ForexFactory, Benzinga).
        For now, returns True (Pass) but logs a warning that it's not implemented.
        """
        # TODO: Implement News API check
        return True
