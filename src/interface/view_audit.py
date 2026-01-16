import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import pathlib
import sys
import pytz

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
    # ⚡ NUCLEAR STYLE: HIGH CONTRAST (Black Text / White Background)
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
                # ⚡ RENAMED BASED ON USER FEEDBACK
                html.H2("TRADE AUDIT & PATTERNS", className="fw-bold text-white mb-0"),
                html.P("FREQUENCY ANALYSIS | DURATION PHYSICS | BEHAVIORAL INSIGHTS", className="text-muted small fw-bold mb-0")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("METRIC: PATTERN RECOGNITION", className="text-end text-warning font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # --- CONTROLS ---
        dbc.Row([
            dbc.Col([
                html.Label("DATA SOURCE", className="small text-muted fw-bold"),
                dbc.Select(
                    id='audit-source',
                    options=[{'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'}, {'label': 'SIMULATION', 'value': 'gen'}],
                    value='rh', 
                    style=INPUT_STYLE,
                    className="mb-3 text-dark"
                )
            ], width=6),
            dbc.Col([
                html.Label("TIME HORIZON", className="small text-muted fw-bold"),
                dbc.Select(
                    id='audit-profile',
                    options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                    value='Year To Date', 
                    style=INPUT_STYLE,
                    className="mb-3 text-dark"
                )
            ], width=6)
        ]),

        # --- ROW 1: THE "WHEN" (Time Analysis) ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("HOURLY PROFITABILITY (THE KILL ZONE)", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='audit-chart-hourly', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary h-100"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("WEEKDAY EFFICIENCY", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='audit-chart-daily', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary h-100"), width=6),
        ], className="mb-4"),

        # --- ROW 2: THE "HOW LONG" (Duration Physics) ---
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("DURATION VS. RESULT (THE 0DTE LEAK)", className="fw-bold font-monospace small"), 
                dbc.CardBody(dcc.Graph(id='audit-chart-duration', style={'height': '350px'}, config={'displayModeBar': False}))
            ], className="shadow-sm border-secondary"), width=12),
        ], className="mb-4"),

        # --- LEDGER (Granular) ---
        dbc.Row([
            dbc.Col([
                html.H5("EXECUTION TAPE", className="text-info font-monospace mt-2 fw-bold"), 
                html.Div(id='audit-table-container')
            ], width=12)
        ])

    ], fluid=True, className="px-4 py-3")

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
    # ⚡ PRESERVED LOGIC: Calls the user's existing engine
    try:
        df = forensics.fetch_scorecard_data(source, profile)
    except Exception as e:
        # Graceful failure if DB is locked
        return go.Figure(), go.Figure(), go.Figure(), html.Div(f"DATA ACCESS ERROR: {e}", className="text-danger fw-bold")
    
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if df.empty: return empty_fig, empty_fig, empty_fig, html.Div("NO DATA AVAILABLE", className="text-center text-muted font-monospace py-5")

    # PRE-PROCESS (Timezone & Features)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    if df['entry_time'].dt.tz is None: df['entry_time'] = df['entry_time'].dt.tz_localize(TZ_UTC)
    df['entry_time'] = df['entry_time'].dt.tz_convert(TZ_PST)
    
    df['hour'] = df['entry_time'].dt.hour
    df['weekday'] = df['entry_time'].dt.day_name()
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    df['weekday'] = pd.Categorical(df['weekday'], categories=days_order, ordered=True)
    
    # 1. HOURLY CHART
    hourly_pnl = df.groupby('hour')['pnl'].sum().reset_index()
    # Institutional Colors: Green/Red/Grey
    fig_hourly = px.bar(hourly_pnl, x='hour', y='pnl', 
                        color='pnl', color_continuous_scale=['#ef4444', '#334155', '#22c55e'])
    fig_hourly.update_layout(
        template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
        font=dict(family="monospace"), showlegend=False, coloraxis_showscale=False
    )
    # Add Open Market Marker
    fig_hourly.add_vrect(x0=6, x1=7, annotation_text="OPEN", annotation_position="top left", fillcolor="yellow", opacity=0.1, line_width=0)

    # 2. DAILY CHART
    daily_pnl = df.groupby('weekday')['pnl'].sum().reset_index()
    fig_daily = px.bar(daily_pnl, x='weekday', y='pnl', 
                       color='pnl', color_continuous_scale=['#ef4444', '#334155', '#22c55e'])
    fig_daily.update_layout(
        template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
        font=dict(family="monospace"), showlegend=False, coloraxis_showscale=False
    )

    # 3. DURATION SCATTER
    df['Outcome'] = df['pnl'].apply(lambda x: 'WIN' if x > 0 else 'LOSS')
    fig_dur = px.scatter(df, x='duration_mins', y='pnl', color='Outcome', 
                         color_discrete_map={'WIN': '#22c55e', 'LOSS': '#ef4444'},
                         hover_data=['ticker', 'entry_time'])
    fig_dur.update_layout(
        template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
        font=dict(family="monospace")
    )
    fig_dur.add_vline(x=200, line_dash="dash", line_color="orange", annotation_text="EXPIRATION DRAG")

    # 4. LEDGER (Institutional Style)
    df_view = df[['entry_time', 'ticker', 'action', 'entry_price', 'exit_price', 'duration_mins', 'pnl']].copy()
    df_view['entry_time'] = df_view['entry_time'].dt.strftime('%Y-%m-%d %H:%M')
    df_view['pnl_str'] = df_view['pnl'].apply(lambda x: f"${x:,.2f}")
    
    # Modern Table Style
    tbl = dash_table.DataTable(
        data=df_view.to_dict('records'),
        columns=[
            {'name': 'TIME', 'id': 'entry_time'}, {'name': 'TICKER', 'id': 'ticker'},
            {'name': 'DUR (m)', 'id': 'duration_mins'}, {'name': 'PnL', 'id': 'pnl_str'}
        ],
        style_header={
            'backgroundColor': '#1e293b', 
            'color': '#f8fafc', 
            'fontWeight': 'bold', 
            'borderBottom': '2px solid #475569',
            'fontFamily': 'monospace'
        },
        style_cell={
            'backgroundColor': '#0f172a', 
            'color': '#e2e8f0', 
            'border': '1px solid #334155', 
            'textAlign': 'left', 
            'fontFamily': 'monospace', 
            'fontSize': '13px'
        },
        style_data_conditional=[
            {'if': {'filter_query': '{pnl} < 0', 'column_id': 'pnl_str'}, 'color': '#ef4444', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{pnl} > 0', 'column_id': 'pnl_str'}, 'color': '#22c55e', 'fontWeight': 'bold'}
        ],
        page_size=10
    )

    return fig_hourly, fig_daily, fig_dur, tbl