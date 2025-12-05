import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import duckdb
from datetime import datetime, time
import pytz
from src.utils import config

# ==============================================================================
# 1. DATA INGESTION (THE FORENSICS)
# ==============================================================================
def fetch_unique_dates(trade_type_filter='call'):
    """Stage 1: Get unique dates. (Optimized for speed - no deep P&L calc here)"""
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        query = f"""
            SELECT date, COUNT(*) as sig_count
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{trade_type_filter}'
            GROUP BY date
            ORDER BY date DESC
        """
        df = con.execute(query).df()
        con.close()
        
        if df.empty: return []
        
        # Format: "2025-11-25 (3 Signals)"
        options = []
        for _, row in df.iterrows():
            d_str = row['date'].strftime('%Y-%m-%d')
            label = f"{d_str} ({row['sig_count']} Signals)"
            options.append({'label': label, 'value': d_str})
            
        return options
    except Exception:
        return []

def scout_day_performance(date_str, trade_type_filter='call'):
    """
    Stage 2 (THE SCOUT): Fetches signals AND calculates max P&L for each.
    Auto-ranks the best trade for the dropdown default.
    """
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Get Signals
        query = f"""
            SELECT entry_timestamp_utc, signal_type, xsp_price, meta_data 
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{trade_type_filter}' 
            AND date = '{date_str}'
            ORDER BY entry_timestamp_utc ASC
        """
        signals = con.execute(query).df()
        
        if signals.empty: 
            con.close()
            return [], None

        # 2. Batch Calc P&L
        options_list = []
        best_ts = None
        max_gain_overall = -999.0

        for i, row in signals.iterrows():
            ts = row['entry_timestamp_utc']
            
            # Reconstruct Ticker
            entry_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
            date_fmt = entry_dt.strftime('%y%m%d')
            opt_code = 'C' if trade_type_filter == 'call' else 'P'
            strike = int(round(float(row['xsp_price'])) * 1000)
            ticker = f"O:XSP{date_fmt}{opt_code}{strike:08d}"
            
            # Query Price Path (Fast Limit)
            day_date = entry_dt.date()
            start_str = entry_dt.strftime('%Y-%m-%d %H:%M:%S') # From entry...
            end_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S') # ...to close
            
            pq = f"SELECT open FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}'"
            prices = con.execute(pq).df()
            
            gain_str = "N/A"
            gain_val = -100.0
            
            if not prices.empty:
                entry_px = prices.iloc[0]['open']
                max_px = prices['open'].max()
                gain_val = ((max_px - entry_px) / entry_px) * 100
                gain_str = f"+{gain_val:.1f}%"
            
            # Track Best
            if gain_val > max_gain_overall:
                max_gain_overall = gain_val
                best_ts = ts

            # Format Label: "Signal #1 (+24.5%) | VIX CRUSH..."
            time_str = entry_dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
            clean_meta = row['meta_data'].replace('VIX_FRACTAL_LONG', '').replace('VIX_FRACTAL_SHORT', '').strip()
            # Clean up the meta string if it duplicates info
            if "|" in clean_meta: clean_meta = clean_meta.split('|')[-1].strip()
            
            label = f"Signal #{i+1} ({time_str}) | Gain: {gain_str} | {clean_meta}"
            options_list.append({'label': label, 'value': ts})

        con.close()
        return options_list, best_ts

    except Exception as e:
        print(f"Scout Error: {e}")
        return [], None

def fetch_trade_performance(entry_ts_ms, trade_type, xsp_price):
    try:
        date_obj = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        date_str = date_obj.strftime('%y%m%d')
        opt_type = 'C' if trade_type == 'call' else 'P'
        strike_raw = round(float(xsp_price))
        strike_str = f"{int(strike_raw * 1000):08d}"
        ticker = f"O:XSP{date_str}{opt_type}{strike_str}"

        day_date = date_obj.date()
        start_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        end_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        query = f"SELECT datetime_utc, open FROM {config.TBL_OPTIONS} WHERE ticker = '{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}' ORDER BY datetime_utc ASC"
        df = con.execute(query).df()
        con.close()

        if df.empty: return None, ticker

        entry_dt_utc = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc)
        try:
            entry_row = df.iloc[df['datetime_utc'].sub(entry_dt_utc).abs().argsort()[:1]]
            entry_price = entry_row['open'].values[0]
        except: entry_price = df.iloc[0]['open']

        df['pnl_pct'] = ((df['open'] - entry_price) / entry_price) * 100
        df['datetime_local'] = df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL)
        return df, ticker
    except Exception: return None, "ERROR"

