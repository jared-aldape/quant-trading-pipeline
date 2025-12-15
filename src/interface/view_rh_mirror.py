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

# ==============================================================================
# 0. PATHS & CONFIG
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

TBL_RH_LEDGER = "active_rh_log"
TBL_SIM_LOG = "active_simulation_log"
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')
TZ_VAULT = pytz.UTC
TZ_GLASS = pytz.timezone('US/Pacific')

# ==============================================================================
# 1. DATA NORMALIZATION HELPERS
# ==============================================================================
def normalize_to_naive_pst(series):
    """
    Converts any timestamp series to Naive Pacific Time (for Plotly).
    """
    if series.empty: return series
    series = pd.to_datetime(series)
    
    # 1. Localize to UTC if naive (Assume Vault is UTC)
    if series.dt.tz is None: 
        series = series.dt.tz_localize(TZ_VAULT)
    else:
        series = series.dt.tz_convert(TZ_VAULT)
        
    # 2. Convert to Pacific and Drop Offset
    return series.dt.tz_convert(TZ_GLASS).dt.tz_localize(None)

def fetch_active_trading_days(source):
    """
    Fetches unique trading days based on the selected profile.
    """
    if not config.DB_FILE.exists(): return []
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # 1. Determine query based on source
    tbl = None
    condition = "1=1"
    date_col = 'entry_time'

    if source == 'rh':
        tbl = TBL_RH_LEDGER
        date_col = 'entry_time_utc'
    elif source in ['manual', 'gen']:
        tbl = TBL_SIM_LOG
        if source == 'manual':
            condition = "reason LIKE 'MANUAL%'"
        elif source == 'gen':
            condition = "reason = 'DATA_GENERATOR'"

    if not tbl: return []
    
    # Check if table exists
    tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
    if tbl not in tables: 
        con.close()
        return []

    # 2. Execute date query
    try:
        # We cast to date to group them
        query = f"SELECT DISTINCT CAST({date_col} AS DATE) AS trade_date FROM {tbl} WHERE {condition} ORDER BY trade_date DESC"
        df = con.execute(query).df()
        con.close()
        
        if df.empty: return []
        
        # Convert to string dates
        dates = [d.strftime('%Y-%m-%d') for d in df['trade_date'].tolist()]
        return [{'label': d, 'value': d} for d in dates]
    except Exception as e:
        print(f"Date Fetch Error: {e}")
        return []

def fetch_day_data(date_str, source):
    """
    Fetches Market Data (SPX/XSP) and Transactions for the given day/source.
    """
    if not config.DB_FILE.exists(): return pd.DataFrame(), pd.DataFrame()
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # Define Day Boundaries (UTC) covering the PST trading session
    start_dt = f"'{date_str} 00:00:00'"
    end_dt = f"'{date_str} 23:59:59'"
    
    # 1. Fetch Market Data (Index Context)
    # Prefer XSP, fallback to SPX
    ticker = 'XSP'
    q_check = f"SELECT COUNT(*) FROM {TBL_INDICES} WHERE ticker='XSP' AND datetime_utc BETWEEN {start_dt} AND {end_dt}"
    try:
        count = con.execute(q_check).fetchone()[0]
        if count == 0: ticker = 'SPX'
    except:
        ticker = 'SPX'
        
    q_mkt = f"""
        SELECT datetime_utc, open, high, low, close 
        FROM {TBL_INDICES} 
        WHERE ticker = '{ticker}' 
        AND datetime_utc BETWEEN {start_dt} AND {end_dt}
        ORDER BY datetime_utc ASC
    """
    mkt_df = con.execute(q_mkt).df()
    
    # 2. Fetch Transactions
    trd_df = pd.DataFrame()
    
    if source == 'rh':
        q_trd = f"""
            SELECT entry_time_utc, action, fill_price, root || ' ' || strike || option_right as ticker
            FROM {TBL_RH_LEDGER} 
            WHERE entry_time_utc BETWEEN {start_dt} AND {end_dt}
            AND status = 'FILLED'
        """
        trd_df = con.execute(q_trd).df().rename(columns={'entry_time_utc': 'time_utc', 'fill_price': 'price'})
        
    elif source in ['manual', 'gen']:
        # Filter Logic
        condition = "1=1"
        if source == 'manual': condition = "reason LIKE 'MANUAL%'"
        elif source == 'gen': condition = "reason = 'DATA_GENERATOR'"

        q_trd = f"""
            SELECT entry_time, exit_time, entry_price, exit_price, ticker
            FROM {TBL_SIM_LOG} 
            WHERE entry_time BETWEEN {start_dt} AND {end_dt} AND {condition}
        """
        raw = con.execute(q_trd).df()
        
        if not raw.empty:
            # Explode Trades into Entries/Exits for plotting
            entries = raw[['entry_time', 'ticker', 'entry_price']].rename(
                columns={'entry_time': 'time_utc', 'entry_price': 'price'}
            )
            entries['action'] = 'BUY'
            
            exits = raw[['exit_time', 'ticker', 'exit_price']].rename(
                columns={'exit_time': 'time_utc', 'exit_price': 'price'}
            )
            exits['action'] = 'SELL'
            
            trd_df = pd.concat([entries, exits]).sort_values('time_utc')
    
    con.close()

    # 3. Normalize Timestamps to PST Naive
    if not mkt_df.empty: 
        mkt_df['time_naive'] = normalize_to_naive_pst(mkt_df['datetime_utc'])
    
    if not trd_df.empty: 
        trd_df['time_naive'] = normalize_to_naive_pst(trd_df['time_utc'])
    
    return mkt_df, trd_df

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("REPLAY MIRROR COMMAND", className="magitek-h2"),
                html.P("EXECUTION OVERLAY | INDEX CONTEXT | TICKER TAPE", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: REFLECTION", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # --- CONTROL STRIP ---
        dbc.Row([
            dbc.Col(dcc.Dropdown(
                id='mirror-source',
                options=[
                    {'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'},
                    {'label': 'SAVE CRYSTAL', 'value': 'gen'},
                    {'label': 'TRAINING GROUNDS', 'value': 'manual'}
                ],
                value='rh', # Default to Live
                clearable=False,
                className="mb-3"
            ), width=6),

            dbc.Col(dcc.Dropdown(
                id='mirror-date',
                options=[], 
                placeholder="Select Active Trading Day",
                className="mb-3"
            ), width=6),
        ], className="mb-3"),

        # MAIN CHART
        dbc.Row([
            dbc.Col(dcc.Graph(id='mirror-chart', style={'height': '75vh'}, config={'displayModeBar': False}), width=12)
        ]),
        
        # TRANSACTION TABLE
        dbc.Row([
            dbc.Col([
                html.H4(id='mirror-table-title', className="text-info font-monospace mt-4 mb-2"),
                html.Div(id='mirror-table-container')
            ], width=12)
        ], className="mb-5")

    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output('mirror-date', 'options'),
     Output('mirror-date', 'value')],
    Input('mirror-source', 'value')
)
def set_date_options(source):
    """
    Populates date dropdown AND auto-selects the most recent date.
    """
    dates = fetch_active_trading_days(source)
    if dates:
        return dates, dates[0]['value']
    return [], None

