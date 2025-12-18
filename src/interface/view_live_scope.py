import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import json
import subprocess
import sys
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

try:
    import src.core.engine_ml as engine_ml
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

# ==============================================================================
# 1. TEMPORAL INTELLIGENCE (IMPORTED FROM OPTIONS SIM)
# ==============================================================================
HOLIDAYS = {
    "2025-01-01": "New Year's Day", "2025-01-20": "MLK Jr. Day",
    "2025-02-17": "Presidents Day", "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence Day", "2025-09-01": "Labor Day",
    "2025-10-13": "Columbus Day",   "2025-11-11": "Veterans Day",
    "2025-11-27": "Thanksgiving",   "2025-12-25": "Christmas Day"
}

EARLY_CLOSES = {
    "2025-07-03": time(13, 0), 
    "2025-11-28": time(13, 0), 
    "2025-12-24": time(13, 0)
}

def get_market_status():
    """
    Standardized Status Logic (Matches Training Grounds).
    Returns: HTML Status, Info String, Is_Active Boolean
    """
    # Use config.TZ_NY for market logic to be safe
    now_ny = datetime.now(config.TZ_NY)
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = EARLY_CLOSES.get(today_str, time(16, 0))

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS
    is_active_hours = market_open <= current_time < market_close
    
    status_text = "CLOSED"
    status_color = "#ff5555" # Hard Red
    reason = ""
    
    if is_holiday:
        reason = f"({HOLIDAYS[today_str]})"
    elif is_weekend:
        reason = "(WEEKEND)"
    elif is_active_hours:
        status_text = "OPEN"
        status_color = "#00ff41" # Hard Green
        reason = "(LIVE)"
    elif current_time < market_open:
        reason = "(PRE-MARKET)"
    else:
        reason = "(POST-MARKET)"

    html_status = html.Span([
        html.Span(f"MARKET: {status_text}", style={'color': status_color, 'fontWeight': 'bold', 'fontFamily': "'VT323', monospace", 'fontSize': '1.2rem'}),
        html.Span(f" {reason}", className="small ms-2", style={'color': '#b5b8b9', 'fontFamily': "'VT323', monospace"})
    ])

    info_line = ""
    if is_active_hours:
        # Convert close to user local time for display if desired, keeping ET for standard
        close_str = market_close.strftime("%H:%M")
        info_line = f"SESSION: 09:30 - {close_str} ET"
    else:
        target_date = now_ny.date()
        if not is_weekend and not is_holiday and current_time < market_open:
            date_label = "TODAY"
        else:
            target_date += timedelta(days=1)
            while True:
                d_str = target_date.strftime("%Y-%m-%d")
                if target_date.weekday() < 5 and d_str not in HOLIDAYS:
                    break
                target_date += timedelta(days=1)
            date_label = target_date.strftime("%A, %b %d")
        info_line = f"NEXT OPEN: {date_label} @ 09:30 ET"

    return html_status, info_line, is_active_hours

# ==============================================================================
# 2. DATA ENGINE
# ==============================================================================
def filter_to_rth(df):
    """
    Strict RTH Clip: 09:30 - 16:00 ET.
    Ensures charts don't show pre/post market noise.
    """
    if df is None or df.empty: return df
    
    # Ensure Datetime is timezone-aware before converting
    if df['Datetime'].dt.tz is None:
         # Fallback assumption: Data in snapshot is UTC if naive
         df['Datetime'] = df['Datetime'].dt.tz_localize('UTC')
    
    # Convert to NY for filtering rules
    ny_times = df['Datetime'].dt.tz_convert(config.TZ_NY)
    
    start_time = time(9, 30)
    end_time = time(16, 0)
    
    # Create Mask
    mask = (ny_times.dt.time >= start_time) & (ny_times.dt.time <= end_time)
    
    return df[mask].copy()