def fetch_indicators(entry_ts_ms):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        entry_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        day_date = entry_dt.date()
        s_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        e_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        df_idx = con.execute(f"SELECT datetime_utc, ticker, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker IN ('VIX', 'SPX') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        try: df_fut = con.execute(f"SELECT datetime_utc, ticker, close FROM {config.TBL_FUTURES} WHERE ticker = 'ES' AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        except: df_fut = pd.DataFrame()
        con.close()
        
        if df_idx.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        df_idx['datetime_local'] = df_idx['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL)
        vix = df_idx[df_idx['ticker'] == 'VIX'].copy().set_index('datetime_local')
        spx = df_idx[df_idx['ticker'] == 'SPX'].copy().set_index('datetime_local')
        
        es = pd.DataFrame()
        if not df_fut.empty:
            df_fut['datetime_local'] = df_fut['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL)
            # FIX 1: Removed division by 10 to match SPX price levels
            df_fut['scaled_close'] = df_fut['close']
            es = df_fut.set_index('datetime_local')

        vix['ema12'] = vix['close'].ewm(span=12).mean()
        vix['ema26'] = vix['close'].ewm(span=26).mean()
        vix['macd'] = vix['ema12'] - vix['ema26']
        vix['signal'] = vix['macd'].ewm(span=9).mean()
        vix['hist'] = vix['macd'] - vix['signal']
        
        delta = vix['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        vix['rsi'] = 100 - (100 / (1 + rs))

        return spx, vix, es
    except Exception: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# 2. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("CHART ANALYSIS (Tactical Forensics)", className="display-6 fw-bold text-white"),
                html.P("Visual validation of the Hedged Protocol.", className="text-muted lead")
            ], width=8),
            dbc.Col([
                html.Label("PROTOCOL SELECTOR", className="fw-bold text-warning small"),
                dbc.RadioItems(
                    id='chart-mode-select',
                    options=[{'label': '🟢 BULLISH (Calls)', 'value': 'call'}, {'label': '🔴 BEARISH (Puts)', 'value': 'put'}],
                    value='call',
                    inline=True,
                    class_name="btn-group",
                    input_class_name="btn-check",
                    label_class_name="btn btn-outline-secondary",
                    label_checked_class_name="active"
                )
            ], width=4, className="text-end pt-2")
        ], className="mb-3"),

        dbc.Card([dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Label("1. MISSION DATE", className="small text-info"), 
                    dcc.Dropdown(id='chart-date-dropdown', placeholder="Select Day...", style={'color': '#000'})
                ], width=5),
                dbc.Col([
                    html.Label("2. SIGNAL VARIANT (Auto-Optimized)", className="small text-warning"), 
                    dcc.Dropdown(id='chart-signal-dropdown', placeholder="Scanning options...", style={'color': '#000'})
                ], width=7)
            ])
        ])], className="mb-3 shadow-sm", style={'backgroundColor': '#1a1a1a'}),

        dbc.Row([dbc.Col([dcc.Loading(dcc.Graph(id='chart-main-display', style={'height': '900px'}, config={'displayModeBar': False}))], width=12)])
    ], fluid=True)

# ==============================================================================
# 3. CALLBACKS
# ==============================================================================
@callback(
    [Output('chart-date-dropdown', 'options'), Output('chart-date-dropdown', 'value')],
    Input('chart-mode-select', 'value')
)
def update_date_dropdown(mode):
    options = fetch_unique_dates(mode)
    return options, options[0]['value'] if options else None

