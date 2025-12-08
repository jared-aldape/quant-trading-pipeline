import dash
from dash import dcc, html, callback, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import duckdb
from datetime import datetime, time, timedelta
import pytz
from src.utils import config

# ==============================================================================
# 1. SCOUT INTELLIGENCE (Navigation Logic)
# ==============================================================================
def fetch_unique_dates(trade_type_filter='call'):
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
        options = []
        for _, row in df.iterrows():
            d_str = row['date'].strftime('%Y-%m-%d')
            label = f"{d_str} ({row['sig_count']} Signals)"
            options.append({'label': label, 'value': d_str})
        return options
    except: return []

def scout_day_performance(date_str, trade_type_filter='call'):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        query = f"""
            SELECT entry_timestamp_utc, signal_type, xsp_price, meta_data 
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{trade_type_filter}' AND date = '{date_str}'
            ORDER BY entry_timestamp_utc ASC
        """
        signals = con.execute(query).df()
        if signals.empty: 
            con.close(); return [], None

        options_list = []
        best_ts = None
        max_gain_overall = -999.0

        for i, row in signals.iterrows():
            ts = row['entry_timestamp_utc']
            entry_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
            date_fmt = entry_dt.strftime('%y%m%d')
            opt_code = 'C' if trade_type_filter == 'call' else 'P'
            strike = int(round(float(row['xsp_price'])) * 1000)
            ticker = f"O:XSP{date_fmt}{opt_code}{strike:08d}"
            
            day_date = entry_dt.date()
            start_str = entry_dt.strftime('%Y-%m-%d %H:%M:%S')
            end_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                pq = f"SELECT open FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' AND datetime_utc >= '{start_str}' AND datetime_utc <= '{end_str}'"
                prices = con.execute(pq).df()
                gain_str = "N/A"
                if not prices.empty:
                    entry_px = prices.iloc[0]['open']
                    max_px = prices['open'].max()
                    gain_val = ((max_px - entry_px) / entry_px) * 100
                    gain_str = f"+{gain_val:.1f}%"
                    if gain_val > max_gain_overall:
                        max_gain_overall = gain_val
                        best_ts = ts
            except:
                gain_str = "--"

            time_str = entry_dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
            clean_meta = str(row['meta_data']).replace('VIX_FRACTAL_LONG', '').replace('VIX_FRACTAL_SHORT', '').strip()
            if "|" in clean_meta: clean_meta = clean_meta.split('|')[-1].strip()
            
            label = f"Signal #{i+1} ({time_str}) | Gain: {gain_str} | {clean_meta}"
            options_list.append({'label': label, 'value': ts})

        con.close()
        return options_list, best_ts
    except: return [], None

