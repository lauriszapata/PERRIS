from datetime import datetime, timezone

class TimeFilter:
    @staticmethod
    def check_daily_close_window():
        """
        Avoid trading around daily close (00:00 UTC).
        Let's say +/- 15 minutes window? User said "No operar en el cierre diario".
        We'll block 23:45 to 00:15 UTC.
        """
        now = datetime.now(timezone.utc)
        # Check if time is between 23:45 and 00:15
        if (now.hour == 23 and now.minute >= 45) or (now.hour == 0 and now.minute <= 15):
            return False
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
