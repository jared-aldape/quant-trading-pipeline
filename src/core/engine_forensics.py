import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("ForensicsEngine")

def fetch_simulation_runs():
    """Fetches a list of all unique Run IDs from the simulation log."""
    if not config.DB_FILE.exists(): return []
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        # Check if table exists
        tables = con.execute("SHOW TABLES").fetchall()
        if (config.TBL_SIM_LOG,) not in tables:
            con.close()
            return []
            
        runs = con.execute(f"SELECT DISTINCT run_id FROM {config.TBL_SIM_LOG} ORDER BY run_id DESC").fetchall()
        con.close()
        
        # Return format for Dash Dropdown
        return [{'label': r[0], 'value': r[0]} for r in runs]
    except Exception as e:
        log.error(f"Failed to fetch runs: {e}")
        return []

def fetch_run_metrics(run_id):
    """
    Fetches the full trade log for a specific Run ID.
    Auto-detects column names and handles Timezones correctly.
    """
    if not run_id: return pd.DataFrame()
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Schema Inspection
        columns = [c[0] for c in con.execute(f"DESCRIBE {config.TBL_SIM_LOG}").fetchall()]
        
        # Map variables to actual DB columns
        pnl_col = 'pnl' if 'pnl' in columns else 'net_pnl'
        dur_col = 'duration_mins' if 'duration_mins' in columns else 'duration'
        
        # 2. Fetch Data
        query = f"""
            SELECT 
                entry_time, 
                type, 
                {pnl_col} as pnl, 
                {dur_col} as duration,
                return_pct,
                reason,
                signal_rank
            FROM {config.TBL_SIM_LOG}
            WHERE run_id = '{run_id}'
            ORDER BY entry_time ASC
        """
        df = con.execute(query).df()
        con.close()
        
        # 3. Enrich Data for Analysis
        if not df.empty:
            # TIMEZONE FIX: 
            # The Backtester saves 'entry_time' as Local Time (PST).
            # We simply force it to datetime objects and extract the hour.
            df['entry_time'] = pd.to_datetime(df['entry_time'], errors='coerce')
            
            # If the DB returned naive datetime (e.g. 2023-10-01 09:30:00), .dt.hour works perfectly.
            # If it returned offset-aware strings, pandas handles it.
            # We DO NOT convert to UTC and back, avoiding the double-shift bug.
            
            df['hour'] = df['entry_time'].dt.hour
            
            # Sequence for Signal Decay
            df['trade_seq'] = range(1, len(df) + 1)
            
        return df

    except Exception as e:
        log.error(f"Forensics Data Error: {e}")
        return pd.DataFrame()