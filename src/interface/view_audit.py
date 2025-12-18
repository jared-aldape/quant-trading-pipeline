import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import duckdb
import pathlib
import sys
import pytz
from datetime import datetime, timedelta

# PATH SETUP
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.core import engine_forensics as forensics
from src.utils.date_profiles import DATE_PROFILES

# TIMEZONES
TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW ---
        dbc.Row([
            dbc.Col([
                html.H2("EXECUTION AUDIT", className="magitek-h2"),
                html.P("TIMING ANALYSIS | DURATION PHYSICS | CALENDAR HEATMAPS", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("METRIC: EXECUTION QUALITY", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # --- CONTROLS ---
        dbc.Row([
            dbc.Col(dcc.Dropdown(
                id='audit-source',
                options=[{'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'}, {'label': 'SIMULATION', 'value': 'gen'}],
                value='rh', clearable=False, className="mb-3"
            ), width=6),
            dbc.Col(dcc.Dropdown(
                id='audit-profile',
                options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                value='Year To Date', clearable=False, className="mb-3"
            ), width=6)
        ]),

        # --- ROW 1: THE "WHEN" (Time Analysis) ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("HOURLY PROFITABILITY (THE KILL ZONE)", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='audit-chart-hourly', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow h-100"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("WEEKDAY EFFICIENCY", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='audit-chart-daily', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow h-100"), width=6),
        ], className="mb-4"),

        # --- ROW 2: THE "HOW LONG" (Duration Physics) ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("DURATION VS. RESULT (THE 0DTE LEAK)", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='audit-chart-duration', style={'height': '350px'}, config={'displayModeBar': False}))
            ], className="shadow"), width=12),
        ], className="mb-4"),

        # --- LEDGER (Granular) ---
        dbc.Row([
            dbc.Col([
                html.H4("EXECUTION TAPE", className="text-info font-monospace mt-2"), 
                html.Div(id='audit-table-container')
            ], width=12)
        ])

    ], fluid=True)

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================
@callback(
    [Output('audit-chart-hourly', 'figure'),
     Output('audit-chart-daily', 'figure'),
     Output('audit-chart-duration', 'figure'),
     Output('audit-table-container', 'children')],
    [Input('audit-source', 'value'),
     Input('audit-profile', 'value')]
)
def update_audit(source, profile):
    # Fetch Data via Forensics Engine
    df = forensics.fetch_scorecard_data(source, profile)
    
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if df.empty: return empty_fig, empty_fig, empty_fig, html.Div("NO DATA", className="text-center text-muted")

    # PRE-PROCESS (Timezone & Features)
    # Ensure TZ-Aware PST
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    if df['entry_time'].dt.tz is None: df['entry_time'] = df['entry_time'].dt.tz_localize(TZ_UTC)
    df['entry_time'] = df['entry_time'].dt.tz_convert(TZ_PST)
    
    df['hour'] = df['entry_time'].dt.hour
    df['weekday'] = df['entry_time'].dt.day_name()
    # Sort Weekdays
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    df['weekday'] = pd.Categorical(df['weekday'], categories=days_order, ordered=True)
    
    # 1. HOURLY CHART
    hourly_pnl = df.groupby('hour')['pnl'].sum().reset_index()
    fig_hourly = px.bar(hourly_pnl, x='hour', y='pnl', title="Net PnL by Hour (PST)",
                        color='pnl', color_continuous_scale=['#ff5555', '#333', '#00ff41'])
    fig_hourly.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")
    fig_hourly.add_vrect(x0=6, x1=7, annotation_text="OPEN", annotation_position="top left", fillcolor="yellow", opacity=0.1, line_width=0)

    # 2. DAILY CHART
    daily_pnl = df.groupby('weekday')['pnl'].sum().reset_index()
    fig_daily = px.bar(daily_pnl, x='weekday', y='pnl', title="Net PnL by Day",
                       color='pnl', color_continuous_scale=['#ff5555', '#333', '#00ff41'])
    fig_daily.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")

    # 3. DURATION SCATTER (THE LEAK DETECTOR)
    # Highlight winners vs losers
    df['Outcome'] = df['pnl'].apply(lambda x: 'WIN' if x > 0 else 'LOSS')
    fig_dur = px.scatter(df, x='duration_mins', y='pnl', color='Outcome', 
                         color_discrete_map={'WIN': '#00ff41', 'LOSS': '#ff5555'},
                         hover_data=['ticker', 'entry_time'], title="Trade Duration vs PnL")
    fig_dur.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_family="'VT323', monospace")
    # Mark the 0DTE Danger Zone (e.g., > 200 mins)
    fig_dur.add_vline(x=200, line_dash="dash", line_color="orange", annotation_text="EXPIRATION DRAG")

    # 4. LEDGER
    df_view = df[['entry_time', 'ticker', 'action', 'entry_price', 'exit_price', 'duration_mins', 'pnl']].copy()
    df_view['entry_time'] = df_view['entry_time'].dt.strftime('%Y-%m-%d %H:%M')
    df_view['pnl_str'] = df_view['pnl'].apply(lambda x: f"${x:,.2f}")
    
    header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9'}
    cell_style = {'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'}

    tbl = dash_table.DataTable(
        data=df_view.to_dict('records'),
        columns=[
            {'name': 'TIME', 'id': 'entry_time'}, {'name': 'TICKER', 'id': 'ticker'},
            {'name': 'DUR (m)', 'id': 'duration_mins'}, {'name': 'PnL', 'id': 'pnl_str'}
        ],
        style_header=header_style, style_cell=cell_style,
        style_data_conditional=[
            {'if': {'filter_query': '{pnl} < 0', 'column_id': 'pnl_str'}, 'color': '#ff5555'},
            {'if': {'filter_query': '{pnl} > 0', 'column_id': 'pnl_str'}, 'color': '#00ff41'}
        ],
        page_size=10
    )

    return fig_hourly, fig_daily, fig_dur, tbl