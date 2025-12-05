import sys
import os
import duckdb
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
from pathlib import Path
import pytz
import uuid

# ==============================================================================
# 0. ENVIRONMENT PATCH (WINDOWS COMPATIBILITY)
# ==============================================================================
# CRITICAL: Force UTF-8 Encoding to allow "Vibe Code" Emojis (🚀, ⚠️) on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception as e:
        print(f"⚠️ Warning: Could not force UTF-8 encoding. Emojis may fail. {e}")

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")

MORNING_EXIT_MINUTES = 80   
AFTERNOON_EXIT_MINUTES = 21 
MORNING_CUTOFF_ET = time(12, 30) 

TZ_UTC = pytz.timezone('UTC')
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def convert_to_pst(dt_input):
    try:
        if dt_input is None: return None
        if isinstance(dt_input, str): dt_obj = pd.to_datetime(dt_input)
        else: dt_obj = dt_input
        if dt_obj.tzinfo is None: dt_obj = TZ_UTC.localize(dt_obj)
        else: dt_obj = dt_obj.tz_convert(TZ_UTC)
        return dt_obj.astimezone(TZ_PST)
    except Exception: return None

def format_duration(dt_start, dt_end):
    try:
        if not dt_start or not dt_end: return "--"
        delta = dt_end - dt_start
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours > 0: return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except: return "--"

def reconstruct_ticker(trade_type, xsp_price, date_obj):
    try:
        if xsp_price is None: return None
        try: price_val = float(xsp_price)
        except: return None
        if pd.isna(price_val) or price_val <= 0: return None
        date_str = date_obj.strftime('%y%m%d')
        opt_type = 'P' if trade_type == 'put' else 'C'
        strike_raw = round(price_val)
        strike_str = f"{int(strike_raw * 1000):08d}"
        return f"O:XSP{date_str}{opt_type}{strike_str}"
    except Exception: return None

def lookup_price(con, ticker, query_time):
    try:
        ts_str = query_time.strftime('%Y-%m-%d %H:%M:%S')
        query = f"""
            SELECT open, datetime_utc 
            FROM {config.TBL_OPTIONS}
            WHERE ticker = '{ticker}' 
            AND datetime_utc >= '{ts_str}'
            ORDER BY datetime_utc ASC
            LIMIT 1
        """
        result = con.execute(query).fetchone()
        if result: return result[0], result[1] 
        return None, None
    except Exception: return None, None

def calculate_fees(ticker, num_contracts, fee_model, manual_comm):
    if fee_model == 'NONE': return 0.0
    if fee_model == 'MANUAL': return manual_comm
    is_gold = (fee_model == 'RH_GOLD')
    fees = config.RH_FEES
    base = fees['REGULATORY_BASE']
    broker = fees['CONTRACT_GOLD'] if is_gold else fees['CONTRACT_STD']
    extra = 0.0
    is_index = any(x in ticker for x in ["XSP", "SPX", "NDX", "VIX"])
    if is_index:
        if "XSP" in ticker and num_contracts >= 10: extra = fees['INDEX_EXCHANGE']
    else: extra = fees['EQUITY_TAF']
    return base + broker + extra

def manage_trade_exit(con, ticker, entry_price, entry_time, duration_min, stop_pct, target_pct, be_pct, slippage_buffer):
    try:
        exit_deadline = entry_time + timedelta(minutes=duration_min)
        entry_str = entry_time.strftime('%Y-%m-%d %H:%M:%S')
        deadline_str = exit_deadline.strftime('%Y-%m-%d %H:%M:%S')
        active_stop_price = entry_price * (1 - stop_pct) if stop_pct else 0
        target_price = entry_price * (1 + target_pct) if target_pct else 999999
        be_activation_price = entry_price * (1 + be_pct) if be_pct else 999999
        is_be_active = False

        query = f"""
            SELECT open, datetime_utc 
            FROM {config.TBL_OPTIONS}
            WHERE ticker = '{ticker}' 
            AND datetime_utc > '{entry_str}'
            AND datetime_utc <= '{deadline_str}'
            ORDER BY datetime_utc ASC
        """
        price_path = con.execute(query).fetchall()
        if not price_path: return None, None, "NO_DATA"

        for price, ts in price_path:
            if be_pct and not is_be_active and price >= be_activation_price:
                is_be_active = True
                active_stop_price = entry_price + (slippage_buffer * 2)
            if price <= active_stop_price:
                reason = "BE_STOP" if is_be_active else "STOP_LOSS"
                return price, ts, reason
            if target_pct and price >= target_price: 
                return price, ts, "TAKE_PROFIT"
        final_price, final_ts = price_path[-1]
        return final_price, final_ts, "TIME_EXIT"
    except Exception: return None, None, "ERROR"

