import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import duckdb
from datetime import datetime, time, timedelta
import pytz
import pathlib
import sys
import numpy as np

# ==============================================================================
# 1. PATH & CONFIG SETUP
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ⚡ ENSURE CORRECT TABLE TARGET
TBL_MANIFEST = "trade_manifest" 

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
def to_wall_clock(series):
    if series.empty: return series
    if series.dt.tz is None:
        series = series.dt.tz_localize('UTC')
    else:
        series = series.dt.tz_convert('UTC')
    series = series.dt.tz_convert(config.TZ_LOCAL)
    return series.dt.tz_localize(None)

def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df = df.copy()
    df['x'] = np.arange(len(df))
    slope, intercept = np.polyfit(df['x'], df['close'], 1)
    df['reg_line'] = slope * df['x'] + intercept
    std = df['close'].std()
    df['upper_band'] = df['reg_line'] + (2 * std)
    df['lower_band'] = df['reg_line'] - (2 * std)
    return df

# ==============================================================================
# 3. DATA INGESTION (ROBUST "WIDE NET" LOGIC)
# ==============================================================================
def fetch_unique_dates(trade_type_filter='call'):
    try:
        if not config.DB_FILE.exists(): return []
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Get All Trading Days
        q_dates = f"SELECT DISTINCT CAST(datetime_utc AS DATE) as date FROM {config.TBL_INDICES} ORDER BY date DESC"
        df_dates = con.execute(q_dates).df()
        
        if df_dates.empty: 
            con.close(); return []

        df_dates['date_str'] = pd.to_datetime(df_dates['date']).dt.strftime('%Y-%m-%d')

        t_filter = trade_type_filter.upper()
        try:
            # 2. Get Signal Counts
            q_sigs = f"SELECT date, COUNT(*) as cnt FROM {TBL_MANIFEST} WHERE trade_type = '{t_filter}' GROUP BY date"
            df_sigs = con.execute(q_sigs).df()
            
            if not df_sigs.empty:
                df_sigs['date_str'] = pd.to_datetime(df_sigs['date']).dt.strftime('%Y-%m-%d')
                
                # 3. Merge
                df = pd.merge(df_dates, df_sigs, on='date_str', how='left')
                df['cnt'] = df['cnt'].fillna(0).astype(int)
            else:
                df = df_dates
                df['cnt'] = 0
        except:
            df = df_dates
            df['cnt'] = 0

        con.close()
        
        options = []
        for _, row in df.iterrows():
            d_str = row['date_str']
            count = row['cnt']
            label = f"🟢 {d_str} ({count} Signals)" if count > 0 else f"{d_str}"
            options.append({'label': label, 'value': d_str})
            
        return options
    except Exception as e: 
        print(f"Date Fetch Error: {e}")
        return []

def scout_day_performance(date_str, trade_type_filter='call'):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        t_type = trade_type_filter.upper()
        
        query = f"""
            SELECT entry_timestamp_utc, signal_type, xsp_price, meta_data 
            FROM {TBL_MANIFEST}
            WHERE trade_type = '{t_type}' 
            AND date = '{date_str}'
            ORDER BY entry_timestamp_utc ASC
        """
        signals = con.execute(query).df()
        con.close()
        
        options_list = []
        
        # ALWAYS Create Manual Entry Point (09:30:00 EST)
        dt_ny = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=30)
        dt_ny = config.TZ_NY.localize(dt_ny)
        manual_ts = int(dt_ny.timestamp() * 1000)
        
        options_list.append({'label': '🔍 MANUAL INSPECTION (09:30 EST)', 'value': manual_ts})

        best_ts = manual_ts
        if not signals.empty:
            for i, row in signals.iterrows():
                ts = row['entry_timestamp_utc']
                entry_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
                time_str = entry_dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
                
                clean_meta = str(row['meta_data']).replace('VIX_FRACTAL_LONG', '').replace('VIX_FRACTAL_SHORT', '').strip()
                if "|" in clean_meta: clean_meta = clean_meta.split('|')[-1].strip()
                
                label = f"#{i+1} {time_str} | {clean_meta}"
                options_list.append({'label': label, 'value': ts})
                if i == 0: best_ts = ts

        return options_list, best_ts
    except Exception as e:
        print(f"Scout Error: {e}")
        return [], None