def load_snapshot():
    """Reads JSON snapshot. Returns Data + Update Time."""
    if not SNAPSHOT_FILE.exists(): return None, None, "NO FILE"
    try:
        with open(SNAPSHOT_FILE, 'r') as f:
            data = json.load(f)
            
        xsp = pd.DataFrame(data['xsp'])
        vix = pd.DataFrame(data['vix'])
        
        # Parse Freshness
        updated_ts = pd.to_datetime(data.get('updated', datetime.now()))
        # Convert updated time to Local (PST)
        if updated_ts.tzinfo is None:
            updated_ts = updated_ts.replace(tzinfo=pytz.utc)
        updated_str = updated_ts.astimezone(config.TZ_LOCAL).strftime('%H:%M:%S')
        
        # Hydrate XSP
        if not xsp.empty:
            xsp['Datetime'] = pd.to_datetime(xsp['datetime_utc'])
            xsp.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)
            # Ensure UTC then convert to Local (PST)
            if xsp['Datetime'].dt.tz is None: xsp['Datetime'] = xsp['Datetime'].dt.tz_localize('UTC')
            xsp['Datetime'] = xsp['Datetime'].dt.tz_convert(config.TZ_LOCAL)

        # Hydrate VIX
        if not vix.empty:
            vix['Datetime'] = pd.to_datetime(vix['datetime_utc'])
            vix.rename(columns={'close': 'Close'}, inplace=True)
            if vix['Datetime'].dt.tz is None: vix['Datetime'] = vix['Datetime'].dt.tz_localize('UTC')
            vix['Datetime'] = vix['Datetime'].dt.tz_convert(config.TZ_LOCAL)

        # RTH Filter (Passes through NY logic but keeps Local TZ)
        xsp = filter_to_rth(xsp)
        vix = filter_to_rth(vix)

        return xsp, vix, updated_str
    except Exception as e:
        return None, None, "ERROR"

def calculate_orb(df):
    if df is None or df.empty: return None, None
    df = df.copy()
    if len(df) < 5: return None, None
    
    # ORB Logic: First 30 mins of the dataset (which is already RTH filtered)
    start_time = df.iloc[0]['Datetime']
    end_time = start_time + timedelta(minutes=30)
    
    orb_df = df[(df['Datetime'] >= start_time) & (df['Datetime'] < end_time)]
    if orb_df.empty: return None, None
    return orb_df['High'].max(), orb_df['Low'].min()

def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df = df.copy()
    # Simple linear regression on the available window
    df['x'] = np.arange(len(df))
    if len(df) > 1:
        slope, intercept = np.polyfit(df['x'], df['Close'], 1)
        df['reg_line'] = slope * df['x'] + intercept
        std = df['Close'].std()
        df['upper_band'] = df['reg_line'] + (2 * std)
        df['lower_band'] = df['reg_line'] - (2 * std)
    return df

