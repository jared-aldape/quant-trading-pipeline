import sys
import duckdb
import pandas as pd
import pandas_ta as ta
import numpy as np
import json
from pathlib import Path
from datetime import timedelta

# ==============================================================================
# 1. ARCHITECTURE SETUP
# ==============================================================================
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parents[1]
sys.path.append(str(ROOT_DIR))

try:
    from src.utils import config
    from src.utils.logger import get_logger
    log = get_logger("MacroScanner")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("MacroScanner")
    class MockConfig:
        DB_FILE = "data/quant_strategy.duckdb"
        TBL_INDICES = "indices_1m"
        TBL_MANIFEST = "trade_manifest"
    config = MockConfig()

# ==============================================================================
# 2. FUNDAMENTAL INTELLIGENCE (THE BRAIN)
# ==============================================================================
def get_fundamental_bias():
    """
    Loads external macro context (CPI, Fed, News) to override technicals.
    In v4.0, this will read from 'data/macro_sentiment.json'.
    """
    return {
        "event": "CPI_NOV_2025", # Context for the log
        "bias": "BULLISH",       # Direction: BULLISH, BEARISH, or NEUTRAL
        "weight": 0.9,           # Confidence (0.0 - 1.0)
        "active": True           # MASTER SWITCH: Set to False to revert to pure Technicals
    }

# ==============================================================================
# 3. MACRO STRATEGY LOGIC
# ==============================================================================
def apply_macro_logic(df):
    """
    Applies Daily VIX Regime Logic + Fundamental Override.
    """
    # Calculate VIX 20-Day SMA (The "Fear Baseline")
    df['vix_sma'] = df.ta.sma(close='close', length=20)
    
    # Load The Narrative
    fund_data = get_fundamental_bias()
    
    signals = []
    
    # Iterate through the dataframe
    for i in range(1, len(df)):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        if pd.isna(curr['vix_sma']) or pd.isna(prev['vix_sma']):
            continue

        # TECHNICAL TRIGGERS
        # Bullish: VIX crosses BELOW SMA (Fear subsiding)
        vix_cross_under = (prev['close'] >= prev['vix_sma']) and (curr['close'] < curr['vix_sma'])
        # Bearish: VIX crosses ABOVE SMA (Fear rising)
        vix_cross_over = (prev['close'] <= prev['vix_sma']) and (curr['close'] > curr['vix_sma'])
        
        signal = None
        
        # --- LOGIC TREE: FUNDAMENTALS vs TECHNICALS ---
        if fund_data['active']:
            # A. BULLISH REGIME (e.g., Cool CPI)
            if fund_data['bias'] == "BULLISH":
                if vix_cross_under:
                    # Amplified Technical Signal
                    signal = {
                        'signal_type': 'MACRO_VIX_BULL',
                        'trade_type': 'call',
                        'reason': f"VIX Tech Buy + {fund_data['event']} (Strong)"
                    }
                elif curr['close'] < curr['vix_sma']:
                    # FORCE CONTINUATION: If VIX is low and Bias is Bull, keep buying dips
                    # This catches the "Gap and Go" days where no crossover happens
                    signal = {
                        'signal_type': 'MACRO_REGIME_LONG',
                        'trade_type': 'call',
                        'reason': f"Regime Continuation ({fund_data['event']})"
                    }
            
            # B. BEARISH REGIME (e.g., Tech Sell-off)
            elif fund_data['bias'] == "BEARISH":
                if vix_cross_over:
                    # Amplified Technical Signal
                    signal = {
                        'signal_type': 'MACRO_VIX_BEAR',
                        'trade_type': 'put',
                        'reason': f"VIX Tech Sell + {fund_data['event']} (Panic)"
                    }
                # Note: We rarely force "Regime Short" unless volatility is exploding
        
        else:
            # C. PURE TECHNICALS (Legacy Mode)
            if vix_cross_under:
                signal = {
                    'signal_type': 'MACRO_VIX_BULL',
                    'trade_type': 'call',
                    'reason': f"VIX ({curr['close']:.2f}) < SMA ({curr['vix_sma']:.2f})"
                }
            elif vix_cross_over:
                signal = {
                    'signal_type': 'MACRO_VIX_BEAR',
                    'trade_type': 'put',
                    'reason': f"VIX ({curr['close']:.2f}) > SMA ({curr['vix_sma']:.2f})"
                }
            
        if signal:
            # TACTICAL ADJUSTMENT: RTH ALIGNMENT
            # Signal generated at Close of Day T. 
            # Entry targeted for 10:00 ET (15:00 UTC) on Day T+1.
            curr_ts = pd.Timestamp(curr['datetime_utc'])
            entry_date = curr_ts + timedelta(days=1)
            
            # Set to 15:00 UTC (10:00 ET) to clear the opening volatility
            entry_ts = entry_date.replace(hour=15, minute=0, second=0, microsecond=0)
            
            signals.append({
                'entry_timestamp_utc': int(entry_ts.timestamp() * 1000),
                'date': entry_ts.date(),
                'signal_type': signal['signal_type'],
                'trade_type': signal['trade_type'],
                'meta_data': signal['reason'],
                'allocation_pct': 1.0 
            })

    return pd.DataFrame(signals)

