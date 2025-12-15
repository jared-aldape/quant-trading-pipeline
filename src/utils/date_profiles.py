from datetime import date, timedelta
import calendar

# ==============================================================================
# DATE PROFILE DEFINITIONS
# ==============================================================================
# This shared utility allows view_backtest.py and view_stats.py 
# to use the same relative date logic.

class DateProfile:
    def __init__(self, name, start_provider, end_provider=lambda: date.today()):
        self.name = name
        self._start_provider = start_provider
        self._end_provider = end_provider

    @property
    def start_date(self):
        """Returns the calculated start date."""
        return self._start_provider()

    @property
    def end_date(self):
        """Returns the calculated end date."""
        return self._end_provider()

# --- HELPER FUNCTIONS ---

def get_specific_month_start(month_index):
    """Returns the 1st of the specified month (1=Jan, 12=Dec) for the current year."""
    today = date.today()
    return date(today.year, month_index, 1)

def get_specific_month_end(month_index):
    """Returns the last day of the specified month for the current year."""
    today = date.today()
    last_day = calendar.monthrange(today.year, month_index)[1]
    return date(today.year, month_index, last_day)

def get_last_month_start():
    today = date.today()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    return last_month.replace(day=1)

def get_last_month_end():
    today = date.today()
    first = today.replace(day=1)
    return first - timedelta(days=1)

def get_this_month_start():
    return date.today().replace(day=1)

# --- THE PROFILE REGISTRY ---
DATE_PROFILES = {
    # --- DYNAMIC ---
    'Last 30 Days': DateProfile('Last 30 Days', lambda: date.today() - timedelta(days=30)),
    'Last 60 Days': DateProfile('Last 60 Days', lambda: date.today() - timedelta(days=60)),
    'Last 90 Days': DateProfile('Last 90 Days', lambda: date.today() - timedelta(days=90)),
    'Year To Date': DateProfile('Year To Date', lambda: date(date.today().year, 1, 1)),
    'Last Year':    DateProfile('Last Year', 
                                lambda: date(date.today().year - 1, 1, 1), 
                                lambda: date(date.today().year - 1, 12, 31)),
    
    # --- RELATIVE MONTHS ---
    'This Month':   DateProfile('This Month', get_this_month_start),
    'Last Month':   DateProfile('Last Month', get_last_month_start, get_last_month_end),

    # --- SPECIFIC MONTHS (CURRENT YEAR) ---
    'January':   DateProfile('January',   lambda: get_specific_month_start(1),  lambda: get_specific_month_end(1)),
    'February':  DateProfile('February',  lambda: get_specific_month_start(2),  lambda: get_specific_month_end(2)),
    'March':     DateProfile('March',     lambda: get_specific_month_start(3),  lambda: get_specific_month_end(3)),
    'April':     DateProfile('April',     lambda: get_specific_month_start(4),  lambda: get_specific_month_end(4)),
    'May':       DateProfile('May',       lambda: get_specific_month_start(5),  lambda: get_specific_month_end(5)),
    'June':      DateProfile('June',      lambda: get_specific_month_start(6),  lambda: get_specific_month_end(6)),
    'July':      DateProfile('July',      lambda: get_specific_month_start(7),  lambda: get_specific_month_end(7)),
    'August':    DateProfile('August',    lambda: get_specific_month_start(8),  lambda: get_specific_month_end(8)),
    'September': DateProfile('September', lambda: get_specific_month_start(9),  lambda: get_specific_month_end(9)),
    'October':   DateProfile('October',   lambda: get_specific_month_start(10), lambda: get_specific_month_end(10)),
    'November':  DateProfile('November',  lambda: get_specific_month_start(11), lambda: get_specific_month_end(11)),
    'December':  DateProfile('December',  lambda: get_specific_month_start(12), lambda: get_specific_month_end(12)),
    
    # --- QUARTERS ---
    'Q1': DateProfile('Q1', lambda: date(date.today().year, 1, 1), lambda: date(date.today().year, 3, 31)),
    'Q2': DateProfile('Q2', lambda: date(date.today().year, 4, 1), lambda: date(date.today().year, 6, 30)),
    'Q3': DateProfile('Q3', lambda: date(date.today().year, 7, 1), lambda: date(date.today().year, 9, 30)),
    'Q4': DateProfile('Q4', lambda: date(date.today().year, 10, 1), lambda: date(date.today().year, 12, 31)),
}