# ==============================================================================
# 2. BATTLEFIELD DATA (Chart Data)
# ==============================================================================
def fetch_replay_data(entry_ts_ms):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        row = con.execute(f"SELECT xsp_price, trade_type FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts_ms}").fetchone()
        if not row: return None, None, None, None
        xsp_est, trade_type = row
        
        entry_dt = datetime.fromtimestamp(entry_ts_ms / 1000, tz=pytz.utc).astimezone(config.TZ_NY)
        date_fmt = entry_dt.strftime('%y%m%d')
        opt_code = 'C' if trade_type == 'call' else 'P'
        strike = int(round(float(xsp_est)) * 1000)
        ticker = f"O:XSP{date_fmt}{opt_code}{strike:08d}"

        day_date = entry_dt.date()
        s_str = config.TZ_NY.localize(datetime.combine(day_date, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        e_str = config.TZ_NY.localize(datetime.combine(day_date, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        opt_df = con.execute(f"SELECT datetime_utc, open, close FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        idx_df = con.execute(f"SELECT datetime_utc, ticker, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker IN ('SPX', 'VIX') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        con.close()

        # FIX: Explicit None return if empty to prevent KeyError in consumer
        if opt_df.empty:
            return None, None, None, ticker

        opt_df['dt'] = opt_df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL)
        
        if not idx_df.empty:
            idx_df['dt'] = idx_df['datetime_utc'].dt.tz_localize('UTC').dt.tz_convert(config.TZ_LOCAL)
            spx = idx_df[idx_df['ticker'] == 'SPX'].copy().set_index('dt')
            vix = idx_df[idx_df['ticker'] == 'VIX'].copy().set_index('dt')
            
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
            return spx, vix, opt_df, ticker
            
        return pd.DataFrame(), pd.DataFrame(), opt_df, ticker

    except Exception:
        return None, None, None, None

# ==============================================================================
# 3. LAYOUT (OPTIMIZED)
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("REPLAY ANALYSIS (The Gym)", className="display-6 fw-bold text-white"),
                html.P("Historical simulation with Fog of War.", className="text-muted lead")
            ], width=8),
            dbc.Col([
                html.Label("PROTOCOL SELECTOR", className="fw-bold text-warning small"),
                dbc.RadioItems(
                    id='replay-mode-select-v2',
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

        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("1. MISSION DATE", className="small text-info"),
                        dcc.Dropdown(id='replay-date-dropdown-v2', placeholder="Select Day...", style={'color': '#000'})
                    ], width=5),
                    dbc.Col([
                        html.Label("2. SIGNAL VARIANT (Target)", className="small text-warning"),
                        dcc.Dropdown(id='replay-signal-dropdown-v2', placeholder="Scanning...", style={'color': '#000'})
                    ], width=7)
                ], className="mb-3"),

                dbc.Row([
                    dbc.Col([
                        dbc.ButtonGroup([
                            dbc.Button("▶ Play", id='replay-play-btn-v2', color="success"),
                            dbc.Button("⏸ Pause", id='replay-pause-btn-v2', color="warning"),
                        ], className="me-3")
                    ], width="auto"),
                    dbc.Col([
                        dcc.Slider(id='replay-time-slider-v2', min=0, max=390, step=1, value=0, 
                                   marks={0:'Open', 60:'10:30', 195:'Mid', 330:'15:00', 390:'Close'})
                    ], width=True, className="align-self-center")
                ], className="mb-2"),

                dbc.Row([
                    dbc.Col([
                        dbc.Checklist(options=[{"label": " Reveal Algo Entry", "value": "SHOW"}], value=[], id="replay-reveal-v2", switch=True, className="text-danger fw-bold")
                    ], width=4),
                    dbc.Col([
                        html.Div(id='replay-stats-panel-v2', className="text-end fw-bold text-white")
                    ], width=4),
                    dbc.Col([
                        html.H4(id='replay-clock-v2', children="--:--", className="text-end text-info font-monospace")
                    ], width=4)
                ])
            ])
        ], className="mb-3 shadow-sm", style={'backgroundColor': '#1a1a1a'}),

        dbc.Row([dbc.Col([dcc.Graph(id='replay-chart-v2', style={'height': '800px'})], width=12)]),
        
        dcc.Interval(id='replay-stepper-v2', interval=1000, n_intervals=0, disabled=True),
        dcc.Store(id='replay-state-v2', data={'playing': False})

    ], fluid=True)

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================

@callback(
    [Output('replay-date-dropdown-v2', 'options'), Output('replay-date-dropdown-v2', 'value')],
    Input('replay-mode-select-v2', 'value')
)
def update_dates(mode):
    options = fetch_unique_dates(mode)
    return options, options[0]['value'] if options else None

@callback(
    [Output('replay-signal-dropdown-v2', 'options'), Output('replay-signal-dropdown-v2', 'value')],
    [Input('replay-date-dropdown-v2', 'value'), Input('replay-mode-select-v2', 'value')]
)
def update_signals(date_str, mode):
    if not date_str: return [], None
    options, best = scout_day_performance(date_str, mode)
    return options, best

@callback(
    [Output('replay-stepper-v2', 'disabled'), Output('replay-state-v2', 'data')],
    [Input('replay-play-btn-v2', 'n_clicks'), Input('replay-pause-btn-v2', 'n_clicks')],
    [State('replay-state-v2', 'data')]
)
def toggle_play(play, pause, state):
    if ctx.triggered_id == 'replay-play-btn-v2': return False, {'playing': True}
    return True, {'playing': False}

@callback(
    Output('replay-time-slider-v2', 'value'),
    [Input('replay-stepper-v2', 'n_intervals')],
    [State('replay-time-slider-v2', 'value'), State('replay-time-slider-v2', 'max')]
)
def auto_step(n, val, max_val):
    return val + 5 if val < max_val else val

