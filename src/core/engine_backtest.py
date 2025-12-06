import sys
import duckdb
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# ==============================================================================
# 0. ENVIRONMENT PATCH (WINDOWS COMPATIBILITY)
# ==============================================================================
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except: pass

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import engine_simulator

log = get_logger("BacktestEngine")

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def calculate_detailed_fees(num_contracts, fee_model="RH_GOLD"):
    """
    Returns breakdown: (total_fee, reg_fee, contract_fee)
    Uses engine_simulator logic for consistency.
    """
    return engine_simulator.calculate_detailed_fees(num_contracts, fee_model)

def fetch_manifest_data(limit_days=30):
    """Fetches signals from the Vault."""
    if not config.DB_FILE.exists(): return pd.DataFrame()
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        # Fetch manifest ordered by time
        query = f"""
            SELECT * FROM {config.TBL_MANIFEST} 
            ORDER BY entry_timestamp_utc ASC
        """
        df = con.execute(query).df()
        
        # Filter by days
        if not df.empty and 'date' in df.columns:
            cutoff = pd.Timestamp.now().date() - timedelta(days=limit_days)
            df['date'] = pd.to_datetime(df['date']).dt.date
            df = df[df['date'] >= cutoff]
            
        return df
    except Exception as e:
        log.error(f"Manifest Fetch Error: {e}")
        return pd.DataFrame()
    finally:
        con.close()

def fetch_option_price(ticker, timestamp_utc, mode='open'):
    """
    Fetches the option price from the Vault at a specific time.
    Uses ASOF logic (nearest prior tick).
    """
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # Format timestamp for SQL
    ts_str = timestamp_utc.strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        # ASOF Lookup: Find the last known price before or at the timestamp
        query = f"""
            SELECT {mode} 
            FROM {config.TBL_OPTIONS} 
            WHERE ticker = '{ticker}' 
            AND datetime_utc <= '{ts_str}' 
            ORDER BY datetime_utc DESC 
            LIMIT 1
        """
        res = con.execute(query).fetchone()
        return res[0] if res else None
    except Exception:
        return None
    finally:
        con.close()

