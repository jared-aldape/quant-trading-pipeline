# File: diagnostic_audit.py (Final Revision)
import sys
import os
import duckdb

# --- ARCHITECTURAL FIX: Add 'src' to the path for correct module import ---
# This line ensures Python can find the 'utils' package inside 'src'
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

# Now import the config module from the correct path
try:
    from utils.config import DB_FILE 
except ImportError:
    print("FATAL CONFIG FAILURE: Could not import config. Check if config.py is in src/utils/.")
    sys.exit(1)


# --- Audit Query Definition (CORRECTED COLUMN NAME) ---
AUDIT_SQL = """
SELECT
    *
FROM
    indices_1m
WHERE
    ticker = 'VIX' AND datetime_utc::date = '2025-11-25'
ORDER BY
    datetime_utc DESC
LIMIT 3;
"""

print("TOOL ID: ANALYSIS")
print("-" * 30)
print(f"Connecting to Golden Source: {DB_FILE}")

try:
    # 1. Connect to the DuckDB file
    with duckdb.connect(database=str(DB_FILE), read_only=True) as con:
        # 2. Execute the audit query
        result = con.execute(AUDIT_SQL).fetchall()

        # 3. Print the results clearly (Military Terminal Aesthetic)
        print("\n[DB TIMEZONE AUDIT REPORT]")
        print("-----------------------------------------------------------------")
        print("Datetime (Raw)        | Type          | Formatted with TZ Check")
        print("-----------------------------------------------------------------")
        for row in result:
            # Format the output for readability and high contrast
            print(f"{row[0]!s:<22} | {row[1]:<13} | {row[2]}")
        print("-----------------------------------------------------------------")

except Exception as e:
    # Satisfy The Observability Law
    print(f"\nFATAL AUDIT FAILURE: Could not connect to or query DuckDB file.")
    print(f"ERROR: {e}")
    sys.exit(1)
    
# --- End of Script ---