import dash
from dash import dcc, html, callback, Input, Output, State, no_update, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
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

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def get_last_trading_day():
    """
    Returns today if weekday, or last Friday if weekend.
    """
    today = datetime.now()
    weekday = today.weekday() # Mon=0, Sun=6
    
    if weekday == 5: # Saturday
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')
    elif weekday == 6: # Sunday
        return (today - timedelta(days=2)).strftime('%Y-%m-%d')
    else:
        return today.strftime('%Y-%m-%d')

def snap_timestamp(target_iso, df_chart):
    try:
        target_dt = pd.to_datetime(target_iso)
        if target_dt.tz: target_dt = target_dt.tz_localize(None)
        
        if not pd.api.types.is_datetime64_any_dtype(df_chart['datetime_local']):
             df_chart['dt_search'] = pd.to_datetime(df_chart['datetime_local'])
        else:
             df_chart['dt_search'] = df_chart['datetime_local']
             
        idx = (df_chart['dt_search'] - target_dt).abs().idxmin()
        row = df_chart.iloc[idx]
        return row['datetime_local'], row['close']
    except Exception as e:
        log.error(f"Snap Error: {e}")
        return target_iso, 0

def convert_auditor_to_local(ts_val):
    if isinstance(ts_val, (int, float)): ts_val = pd.to_datetime(ts_val, unit='ms')
    if isinstance(ts_val, str): ts_val = pd.to_datetime(ts_val)
    if ts_val.tz is None: ts_val = ts_val.tz_localize('UTC')
    else: ts_val = ts_val.tz_convert('UTC')
    return ts_val.tz_convert(config.TZ_LOCAL).tz_localize(None).isoformat()

def get_chart_data(date_str):
    if not config.DB_FILE.exists(): return pd.DataFrame()
    df = engine_auditor.fetch_day_data(date_str)
    if df.empty: return pd.DataFrame()
    
    df['dt_obj'] = df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL).dt.tz_localize(None)
    df['datetime_local'] = df['dt_obj'].apply(lambda x: x.isoformat())
    
    if len(df) > 20:
        y = df['close'].values
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        df['reg_line'] = slope * x + intercept
        std = df['close'].std()
        df['upper'] = df['reg_line'] + (2 * std)
        df['lower'] = df['reg_line'] - (2 * std)
        
    return df

