import sys
import os
import dash
from dash import dcc, html, Input, Output, register_page, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

# ==============================================================================
# 2. MPA PAGE REGISTRATION
# ==============================================================================
register_page(__name__, path='/live', name='Live Ops')
logger = get_logger("LiveOps")

# ==============================================================================
# 3. GLOBAL STATE (Caching)
# ==============================================================================
# We rely on config.GLOBAL_SESSION for the network identity.
# Cache is local to this tool.
_CACHE = {
    "data": (None, None), # (spx_ohlc, vix_close)
    "last_updated": None
}

# ==============================================================================
# 4. HELPER FUNCTIONS
# ==============================================================================
def fetch_live_data(force_refresh=False):
    """
    Fetches 5-minute bars for SPX and VIX.
    Uses Caching + Global Session to prevent IP Bans.
    """
    global _CACHE
    
    # 1. Cache Check
    now = datetime.now()
    if not force_refresh and _CACHE['data'][0] is not None and _CACHE['last_updated']:
        delta = (now - _CACHE['last_updated']).total_seconds()
        # Cache for 60 seconds to prevent button spamming
        if delta < 60: 
            return _CACHE['data']

    try:
        # 2. Batch Download using GLOBAL SESSION
        # Using 5d to ensure we get data even if market just opened
        df = yf.download(
            ['^GSPC', '^VIX'], 
            period='5d', 
            interval='5m', 
            progress=False, 
            group_by='ticker', 
            session=config.GLOBAL_SESSION # <--- The Pro Move
        )
        
        if df.empty: return None, None
        
        # 3. Extract SPX (Handle MultiIndex safely)
        if '^GSPC' in df.columns:
            spx_df = df['^GSPC']
        else:
            return None, None 
            
        spx_ohlc = spx_df[['Open', 'High', 'Low', 'Close']].dropna()
        
        # 4. Extract VIX
        if '^VIX' in df.columns:
            vix_close = df['^VIX']['Close'].dropna().iloc[-1]
        else:
            vix_close = 0.0

        # --- TIMEZONE LAW ENFORCEMENT ---
        # A. Ensure NY Time (Exchange Time)
        if spx_ohlc.index.tz is None:
            spx_ohlc.index = spx_ohlc.index.tz_localize(config.TZ_NY)
        else:
            spx_ohlc.index = spx_ohlc.index.tz_convert(config.TZ_NY)
            
        # Filter for "Today" (Last 24h of trading sessions) to keep chart clean
        cutoff = spx_ohlc.index[-1] - timedelta(days=1)
        spx_ohlc = spx_ohlc[spx_ohlc.index > cutoff]

        # B. Convert to LOCAL (Glass) for Display
        spx_ohlc.index = spx_ohlc.index.tz_convert(config.TZ_LOCAL)

        # Update Cache
        _CACHE['data'] = (spx_ohlc, float(vix_close))
        _CACHE['last_updated'] = now
        
        return spx_ohlc, float(vix_close)
        
    except Exception as e:
        logger.error(f"Live Data Error: {e}")
        # Return stale data if possible
        return _CACHE['data'] if _CACHE['data'][0] is not None else (None, None)

