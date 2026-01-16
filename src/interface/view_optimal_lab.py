import dash
from dash import dcc, html, callback, Input, Output, State, no_update, ctx, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import pytz
import sys
import duckdb
from pathlib import Path

# ==============================================================================
# SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from ops import engine_auditor, forensic_snapshotter
from src.data import manage_training_ledger

log = get_logger("OptimalLab")

# ⚡ ENFORCE MARKET TIME (Prevent UTC Drift)
TZ_NY = pytz.timezone('America/New_York')

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def get_last_trading_day():
    today = datetime.now()
    weekday = today.weekday()
    if weekday == 5: return (today - timedelta(days=1)).strftime('%Y-%m-%d')
    elif weekday == 6: return (today - timedelta(days=2)).strftime('%Y-%m-%d')
    else: return today.strftime('%Y-%m-%d')

def to_ny_iso(dt_val):
    """Converts ANY timestamp to New York ISO String for Chart Mapping"""
    if isinstance(dt_val, str): dt_val = pd.to_datetime(dt_val)
    if dt_val.tz is None: dt_val = dt_val.tz_localize('UTC') # Assume DB is UTC
    else: dt_val = dt_val.tz_convert('UTC')
    
    # Convert UTC -> NY
    return dt_val.tz_convert(TZ_NY).tz_localize(None).isoformat()

def snap_timestamp(target_iso, df_chart):
    try:
        target_dt = pd.to_datetime(target_iso)
        idx = (pd.to_datetime(df_chart['datetime_local']) - target_dt).abs().idxmin()
        row = df_chart.iloc[idx]
        return row['datetime_local'], row['close']
    except Exception:
        return target_iso, 0