def fetch_saved_trades_for_day(date_str):
    if not config.DB_FILE.exists(): return []
    try:
        local_tz = config.TZ_LOCAL
        dt_start_local = local_tz.localize(datetime.strptime(date_str, '%Y-%m-%d'))
        dt_end_local = dt_start_local + timedelta(days=1)
        
        ts_start = dt_start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        ts_end = dt_end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if "optimal_training_manifest" not in tables:
            con.close()
            return []
            
        # Robust Fetch: Load all, filter in Py
        df = con.execute("SELECT * FROM optimal_training_manifest").df()
        con.close()
        
        if df.empty: return []
        
        df['local_dt'] = df['entry_time_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL)
        df['date_key'] = df['local_dt'].dt.strftime('%Y-%m-%d')
        day_trades = df[df['date_key'] == date_str].copy()
        
        if day_trades.empty: return []

        day_trades['entry_iso'] = day_trades['local_dt'].dt.tz_localize(None).apply(lambda x: x.isoformat())
        day_trades['exit_iso'] = day_trades['exit_time_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL).dt.tz_localize(None).apply(lambda x: x.isoformat())
        
        return day_trades.to_dict('records')
    except Exception as e:
        log.error(f"Fetch Saved Error: {e}")
        return []

# ==============================================================================
# LAYOUT
# ==============================================================================
def render():
    default_date = get_last_trading_day()
    
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("OPTIMAL TRUTH LAB", className="magitek-h2"),
                html.P("EXPERT-IN-THE-LOOP TRAINING SYSTEM", className="magitek-note"),
            ], width=8),
            dbc.Col([
                html.Div("VAULT STATUS", className="small text-muted font-monospace text-end"),
                html.Div(id="vault-status-text", className="fw-bold text-success font-monospace text-end")
            ], width=4)
        ], className="mb-3 p-3 card flex-row align-items-center", style={"backgroundColor": "#1a1a2e", "border": "1px solid #444"}),

        # CONTROLS
        dbc.Row([
            dbc.Col([
                html.Label("MISSION DATE", className="small text-muted font-monospace"),
                html.Div([
                    dcc.DatePickerSingle(
                        id='lab-date-picker',
                        min_date_allowed=datetime(2023, 1, 1),
                        max_date_allowed=datetime.now() + timedelta(days=1),
                        initial_visible_month=datetime.strptime(default_date, '%Y-%m-%d'),
                        date=default_date, # Uses smart default
                        display_format='YYYY-MM-DD',
                        style={"backgroundColor": "#0a0f1e", "color": "white", "border": "none"}
                    )
                ], className="mb-2"),
                dbc.Button("LOAD SESSION", id="btn-load-lab", color="primary", className="w-100 font-monospace"),
            ], width=2),
            
            # OPTIMAL (AUDITOR)
            dbc.Col([
                html.Label("AUDITOR SUGGESTION (MATH)", className="small text-muted font-monospace"),
                dbc.ButtonGroup([
                    dbc.Button("OPTIMAL CALL", id="btn-show-call", color="info", outline=True, className="font-monospace"),
                    dbc.Button("OPTIMAL PUT", id="btn-show-put", color="warning", outline=True, className="font-monospace"),
                ], className="w-100 mb-2"),
                html.Div(id="auditor-readout", className="small text-info font-monospace")
            ], width=4),

            # MANUAL (HUMAN)
            dbc.Col([
                html.Label("MANUAL OVERRIDE (HUMAN)", className="small text-muted font-monospace"),
                dbc.ButtonGroup([
                    dbc.Button("MANUAL CALL", id="btn-manual-call", color="success", className="font-monospace"),
                    dbc.Button("MANUAL PUT", id="btn-manual-put", color="danger", className="font-monospace"),
                ], className="w-100 mb-2"),
                dbc.ButtonGroup([
                    dbc.Button("CLEAR", id="btn-clear-sel", color="secondary", size="sm", className="font-monospace"),
                    dbc.Button("COMMIT TO VAULT", id="btn-commit", color="warning", className="font-monospace fw-bold"),
                ], className="w-100")
            ], width=3),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("FORENSIC SNAPSHOT", className="py-1 px-2 font-monospace small bg-black text-muted"),
                    dbc.CardBody(id="forensic-panel", className="p-2 font-monospace small text-white")
                ], style={"backgroundColor": "#0a0f1e", "border": "1px solid #444"})
            ], width=3)
        ], className="mb-3"),

        # CHART
        dbc.Row([
            dbc.Col([dcc.Graph(id='lab-chart', style={'height': '700px'}, config={'displayModeBar': True, 'scrollZoom': True})], width=12)
        ]),

        # STORES
        dcc.Store(id='lab-data-store'),
        dcc.Store(id='selection-store'),
        dcc.Store(id='auditor-store'),
        dcc.Store(id='manual-mode-store', data='CALL'),
        dcc.Store(id='last-saved-timestamp'), 
        dcc.Interval(id='vault-refresh', interval=5000, n_intervals=0)

    ], fluid=True)

