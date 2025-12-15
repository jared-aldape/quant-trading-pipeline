import sys
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.utils.date_profiles import DATE_PROFILES 

log = get_logger("ForensicsEngine")

# Table Constants
TBL_RH = "active_rh_log"
TBL_SIM = "active_simulation_log"
TBL_MANIFEST = getattr(config, 'TBL_MANIFEST', 'option_signal_manifest')

# ==============================================================================
# 2. FIFO RECONCILER
# ==============================================================================
class FIFOReconciler:
    def process(self, df_ledger):
        if df_ledger.empty: return pd.DataFrame()
        df = df_ledger.sort_values('entry_time_utc').copy()
        inventory = {} 
        trades = []
        
        for _, row in df.iterrows():
            root = row.get('root', 'UNK')
            strike = row.get('strike', '0')
            otype = row.get('option_right', 'C')
            expiry = row.get('expiry_date', '0000-00-00')
            key = f"{root} {strike}{otype} {expiry}"
            
            if key not in inventory: inventory[key] = []
            
            action = str(row.get('action', '')).upper()
            qty = int(float(row.get('quantity', 0)))
            price = float(row.get('fill_price', 0))
            time = row['entry_time_utc']
            
            if 'BUY' in action or 'OPEN' in action:
                inventory[key].append({'price': price, 'time': time, 'quantity': qty})
            
            elif 'SELL' in action or 'CLOSE' in action:
                count = 0
                while count < qty and inventory[key]:
                    match = inventory[key][0]
                    can_close = min(qty - count, match['quantity'])
                    
                    entry_px = match['price']
                    exit_px = price
                    pnl = (exit_px - entry_px) * 100 * can_close
                    roi = (pnl / (entry_px * 100 * can_close)) * 100 if entry_px > 0 else 0
                    duration = (time - match['time']).total_seconds() / 60
                    
                    trades.append({
                        'entry_time': match['time'],
                        'exit_time': time,
                        'ticker': f"{root} {strike}{otype}",
                        'action': 'SELL',
                        'quantity': can_close,
                        'entry_price': entry_px,
                        'exit_price': exit_px,
                        'pnl': pnl,
                        'return_pct': roi,
                        'duration_mins': duration,
                        'status': 'CLOSED'
                    })
                    
                    match['quantity'] -= can_close
                    if match['quantity'] == 0: inventory[key].pop(0)
                    count += can_close
                    
        return pd.DataFrame(trades)

# ==============================================================================
# 3. DATA FETCHING LOGIC
# ==============================================================================
def fetch_scorecard_data(source='rh', date_profile_name='Last 30 Days'):
    if not config.DB_FILE.exists(): return pd.DataFrame()
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    if date_profile_name in DATE_PROFILES:
        profile = DATE_PROFILES[date_profile_name]
        start_date = profile.start_date
        end_date = profile.end_date
    else:
        start_date = datetime.now().date() - timedelta(days=30)
        end_date = datetime.now().date()

    try:
        # --- ROBINHOOD ---
        if source == 'rh':
            q = f"SELECT * FROM {TBL_RH} WHERE status = 'FILLED' ORDER BY entry_time_utc ASC"
            raw_df = con.execute(q).df()
            reconciler = FIFOReconciler()
            df = reconciler.process(raw_df)
            if not df.empty:
                df['entry_time'] = pd.to_datetime(df['entry_time'])
                df['exit_time'] = pd.to_datetime(df['exit_time'])
                mask = (df['exit_time'].dt.date >= start_date) & (df['exit_time'].dt.date <= end_date)
                df = df.loc[mask]
                df['price'] = df['exit_price']

        # --- SIMULATION ---
        elif source == 'gen' or source == 'manual':
            reason_filter = "reason = 'DATA_GENERATOR'" if source == 'gen' else "reason LIKE 'MANUAL%'"
            # CRITICAL FIX: Explicitly selecting 'exit_price' instead of aliasing it
            q = f"""
                SELECT entry_time, exit_time, ticker, 'SELL' as action,
                    entry_price, exit_price, quantity, 
                    net_pnl as pnl, return_pct, status
                FROM {TBL_SIM}
                WHERE {reason_filter}
                AND exit_time >= '{start_date}' AND exit_time <= '{end_date} 23:59:59'
                ORDER BY entry_time ASC
            """
            df = con.execute(q).df()
            
            # Post-process for consistency
            if not df.empty:
                df['price'] = df['exit_price']

        # --- RAW SIGNALS ---
        elif source == 'sig':
            start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
            end_ts = int(pd.Timestamp(f"{end_date} 23:59:59").timestamp() * 1000)
            tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
            if TBL_MANIFEST not in tables: return pd.DataFrame()
            q = f"""
                SELECT entry_timestamp_utc, trade_type, 'XSP ' || upper(trade_type) as ticker,
                    'SIGNAL' as action, 0.0 as pnl, 0.0 as return_pct
                FROM {TBL_MANIFEST}
                WHERE entry_timestamp_utc >= {start_ts} AND entry_timestamp_utc <= {end_ts}
                ORDER BY entry_timestamp_utc ASC
            """
            df = con.execute(q).df()
            
        else:
            return pd.DataFrame()
        
        # Common Post-Process
        if not df.empty:
            if source == 'sig':
                df['entry_time'] = pd.to_datetime(df['entry_timestamp_utc'], unit='ms')
                df['exit_time'] = df['entry_time']
                df['price'] = 0.0
                df['duration_mins'] = 0.0
                df['equity_curve'] = 0.0
            else:
                df['entry_time'] = pd.to_datetime(df['entry_time'])
                df['exit_time'] = pd.to_datetime(df['exit_time'])
                if 'duration_mins' not in df.columns:
                    df['duration_mins'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60
                df.loc[df['duration_mins'] < 0.1, 'duration_mins'] = 0.0
                df['equity_curve'] = df['pnl'].cumsum()
            
        return df

    except Exception as e:
        log.error(f"Stats Fetch Error: {e}")
        return pd.DataFrame()
    finally:
        con.close()

# ==============================================================================
# 4. LEGACY SUPPORT
# ==============================================================================
def fetch_rh_data():
    if not config.DB_FILE.exists(): return pd.DataFrame()
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        q = f"SELECT * FROM {TBL_RH} WHERE status = 'FILLED' ORDER BY entry_time_utc ASC"
        raw_df = con.execute(q).df()
        reconciler = FIFOReconciler()
        df = reconciler.process(raw_df)
        if not df.empty:
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            if 'duration_mins' not in df.columns:
                df['duration_mins'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60
            df['equity_curve'] = df['pnl'].cumsum()
        return df
    except Exception as e:
        log.error(f"Legacy Fetch Error: {e}")
        return pd.DataFrame()
    finally:
        con.close()

# ==============================================================================
# 5. METRICS
# ==============================================================================
def calculate_metrics(df):
    if df.empty: return {'net_pnl': 0, 'win_rate': 0, 'pf': 0, 'total_trades': 0}
    net_pnl = df['pnl'].sum()
    total_trades = len(df)
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
    gross_win = wins['pnl'].sum()
    gross_loss = abs(losses['pnl'].sum())
    pf = (gross_win / gross_loss) if gross_loss != 0 else 0
    return {'net_pnl': net_pnl, 'win_rate': win_rate, 'pf': pf, 'total_trades': total_trades}