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
import time as t_time 
import pandas_ta as ta
from datetime import datetime, time, timedelta
import pytz
from pathlib import Path

# ==============================================================================
# 1. SETUP & PATHING
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
# ⚡ NEURAL INJECTION: Import your trained Oracle
from src.core import engine_ml_precision

# FILE POINTERS
SNAPSHOT_FILE = config.DATA_DIR / "live_snapshot.json"
MACRO_FILE = config.DATA_DIR / "macro_bias.json"
REFRESH_SCRIPT = ROOT_DIR / "main_pipeline.py"

# ==============================================================================
# 2. TEMPORAL INTELLIGENCE
# ==============================================================================
MARKET_CALENDAR_2026 = {
    "2026-01-01": {"name": "New Year's Day", "status": "CLOSED"},
    "2026-01-19": {"name": "MLK Jr. Day", "status": "CLOSED"},
    "2026-02-16": {"name": "Presidents Day", "status": "CLOSED"},
    "2026-04-03": {"name": "Good Friday", "status": "CLOSED"},
    "2026-05-25": {"name": "Memorial Day", "status": "CLOSED"},
    "2026-06-19": {"name": "Juneteenth", "status": "CLOSED"},
    "2026-07-03": {"name": "Independence Day (Obs)", "status": "CLOSED"},
    "2026-09-07": {"name": "Labor Day", "status": "CLOSED"},
    "2026-11-26": {"name": "Thanksgiving", "status": "CLOSED"},
    "2026-11-27": {"name": "Black Friday", "status": "13:00 CLOSE"},
    "2026-12-24": {"name": "Christmas Eve", "status": "13:00 CLOSE"},
    "2026-12-25": {"name": "Christmas Day", "status": "CLOSED"}
}

def get_market_status():
    """
    Enhanced Logic: 
    - PRE-MARKET (04:00 - 09:30) -> YELLOW
    - OPEN (09:30 - 16:00) -> GREEN
    - AFTER HOURS (16:00 - 20:00) -> YELLOW
    - CLOSED (Other) -> RED
    """
    now_ny = datetime.now(pytz.timezone('America/New_York'))
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    # Session Times
    t_pre_start = time(4, 0)
    t_open = time(9, 30)
    t_close = time(16, 0)
    t_post_end = time(20, 0)

    # Defaults
    status_text = "MARKET CLOSED"
    status_color = "var(--inst-danger)" # Red
    reason = ""
    is_active = False # Algo Execution Flag

    # 1. Check Calendar Holidays
    cal_event = MARKET_CALENDAR_2026.get(today_str)
    if cal_event:
        if cal_event['status'] == "CLOSED":
            reason = f"({cal_event['name']})"
            # Returns immediately as Closed
            return _format_status(status_text, status_color, reason, t_open, t_close), False
        elif "13:00" in cal_event['status']:
            t_close = time(13, 0)
            reason = f"({cal_event['name']})"

    # 2. Check Weekend
    if now_ny.weekday() >= 5:
        reason = "(WEEKEND)"
        return _format_status(status_text, status_color, reason, t_open, t_close), False

    # 3. Time of Day Logic
    if t_pre_start <= current_time < t_open:
        status_text = "PRE-MARKET"
        status_color = "var(--inst-warning)" # Yellow
        is_active = False # No Algo in Pre-market
    elif t_open <= current_time < t_close:
        status_text = "MARKET OPEN"
        status_color = "var(--inst-success)" # Green
        is_active = True
    elif t_close <= current_time < t_post_end:
        status_text = "AFTER HOURS"
        status_color = "var(--inst-warning)" # Yellow
        is_active = False
    else:
        # Overnight Closed
        status_text = "MARKET CLOSED"
        status_color = "var(--inst-danger)" # Red
        is_active = False

    return _format_status(status_text, status_color, reason, t_open, t_close), is_active

def _format_status(text, color, reason, t_open, t_close):
    html_status = html.Span([
        html.Span(text, className="fw-bold", style={'color': color, 'fontSize': '1.1rem'}),
        html.Span(f" {reason}", className="small ms-1 text-muted")
    ])
    
    info_line = html.Div([
        html.Span(f"RTH: {t_open.strftime('%H:%M')} - {t_close.strftime('%H:%M')} ET", className="me-2"),
    ], className="small text-muted font-monospace")
    
    return html_status, info_line

# ==============================================================================
# 3. DATA ENGINE
# ==============================================================================
def load_macro_bias():
    if not MACRO_FILE.exists(): return "NEUTRAL", "#94a3b8"
    try:
        with open(MACRO_FILE, 'r') as f:
            data = json.load(f)
            bias = data.get('bias', 'NEUTRAL')
            if bias == "BULLISH": color = "var(--inst-success)"
            elif bias == "BEARISH": color = "var(--inst-danger)"
            else: color = "var(--inst-warning)"
            return bias, color
    except: return "ERROR", "var(--inst-danger)"

