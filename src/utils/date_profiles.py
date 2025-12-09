from datetime import date, timedelta

class DateProfile:
    def __init__(self, name, start_provider, end_provider=lambda: date.today()):
        self.name = name
        self._start_provider = start_provider
        self._end_provider = end_provider

    @property
    def start_date(self):
        return self._start_provider()

    @property
    def end_date(self):
        return self._end_provider()

# Helpers
def get_ytd_start(): return date(date.today().year, 1, 1)
def get_last_year_start(): return date(date.today().year - 1, 1, 1)
def get_last_year_end(): return date(date.today().year - 1, 12, 31)

DATE_PROFILES = {
    'Last 30 Days': DateProfile('Last 30 Days', lambda: date.today() - timedelta(days=30)),
    'Last 60 Days': DateProfile('Last 60 Days', lambda: date.today() - timedelta(days=60)),
    'Last 90 Days': DateProfile('Last 90 Days', lambda: date.today() - timedelta(days=90)),
    'Year to Date (YTD)': DateProfile('YTD', get_ytd_start),
    'Last Year (Full)': DateProfile('Last Year', get_last_year_start, get_last_year_end),
    'Max History (2020)': DateProfile('Max', lambda: date(2020, 1, 1))
}