# ==============================================================================
# 3. CORE BACKTEST LOOPS
# ==============================================================================
def run_backtest_session(initial_balance=1000.0, days=30, selection_mode='FIRST', hedged_mode=True):
    """
    Executes the simulation based on Trade Manifest signals.
    """
    log.info(f"⚔️ Starting Backtest (Hedged: {hedged_mode} | Selection: {selection_mode})")
    
    # 1. Load Signals
    signals = fetch_manifest_data(limit_days=days)
    if signals.empty:
        log.warning("⚠️ No signals found in Manifest.")
        return pd.DataFrame()

    # 2. Load Macro Flow (for Hedging)
    flow_map = {}
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        flow_df = con.execute(f"SELECT date, flow_bias FROM {config.TBL_MACRO_FLOW}").df()
        con.close()
        flow_df['date'] = pd.to_datetime(flow_df['date']).dt.date
        flow_map = dict(zip(flow_df['date'], flow_df['flow_bias']))
    except: pass

    # 3. Simulation State
    balance = initial_balance
    trades = []
    
    # Group by Date to handle daily selection logic
    grouped = signals.groupby('date')
    
    for date, group in grouped:
        daily_candidates = []
        
        # --- A. PROCESS CANDIDATES ---
        for _, row in group.iterrows():
            signal_type = row['trade_type'] # 'call' or 'put'
            macro_bias = flow_map.get(date, 'NEUTRAL')
            
            # HEDGED PROTOCOL LOGIC:
            # If Bearish Flow, prioritize Puts. If Bullish, Calls.
            if hedged_mode:
                if macro_bias == 'BEAR' and signal_type == 'call': continue # Skip counter-trend
                if macro_bias == 'BULL' and signal_type == 'put': continue
            
            # Ticker Construction (Same as Sentinel)
            # We need to construct the ticker string to lookup prices
            # Schema: O:XSP{YYMMDD}{C/P}{STRIKE}
            try:
                dt_obj = pd.to_datetime(date)
                ticker_date = dt_obj.strftime('%y%m%d')
                strike = int(round(row['xsp_price']))
                char = 'C' if signal_type == 'call' else 'P'
                strike_str = f"{strike*1000:08d}"
                ticker = f"O:XSP{ticker_date}{char}{strike_str}"
                
                # Timestamp Handling (UTC for Vault)
                entry_ts = row['entry_timestamp_utc'] # ms
                entry_dt_utc = datetime.fromtimestamp(entry_ts/1000.0, tz=pytz.utc)
                
                # --- ENTRY PRICE ---
                entry_price = fetch_option_price(ticker, entry_dt_utc, 'open')
                if not entry_price: continue
                
                # --- EXIT SIMULATION ---
                # Strategy: Hold for 60 minutes or End of Day
                exit_dt_utc = entry_dt_utc + timedelta(minutes=60)
                exit_price = fetch_option_price(ticker, exit_dt_utc, 'open')
                
                # Fallback: Close at EOD if no 60m data (e.g. late entry)
                if not exit_price:
                    # Try getting the last tick of the day
                    eod_dt = entry_dt_utc.replace(hour=20, minute=59) # ~4 PM ET in UTC
                    exit_price = fetch_option_price(ticker, eod_dt, 'close')
                
                if not exit_price: continue # Skip if bad data
                
                # --- FEES & PNL ---
                # Position Sizing: 10% of current balance
                alloc_amt = balance * 0.10
                contract_cost = entry_price * 100
                contracts = int(alloc_amt / contract_cost)
                if contracts < 1: contracts = 1
                
                total_fee, _, _ = calculate_detailed_fees(contracts)
                
                entry_cost = (contracts * contract_cost) + total_fee
                # APPLY SLIPPAGE: $0.01 per contract on entry and exit
                slippage = 0.01 * 100 * contracts
                
                # Exit
                gross_return = (contracts * exit_price * 100)
                exit_fee, _, _ = calculate_detailed_fees(contracts)
                net_pnl = gross_return - entry_cost - exit_fee - (slippage * 2) # Slippage both sides
                
                ret_pct = (net_pnl / entry_cost) * 100
                
                # Convert times to PST for "The Glass" (Reporting)
                pst_entry = entry_dt_utc.astimezone(config.TZ_LOCAL).strftime('%H:%M')
                pst_exit = exit_dt_utc.astimezone(config.TZ_LOCAL).strftime('%H:%M')

                daily_candidates.append({
                    'entry_timestamp': entry_ts, # <--- CRITICAL FIX: Restored for sorting
                    'entry_time': pst_entry,
                    'exit_time': pst_exit,
                    'ticker': ticker,
                    'type': signal_type.upper(),
                    'contracts': contracts,
                    'entry': entry_price,
                    'exit': exit_price,
                    'pnl': net_pnl,
                    'return': ret_pct,
                    'balance_impact': net_pnl
                })
                
            except Exception as e:
                log.error(f"Sim Error {date}: {e}")
                continue

        # --- B. SELECT TRADES ---
        if not daily_candidates: continue
        
        # Sort by timestamp to find the chronological first
        daily_candidates.sort(key=lambda x: x['entry_timestamp']) # <--- CRITICAL FIX: Sorting Logic

        selected_trades = []
        if selection_mode == 'FIRST':
            selected_trades = [daily_candidates[0]]
        elif selection_mode == 'ALL':
            selected_trades = daily_candidates
            
        # --- C. COMMIT TRADES ---
        for t in selected_trades:
            balance += t['balance_impact']
            trades.append({
                'Date': date,
                'Time': t['entry_time'],
                'Type': t['type'],
                'Ticker': t['ticker'],
                'Entry': f"${t['entry']:.2f}",
                'Exit': f"${t['exit']:.2f}",
                'Contracts': t['contracts'],
                'PnL': f"${t['pnl']:.2f}",
                'Return': f"{t['return']:.1f}%",
                'Balance': f"${balance:.2f}"
            })

    return pd.DataFrame(trades)

if __name__ == "__main__":
    df = run_backtest_session(days=5, selection_mode='FIRST')
    print(df.to_markdown(index=False))