def load_snapshot():
    if not SNAPSHOT_FILE.exists(): return None, None, "NO FILE"
    
    # RETRY LOGIC FOR WINDOWS FILE LOCKS
    data = None
    attempts = 3
    while attempts > 0:
        try:
            with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            break
        except Exception:
            t_time.sleep(0.1)
            attempts -= 1
            
    if data is None: return None, None, "FILE LOCKED"

    try:
        updated_ts = pd.to_datetime(data.get('updated', datetime.now()))
        if updated_ts.tzinfo is None: updated_ts = updated_ts.replace(tzinfo=pytz.utc)
        target_tz = pytz.timezone('US/Pacific')
        updated_str = updated_ts.astimezone(target_tz).strftime('%H:%M:%S')
        
        xsp = pd.DataFrame(data.get('xsp', []))
        vix = pd.DataFrame(data.get('vix', []))
        
        if not xsp.empty:
            xsp['Datetime'] = pd.to_datetime(xsp['datetime_utc'])
            if xsp['Datetime'].dt.tz is None: xsp['Datetime'] = xsp['Datetime'].dt.tz_localize(config.TZ_LOCAL)
            else: xsp['Datetime'] = xsp['Datetime'].dt.tz_convert(config.TZ_LOCAL)
            xsp.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)

        if not vix.empty:
            vix['Datetime'] = pd.to_datetime(vix['datetime_utc'])
            if vix['Datetime'].dt.tz is None: vix['Datetime'] = vix['Datetime'].dt.tz_localize(config.TZ_LOCAL)
            else: vix['Datetime'] = vix['Datetime'].dt.tz_convert(config.TZ_LOCAL)
            vix.rename(columns={'close': 'Close'}, inplace=True)

        return xsp, vix, updated_str
    except Exception as e:
        print(f"Data Load Error: {e}")
        return None, None, "ERR"

# Math Helpers
def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df = df.copy()
    df['x'] = np.arange(len(df))
    slope, intercept = np.polyfit(df['x'], df['Close'], 1)
    df['reg_line'] = slope * df['x'] + intercept
    std = df['Close'].std()
    df['upper_band'] = df['reg_line'] + (2 * std)
    df['lower_band'] = df['reg_line'] - (2 * std)
    return df

def fetch_market_internals(vix_df, xsp_df=None):
    """
    ⚡ UPGRADED: Calculates technicals for BOTH VIX and XSP so the Oracle has full context.
    """
    if vix_df is None or vix_df.empty: return None, None
    v = vix_df.copy()
    
    # VIX MACD/RSI
    try:
        v_macd = ta.macd(v['Close'])
        v['macd'] = v_macd['MACD_12_26_9']
        v['signal'] = v_macd['MACDs_12_26_9']
        v['hist'] = v_macd['MACDh_12_26_9']
        
        # Calculate Cross (-1, 0, 1)
        v_diff = v['macd'] - v['signal']
        v['cross'] = np.where((v_diff > 0) & (v_diff.shift(1) <= 0), 1, 0)
        v['cross'] = np.where((v_diff < 0) & (v_diff.shift(1) >= 0), -1, v['cross'])
    except:
        v['macd'], v['signal'], v['hist'], v['cross'] = 0, 0, 0, 0

    v['rsi'] = ta.rsi(v['Close'])

    x = None
    if xsp_df is not None and not xsp_df.empty:
        x = xsp_df.copy()
        try:
            x_macd = ta.macd(x['Close'])
            x['macd'] = x_macd['MACD_12_26_9']
            x['signal'] = x_macd['MACDs_12_26_9']
            x['hist'] = x_macd['MACDh_12_26_9']
            
            x_diff = x['macd'] - x['signal']
            x['cross'] = np.where((x_diff > 0) & (x_diff.shift(1) <= 0), 1, 0)
            x['cross'] = np.where((x_diff < 0) & (x_diff.shift(1) >= 0), -1, x['cross'])
            
            x_adx = ta.adx(x['High'], x['Low'], x['Close'])
            x['adx'] = x_adx['ADX_14'] if x_adx is not None else 20
        except:
            x['macd'], x['signal'], x['hist'], x['cross'], x['adx'] = 0, 0, 0, 0, 20

    return v, x

def calculate_orb(df):
    if df is None or df.empty or len(df) < 5: return None, None
    start_time = df.iloc[0]['Datetime']
    end_time = start_time + timedelta(minutes=30)
    orb_df = df[(df['Datetime'] >= start_time) & (df['Datetime'] < end_time)]
    if orb_df.empty: return None, None
    return orb_df['High'].max(), orb_df['Low'].min()

