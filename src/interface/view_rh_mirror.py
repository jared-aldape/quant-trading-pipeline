import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, no_update
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
from src.utils.logger import get_logger

log = get_logger("RH_Mirror")

TBL_RH_LEDGER = "active_rh_log"
TBL_SIM_LOG = "active_simulation_log"
TBL_INDICES = getattr(config, 'TBL_INDICES', 'indices_1m')
TBL_FUTURES = getattr(config, 'TBL_FUTURES', 'futures_1m')

# Define Timezone locally to ensure safety
TZ_NY = pytz.timezone('America/New_York')

# ==============================================================================
# 1. HELPER FUNCTIONS
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

def fetch_unique_dates(source='rh'):
    """Finds all dates available in the trade logs."""
    try:
        if not config.DB_FILE.exists(): return []
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        target_tbl = TBL_RH_LEDGER if source == 'rh' else TBL_SIM_LOG
        date_col = 'entry_time_utc' if source == 'rh' else 'entry_time'
        
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if target_tbl not in tables: 
            con.close()
            return []

        # ⚡ FIX: Filter by STATUS='FILLED' for RH to match session data
        where_clause = "WHERE status = 'FILLED'" if source == 'rh' else ""

        q = f"""
            SELECT CAST({date_col} AS DATE) as d, COUNT(*) as cnt 
            FROM {target_tbl} 
            {where_clause}
            GROUP BY d 
            ORDER BY d DESC
        """
        df = con.execute(q).df()
        con.close()
        
        if df.empty: return []
        
        return [
            {'label': f"{r['d']} ({r['cnt']} trades)", 'value': str(r['d'])}
            for _, r in df.iterrows()
        ]
    except Exception as e:
        log.error(f"Date Fetch Error: {e}")
        return []

def fetch_session_data(date_str, source='rh'):
    if not config.DB_FILE.exists(): 
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # Sanitize Date
        clean_date_str = str(date_str).split(' ')[0]
        dt_target = datetime.strptime(clean_date_str, '%Y-%m-%d').date()
        
        # RTH Window (NY -> UTC)
        t_open = TZ_NY.localize(datetime.combine(dt_target, time(9, 30)))
        t_close = TZ_NY.localize(datetime.combine(dt_target, time(16, 0)))
        
        s_utc = t_open.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        e_utc = t_close.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        # 1. INDICES (XSP, VIX)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        xsp, vix = pd.DataFrame(), pd.DataFrame()
        
        if TBL_INDICES in tables:
            q_idx = f"""
                SELECT datetime_utc, ticker, open, high, low, close 
                FROM {TBL_INDICES} 
                WHERE ticker IN ('XSP', 'VIX') 
                AND datetime_utc BETWEEN '{s_utc}' AND '{e_utc}'
                ORDER BY datetime_utc
            """
            df_idx = con.execute(q_idx).df()
            
            if not df_idx.empty:
                df_idx['datetime_utc'] = pd.to_datetime(df_idx['datetime_utc'])
                df_idx['datetime_local'] = to_wall_clock(df_idx['datetime_utc'])
                
                xsp = df_idx[df_idx['ticker']=='XSP'].copy()
                if not xsp.empty: xsp = calculate_linreg(xsp)
                
                vix = df_idx[df_idx['ticker']=='VIX'].copy()
                if not vix.empty:
                    vix['macd'] = vix['close'].ewm(span=12).mean() - vix['close'].ewm(span=26).mean()
                    vix['hist'] = vix['macd'] - vix['macd'].ewm(span=9).mean()
                    d = vix['close'].diff()
                    rs = d.clip(lower=0).ewm(com=13).mean() / (-1 * d.clip(upper=0)).ewm(com=13).mean()
                    vix['rsi'] = 100 - (100 / (1 + rs))

        # 2. TRADES
        trades = pd.DataFrame()
        if source == 'rh' and TBL_RH_LEDGER in tables:
            q_trd = f"""
                SELECT entry_time_utc, action, fill_price as price, 
                       root || ' ' || strike || option_right as ticker,
                       quantity
                FROM {TBL_RH_LEDGER}
                WHERE entry_time_utc BETWEEN '{s_utc}' AND '{e_utc}'
                AND status='FILLED'
                ORDER BY entry_time_utc
            """
            trades = con.execute(q_trd).df()
            if not trades.empty:
                trades.rename(columns={'entry_time_utc': 'time_utc'}, inplace=True)
                
        elif source != 'rh' and TBL_SIM_LOG in tables:
            # Fallback for sim
            q_trd = f"""
                SELECT entry_time as time_utc, 'BUY' as action, entry_price as price, ticker, 1 as quantity
                FROM {TBL_SIM_LOG} WHERE entry_time BETWEEN '{s_utc}' AND '{e_utc}'
                UNION ALL
                SELECT exit_time as time_utc, 'SELL' as action, exit_price as price, ticker, 1 as quantity
                FROM {TBL_SIM_LOG} WHERE exit_time BETWEEN '{s_utc}' AND '{e_utc}'
                ORDER BY time_utc
            """
            trades = con.execute(q_trd).df()

        con.close()
        
        if not trades.empty:
            trades['time_utc'] = pd.to_datetime(trades['time_utc'])
            trades['datetime_local'] = to_wall_clock(trades['time_utc'])
            
        return trades, xsp, vix, pd.DataFrame()

    except Exception as e:
        log.error(f"Fetch Session Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# 3. LAYOUT
# ==============================================================================
def render():
    INPUT_STYLE = {'color': '#000', 'backgroundColor': '#fff', 'fontFamily': 'monospace', 'border': '1px solid #ccc'}
    
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("RH MIRROR", className="fw-bold text-white mb-0"),
                html.P("EXECUTION REPLAY | INDEX CONTEXT | TICKER TAPE", className="text-muted small fw-bold mb-0"),
            ], width=8),
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: REFLECTION", className="text-end text-warning font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # CONTROLS
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("1. TARGETING", className="fw-bold small font-monospace"),
                    dbc.CardBody([
                        html.Label("Source", className="small text-muted fw-bold"),
                        dbc.Select(
                            id='mirror-source',
                            options=[{'label': 'RH LEDGER', 'value': 'rh'}, {'label': 'SIMULATION', 'value': 'gen'}],
                            value='rh', style=INPUT_STYLE, className="mb-2"
                        ),
                        html.Label("Date", className="small text-muted fw-bold"), 
                        dbc.Select(id='mirror-date', style=INPUT_STYLE),
                    ])
                ], className="h-100 border-secondary")
            ], width=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("2. PERFORMANCE", className="fw-bold small font-monospace"),
                    dbc.CardBody(id='mirror-report-card', className="d-flex align-items-center justify-content-center h-100")
                ], className="h-100 border-secondary")
            ], width=4),

            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("3. TAPE", className="fw-bold small font-monospace"),
                    dbc.CardBody(id='mirror-table-container', className="p-0", style={"overflowY": "auto", "maxHeight": "150px"})
                ], className="h-100 border-secondary")
            ], width=4)
        ], className="mb-3"),

        # CHART
        dbc.Row([
            dbc.Col([
                dcc.Loading(
                    dcc.Graph(
                        id='mirror-chart', 
                        style={'height': '900px'}, 
                        config={'displayModeBar': True, 'scrollZoom': True}
                    )
                )
            ], width=12)
        ])
    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    [Output('mirror-date', 'options'), Output('mirror-date', 'value')],
    Input('mirror-source', 'value')
)
def update_date_opts(source):
    opts = fetch_unique_dates(source)
    val = opts[0]['value'] if opts else None
    return opts, val