# ==============================================================================
# CALLBACK 1: LOGIC & STATE
# ==============================================================================
@callback(
    [Output('lab-data-store', 'data'),
     Output('auditor-store', 'data'),
     Output('selection-store', 'data'),
     Output('manual-mode-store', 'data'),
     Output('auditor-readout', 'children'),
     Output('btn-manual-call', 'outline'),
     Output('btn-manual-put', 'outline')],
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
    if ctx_id == 'btn-load-lab' or (not json_data and date_str):
        if not date_str: return no_update, no_update, no_update, no_update, "Select Date", True, True
        df = get_chart_data(date_str)
        if not df.empty:
            auditor_data = engine_auditor.find_optimal_trades(df)
            json_data = df.to_dict('records')
            selection = None
            return json_data, auditor_data, selection, manual_mode, f"Loaded {date_str}", True, True
    
    if not json_data:
        return no_update, no_update, no_update, no_update, "No Data", True, True

    readout = no_update
    call_outline, put_outline = True, True
    
    if manual_mode == 'CALL': call_outline = False
    elif manual_mode == 'PUT': put_outline = False

    if ctx_id == 'btn-manual-call':
        manual_mode = 'CALL'
        selection = None
        readout = "Mode: MANUAL CALL"
        call_outline, put_outline = False, True
        
    elif ctx_id == 'btn-manual-put':
        manual_mode = 'PUT'
        selection = None
        readout = "Mode: MANUAL PUT"
        call_outline, put_outline = True, False
        
    elif ctx_id == 'btn-show-call' and auditor_data:
        c = auditor_data['call']
        if c['points'] > 1.0:
            selection = {
                'entry': convert_auditor_to_local(c['entry_ts']),
                'exit': convert_auditor_to_local(c['exit_ts']),
                'type': 'CALL', 'source': 'AUDITOR'
            }
            readout = f"Auditor: Call (+{c['points']:.2f})"
        else: 
            readout = "⚠ Set Manual Override"
            selection = None
            
    elif ctx_id == 'btn-show-put' and auditor_data:
        p = auditor_data['put']
        if p['points'] > 1.0:
            selection = {
                'entry': convert_auditor_to_local(p['entry_ts']),
                'exit': convert_auditor_to_local(p['exit_ts']),
                'type': 'PUT', 'source': 'AUDITOR'
            }
            readout = f"Auditor: Put (+{p['points']:.2f})"
        else: 
            readout = "⚠ Set Manual Override"
            selection = None
            
    elif ctx_id == 'btn-clear-sel':
        selection = None
        readout = "Selection Cleared."
        
    elif ctx_id == 'lab-chart' and click_data:
        df = pd.DataFrame(json_data)
        click_x = click_data['points'][0]['x']
        snap_x, snap_price = snap_timestamp(click_x, df)
        
        if not selection or (selection.get('entry') and selection.get('exit')):
            selection = {'entry': snap_x, 'exit': None, 'type': manual_mode, 'source': 'MANUAL'}
            readout = f"Entry ({manual_mode}): {snap_x}"
        else:
            if snap_x < selection['entry']:
                selection['exit'] = selection['entry']
                selection['entry'] = snap_x
                readout = f"Exit Set (Auto-Swapped)"
            else:
                selection['exit'] = snap_x
                readout = f"Exit Set ({manual_mode}): {snap_x}"

    return json_data, auditor_data, selection, manual_mode, readout, call_outline, put_outline

# ==============================================================================
# CALLBACK 2: RENDERER (THE EYES)
# ==============================================================================
@callback(
    Output('lab-chart', 'figure'),
    [Input('lab-data-store', 'data'),
     Input('selection-store', 'data'),
     Input('last-saved-timestamp', 'data')],
    [State('lab-date-picker', 'date')]
)
def render_chart(json_data, selection, save_ts, date_str):
    fig = go.Figure()
    
    # 1. EMPTY STATE HANDLING
    if not json_data: 
        fig.update_layout(
            template="plotly_dark",
            xaxis={"visible": False}, yaxis={"visible": False},
            annotations=[{
                "text": "NO MARKET DATA FOUND",
                "xref": "paper", "yref": "paper",
                "showarrow": False, "font": {"size": 20, "color": "#555"}
            }]
        )
        return fig
    
    df = pd.DataFrame(json_data)
    if df.empty:
        # Same handling if DF is technically present but has 0 rows
        fig.update_layout(template="plotly_dark", annotations=[{"text": "NO DATA", "showarrow": False, "font": {"size": 20}}])
        return fig

    # 2. Base Chart
    fig.add_trace(go.Candlestick(
        x=df['datetime_local'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name="XSP"
    ))
    if 'reg_line' in df.columns:
        fig.add_trace(go.Scatter(x=df['datetime_local'], y=df['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"))
        fig.add_trace(go.Scatter(x=df['datetime_local'], y=df['upper'], line=dict(color='cyan', width=1), name="+2σ"))
        fig.add_trace(go.Scatter(x=df['datetime_local'], y=df['lower'], line=dict(color='cyan', width=1), name="-2σ"))

    # 3. Saved Trades
    if date_str:
        saved_trades = fetch_saved_trades_for_day(date_str)
        for t in saved_trades:
            color = "#00ff41" if "CALL" in t['trade_type'].upper() else "#ff5555"
            opacity = 1.0 if "MANUAL" in t['source'] else 0.5
            fig.add_vline(x=t['entry_iso'], line_color=color, line_width=2, line_dash="solid", opacity=opacity)
            fig.add_annotation(x=t['entry_iso'], y=0.02, yref="paper", text="SAVED", showarrow=False, font=dict(color=color, size=10), bgcolor="rgba(0,0,0,0.5)")
            fig.add_vline(x=t['exit_iso'], line_color=color, line_width=2, line_dash="solid", opacity=opacity)

    # 4. Active Ghost
    if selection and selection.get('entry'):
        active_color = "#00ff41" if "CALL" in selection['type'].upper() else "#ff5555"
        fig.add_vline(x=selection['entry'], line_color=active_color, line_width=2, line_dash="dash")
        fig.add_annotation(x=selection['entry'], y=1.02, yref="paper", text=f"{selection['type']}", showarrow=False, font=dict(color=active_color, size=12))
        if selection.get('exit'):
            fig.add_vline(x=selection['exit'], line_color=active_color, line_width=2, line_dash="dash")

    # 5. ZOOM LOCK (uirevision)
    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False, 
        height=700,
        uirevision='constant' # <--- PREVENTS AUTO-ZOOM OUT ON UPDATE
    )
    return fig

# ==============================================================================
# CALLBACK 3: SAVE SYSTEM
# ==============================================================================
@callback(
    [Output('forensic-panel', 'children'),
     Output('vault-status-text', 'children'),
     Output('last-saved-timestamp', 'data')],
    [Input('btn-commit', 'n_clicks'),
     Input('selection-store', 'data'),
     Input('vault-refresh', 'n_intervals')],
    [State('lab-data-store', 'data')]
)
def manage_vault(commit_n, selection, n, json_data):
    ctx_id = ctx.triggered_id
    save_ts = no_update
    
    count = 0
    try:
        df_v = manage_training_ledger.fetch_training_set()
        count = len(df_v)
    except: pass
    status_text = f"Records: {count}"

    panel = "Select a trade to analyze."
    
    if selection and selection.get('entry') and json_data:
        try:
            df_chart = pd.DataFrame(json_data)
            entry_row = df_chart[df_chart['datetime_local'] == selection['entry']].iloc[0]
            utc_str = entry_row['datetime_utc']
            dt_utc = pd.to_datetime(utc_str)
            if dt_utc.tz is None: dt_utc = dt_utc.tz_localize('UTC')

            snap = forensic_snapshotter.capture_market_state(dt_utc)
            
            if snap and snap['valid']:
                panel = [
                    html.Div(f"Type: {selection.get('type')}", className="fw-bold mb-2"),
                    html.Div(f"VIX RSI: {snap.get('vix_rsi', 0):.1f}", className="mb-1"),
                    html.Div(f"Slope: {snap.get('trend_slope', 0):.4f}", className="mb-1 text-warning"),
                    html.Div(f"Source: {selection.get('source', 'MANUAL')}", className="mt-2 text-muted small")
                ]
                
                if ctx_id == 'btn-commit':
                    exit_px = entry_row['close']
                    exit_utc = dt_utc
                    
                    if selection.get('exit'):
                        exit_row = df_chart[df_chart['datetime_local'] == selection['exit']].iloc[0]
                        exit_px = exit_row['close']
                        exit_utc_str = exit_row['datetime_utc']
                        exit_utc = pd.to_datetime(exit_utc_str)
                        if exit_utc.tz is None: exit_utc = exit_utc.tz_localize('UTC')
                        
                    points = abs(exit_px - entry_row['close'])
                    
                    payload = {
                        'entry_ts': dt_utc, 'exit_ts': exit_utc,
                        'type': selection.get('type', 'MANUAL'),
                        'entry_px': entry_row['close'], 'exit_px': exit_px,
                        'points': points
                    }
                    manage_training_ledger.save_profile(payload, snap, source=selection['source'])
                    
                    panel.append(html.Div(f"✅ SAVED (+{points:.2f} pts)", className="text-success fw-bold mt-2"))
                    save_ts = datetime.now().isoformat()

        except Exception as e:
            panel = f"Error: {e}"

    return panel, status_text, save_ts

if __name__ == '__main__':
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
    app.layout = render()
    app.run_server(debug=True, port=8050)