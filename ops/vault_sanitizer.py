import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. ARCHITECTURE SETUP
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
    log = get_logger("VaultSanitizer")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("VaultSanitizer")
    class MockConfig:
        DB_FILE = "data/quant_strategy.duckdb" # Adjust if needed
        TBL_INDICES = "indices_1m"
        TBL_MANIFEST = "trade_manifest"
    config = MockConfig()

# ==============================================================================
# 2. FORENSIC LOGIC
# ==============================================================================
def run_diagnostics():
    print(f"\n⚔️  QUANT OS v3.3: VAULT SANITIZER")
    print("===================================")
    
    if not Path(config.DB_FILE).exists():
        log.error(f"❌ Database not found at {config.DB_FILE}")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=False) # Write access for cleanup
    
    # ---------------------------------------------------------
    # TEST 1: DUPLICATE CHECK (The "Clone" Attack)
    # ---------------------------------------------------------
    log.info("🔍 TEST 1: Checking for Duplicate Timestamps...")
    
    # Find duplicates in INDICES
    dup_query = f"""
        SELECT ticker, datetime_utc, COUNT(*) as count
        FROM {config.TBL_INDICES}
        GROUP BY ticker, datetime_utc
        HAVING COUNT(*) > 1
    """
    dups = con.execute(dup_query).df()
    
    if not dups.empty:
        log.warning(f"⚠️  CONTAMINATION DETECTED: {len(dups)} duplicate rows found.")
        print(dups.head())
        
        # AUTO-REPAIR
        print("   >> 🛠️  INITIATING AUTO-REPAIR...")
        # Create temp table with unique rows
        con.execute(f"""
            CREATE TABLE indices_temp AS 
            SELECT DISTINCT * FROM {config.TBL_INDICES}
        """)
        # Drop old
        con.execute(f"DROP TABLE {config.TBL_INDICES}")
        # Rename new
        con.execute(f"ALTER TABLE indices_temp RENAME TO {config.TBL_INDICES}")
        print("   >> ✅  Duplicates eliminated.")
    else:
        print("   ✅  Zero Duplicates detected.")

    # ---------------------------------------------------------
    # TEST 2: THE SEAM INSPECTION (CSV vs Yahoo)
    # ---------------------------------------------------------
    log.info("\n🔍 TEST 2: Inspecting Data Continuity (The Seam)...")
    
    # Get Date Range
    range_df = con.execute(f"""
        SELECT 
            MIN(datetime_utc) as start_date, 
            MAX(datetime_utc) as end_date, 
            COUNT(*) as total_rows 
        FROM {config.TBL_INDICES} 
        WHERE ticker = 'VIX'
    """).df()
    
    print(f"   VIX Range: {range_df.iloc[0]['start_date']} -> {range_df.iloc[0]['end_date']}")
    print(f"   Total Bars: {range_df.iloc[0]['total_rows']}")
    
    # Check resolution mix
    # Yahoo (5m) vs CSV (Daily/00:00:00)
    # We count how many rows have non-zero minutes
    res_check = con.execute(f"""
        SELECT 
            COUNT(*) FILTER (WHERE EXTRACT(MINUTE FROM datetime_utc) = 0 
                             AND EXTRACT(HOUR FROM datetime_utc) = 0) as daily_like_bars,
            COUNT(*) FILTER (WHERE EXTRACT(MINUTE FROM datetime_utc) > 0 
                             OR EXTRACT(HOUR FROM datetime_utc) > 0) as intraday_bars
        FROM {config.TBL_INDICES}
        WHERE ticker = 'VIX'
    """).df()
    
    print(f"   Daily Bars (CSV Layer):    {res_check.iloc[0]['daily_like_bars']}")
    print(f"   Intraday Bars (Yahoo Layer): {res_check.iloc[0]['intraday_bars']}")
    
    if res_check.iloc[0]['daily_like_bars'] > 0 and res_check.iloc[0]['intraday_bars'] > 0:
        print("   ✅  HYBRID FUSION CONFIRMED (Daily + Intraday coexist).")
    else:
        print("   ⚠️  WARNING: Data appears effectively monolithic (Missing one layer?).")

    # ---------------------------------------------------------
    # TEST 3: MANIFEST HEALTH
    # ---------------------------------------------------------
    log.info("\n🔍 TEST 3: Trade Manifest Integrity...")
    
    try:
        manifest_stats = con.execute(f"""
            SELECT 
                signal_type, 
                COUNT(*) as count, 
                MIN(date) as first_sig, 
                MAX(date) as last_sig 
            FROM {config.TBL_MANIFEST}
            GROUP BY signal_type
        """).df()
        
        if not manifest_stats.empty:
            print(manifest_stats)
        else:
            print("   ⚠️  Manifest is EMPTY. (Did you run the scanner?)")
    except Exception:
        print("   ❌  Manifest table missing or corrupt.")

    # ---------------------------------------------------------
    # OPTIMIZATION: VACUUM
    # ---------------------------------------------------------
    log.info("\n🧹 Finalizing: Vacuuming Database...")
    con.execute("VACUUM")
    print("   ✅  Database Optimized.")
    
    con.close()

if __name__ == "__main__":
    run_diagnostics()