@callback(
    [Output('mirror-chart', 'figure'),
     Output('mirror-table-title', 'children'),
     Output('mirror-table-container', 'children')],
    [Input('mirror-date', 'value'),
     Input('mirror-source', 'value')]
)
def update_mirror(date_str, source):
    if not date_str: 
        return go.Figure(), "Transaction Tape", html.Div("Select a profile and date.", className="text-muted text-center mt-5")
        
    mkt, trd = fetch_day_data(date_str, source)
    
    # 1. BUILD CHART
    fig = go.Figure()
    
    # A. Index Context (Candles)
    if not mkt.empty:
        fig.add_trace(go.Candlestick(
            x=mkt['time_naive'], open=mkt['open'], high=mkt['high'], 
            low=mkt['low'], close=mkt['close'], name="Index Price"
        ))
    
    # B. Transactions (Markers Overlay)
    if not trd.empty and not mkt.empty:
        buys = trd[trd['action'] == 'BUY']
        sells = trd[trd['action'] == 'SELL']
        
        # KEY LOGIC: Pin Marker Y-Axis to the INDEX PRICE
        def align_markers_to_candles(trade_times):
            y_vals = []
            for t in trade_times:
                idx = mkt['time_naive'].searchsorted(t)
                if idx >= len(mkt): idx = len(mkt) - 1
                y_vals.append(mkt.iloc[idx]['close'])
            return y_vals

        if not buys.empty:
            buy_y = align_markers_to_candles(buys['time_naive'])
            buy_text = [f"BUY {t}<br>Opt Px: ${p:.2f}" for t, p in zip(buys['ticker'], buys['price'])]
            
            fig.add_trace(go.Scatter(
                x=buys['time_naive'], y=buy_y, 
                mode='markers', name='BUY', 
                marker=dict(
                    symbol='triangle-up', 
                    size=20, # Increased Size
                    color='#00FF00', # Neon Green
                    line=dict(width=2, color='white') # High Contrast Border
                ),
                text=buy_text, hoverinfo='text'
            ))

        if not sells.empty:
            sell_y = align_markers_to_candles(sells['time_naive'])
            sell_text = [f"SELL {t}<br>Opt Px: ${p:.2f}" for t, p in zip(sells['ticker'], sells['price'])]
            
            fig.add_trace(go.Scatter(
                x=sells['time_naive'], y=sell_y, 
                mode='markers', name='SELL', 
                marker=dict(
                    symbol='triangle-down', 
                    size=20, # Increased Size
                    color='#FF4500', # Neon Red/Orange
                    line=dict(width=2, color='white') # High Contrast Border
                ),
                text=sell_text, hoverinfo='text'
            ))

    # C. Styling
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)',
        title=f"Execution Replay: {date_str} ({source.upper()})",
        xaxis_title="Time (PST)",
        yaxis_title="Index Price",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
        font=dict(family="'VT323', monospace", size=14, color="#f3f5f9")
    )
    
    # 2. BUILD TABLE
    if not trd.empty:
        table_data = trd.copy()
        table_data['time'] = table_data['time_naive'].dt.strftime('%H:%M:%S')
        table_data['price'] = table_data['price'].apply(lambda x: f"${x:,.2f}")
        
        if 'ticker' not in table_data.columns: table_data['ticker'] = 'UNK'
        
        df_view = table_data[['time', 'action', 'ticker', 'price']]
        
        # MAGITEK STYLES
        header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9', 'fontWeight': 'bold'}
        cell_style = {'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'}

        dt = dash_table.DataTable(
            data=df_view.to_dict('records'),
            columns=[{'name': i.upper(), 'id': i} for i in df_view.columns],
            style_header=header_style,
            style_cell=cell_style,
            style_data_conditional=[
                {'if': {'filter_query': '{action} = "BUY"', 'column_id': 'action'}, 'color': '#00ff41'},
                {'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'}, 'color': '#ff9900'},
            ],
            page_size=10
        )
    else:
        dt = html.Div("No trades found.", className="text-muted text-center")

    return fig, f"TRANSACTION TAPE ({source.upper()})", dt