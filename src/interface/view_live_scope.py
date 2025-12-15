import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
import pytz
import sys
import duckdb
from pathlib import Path

# ==============================================================================
# 1. SETUP & CONFIG
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ==============================================================================
# 2. MARKET SCHEDULE LOGIC
# ==============================================================================
HOLIDAYS_2025 = {
    "2025-01-01": "New Year's Day", "2025-01-20": "MLK Jr. Day",
    "2025-02-17": "Presidents Day", "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence Day", "2025-09-01": "Labor Day",
    "2025-11-27": "Thanksgiving", "2025-12-25": "Christmas Day"
}

EARLY_CLOSES_2025 = {
    "2025-07-03": time(13, 0), "2025-11-28": time(13, 0), "2025-12-24": time(13, 0)
}
# ... (imports remain the same)

def render():
    return dbc.Container([
        # --- ROW 1: MAGITEK COMMAND DECK ---
        dbc.Row([
            dbc.Col([
                html.H2("ATB SCOPE COMMAND", className="magitek-h2"),
                html.P("MAGITEK VISUAL INTERFACE | XSP NATIVE | VIX REGIME", className="magitek-note")
            ], width=7),
            
            dbc.Col([
                # ... (Clock logic remains, update specific styles to use classes where possible)
                # For brevity, retaining logic but assuming CSS classes handle fonts now
                dbc.Row([
                    dbc.Col([
                        html.Div("DATA SNAPSHOT:", className="text-end small fw-bold text-muted"),
                        html.Div(id="data-freshness", className="text-end fw-bold text-warning fs-4"),
                        dbc.Button("↻ REFRESH", id='btn-manual-refresh', color="primary", size="sm", className="float-end mt-2")
                    ], width=4),
                    dbc.Col([
                        html.H4(id='live-clock-time', className="mb-0 text-end fw-bold text-warning"),
                        html.Div(id='live-market-status', className="text-end"),
                        html.Div(id='live-next-day', className="text-end small text-muted")
                    ], width=8)
                ])
            ], width=5, className="align-self-center")
        ], className="mb-2 pb-2 card", style={"border": "2px solid #b5b8b9"}), # Reusing card style manually or wrapping in Card

        # ... (Rest of layout using dbc.Card and dbc.CardHeader)
    ], fluid=True, className="px-0")

def get_market_status():
    """
    Calculates current status (OPEN/CLOSED) and Next Market Day.
    """
    now_ny = datetime.now(config.TZ_NY)
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = time(16, 0)
    
    if today_str in EARLY_CLOSES_2025:
        market_close = EARLY_CLOSES_2025[today_str]

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS_2025
    is_active_hours = market_open <= current_time < market_close
    
    status_text = "CLOSED"
    status_color = "#e74c3c" # Red
    reason = ""

    if is_holiday: reason = f"({HOLIDAYS_2025[today_str]})"
    elif is_weekend: reason = "(WEEKEND)"
    elif is_active_hours:
        status_text = "OPEN"
        status_color = "#00bc8c" # Green
        reason = "(ACTIVE)"
    elif current_time < market_open: reason = "(PRE-MARKET)"
    else: reason = "(POST-MARKET)"

    status_html = html.Span([
        html.Span(f"STATUS: {status_text}", style={'color': status_color, 'fontWeight': 'bold', 'fontFamily': "'VT323', monospace", 'fontSize': '1.2rem'}),
        html.Span(f" {reason}", className="text-white small ms-2", style={'fontFamily': "'VT323', monospace"})
    ])

    # Next Market Day
    next_date = now_ny.date() + timedelta(days=1)
    while True:
        d_str = next_date.strftime("%Y-%m-%d")
        if next_date.weekday() < 5 and d_str not in HOLIDAYS_2025:
            break
        next_date += timedelta(days=1)
        
    next_day_str = f"NEXT: {next_date.strftime('%A, %b %d')}"
    return status_html, next_day_str

# ==============================================================================
# 3. DATA HARVESTER (LAST KNOWN STATE)
# ==============================================================================
def to_wall_clock(series):
    if series.empty: return series
    if series.dt.tz is None:
        series = series.dt.tz_localize('UTC')
    else:
        series = series.dt.tz_convert('UTC')
    series = series.dt.tz_convert(config.TZ_LOCAL)
    return series.dt.tz_localize(None)

