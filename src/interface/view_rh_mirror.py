import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import duckdb
import pathlib
import sys
import numpy as np
from datetime import datetime, time, timedelta
import pytz

# ==============================================================================
# 0. PATHS & CONFIG
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

TBL_RH_LEDGER = "active_rh_log"
TBL_SIM_LOG = "active_simulation_log"
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')
TBL_FUTURES = getattr(config, 'TBL_FUTURES', 'futures_1m')

# ==============================================================================
# 1. HELPER FUNCTIONS (Vault Standard)
# ==============================================================================
def to_wall_clock(series):
    if series.empty: return series
    if series.dt.tz is None:
        series = series.dt.tz_localize('UTC')
    else:
        series = series.dt.tz_convert('UTC')
    series = series.dt.tz_convert(config.TZ_LOCAL)
    return series.dt.tz_localize(None)

def calculate_linreg(df):
    if df is None or len(df) < 20: return df
    df = df.copy()
    df['x'] = np.arange(len(df))
    slope, intercept = np.polyfit(df['x'], df['close'], 1)
    df['reg_line'] = slope * df['x'] + intercept
    std = df['close'].std()
    df['upper_band'] = df['reg_line'] + (2 * std)
    df['lower_band'] = df['reg_line'] - (2 * std)
    return df

# ==============================================================================
# 2. DATA FETCHING
# ==============================================================================
def fetch_active_trading_days(source):
    if not config.DB_FILE.exists(): return []
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    tbl = None
    condition = "1=1"
    date_col = 'entry_time'

    if source == 'rh':
        tbl = TBL_RH_LEDGER
        date_col = 'entry_time_utc'
    elif source in ['manual', 'gen']:
        tbl = TBL_SIM_LOG
        if source == 'manual': condition = "reason LIKE 'MANUAL%'"
        elif source == 'gen': condition = "reason = 'DATA_GENERATOR'"

    if not tbl: return []
    
    try:
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if tbl not in tables: 
            con.close(); return []

        query = f"SELECT DISTINCT CAST({date_col} AS DATE) AS trade_date FROM {tbl} WHERE {condition} ORDER BY trade_date DESC"
        df = con.execute(query).df()
        con.close()
        
        if df.empty: return []
        dates = [d.strftime('%Y-%m-%d') for d in df['trade_date'].tolist()]
        return [{'label': d, 'value': d} for d in dates]
    except Exception as e:
        print(f"Date Fetch Error: {e}")
        return []

