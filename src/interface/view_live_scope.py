import dash
from dash import dcc, html, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import json
import sys
import subprocess
from datetime import datetime, time, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 0. SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
SNAPSHOT_FILE = ROOT_DIR / "data" / "live_snapshot.json"
MACRO_FILE = ROOT_DIR / "data" / "macro_sentiment.json"

# ==============================================================================
# 1. TEMPORAL INTELLIGENCE
# ==============================================================================
HOLIDAYS = {
    "2025-01-01": "New Year's Day", "2025-01-20": "MLK Jr. Day",
    "2025-02-17": "Presidents Day", "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence Day", "2025-09-01": "Labor Day",
    "2025-10-13": "Columbus Day",   "2025-11-11": "Veterans Day",
    "2025-11-27": "Thanksgiving",   "2025-12-25": "Christmas Day"
}

# STYLES
STYLE_MONO = {'fontFamily': "'VT323', monospace"}
STYLE_VALUE = {'fontFamily': "'VT323', monospace", 'fontSize': '1.2rem', 'color': '#fff'}
STYLE_LABEL = {'fontFamily': "'VT323', monospace", 'color': '#b5b8b9', 'fontSize': '0.9rem', 'fontWeight': 'bold'}

def get_market_status():
    """Standardized Status Logic."""
    now_ny = datetime.now(pytz.timezone('America/New_York'))
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = time(16, 0) 

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS
    is_active_hours = market_open <= current_time < market_close
    
    status_text = "CLOSED"
    status_color = "#ff5555" # Hard Red
    reason = ""
    
    if is_holiday: reason = f"({HOLIDAYS[today_str]})"
    elif is_weekend: reason = "(WEEKEND)"
    elif is_active_hours:
        status_text = "OPEN"
        status_color = "#00ff41" # Hard Green
        reason = "(LIVE)"
    elif current_time < market_open: reason = "(PRE-MARKET)"
    else: reason = "(POST-MARKET)"

    s_status = {'color': status_color, 'fontWeight': 'bold', 'fontSize': '1.2rem'}
    s_status.update(STYLE_MONO)
    
    s_reason = {'color': '#b5b8b9'}
    s_reason.update(STYLE_MONO)

    html_status = html.Span([
        html.Span(f"MARKET: {status_text}", style=s_status),
        html.Span(f" {reason}", className="small ms-2", style=s_reason)
    ])

    info_line = ""
    if is_active_hours:
        close_str = market_close.strftime("%H:%M")
        info_line = f"SESSION: 09:30 - {close_str} ET"
    else:
        info_line = "MARKET CLOSED"

    return html_status, info_line, is_active_hours

# ==============================================================================
# 2. DATA ENGINE
# ==============================================================================
def load_macro_bias():
    if not MACRO_FILE.exists():
        return "NEUTRAL", "#b5b8b9", "NO DATA"
    try:
        with open(MACRO_FILE, 'r') as f:
            data = json.load(f)
            bias = data.get('bias', 'NEUTRAL')
            reason = data.get('reason', '')
            
            color = "#fde722" 
            if bias == "BULLISH": color = "#00ff41"
            elif bias == "BEARISH": color = "#ff5555"
            
            return bias, color, reason
    except:
        return "ERROR", "#ff5555", "READ FAIL"

def filter_to_rth(df):
    if df is None or df.empty: return df
    if df['Datetime'].dt.tz is None: df['Datetime'] = df['Datetime'].dt.tz_localize('UTC')
    ny_times = df['Datetime'].dt.tz_convert(pytz.timezone('America/New_York'))
    start_time = time(9, 30)
    end_time = time(16, 0)
    mask = (ny_times.dt.time >= start_time) & (ny_times.dt.time <= end_time)
    return df[mask].copy()

