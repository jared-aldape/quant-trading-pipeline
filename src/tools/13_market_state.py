import sys
import os
import dash
from dash import dcc, html, Input, Output, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
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
register_page(__name__, path='/periscope', name='Periscope')
logger = get_logger("MarketPeriscope")

# ==============================================================================
# 3. GLOBAL STATE (Caching)
# ==============================================================================
# We rely on config.GLOBAL_SESSION for the network identity.
# We keeps the cache local to this tool since the data requirements (Daily)
# are unique to this page.
_CACHE = {
    "data": None,
    "last_updated": None
}

# ==============================================================================
# 4. HELPER FUNCTIONS
# ==============================================================================
def fetch_market_snapshot():
    """
    Fetches market data using Batch Download + Caching + Global Session.
    """
    global _CACHE
    
    # 1. Cache Check (Throttle to 1 request per minute)
    now = datetime.now()
    if _CACHE['data'] and _CACHE['last_updated']:
        delta = (now - _CACHE['last_updated']).total_seconds()
        if delta < 60: 
            return _CACHE['data']

    tickers = ['^GSPC', '^DJI', '^IXIC', '^VIX']
    names = {'^GSPC': 'S&P 500', '^DJI': 'Dow Jones', '^IXIC': 'Nasdaq', '^VIX': 'VIX'}
    data = {}
    
    try:
        # 2. Batch Download using GLOBAL SESSION
        # This makes the request look identical to the Live Ops dashboard
        df = yf.download(
            tickers, 
            period="5d", 
            interval="1d", 
            progress=False, 
            group_by='ticker', 
            session=config.GLOBAL_SESSION # <--- The Pro Move
        )
        
        # 3. Parse Response
        for sym in tickers:
            try:
                # Handle Single Ticker vs Multi-Ticker result structure
                if len(tickers) == 1:
                    closes = df['Close'].dropna()
                else:
                    if sym not in df.columns: continue
                    closes = df[sym]['Close'].dropna()

                if len(closes) < 2: continue
                
                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2])
                change = price - prev
                pct_change = (change / prev) * 100
                
                color = '#00E676' if change >= 0 else '#FF1744'
                
                data[sym] = {
                    'name': names[sym], 
                    'price': price, 
                    'change': change, 
                    'pct': pct_change, 
                    'color': color
                }
            except Exception as e:
                logger.warning(f"Parse error for {sym}: {e}")
                continue

        # 4. Update Cache on Success
        if data:
            _CACHE['data'] = data
            _CACHE['last_updated'] = now
            
    except Exception as e:
        logger.error(f"Snapshot Error: {e}")
        # Return stale data if available
        return _CACHE['data']
        
    return data

def fetch_news():
    news_items = []
    rss_url = "https://finance.yahoo.com/rss/topstories" 
    
    try:
        # Use the GLOBAL SESSION for RSS as well to benefit from the User-Agent
        response = config.GLOBAL_SESSION.get(rss_url, timeout=5)
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            
            for item in root.findall('.//item')[:6]:
                pub_date = item.find('pubDate')
                time_str = "Recent"
                
                if pub_date is not None:
                    try:
                        dt = pd.to_datetime(pub_date.text)
                        if dt.tzinfo is None: dt = dt.tz_localize(config.TZ_UTC)
                        dt_local = dt.astimezone(config.TZ_LOCAL)
                        time_str = dt_local.strftime('%H:%M PST')
                    except: pass
                
                news_items.append({
                    'title': item.find('title').text, 
                    'link': item.find('link').text, 
                    'time': time_str
                })
    except Exception as e:
        logger.warning(f"News Fetch Error: {e}")
        pass
        
    return news_items

def create_gauge(vix_price):
    val = float(vix_price)
    if val < 15: label, color = "EXTREME GREED", "#00C853"
    elif val < 20: label, color = "NORMAL", "#00E5FF"
    elif val < 30: label, color = "FEAR", "#FF9100"
    else: label, color = "EXTREME FEAR", "#FF1744"
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number", 
        value = val,
        title = {'text': label, 'font': {'size': 20, 'color': color}},
        gauge = {'axis': {'range': [10, 45]}, 'bar': {'color': color}, 'bgcolor': "white"}
    ))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', font={'color': "white"}, 
        height=300, margin=dict(l=30, r=30, t=30, b=30)
    )
    return fig

# ==============================================================================
# 5. LAYOUT
# ==============================================================================
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 6", className="text-muted mb-0"),
            html.H2("MARKET PERISCOPE", className="display-6 fw-bold", style={'color': '#20c997'}),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    html.Div(id='peri-indices-row'),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-speedometer2 me-2"), "Volatility Regime"]),
                dbc.CardBody([dcc.Graph(id='peri-gauge')], className="p-0")
            ], className="shadow mb-4")
        ], width=12, lg=6),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader([html.I(className="bi bi-newspaper me-2"), "Global Top Stories"]),
                dbc.CardBody(id='peri-news-feed', style={'maxHeight': '350px', 'overflowY': 'auto'})
            ], className="shadow mb-4")
        ], width=12, lg=6)
    ]),

    # Interval set to 60 seconds
    dcc.Interval(id='peri-interval', interval=60*1000, n_intervals=0)
], fluid=True)

# ==============================================================================
# 6. CALLBACKS
# ==============================================================================
@callback(
    [Output('peri-indices-row', 'children'), Output('peri-gauge', 'figure'), Output('peri-news-feed', 'children')],
    [Input('peri-interval', 'n_intervals')]
)
def update_periscope(n):
    market_data = fetch_market_snapshot()
    news_items = fetch_news()
    
    # 1. INDICES
    if market_data:
        cards = []
        for sym in ['^GSPC', '^DJI', '^IXIC', '^VIX']:
            if sym in market_data:
                d = market_data[sym]
                cards.append(dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6(d['name'], className="text-muted text-uppercase small mb-1"),
                            html.H3(f"{d['price']:,.2f}", className="metric-value text-white"),
                            html.P(f"{d['change']:+.2f} ({d['pct']:+.2f}%)", style={'color': d['color'], 'fontWeight': 'bold', 'marginBottom': 0})
                        ])
                    ], className="mb-3 border-secondary")
                ], width=12, sm=6, lg=3))
        indices_layout = dbc.Row(cards)
        vix_val = market_data.get('^VIX', {}).get('price', 20)
        gauge_fig = create_gauge(vix_val)
    else:
        indices_layout = html.Div("Data Link Offline (Yahoo Rate Limit or Network)", className="text-danger text-center mt-3")
        gauge_fig = go.Figure()

    # 2. NEWS
    news_layout = []
    if news_items:
        for item in news_items:
            news_layout.append(html.Div([
                html.A(item['title'], href=item['link'], target="_blank", className="text-decoration-none fw-bold text-white d-block mb-1", style={'fontSize': '0.95rem'}),
                html.Small(item['time'], className="text-muted"),
                html.Hr(className="border-secondary my-2")
            ]))
    else:
        news_layout = html.Div("Connecting to Wire...", className="text-muted small")

    return indices_layout, gauge_fig, news_layout