# ------------------------------------------------------------------------------
# CORE DATA ENGINE (SQL BASED for PRECISION)
# ------------------------------------------------------------------------------
def get_chart_data(date_str):
    if not config.DB_FILE.exists(): return pd.DataFrame(), pd.DataFrame()
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. FETCH XSP (Target Asset)
        q_xsp = f"""
            SELECT datetime_utc, open, high, low, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'XSP' 
            AND CAST(datetime_utc AS DATE) = '{date_str}'
            ORDER BY datetime_utc
        """
        df_xsp = con.execute(q_xsp).df()
        
        # 2. FETCH VIX (Context Asset)
        q_vix = f"""
            SELECT datetime_utc, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'VIX' 
            AND CAST(datetime_utc AS DATE) = '{date_str}'
            ORDER BY datetime_utc
        """
        df_vix = con.execute(q_vix).df()
        con.close()
        
        if df_xsp.empty: return pd.DataFrame(), pd.DataFrame()

        # 3. PROCESS & LOCALIZE (XSP)
        # Force UTC -> NY Conversion
        df_xsp['dt_obj'] = df_xsp['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(TZ_NY).dt.tz_localize(None)
        
        # RTH FILTER (09:30 - 16:00 NY TIME)
        target_date = pd.to_datetime(date_str).date()
        df_xsp = df_xsp[
            (df_xsp['dt_obj'].dt.date == target_date) & 
            (df_xsp['dt_obj'].dt.time >= time(9, 30)) & 
            (df_xsp['dt_obj'].dt.time <= time(16, 0))
        ].copy()
        
        if df_xsp.empty: return pd.DataFrame(), pd.DataFrame()
        
        df_xsp['datetime_local'] = df_xsp['dt_obj'].apply(lambda x: x.isoformat())
        
        # Add Regression Stats
        if len(df_xsp) > 20:
            y = df_xsp['close'].values
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            df_xsp['reg_line'] = slope * x + intercept
            std = df_xsp['close'].std()
            df_xsp['upper'] = df_xsp['reg_line'] + (2 * std)
            df_xsp['lower'] = df_xsp['reg_line'] - (2 * std)

        # 4. PROCESS & LOCALIZE (VIX)
        if not df_vix.empty:
            df_vix['dt_obj'] = df_vix['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(TZ_NY).dt.tz_localize(None)
            # RTH Filter VIX
            df_vix = df_vix[
                (df_vix['dt_obj'].dt.date == target_date) & 
                (df_vix['dt_obj'].dt.time >= time(9, 30)) & 
                (df_vix['dt_obj'].dt.time <= time(16, 0))
            ].copy()
            
            # VIX Indicators (MACD, RSI)
            if len(df_vix) > 26:
                close = df_vix['close']
                ema12 = close.ewm(span=12).mean()
                ema26 = close.ewm(span=26).mean()
                df_vix['macd'] = ema12 - ema26
                df_vix['signal'] = df_vix['macd'].ewm(span=9).mean()
                df_vix['hist'] = df_vix['macd'] - df_vix['signal']
                
                delta = close.diff()
                up = delta.clip(lower=0)
                down = -1 * delta.clip(upper=0)
                rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
                df_vix['rsi'] = 100 - (100 / (1 + rs))
            
            df_vix['datetime_local'] = df_vix['dt_obj'].apply(lambda x: x.isoformat())

        return df_xsp, df_vix

    except Exception as e:
        log.error(f"Chart Data Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

def fetch_saved_trades_for_day(date_str):
    """
    Fetches trades and aggressively normalizes UTC -> NY Time.
    """
    if not config.DB_FILE.exists(): return []
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if "optimal_training_manifest" not in tables:
            con.close(); return []
            
        # Fetch all
        df = con.execute("SELECT * FROM optimal_training_manifest").df()
        con.close()
        
        if df.empty: return []
        
        # ⚡ FORCE AWARE CONVERSION (UTC -> NY)
        # utc=True ensures pandas treats input as UTC-aware, avoiding ambiguity
        df['dt_utc'] = pd.to_datetime(df['entry_time_utc'], utc=True)
        
        # Convert to NY and Strip
        df['local_dt'] = df['dt_utc'].dt.tz_convert(TZ_NY)
        df['date_key'] = df['local_dt'].dt.strftime('%Y-%m-%d')
        
        # Filter for Target Day
        day_trades = df[df['date_key'] == date_str].copy()
        if day_trades.empty: return []

        # Create ISO String for Chart (Naive Local)
        day_trades['entry_iso'] = day_trades['local_dt'].dt.tz_localize(None).apply(lambda x: x.isoformat())
        
        # Handle Exit
        mask_exit = day_trades['exit_time_utc'].notna()
        day_trades['exit_iso'] = None
        if mask_exit.any():
            et = pd.to_datetime(day_trades.loc[mask_exit, 'exit_time_utc'], utc=True)
            day_trades.loc[mask_exit, 'exit_iso'] = et.dt.tz_convert(TZ_NY).dt.tz_localize(None).apply(lambda x: x.isoformat())
        
        day_trades['trade_type'] = day_trades['trade_type'].str.upper()
        
        # Formatted Columns for UI Table
        day_trades['UTC Time'] = day_trades['dt_utc'].dt.strftime('%H:%M:%S')
        day_trades['Local Time'] = day_trades['local_dt'].dt.strftime('%H:%M:%S')
        day_trades['Points'] = day_trades['points'].round(2)
        
        return day_trades.to_dict('records')
    except Exception as e:
        log.error(f"Fetch Saved Error: {e}")
        return []

# ==============================================================================
# LAYOUT
# ==============================================================================
def render():
    default_date = get_last_trading_day()
    
    PICKER_STYLE = {
        'backgroundColor': 'white', 
        'color': 'black', 
        'padding': '5px',
        'borderRadius': '4px',
        'border': '1px solid #ccc'
    }

    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("OPTIMAL TRUTH LAB", className="fw-bold text-white mb-0"),
                html.P("MULTI-LAYER FORENSICS & GROUND TRUTH GENERATOR", className="text-muted small fw-bold mb-0"),
            ], width=8),
            dbc.Col([
                html.Div("VAULT STATUS", className="small text-muted font-monospace text-end"),
                html.Div(id="vault-status-text", className="fw-bold text-success font-monospace text-end")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        dbc.Row([
            dbc.Col([
                html.Label("MISSION DATE", className="small text-muted font-monospace fw-bold"),
                html.Div([
                    dcc.DatePickerSingle(
                        id='lab-date-picker',
                        min_date_allowed=datetime(2023, 1, 1),
                        max_date_allowed=datetime.now() + timedelta(days=1),
                        initial_visible_month=datetime.strptime(default_date, '%Y-%m-%d'),
                        date=default_date,
                        display_format='YYYY-MM-DD',
                        style={'border': 'none'},
                        persistence=True,          # PERSISTENCE ENABLED
                        persistence_type='session' # SESSION STORAGE
                    )
                ], className="mb-2", style=PICKER_STYLE),
                dbc.Button("LOAD SESSION", id="btn-load-lab", color="primary", className="w-100 font-monospace fw-bold"),
            ], width=3),
            
            dbc.Col([
                html.Label("AUDITOR SUGGESTION", className="small text-muted font-monospace fw-bold"),
                dbc.ButtonGroup([
                    dbc.Button("OPTIMAL CALL", id="btn-show-call", color="info", outline=True, className="font-monospace"),
                    dbc.Button("OPTIMAL PUT", id="btn-show-put", color="warning", outline=True, className="font-monospace"),
                ], className="w-100 mb-2"),
                html.Div(id="auditor-readout", className="small text-info font-monospace")
            ], width=3),

            dbc.Col([
                html.Label("MANUAL OVERRIDE", className="small text-muted font-monospace fw-bold"),
                dbc.ButtonGroup([
                    dbc.Button("MANUAL CALL", id="btn-manual-call", color="success", outline=True, className="font-monospace fw-bold"),
                    dbc.Button("MANUAL PUT", id="btn-manual-put", color="danger", outline=True, className="font-monospace fw-bold"),
                ], className="w-100 mb-2"),
                dbc.ButtonGroup([
                    dbc.Button("CLEAR", id="btn-clear-sel", color="secondary", size="sm", className="font-monospace"),
                    dbc.Button("COMMIT TO VAULT", id="btn-commit", color="warning", className="font-monospace fw-bold"),
                ], className="w-100")
            ], width=3),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("FORENSIC SNAPSHOT", className="py-1 px-2 font-monospace small bg-black text-muted fw-bold"),
                    dbc.CardBody(id="forensic-panel", className="p-2 font-monospace small text-white")
                ], style={"backgroundColor": "#0f172a", "border": "1px solid #334155"})
            ], width=3)
        ], className="mb-3"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody(
                        # HEIGHT INCREASED TO ACCOMMODATE 4 ROWS
                        dcc.Graph(id='lab-chart', style={'height': '85vh'}, config={'displayModeBar': True, 'scrollZoom': True}),
                        className="p-0"
                    )
                ], className="border-secondary shadow-sm")
            ], width=12)
        ]),

        # DIAGNOSTIC LEDGER (NEW)
        dbc.Row([
            dbc.Col([
                html.H5("SESSION TRADE LEDGER (UTC vs LOCAL DIAGNOSTICS)", className="text-white mt-4 mb-2 small font-monospace"),
                dash_table.DataTable(
                    id='trade-ledger-table',
                    columns=[
                        {'name': 'Type', 'id': 'trade_type'},
                        {'name': 'Source', 'id': 'source'},
                        {'name': 'UTC Time (DB)', 'id': 'UTC Time'},
                        {'name': 'Local Time (Chart)', 'id': 'Local Time'},
                        {'name': 'Points', 'id': 'Points'},
                    ],
                    style_cell={'backgroundColor': '#111', 'color': 'white', 'fontFamily': 'monospace'},
                    style_header={'backgroundColor': '#222', 'fontWeight': 'bold'},
                    page_size=10
                )
            ], width=12, style={'marginBottom': '100px'}) # Added PADDING
        ]),

        dcc.Store(id='lab-data-store', storage_type='session'), # XSP Data (PERSISTED)
        dcc.Store(id='lab-vix-store', storage_type='session'),  # VIX Data (PERSISTED)
        dcc.Store(id='selection-store', storage_type='session'),
        dcc.Store(id='auditor-store', storage_type='session'),
        dcc.Store(id='manual-mode-store', data='CALL', storage_type='session'),
        dcc.Store(id='session-trades-store', data=[], storage_type='session'),
        dcc.Interval(id='vault-refresh', interval=5000, n_intervals=0)

    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# CALLBACK 1: LOAD & INTERACT
