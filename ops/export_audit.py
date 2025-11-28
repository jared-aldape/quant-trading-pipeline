import sys
import duckdb
import pandas as pd
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def export_audit_csv():
    print("🕵️  GENERATING FULL TIMEZONE AUDIT CSV...")
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    target_date = '2025-11-26'
    
    # 1. FETCH SPX (Naive UTC from DB)
    print("   Fetching SPX Data...")
    try:
        df_spx = con.execute(f"""
            SELECT 
                datetime_utc as spx_utc, 
                open as spx_open 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'SPX' 
              AND CAST(datetime_utc AS DATE) = '{target_date}'
            ORDER BY datetime_utc ASC
        """).df()
    except Exception as e:
        print(f"❌ Error fetching SPX: {e}")
        return
    
    # 2. FETCH OPTIONS (Naive UTC from DB)
    print("   Fetching Option Data...")
    try:
        ticker = con.execute(f"SELECT ticker FROM {config.TBL_OPTIONS} LIMIT 1").fetchone()
        
        if ticker:
            df_opt = con.execute(f"""
                SELECT 
                    datetime_utc as opt_utc, 
                    open as opt_open,
                    ticker as opt_ticker
                FROM {config.TBL_OPTIONS} 
                WHERE ticker = '{ticker[0]}' 
                  AND CAST(datetime_utc AS DATE) = '{target_date}'
                ORDER BY datetime_utc ASC
            """).df()
        else:
            df_opt = pd.DataFrame(columns=['opt_utc', 'opt_open', 'opt_ticker'])
    except Exception as e:
        print(f"❌ Error fetching Options: {e}")
        con.close()
        return

    con.close()

    # 3. MERGE & EXPORT
    print("   Merging Data...")
    
    # Rename for merging
    df_spx['merge_key'] = df_spx['spx_utc']
    df_opt['merge_key'] = df_opt['opt_utc']
    
    merged = pd.merge(df_spx, df_opt, on='merge_key', how='outer', suffixes=('_spx', '_opt'))
    
    # Sort by time
    merged['timestamp'] = merged['merge_key']
    merged = merged.sort_values('timestamp')
    
    # Select Clean Columns
    final_df = merged[['timestamp', 'spx_open', 'opt_open', 'opt_ticker']].copy()
    
    # --- TIMEZONE FIX ---
    # 1. Force UTC Localization (Treat Naive DB data as UTC)
    if final_df['timestamp'].dt.tz is None:
        final_df['timestamp'] = final_df['timestamp'].dt.tz_localize('UTC')
    else:
        final_df['timestamp'] = final_df['timestamp'].dt.tz_convert('UTC')
        
    # 2. Create PST Column for readability
    final_df['local_pst'] = final_df['timestamp'].dt.tz_convert(config.TZ_LOCAL)

    # Export
    filename = config.REPORTS_DIR / f"timezone_audit_{target_date}.csv"
    final_df.to_csv(filename, index=False)
    
    print(f"✅ AUDIT COMPLETE. File saved to:\n   {filename}")

if __name__ == "__main__":
    export_audit_csv()