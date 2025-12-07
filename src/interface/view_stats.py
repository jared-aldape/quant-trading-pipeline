import dash
from dash import dcc, html, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import duckdb
from datetime import datetime, timedelta
from src.utils import config

# ==============================================================================
# 1. FORENSICS ENGINE (Direct DB Access)
# ==============================================================================
def fetch_simulation_runs():
    """Fetches unique backtest runs and date ranges for the dropdown."""
    if not config.DB_FILE.exists(): return []
    
    # Standard Time Filters
    options = [
        {'label': '🔴 LIVE COMBAT LOG (The Ledger)', 'value': 'LIVE_LEDGER'},
        {'label': '⚠️ FULL HISTORY (All Trades)', 'value': 'ALL'},
        {'label': '📅 Year to Date (YTD)', 'value': 'YTD'},
        {'label': '📅 Quarter to Date (QTD)', 'value': 'QTD'},
        {'label': '📅 Month to Date (MTD)', 'value': 'MTD'},
        {'label': '📅 Week to Date (WTD)', 'value': 'WTD'},
        {'label': '⏪ Last 30 Days', 'value': 'L30D'},
        {'label': '⏪ Last 7 Days', 'value': 'L7D'},
    ]

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        # Check if table exists
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_SIM_LOG not in tables:
            con.close()
            return options

        # Dynamic Months from Data
        try:
            # Extract distinct YYYY-MM from entry_time
            query = f"""
                SELECT DISTINCT strftime(CAST(entry_time AS TIMESTAMP), '%Y-%m') as month_str 
                FROM {config.TBL_SIM_LOG} 
                WHERE entry_time IS NOT NULL
                ORDER BY month_str DESC
            """
            months = con.execute(query).fetchall()
            
            if months:
                options.append({'label': '--- MONTHLY ARCHIVES ---', 'value': 'DISABLED', 'disabled': True})
                for m in months:
                    m_str = m[0] # "2025-11"
                    # Convert to "November 2025"
                    dt_obj = datetime.strptime(m_str, '%Y-%m')
                    pretty_lbl = dt_obj.strftime('%B %Y')
                    options.append({'label': f"📂 {pretty_lbl}", 'value': f"MONTH_{m_str}"})
        except Exception as e:
            print(f"Error fetching months: {e}")

        con.close()
        return options
    except: return options

