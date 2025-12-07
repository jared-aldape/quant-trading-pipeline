import dash
from dash import dcc, html, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import pytz
from src.core import engine_simulator, engine_ml
from src.utils import config

# ==============================================================================
# 0. TEMPORAL INTELLIGENCE (2025-2026)
# ==============================================================================
HOLIDAYS = {
    "2025-01-01": "New Year's Day", "2025-01-20": "MLK Jr. Day",
    "2025-02-17": "Presidents Day", "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence Day", "2025-09-01": "Labor Day",
    "2025-11-27": "Thanksgiving", "2025-12-25": "Christmas Day",
    "2026-01-01": "New Year's Day", "2026-01-19": "MLK Jr. Day",
    "2026-02-16": "Presidents Day", "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (Obs)", "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving", "2026-12-25": "Christmas Day"
}

EARLY_CLOSES = {
    "2025-07-03": time(13, 0), "2025-11-28": time(13, 0), "2025-12-24": time(13, 0),
    "2026-11-27": time(13, 0), "2026-12-24": time(13, 0)
}

def get_market_status():
    now_ny = datetime.now(config.TZ_NY)
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = EARLY_CLOSES.get(today_str, time(16, 0))

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS
    is_active_hours = market_open <= current_time < market_close
    
    if is_holiday: status_text, color, reason = "CLOSED", "#e74c3c", f"({HOLIDAYS[today_str]})"
    elif is_weekend: status_text, color, reason = "CLOSED", "#e74c3c", "(WEEKEND)"
    elif is_active_hours: status_text, color, reason = "OPEN", "#00ff41", "(LIVE)"
    elif current_time < market_open: status_text, color, reason = "CLOSED", "#e74c3c", "(PRE-MARKET)"
    else: status_text, color, reason = "CLOSED", "#e74c3c", "(POST-MARKET)"

    status_html = html.Span([
        html.Span(f"MARKET STATUS: {status_text}", style={'color': color, 'fontWeight': 'bold'}),
        html.Span(f" {reason}", className="text-muted small ms-2")
    ])

    next_date = now_ny.date() + timedelta(days=1)
    while True:
        d_str = next_date.strftime("%Y-%m-%d")
        if next_date.weekday() < 5 and d_str not in HOLIDAYS: break
        next_date += timedelta(days=1)
        
    return status_html, next_date.strftime("%m/%d/%y")

# ==============================================================================
# 1. MATH LOGIC
# ==============================================================================
def calculate_orb(df):
    if df is None or df.empty: return None, None
    df['time'] = df['Datetime'].dt.time
    start = time(9, 30)
    dummy_date = datetime.now().date()
    start_dt = datetime.combine(dummy_date, start)
    end_dt = start_dt + timedelta(minutes=config.ORB_WINDOW_MINUTES)
    end = end_dt.time()
    
    orb_df = df[(df['time'] >= start) & (df['time'] < end)]
    if orb_df.empty: return None, None
    return orb_df['High'].max(), orb_df['Low'].min()

def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df['x'] = np.arange(len(df))
    slope, intercept = np.polyfit(df['x'], df['Close'], 1)
    df['reg_line'] = slope * df['x'] + intercept
    std = df['Close'].std()
    df['upper_band'] = df['reg_line'] + (2 * std)
    df['lower_band'] = df['reg_line'] - (2 * std)
    return df

