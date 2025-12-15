import sys
import duckdb
import pandas as pd
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("MacroIngest")

def run_ingest():
    log.info("🌍 Initializing Macro Intelligence...")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. Create Table
    con.execute("DROP TABLE IF EXISTS macro_events")
    con.execute("""
        CREATE TABLE macro_events (
            date DATE PRIMARY KEY,
            event_type VARCHAR,
            impact_score INTEGER
        )
    """)
    
    # 2. The "Hard Coded" Truth (2024-2025 Key Dates)
    # Impact Score: 1 (Watch), 2 (Caution), 3 (DANGER/CHOP)
    events = [
        # 2024
        ('2024-10-21', 'EARNINGS_TSLA_ANTICIPATION', 3), # The day you referenced
        ('2024-11-05', 'US_ELECTION', 3),
        ('2024-11-07', 'FOMC_RATE_DECISION', 3),
        ('2024-12-18', 'FOMC_RATE_DECISION', 3),
        # 2025 (Projected)
        ('2025-01-29', 'FOMC_RATE_DECISION', 3),
        ('2025-03-19', 'FOMC_RATE_DECISION', 3),
        ('2025-10-29', 'FOMC_RATE_DECISION', 3)
    ]
    
    con.executemany("INSERT INTO macro_events VALUES (?, ?, ?)", events)
    log.info(f"✅ Ingested {len(events)} Macro Events.")
    con.close()

if __name__ == "__main__":
    run_ingest()