def load_snapshot():
    if not SNAPSHOT_FILE.exists(): return None, None, "NO FILE"
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
        xsp = pd.DataFrame(data['xsp'])
        vix = pd.DataFrame(data['vix'])
        
        # TIMEZONE FIX: Force conversion to US/Pacific for display
        updated_ts = pd.to_datetime(data.get('updated', datetime.now()))
        if updated_ts.tzinfo is None: 
            updated_ts = updated_ts.replace(tzinfo=pytz.utc)
        
        target_tz = pytz.timezone('US/Pacific')
        updated_str = updated_ts.astimezone(target_tz).strftime('%H:%M:%S %Z')
        
        if not xsp.empty:
            xsp['Datetime'] = pd.to_datetime(xsp['datetime_utc'])
            xsp.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)
            if xsp['Datetime'].dt.tz is None: xsp['Datetime'] = xsp['Datetime'].dt.tz_localize('UTC')
            xsp['Datetime'] = xsp['Datetime'].dt.tz_convert(target_tz)

        if not vix.empty:
            vix['Datetime'] = pd.to_datetime(vix['datetime_utc'])
            vix.rename(columns={'close': 'Close'}, inplace=True)
            if vix['Datetime'].dt.tz is None: vix['Datetime'] = vix['Datetime'].dt.tz_localize('UTC')
            vix['Datetime'] = vix['Datetime'].dt.tz_convert(target_tz)

        xsp = filter_to_rth(xsp)
        vix = filter_to_rth(vix)
        return xsp, vix, updated_str
    except Exception as e:
        return None, None, "ERROR"

def calculate_orb(df):
    if df is None or df.empty: return None, None
    df = df.copy()
    if len(df) < 5: return None, None
    start_time = df.iloc[0]['Datetime']
    end_time = start_time + timedelta(minutes=30)
    orb_df = df[(df['Datetime'] >= start_time) & (df['Datetime'] < end_time)]
    if orb_df.empty: return None, None
    return orb_df['High'].max(), orb_df['Low'].min()

def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df = df.copy()
    df['x'] = np.arange(len(df))
    if len(df) > 1:
        slope, intercept = np.polyfit(df['x'], df['Close'], 1)
        df['reg_line'] = slope * df['x'] + intercept
        std = df['Close'].std()
        df['upper_band'] = df['reg_line'] + (2 * std)
        df['lower_band'] = df['reg_line'] - (2 * std)
    return df