def fetch_hud_data():
    """
    Smart Fetch: Looks for the LATEST available session in the DB.
    """
    if not config.DB_FILE.exists(): return None, None, None, "DB NOT FOUND"
    
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        max_ts = con.execute(f"SELECT MAX(datetime_utc) FROM {config.TBL_INDICES} WHERE ticker = 'XSP'").fetchone()[0]
        if not max_ts:
            con.close()
            return None, None, None, "NO DATA IN VAULT"
            
        target_date = pd.to_datetime(max_ts).date()
        
        s_str = f"{target_date} 00:00:00"
        e_str = f"{target_date} 23:59:59"

        # FETCH XSP
        xsp = con.execute(f"""
            SELECT datetime_utc, open, high, low, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'XSP' 
            AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}'
            ORDER BY datetime_utc ASC
        """).df()
        
        # FETCH VIX 
        vix = con.execute(f"""
            SELECT datetime_utc, close 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'VIX' 
            AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}'
            ORDER BY datetime_utc ASC
        """).df()
        
        # VIX MACRO (30D Lookback)
        lookback_start = (target_date - timedelta(days=30)).strftime('%Y-%m-%d')
        vix_stats = con.execute(f"""
            SELECT MIN(close), MAX(close) 
            FROM {config.TBL_INDICES} 
            WHERE ticker = 'VIX' 
            AND datetime_utc >= '{lookback_start}'
        """).fetchone()
        
        con.close()
        
        if not xsp.empty:
            xsp['datetime_utc'] = pd.to_datetime(xsp['datetime_utc'])
            xsp['datetime_local'] = to_wall_clock(xsp['datetime_utc'])
            xsp['sma_20'] = xsp['close'].rolling(20).mean()
            xsp['sma_50'] = xsp['close'].rolling(50).mean()
        
        if not vix.empty:
            vix['datetime_utc'] = pd.to_datetime(vix['datetime_utc'])
            vix['datetime_local'] = to_wall_clock(vix['datetime_utc'])

        # "Data As Of" String
        last_update_str = "N/A"
        if not xsp.empty:
            last_dt = xsp.iloc[-1]['datetime_local']
            last_update_str = last_dt.strftime('%m/%d %H:%M')

        return xsp, vix, vix_stats, last_update_str

    except Exception as e:
        print(f"HUD Error: {e}")
        return None, None, None, "ERROR"

def analyze_situation(xsp, vix, vix_stats):
    alerts = []
    regime_color = 'rgba(0,0,0,0)'
    orb_lines = None
    
    if xsp is None or xsp.empty:
        return alerts, regime_color, orb_lines, 0, 0
    
    open_time = xsp.iloc[0]['datetime_local']
    orb_end = open_time + timedelta(minutes=30)
    orb_df = xsp[xsp['datetime_local'] <= orb_end]
    if not orb_df.empty:
        orb_h, orb_l = orb_df['high'].max(), orb_df['low'].min()
        orb_lines = (orb_h, orb_l)
        if (orb_h - orb_l) < 0.50: alerts.append("⚠️ DEAD AIR (WAIT)")
    
    if 'sma_20' in xsp.columns and pd.notnull(xsp.iloc[-1]['sma_20']):
        if abs(xsp.iloc[-1]['close'] - xsp.iloc[-1]['sma_20']) > 2.0: alerts.append("🔥 LIMIT BREAK (EXT)")

    curr_vix, vix_pct = 0, 0
    if vix is not None and not vix.empty:
        curr_vix = vix.iloc[-1]['close']
        v_min, v_max = vix_stats if vix_stats else (12, 20)
        vix_pct = min(max(((curr_vix - v_min) / (v_max - v_min)) * 100, 0), 100)
        
        if vix_pct < 10: alerts.append("🛑 VIX FLOOR (RISK)")
        if curr_vix > 20: regime_color = 'rgba(50, 0, 0, 0.2)'
        elif curr_vix < 15: regime_color = 'rgba(0, 50, 0, 0.2)'
        else: regime_color = 'rgba(50, 50, 50, 0.1)'

    return alerts, regime_color, orb_lines, curr_vix, vix_pct

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
# MAGITEK THEME STYLES
STYLE_MAGITEK_WINDOW = {
    "backgroundColor": "#283878", # FF Blue
    "border": "2px solid #b5b8b9", # Silver Frame
    "borderRadius": "4px",
    "color": "#f3f5f9", # White Text
    "padding": "10px",
    "boxShadow": "0px 0px 10px rgba(0,0,0,0.5)"
}

STYLE_FONT_HEADER = {
    "fontFamily": "'VT323', monospace",
    "letterSpacing": "2px",
    "textShadow": "2px 2px #000"
}

STYLE_FONT_MONO = {
    "fontFamily": "'VT323', monospace",
    "fontSize": "1.1rem"
}