def fetch_market_internals():
    vix_df = engine_simulator.get_live_chart_data(ticker="^VIX", period="1d", interval="5m")
    if vix_df is None or vix_df.empty: return None
    
    # Calculate MACD (The Fractal Component)
    vix_df['ema12'] = vix_df['Close'].ewm(span=12).mean()
    vix_df['ema26'] = vix_df['Close'].ewm(span=26).mean()
    vix_df['macd'] = vix_df['ema12'] - vix_df['ema26']
    vix_df['signal'] = vix_df['macd'].ewm(span=9).mean()
    vix_df['hist'] = vix_df['macd'] - vix_df['signal']
    
    # Calculate RSI (Momentum Component)
    delta = vix_df['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
    vix_df['rsi'] = 100 - (100 / (1 + rs))
    return vix_df

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("LIVE MARKET", className="text-white font-monospace fw-bold"),
                html.Small(f"FEED: SPY | VIX | ORB-{config.ORB_WINDOW_MINUTES}m | PROJ. DELTA", className="text-muted")
            ], width=6),
            
            dbc.Col([
                html.H4(id='scope-clock', className="text-end text-info font-monospace mb-0 fw-bold"),
                html.Div(id='scope-status', className="text-end small font-monospace"),
                html.Div(id='scope-next-day', className="text-end text-muted small font-monospace")
            ], width=6, className="align-self-center")
        ], className="mb-2 border-bottom border-secondary pb-2"),

        # ORACLE BANNER
        dbc.Row([
            dbc.Col(html.Div(id='scope-oracle', className="text-center font-monospace fw-bold mb-2"), width=12)
        ]),

        # MAIN CHART
        dbc.Row([
            dbc.Col([
                dcc.Graph(id='scope-chart', style={'height': '85vh'}, config={'displayModeBar': False})
            ], width=12)
        ]),

        dcc.Interval(id='scope-interval', interval=5000, n_intervals=0) 
    ], fluid=True, style={'height': '100vh', 'overflow': 'hidden'})

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output('scope-chart', 'figure'),
     Output('scope-clock', 'children'),
     Output('scope-status', 'children'),
     Output('scope-next-day', 'children'),
     Output('scope-oracle', 'children')],
    [Input('scope-interval', 'n_intervals')]
)
def update_scope(n):
    # 1. Fetch Data
    spy_df = engine_simulator.get_live_chart_data(ticker="SPY", period="1d", interval="5m")
    vix_df = fetch_market_internals()
    
    # 2. Oracle Prediction
    vix_val, vix_rsi_val = engine_simulator.get_vix_metrics()
    p_call = engine_ml.predict_success("CALL", vix_val, vix_rsi_val)
    p_put = engine_ml.predict_success("PUT", vix_val, vix_rsi_val)
    
    oracle_html = html.Div([
        html.Span(f"🤖 AI FORECAST: ", className="text-muted me-2"),
        html.Span(f"CALL {p_call}%", style={'color': '#00bc8c' if p_call > 60 else '#555', 'marginRight': '15px'}),
        html.Span(f"PUT {p_put}%", style={'color': '#e74c3c' if p_put > 60 else '#555'})
    ])

    # 3. Clock & Status
    now_pst = datetime.now(config.TZ_LOCAL)
    time_str = now_pst.strftime("%m/%d/%y | %I:%M:%S %p PST")
    status_html, next_day = get_market_status()
    next_day_str = f"Next Market Day: {next_day}"

    if spy_df is None or spy_df.empty:
        fig = go.Figure()
        fig.update_layout(template="plotly_dark", title="WAITING FOR MARKET DATA...")
        return fig, time_str, status_html, next_day_str, oracle_html

    # 4. Process Math
    spy_df = calculate_linreg(spy_df)
    orb_h, orb_l = calculate_orb(spy_df)

    # 5. Build Chart (Updated Titles to swap MACD for FRACTAL FLOW)
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.02, 
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=("SPY (ORB + LinReg)", "VIX FRACTAL FLOW", "VIX RSI (Momentum)") # <--- CHANGED
    )

    # ROW 1: SPY Price + Overlays
    fig.add_trace(go.Candlestick(
        x=spy_df['Datetime'], open=spy_df['Open'], high=spy_df['High'], low=spy_df['Low'], close=spy_df['Close'],
        name="SPY"
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=spy_df['Datetime'], y=spy_df['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
    fig.add_trace(go.Scatter(x=spy_df['Datetime'], y=spy_df['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
    fig.add_trace(go.Scatter(x=spy_df['Datetime'], y=spy_df['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)
    
    if orb_h:
        fig.add_hline(y=orb_h, line_color="#00bc8c", line_width=1, annotation_text="ORB H", row=1, col=1)
        fig.add_hline(y=orb_l, line_color="#e74c3c", line_width=1, annotation_text="ORB L", row=1, col=1)

    # ROW 2: VIX FRACTAL FLOW (Derived from MACD)
    if vix_df is not None:
        # Re-labeled to "Fractal" for consistency
        fig.add_trace(go.Bar(x=vix_df.index, y=vix_df['hist'], marker_color='rgba(255, 255, 255, 0.3)', name="Fractal Hist"), row=2, col=1)
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['macd'], line=dict(color='#f1c40f', width=1), name="Fractal Line"), row=2, col=1)

    # ROW 3: VIX RSI
    if vix_df is not None:
        fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['rsi'], line=dict(color='#a855f7', width=2), name="VIX RSI"), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=3, col=1)

    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=30, b=40),
        xaxis_rangeslider_visible=False,
        showlegend=False
    )

    return fig, time_str, status_html, next_day_str, oracle_html