# ==============================================================================
@callback(
    [Output('lab-data-store', 'data'),
     Output('lab-vix-store', 'data'),
     Output('auditor-store', 'data'),
     Output('selection-store', 'data'),
     Output('manual-mode-store', 'data'),
     Output('auditor-readout', 'children')],
    [Input('btn-load-lab', 'n_clicks'),
     Input('btn-show-call', 'n_clicks'),
     Input('btn-show-put', 'n_clicks'),
     Input('btn-manual-call', 'n_clicks'),
     Input('btn-manual-put', 'n_clicks'),
     Input('btn-clear-sel', 'n_clicks'),
     Input('lab-chart', 'clickData')],
    [State('lab-date-picker', 'date'),
     State('lab-data-store', 'data'),
     State('auditor-store', 'data'),
     State('selection-store', 'data'),
     State('manual-mode-store', 'data')]
)
def handle_interactions(load_n, show_call, show_put, man_call, man_put, clear_n, click_data,
                        date_str, json_data, auditor_data, selection, manual_mode):
    ctx_id = ctx.triggered_id
    
    # 1. LOAD DATA
    if ctx_id == 'btn-load-lab' or (not json_data and date_str and not ctx_id):
        if not date_str: return no_update, no_update, no_update, no_update, no_update, "Select Date"
        
        df_xsp, df_vix = get_chart_data(date_str)
        
        if df_xsp.empty: return [], [], {}, None, manual_mode, f"No Data: {date_str}"
        
        # Calc Auditor on XSP
        auditor_data = engine_auditor.find_optimal_trades(df_xsp)
        
        json_xsp = df_xsp.to_dict('records')
        json_vix = df_vix.to_dict('records') if not df_vix.empty else []
        selection = None
        
        return json_xsp, json_vix, auditor_data, selection, manual_mode, f"Loaded {date_str}"

    if not json_data: return no_update, no_update, no_update, no_update, no_update, "Data Not Loaded"

    readout = no_update

    # 2. MODE SWITCHING
    if ctx_id == 'btn-manual-call':
        manual_mode = 'CALL'; selection = None; readout = "Mode: MANUAL CALL"
    elif ctx_id == 'btn-manual-put':
        manual_mode = 'PUT'; selection = None; readout = "Mode: MANUAL PUT"
    
    # 3. AUDITOR REVEAL
    elif ctx_id == 'btn-show-call' and auditor_data:
        c = auditor_data.get('call', {})
        if c.get('points', 0) > 1.0:
            selection = {'entry': to_ny_iso(c['entry_ts']), 'exit': to_ny_iso(c['exit_ts']), 'type': 'CALL', 'source': 'AUDITOR'}
            readout = f"Auditor: Call (+{c['points']:.2f})"
        else: readout = "⚠ No Optimal Call"; selection = None
    elif ctx_id == 'btn-show-put' and auditor_data:
        p = auditor_data.get('put', {})
        if p.get('points', 0) > 1.0:
            selection = {'entry': to_ny_iso(p['entry_ts']), 'exit': to_ny_iso(p['exit_ts']), 'type': 'PUT', 'source': 'AUDITOR'}
            readout = f"Auditor: Put (+{p['points']:.2f})"
        else: readout = "⚠ No Optimal Put"; selection = None
        
    # 4. CLEAR
    elif ctx_id == 'btn-clear-sel':
        selection = None; readout = "Cleared."
        
    # 5. CHART CLICK
    elif ctx_id == 'lab-chart' and click_data:
        df = pd.DataFrame(json_data)
        snap_x, _ = snap_timestamp(click_data['points'][0]['x'], df)
        if not selection or (selection.get('entry') and selection.get('exit')):
            selection = {'entry': snap_x, 'exit': None, 'type': manual_mode, 'source': 'MANUAL'}
            readout = f"Entry: {snap_x}"
        else:
            if snap_x < selection['entry']: selection['exit'] = selection['entry']; selection['entry'] = snap_x
            else: selection['exit'] = snap_x
            readout = f"Exit Set: {snap_x}"

    return json_data, no_update, auditor_data, selection, manual_mode, readout