def fetch_market_internals(vix_df):
    """
    Calculates the MACD and RSI for VIX.
    This IS the data behind the Fractal Flow.
    """
    if vix_df is None or vix_df.empty: return None
    df = vix_df.copy()
    
    # MACD (12, 26, 9)
    df['ema12'] = df['Close'].ewm(span=12).mean()
    df['ema26'] = df['Close'].ewm(span=26).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['signal'] = df['macd'].ewm(span=9).mean()
    df['hist'] = df['macd'] - df['signal']
    
    # RSI (14)
    delta = df['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + rs))
    
    return df

# ==============================================================================
# 3. LAYOUT (UNIFIED MAGITEK STANDARD)
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- COMMAND HEADER (MATCHING SIMULATOR) ---
        dbc.Row([
            dbc.Col([
                html.H2("ATB SCOPE COMMAND", className="fw-bold text-white mb-0", style={"fontFamily": "'VT323', monospace", "letterSpacing": "2px", "textShadow": "2px 2px #000"}),
                html.P("LIVE FRACTAL MONITOR | XSP NATIVE | VIX REGIME", className="text-info lead mb-0", style={"fontFamily": "'VT323', monospace", "fontSize": "1.1rem"})
            ], width=6),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        html.Div("DATA INTEGRITY:", className="text-end small fw-bold", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"}),
                        html.Div(id="data-freshness", className="text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}),
                    ], width=4),
                    dbc.Col([
                        html.H4(id='live-clock-time', className="mb-0 text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "textShadow": "1px 1px #000"}),
                        html.Div(id='live-market-status', className="text-end"),
                        html.Div(id='live-next-day', className="text-end small", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"})
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-4 pb-2", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "padding": "10px", "boxShadow": "0px 0px 15px rgba(0,0,0,0.8)"}),

        # --- ROW 2: TACTICAL STRIP ---
        dbc.Row([
            dbc.Col([
                html.Div("VIX THERMOMETER", className="small text-muted fw-bold mb-1", style={"fontFamily": "'VT323', monospace"}),
                dbc.Row([
                    dbc.Col(dbc.Progress(id="vix-thermometer", value=50, color="warning", className="mt-1", style={"height": "16px", "border": "1px solid #fff"}), width=8),
                    dbc.Col(html.Span(id="vix-val-text", className="ps-2", style={"color": "#fff", "fontFamily": "'VT323', monospace", "fontSize": "1.1rem"}), width=4),
                ], className="g-0 align-items-center"),
            ], width=4, className="border-end border-secondary pe-3"),
            
            dbc.Col([
                html.Div("NEURAL CONFIDENCE (FRACTAL SCORE)", className="small text-muted fw-bold mb-1 text-center", style={"fontFamily": "'VT323', monospace"}),
                html.Div(id="oracle-readout", className="text-center d-flex align-items-center justify-content-center", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem", "color": "#00bc8c"})
            ], width=4, className="border-end border-secondary px-3"),

            dbc.Col([
                html.Div("SYSTEM ALERTS", className="small text-muted fw-bold mb-1", style={"fontFamily": "'VT323', monospace"}),
                html.Div(id="hud-alerts", className="text-start d-flex align-items-center h-100", style={"fontFamily": "'VT323', monospace", "fontSize": "1.1rem"})
            ], width=4, className="ps-3")
        ], className="py-2 mb-3", style={"backgroundColor": "#050a18", "border": "1px solid #444", "borderRadius": "4px", "padding": "10px"}),

        # --- ROW 3: SCOPE (THE CHARTS) ---
        dbc.Row([
            dbc.Col([
                dcc.Graph(id='live-scope-chart', style={'height': '75vh'}, config={'displayModeBar': True})
            ], width=12)
        ], className="g-0"),

        # 5 Second Heartbeat (Polls JSON for changes)
        dcc.Interval(id='scope-heartbeat', interval=5000, n_intervals=0)
    ], fluid=True, className="px-3 py-3", style={"backgroundColor": "#000"})

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
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
     Output('oracle-readout', 'children')],
    [Input('scope-heartbeat', 'n_intervals')]
)
def update_hud(n):
    # 1. Fetch Data
    xsp, vix, updated_str = load_snapshot()
    
    # 2. Clock & Status
    now_local = datetime.now(config.TZ_LOCAL)
    time_str = now_local.strftime("%H:%M:%S")
    status_html, next_info, is_active = get_market_status()
    
    # 3. Calculate RTH Boundaries for X-Axis Lock
    # This enforces the 09:30 - 16:00 ET window converted to local (PST)
    today_date = now_local.date()
    # 06:30 PST = 09:30 ET
    rth_start_dt = datetime.combine(today_date, time(6, 30)).replace(tzinfo=config.TZ_LOCAL)
    # 13:00 PST = 16:00 ET
    rth_end_dt = datetime.combine(today_date, time(13, 0)).replace(tzinfo=config.TZ_LOCAL)

    if xsp is None or xsp.empty:
        fig = go.Figure()
        fig.add_annotation(text="WAITING FOR DATA PIPELINE...", font=dict(color="#fde722", size=24, family="Monospace"), showarrow=False)
        fig.update_layout(
            template="plotly_dark", 
            paper_bgcolor='black', 
            plot_bgcolor='rgba(0,0,0,0)', 
            xaxis_visible=False, yaxis_visible=False
        )
        return fig, time_str, status_html, next_info, "OFFLINE", 0, "secondary", "--", [], ""

    # 4. Math & Logic
    xsp = calculate_linreg(xsp)
    vix = fetch_market_internals(vix)
    orb_h, orb_l = calculate_orb(xsp)

    # 5. Metrics
    curr_vix = 0
    vix_pct = 50
    p_call, p_put = 50, 50
    
    if vix is not None and not vix.empty:
        curr_vix = vix.iloc[-1]['Close']
        vix_pct = min(max(((curr_vix - 12) / (20 - 12)) * 100, 0), 100)
        
        # Calculate Fractal Score
        hist = vix.iloc[-1]['hist'] if 'hist' in vix.columns else 0
        rsi = vix.iloc[-1]['rsi'] if 'rsi' in vix.columns else 50
        score = 50.0 + (float(hist) * -200.0)
        if rsi > 70: score += 5
        if rsi < 30: score -= 5
        score = max(0, min(100, score))
        p_call = int(score)
        p_put = 100 - p_call

    oracle_html = html.Span([
        html.Span(f"CALL: {p_call}%", style={'color': '#00bc8c' if p_call > 55 else '#555', 'marginRight': '15px', 'fontFamily': "'VT323', monospace"}),
        html.Span(f"PUT: {p_put}%", style={'color': '#e74c3c' if p_put > 55 else '#555', 'fontFamily': "'VT323', monospace"})
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
    
    badges = [dbc.Badge(alert_msg, color=alert_color, className="me-2", style={"fontFamily": "'VT323', monospace"})]
    therm_color = "danger" if vix_pct > 75 else "info" if vix_pct < 25 else "success"

    # 6. Chart (Rich Layout - Restored)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2],
                        subplot_titles=("XSP (ORB + LinReg)", "VIX FRACTAL (MACD)", "VIX RSI"))

    # ROW 1: PRICE
    fig.add_trace(go.Candlestick(x=xsp['Datetime'], open=xsp['Open'], high=xsp['High'], low=xsp['Low'], close=xsp['Close'], name="Price"), row=1, col=1)
    if 'reg_line' in xsp.columns:
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)
    
    if orb_h:
        fig.add_hline(y=orb_h, line_color="#00bc8c", line_width=1, annotation_text="ORB H", row=1, col=1)
        fig.add_hline(y=orb_l, line_color="#e74c3c", line_width=1, annotation_text="ORB L", row=1, col=1)

    # ROW 2: VIX MACD
    if vix is not None and 'hist' in vix.columns:
        # Color Logic: Red for Heat (Positive), Green for Cool (Negative)
        colors = ['#ff5555' if val > 0 else '#00bc8c' for val in vix['hist']]
        fig.add_trace(go.Bar(x=vix['Datetime'], y=vix['hist'], marker_color=colors, name="Hist"), row=2, col=1)
        fig.add_trace(go.Scatter(x=vix['Datetime'], y=vix['macd'], line=dict(color='#f1c40f', width=1), name="MACD"), row=2, col=1)

    # ROW 3: VIX RSI
    if vix is not None and 'rsi' in vix.columns:
        fig.add_trace(go.Scatter(x=vix['Datetime'], y=vix['rsi'], line=dict(color='#a855f7', width=2, shape='spline'), name="RSI"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    # ⚡ ZOOM LOCKED & DARK HOVER
    # Lock X-Axis to Today's RTH Window (PST)
    fig.update_xaxes(range=[rth_start_dt, rth_end_dt], row=3, col=1) # Apply to bottom chart (shared axis)
    fig.update_yaxes(fixedrange=False) # Allow Y-axis zoom

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

    return fig, time_str, status_html, next_info, updated_str, vix_pct, therm_color, f"{curr_vix:.2f}", badges, oracle_html