def generate_guardrails(xsp, vix):
    alerts = []
    # 3. ALGO STATUS (Trigger Logic)
    _, is_open = get_market_status()
    if is_open:
        alerts.append(html.Div("🚀 ALGO: RUNNING", className="text-success fw-bold small"))
    else:
        alerts.append(html.Div("💤 ALGO: STANDBY", className="text-muted fw-bold small"))
    return alerts

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("REAL-TIME MONITOR", className="fw-bold text-white mb-0"),
                html.P("INSTITUTIONAL EXECUTION FLOW | XSP NATIVE", className="text-muted small fw-bold mb-0")
            ], width=6),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        html.Div("LAST SYNC", className="text-end text-muted small fw-bold"),
                        html.Div(id="data-freshness", className="text-end fw-bold font-monospace text-warning", style={'fontSize': '1.1rem'}),
                        html.Div(id="refresh-feedback", className="text-end small text-info font-monospace")
                    ], width=4),
                    dbc.Col([
                        html.H3(id='live-clock-time', className="mb-0 text-end fw-bold font-monospace text-info"),
                        html.Div(id='live-market-status', className="text-end"),
                        html.Div(id='live-next-day', className="text-end")
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # HUD
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Volatility Index (VIX)"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col(dbc.Progress(id="vix-thermometer", value=50, color="warning", style={"height": "8px"}), width=8),
                            dbc.Col(html.Div(id="vix-val-text", className="fw-bold font-monospace text-end"), width=4),
                        ], className="align-items-center"),
                    ])
                ])
            ], width=3),
            
            dbc.Col(dbc.Card([dbc.CardHeader("Market Sentiment Bias"), dbc.CardBody(html.Div(id="macro-regime-display", className="text-center fw-bold", style={'fontSize': '1.2rem'}))]), width=3),
            dbc.Col(dbc.Card([dbc.CardHeader("Neural Alpha Confidence"), dbc.CardBody(html.Div(id="oracle-readout", className="text-center fw-bold font-monospace"))]), width=3),
            dbc.Col(dbc.Card([dbc.CardHeader("System Guardrails"), dbc.CardBody(html.Div(id="hud-alerts", className="text-start"))]), width=3),
        ], className="mb-4"),

        # Chart
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("Multi-Factor Price Action Analysis"),
                        dbc.Button("FORCE SYNC", id="btn-manual-refresh", size="sm", color="primary", className="float-end fw-bold")
                    ]),
                    dbc.CardBody(dcc.Graph(id='live-scope-chart', style={'height': '70vh'}, config={'displayModeBar': True}))
                ])
            ], width=12)
        ]),
        
        dcc.Interval(id='scope-heartbeat', interval=5000, n_intervals=0)
    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================

