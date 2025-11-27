import sys
import os
import dash
from dash import dcc, html, Input, Output, register_page, callback, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
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
register_page(__name__, path='/', name='Command Center')
logger = get_logger("CommandCenter")

# ==============================================================================
# 3. GLOBAL STATE (Caching)
# ==============================================================================
_CACHE = {
    "live_data": (None, None),
    "market_snapshot": None,
    "news_global": [],
    "news_spx": [],
    "last_updated": None
}

# ==============================================================================
# 4. HELPER FUNCTIONS
# ==============================================================================
def parse_rss(url):
    """Robust RSS parser for Yahoo Finance feeds."""
    items = []
    try:
        # Use Global Session to avoid rate limits
        resp = config.GLOBAL_SESSION.get(url, timeout=5)
        if resp.status_code == 200:
            # Fix: Handle potential encoding issues
            content = resp.content
            root = ET.fromstring(content)
            
            # Yahoo RSS namespace handling can be tricky, so we search broadly
            for item in root.findall('.//item')[:6]: # Top 6 stories
                try:
                    title = item.find('title').text
                    link = item.find('link').text
                    pub_date = item.find('pubDate').text
                    
                    # Date Parsing & Localization
                    dt = pd.to_datetime(pub_date)
                    if dt.tzinfo is None: dt = dt.tz_localize(config.TZ_UTC)
                    time_str = dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
                    
                    items.append({'title': title, 'link': link, 'time': time_str})
                except: continue
    except Exception as e:
        logger.warning(f"RSS Fail ({url}): {e}")
    return items

def fetch_data_bundle(force_refresh=False):
    global _CACHE
    now = datetime.now()
    
    # 1. Cache Check (60s throttle)
    if not force_refresh and _CACHE['last_updated']:
        delta = (now - _CACHE['last_updated']).total_seconds()
        if delta < 60: return _CACHE

    # --- A. LIVE INTRADAY ---
    try:
        # 5-day buffer ensures we have data even on Monday mornings
        df_live = yf.download(['^GSPC', '^VIX'], period='5d', interval='5m', progress=False, group_by='ticker', session=config.GLOBAL_SESSION)
        
        if '^GSPC' in df_live.columns:
            spx_ohlc = df_live['^GSPC'][['Open', 'High', 'Low', 'Close']].dropna()
            # TZ Enforcement: NY -> UTC -> Local
            if spx_ohlc.index.tz is None: spx_ohlc.index = spx_ohlc.index.tz_localize(config.TZ_NY)
            else: spx_ohlc.index = spx_ohlc.index.tz_convert(config.TZ_NY)
            
            # Filter to "Today" (Last 24h rolling window)
            cutoff = spx_ohlc.index[-1] - timedelta(days=1)
            spx_ohlc = spx_ohlc[spx_ohlc.index > cutoff]
            spx_ohlc.index = spx_ohlc.index.tz_convert(config.TZ_LOCAL)
        else:
            spx_ohlc = None

        vix_close = df_live['^VIX']['Close'].dropna().iloc[-1] if '^VIX' in df_live.columns else 0.0
        _CACHE['live_data'] = (spx_ohlc, float(vix_close))
    except Exception as e:
        logger.error(f"Live Data Fetch Fail: {e}")

    # --- B. MARKET SNAPSHOT ---
    try:
        tickers = ['^GSPC', '^DJI', '^IXIC', '^VIX']
        names = {'^GSPC': 'S&P 500', '^DJI': 'Dow Jones', '^IXIC': 'Nasdaq', '^VIX': 'VIX'}
        df_daily = yf.download(tickers, period="5d", interval="1d", progress=False, group_by='ticker', session=config.GLOBAL_SESSION)
        
        snapshot = {}
        for sym in tickers:
            try:
                data_src = df_daily[sym] if len(tickers) > 1 else df_daily
                closes = data_src['Close'].dropna()
                if len(closes) < 2: continue
                
                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                change = price - prev
                pct = (change/prev)*100
                
                snapshot[sym] = {
                    'name': names[sym], 'price': price, 'change': change, 'pct': pct,
                    'color': '#00E676' if change >= 0 else '#FF1744'
                }
            except: continue
        _CACHE['market_snapshot'] = snapshot
    except: pass

    # --- C. NEWS FEEDS (UPDATED) ---
    # 1. Global Wire: The Main Yahoo Finance "Top Stories"
    _CACHE['news_global'] = parse_rss("https://finance.yahoo.com/rss/topstories")
    
    # 2. SPX Intelligence: Using ^GSPC (The Main Index) instead of ^XSP
    # This captures all major market-moving news tagged to the S&P 500
    _CACHE['news_spx'] = parse_rss("https://finance.yahoo.com/rss/headline?s=^GSPC")

    _CACHE['last_updated'] = now
    return _CACHE

def create_gauge(val):
    if val < 15: label, color = "GREED", "#00C853"
    elif val < 20: label, color = "NORMAL", "#00E5FF"
    elif val < 30: label, color = "FEAR", "#FF9100"
    else: label, color = "PANIC", "#FF1744"
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number", value = val,
        title = {'text': label, 'font': {'size': 16, 'color': color}},
        gauge = {'axis': {'range': [10, 45]}, 'bar': {'color': color}, 'bgcolor': "white"}
    ))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', font={'color': "white"}, height=200, margin=dict(l=20, r=20, t=20, b=20))
    return fig