# ==============================================================================
# 4. EXECUTION
# ==============================================================================
def run_macro_scan():
    log.info("📡 MACRO SCANNER v3.5 (REGIME AWARE) INITIALIZED...")
    
    if not Path(config.DB_FILE).exists():
        log.error("❌ DB File Not Found")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    try:
        # 1. FETCH DAILY VIX DATA
        query = f"""
            SELECT 
                date_trunc('day', datetime_utc) as datetime_utc, 
                AVG(close) as close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'VIX' 
            GROUP BY 1
            ORDER BY 1 ASC
        """
        df = con.execute(query).df()
        
        if df.empty:
            log.warning("⚠️ No VIX Data Found.")
            con.close()
            return

        # 2. FETCH SPX PRICE (For Strikes)
        spx_df = con.execute(f"""
            SELECT 
                date_trunc('day', datetime_utc) as datetime_utc, 
                AVG(close) as close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'SPX' 
            GROUP BY 1
            ORDER BY 1 ASC
        """).df()
        
        # Merge Pre-processing
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
        spx_df['datetime_utc'] = pd.to_datetime(spx_df['datetime_utc'])
        
        # Merge VIX and SPX
        df = pd.merge(df, spx_df, on='datetime_utc', suffixes=('', '_spx'), how='left')
        df['close_spx'] = df['close_spx'].ffill() 

        # 3. RUN STRATEGY (WITH BIAS)
        log.info(f"🧠 Processing {len(df)} daily candles with Fundamental Bias...")
        signal_df = apply_macro_logic(df)
        
        if signal_df.empty:
            log.warning("⚠️ No Macro Signals generated.")
            con.close()
            return

        # 4. MAP XSP PRICE (SMART SCALING)
        # Force Nanosecond Precision
        signal_df['date'] = pd.to_datetime(signal_df['date']).astype('datetime64[ns]')
        df['datetime_utc'] = pd.to_datetime(df['datetime_utc']).astype('datetime64[ns]')

        # Merge signal date with underlying price date
        signal_df = pd.merge_asof(
            signal_df.sort_values('date'),
            df[['datetime_utc', 'close_spx']].sort_values('datetime_utc'),
            left_on='date', 
            right_on='datetime_utc',
            direction='backward'
        )
        
        # Auto-Scale Index vs ETF
        signal_df['xsp_price'] = np.where(
            signal_df['close_spx'] > 2000, 
            signal_df['close_spx'] / 10.0, 
            signal_df['close_spx']
        )

        # 5. WRITE TO VAULT (UPSERT MODE)
        log.info(f"💾 Saving {len(signal_df)} Macro Signals...")
        
        # Delete existing Macro signals to prevent duplicates
        con.execute(f"DELETE FROM {config.TBL_MANIFEST} WHERE signal_type LIKE 'MACRO%'")
        
        db_rows = signal_df[['entry_timestamp_utc', 'date', 'signal_type', 'xsp_price', 'trade_type', 'meta_data', 'allocation_pct']]
        
        con.register('macro_signals', db_rows)
        con.execute(f"INSERT INTO {config.TBL_MANIFEST} SELECT * FROM macro_signals")
        
        log.info("✅ MANIFEST UPDATED.")

    except Exception as e:
        log.error(f"❌ SCANNER ERROR: {e}")
        import traceback
        traceback.print_exc()
        
    con.close()

if __name__ == "__main__":
    run_macro_scan()