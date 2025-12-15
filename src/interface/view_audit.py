import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
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
from src.utils.date_profiles import DATE_PROFILES

# TIMEZONES
TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# 1. CORE LOGIC: TRANSACTION FETCHER (EVENTS)
# ==============================================================================
def fetch_executions(source, date_profile_name):
    """
    Fetches Granular Events (Signals, Entries, Exits).
    Returns DataFrame with: time, ticker, action, price, pnl, seq_num
    """
    if not config.DB_FILE.exists(): return pd.DataFrame()
    
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    df = pd.DataFrame()
    
    # 1. Resolve Dates
    if date_profile_name in DATE_PROFILES:
        profile = DATE_PROFILES[date_profile_name]
        start_date = profile.start_date
        end_date = profile.end_date
    else:
        start_date = datetime.now().date() - timedelta(days=30)
        end_date = datetime.now().date()
        
    start_str = f"'{start_date}'"
    end_str = f"'{end_date} 23:59:59'"
    
    try:
        # --- A. LIVE LEDGER (Robinhood) ---
        if source == 'rh':
            if 'active_rh_log' in [x[0] for x in con.execute("SHOW TABLES").fetchall()]:
                q = f"""
                    SELECT 
                        entry_time_utc as time, 
                        root || ' ' || strike || option_right as ticker, 
                        action, 
                        fill_price as price,
                        net_pnl as pnl
                    FROM active_rh_log 
                    WHERE status='FILLED'
                    AND entry_time_utc >= {start_str} AND entry_time_utc <= {end_str}
                    ORDER BY entry_time_utc ASC
                """
                df = con.execute(q).df()

        # --- B. SIMULATIONS (Gen / Manual) ---
        elif source in ['gen', 'manual']:
            if 'active_simulation_log' in [x[0] for x in con.execute("SHOW TABLES").fetchall()]:
                condition = "reason = 'DATA_GENERATOR'" if source == 'gen' else "reason LIKE 'MANUAL%'"
                
                # Split entries and exits into separate events
                q = f"""
                    SELECT 
                        entry_time as time, 
                        ticker, 
                        'BUY' as action, 
                        entry_price as price,
                        0.0 as pnl
                    FROM active_simulation_log 
                    WHERE {condition}
                    AND entry_time >= {start_str} AND entry_time <= {end_str}
                    UNION ALL
                    SELECT 
                        exit_time as time, 
                        ticker, 
                        'SELL' as action, 
                        exit_price as price,
                        net_pnl as pnl
                    FROM active_simulation_log 
                    WHERE {condition}
                    AND exit_time >= {start_str} AND exit_time <= {end_str}
                    ORDER BY time ASC
                """
                df = con.execute(q).df()

        # --- C. RAW SIGNALS (Manifest) ---
        elif source == 'sig':
            tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
            tbl_manifest = getattr(config, 'TBL_MANIFEST', 'option_signal_manifest')
            tbl_indices = getattr(config, 'TBL_INDICES', 'indices_1m')
            
            if tbl_manifest in tables:
                start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
                end_ts = int(pd.Timestamp(f"{end_date} 23:59:59").timestamp() * 1000)
                
                # Signals
                q_sig = f"""
                    SELECT 
                        to_timestamp(entry_timestamp_utc / 1000) as time,
                        'XSP ' || upper(trade_type) as ticker,
                        'SIGNAL' as action,
                        0.0 as pnl
                    FROM {tbl_manifest}
                    WHERE entry_timestamp_utc >= {start_ts} AND entry_timestamp_utc <= {end_ts}
                    ORDER BY entry_timestamp_utc ASC
                """
                df_sigs = con.execute(q_sig).df()
                
                # Market Context
                if not df_sigs.empty and tbl_indices in tables:
                    q_mkt = f"""
                        SELECT datetime_utc as time, close as market_price 
                        FROM {tbl_indices} 
                        WHERE ticker = 'XSP' 
                        AND datetime_utc >= {start_str} AND datetime_utc <= {end_str}
                        ORDER BY datetime_utc ASC
                    """
                    df_mkt = con.execute(q_mkt).df()
                    
                    if not df_mkt.empty:
                        df_sigs['time'] = pd.to_datetime(df_sigs['time']).dt.tz_localize(None)
                        df_mkt['time'] = pd.to_datetime(df_mkt['time']).dt.tz_localize(None)
                        
                        df_sigs = df_sigs.sort_values('time')
                        df_mkt = df_mkt.sort_values('time')
                        
                        merged = pd.merge_asof(df_sigs, df_mkt, on='time', direction='backward')
                        merged['price'] = merged['market_price']
                        df = merged.drop(columns=['market_price'])
                    else:
                        df = df_sigs
                        df['price'] = 0.0
                else:
                    df = df_sigs
                    df['price'] = 0.0

    except Exception as e:
        print(f"[Audit] Fetch Error: {e}")
    finally:
        con.close()
    
    # --- POST PROCESSING ---
    if not df.empty:
        # 1. TZ Conversion
        df['time'] = pd.to_datetime(df['time'])
        if df['time'].dt.tz is None: df['time'] = df['time'].dt.tz_localize(TZ_UTC)
        df['time'] = df['time'].dt.tz_convert(TZ_PST)
        
        # 2. Sort Ascending for Sequencing
        df = df.sort_values('time', ascending=True)
        
        # 3. Daily Sequence # (Event #1, Event #2...)
        df['seq_num'] = df.groupby(df['time'].dt.date).cumcount() + 1
        
        # 4. Sort Descending for Display
        df = df.sort_values('time', ascending=False)
        
    return df

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("JUDGMENT COMMAND", className="magitek-h2"),
                html.P("EVENT LOG | COMPLIANCE AUDIT | DENSITY ANALYSIS", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: FORENSICS", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # --- CONTROL STRIP ---
        dbc.Row([
            dbc.Col(dcc.Dropdown(
                id='audit-source',
                options=[
                    {'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'},
                    {'label': 'SAVE CRYSTAL', 'value': 'gen'},
                    {'label': 'TRAINING GROUNDS', 'value': 'manual'},
                    {'label': 'RAW SIGNAL HISTORY', 'value': 'sig'}
                ],
                value='gen',
                clearable=False,
                className="mb-3"
            ), width=6),
            
            dbc.Col(dcc.Dropdown(
                id='audit-date-profile',
                options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                value='Last 30 Days',
                clearable=False,
                className="mb-3"
            ), width=6),
        ], className="mb-3"),

        # KPIs
        dbc.Row(id='audit-kpi-row', className="mb-4"),

        # CHARTS ROW 1: TEMPO & SEQUENCE
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("DAILY TRANSACTION VOLUME (Tempo)", className="card-header text-center"),
                    dbc.CardBody(dcc.Graph(id='audit-vol-chart', style={'height': '300px'}, config={'displayModeBar': False}))
                ], className="shadow h-100")
            ], width=6),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("SIGNAL SEQUENCE DECAY (Cumulative P/L by Event)", className="card-header text-center"),
                    dbc.CardBody(dcc.Graph(id='audit-decay-chart', style={'height': '300px'}, config={'displayModeBar': False}))
                ], className="shadow h-100")
            ], width=6),
        ], className="mb-4"),

        # CHARTS ROW 2: DENSITY
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("EXECUTION DENSITY HEATMAP", className="card-header text-center"),
                    dbc.CardBody(dcc.Graph(id='audit-heat-chart', style={'height': '300px'}, config={'displayModeBar': False}))
                ], className="shadow")
            ], width=12),
        ], className="mb-4"),

        # LEDGER
        dbc.Row([
            dbc.Col([
                html.H4("EVENT LOG (CHRONOLOGICAL)", className="text-info font-monospace mt-2"),
                html.Div(id='audit-table-container')
            ], width=12)
        ])

    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output('audit-kpi-row', 'children'),
     Output('audit-vol-chart', 'figure'),
     Output('audit-decay-chart', 'figure'),
     Output('audit-heat-chart', 'figure'),
     Output('audit-table-container', 'children')],
    [Input('audit-source', 'value'),
     Input('audit-date-profile', 'value')]
)
def update_audit(source, date_profile):
    df = fetch_executions(source, date_profile)
    
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if df.empty:
        return [], empty_fig, empty_fig, empty_fig, html.Div("No records found.", className="text-muted text-center mt-5")
    
    # 1. KPIs
    total_events = len(df)
    net_pnl = df['pnl'].sum()
    # Count specific actions
    buys = len(df[df['action'] == 'BUY'])
    sells = len(df[df['action'] == 'SELL'])
    signals = len(df[df['action'] == 'SIGNAL'])
    
    kpis = [
        dbc.Col(dbc.Card([html.H6("NET PnL"), html.H3(f"${net_pnl:,.2f}", className="text-success" if net_pnl>=0 else "text-danger")], body=True, color="dark", inverse=True)),
        dbc.Col(dbc.Card([html.H6("TOTAL EVENTS"), html.H3(f"{total_events}", className="text-white")], body=True, color="dark", inverse=True)),
        dbc.Col(dbc.Card([html.H6("ENTRIES"), html.H3(f"{buys}", className="text-info")], body=True, color="dark", inverse=True)),
        dbc.Col(dbc.Card([html.H6("EXITS"), html.H3(f"{sells}", className="text-warning")], body=True, color="dark", inverse=True)),
    ]
    if source == 'sig':
        kpis[2] = dbc.Col(dbc.Card([html.H6("SIGNALS"), html.H3(f"{signals}", className="text-info")], body=True, color="dark", inverse=True))
        kpis[3] = dbc.Col(dbc.Card([html.H6("CONTEXT"), html.H3("IDX", className="text-warning")], body=True, color="dark", inverse=True))

    # 2. VOLUME CHART
    vol_data = df.groupby(df['time'].dt.date).size()
    fig_vol = go.Figure(data=[go.Bar(x=vol_data.index, y=vol_data.values, marker_color='#e74c3c')])
    fig_vol.update_layout(title="Daily Frequency", template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

    # 3. SIGNAL DECAY CHART
    df_sorted = df.sort_values('time')
    df_sorted['cum_pnl'] = df_sorted['pnl'].fillna(0).cumsum()
    
    fig_decay = go.Figure()
    fig_decay.add_trace(go.Scatter(
        x=df_sorted['time'], y=df_sorted['cum_pnl'],
        mode='lines', fill='tozeroy', line=dict(color='#00bc8c', width=2)
    ))
    fig_decay.update_layout(title="Sequence Decay", template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

    # 4. HEATMAP
    df['hour'] = df['time'].dt.hour
    df['day'] = df['time'].dt.day_name()
    hm_data = df.groupby(['day', 'hour']).size().unstack(fill_value=0)
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    hm_data = hm_data.reindex(days)
    
    fig_heat = go.Figure(data=go.Heatmap(z=hm_data.values, x=hm_data.columns, y=hm_data.index, colorscale='Hot'))
    fig_heat.update_layout(title="Execution Density", template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

    # 5. LEDGER
    df_view = df.copy()
    df_view['time_str'] = df_view['time'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Formatting
    if source == 'sig':
        df_view['price'] = df_view['price'].apply(lambda x: f"${x:,.2f} (IDX)" if pd.notnull(x) else "-")
    else:
        df_view['price'] = df_view['price'].apply(lambda x: f"${x:.2f}" if pd.notnull(x) else "$0.00")
    df_view['pnl'] = df_view['pnl'].apply(lambda x: f"${x:,.2f}" if x != 0 else "-")

    cols = ['seq_num', 'time_str', 'ticker', 'action', 'price', 'pnl']
    
    # Header Style: Magitek Blue
    header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9', 'fontWeight': 'bold'}
    
    # Cell Style: Magitek Dark Blue
    cell_style = {
        'backgroundColor': '#101830', 
        'color': '#f3f5f9', 
        'border': '1px solid #444', 
        'textAlign': 'left', 
        'fontFamily': "'VT323', monospace", 
        'fontSize': '1.1rem'
    }

    dt = dash_table.DataTable(
        data=df_view.to_dict('records'),
        columns=[
            {'name': '#', 'id': 'seq_num'},
            {'name': 'TIME (PST)', 'id': 'time_str'},
            {'name': 'TICKER', 'id': 'ticker'},
            {'name': 'ACTION', 'id': 'action'},
            {'name': 'PRICE', 'id': 'price'},
            {'name': 'PnL', 'id': 'pnl'}
        ],
        style_header=header_style,
        style_cell=cell_style,
        style_data_conditional=[
            {'if': {'filter_query': '{pnl} contains "-"', 'column_id': 'pnl'}, 'color': '#888'},
            {'if': {'filter_query': '{pnl} contains "$"', 'column_id': 'pnl'}, 'color': '#00ff41'},
            {'if': {'filter_query': '{pnl} contains "$-"', 'column_id': 'pnl'}, 'color': '#ff5555'},
            {'if': {'column_id': 'seq_num'}, 'color': '#ff9900', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{action} = "SIGNAL"', 'column_id': 'action'}, 'color': '#00d2ff'},
            {'if': {'filter_query': '{action} = "BUY"', 'column_id': 'action'}, 'color': '#00ff41'},
            {'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'}, 'color': '#ff9900'}
        ],
        page_size=20,
        style_table={'overflowX': 'auto'}
    )

    return kpis, fig_vol, fig_decay, fig_heat, dt