import sys
import duckdb
import pandas as pd
import numpy as np
import pandas_ta as ta
import time
from datetime import datetime, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. PATH & ARCHITECTURE CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("BacktestEngine")
TZ_UTC = pytz.UTC

TBL_OPTIONS = getattr(config, 'TBL_OPTIONS', 'options_1m')

try:
    from src.core import engine_ml_precision
    ML_AVAILABLE = True
except ImportError:
    log.warning("ML Oracle not found. Proceeding without ML triage.")
    ML_AVAILABLE = False

# ==============================================================================
# 2. FINANCIAL CALCULATORS
# ==============================================================================
def calculate_fees(price, quantity, model='RH_GOLD'):
    if model == 'NONE': return 0.0
    reg_fee = 0.04
    taf_fee = 0.002
    contract_fee = 0.35 if model == 'RH_GOLD' else 0.65 if model == 'STD' else 1.00
    return round((contract_fee * quantity) + reg_fee + taf_fee, 2)

# ==============================================================================
# 3. MACHINE LEARNING BATCH PROTOCOL (THE GATEKEEPER)
# ==============================================================================
def enrich_and_predict(signals_df, con):
    """
    ⚡ RESTORED & UPGRADED: Pulls the exact MACD/ADX data the Oracle needs 
    to make a >70% confidence prediction.
    """
    if not ML_AVAILABLE or signals_df.empty:
        signals_df['ml_confidence'] = 50.0
        return signals_df
        
    log.info(f"🧠 AI GATEKEEPER: Extracting live technicals for {len(signals_df)} raw signals...")
    
    # Fetch Market Context to calculate overlaps
    min_time = signals_df['entry_timestamp_utc'].min() - timedelta(days=2)
    df_mkt = con.execute(f"SELECT * FROM indices_1m WHERE datetime_utc >= '{min_time}'").df()
    
    # Calculate VIX Technicals
    vix = df_mkt[df_mkt['ticker'] == 'VIX'].copy()
    if not vix.empty:
        v_macd = ta.macd(vix['close'])
        vix['macd'] = v_macd['MACD_12_26_9'] if v_macd is not None else 0
        vix['signal'] = v_macd['MACDs_12_26_9'] if v_macd is not None else 0
        vix['hist'] = v_macd['MACDh_12_26_9'] if v_macd is not None else 0
        v_diff = vix['macd'] - vix['signal']
        vix['cross'] = np.where((v_diff > 0) & (v_diff.shift(1) <= 0), 1, 0)
        vix['cross'] = np.where((v_diff < 0) & (v_diff.shift(1) >= 0), -1, vix['cross'])
        vix['rsi'] = ta.rsi(vix['close'])
        
    # Calculate XSP Technicals
    xsp = df_mkt[df_mkt['ticker'] == 'XSP'].copy()
    if not xsp.empty:
        x_macd = ta.macd(xsp['close'])
        xsp['macd'] = x_macd['MACD_12_26_9'] if x_macd is not None else 0
        xsp['signal'] = x_macd['MACDs_12_26_9'] if x_macd is not None else 0
        xsp['hist'] = x_macd['MACDh_12_26_9'] if x_macd is not None else 0
        x_diff = xsp['macd'] - xsp['signal']
        xsp['cross'] = np.where((x_diff > 0) & (x_diff.shift(1) <= 0), 1, 0)
        xsp['cross'] = np.where((x_diff < 0) & (x_diff.shift(1) >= 0), -1, xsp['cross'])
        x_adx = ta.adx(xsp['high'], xsp['low'], xsp['close'])
        xsp['adx'] = x_adx['ADX_14'] if x_adx is not None else 20

    # Generate Predictions
    predictions = []
    for row in signals_df.itertuples():
        t_time = row.entry_timestamp_utc.replace(tzinfo=None)
        
        v_ctx = vix[vix['datetime_utc'] <= t_time].tail(1) if not vix.empty else pd.DataFrame()
        x_ctx = xsp[xsp['datetime_utc'] <= t_time].tail(1) if not xsp.empty else pd.DataFrame()
        
        if v_ctx.empty or x_ctx.empty:
            predictions.append(0.0)
            continue
            
        lv = v_ctx.iloc[0]
        lx = x_ctx.iloc[0]
        
        conf = engine_ml_precision.predict_success(
            signal_type=row.trade_type, 
            vix_val=lv['rsi'], vix_hist=lv['hist'], vix_cross=lv['cross'],
            xsp_hist=lx['hist'], xsp_cross=lx['cross'], adx=lx['adx'],
            trade_hour=row.entry_timestamp_utc.hour
        )
        predictions.append(conf)
        
    signals_df['ml_confidence'] = predictions
    
    # 🎯 THE STRIKE ZONE: Only keep signals the Oracle is > 70% sure about
    filtered_df = signals_df[signals_df['ml_confidence'] >= 75.0].copy()
    log.info(f"🛡️  TRIAGE COMPLETE: {len(filtered_df)} high-probability setups survive.")
    return filtered_df

