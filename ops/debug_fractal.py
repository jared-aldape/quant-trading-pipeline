import duckdb
import pandas as pd
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from src.utils import config
import src.core.strat_fractal as strategy

def run_debug_scan():
    print("🕵️ STARTING FRACTAL LOGIC DEBUGGER")
    print(f"🔌 Connecting to: {config.DB_FILE}")
    
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. LOAD VIX DATA
    print("⏳ Fetching VIX Data...")
    df = con.execute(f"SELECT datetime_utc, close FROM {config.TBL_INDICES} WHERE ticker = 'VIX'").df()
    
    if df.empty:
        print("❌ ERROR: No VIX Data Found.")
        return

    df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
    df.set_index('datetime_utc', inplace=True)
    df.sort_index(inplace=True)
    
    print(f"📊 Loaded {len(df)} Raw Rows. Range: {df.index.min()} to {df.index.max()}")

    # 2. BUILD GRIDS (Replicating engine_scanner)
    print("📐 Building 5M and 1H Grids...")
    
    # Micro 5M
    df_5m = df['close'].resample('5min').ohlc()
    df_5m = df_5m[['close']].copy() # Flatten
    df_5m = strategy.calculate_macd(df_5m)
    df_5m = strategy.calculate_rsi(df_5m)
    
    # Macro 1H
    df_1h = df['close'].resample('1h').ohlc()
    df_1h = df_1h[['close']].copy()
    df_1h = strategy.calculate_macd(df_1h)

    # 3. DEBUG LOOP
    print("\n🔍 ANALYZING LAST 1000 CANDLES (The 'Live' Zone)...")
    
    # Slice the last 1000 rows (most likely to have valid 5m data)
    subset_5m = df_5m.iloc[-1000:]
    
    rejection_stats = {
        "NaN_RSI": 0,
        "Data_Gap_1H": 0,
        "Logic_Fail": 0,
        "Signal_Found": 0
    }
    
    detailed_logs = []
    
    for current_time, row in subset_5m.iterrows():
        # A. PRE-CHECK
        if pd.isna(row['rsi']):
            rejection_stats["NaN_RSI"] += 1
            continue
            
        # B. STRATEGY CALL
        result = strategy.check_fractal_flow(df_1h, df_5m, current_time, row['rsi'])
        
        if result['signal_type']:
            rejection_stats["Signal_Found"] += 1
            detailed_logs.append(f"✅ SIGNAL: {current_time} | {result['signal_type']} | {result['reason']}")
        else:
            if result['reason'] == 'Data Gap':
                rejection_stats["Data_Gap_1H"] += 1
                # Print one sample of data gap
                if rejection_stats["Data_Gap_1H"] == 1:
                    ts_1h = current_time.floor('1h')
                    print(f"   ⚠️ SAMPLE DATA GAP: Time={current_time}, Looked for 1H={ts_1h}")
                    print(f"      Does 1H Index contain {ts_1h}? {ts_1h in df_1h.index}")
            else:
                rejection_stats["Logic_Fail"] += 1
                # Log a few "Close Calls" or Logic Fails
                if len(detailed_logs) < 5:
                     detailed_logs.append(f"❌ REJECT: {current_time} | Reason: {result['reason']}")

    # 4. REPORT
    print("\n📊 DIAGNOSTIC REPORT")
    print("--------------------")
    print(f"Scanned Candidates: {len(subset_5m)}")
    print(f"Rejected (NaN RSI): {rejection_stats['NaN_RSI']} (Expected if gaps exist)")
    print(f"Rejected (Data Gap): {rejection_stats['Data_Gap_1H']} (Critical Alignment Issue)")
    print(f"Rejected (Logic):   {rejection_stats['Logic_Fail']} (Strategy conditions not met)")
    print(f"SIGNALS FOUND:      {rejection_stats['Signal_Found']}")
    
    print("\n📜 DETAILED SAMPLE LOGS:")
    for log in detailed_logs:
        print(log)

if __name__ == "__main__":
    run_debug_scan()