# ==============================================================================
# 3. PERSISTENCE LAYER
# ==============================================================================
def persist_to_database(df, run_meta):
    if df.empty: return
    con = None
    try:
        con = duckdb.connect(str(config.DB_FILE))
        save_df = df.copy()
        save_df['run_id'] = run_meta['run_id']
        save_df['strategy_mode'] = run_meta['mode']
        save_df['timestamp'] = datetime.now()
        con.register('df_staging', save_df)
        try:
            con.execute(f"INSERT INTO {config.TBL_SIM_LOG} SELECT run_id, strategy_mode, timestamp, entry_time, exit_time, ticker, type, signal_rank, duration_str, duration_mins, reason, entry_px, exit_px, return_pct, pnl, position_size, start_balance, end_balance, balance FROM df_staging")
            log.info(f"✅ Run persisted cleanly.")
        except Exception as e:
            log.warning(f"⚠️ Standard Write Failed ({e}). Initiating Schema Repair...")
            con.execute(f"DROP TABLE IF EXISTS {config.TBL_SIM_LOG}")
            con.execute(f"""
                CREATE TABLE {config.TBL_SIM_LOG} (
                    run_id VARCHAR, strategy_mode VARCHAR, timestamp TIMESTAMP, entry_time TIMESTAMP, exit_time TIMESTAMP, ticker VARCHAR, type VARCHAR, signal_rank INTEGER, duration_str VARCHAR, duration_mins DOUBLE, reason VARCHAR, entry_px DOUBLE, exit_px DOUBLE, return_pct DOUBLE, pnl DOUBLE, position_size DOUBLE, start_balance DOUBLE, end_balance DOUBLE, balance DOUBLE
                )
            """)
            con.execute(f"INSERT INTO {config.TBL_SIM_LOG} SELECT run_id, strategy_mode, timestamp, entry_time, exit_time, ticker, type, signal_rank, duration_str, duration_mins, reason, entry_px, exit_px, return_pct, pnl, position_size, start_balance, end_balance, balance FROM df_staging")
            log.info(f"✅ Schema Repaired & Data Persisted.")
    except Exception as e:
        log.error(f"❌ CRITICAL DB FAILURE: {e}")
    finally:
        if con:
            con.unregister('df_staging')
            con.close()