def fetch_run_metrics(run_id="ALL"):
    """Fetches trade log from DuckDB and filters by run_id (Date Range)."""
    if not config.DB_FILE.exists(): return pd.DataFrame()
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # --- CASE: LIVE LEDGER ---
        if run_id == 'LIVE_LEDGER':
            query = f"""
                SELECT 
                    entry_time, 
                    exit_time, 
                    ticker, 
                    asset_type as type, 
                    net_pnl as pnl, 
                    return_pct, 
                    qty,
                    entry_price, 
                    exit_price 
                FROM {config.TBL_LIVE_LOG}
                ORDER BY entry_time ASC
            """
            try:
                df = con.execute(query).df()
            except Exception: # Table might not exist yet
                df = pd.DataFrame()
            con.close()
            
            if not df.empty:
                df['entry_time'] = pd.to_datetime(df['entry_time'])
                df['exit_time'] = pd.to_datetime(df['exit_time'])
                df['duration_mins'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60
                df['hour'] = df['entry_time'].dt.hour
                df['trade_seq'] = df.index + 1
            return df

        # --- CASE: BACKTEST LOGS ---
        # Handle table check
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_SIM_LOG not in tables:
            con.close()
            return pd.DataFrame()

        # Query
        query = f"SELECT * FROM {config.TBL_SIM_LOG}"
        df = con.execute(query).df()
        con.close()
        
        if df.empty: return pd.DataFrame()
        
        # --- DATA NORMALIZATION ---
        if 'pnl' not in df.columns and 'net_pnl' in df.columns: df['pnl'] = df['net_pnl']
        if 'return_pct' not in df.columns: df['return_pct'] = 0.0
        
        # Datetime Conversion
        if 'entry_time' in df.columns:
            df['entry_time'] = pd.to_datetime(df['entry_time'])
        if 'exit_time' in df.columns:
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            
        if 'duration_mins' not in df.columns and 'entry_time' in df.columns and 'exit_time' in df.columns:
             df['duration_mins'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60

        if 'entry_time' in df.columns:
            df['hour'] = df['entry_time'].dt.hour

        # --- FILTER LOGIC (For Backtests) ---
        if run_id and run_id != 'ALL' and 'entry_time' in df.columns:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            if run_id == 'YTD':
                start_date = today.replace(month=1, day=1)
                df = df[df['entry_time'] >= start_date]
                
            elif run_id == 'QTD':
                curr_month = today.month
                quarter_start_month = 3 * ((curr_month - 1) // 3) + 1
                start_date = today.replace(month=quarter_start_month, day=1)
                df = df[df['entry_time'] >= start_date]
                
            elif run_id == 'MTD':
                start_date = today.replace(day=1)
                df = df[df['entry_time'] >= start_date]
                
            elif run_id == 'WTD':
                start_date = today - timedelta(days=today.weekday())
                df = df[df['entry_time'] >= start_date]
                
            elif run_id == 'L7D':
                start_date = today - timedelta(days=7)
                df = df[df['entry_time'] >= start_date]
                
            elif run_id == 'L30D':
                start_date = today - timedelta(days=30)
                df = df[df['entry_time'] >= start_date]
                
            elif run_id.startswith('MONTH_'):
                parts = run_id.split('_')[1]
                target_y, target_m = map(int, parts.split('-'))
                df = df[(df['entry_time'].dt.year == target_y) & (df['entry_time'].dt.month == target_m)]

        # Sort and sequence
        df = df.sort_values('entry_time').reset_index(drop=True)
        df['trade_seq'] = df.index + 1
        
        return df
    except Exception as e:
        print(f"Stats DB Error: {e}")
        return pd.DataFrame()

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("STATISTICS LAB", className="display-6 fw-bold text-white"),
                html.Small("Post-Trade Audit & Statistical Breakdown", className="text-muted"),
                html.Hr(className="my-2", style={'borderColor': '#444'})
            ], width=12)
        ], className="mb-4"),

        # CONTROL PANEL
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("CASE FILE SELECTOR (DB)", className="fw-bold text-info", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        html.Label("Select Dataset", className="text-white"),
                        dcc.Dropdown(
                            id='audit-run-selector',
                            options=fetch_simulation_runs(),
                            value='ALL', # Default to ALL
                            placeholder="Select Data Source...",
                            className="mb-2",
                            style={'color': '#000'}
                        ),
                        dbc.Button("↻ REFRESH FROM VAULT", id='audit-refresh-btn', color="secondary", outline=True, size="sm", className="w-100")
                    ], style={'backgroundColor': '#131722'})
                ], className="shadow mb-4", style={'border': '1px solid #444'})
            ], width=12, md=4),
            
            # SUMMARY STATS
            dbc.Col([
                html.Div(id='audit-stats-panel')
            ], width=12, md=8)
        ]),

        # VISUALIZATION GRID
        dbc.Row([
            # ROW 1: DECAY & DOMINANCE
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("SIGNAL DECAY (Profit by Sequence)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-decay', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=8),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("DOMINANCE (Call vs Put)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-dominance', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=4),
        ], className="mb-4"),

        # ROW 2: KILL ZONES & THETA
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("KILL ZONE (Hourly Performance)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-killzone', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=6),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("THETA RISK (Duration vs P&L)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id='chart-theta', style={'height': '300px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'}
                    )
                ], className="shadow h-100", style={'border': '1px solid #444'})
            ], width=12, md=6),
        ])

    ], fluid=True, style={'backgroundColor': '#000', 'minHeight': '100vh', 'padding': '20px'})

