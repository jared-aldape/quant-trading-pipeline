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
    print(f"✅ Configuration Loaded. Target DB: {config.DB_FILE}")
except ImportError:
    print("❌ CRITICAL: Run from Project Root.")
    sys.exit(1)

def run_integrity_check():
    print("\n⚔️  QUANT OS v3.3: VAULT INTEGRITY MAP")
    print("=======================================")
    
    if not Path(config.DB_FILE).exists():
        print("❌ Database not found.")
        return

    con = duckdb.connect(str(config.DB_FILE), read_only=True)

    # ---------------------------------------------------------
    # QUERY 1: SIGNAL COVERAGE (The Orders)
    # ---------------------------------------------------------
    print("\n📡 [1] SIGNAL COVERAGE (Trade Manifest)")
    signals = con.execute("""
        SELECT 
            strftime(date, '%Y-%m') as month,
            COUNT(*) as signal_count,
            STRING_AGG(DISTINCT signal_type, ', ') as types
        FROM trade_manifest
        GROUP BY 1
        ORDER BY 1 ASC
    """).df()
    
    if signals.empty:
        print("   ❌ Manifest is EMPTY.")
    else:
        print(signals.to_string(index=False))

    # ---------------------------------------------------------
    # QUERY 2: VIX DATA COVERAGE (The Map)
    # ---------------------------------------------------------
    print("\n🗺️  [2] VIX DATA COVERAGE (Indices)")
    vix = con.execute("""
        SELECT 
            strftime(datetime_utc, '%Y-%m') as month,
            COUNT(*) as bar_count,
            MIN(datetime_utc) as start,
            MAX(datetime_utc) as end
        FROM indices_1m
        WHERE ticker = 'VIX'
        GROUP BY 1
        ORDER BY 1 ASC
    """).df()
    
    if vix.empty:
        print("   ❌ VIX Data is EMPTY.")
    else:
        print(vix.to_string(index=False))

    # ---------------------------------------------------------
    # QUERY 3: OPTIONS DATA COVERAGE (The Vehicle)
    # ---------------------------------------------------------
    print("\n🏎️  [3] OPTIONS DATA COVERAGE (The Critical Check)")
    options = con.execute("""
        SELECT 
            strftime(datetime_utc, '%Y-%m') as month,
            COUNT(*) as price_points,
            COUNT(DISTINCT ticker) as unique_contracts
        FROM options_1m
        GROUP BY 1
        ORDER BY 1 ASC
    """).df()
    
    if options.empty:
        print("   ❌ OPTIONS DATA IS EMPTY (Critical Failure).")
    else:
        print(options.to_string(index=False))

    # ---------------------------------------------------------
    # SYNTHESIS
    # ---------------------------------------------------------
    print("\n🔎 DIAGNOSTIC CONCLUSION:")
    
    # Check for Gaps
    sig_months = set(signals['month'].tolist()) if not signals.empty else set()
    opt_months = set(options['month'].tolist()) if not options.empty else set()
    
    missing_data = sig_months - opt_months
    
    if missing_data:
        print(f"   ⚠️  CRITICAL GAP: You have Signals in {sorted(list(missing_data))} but NO OPTIONS DATA.")
        print("       -> The robot cannot trade what it cannot see.")
    elif not opt_months:
        print("   ❌  NO OPTIONS DATA AT ALL. Backtest is impossible.")
    else:
        print("   ✅  Data Coverage looks aligned. Check execution logic.")

    con.close()

if __name__ == "__main__":
    run_integrity_check()