# ==============================================================================
# 4. MAIN EXECUTION ROUTINE
# ==============================================================================
def run_backtest(args):
    start_date = getattr(args, 'start_date', None) or '2025-09-11'
    end_date = getattr(args, 'end_date', None) or '2025-12-01'
    start_balance = getattr(args, 'start_balance', None) or 600.0
    strategy_mode = getattr(args, 'strategy_mode', None) or 'Fractal'
    selection_mode = getattr(args, 'selection_mode', None) or 'FIRST'
    archive_report = getattr(args, 'archive_report', False)
    stop_loss_pct = getattr(args, 'trailing_stop_pct', None)
    take_profit_pct = getattr(args, 'ideal_gain_pct', None)
    be_pct = getattr(args, 'breakeven_pct', None)
    slippage = getattr(args, 'slippage', 0.0)
    fee_model = getattr(args, 'fee_model', 'NONE')
    manual_comm = getattr(args, 'commission', 0.65)
    
    run_id = f"SIM_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log.info(f"🚀 Starting Run: {run_id} | Mode: {strategy_mode}")

    if not os.path.exists(config.DB_FILE): return pd.DataFrame()
    manifest_df = pd.DataFrame()
    flow_df = pd.DataFrame()
    try: 
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        try:
            flow_df = con.execute(f"SELECT date, flow_bias FROM {config.TBL_MACRO_FLOW}").df()
            flow_df['date'] = pd.to_datetime(flow_df['date']).dt.date
            flow_df = flow_df.set_index('date')
        except: pass
        query = f"SELECT * FROM {config.TBL_MANIFEST} WHERE date >= date('{start_date}') AND date <= date('{end_date}') ORDER BY entry_timestamp_utc ASC"
        manifest_df = con.execute(query).df()
        con.close()
    except Exception: return pd.DataFrame()

    if manifest_df.empty: return pd.DataFrame()
    try: price_lookup_con = duckdb.connect(str(config.DB_FILE), read_only=True)
    except: return pd.DataFrame()

    balance = start_balance
    trades = []
    manifest_df['date'] = pd.to_datetime(manifest_df['date']).dt.date
    
    for date, daily_signals in manifest_df.groupby('date'):
        daily_bias = 'NEUTRAL'
        if not flow_df.empty and date in flow_df.index: daily_bias = flow_df.loc[date, 'flow_bias']
        
        # --- PROFILE LOGIC ---
        call_weight, put_weight = 0.0, 0.0
        
        # 1. Fractal (Scanner Truth)
        if strategy_mode == 'Fractal': 
            call_weight = 1.0; put_weight = 1.0
            
        # 2. Macro (Dynamic)
        elif strategy_mode == 'Macro':
            if daily_bias == 'BEAR': call_weight = 0.25; put_weight = 0.75
            else: call_weight = 0.75; put_weight = 0.25
            
        # 3. Call (Long Only)
        elif strategy_mode == 'Call': 
            call_weight = 1.0; put_weight = 0.0
            
        # 4. Put (Long Put Only)
        elif strategy_mode == 'Put': 
            call_weight = 0.0; put_weight = 1.0
            
        # 5. Hedged Call (Bullish Bias)
        elif strategy_mode == 'Hedged Call': 
            call_weight = 0.75; put_weight = 0.25
            
        # 6. Hedged Put (Bearish Bias)
        elif strategy_mode == 'Hedged Put': 
            call_weight = 0.25; put_weight = 0.75

        daily_candidates = []
        signal_rank_counter = 0 
        
        for _, row in daily_signals.iterrows():
            signal_rank_counter += 1
            try:
                trade_type = row.get('trade_type', 'call')
                # SELECT WEIGHT BASED ON TRADE TYPE
                final_weight = call_weight if trade_type == 'call' else put_weight
                
                if final_weight <= 0: continue
                allocation_amt = balance * final_weight
                ticker = reconstruct_ticker(trade_type, row.get('xsp_price'), date)
                if not ticker: continue
                
                entry_ts = pd.Timestamp(row['entry_timestamp_utc'], unit='ms', tz='UTC')
                raw_entry, actual_entry_time = lookup_price(price_lookup_con, ticker, entry_ts)
                if not raw_entry: continue
                
                eff_entry = raw_entry + slippage
                contract_cost = eff_entry * 100
                est_fee = calculate_fees(ticker, 1, fee_model, manual_comm)
                num_contracts = int(allocation_amt / (contract_cost + est_fee))
                if num_contracts < 1: continue
                
                entry_fees = num_contracts * est_fee
                actual_invested = (num_contracts * contract_cost) + entry_fees
                entry_et = entry_ts.tz_convert(config.TZ_NY)
                is_morning = entry_et.time() < MORNING_CUTOFF_ET
                time_limit = MORNING_EXIT_MINUTES if is_morning else AFTERNOON_EXIT_MINUTES
                
                raw_exit, actual_exit_time, reason = manage_trade_exit(
                    price_lookup_con, ticker, raw_entry, entry_ts, time_limit, 
                    stop_loss_pct, take_profit_pct, be_pct, slippage
                )
                
                if raw_exit:
                    eff_exit = raw_exit - slippage
                    exit_fees = calculate_fees(ticker, num_contracts, fee_model, manual_comm) * num_contracts
                    gross_proceeds = num_contracts * 100 * eff_exit
                    net_pnl = (gross_proceeds - exit_fees) - actual_invested
                    pct_return = net_pnl / actual_invested
                    pst_entry = convert_to_pst(actual_entry_time)
                    pst_exit = convert_to_pst(actual_exit_time)
                    duration_str = format_duration(actual_entry_time, actual_exit_time)
                    duration_mins = (actual_exit_time - actual_entry_time).total_seconds() / 60
                    
                    # TACTICAL FIX: ADD 'entry_timestamp' HERE
                    daily_candidates.append({
                        'entry_timestamp': entry_ts, # <--- RESTORED KEY
                        'entry_time': pst_entry, 'exit_time': pst_exit,
                        'ticker': ticker, 'type': trade_type,
                        'signal_rank': signal_rank_counter, 'duration_str': duration_str, 'duration_mins': duration_mins,
                        'reason': reason, 'entry_px': round(eff_entry, 2), 'exit_px': round(eff_exit, 2),
                        'return_pct': round(pct_return * 100, 2), 'pnl': net_pnl, 'position_size': actual_invested
                    })
            except Exception: continue
        
        if not daily_candidates: continue
        selected_trade = None
        if selection_mode == 'FIRST':
            daily_candidates.sort(key=lambda x: x['entry_timestamp'])
            selected_trade = daily_candidates[0]
        elif selection_mode == 'BEST':
            daily_candidates.sort(key=lambda x: x['pnl'], reverse=True)
            selected_trade = daily_candidates[0]
            
        if selected_trade:
            start_bal_trade = balance
            balance += selected_trade['pnl']
            selected_trade['start_balance'] = round(start_bal_trade, 2)
            selected_trade['end_balance'] = round(balance, 2)
            selected_trade['balance'] = round(balance, 2)
            selected_trade['pnl'] = round(selected_trade['pnl'], 2)
            # Remove timestamp obj before saving (serialization safety)
            del selected_trade['entry_timestamp']
            trades.append(selected_trade)

    price_lookup_con.close()
    if not trades: return pd.DataFrame()
    results = pd.DataFrame(trades)
    persist_to_database(results, {'run_id': run_id, 'mode': strategy_mode})
    if archive_report:
        try:
            report_dir = ROOT_DIR / "reports"
            report_dir.mkdir(exist_ok=True)
            filename = f"Backtest_{strategy_mode}_{selection_mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            results.to_csv(report_dir / filename, index=False)
        except: pass
    return results

if __name__ == "__main__":
    class Args:
        start_date = '2025-01-01'
        end_date = '2025-12-31'
        start_balance = 1000.0
        strategy_mode = 'Fractal'
        selection_mode = 'FIRST'
        trailing_stop_pct = 0.20
        ideal_gain_pct = 0.40
        breakeven_pct = 0.10
        slippage = 0.01
        fee_model = 'RH_GOLD'
        commission = 0.65
        archive_report = True
    run_backtest(Args())