# ==============================================================================
# CALLBACK 2: TRADE MANAGER
# ==============================================================================
@callback(
    [Output('forensic-panel', 'children'),
     Output('vault-status-text', 'children'),
     Output('session-trades-store', 'data'),
     Output('btn-manual-call', 'children'),
     Output('btn-manual-put', 'children'),
     Output('btn-manual-call', 'style'),
     Output('btn-manual-put', 'style'),
     Output('trade-ledger-table', 'data')], # <--- NEW TABLE OUTPUT
    [Input('lab-data-store', 'data'),
     Input('btn-commit', 'n_clicks'),
     Input('selection-store', 'data'),
     Input('vault-refresh', 'n_intervals')],
    [State('session-trades-store', 'data'),
     State('lab-date-picker', 'date')]
)
def manage_trades(json_data, commit_n, selection, n, current_session_trades, date_str):
    ctx_id = ctx.triggered_id
    
    # A. RELOAD FROM DB
    if ctx_id == 'lab-data-store' and date_str:
        db_trades = fetch_saved_trades_for_day(date_str)
        c_cnt = sum(1 for t in db_trades if 'CALL' in str(t.get('trade_type', '')).upper())
        p_cnt = sum(1 for t in db_trades if 'PUT' in str(t.get('trade_type', '')).upper())
        c_txt = f"MANUAL CALL ({c_cnt}) ✔" if c_cnt > 0 else "MANUAL CALL"
        p_txt = f"MANUAL PUT ({p_cnt}) ✔" if p_cnt > 0 else "MANUAL PUT"
        c_style = {'opacity': 1.0} if c_cnt > 0 else {'opacity': 0.7}
        p_style = {'opacity': 1.0} if p_cnt > 0 else {'opacity': 0.7}
        return "Loaded Records.", f"Records: {len(db_trades)}", db_trades, c_txt, p_txt, c_style, p_style, db_trades

    # Defaults
    current_trades = current_session_trades or []
    count = len(current_trades)
    
    c_cnt = sum(1 for t in current_trades if 'CALL' in str(t.get('trade_type', '')).upper())
    p_cnt = sum(1 for t in current_trades if 'PUT' in str(t.get('trade_type', '')).upper())
    c_txt = f"MANUAL CALL ({c_cnt}) ✔" if c_cnt > 0 else "MANUAL CALL"
    p_txt = f"MANUAL PUT ({p_cnt}) ✔" if p_cnt > 0 else "MANUAL PUT"
    c_style = {'opacity': 1.0} if c_cnt > 0 else {'opacity': 0.7}
    p_style = {'opacity': 1.0} if p_cnt > 0 else {'opacity': 0.7}

    if not selection or not selection.get('entry') or not json_data:
        return "Select a trade.", f"Records: {count}", no_update, c_txt, p_txt, c_style, p_style, current_trades

    try:
        df_chart = pd.DataFrame(json_data)
        entry_row = df_chart[df_chart['datetime_local'] == selection['entry']].iloc[0]
        dt_utc = pd.to_datetime(entry_row['datetime_utc'])
        if dt_utc.tz is None: dt_utc = dt_utc.tz_localize('UTC')

        snap = forensic_snapshotter.capture_market_state(dt_utc)
        
        if snap:
            panel = [
                html.Div(f"Type: {selection.get('type')}", className="fw-bold mb-2"),
                html.Div(f"VIX RSI: {snap.get('vix_rsi', 0):.1f}", className="mb-1"),
                html.Div(f"Source: {selection.get('source', 'MANUAL')}", className="mt-2 text-muted small")
            ]
            
            if ctx_id == 'btn-commit':
                exit_px = entry_row['close']
                exit_utc = dt_utc
                exit_iso = selection['entry']

                if selection.get('exit'):
                    exit_row = df_chart[df_chart['datetime_local'] == selection['exit']].iloc[0]
                    exit_px = exit_row['close']
                    exit_utc = pd.to_datetime(exit_row['datetime_utc'])
                    if exit_utc.tz is None: exit_utc = exit_utc.tz_localize('UTC')
                    exit_iso = selection['exit']
                    
                points = abs(exit_px - entry_row['close'])
                
                # Update Session
                new_trade = {
                    'entry_iso': selection['entry'], 'exit_iso': exit_iso,
                    'trade_type': selection.get('type', 'MANUAL'), 'source': selection.get('source', 'MANUAL'),
                    'UTC Time': dt_utc.strftime('%H:%M:%S'),
                    'Local Time': selection['entry'].split('T')[1],
                    'Points': round(points, 2)
                }
                updated_trades = current_trades + [new_trade]
                
                # DB SAVE
                try:
                    payload = {
                        'entry_ts': dt_utc, 'exit_ts': exit_utc,
                        'type': selection.get('type', 'MANUAL'),
                        'entry_px': entry_row['close'], 'exit_px': exit_px,
                        'points': points
                    }
                    manage_training_ledger.save_profile(payload, snap, source=selection['source'])
                    msg = "✅ SAVED (DB)"
                except Exception as e:
                    log.warning(f"DB Fail: {e}")
                    msg = "⚠️ SESSION ONLY"

                # RE-FETCH FROM DB to update table & state (Best Practice)
                # If we rely on session update, we might drift from DB.
                # But to be fast, we append to session.
                # Better: Re-fetch entire day from DB to confirm save.
                updated_trades = fetch_saved_trades_for_day(date_str)
                new_count = len(updated_trades)

                panel.append(html.Div(f"{msg} +{points:.2f} pts", className="fw-bold mt-2 text-warning"))
                
                # Immediate Button Update (re-calc on new list)
                c_cnt = sum(1 for t in updated_trades if 'CALL' in str(t.get('trade_type', '')).upper())
                p_cnt = sum(1 for t in updated_trades if 'PUT' in str(t.get('trade_type', '')).upper())
                c_txt = f"MANUAL CALL ({c_cnt}) ✔" if c_cnt > 0 else "MANUAL CALL"
                p_txt = f"MANUAL PUT ({p_cnt}) ✔" if p_cnt > 0 else "MANUAL PUT"
                
                return panel, f"Records: {new_count}", updated_trades, c_txt, p_txt, c_style, p_style, updated_trades
            
            return panel, f"Records: {count}", no_update, c_txt, p_txt, c_style, p_style, current_trades

    except Exception as e:
        return f"Error: {e}", f"Records: {count}", no_update, c_txt, p_txt, c_style, p_style, current_trades

    return "Select trade.", f"Records: {count}", no_update, c_txt, p_txt, c_style, p_style, current_trades