def fetch_available_strikes(entry_ts, trade_type):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        res = con.execute(f"SELECT xsp_price, date FROM {TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts}").fetchone()
        
        dt_obj = None
        xsp_price = None

        if res:
            xsp_price, date_val = res
            dt_obj = date_val if isinstance(date_val, (datetime, pd.Timestamp)) else datetime.strptime(str(date_val), '%Y-%m-%d')
        else:
            ts_sec = entry_ts / 1000
            dt_utc = datetime.fromtimestamp(ts_sec, tz=pytz.utc)
            dt_obj = dt_utc.astimezone(config.TZ_NY)
            dt_str_utc = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
            
            # Widen the net for Fallback Price
            q_fallback = f"""
                SELECT close 
                FROM {config.TBL_INDICES} 
                WHERE ticker='XSP' 
                AND datetime_utc <= '{dt_str_utc}' 
                ORDER BY datetime_utc DESC LIMIT 1
            """
            res_fb = con.execute(q_fallback).fetchone()
            if not res_fb:
                con.close(); return [], None
            xsp_price = res_fb[0]

        target_strike = round(float(xsp_price))
        date_fmt = dt_obj.strftime('%y%m%d') if isinstance(dt_obj, datetime) else datetime.strptime(str(dt_obj), '%Y-%m-%d').strftime('%y%m%d')
        opt_code = 'C' if trade_type.upper() == 'CALL' else 'P'
        like_pattern = f"%XSP{date_fmt}{opt_code}%"
        
        tickers = con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS} WHERE ticker LIKE '{like_pattern}'").fetchall()
        con.close()
        
        if not tickers: return [], None
        
        temp_options = []
        atm_ticker = None
        min_dist = float('inf')
        
        for t in tickers:
            ticker = t[0]
            try:
                strike_str = ticker[-8:] 
                strike_val = int(strike_str) / 1000.0
                diff = strike_val - target_strike
                
                if diff == 0: label = f"{strike_val:.0f} (ATM)"
                elif diff > 0: label = f"{strike_val:.0f} (+{int(diff)})"
                else: label = f"{strike_val:.0f} ({int(diff)})"
                
                temp_options.append({'label': label, 'value': ticker, 'strike': strike_val})
                if abs(diff) < min_dist:
                    min_dist = abs(diff); atm_ticker = ticker
            except: continue
            
        temp_options.sort(key=lambda x: x['strike'])
        return [{'label': x['label'], 'value': x['value']} for x in temp_options], atm_ticker

    except Exception as e:
        print(f"Strike Fetch Error: {e}")
        return [], None