def fetch_session_data(date_str, source):
    if not config.DB_FILE.exists(): return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    
    # Time Boundaries (UTC)
    dt_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    start_utc = config.TZ_NY.localize(datetime.combine(dt_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
    end_utc = config.TZ_NY.localize(datetime.combine(dt_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    # 1. INDICES (XSP & VIX)
    q_idx = f"""
        SELECT datetime_utc, ticker, open, high, low, close 
        FROM {TBL_INDICES} 
        WHERE ticker IN ('XSP', 'VIX') AND datetime_utc BETWEEN '{start_utc}' AND '{end_utc}'
        ORDER BY datetime_utc ASC
    """
    df_idx = con.execute(q_idx).df()
    
    xsp = pd.DataFrame()
    vix = pd.DataFrame()
    
    if not df_idx.empty:
        df_idx['datetime_utc'] = pd.to_datetime(df_idx['datetime_utc'])
        df_idx['datetime_local'] = to_wall_clock(df_idx['datetime_utc'])
        
        if 'XSP' in df_idx['ticker'].values:
            xsp = df_idx[df_idx['ticker'] == 'XSP'].copy()
            xsp['sma_50'] = xsp['close'].rolling(50).mean()
            xsp = calculate_linreg(xsp)
            
        if 'VIX' in df_idx['ticker'].values:
            vix = df_idx[df_idx['ticker'] == 'VIX'].copy()
            vix['ema12'] = vix['close'].ewm(span=12).mean()
            vix['ema26'] = vix['close'].ewm(span=26).mean()
            vix['macd'] = vix['ema12'] - vix['ema26']
            vix['signal'] = vix['macd'].ewm(span=9).mean()
            vix['hist'] = vix['macd'] - vix['signal']
            # RSI
            delta = vix['close'].diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
            vix['rsi'] = 100 - (100 / (1 + rs))

    # 2. FUTURES (/ES)
    es = pd.DataFrame()
    try:
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if TBL_FUTURES in tables:
            q_fut = f"""
                SELECT datetime_utc, ticker, close 
                FROM {TBL_FUTURES} 
                WHERE (ticker LIKE 'ES%' OR ticker = '/ES') AND datetime_utc BETWEEN '{start_utc}' AND '{end_utc}'
                ORDER BY datetime_utc ASC
            """
            es = con.execute(q_fut).df()
            if not es.empty:
                es['datetime_utc'] = pd.to_datetime(es['datetime_utc'])
                es['datetime_local'] = to_wall_clock(es['datetime_utc'])
                es['scaled_close'] = es['close'] / 10.0
    except: pass

    # 3. TRANSACTIONS
    trd_df = pd.DataFrame()
    if source == 'rh':
        q_trd = f"""
            SELECT entry_time_utc, action, fill_price, root || ' ' || strike || option_right as ticker
            FROM {TBL_RH_LEDGER} 
            WHERE entry_time_utc BETWEEN '{start_utc}' AND '{end_utc}'
            AND status = 'FILLED'
        """
        trd_df = con.execute(q_trd).df().rename(columns={'entry_time_utc': 'time_utc', 'fill_price': 'price'})
        
    elif source in ['manual', 'gen']:
        condition = "reason LIKE 'MANUAL%'" if source == 'manual' else "reason = 'DATA_GENERATOR'"
        q_trd = f"""
            SELECT entry_time, exit_time, entry_price, exit_price, ticker
            FROM {TBL_SIM_LOG} 
            WHERE entry_time BETWEEN '{start_utc}' AND '{end_utc}' AND {condition}
        """
        raw = con.execute(q_trd).df()
        if not raw.empty:
            entries = raw[['entry_time', 'ticker', 'entry_price']].rename(columns={'entry_time': 'time_utc', 'entry_price': 'price'})
            entries['action'] = 'BUY'
            exits = raw[['exit_time', 'ticker', 'exit_price']].rename(columns={'exit_time': 'time_utc', 'exit_price': 'price'})
            exits['action'] = 'SELL'
            trd_df = pd.concat([entries, exits]).sort_values('time_utc')

    con.close()
    
    if not trd_df.empty:
        trd_df['datetime_local'] = to_wall_clock(pd.to_datetime(trd_df['time_utc']))

    return xsp, vix, es, trd_df

# ==============================================================================
# 3. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("MIMIC COMMAND", className="magitek-h2"),
                html.P("EXECUTION REPLAY | INDEX CONTEXT | TICKER TAPE", className="magitek-note"),
                html.Div([
                    html.Span("PROFILE: ", className="fw-bold text-warning small me-2 align-middle font-monospace"),
                    dcc.Dropdown(
                        id='mirror-source',
                        options=[
                            {'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'},
                            {'label': 'SAVE CRYSTAL (Backtest)', 'value': 'gen'},
                            {'label': 'TRAINING GROUNDS (Sim)', 'value': 'manual'}
                        ],
                        value='rh',
                        clearable=False,
                        style={'width': '250px', 'display': 'inline-block', 'verticalAlign': 'middle'}
                    )
                ], className="d-inline-block mt-1")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: REFLECTION", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "color": "#f3f5f9", "boxShadow": "0px 0px 10px rgba(0,0,0,0.5)"}),

        # 3-COLUMN CONTROL DECK
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("1. TARGETING", className="card-header"),
                    dbc.CardBody([
                        html.Label("Session Date", className="small text-muted font-monospace"), 
                        dcc.Dropdown(id='mirror-date', placeholder="Select Active Day...", className="mb-2"),
                    ])
                ], className="h-100 shadow-sm")
            ], width=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("2. COMBAT REPORT", className="card-header"),
                    dbc.CardBody(id='mirror-report-card', className="d-flex align-items-center justify-content-center h-100")
                ], className="h-100 shadow-sm")
            ], width=4),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("3. TRANSACTION TAPE", className="card-header"),
                    dbc.CardBody(id='mirror-table-container', className="p-0", style={"overflowY": "auto", "maxHeight": "120px"})
                ], className="h-100 shadow-sm")
            ], width=4)
        ], className="mb-3"),

        # FORENSIC STACK
        dbc.Row([dbc.Col([dcc.Loading(dcc.Graph(id='mirror-chart', style={'height': '900px'}, config={'displayModeBar': True}))], width=12)])
    ], fluid=True)

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    [Output('mirror-date', 'options'),
     Output('mirror-date', 'value')],
    Input('mirror-source', 'value')
)
def set_date_options(source):
    dates = fetch_active_trading_days(source)
    return dates, dates[0]['value'] if dates else None