@callback(
    [Output('replay-chart-v2', 'figure'), 
     Output('replay-clock-v2', 'children'),
     Output('replay-stats-panel-v2', 'children')],
    [Input('replay-signal-dropdown-v2', 'value'), 
     Input('replay-time-slider-v2', 'value'), 
     Input('replay-reveal-v2', 'value')]
)
def update_replay_unified(entry_ts, minutes, reveal):
    if not entry_ts: return go.Figure(), "--:--", ""

    spx, vix, opt, ticker = fetch_replay_data(entry_ts)
    
    # FIX: Handle Missing Data Gracefully
    if opt is None or opt.empty: 
        fig = go.Figure()
        fig.update_layout(
            template="plotly_dark", 
            title=dict(text="⚠️ OPTION DATA MISSING<br>Run ingest_options.py", x=0.5, y=0.5, font=dict(color="red", size=20)),
            xaxis={'visible': False}, yaxis={'visible': False}
        )
        return fig, "No Data", "N/A"

    entry_dt = datetime.fromtimestamp(entry_ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
    market_open = config.TZ_NY.localize(datetime.combine(entry_dt.date(), time(9, 30)))
    
    current_time_ny = market_open + timedelta(minutes=minutes)
    current_time_local = current_time_ny.astimezone(config.TZ_LOCAL)
    
    # Fog of War Slicing
    spx_slice = spx[spx.index <= current_time_local] if spx is not None else pd.DataFrame()
    vix_slice = vix[vix.index <= current_time_local] if vix is not None else pd.DataFrame()
    opt_slice = opt[opt['dt'] <= current_time_local]

    stats_msg = "WAITING FOR ENTRY..."
    try:
        entry_local = entry_dt.astimezone(config.TZ_LOCAL)
        if current_time_local >= entry_local:
            entry_px_row = opt.iloc[opt['dt'].sub(entry_local).abs().argsort()[:1]]
            entry_px = entry_px_row['close'].values[0]
            
            if not opt_slice.empty:
                curr_px = opt_slice.iloc[-1]['close']
                pnl = ((curr_px - entry_px) / entry_px) * 100
                color = "#00bc8c" if pnl >= 0 else "#e74c3c"
                stats_msg = html.Span(f"PNL: {pnl:+.2f}% (${curr_px:.2f})", style={'color': color, 'fontSize': '1.2rem'})
    except:
        stats_msg = "CALC ERROR"

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.35, 0.25, 0.2, 0.2],
                        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
                        subplot_titles=("Context: SPX (Price Action)", f"Execution: {ticker}", "VIX Fractal Flow", "VIX RSI"))

    if not spx_slice.empty:
        fig.add_trace(go.Candlestick(x=spx_slice.index, open=spx_slice['open'], high=spx_slice['high'], low=spx_slice['low'], close=spx_slice['close'], name="SPX", increasing_line_color='#00bc8c', decreasing_line_color='#e74c3c'), row=1, col=1)

    if not opt_slice.empty:
        fig.add_trace(go.Scatter(x=opt_slice['dt'], y=opt_slice['close'], name="Option Price", line=dict(color='white', width=2)), row=2, col=1, secondary_y=False)
        
        if reveal and 'SHOW' in reveal:
            entry_local = entry_dt.astimezone(config.TZ_LOCAL)
            if current_time_local >= entry_local:
                fig.add_vline(x=entry_local, line_dash="dash", line_color="yellow", row=2, col=1)
                try:
                    price_at_entry = opt.iloc[opt['dt'].sub(entry_local).abs().argsort()[:1]]['close'].values[0]
                    fig.add_trace(go.Scatter(x=[entry_local], y=[price_at_entry], mode='markers', marker=dict(color='yellow', size=12, symbol='star'), name="ENTRY SIGNAL"), row=2, col=1)
                except: pass

    if not vix_slice.empty:
        fig.add_trace(go.Bar(x=vix_slice.index, y=vix_slice['hist'], name="Macro (1h)", marker_color='rgba(255, 255, 255, 0.2)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_slice.index, y=vix_slice['macd'], name="Micro (5m)", line=dict(color='#f1c40f', width=1)), row=3, col=1)

    if not vix_slice.empty:
        fig.add_trace(go.Scatter(x=vix_slice.index, y=vix_slice['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5)), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#e74c3c", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=50, r=50, t=30, b=50), 
        showlegend=False, 
        height=900,
        uirevision='dataset'
    )
    fig.update_xaxes(rangeslider_visible=False)
    
    return fig, current_time_local.strftime('%H:%M %Z'), stats_msg