def fetch_trade_performance(entry_ts_ms, ticker, sim_stop_pct=20):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_OPTIONS not in tables: con.close(); return None, {}

        # WIDE NET PROTOCOL
        entry_dt_utc = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).replace(tzinfo=None)
        
        # Robust Window: FULL DAY + Buffer
        s_str = entry_dt_utc.strftime('%Y-%m-%d 00:00:00')
        e_str = (entry_dt_utc + timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')
        
        query = f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC"
        df = con.execute(query).df()
        con.close()

        if df.empty: return None, {}

        temp = df.copy()
        temp['datetime_utc'] = pd.to_datetime(temp['datetime_utc'])
        if temp['datetime_utc'].dt.tz is not None:
             temp['datetime_utc'] = temp['datetime_utc'].dt.tz_convert(None)
        
        idx = temp['datetime_utc'].sub(entry_dt_utc).abs().idxmin()
        
        sim_slice = df.loc[idx:].copy()
        entry_price = max(df.loc[idx, 'open'], 0.01)

        sim_slice['pnl_pct'] = ((sim_slice['open'] - entry_price) / entry_price) * 100
        stop_mult = 1.0 - (sim_stop_pct / 100.0)
        sim_slice['rolling_max'] = sim_slice['high'].cummax()
        sim_slice['stop_level'] = sim_slice['rolling_max'] * stop_mult
        
        stop_hits = sim_slice[sim_slice['low'] < sim_slice['stop_level']]
        sim_slice['sim_pnl_pct'] = sim_slice['pnl_pct']
        
        sim_exit_pct = sim_slice.iloc[-1]['pnl_pct'] if not sim_slice.empty else 0
        if not stop_hits.empty:
            first_stop_idx = stop_hits.index[0]
            sim_exit_pct = sim_slice.loc[first_stop_idx, 'pnl_pct']
            sim_slice.loc[first_stop_idx:, 'sim_pnl_pct'] = sim_exit_pct

        df['sim_pnl_pct'] = np.nan
        df.loc[idx:, 'sim_pnl_pct'] = sim_slice['sim_pnl_pct']
        
        stats = {
            "entry": entry_price,
            "max_price": sim_slice['high'].max() if not sim_slice.empty else 0,
            "max_gain": ((sim_slice['high'].max() - entry_price) / entry_price) * 100 if not sim_slice.empty and entry_price > 0 else 0,
            "sim_exit": sim_exit_pct
        }
            
        df['datetime_local'] = to_wall_clock(df['datetime_utc'])
        return df, stats
    except Exception as e: return None, {}

def fetch_executions(entry_ts_ms, root):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if 'active_rh_log' not in tables:
             con.close(); return pd.DataFrame()
             
        sig_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc)
        s_start = (sig_dt - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
        s_end = (sig_dt + timedelta(minutes=120)).strftime('%Y-%m-%d %H:%M:%S')
        
        q = f"""
            SELECT entry_time_utc, avg_price, action, status 
            FROM active_rh_log 
            WHERE status = 'FILLED' 
            AND root = '{root}'
            AND entry_time_utc >= '{s_start}' 
            AND entry_time_utc <= '{s_end}'
        """
        fills = con.execute(q).df()
        con.close()
        
        if not fills.empty:
             fills['datetime_utc'] = pd.to_datetime(fills['entry_time_utc'])
             fills['datetime_local'] = to_wall_clock(fills['datetime_utc'])
             
        return fills
    except: return pd.DataFrame()

def fetch_indicators(entry_ts_ms):
    """
    🔥 ROBUST FIX: Fetches the entire day (Wide Net) and filters in Python.
    This prevents 'NO DATA' caused by strict SQL timezone mismatches.
    """
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        entry_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        day_date = entry_dt.date()
        
        # ⚡ FETCH WIDE (Whole 48h Window to catch UTC offsets)
        s_str = day_date.strftime('%Y-%m-%d 00:00:00')
        e_str_safe = (day_date + timedelta(days=2)).strftime('%Y-%m-%d 00:00:00')

        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_INDICES not in tables:
             con.close(); return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # FETCH XSP / VIX (No strict time filter in SQL)
        q_idx = f"""
            SELECT datetime_utc, ticker, open, high, low, close 
            FROM {config.TBL_INDICES} 
            WHERE datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str_safe}' 
            ORDER BY datetime_utc ASC
        """
        df_idx = con.execute(q_idx).df()
        
        # FETCH ES (FUTURES)
        tbl_fut = getattr(config, 'TBL_FUTURES', 'futures_1m')
        df_fut = pd.DataFrame()
        if tbl_fut in tables:
             try: 
                 df_fut = con.execute(f"SELECT datetime_utc, ticker, close FROM {tbl_fut} WHERE (ticker LIKE 'ES%' OR ticker = '/ES') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str_safe}' ORDER BY datetime_utc ASC").df()
             except: pass
        con.close()
        
        xsp, vix, es = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        if not df_idx.empty:
            # NORMALIZE TIMESTAMPS IN PYTHON
            df_idx['datetime_utc'] = pd.to_datetime(df_idx['datetime_utc'])
            if df_idx['datetime_utc'].dt.tz is None:
                df_idx['datetime_utc'] = df_idx['datetime_utc'].dt.tz_localize('UTC')
            
            # FILTER RTH (09:30 - 16:00 NY) MANUALLY
            df_idx['dt_ny'] = df_idx['datetime_utc'].dt.tz_convert(config.TZ_NY)
            day_start_ny = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30)))
            day_end_ny = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0)))
            
            df_idx = df_idx[(df_idx['dt_ny'] >= day_start_ny) & (df_idx['dt_ny'] <= day_end_ny)].copy()
            df_idx['datetime_local'] = to_wall_clock(df_idx['datetime_utc'])

            xsp_mask = df_idx['ticker'].str.contains('XSP', case=False, na=False)
            if xsp_mask.any():
                xsp = df_idx[xsp_mask].copy().set_index('datetime_local')
                xsp = xsp[~xsp.index.duplicated(keep='first')]
                xsp['sma_50'] = xsp['close'].rolling(50).mean()
                xsp = calculate_linreg(xsp)

            vix_mask = df_idx['ticker'].str.contains('VIX', case=False, na=False)
            if vix_mask.any():
                vix = df_idx[vix_mask].copy().set_index('datetime_local')
                vix = vix[~vix.index.duplicated(keep='first')]
                vix['ema12'] = vix['close'].ewm(span=12).mean()
                vix['ema26'] = vix['close'].ewm(span=26).mean()
                vix['macd'] = vix['ema12'] - vix['ema26']
                vix['signal'] = vix['macd'].ewm(span=9).mean()
                vix['hist'] = vix['macd'] - vix['signal']
                delta = vix['close'].diff()
                rs = delta.clip(lower=0).ewm(com=13).mean() / (-1 * delta.clip(upper=0)).ewm(com=13).mean()
                vix['rsi'] = 100 - (100 / (1 + rs))

        if not df_fut.empty:
            df_fut['datetime_utc'] = pd.to_datetime(df_fut['datetime_utc'])
            if df_fut['datetime_utc'].dt.tz is None:
                df_fut['datetime_utc'] = df_fut['datetime_utc'].dt.tz_localize('UTC')
            df_fut['datetime_local'] = to_wall_clock(df_fut['datetime_utc'])
            df_fut['scaled_close'] = df_fut['close'] / 10.0 
            es = df_fut.set_index('datetime_local')

        return xsp, vix, es
    except Exception as e: 
        print(f"Fetch Indicators Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
def render():
    INPUT_STYLE = {'color': '#000000', 'backgroundColor': '#ffffff', 'fontFamily': 'monospace', 'border': '1px solid #ccc'}
    
    return dbc.Container([
        # --- HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("CHART SCANNER", className="fw-bold text-white mb-0"),
                html.P("FORENSIC CHART ANALYSIS | SIMULATION | RTH ONLY", className="text-muted small fw-bold mb-0"),
                html.Div([
                    html.Span("PROTOCOL: ", className="fw-bold text-muted small me-2 font-monospace"),
                    dbc.RadioItems(
                        id='chart-mode-select',
                        options=[{'label': 'CALLS', 'value': 'call'}, {'label': 'PUTS', 'value': 'put'}],
                        value='call', inline=True,
                        label_class_name="text-white font-monospace small me-2"
                    )
                ], className="mt-2")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("FILTER: RTH (09:30-16:00)", className="text-end text-warning font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # --- CONTROL DECK ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("1. TARGETING", className="fw-bold small font-monospace", style={"backgroundColor": "#1e293b", "color": "white"}),
                    dbc.CardBody([
                        html.Label("Mission Date", className="small text-muted fw-bold font-monospace"), 
                        dbc.Select(id='chart-date-dropdown', style=INPUT_STYLE, className="mb-2"),
                        html.Label("Signal ID (Select 'MANUAL' for Free Flight)", className="small text-muted fw-bold font-monospace"), 
                        dbc.Select(id='chart-signal-dropdown', style=INPUT_STYLE, className="mb-2"),
                        html.Label("Strike Selection", className="small text-muted fw-bold font-monospace"),
                        dbc.Select(id='chart-strike-dropdown', style=INPUT_STYLE)
                    ], style={"backgroundColor": "#0f172a", "border": "1px solid #334155"})
                ], className="h-100 shadow-sm")
            ], width=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("2. COMBAT REPORT", className="fw-bold small font-monospace", style={"backgroundColor": "#1e293b", "color": "white"}),
                    dbc.CardBody(id='signal-report-card', className="d-flex align-items-center justify-content-center h-100", style={"backgroundColor": "#0f172a", "border": "1px solid #334155"})
                ], className="h-100 shadow-sm")
            ], width=4),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("3. WHAT-IF SIMULATOR", className="fw-bold small font-monospace", style={"backgroundColor": "#1e293b", "color": "white"}),
                    dbc.CardBody([
                        html.Label("Simulated Trailing Stop %", className="small text-muted fw-bold font-monospace"),
                        dcc.Slider(min=5, max=50, step=5, value=20, marks={5:'5%', 20:'20%', 50:'50%'}, id='stop-loss-slider'),
                        html.Div(id='sim-feedback', className="text-end small text-white mt-2 font-monospace")
                    ], style={"backgroundColor": "#0f172a", "border": "1px solid #334155"})
                ], className="h-100 shadow-sm")
            ], width=4)
        ], className="mb-3"),

        # --- CHART STACK ---
        dbc.Row([dbc.Col([dcc.Graph(id='chart-main-display', style={'height': '900px'}, config={'displayModeBar': True, 'scrollZoom': False})], width=12)])
    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================