def render():
    return dbc.Container([
        # --- ROW 1: MAGITEK COMMAND DECK ---
        dbc.Row([
            dbc.Col([
                html.H2("ATB SCOPE COMMAND", className="fw-bold text-white mb-0", style=STYLE_FONT_HEADER),
                html.P("MAGITEK VISUAL INTERFACE | XSP NATIVE | VIX REGIME", className="text-info lead mb-0", style=STYLE_FONT_MONO)
            ], width=7),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        # DATA SNAPSHOT BLOCK
                        html.Div("DATA SNAPSHOT:", className="text-end small fw-bold", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"}),
                        html.Div(id="data-freshness", className="text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}),
                        dbc.Button("↻ REFRESH", id='btn-manual-refresh', color="primary", size="sm", className="float-end mt-2", style=STYLE_FONT_MONO)
                    ], width=4),
                    dbc.Col([
                        # CLOCK/STATUS BLOCK
                        html.H4(id='live-clock-time', className="mb-0 text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "textShadow": "1px 1px #000"}),
                        html.Div(id='live-market-status', className="text-end", style=STYLE_FONT_MONO),
                        html.Div(id='live-next-day', className="text-end small", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"})
                    ], width=8)
                ])
            ], width=5, className="align-self-center")
        ], className="mb-2 pb-2", style=STYLE_MAGITEK_WINDOW),

        # --- ROW 2: TACTICAL STRIP ---
        dbc.Row([
            # VIX THERMOMETER
            dbc.Col([
                dbc.Row([
                    dbc.Col(html.Label("VIX RISK:", className="fw-bold text-end pe-2", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}), width=3),
                    dbc.Col(dbc.Progress(id="vix-thermometer", value=50, color="warning", className="mt-1", style={"height": "16px", "border": "1px solid #fff"}), width=6),
                    dbc.Col(html.Span(id="vix-val-text", className="ps-2", style={"color": "#fff", "fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}), width=3),
                ], className="g-0 align-items-center")
            ], width=4, className="border-end border-secondary"),
            
            # ALERT FEED
            dbc.Col([
                html.Div(id="hud-alerts", className="text-start d-flex align-items-center h-100 ps-3", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem"})
            ], width=8)
            
        ], className="py-2 mb-1", style=STYLE_MAGITEK_WINDOW),

        # --- ROW 3: MAIN SCOPE ---
        dbc.Row([
            dbc.Col([
                # Chart Container with Border
                html.Div([
                    dcc.Graph(id='live-scope-chart', style={'height': '80vh'}, config={'displayModeBar': False})
                ], style={"border": "2px solid #b5b8b9", "borderRadius": "4px", "padding": "2px", "backgroundColor": "black"})
            ], width=12)
        ], className="g-0"),

        # Interval set to 10s to reduce load and flicker
        dcc.Interval(id='scope-heartbeat', interval=10*1000, n_intervals=0)
    ], fluid=True, className="px-0")

# ==============================================================================
# 5. CALLBACKS
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
     Output('hud-alerts', 'children')],
    [Input('scope-heartbeat', 'n_intervals'),
     Input('btn-manual-refresh', 'n_clicks')]
)
def update_hud(n, manual_click):
    # 1. FETCH & ANALYZE
    xsp, vix, v_stats, last_update = fetch_hud_data()
    alerts, bg_color, orb, curr_vix, vix_pct = analyze_situation(xsp, vix, v_stats)
    
    # 2. STATUS & CLOCK
    tz_local = getattr(config, 'TZ_LOCAL', pytz.timezone('US/Pacific'))
    now_local = datetime.now(tz_local)
    time_str = now_local.strftime("%m/%d/%y | %I:%M:%S %p")
    status_html, next_day_str = get_market_status()

    # 3. CHART
    fig = go.Figure()
    if xsp is not None and not xsp.empty:
        fig.add_trace(go.Candlestick(x=xsp['datetime_local'], open=xsp['open'], high=xsp['high'], low=xsp['low'], close=xsp['close'], name="XSP"))
        if 'sma_50' in xsp.columns:
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['sma_50'], mode='lines', name='FRACTAL (50)', line=dict(color='#ff9f43', width=2)))
        
        if orb:
            h, l = orb
            fig.add_hline(y=h, line_dash="dash", line_color="#00bc8c")
            fig.add_hline(y=l, line_dash="dash", line_color="#e74c3c")
            t0 = xsp.iloc[0]['datetime_local']
            t30 = t0 + timedelta(minutes=30)
            fig.add_shape(type="rect", x0=t0, y0=l, x1=t30, y1=h, fillcolor="gray", opacity=0.15, line_width=0, layer="below")
    else:
        # Empty State
        fig.add_annotation(text="CONNECTING TO CRYSTAL...", font=dict(color="#fde722", size=24, family="Monospace"), showarrow=False)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='black',
        plot_bgcolor=bg_color,
        margin=dict(l=50, r=50, t=10, b=30),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        font=dict(family="'VT323', monospace", size=14, color="#f3f5f9") # Magitek Font for Chart
    )

    # 4. ALERTS & METRICS
    # Badges using Magitek styling implicitly via Bootstrap, but we add custom text
    badges = [dbc.Badge("SYSTEM NORMAL", color="success", className="me-2", style={"fontFamily": "'VT323', monospace", "fontSize": "1rem", "border": "1px solid white"})] 
    if alerts:
        badges = [dbc.Badge(a, color="danger" if "FIRE" in a or "FLOOR" in a else "warning", className="me-2", style={"fontFamily": "'VT323', monospace", "fontSize": "1rem", "border": "1px solid white", "color": "black" if "WAIT" in a else "white"}) for a in alerts]
    
    therm_color = "danger" if vix_pct > 70 else "info" if vix_pct < 20 else "success"

    return fig, time_str, status_html, next_day_str, last_update, vix_pct, therm_color, f"{curr_vix:.2f} ({int(vix_pct)}%)", badges