@callback(Output("refresh-feedback", "children"), Input("btn-manual-refresh", "n_clicks"), prevent_initial_call=True)
def trigger_pipeline(n):
    if n:
        try:
            subprocess.Popen([sys.executable, str(REFRESH_SCRIPT)], cwd=str(ROOT_DIR))
            return f"Triggered @ {datetime.now().strftime('%H:%M:%S')}"
        except Exception as e: return f"Error: {e}"
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
    xsp, vix, updated_str = load_snapshot()
    macro_bias, macro_color = load_macro_bias()
    
    now_local = datetime.now(pytz.timezone('US/Pacific'))
    time_str = now_local.strftime("%H:%M:%S")
    
    # UNPACK 2 VALUES (html, info) + IGNORE is_active boolean
    status_html, next_info = get_market_status()[0] 
    
    macro_style = {'color': macro_color}
    guardrails = generate_guardrails(xsp, vix)

    if xsp is None or xsp.empty:
        fig = go.Figure()
        msg = f"WAITING... ({updated_str})" if updated_str else "WAITING FOR DATA PIPELINE..."
        fig.add_annotation(text=msg, font=dict(color="var(--inst-warning)", size=18), showarrow=False)
        fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', xaxis_visible=False, yaxis_visible=False)
        return fig, time_str, status_html, next_info, updated_str if updated_str else "OFFLINE", 0, "secondary", "--", guardrails, "", "WAITING", macro_style

    anchor_date = xsp['Datetime'].max().date()
    rth_start_dt = datetime.combine(anchor_date, time(6, 30)).replace(tzinfo=pytz.timezone('US/Pacific'))
    rth_end_dt = datetime.combine(anchor_date, time(13, 0)).replace(tzinfo=pytz.timezone('US/Pacific'))

    xsp = calculate_linreg(xsp)
    vix, xsp = fetch_market_internals(vix, xsp)
    orb_h, orb_l = calculate_orb(xsp)

    # ⚡ ORACLE V5 REAL-TIME PREDICTION
    try:
        if vix is not None and not vix.empty and xsp is not None and not xsp.empty:
            lv = vix.iloc[-1]
            lx = xsp.iloc[-1]
            
            p_call = engine_ml_precision.predict_success(
                "CALL", vix_val=lv['rsi'], vix_hist=lv['hist'], vix_cross=lv['cross'],
                xsp_hist=lx['hist'], xsp_cross=lx['cross'], adx=lx['adx'], trade_hour=now_local.hour
            )
            p_put = engine_ml_precision.predict_success(
                "PUT", vix_val=lv['rsi'], vix_hist=lv['hist'], vix_cross=lv['cross'],
                xsp_hist=lx['hist'], xsp_cross=lx['cross'], adx=lx['adx'], trade_hour=now_local.hour
            )
            
            call_style = {'color': 'var(--inst-success)', 'fontWeight': 'bold'} if p_call > 70 else {'color': 'var(--inst-text-main)'}
            put_style = {'color': 'var(--inst-danger)', 'fontWeight': 'bold'} if p_put > 70 else {'color': 'var(--inst-text-main)'}
            
            oracle_html = html.Div([
                html.Span(f"CALL: {p_call:.1f}%", className="me-3", style=call_style),
                html.Span(f"PUT: {p_put:.1f}%", style=put_style)
            ])
        else:
            oracle_html = html.Span("ORACLE PENDING DATA...", className="text-muted")
    except Exception as e:
        print(f"Oracle Error: {e}")
        oracle_html = html.Span("ORACLE OFFLINE", className="text-danger")

    # VIX LOGIC - COLORIZED TEXT
    curr_vix = vix.iloc[-1]['Close'] if (vix is not None and not vix.empty) else 0
    vix_pct = min(max(((curr_vix - 12) / (20 - 12)) * 100, 0), 100)
    
    if curr_vix > 30:
        therm_color = "danger"
        vix_text_color = "#e74c3c" # Red
    elif curr_vix > 20:
        therm_color = "warning"
        vix_text_color = "#f1c40f" # Yellow
    else:
        therm_color = "success" 
        vix_text_color = "#ffffff" # White

    vix_display = html.Span(f"{curr_vix:.2f}", style={'color': vix_text_color, 'fontSize': '1.2rem'})

    # PLOT
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2],
                        subplot_titles=("XSP Index Flow", "VIX Fractal Momentum", "VIX RSI"))

    fig.add_trace(go.Candlestick(x=xsp['Datetime'], open=xsp['Open'], high=xsp['High'], low=xsp['Low'], close=xsp['Close'], name="Price"), row=1, col=1)
    if 'reg_line' in xsp.columns:
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['reg_line'], line=dict(color='var(--inst-warning)', width=1, dash='dot')), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['upper_band'], line=dict(color='var(--inst-accent)', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp['Datetime'], y=xsp['lower_band'], line=dict(color='var(--inst-accent)', width=1)), row=1, col=1)
    
    if orb_h:
        fig.add_hline(y=orb_h, line_color="var(--inst-success)", line_width=1, annotation_text="ORB H", row=1, col=1)
        fig.add_hline(y=orb_l, line_color="var(--inst-danger)", line_width=1, annotation_text="ORB L", row=1, col=1)

    if vix is not None and 'hist' in vix.columns:
        colors = ['var(--inst-danger)' if val > 0 else 'var(--inst-success)' for val in vix['hist']]
        fig.add_trace(go.Bar(x=vix['Datetime'], y=vix['hist'], marker_color=colors), row=2, col=1)
        fig.add_trace(go.Scatter(x=vix['Datetime'], y=vix['macd'], line=dict(color='#f1c40f', width=1)), row=2, col=1)

    if vix is not None and 'rsi' in vix.columns:
        fig.add_trace(go.Scatter(x=vix['Datetime'], y=vix['rsi'], line=dict(color='#a855f7', width=1.5)), row=3, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="var(--inst-danger)", row=3, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="var(--inst-success)", row=3, col=1)

    fig.update_xaxes(range=[rth_start_dt, rth_end_dt], fixedrange=True, gridcolor='rgba(128,128,128,0.2)')
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                      margin=dict(l=40, r=40, t=30, b=40), xaxis_rangeslider_visible=False, showlegend=False,
                      hovermode="x unified", font=dict(family="var(--font-data)", size=12, color="var(--inst-text-main)"),
                      uirevision=updated_str)

    return fig, time_str, status_html, next_info, updated_str, vix_pct, therm_color, vix_display, guardrails, oracle_html, "NEUTRAL", macro_style

if __name__ == '__main__':
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
    app.layout = render()
    app.run_server(debug=True, port=8050)