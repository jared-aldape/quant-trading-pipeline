import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import pathlib
import sys
import pytz
import calendar

# PATH SETUP
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_forensics as forensics
from src.utils.date_profiles import DATE_PROFILES

TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW ---
        dbc.Row([
            dbc.Col([
                html.H2("FINANCIAL STATISTICS", className="magitek-h2"),
                html.P("CAPITAL ALLOCATION | CALL vs PUT BIAS | PREMIUM BURN", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("METRIC: FINANCIAL HEALTH", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # --- CONTROLS ---
        dbc.Row([
            dbc.Col(dcc.Dropdown(
                id='stats-source',
                options=[{'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'}, {'label': 'SIMULATION', 'value': 'gen'}],
                value='rh', clearable=False, className="mb-3"
            ), width=6),
            dbc.Col(dcc.Dropdown(
                id='stats-profile',
                options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                value='Year To Date', clearable=False, className="mb-3"
            ), width=6)
        ]),

        # --- KPI ROW ---
        dbc.Row(id='stats-kpi-row', className="mb-4"),

        # --- ROW 1: THE SPLIT (Call vs Put) ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("DIRECTIONAL BIAS (THE 75/25 SPLIT)", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-split', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow h-100"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("WIN RATE BY SIDE", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-winrate', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow h-100"), width=6),
        ], className="mb-4"),

        # --- ROW 2: COSTS & STRIKES ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("PREMIUM SPENT PER WEEK (BURN RATE)", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-burn', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("PROFIT BY STRIKE PRICE", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-strike', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow"), width=6),
        ], className="mb-4"),

        # --- ROW 3: EQUITY CURVE ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("PORTFOLIO EQUITY CURVE", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-equity', style={'height': '350px'}, config={'displayModeBar': False}))
            ], className="shadow"), width=12),
        ], className="mb-4"),

    ], fluid=True)

# ==============================================================================
# CALLBACKS
# ==============================================================================
@callback(
    [Output('stats-kpi-row', 'children'),
     Output('stats-chart-split', 'figure'),
     Output('stats-chart-winrate', 'figure'),
     Output('stats-chart-burn', 'figure'),
     Output('stats-chart-strike', 'figure'),
     Output('stats-chart-equity', 'figure')],
    [Input('stats-source', 'value'),
     Input('stats-profile', 'value')]
)
def update_stats(source, profile):
    df = forensics.fetch_scorecard_data(source, profile)
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if df.empty: return [], empty_fig, empty_fig, empty_fig, empty_fig, empty_fig

    # PRE-PROCESS
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    if df['entry_time'].dt.tz is None: df['entry_time'] = df['entry_time'].dt.tz_localize(TZ_UTC)
    df['entry_time'] = df['entry_time'].dt.tz_convert(TZ_PST)
    
    # Extract Type (C/P) and Strike from Ticker (e.g., "XSP 580C...")
    def parse_ticker(t):
        try:
            parts = t.split()
            # Assuming format: "XSP 580C" or similar
            # If simplistic format from reconciler: "XSP 677P 2025-12-10"
            for p in parts:
                if 'C' in p and p[:-1].isdigit(): return 'CALL', int(p[:-1]) # Match "580C"
                if 'P' in p and p[:-1].isdigit(): return 'PUT', int(p[:-1])
                # Reconciler specific format check
                if p.endswith('C'): return 'CALL', float(p[:-1])
                if p.endswith('P'): return 'PUT', float(p[:-1])
            return 'UNK', 0
        except: return 'UNK', 0

    # Logic to handle reconciler format "XSP 677C 2025-..."
    # The reconciler builds ticker as f"{root} {strike}{otype} {expiry}"
    # So "XSP 677.0C 2025-12-10"
    df['Type'] = df['ticker'].apply(lambda x: 'CALL' if 'C ' in x or x.endswith('C') or 'C' in x.split()[1] else ('PUT' if 'P ' in x or x.endswith('P') or 'P' in x.split()[1] else 'UNK'))
    # Rough strike parser
    df['Strike'] = df['ticker'].apply(lambda x: ''.join([c for c in x.split()[1] if c.isdigit() or c=='.']) if len(x.split())>1 else '0')

    # 1. KPIs
    net_pnl = df['pnl'].sum()
    win_rate = len(df[df['pnl']>0]) / len(df) * 100
    pf = df[df['pnl']>0]['pnl'].sum() / abs(df[df['pnl']<0]['pnl'].sum()) if len(df[df['pnl']<0]) > 0 else 0
    
    kpis = [
        dbc.Col(dbc.Card([html.H6("NET PnL"), html.H3(f"${net_pnl:,.2f}", className="text-success" if net_pnl>=0 else "text-danger")], body=True, color="dark", inverse=True)),
        dbc.Col(dbc.Card([html.H6("WIN RATE"), html.H3(f"{win_rate:.1f}%", className="text-info")], body=True, color="dark", inverse=True)),
        dbc.Col(dbc.Card([html.H6("PROFIT FACTOR"), html.H3(f"{pf:.2f}", className="text-warning")], body=True, color="dark", inverse=True)),
        dbc.Col(dbc.Card([html.H6("TOTAL TRADES"), html.H3(f"{len(df)}", className="text-white")], body=True, color="dark", inverse=True)),
    ]

    # 2. SPLIT CHART (PnL by Type)
    split_grp = df.groupby('Type')['pnl'].sum().reset_index()
    fig_split = px.bar(split_grp, x='Type', y='pnl', color='pnl', title="Net PnL by Instrument",
                       color_continuous_scale=['#ff5555', '#333', '#00ff41'])
    fig_split.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")

    # 3. WIN RATE CHART
    wr_grp = df.groupby('Type').apply(lambda x: len(x[x['pnl']>0])/len(x)*100).reset_index(name='WinRate')
    fig_wr = px.bar(wr_grp, x='Type', y='WinRate', title="Win Rate % by Instrument", color='WinRate', range_y=[0, 100])
    fig_wr.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")

    # 4. BURN RATE (Premium Spent per Week)
    df['Week'] = df['entry_time'].dt.to_period('W').astype(str)
    # Estimate cost: entry_price * quantity * 100
    df['Cost'] = df['entry_price'] * df['quantity'] * 100
    burn_grp = df.groupby('Week')['Cost'].sum().reset_index()
    fig_burn = px.bar(burn_grp, x='Week', y='Cost', title="Premium Deployed (Risk On)", color_discrete_sequence=['#f39c12'])
    fig_burn.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")

    # 5. STRIKE PERFORMANCE
    # Filter out weird strikes
    strike_df = df[df['Strike'] != '0'].copy()
    if not strike_df.empty:
        fig_strike = px.scatter(strike_df, x='Strike', y='pnl', color='Type', title="PnL Distribution by Strike",
                                color_discrete_map={'CALL': '#00ff41', 'PUT': '#ff5555'})
        fig_strike.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")
    else:
        fig_strike = empty_fig

    # 6. EQUITY CURVE
    df = df.sort_values('entry_time')
    df['Equity'] = df['pnl'].cumsum()
    fig_eq = px.line(df, x='entry_time', y='Equity', title="Account Growth (Equity Curve)")
    fig_eq.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_eq.update_traces(line_color='#00bc8c', fill='tozeroy')
    fig_eq.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")

    return kpis, fig_split, fig_wr, fig_burn, fig_strike, fig_eq