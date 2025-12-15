import pandas as pd
import duckdb
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pytz
import re
import numpy as np

# ==============================================================================
# 1. PATH & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("HydrateLedger")
CSV_PATH = ROOT_DIR / "data" / "rh_options_export.csv"
TARGET_TABLE = "active_rh_log" 

# ==============================================================================
# 2. HELPER: TIMESTAMP PARSER (NAIVE UTC PROTOCOL)
# ==============================================================================
def parse_rh_timestamp(ts_str):
    """
    Parses '12/10, 8:27 AM PST' -> Naive UTC Timestamp.
    Example: '8:27 AM PST' -> 16:27 UTC (Stored as 2025-12-10 16:27:00)
    """
    if not isinstance(ts_str, str) or not ts_str.strip():
        return None
    clean_str = ts_str.replace("Submitted | ", "").strip()
    clean_str = clean_str.replace(" PST", "").replace(" PDT", "").replace(" EST", "").replace(" EDT", "")
    try:
        current_year = datetime.now().year
        dt = datetime.strptime(f"{current_year}, {clean_str}", "%Y, %m/%d, %I:%M %p")
        
        # Handle Year Rollover
        if dt > datetime.now() + timedelta(days=2):
            dt = dt.replace(year=current_year - 1)
            
        # 1. Localize to Source (Glass Time -> PST)
        tz_source = pytz.timezone('US/Pacific') 
        dt_aware = tz_source.localize(dt)
        
        # 2. Convert to Vault Time (UTC)
        dt_utc = dt_aware.astimezone(pytz.UTC)
        
        # 3. SANITIZE: Strip Timezone Info to match indices_1m format
        return dt_utc.replace(tzinfo=None)
        
    except Exception as e:
        # log.warning(f"Date Parse Fail: {e}") # Silence noise if needed
        return None

# ==============================================================================
# 3. HELPER: REGEX ATOMIZER
# ==============================================================================
def parse_header_string(header_str, trade_dt_utc):
    if not isinstance(header_str, str): return {}
    
    pattern = r"(?P<side>Buy|Sell)\s+(?P<root>[A-Z]+)\s+(?P<strike>[0-9.]+)\s+(?P<right>Call|Put)\s+(?P<expiry_md>\d{1,2}/\d{1,2})"
    match = re.search(pattern, header_str, re.IGNORECASE)
    if not match: return {}
    
    data = match.groupdict()
    side = data['side'].upper()
    root = data['root'].upper()
    strike = float(data['strike'])
    right_code = 'C' if 'Call' in data['right'] else 'P'
    
    trade_year = trade_dt_utc.year
    exp_month, exp_day = map(int, data['expiry_md'].split('/'))
    exp_year = trade_year
    if exp_month < trade_dt_utc.month and trade_dt_utc.month == 12:
        exp_year += 1
        
    expiry_date = datetime(exp_year, exp_month, exp_day).date()
    
    yy = str(exp_year)[2:]
    mm = f"{exp_month:02d}"
    dd = f"{exp_day:02d}"
    strike_scaled = int(strike * 1000)
    strike_str = f"{strike_scaled:08d}" 
    opra_code = f"O:{root}{yy}{mm}{dd}{right_code}{strike_str}"
    
    return {
        'action': side,
        'root': root,
        'strike': strike,
        'option_right': right_code,
        'expiry_date': expiry_date,
        'opra_code': opra_code
    }

def clean_currency(val):
    if pd.isna(val) or val == '': return 0.0
    val_str = str(val).replace('$', '').replace(',', '').replace('+', '').strip()
    try:
        return float(val_str)
    except:
        return 0.0

# ==============================================================================
# 4. CORE PIPELINE
# ==============================================================================
def hydrate_ledger():
    log.info(f"🌊 STARTING LEDGER HYDRATION (NAIVE UTC) -> {TARGET_TABLE}")
    
    if not CSV_PATH.exists():
        log.error(f"❌ File not found: {CSV_PATH}")
        return

    try:
        df_raw = pd.read_csv(CSV_PATH, dtype=str)
        
        # Split & Merge
        df_headers = df_raw[df_raw['Strike title'].notna()].copy().reset_index(drop=True)
        df_details = df_raw[df_raw['Status'].notna() & df_raw['Strike title'].isna()].copy().reset_index(drop=True)
        
        min_len = min(len(df_headers), len(df_details))
        df_headers = df_headers.iloc[:min_len]
        df_details = df_details.iloc[:min_len]
        
        # Correctly pull Fees from Details
        df = pd.concat([
            df_headers[['Strike title', 'Total Sale', 'Contracts', 'web_scraper_order']],
            df_details[['Submitted', 'Status', 'Est Regulatory Fees']]
        ], axis=1)

        final_rows = []
        
        for _, row in df.iterrows():
            entry_time = parse_rh_timestamp(row['Submitted'])
            if entry_time is None: continue

            header_data = parse_header_string(row['Strike title'], entry_time)
            if not header_data: continue
            
            qty_match = re.search(r"(\d+)\s+contract", str(row['Contracts']))
            qty = float(qty_match.group(1)) if qty_match else 0.0
            
            fees = clean_currency(row.get('Est Regulatory Fees', 0))
            raw_total = clean_currency(row['Total Sale'])
            
            if header_data['action'] == "BUY":
                net_pnl = -abs(raw_total)
            else:
                net_pnl = abs(raw_total)
            
            fill_price = (abs(net_pnl) - fees) / (qty * 100) if qty > 0 else 0.0
            
            status = str(row['Status']).upper()
            if "CANCEL" in status:
                net_pnl = 0.0; fees = 0.0; qty = 0.0

            final_rows.append({
                'source_id': row['web_scraper_order'],
                'entry_time_utc': entry_time, # Now Naive UTC
                'action': header_data['action'],
                'root': header_data['root'],
                'strike': header_data['strike'],
                'option_right': header_data['option_right'],
                'expiry_date': header_data['expiry_date'],
                'quantity': qty,
                'fill_price': round(fill_price, 2),
                'net_pnl': net_pnl,
                'fees': fees,
                'status': status,
                'opra_code': header_data['opra_code']
            })

        final_df = pd.DataFrame(final_rows)
        
        con = duckdb.connect(str(config.DB_FILE))
        
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (
                source_id VARCHAR PRIMARY KEY,
                entry_time_utc TIMESTAMP,
                action VARCHAR,
                root VARCHAR,
                strike DOUBLE,
                option_right VARCHAR,
                expiry_date DATE,
                quantity DOUBLE,
                fill_price DOUBLE,
                net_pnl DOUBLE,
                fees DOUBLE,
                status VARCHAR,
                opra_code VARCHAR
            )
        """)
        
        incoming_ids = final_df['source_id'].unique().tolist()
        if incoming_ids:
            formatted_ids = ", ".join([f"'{x}'" for x in incoming_ids])
            con.execute(f"DELETE FROM {TARGET_TABLE} WHERE source_id IN ({formatted_ids})")
            log.info(f"🧹 Cleared {len(incoming_ids)} existing records.")

        con.register('df_insert', final_df)
        con.execute(f"INSERT INTO {TARGET_TABLE} SELECT * FROM df_insert")
        
        log.info(f"✅ Hydration Complete. {len(final_df)} records stored as NAIVE UTC.")
        con.close()

    except Exception as e:
        log.error(f"🔥 Hydration Failed: {e}")
        raise e

if __name__ == "__main__":
    hydrate_ledger()