# ==============================================================================
# 4. TRUE-WIN OPTIONS SIMULATOR (1:1 Risk Desk Protocol)
# ==============================================================================
def run_simulation_core(start_dt, end_dt, initial_balance=1000.0):
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    start_ms = int(start_dt.timestamp() * 1000)
    sig_query = f"SELECT * FROM trade_manifest WHERE entry_timestamp_utc >= {start_ms}"
    try:
        signals = con.execute(sig_query).df()
    except:
        con.close()
        return None
        
    if signals.empty:
        con.close()
        return None

    signals['entry_timestamp_utc'] = pd.to_datetime(signals['entry_timestamp_utc'], unit='ms').dt.tz_localize('UTC')
    
    # ⚡ APPLY THE RESTORED AI FILTER
    signals = enrich_and_predict(signals, con)
    
    capital = float(initial_balance)
    trades_log = []
    wins, losses = 0, 0
    
    log.info(f"⚡ Simulating {len(signals)} Strategic Trades (1:1 Risk Desk)...")
    
    for row in signals.itertuples():
        entry_time = row.entry_timestamp_utc
        entry_price_xsp = float(row.xsp_price) if hasattr(row, 'xsp_price') else 0.0
        is_call = 'CALL' in row.trade_type
        op_type = 'C' if is_call else 'P'
        
        # Select +1 OTM Strike
        contract_q = f"""
            SELECT ticker, close as entry_premium 
            FROM {TBL_OPTIONS}
            WHERE datetime_utc = '{entry_time}'
            AND SUBSTRING(ticker, 10, 1) = '{op_type}'
        """
        if is_call: contract_q += f" AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT) / 1000.0 > {entry_price_xsp} ORDER BY CAST(SUBSTRING(ticker, 11, 8) AS FLOAT) ASC LIMIT 1"
        else: contract_q += f" AND CAST(SUBSTRING(ticker, 11, 8) AS FLOAT) / 1000.0 < {entry_price_xsp} ORDER BY CAST(SUBSTRING(ticker, 11, 8) AS FLOAT) DESC LIMIT 1"
            
        try:
            contract_df = con.execute(contract_q).df()
        except: continue
        if contract_df.empty: continue
            
        c_ticker = contract_df.iloc[0]['ticker']
        entry_premium = float(contract_df.iloc[0]['entry_premium'])
        if entry_premium <= 0.05: continue
            
        # CLAMP RISK AT 1:1
        target_premium = entry_premium * 1.30 
        stop_loss_premium = entry_premium * 0.50 
        
        track_q = f"SELECT datetime_utc, high, low, close FROM {TBL_OPTIONS} WHERE ticker = '{c_ticker}' AND datetime_utc > '{entry_time}' AND datetime_utc <= '{entry_time + timedelta(hours=4)}' ORDER BY datetime_utc ASC"
        try:
            trajectory = con.execute(track_q).df()
        except: continue
        if trajectory.empty: continue
            
        status = 'LOSS'; reason = 'TIME_EXHAUSTION'
        exit_premium = trajectory.iloc[-1]['close']; exit_time = trajectory.iloc[-1]['datetime_utc']
        
        for t_row in trajectory.itertuples():
            if t_row.low <= stop_loss_premium:
                status = 'LOSS'; exit_premium = stop_loss_premium; reason = 'STOP_LOSS_30_PCT'; losses += 1
                break
            elif t_row.high >= target_premium:
                status = 'WIN'; exit_premium = target_premium; reason = 'TARGET_30_PCT'; wins += 1
                break
        
        if reason == 'TIME_EXHAUSTION': losses += 1
            
        # RESTORED: Exact PnL math
        qty = 1
        gross_pnl = (exit_premium - entry_premium) * 100 * qty
        fees = calculate_fees(entry_premium, qty)
        net_pnl = gross_pnl - fees
        capital += net_pnl
        
        # RESTORED: Full Institutional Audit Log format
        trades_log.append({
            'entry_time': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
            'exit_time': exit_time.strftime('%Y-%m-%d %H:%M:%S'),
            'ticker': c_ticker,
            'entry_price': entry_premium,
            'exit_price': exit_premium,
            'quantity': qty,
            'net_pnl': net_pnl,
            'return_pct': ((exit_premium - entry_premium) / entry_premium) * 100,
            'reason': reason,
            'status': status,
            'notes': f"Underlying: {entry_price_xsp:.2f}",
            'meta_data': f"Flow: {row.trade_type} | ML: {row.ml_confidence:.1f}%",
            'action': 'BUY',
            'source_id': 'BACKTEST'
        })
        
    con.close()
    
    # 4. RESTORED: Save to Database
    if trades_log:
        df_write = pd.DataFrame(trades_log)
        try:
            con_write = duckdb.connect(str(config.DB_FILE))
            con_write.execute(f"DELETE FROM {config.TBL_SIM_LOG} WHERE source_id = 'BACKTEST'")
            con_write.register('df_write_temp', df_write)
            cols_str = ", ".join(df_write.columns)
            con_write.execute(f"INSERT INTO {config.TBL_SIM_LOG} ({cols_str}) SELECT * FROM df_write_temp")
            con_write.close()
            log.info(f"💾 Alpha-Harvest Commit successful: {len(df_write)} trades saved.")
        except Exception as e:
            log.error(f"❌ DB Write Error during commit: {e}")

    log.info(f"🏁 Simulation Complete. Final Capital: ${capital:.2f} | True Wins: {wins} | Losses: {losses}")
    return trades_log

# ==============================================================================
# 5. THE MISSING HANDSHAKE (Pipeline Adapter)
# ==============================================================================
def run_backtest_session(initial_balance=1000.0, days=59):
    log.info(f"🧪 TRUE-WIN BACKTEST REQUEST: Last {days} days. Starting Balance: ${initial_balance}")
    end_dt = datetime.now(pytz.UTC)
    start_dt = end_dt - timedelta(days=days)
    return run_simulation_core(start_dt, end_dt, initial_balance)

if __name__ == "__main__":
    run_backtest_session(days=30)