@callback(
    [Output('chart-signal-dropdown', 'options'), Output('chart-signal-dropdown', 'value')],
    [Input('chart-date-dropdown', 'value'), Input('chart-mode-select', 'value')]
)
def update_signal_dropdown(date_str, mode):
    if not date_str: return [], None
    # THE SCOUT: Returns options list AND the 'value' of the best performer
    options, best_val = scout_day_performance(date_str, mode)
    return options, best_val

@callback(
    Output('chart-main-display', 'figure'),
    [Input('chart-signal-dropdown', 'value')],
    [State('chart-mode-select', 'value')]
)
def update_chart(entry_ts, mode):
    if not entry_ts: return go.Figure()

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    res = con.execute(f"SELECT xsp_price, trade_type FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts}").fetchone()
    con.close()
    if not res: return go.Figure()
    
    xsp_est, trade_type = res[0], res[1]
    opt_df, ticker = fetch_trade_performance(entry_ts, trade_type, xsp_est)
    spx_df, vix_df, es_df = fetch_indicators(entry_ts)

    if opt_df is None or spx_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="MARKET DATA UNAVAILABLE", showarrow=False, font=dict(size=20, color="red"))
        return fig

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.3, 0.25, 0.25, 0.2], 
                        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
                        subplot_titles=("CONTEXT: SPX vs /ES", f"STRATEGY: {ticker}", "VIX FRACTAL FLOW", "VIX RSI"))

    # 1. SPX + ES
    fig.add_trace(go.Candlestick(x=spx_df.index, open=spx_df['open'], high=spx_df['high'], low=spx_df['low'], close=spx_df['close'], name="SPX"), row=1, col=1)
    if not es_df.empty:
        fig.add_trace(go.Scatter(x=es_df.index, y=es_df['scaled_close'], name="/ES Futures", line=dict(color='#00d2ff', width=1, dash='dot')), row=1, col=1)

    # 2. P&L + PRICE
    colors = ['rgba(0, 188, 140, 0.3)' if v >= 0 else 'rgba(231, 76, 60, 0.3)' for v in opt_df['pnl_pct']]
    fig.add_trace(go.Bar(x=opt_df['datetime_local'], y=opt_df['pnl_pct'], name="P&L %", marker_color=colors), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=opt_df['datetime_local'], y=opt_df['open'], name="Option Price", line=dict(color='white', width=1.5)), row=2, col=1, secondary_y=True)
    
    # Max Gain
    if not opt_df.empty:
        max_gain = opt_df['pnl_pct'].max()
        max_idx = opt_df['pnl_pct'].idxmax()
        if max_gain > 0:
            fig.add_annotation(x=opt_df.loc[max_idx, 'datetime_local'], y=max_gain, text=f"PEAK +{max_gain:.1f}%", showarrow=True, arrowhead=1, row=2, col=1, secondary_y=False)

    # 3. MACD
    fig.add_trace(go.Bar(x=vix_df.index, y=vix_df['hist'], name="Macro (1h)", marker_color='rgba(255, 255, 255, 0.2)'), row=3, col=1)
    fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['macd'], name="Micro (5m)", line=dict(color='#f1c40f', width=1)), row=3, col=1)

    # 4. RSI
    fig.add_trace(go.Scatter(x=vix_df.index, y=vix_df['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5)), row=4, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="#e74c3c", row=4, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    entry_dt = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc).astimezone(config.TZ_LOCAL)
    fig.add_vline(x=entry_dt, line_width=1, line_dash="dash", line_color="yellow")
    
    # FIX 2: Moved legend to bottom (horizontal) and increased bottom margin
    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=50, r=50, t=30, b=100), 
        showlegend=True, 
        height=900,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.05,
            xanchor="center",
            x=0.5
        )
    )
    
    fig.update_xaxes(rangeslider_visible=False, rangebreaks=[dict(bounds=["16:00", "09:30"], pattern="hour"), dict(bounds=["sat", "mon"])])
    return fig