def fetch_market_internals(vix_df):
    if vix_df is None or vix_df.empty: return None
    df = vix_df.copy()
    df['ema12'] = df['Close'].ewm(span=12).mean()
    df['ema26'] = df['Close'].ewm(span=26).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9).mean()
    df['hist'] = df['macd'] - df['signal']
    delta = df['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

# ==============================================================================
# 3. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- COMMAND HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("ATB SCOPE COMMAND", className="fw-bold text-white mb-0", style={"fontFamily": "'VT323', monospace", "letterSpacing": "2px", "textShadow": "2px 2px #000"}),
                html.P("LIVE FRACTAL MONITOR | XSP NATIVE | VIX REGIME", className="text-info lead mb-0", style=STYLE_MONO)
            ], width=6),
            
            dbc.Col([
                dbc.Row([
                    # UPDATED: REFRESH BUTTON & TIMESTAMP
                    dbc.Col([
                        html.Div("LAST REFRESH:", className="text-end small fw-bold", style={'color': '#b5b8b9', **STYLE_MONO}),
                        html.Div(id="data-freshness", className="text-end fw-bold", style={'color': '#fde722', 'fontSize': '1.2rem', **STYLE_MONO}),
                        dbc.Button("↻ REFRESH DATA", id="btn-manual-refresh", size="sm", color="info", className="mt-1 w-100 font-monospace", style={"fontSize": "0.8rem", "fontWeight": "bold"}),
                        html.Div(id="refresh-feedback", style={'display': 'none'}) # Dummy for callback output
                    ], width=4),
                    
                    dbc.Col([
                        html.H4(id='live-clock-time', className="mb-0 text-end fw-bold", style={'color': '#fde722', 'textShadow': '1px 1px #000', **STYLE_MONO}),
                        html.Div(id='live-market-status', className="text-end"),
                        html.Div(id='live-next-day', className="text-end small", style={'color': '#b5b8b9', **STYLE_MONO})
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-4 pb-2", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "padding": "10px", "boxShadow": "0px 0px 15px rgba(0,0,0,0.8)"}),

        # --- ROW 2: TACTICAL STRIP ---
        dbc.Row([
            dbc.Col([
                html.Div("VIX THERMOMETER", className="small text-muted fw-bold mb-1", style=STYLE_MONO),
                dbc.Row([
                    dbc.Col(dbc.Progress(id="vix-thermometer", value=50, color="warning", className="mt-1", style={"height": "16px", "border": "1px solid #fff"}), width=8),
                    dbc.Col(html.Span(id="vix-val-text", className="ps-2", style=STYLE_VALUE), width=4),
                ], className="g-0 align-items-center"),
            ], width=3, className="border-end border-secondary pe-2"),
            
            dbc.Col([
                html.Div("MACRO REGIME", className="small text-muted fw-bold mb-1 text-center", style=STYLE_MONO),
                html.Div(id="macro-regime-display", className="text-center fw-bold", style={'fontSize': '1.3rem', 'letterSpacing': '1px', **STYLE_MONO})
            ], width=3, className="border-end border-secondary px-2"),

            dbc.Col([
                html.Div("NEURAL CONFIDENCE", className="small text-muted fw-bold mb-1 text-center", style=STYLE_MONO),
                html.Div(id="oracle-readout", className="text-center d-flex align-items-center justify-content-center", style={'fontSize': '1.2rem', 'color': '#00bc8c', **STYLE_MONO})
            ], width=3, className="border-end border-secondary px-2"),

            dbc.Col([
                html.Div("SYSTEM ALERTS", className="small text-muted fw-bold mb-1", style=STYLE_MONO),
                html.Div(id="hud-alerts", className="text-start d-flex align-items-center h-100", style={'fontSize': '1.1rem', **STYLE_MONO})
            ], width=3, className="ps-2")
        ], className="py-2 mb-3", style={"backgroundColor": "#050a18", "border": "1px solid #444", "borderRadius": "4px", "padding": "10px"}),

        # --- ROW 3: SCOPE (THE CHARTS) ---
        dbc.Row([
            dbc.Col([
                dcc.Graph(id='live-scope-chart', style={'height': '75vh'}, config={'displayModeBar': True})
            ], width=12)
        ], className="g-0"),

        dcc.Interval(id='scope-heartbeat', interval=5000, n_intervals=0)
    ], fluid=True, className="px-3 py-3", style={"backgroundColor": "#000"})

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================

# NEW CALLBACK: MANUAL REFRESH TRIGGER
@callback(
    Output("refresh-feedback", "children"),
    Input("btn-manual-refresh", "n_clicks"),
    prevent_initial_call=True
)
def trigger_pipeline(n):
    """
    Spawns the main_pipeline.py as a separate process.
    This prevents the UI from freezing while the heavy lifting happens.
    The Dashboard will update automatically when the file is written.
    """
    if n:
        try:
            # Execute main_pipeline.py in a detached process
            subprocess.Popen([sys.executable, "main_pipeline.py"], cwd=str(ROOT_DIR))
            return "Triggered"
        except Exception as e:
            return f"Error: {e}"
    return no_update

@callback(
    [Output('live-scope-chart', 'figure'),
     Output('live-clock-time', 'children'),
     Output('live-market-status', 'children'),
     Output('live-next-day', 'children'),
     Output('data-freshness', 'children'),
     Output('vix-thermometer', 'value'),
     Output('vix-thermometer', 'color'),
     Output('vix-val-text', 'children'),
     Output('hud-alerts', 'children'),
     Output('oracle-readout', 'children'),
     Output('macro-regime-display', 'children'),
     Output('macro-regime-display', 'style')],
    [Input('scope-heartbeat', 'n_intervals')]
)
def update_hud(n):
    # 1. Fetch Data
    xsp, vix, updated_str = load_snapshot()
    macro_bias, macro_color, macro_reason = load_macro_bias()
    
    # 2. Clock & Status
    now_local = datetime.now(pytz.timezone('US/Pacific'))
    time_str = now_local.strftime("%H:%M:%S")
    status_html, next_info, is_active = get_market_status()
    
    # RTH Boundaries
    today_date = now_local.date()
    rth_start_dt = datetime.combine(today_date, time(6, 30)).replace(tzinfo=pytz.timezone('US/Pacific'))
    rth_end_dt = datetime.combine(today_date, time(13, 0)).replace(tzinfo=pytz.timezone('US/Pacific'))

    macro_style = {'color': macro_color, 'fontSize': '1.3rem', 'letterSpacing': '1px'}
    macro_style.update(STYLE_MONO)

    if xsp is None or xsp.empty:
        fig = go.Figure()
        fig.add_annotation(text="WAITING FOR DATA PIPELINE...", font=dict(color="#fde722", size=24, family="Monospace"), showarrow=False)
        fig.update_layout(template="plotly_dark", paper_bgcolor='black', plot_bgcolor='rgba(0,0,0,0)', xaxis_visible=False, yaxis_visible=False)
        return fig, time_str, status_html, next_info, "OFFLINE", 0, "secondary", "--", [], "", "WAITING", macro_style

    # 3. Math & Logic
    xsp = calculate_linreg(xsp)
    vix = fetch_market_internals(vix)
    orb_h, orb_l = calculate_orb(xsp)

    # 4. Metrics
    curr_vix = 0
    vix_pct = 50
    p_call, p_put = 50, 50
    
    if vix is not None and not vix.empty:
        curr_vix = vix.iloc[-1]['Close']
        vix_pct = min(max(((curr_vix - 12) / (20 - 12)) * 100, 0), 100)
        
        hist = vix.iloc[-1]['hist'] if 'hist' in vix.columns else 0
        rsi = vix.iloc[-1]['rsi'] if 'rsi' in vix.columns else 50
        score = 50.0 + (float(hist) * -200.0)
        if rsi > 70: score += 5
        if rsi < 30: score -= 5
        score = max(0, min(100, score))
        p_call = int(score)
        p_put = 100 - p_call

    oracle_html = html.Span([
        html.Span(f"CALL: {p_call}%", style={'color': '#00bc8c' if p_call > 55 else '#555', 'marginRight': '15px', **STYLE_MONO}),
        html.Span(f"PUT: {p_put}%", style={'color': '#e74c3c' if p_put > 55 else '#555', **STYLE_MONO})
    ])
    
    # Badges
    alert_msg = "SYSTEM NOMINAL"
    alert_color = "success"
    if curr_vix > 20: 
        alert_msg = "HIGH VOLATILITY"
        alert_color = "warning"
    if curr_vix > 30:
        alert_msg = "EXTREME FEAR"
        alert_color = "danger"
    
    badges = [dbc.Badge(alert_msg, color=alert_color, className="me-2", style=STYLE_MONO)]
    therm_color = "danger" if vix_pct > 75 else "info" if vix_pct < 25 else "success"

    # 5. Chart
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2],
                        subplot_titles=("XSP (ORB + LinReg)", "VIX FRACTAL (MACD)", "VIX RSI"))

    fig.add_trace(go.Candlestick(x=xsp['Datetime'], open=xsp['Open'], high=xsp['High'], low=xsp['Low'], close=xsp['Close'], name="Price"), row=1, col=1)
    if 'reg_line' in xsp.columns:
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)
    
    if orb_h:
        fig.add_hline(y=orb_h, line_color="#00bc8c", line_width=1, annotation_text="ORB H", row=1, col=1)
        fig.add_hline(y=orb_l, line_color="#e74c3c", line_width=1, annotation_text="ORB L", row=1, col=1)

    if vix is not None and 'hist' in vix.columns:
        colors = ['#ff5555' if val > 0 else '#00bc8c' for val in vix['hist']]
        fig.add_trace(go.Bar(x=vix['Datetime'], y=vix['hist'], marker_color=colors, name="Hist"), row=2, col=1)
        fig.add_trace(go.Scatter(x=vix['Datetime'], y=vix['macd'], line=dict(color='#f1c40f', width=1), name="MACD"), row=2, col=1)

    if vix is not None and 'rsi' in vix.columns:
        fig.add_trace(go.Scatter(x=vix['Datetime'], y=vix['rsi'], line=dict(color='#a855f7', width=2, shape='spline'), name="RSI"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    fig.update_xaxes(range=[rth_start_dt, rth_end_dt], row=3, col=1)
    fig.update_yaxes(fixedrange=False)

    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='black', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=30, b=40), 
        xaxis_rangeslider_visible=False, 
        showlegend=False,
        hovermode="x unified",
        font=dict(family="'VT323', monospace", size=14, color="#f3f5f9"),
        hoverlabel=dict(bgcolor="#1e1e1e", font=dict(color="#f3f5f9", family="monospace"))
    )

    return fig, time_str, status_html, next_info, updated_str, vix_pct, therm_color, f"{curr_vix:.2f}", badges, oracle_html, macro_bias, macro_style

if __name__ == '__main__':
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
    app.layout = render()
    app.run_server(debug=True, port=8050)