# ==============================================================================
# 5. LAYOUT
# ==============================================================================
layout = dbc.Container([
    
    # HEADER
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 5", className="text-muted mb-0"),
            html.H2("LIVE OPERATIONS CENTER", className="display-6 fw-bold text-danger"),
            html.Hr(className="my-2")
        ], width=8),
        
        # STATUS BADGE
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("DATA FEED (YF)", className="text-muted small mb-0"),
                    html.H4([
                        dbc.Badge("● LIVE (5m)", color="success", className="me-2", id="live-status-badge"),
                        html.Span(id="live-clock", className="text-white small")
                    ], className="mt-1")
                ], className="p-2 text-end")
            ], className="border-0 bg-transparent") 
        ], width=4)
    ], className="mb-4"),

    # MAIN COCKPIT
    dbc.Row([
        # LEFT: The Chart (Windshield)
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([
                    html.I(className="bi bi-activity me-2"),
                    "Intraday Price Action (S&P 500)"
                ]),
                dbc.CardBody([
                    dcc.Graph(id='live-chart', style={'height': '600px'}, config={'displayModeBar': False})
                ], className="p-0")
            ], className="shadow mb-4")
        ], width=12, lg=8),

        # RIGHT: Telemetry (Dashboard)
        dbc.Col([
            # 1. TARGET LOCK
            dbc.Card([
                dbc.CardHeader("🎯 Target Acquisition"),
                dbc.CardBody([
                    html.Label("Projected ATM Strike (XSP)", className="text-danger fw-bold"),
                    html.H2("----", id='live-target-strike', className="text-white metric-value"),
                    html.Hr(className="border-secondary"),
                    dbc.Row([
                        dbc.Col([html.Small("SPX Price", className="text-muted"), html.H5("--", id='live-spx-price', className="text-info")]),
                        dbc.Col([html.Small("VIX Level", className="text-muted"), html.H5("--", id='live-vix-level', className="text-warning")]),
                    ])
                ])
            ], className="mb-3 shadow"),

            # 2. P&L ENGINE
            dbc.Card([
                dbc.CardHeader("💰 Option Chain Status"),
                dbc.CardBody([
                    html.Div([
                        html.I(className="bi bi-exclamation-triangle text-warning me-2"),
                        "Live Options Data Unavailable via YF API"
                    ], className="alert alert-dark small text-center"),
                    
                    dbc.Row([
                        dbc.Col([html.H6("Est. Delta"), html.H3("0.50", className="text-muted metric-value")], width=6),
                        dbc.Col([html.H6("Data Source"), html.H3("DELAYED", className="text-muted metric-value")], width=6),
                    ]),
                    dbc.Progress(value=100, color="secondary", className="mt-3", striped=True, style={"height": "5px"})
                ])
            ], className="mb-3 shadow"),

            # 3. CONTROLS
            dbc.Card([
                dbc.CardHeader("⚙️ Manual Override"),
                dbc.CardBody([
                    dbc.Button("🔄 Force Refresh Data", id='live-refresh-btn', color="secondary", outline=True, size="sm", className="w-100")
                ])
            ], className="shadow")
        ], width=12, lg=4)
    ]),

    # HEARTBEAT (5 Minutes)
    dcc.Interval(id='live-interval', interval=300*1000, n_intervals=0)

], fluid=True)

# ==============================================================================
# 6. CALLBACKS
# ==============================================================================
@callback(
    [Output('live-chart', 'figure'),
     Output('live-target-strike', 'children'),
     Output('live-spx-price', 'children'),
     Output('live-vix-level', 'children'),
     Output('live-clock', 'children')],
    [Input('live-interval', 'n_intervals'),
     Input('live-refresh-btn', 'n_clicks')]
)
def update_live_cockpit(n, refresh_clicks):
    # Determine if this was a manual refresh
    trigger = ctx.triggered_id
    is_manual = (trigger == 'live-refresh-btn')
    
    # 1. Clock
    now = datetime.now(config.TZ_LOCAL)
    time_str = now.strftime("%H:%M:%S PST")
    
    # 2. Fetch Data (Cached unless manual force)
    spx_ohlc, current_vix = fetch_live_data(force_refresh=is_manual)
    
    if spx_ohlc is None or spx_ohlc.empty:
        fig = go.Figure(layout=dict(template='plotly_dark', title="Waiting for Market Data..."))
        # Keep old values if cache exists but is empty/failed
        return fig, "----", "No Data", "No Data", time_str

    # 3. Process Metrics
    current_spx = spx_ohlc['Close'].iloc[-1]
    # Simple XSP logic: SPX / 10
    xsp_ref_price = current_spx / 10.0
    atm_strike = round(xsp_ref_price) 
    
    # 4. Build Chart
    fig = go.Figure()
    
    # SPX Candles
    fig.add_trace(go.Candlestick(
        x=spx_ohlc.index,
        open=spx_ohlc['Open'], high=spx_ohlc['High'],
        low=spx_ohlc['Low'], close=spx_ohlc['Close'],
        name="S&P 500"
    ))
    
    # ATM Line (Projected onto SPX scale)
    strike_line_spx = atm_strike * 10
    fig.add_hline(y=strike_line_spx, line_dash="dash", line_color="#00E676", annotation_text="ATM TARGET")

    fig.update_layout(
        template="plotly_dark",
        height=600,
        title=f"S&P 500 Intraday (5m) | {spx_ohlc.index[-1].strftime('%H:%M PST')}",
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis_rangeslider_visible=False,
        showlegend=False
    )

    return fig, f"{atm_strike}", f"{current_spx:.2f}", f"{current_vix:.2f}", time_str