# ==============================================================================
# 5. LAYOUT
# ==============================================================================
layout = dbc.Container([
    
    # 1. HEADER & STATUS
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 5", className="text-muted mb-0"),
            html.H2("COMMAND CENTER", className="display-6 fw-bold text-light"),
        ], width=8),
        dbc.Col([
            html.H4(id='cmd-clock', className="text-end text-info mt-2")
        ], width=4)
    ], className="mb-3"),

    # 2. TICKER TAPE
    html.Div(id='cmd-ticker-tape', className="mb-3"),

    # 3. MAIN DASHBOARD
    dbc.Row([
        # LEFT: Live Chart
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-graph-up me-2"), "Live Price Action (5m)"]),
                dbc.CardBody([dcc.Graph(id='cmd-main-chart', style={'height': '500px'}, config={'displayModeBar': False})], className="p-0")
            ], className="shadow h-100")
        ], width=12, lg=8),

        # RIGHT: VIX & Targets
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("🎯 Intraday Target (XSP)"),
                dbc.CardBody([
                    html.H1(id='cmd-target-strike', className="text-center text-warning display-4 fw-bold"),
                    html.Div("ATM Projection", className="text-center text-muted small")
                ])
            ], className="shadow mb-3"),

            dbc.Card([
                dbc.CardHeader("Volatility Regime"),
                dbc.CardBody([dcc.Graph(id='cmd-vix-gauge', style={'height': '200px'})], className="p-0")
            ], className="shadow mb-3"),

            # Manual Refresh Button (Renamed to avoid conflicts)
            dbc.Button("🔄 Force Sync", id='cc-refresh-btn', color="secondary", outline=True, className="w-100")

        ], width=12, lg=4)
    ], className="mb-4"),

    # 4. NEWS FEEDS (Split Row)
    dbc.Row([
        # Col 1: Global Wire
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-globe me-2"), "Global Wire (Top Stories)"]),
                dbc.CardBody(id='cmd-news-global', style={'maxHeight': '300px', 'overflowY': 'auto'})
            ], className="shadow h-100")
        ], width=12, lg=6),

        # Col 2: SPX Wire
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-cpu me-2"), "S&P 500 Intelligence"]),
                dbc.CardBody(id='cmd-news-spx', style={'maxHeight': '300px', 'overflowY': 'auto'})
            ], className="shadow h-100")
        ], width=12, lg=6)
    ]),

    # 5. Heartbeat
    dcc.Interval(id='cmd-interval', interval=60*1000, n_intervals=0)

], fluid=True)

# ==============================================================================
# 6. CALLBACKS
# ==============================================================================
@callback(
    [Output('cmd-main-chart', 'figure'),
     Output('cmd-ticker-tape', 'children'),
     Output('cmd-target-strike', 'children'),
     Output('cmd-vix-gauge', 'figure'),
     Output('cmd-news-global', 'children'),
     Output('cmd-news-spx', 'children'),
     Output('cmd-clock', 'children')],
    [Input('cmd-interval', 'n_intervals'),
     Input('cc-refresh-btn', 'n_clicks')] # Updated ID here
)
def update_command_center(n, refresh_clicks):
    trigger = ctx.triggered_id
    is_manual = (trigger == 'cc-refresh-btn')
    
    time_str = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S PST")
    data = fetch_data_bundle(force_refresh=is_manual)
    
    # --- 1. CHART & TARGETS ---
    spx_ohlc, vix_live = data.get('live_data', (None, None))
    
    if spx_ohlc is not None and not spx_ohlc.empty:
        curr_spx = spx_ohlc['Close'].iloc[-1]
        atm_strike = round(curr_spx / 10.0)
        
        fig_chart = go.Figure(go.Candlestick(
            x=spx_ohlc.index, open=spx_ohlc['Open'], high=spx_ohlc['High'],
            low=spx_ohlc['Low'], close=spx_ohlc['Close'], name="SPX"
        ))
        fig_chart.add_hline(y=atm_strike*10, line_dash="dash", line_color="#00E676", annotation_text="ATM")
        fig_chart.update_layout(template="plotly_dark", margin=dict(l=40, r=40, t=30, b=30), showlegend=False, xaxis_rangeslider_visible=False)
        target_text = f"{atm_strike}"
    else:
        fig_chart = go.Figure(layout=dict(template='plotly_dark', title="Waiting for Data..."))
        target_text = "----"

    # --- 2. TICKER TAPE ---
    snapshot = data.get('market_snapshot', {})
    tape_cols = []
    if snapshot:
        for sym in ['^GSPC', '^DJI', '^IXIC', '^VIX']:
            if sym in snapshot:
                d = snapshot[sym]
                tape_cols.append(dbc.Col(dbc.Card([
                    dbc.CardBody([
                        html.H6(d['name'], className="text-muted small mb-0"),
                        html.H4(f"{d['price']:,.2f}", className="text-white mb-0"),
                        html.Small(f"{d['pct']:+.2f}%", style={'color': d['color'], 'fontWeight': 'bold'})
                    ], className="p-2")
                ], className="border-secondary"), width=6, lg=3))
    
    # --- 3. GAUGE ---
    vix_val = vix_live if vix_live else (snapshot.get('^VIX', {}).get('price', 20))
    fig_gauge = create_gauge(vix_val)

    # --- 4. NEWS RENDERER ---
    def render_news(items, empty_msg):
        if not items: return [html.Div(empty_msg, className="text-muted small fst-italic")]
        divs = []
        for item in items:
            divs.append(html.Div([
                html.Small(item['time'], className="text-info me-2"),
                html.A(item['title'], href=item['link'], target="_blank", className="text-white text-decoration-none hover-underline"),
                html.Hr(className="my-1 border-secondary")
            ]))
        return divs

    news_global_divs = render_news(data.get('news_global', []), "No global wires found.")
    news_spx_divs = render_news(data.get('news_spx', []), "No S&P 500 specific intel.")

    return fig_chart, dbc.Row(tape_cols, className="g-2"), target_text, fig_gauge, news_global_divs, news_spx_divs, time_str