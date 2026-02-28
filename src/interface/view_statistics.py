import dash
from dash import dcc, html, dash_table, callback, Input, Output, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import duckdb
import pathlib
import sys
import pytz
from datetime import datetime, timedelta
import calendar

# PATH SETUP
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ⚡ PREVENT SILENT CRASHES
try:
    from src.utils.date_profiles import DATE_PROFILES
except ImportError:
    print("⚠️ WARNING: DATE_PROFILES could not be imported.")
    DATE_PROFILES = {"Last 30 Days": None}

TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    INPUT_STYLE = {
        'color': '#000000', 
        'backgroundColor': '#ffffff', 
        'fontFamily': 'monospace',
        'border': '1px solid #ccc'
    }

    return dbc.Container([
        
        # --- TITLE ROW ---
        dbc.Row([
            dbc.Col([
                html.H2("STATISTICAL METRICS", className="fw-bold text-white mb-0"),
                html.P("CAPITAL ALLOCATION | CALL vs PUT BIAS | BURN RATE", className="text-muted small fw-bold mb-0")
            ], width=8),
            
            dbc.Col([
                html.Div("ANALYTICS ENGINE: ACTIVE", className="text-end text-success font-monospace fw-bold"),
                html.Div("COMPANION: TRADE AUDIT", className="text-end text-info font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # --- CONTROLS ---
        dbc.Row([
            dbc.Col([
                html.Label("LEDGER SOURCE", className="small text-muted fw-bold"),
                # ⚡ ALIGNED 3-TIER MENU
                dbc.Select(
                    id='stats-source',
                    options=[
                        {'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'}, 
                        {'label': 'PAPER TRADING (Simulator)', 'value': 'SIM'},
                        {'label': 'BACKTEST (Generator)', 'value': 'BACKTEST'}
                    ],
                    value='BACKTEST', 
                    style=INPUT_STYLE,
                    className="mb-3 text-dark"
                )
            ], width=6),
            dbc.Col([
                html.Label("LOOKBACK PROFILE", className="small text-muted fw-bold"),
                dbc.Select(
                    id='stats-profile',
                    options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                    value='Last 30 Days', 
                    style=INPUT_STYLE,
                    className="mb-3 text-dark"
                )
            ], width=6)
        ]),

        # --- KPI ROW ---
        dbc.Row(id='stats-kpi-row', className="mb-4"),

        # --- ROW 1: THE SPLIT (Call vs Put) ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("DIRECTIONAL BIAS (75/25 SPLIT)", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-split', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary h-100"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("WIN RATE BY INSTRUMENT", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-winrate', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary h-100"), width=6),
        ], className="mb-4"),

        # --- ROW 2: COSTS & STRIKES ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("PREMIUM SPENT PER WEEK (BURN RATE)", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-burn', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary h-100"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("PROFITABILITY BY STRIKE", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-strike', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary h-100"), width=6),
        ], className="mb-4"),

        # --- ROW 3: EQUITY CURVE ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("PORTFOLIO EQUITY GROWTH", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-equity', style={'height': '350px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary"), width=12),
        ], className="mb-4"),

    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 2. CALLBACKS
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
def update_stats(source, profile_name):
    if not source: return [], no_update, no_update, no_update, no_update, no_update
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

    try:
        # ⚡ DIRECT DUCKDB QUERY PROTOCOL
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        try: start_date = DATE_PROFILES[profile_name].start_date
        except: start_date = (datetime.now() - timedelta(days=30)).date()
            
        if hasattr(start_date, 'strftime'): start_str = start_date.strftime('%Y-%m-%d 00:00:00')
        else: start_str = f"{start_date} 00:00:00"
        
        if source == 'rh':
            q = f"SELECT entry_time_utc as entry_time, opra_code as ticker, action, fill_price as entry_price, quantity, net_pnl as pnl FROM active_rh_log WHERE entry_time_utc >= '{start_str}'"
        else:
            q = f"SELECT entry_time, ticker, action, entry_price, quantity, net_pnl as pnl FROM {config.TBL_SIM_LOG} WHERE source_id = '{source}' AND entry_time >= '{start_str}'"
            
        try: df = con.execute(q).df()
        except: df = pd.DataFrame()
        con.close()
        
        if df.empty: return [], empty_fig, empty_fig, empty_fig, empty_fig, empty_fig

        # PRE-PROCESS TIMEZONES
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        if df['entry_time'].dt.tz is None: df['entry_time'] = df['entry_time'].dt.tz_localize(TZ_UTC)
        df['entry_time'] = df['entry_time'].dt.tz_convert(TZ_PST)
        
        # ⚡ INSTITUTIONAL OCC TICKER DECRYPTION
        def safe_parse_type(x):
            x = str(x).upper()
            if 'CALL' in x or ' C ' in x or x.endswith('C'): return 'CALL'
            if 'PUT' in x or ' P ' in x or x.endswith('P'): return 'PUT'
            # OCC Format Check (e.g. XSP260127C00698000)
            if len(x) >= 15:
                if 'C' in x[-10:]: return 'CALL'
                if 'P' in x[-10:]: return 'PUT'
            return 'UNK'

        def safe_parse_strike(x):
            x = str(x).upper()
            # OCC Format (last 8 digits divided by 1000)
            if len(x) >= 15 and x[-8:].isdigit():
                return str(int(x[-8:]) / 1000.0)
            parts = x.split()
            for p in parts:
                if p.replace('.', '', 1).isdigit(): return p
            return '0'

        df['Type'] = df['ticker'].apply(safe_parse_type)
        df['Strike'] = df['ticker'].apply(safe_parse_strike)

        # 1. KPIs
        net_pnl = df['pnl'].sum()
        win_rate = len(df[df['pnl']>0]) / len(df) * 100 if len(df) > 0 else 0
        pf = df[df['pnl']>0]['pnl'].sum() / abs(df[df['pnl']<0]['pnl'].sum()) if len(df[df['pnl']<0]) > 0 else 0
        
        card_style = {"backgroundColor": "#1e293b", "borderColor": "#334155", "color": "white"}
        
        kpis = [
            dbc.Col(dbc.Card([html.H6("NET PnL", className="text-muted small fw-bold"), html.H3(f"${net_pnl:,.2f}", className="text-success font-monospace" if net_pnl>=0 else "text-danger font-monospace")], body=True, style=card_style)),
            dbc.Col(dbc.Card([html.H6("WIN RATE", className="text-muted small fw-bold"), html.H3(f"{win_rate:.1f}%", className="text-info font-monospace")], body=True, style=card_style)),
            dbc.Col(dbc.Card([html.H6("PROFIT FACTOR", className="text-muted small fw-bold"), html.H3(f"{pf:.2f}", className="text-warning font-monospace")], body=True, style=card_style)),
            dbc.Col(dbc.Card([html.H6("TOTAL TRADES", className="text-muted small fw-bold"), html.H3(f"{len(df)}", className="text-white font-monospace")], body=True, style=card_style)),
        ]

        # 2. SPLIT CHART
        split_grp = df.groupby('Type')['pnl'].sum().reset_index()
        fig_split = px.bar(split_grp, x='Type', y='pnl', color='pnl', color_continuous_scale=['#ef4444', '#333', '#22c55e'])
        fig_split.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family="monospace"), coloraxis_showscale=False)

        # 3. WIN RATE CHART
        wr_grp = df.groupby('Type').apply(lambda x: len(x[x['pnl']>0])/len(x)*100).reset_index(name='WinRate')
        fig_wr = px.bar(wr_grp, x='Type', y='WinRate', color='WinRate', range_y=[0, 100], color_continuous_scale='Bluered_r')
        fig_wr.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family="monospace"), coloraxis_showscale=False)

        # 4. BURN RATE
        df['Week'] = df['entry_time'].dt.to_period('W').astype(str)
        df['quantity'] = df['quantity'].fillna(1.0).astype(float)
        df['Cost'] = df['entry_price'] * df['quantity'] * 100
        burn_grp = df.groupby('Week')['Cost'].sum().reset_index()
        fig_burn = px.bar(burn_grp, x='Week', y='Cost', color_discrete_sequence=['#f39c12'])
        fig_burn.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family="monospace"))

        # 5. STRIKE PERFORMANCE
        strike_df = df[df['Strike'] != '0'].copy()
        if not strike_df.empty:
            # Sort strikes for sequential x-axis plotting
            strike_df['Strike_Num'] = strike_df['Strike'].astype(float)
            strike_df = strike_df.sort_values('Strike_Num')
            fig_strike = px.scatter(strike_df, x='Strike', y='pnl', color='Type', color_discrete_map={'CALL': '#38bdf8', 'PUT': '#f43f5e'})
            fig_strike.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family="monospace"))
        else:
            fig_strike = empty_fig

        # 6. EQUITY CURVE
        df = df.sort_values('entry_time')
        df['Equity'] = df['pnl'].cumsum()
        fig_eq = px.line(df, x='entry_time', y='Equity')
        fig_eq.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_eq.update_traces(line_color='#00bc8c', fill='tozeroy', fillcolor='rgba(0, 188, 140, 0.1)')
        fig_eq.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(family="monospace"))

        return kpis, fig_split, fig_wr, fig_burn, fig_strike, fig_eq

    except Exception as e:
        return [dbc.Col(html.Div(f"DATA ERROR: {e}", className="text-danger fw-bold font-monospace py-3"))], empty_fig, empty_fig, empty_fig, empty_fig, empty_fig