# ==============================================================================
# CALLBACK 3: MULTI-LAYER FORENSICS RENDERER
# ==============================================================================
@callback(
    Output('lab-chart', 'figure'),
    [Input('lab-data-store', 'data'),
     Input('lab-vix-store', 'data'),
     Input('selection-store', 'data'),
     Input('session-trades-store', 'data')],
    [State('lab-date-picker', 'date')]
)
def render_forensics(json_xsp, json_vix, selection, session_trades, date_str):
    if not json_xsp: 
        return go.Figure(layout=dict(template="plotly_dark", annotations=[{"text": "NO DATA", "showarrow": False}]))
    
    df_xsp = pd.DataFrame(json_xsp)
    df_vix = pd.DataFrame(json_vix) if json_vix else pd.DataFrame()
    
    # SETUP 4-ROW SUBPLOTS
    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.02, 
        row_heights=[0.45, 0.15, 0.20, 0.20],
        subplot_titles=("XSP Price Action", "Option Flow (Placeholder)", "VIX Momentum (MACD)", "VIX Reversion (RSI)")
    )

    # ROW 1: XSP
    fig.add_trace(go.Candlestick(
        x=df_xsp['datetime_local'], open=df_xsp['open'], high=df_xsp['high'], low=df_xsp['low'], close=df_xsp['close'], 
        name="XSP"
    ), row=1, col=1)
    
    if 'reg_line' in df_xsp.columns:
        fig.add_trace(go.Scatter(x=df_xsp['datetime_local'], y=df_xsp['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_xsp['datetime_local'], y=df_xsp['upper'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_xsp['datetime_local'], y=df_xsp['lower'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)

    # ROW 2: PLACEHOLDER (Option Flow)
    fig.add_trace(go.Scatter(x=[], y=[], name="Option Data"), row=2, col=1)

    # ROW 3 & 4: VIX
    if not df_vix.empty and 'hist' in df_vix.columns:
        # Row 3: MACD
        colors = ['#ff5555' if v > 0 else '#00bc8c' for v in df_vix['hist']]
        fig.add_trace(go.Bar(x=df_vix['datetime_local'], y=df_vix['hist'], marker_color=colors, name="VIX Hist"), row=3, col=1)
        fig.add_trace(go.Scatter(x=df_vix['datetime_local'], y=df_vix['macd'], line=dict(color='#f1c40f', width=1), name="VIX MACD"), row=3, col=1)
        
        # Row 4: RSI
        fig.add_trace(go.Scatter(x=df_vix['datetime_local'], y=df_vix['rsi'], line=dict(color='#a855f7', width=1.5), name="VIX RSI"), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ff5555", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    # OVERLAY TRADES (On Row 1)
    if session_trades:
        for t in session_trades:
            color = "#00ff41" if "CALL" in str(t.get('trade_type', '')).upper() else "#ff5555"
            opacity = 1.0 if "MANUAL" in str(t.get('source', '')).upper() else 0.5
            
            if 'entry_iso' in t:
                fig.add_vline(x=t['entry_iso'], line_color=color, line_width=2, line_dash="solid", opacity=opacity, row=1, col=1)
            if 'exit_iso' in t and t['exit_iso']:
                fig.add_vline(x=t['exit_iso'], line_color=color, line_width=2, line_dash="solid", opacity=opacity, row=1, col=1)

    if selection and selection.get('entry'):
        active_color = "#00ff41" if "CALL" in selection['type'].upper() else "#ff5555"
        fig.add_vline(x=selection['entry'], line_color=active_color, line_width=2, line_dash="dash", row=1, col=1)
        if selection.get('exit'):
            fig.add_vline(x=selection['exit'], line_color=active_color, line_width=2, line_dash="dash", row=1, col=1)

    # FINAL LAYOUT
    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=30, b=10), 
        height=900,
        showlegend=False,
        hovermode="x unified",
        xaxis=dict(fixedrange=True, type='date'), # RTH Lock
        xaxis4=dict(title="Time (Local)", fixedrange=True, type='date'),
        uirevision=date_str
    )
    
    return fig