@callback(
    [Output('chart-date-dropdown', 'options'), Output('chart-date-dropdown', 'value')],
    Input('chart-mode-select', 'value')
)
def update_date_dropdown(mode):
    options = fetch_unique_dates(mode)
    return options, options[0]['value'] if options else None

@callback(
    [Output('chart-signal-dropdown', 'options'), Output('chart-signal-dropdown', 'value')],
    [Input('chart-date-dropdown', 'value'), Input('chart-mode-select', 'value')]
)
def update_signal_dropdown(date_str, mode):
    if not date_str: return [], None
    options, best_val = scout_day_performance(date_str, mode)
    return options, best_val

@callback(
    [Output('chart-strike-dropdown', 'options'), Output('chart-strike-dropdown', 'value')],
    [Input('chart-signal-dropdown', 'value')],
    [State('chart-mode-select', 'value')]
)
def update_strike_options(entry_ts, mode):
    if not entry_ts: return [], None
    options, atm_ticker = fetch_available_strikes(entry_ts, mode)
    return options, atm_ticker

@callback(
    [Output('chart-main-display', 'figure'), 
     Output('signal-report-card', 'children'),
     Output('sim-feedback', 'children')],
    [Input('chart-signal-dropdown', 'value'), 
     Input('chart-strike-dropdown', 'value'),
     Input('stop-loss-slider', 'value')],
    [State('chart-mode-select', 'value')]
)
def update_chart(entry_ts, ticker, stop_pct, mode):
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)') 
    if not entry_ts or not ticker: return empty_fig, "NO DATA", ""

    if not config.DB_FILE.exists(): return empty_fig, "DB MISSING", ""
    
    # FETCH DATA
    opt_df, stats = fetch_trade_performance(entry_ts, ticker, stop_pct)
    xsp_df, vix_df, es_df = fetch_indicators(entry_ts)
    fills = fetch_executions(entry_ts, 'XSP')

    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.35, 0.25, 0.2, 0.2], 
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("CONTEXT: XSP + LinReg + ES(x0.1)", f"FORENSICS: {ticker}", "VIX FRACTAL FLOW", "VIX RSI")
    )

    has_data = False
    
    # CALCULATE RTH WINDOW
    entry_wc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc).astimezone(config.TZ_LOCAL).replace(tzinfo=None)
    day_start = entry_wc.replace(hour=6, minute=30, second=0)
    day_end = entry_wc.replace(hour=13, minute=0, second=0)

    # 1. XSP (Row 1)
    if not xsp_df.empty:
        orb_start = day_start
        orb_end = day_start + timedelta(minutes=30)
        orb_df = xsp_df[(xsp_df.index >= orb_start) & (xsp_df.index <= orb_end)]
        orb_h = orb_df['high'].max() if not orb_df.empty else None
        orb_l = orb_df['low'].min() if not orb_df.empty else None

        fig.add_trace(go.Candlestick(
            x=xsp_df.index, open=xsp_df['open'], high=xsp_df['high'], low=xsp_df['low'], close=xsp_df['close'], name="XSP",
            increasing_line_color='#00bc8c', decreasing_line_color='#e74c3c'
        ), row=1, col=1)
        
        if 'reg_line' in xsp_df.columns:
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp_df.index, y=xsp_df['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)

        if orb_h and orb_l:
            fig.add_hline(y=orb_h, line_dash="solid", line_color="green", opacity=0.5, row=1, col=1)
            fig.add_hline(y=orb_l, line_dash="solid", line_color="red", opacity=0.5, row=1, col=1)

        has_data = True
    else:
        fig.add_annotation(text="NO XSP DATA", row=1, col=1, font=dict(color="red"))

    if not es_df.empty:
        fig.add_trace(go.Scatter(x=es_df.index, y=es_df['scaled_close'], name="/ES (x0.1)", line=dict(color='#00d2ff', width=1, dash='dot')), row=1, col=1)

    # 2. OPTIONS (Row 2)
    if opt_df is not None and not opt_df.empty:
        has_data = True
        fig.add_trace(go.Candlestick(
            x=opt_df['datetime_local'],
            open=opt_df['open'], high=opt_df['high'],
            low=opt_df['low'], close=opt_df['close'],
            name="Option",
            increasing_line_color='#00bc8c', decreasing_line_color='#e74c3c'
        ), row=2, col=1, secondary_y=False)
        
        fig.add_trace(go.Scatter(x=opt_df['datetime_local'], y=opt_df['sim_pnl_pct'], name="Sim Stop", line=dict(color='yellow', width=2, dash='dot')), row=2, col=1, secondary_y=True)
        
        if not fills.empty:
             fig.add_trace(go.Scatter(x=fills['datetime_local'], y=fills['avg_price'], mode='markers', name="FILL", marker=dict(symbol='circle', size=12, color='cyan', line=dict(width=2, color='white'))), row=2, col=1, secondary_y=True)

    # 3. VIX (Row 3)
    if not vix_df.empty:
        fig.add_trace(go.Bar(x=vix_df.index, y=vix_df['hist'], name="Hist", marker_color='rgba(255, 255, 255, 0.4)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['macd'], name="MACD", line=dict(color='#f1c40f', width=1.5)), row=3, col=1)
    else:
        fig.add_annotation(text="NO VIX DATA", row=3, col=1, font=dict(color="red"))

    # 4. RSI (Row 4)
    if not vix_df.empty:
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['rsi'], name="RSI", line=dict(color='#aa00ff', width=1.5)), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#e74c3c", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)
    else:
        fig.add_annotation(text="NO RSI DATA", row=4, col=1, font=dict(color="red"))

    if not has_data:
        empty_fig.add_annotation(text="DATA UNAVAILABLE", showarrow=False, font=dict(size=20, color="red"))
        return empty_fig, "NO DATA", ""
        
    fig.update_xaxes(matches='x', range=[day_start, day_end], type='date', fixedrange=True, showgrid=True, gridcolor='#333')
    fig.update_yaxes(fixedrange=True, showgrid=True, gridcolor='#333')
    
    fig.update_layout(
        uirevision=entry_ts,
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=30, b=40), 
        showlegend=False, 
        height=900,
        hovermode="x unified",
        font=dict(family="monospace", size=12, color="#f3f5f9"),
        hoverlabel=dict(bgcolor="#1e1e1e", font=dict(color="#f3f5f9", family="monospace"))
    )
    
    fig.add_vline(x=entry_wc, line_width=1, line_dash="dash", line_color="lime", row=1, col=1)
    
    entry = stats.get('entry', 0)
    max_gain = stats.get('max_gain', 0)
    sim_exit = stats.get('sim_exit', 0)
    sim_color = 'text-success' if sim_exit > 0 else 'text-danger'
    
    report_html = html.Div([
        dbc.Row([
            dbc.Col([html.Div("ENTRY PRICE", className="small text-muted"), html.Div(f"${entry:.2f}", className="fw-bold text-white")], width=4),
            dbc.Col([html.Div("MAX POTENTIAL", className="small text-muted"), html.Div(f"+{max_gain:.1f}%", className="fw-bold text-success")], width=4),
            dbc.Col([html.Div("SIM RESULT", className="small text-muted"), html.Div(f"+{sim_exit:.1f}%", className=f"fw-bold {sim_color}")], width=4),
        ])
    ], className="text-center font-monospace")

    sim_msg = f"Simulating {stop_pct}% Trailing Stop"
    return fig, report_html, sim_msg