import dash
from dash import dcc, html, Input, Output, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz
import logging

# ==========================================
# 1. SETUP
# ==========================================
register_page(__name__, path='/live', name='Live Ops')

logger = logging.getLogger("LiveOps")
TZ_LOCAL = pytz.timezone('US/Pacific')
TZ_NY = pytz.timezone('America/New_York')

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================
def fetch_live_data():
    """
    Fetches the last 1 day of 5-minute bars for SPX and VIX.
    """
    try:
        # Fetch both tickers at once
        df = yf.download(['^GSPC', '^VIX'], period='1d', interval='5m', progress=False)
        
        if df.empty: return None, None
        
        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            spx = df['Close']['^GSPC'].dropna()
            vix = df['Close']['^VIX'].dropna()
            
            # Get full OHLC for SPX chart
            spx_ohlc = pd.DataFrame({
                'Open': df['Open']['^GSPC'],
                'High': df['High']['^GSPC'],
                'Low': df['Low']['^GSPC'],
                'Close': df['Close']['^GSPC']
            }).dropna()
        else:
            # Fallback if single ticker (rare)
            return None, None

        return spx_ohlc, vix.iloc[-1]
        
    except Exception as e:
        logger.error(f"Live Data Error: {e}")
        return None, None

# ==========================================
# 3. LAYOUT
# ==========================================
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

            # 2. P&L ENGINE (Placeholder for now)
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

    # HEARTBEAT (5 Minutes = 300,000 ms)
    dcc.Interval(id='live-interval', interval=300*1000, n_intervals=0)

], fluid=True)

# ==========================================
# 4. LOGIC
# ==========================================
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
    # 1. Clock
    now = datetime.now(TZ_LOCAL)
    time_str = now.strftime("%H:%M:%S PST")
    
    # 2. Fetch Data
    spx_ohlc, current_vix = fetch_live_data()
    
    if spx_ohlc is None or spx_ohlc.empty:
        # Empty State
        fig = go.Figure(layout=dict(template='plotly_dark', title="Waiting for Market Data..."))
        return fig, "----", "No Data", "No Data", time_str

    # 3. Process Metrics
    current_spx = spx_ohlc['Close'].iloc[-1]
    
    # Calculate XSP Equivalent ATM Strike (SPX / 10)
    # XSP strikes are integers (e.g., 580, 581). SPX is ~5800.
    # XSP Price = SPX / 10.
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
    
    # ATM Line (Theoretical Target)
    # We project the strike back to SPX terms (Strike * 10) for the visual
    strike_line_spx = atm_strike * 10
    fig.add_hline(y=strike_line_spx, line_dash="dash", line_color="#00E676", annotation_text="ATM TARGET")

    fig.update_layout(
        template="plotly_dark",
        height=600,
        title=f"S&P 500 Intraday (5m) | {spx_ohlc.index[-1].strftime('%H:%M')}",
        margin=dict(l=40, r=40, t=40, b=40),
        xaxis_rangeslider_visible=False,
        showlegend=False
    )

    return fig, f"{atm_strike}", f"{current_spx:.2f}", f"{current_vix:.2f}", time_str