@callback(
    [Output('mirror-chart', 'figure'),
     Output('mirror-report-card', 'children'),
     Output('mirror-table-container', 'children')],
    [Input('mirror-date', 'value'),
     Input('mirror-source', 'value')]
)
def update_mirror(date_str, source):
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if not date_str: return empty_fig, "NO DATA", ""
        
    xsp, vix, es, trd = fetch_session_data(date_str, source)
    
    # --- BUILD STATS ---
    trade_count = len(trd) if not trd.empty else 0
    pnl_display = "N/A"
    
    # Simple P&L Logic for Report Card (Approximate)
    if not trd.empty:
        buys = trd[trd['action'] == 'BUY']['price'].sum()
        sells = trd[trd['action'] == 'SELL']['price'].sum()
        net = (sells - buys) * 100 # Assuming 1 contract for simple view
        color = "text-success" if net >= 0 else "text-danger"
        pnl_display = html.Div(f"${net:,.2f}", className=f"fw-bold {color}")
    else:
        pnl_display = html.Div("$0.00", className="fw-bold text-white")

    report_html = html.Div([
        dbc.Row([
            dbc.Col([html.Div("TOTAL TRADES", className="small text-muted"), html.Div(f"{trade_count}", className="fw-bold text-white")], width=6),
            dbc.Col([html.Div("EST. SESSION P&L", className="small text-muted"), pnl_display], width=6),
        ])
    ], className="text-center font-monospace w-100")

    # --- BUILD TABLE ---
    table_html = html.Div("No trades.", className="text-muted text-center p-3")
    if not trd.empty:
        df_view = trd.copy()
        df_view['time'] = df_view['datetime_local'].dt.strftime('%H:%M:%S')
        df_view = df_view[['time', 'action', 'price', 'ticker']]
        
        table_html = dash_table.DataTable(
            data=df_view.to_dict('records'),
            columns=[{'name': i.upper(), 'id': i} for i in df_view.columns],
            style_header={'backgroundColor': '#283878', 'color': '#fde722', 'fontWeight': 'bold'},
            style_cell={'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'fontFamily': "'VT323', monospace"},
            style_data_conditional=[
                {'if': {'filter_query': '{action} = "BUY"'}, 'color': '#00ff41'},
                {'if': {'filter_query': '{action} = "SELL"'}, 'color': '#ff9900'},
            ],
            page_size=50,
            style_table={'height': '120px', 'overflowY': 'auto'}
        )

    # --- BUILD CHART ---
    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.35, 0.25, 0.2, 0.2], 
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("CONTEXT: XSP + LinReg + ES", f"MIRROR: {source.upper()} EXECUTION TAPE", "VIX FRACTAL FLOW", "VIX RSI")
    )

    day_start = xsp['datetime_local'].iloc[0].replace(hour=6, minute=30) if not xsp.empty else None
    day_end = day_start.replace(hour=13, minute=0) if day_start else None

    # 1. CONTEXT (XSP)
    if not xsp.empty:
        fig.add_trace(go.Candlestick(x=xsp['datetime_local'], open=xsp['open'], high=xsp['high'], low=xsp['low'], close=xsp['close'], name="XSP"), row=1, col=1)
        
        if 'reg_line' in xsp.columns:
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)
            
            # ORB
            start_window = day_start
            end_window = day_start + timedelta(minutes=30)
            orb_df = xsp[(xsp['datetime_local'] >= start_window) & (xsp['datetime_local'] <= end_window)]
            if not orb_df.empty:
                fig.add_hline(y=orb_df['high'].max(), line_dash="solid", line_color="green", opacity=0.5, row=1, col=1)
                fig.add_hline(y=orb_df['low'].min(), line_dash="solid", line_color="red", opacity=0.5, row=1, col=1)

    if not es.empty:
        fig.add_trace(go.Scatter(x=es['datetime_local'], y=es['scaled_close'], name="/ES", line=dict(color='#00d2ff', width=1, dash='dot')), row=1, col=1)

    # 2. MIRROR (Executions)
    if not trd.empty:
        buys = trd[trd['action'] == 'BUY']
        sells = trd[trd['action'] == 'SELL']
        
        # Use simple markers since we have multiple tickers
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys['datetime_local'], y=buys['price'], 
                mode='markers', name='BUY', 
                marker=dict(symbol='triangle-up', size=15, color='#00FF00', line=dict(width=1, color='white')),
                hovertemplate="BUY<br>Time: %{x}<br>Price: $%{y:.2f}<extra></extra>"
            ), row=2, col=1)
            
        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells['datetime_local'], y=sells['price'], 
                mode='markers', name='SELL', 
                marker=dict(symbol='triangle-down', size=15, color='#FF4500', line=dict(width=1, color='white')),
                hovertemplate="SELL<br>Time: %{x}<br>Price: $%{y:.2f}<extra></extra>"
            ), row=2, col=1)
    else:
        fig.add_annotation(x=day_start + timedelta(hours=3), y=0.5, yref="y2", text="NO TRADES FOUND", showarrow=False, font=dict(color="gray", size=20))

    # 3. VIX FRACTAL
    if not vix.empty:
        fig.add_trace(go.Bar(x=vix['datetime_local'], y=vix['hist'], name="Hist", marker_color='rgba(255, 255, 255, 0.3)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix['datetime_local'], y=vix['macd'], name="MACD", line=dict(color='#f1c40f', width=1)), row=3, col=1)

    # 4. VIX RSI
    if not vix.empty:
        fig.add_trace(go.Scatter(x=vix['datetime_local'], y=vix['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5, shape='spline')), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", row=4, col=1)

    # ⚡ ZOOM LOCKED & DARK HOVER
    if day_start:
        fig.update_xaxes(matches='x', range=[day_start, day_end], type='date', fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    
    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=30, b=40), 
        showlegend=True, 
        height=900,
        legend=dict(orientation="h", yanchor="top", y=-0.05, xanchor="center", x=0.5),
        hovermode="x unified",
        font=dict(family="'VT323', monospace", size=14, color="#f3f5f9"),
        hoverlabel=dict(bgcolor="#1e1e1e", font=dict(color="#f3f5f9", family="monospace"))
    )

    return fig, report_html, table_html