@callback(
    [Output('mirror-chart', 'figure'),
     Output('mirror-report-card', 'children'),
     Output('mirror-table-container', 'children')],
    [Input('mirror-date', 'value')],
    [State('mirror-source', 'value')]
)
def update_mirror_view(date_str, source):
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02, 
                        row_heights=[0.4, 0.2, 0.2, 0.2], 
                        subplot_titles=("XSP Index", "Execution Flow", "VIX MACD", "VIX RSI"))

    if not date_str:
        return fig, "Select Date", []

    trades, xsp, vix, _ = fetch_session_data(date_str, source)
    
    clean_date_str = str(date_str).split(' ')[0]
    dt_base = datetime.strptime(clean_date_str, '%Y-%m-%d')
    day_start = dt_base.replace(hour=6, minute=30)
    day_end = dt_base.replace(hour=13, minute=0)

    # 1. XSP
    if not xsp.empty:
        fig.add_trace(go.Candlestick(x=xsp['datetime_local'], open=xsp['open'], high=xsp['high'], low=xsp['low'], close=xsp['close'], name="XSP"), row=1, col=1)
        if 'reg_line' in xsp.columns:
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Reg"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['upper_band'], line=dict(color='cyan', width=1), name="+2"), row=1, col=1)
            fig.add_trace(go.Scatter(x=xsp['datetime_local'], y=xsp['lower_band'], line=dict(color='cyan', width=1), name="-2"), row=1, col=1)
    else:
        fig.add_annotation(text="MARKET DATA MISSING", row=1, col=1, font=dict(color="red", size=14))

    # 2. TRADES
    total_pnl = 0.0
    pnl_pct = 0.0
    trade_count = len(trades)
    
    if not trades.empty:
        # ⚡ FIX: Case-Insensitive PnL & Percentage
        try:
            trades['action_upper'] = trades['action'].astype(str).str.upper()
            
            # Use Quantity if available, else 100 shares per contract assumption standard
            qty_col = 'quantity' if 'quantity' in trades.columns else None
            
            # Buys
            buy_mask = trades['action_upper'].str.contains('BUY')
            if qty_col:
                buys = (trades.loc[buy_mask, 'price'] * trades.loc[buy_mask, qty_col] * 100).sum()
            else:
                buys = (trades.loc[buy_mask, 'price'] * 100).sum()
                
            # Sells
            sell_mask = trades['action_upper'].str.contains('SELL')
            if qty_col:
                sells = (trades.loc[sell_mask, 'price'] * trades.loc[sell_mask, qty_col] * 100).sum()
            else:
                sells = (trades.loc[sell_mask, 'price'] * 100).sum()
            
            total_pnl = sells - buys
            
            # P/L % Calculation
            if buys > 0:
                pnl_pct = (total_pnl / buys) * 100
            else:
                pnl_pct = 0.0
                
        except Exception as e:
            log.error(f"PnL Calc Error: {e}")
            total_pnl = 0

        # Plot Markers
        for _, t in trades.iterrows():
            t_ts = t['datetime_local']
            y_val = t['price']
            
            # Align marker with XSP price if possible
            if not xsp.empty:
                try:
                    idx = (xsp['datetime_local'] - t_ts).abs().idxmin()
                    y_val = xsp.loc[idx, 'close']
                except: pass

            act = str(t['action']).upper()
            color = 'lime' if 'BUY' in act else 'cyan'
            symbol = 'triangle-up' if 'BUY' in act else 'triangle-down'
            
            fig.add_trace(go.Scatter(
                x=[t_ts], y=[y_val], mode='markers',
                marker=dict(color=color, size=14, symbol=symbol, line=dict(width=2, color='white')),
                name=f"{t['action']}", hoverinfo='text',
                hovertext=f"{t['action']} @ ${t['price']}<br>{t.get('ticker','OPT')}"
            ), row=1, col=1)

    # 3/4. VIX
    if not vix.empty:
        fig.add_trace(go.Bar(x=vix['datetime_local'], y=vix['hist'], name="Hist", marker_color='rgba(255, 255, 255, 0.3)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix['datetime_local'], y=vix['macd'], name="MACD", line=dict(color='#f1c40f', width=1.5)), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix['datetime_local'], y=vix['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5, shape='spline')), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="lime", row=4, col=1)

    # ⚡ FIX: Standardized Hover Label
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
        hoverlabel=dict(
            bgcolor="black", 
            font=dict(color="white", family="monospace"),
            bordercolor="#333"
        )
    )
    
    if day_start:
        fig.update_xaxes(matches='x', range=[day_start, day_end], type='date', fixedrange=True)
    fig.update_yaxes(fixedrange=True)

    # Report HTML with P/L %
    pnl_color = "text-success" if total_pnl >= 0 else "text-danger"
    report_html = html.Div([
        dbc.Row([
            dbc.Col([
                html.Div("TRADES", className="small text-muted"), 
                html.Div(f"{trade_count}", className="fw-bold text-white")
            ], width=4),
            dbc.Col([
                html.Div("EST. PnL", className="small text-muted"), 
                html.Div(f"${total_pnl:,.2f}", className=f"fw-bold {pnl_color}")
            ], width=4),
            dbc.Col([
                html.Div("RETURN", className="small text-muted"), 
                html.Div(f"{pnl_pct:+.2f}%", className=f"fw-bold {pnl_color}")
            ], width=4),
        ])
    ], className="text-center font-monospace w-100")

    # Table
    if not trades.empty:
        tbl_data = trades.copy()
        tbl_data['time'] = tbl_data['datetime_local'].dt.strftime('%H:%M:%S')
        view_cols = ['time', 'action', 'price', 'ticker']
        tbl = dash_table.DataTable(
            data=tbl_data[view_cols].to_dict('records'),
            columns=[{'name': i.upper(), 'id': i} for i in view_cols],
            style_header={'backgroundColor': '#1e293b', 'color': 'white', 'fontWeight': 'bold', 'fontFamily': 'monospace'},
            style_cell={'backgroundColor': '#0f172a', 'color': '#e2e8f0', 'fontFamily': 'monospace', 'fontSize': '12px'},
            page_size=50, style_table={'height': '120px', 'overflowY': 'auto'}
        )
    else:
        tbl = html.Div("No trades recorded.", className="text-muted text-center p-3 font-monospace")
    
    tbl_container = html.Div(tbl, style={'marginBottom': '50px'})

    return fig, report_html, tbl_container