# ==============================================================================
# CALLBACKS
# ==============================================================================
@callback(
    [Output('audit-run-selector', 'options'),
     Output('chart-decay', 'figure'),
     Output('chart-dominance', 'figure'),
     Output('chart-killzone', 'figure'),
     Output('chart-theta', 'figure')],
    [Input('audit-run-selector', 'value'),
     Input('audit-refresh-btn', 'n_clicks')]
)
def update_forensics(run_id, n_clicks):
    # 1. Refresh Dropdown
    options = fetch_simulation_runs()
    
    # 2. Base Charts (Empty)
    empty_fig = go.Figure().update_layout(
        template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color="white"), xaxis={'showgrid': False, 'visible': False}, yaxis={'showgrid': False, 'visible': False}
    )
    
    if not run_id:
        return options, empty_fig, empty_fig, empty_fig, empty_fig

    # 3. Fetch Data
    df = fetch_run_metrics(run_id)
    if df.empty:
        return options, empty_fig, empty_fig, empty_fig, empty_fig

    # --- CHART 1: SIGNAL DECAY (Cumulative P&L) ---
    df['cum_pnl'] = df['pnl'].cumsum()
    fig_decay = go.Figure()
    fig_decay.add_trace(go.Scatter(x=df['trade_seq'], y=df['cum_pnl'], mode='lines+markers', line=dict(color='#00bc8c', width=2), marker=dict(size=4)))
    fig_decay.update_layout(
        template="plotly_dark", title=None, margin=dict(l=40, r=40, t=20, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        yaxis=dict(gridcolor='#333'), xaxis=dict(gridcolor='#333', title="Trade Sequence")
    )

    # --- CHART 2: DOMINANCE (Win Rate by Type) ---
    # Case insensitive type
    df['type'] = df['type'].str.upper()
    win_rates = df[df['pnl'] > 0].groupby('type').size()
    total_counts = df.groupby('type').size()
    wr_pct = (win_rates / total_counts * 100).fillna(0)
    
    fig_dom = go.Figure()
    fig_dom.add_trace(go.Bar(x=wr_pct.index, y=wr_pct.values, marker_color=['#00d2ff', '#f39c12']))
    fig_dom.update_layout(
        template="plotly_dark", title=None, margin=dict(l=40, r=40, t=20, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        yaxis=dict(range=[0, 100], gridcolor='#333', title="Win Rate %")
    )

    # --- CHART 3: KILL ZONE (Hourly P&L) ---
    hourly_pnl = df.groupby('hour')['pnl'].sum().reset_index()
    colors = ['#00bc8c' if v >= 0 else '#ef5350' for v in hourly_pnl['pnl']]
    
    fig_kill = go.Figure()
    fig_kill.add_trace(go.Bar(x=hourly_pnl['hour'], y=hourly_pnl['pnl'], marker_color=colors))
    fig_kill.update_layout(
        template="plotly_dark", title=None, margin=dict(l=40, r=40, t=20, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        xaxis=dict(tickmode='linear', dtick=1, gridcolor='#333', title="Hour of Day"), yaxis=dict(gridcolor='#333')
    )

    # --- CHART 4: THETA RISK (Duration vs ROI) ---
    fig_theta = go.Figure()
    fig_theta.add_trace(go.Scatter(
        x=df['duration_mins'], y=df['return_pct'], 
        mode='markers', 
        marker=dict(
            size=8, 
            color=df['return_pct'], 
            colorscale='RdYlGn', 
            cmid=0,
            line=dict(width=1, color='#333')
        )
    ))
    fig_theta.update_layout(
        template="plotly_dark", title=None, margin=dict(l=40, r=40, t=20, b=30),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"),
        xaxis=dict(title="Minutes Held", gridcolor='#333'), yaxis=dict(title="Return %", gridcolor='#333')
    )

    return options, fig_decay, fig_dom, fig_kill, fig_theta