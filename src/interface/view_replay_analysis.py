import dash
from dash import dcc, html, callback, Input, Output, State, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import duckdb
from datetime import datetime, time, timedelta
import pytz
import pathlib
import sys
import numpy as np

# ==============================================================================
# 1. PATH & CONFIG SETUP
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

# ==============================================================================
# 2. HELPER FUNCTIONS
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

def fetch_unique_dates(trade_type_filter='call'):
    """
    Fetches ALL trading dates from XSP data, merging with signal counts.
    Ensures 'No Signal' days are visible for review.
    """
    try:
        if not config.DB_FILE.exists(): return []
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_INDICES not in tables: 
             con.close(); return []

        t_filter = trade_type_filter.upper()
        
        # 1. Get ALL valid trading days from XSP (implicitly handles weekends/holidays)
        q_dates = f"SELECT DISTINCT CAST(datetime_utc AS DATE) as d FROM {config.TBL_INDICES} WHERE ticker='XSP' ORDER BY d DESC"
        df_dates = con.execute(q_dates).df()
        
        # 2. Get Signal Counts
        q_signals = f"""
            SELECT date, COUNT(*) as sig_count
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{t_filter}'
            GROUP BY date
        """
        try:
            df_sigs = con.execute(q_signals).df()
        except:
            df_sigs = pd.DataFrame(columns=['date', 'sig_count'])
            
        con.close()
        
        if df_dates.empty: return []
        
        # Merge
        df_dates['d'] = pd.to_datetime(df_dates['d'])
        df_sigs['date'] = pd.to_datetime(df_sigs['date'])
        
        merged = pd.merge(df_dates, df_sigs, left_on='d', right_on='date', how='left')
        merged['sig_count'] = merged['sig_count'].fillna(0).astype(int)
        
        options = []
        for _, row in merged.iterrows():
            d_str = row['d'].strftime('%Y-%m-%d')
            count = row['sig_count']
            if count > 0:
                label = f"{d_str} ({count} Signals)"
            else:
                label = f"{d_str} (No Signals)"
            options.append({'label': label, 'value': d_str})
            
        return options
    except Exception as e: 
        print(f"Date Fetch Error: {e}")
        return []

def scout_day_performance(date_str, trade_type_filter='call'):
    """
    Returns signals for a day. If no signals, returns a default 09:30 start point.
    """
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        t_type = trade_type_filter.upper()
        
        # Check for actual signals
        query = f"""
            SELECT entry_timestamp_utc, signal_type, xsp_price, meta_data 
            FROM {config.TBL_MANIFEST}
            WHERE trade_type = '{t_type}' 
            AND date = '{date_str}'
            ORDER BY entry_timestamp_utc ASC
        """
        try:
            signals = con.execute(query).df()
        except:
            signals = pd.DataFrame()
        con.close()
        
        options_list = []
        best_ts = None

        if not signals.empty:
            for i, row in signals.iterrows():
                ts = row['entry_timestamp_utc']
                entry_dt = datetime.fromtimestamp(ts/1000, tz=pytz.utc).astimezone(config.TZ_NY)
                time_str = entry_dt.astimezone(config.TZ_LOCAL).strftime('%H:%M')
                clean_meta = str(row['meta_data']).replace('VIX_FRACTAL_LONG', '').replace('VIX_FRACTAL_SHORT', '').strip()
                if "|" in clean_meta: clean_meta = clean_meta.split('|')[-1].strip()
                
                label = f"Signal #{i+1} ({time_str}) | {clean_meta}"
                options_list.append({'label': label, 'value': ts})
                if i == 0: best_ts = ts
        else:
            # NO SIGNALS: Create a "Market Open" anchor
            dt = datetime.strptime(date_str, '%Y-%m-%d').date()
            # 9:30 AM NY Time
            open_ny = config.TZ_NY.localize(datetime.combine(dt, time(9, 30)))
            ts = open_ny.timestamp() * 1000
            options_list.append({'label': "09:30 Market Open (Review Mode)", 'value': ts})
            best_ts = ts

        return options_list, best_ts
    except Exception as e:
        print(f"Scout Error: {e}")
        return [], None

def fetch_available_strikes_for_replay(entry_ts, trade_type):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Try to find price in Manifest (Signal Exists)
        res = con.execute(f"SELECT xsp_price, date FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts}").fetchone()
        
        xsp_price = 0
        date_val = None
        
        if res:
            xsp_price, date_val = res
        else:
            # 2. Fallback: Find price in Indices (Manual Review)
            entry_dt_utc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc)
            date_val = entry_dt_utc.date()
            
            # Find closest 1m candle
            s_str = entry_dt_utc.strftime('%Y-%m-%d %H:%M:%S')
            q_price = f"SELECT close FROM {config.TBL_INDICES} WHERE ticker='XSP' AND datetime_utc <= '{s_str}' ORDER BY datetime_utc DESC LIMIT 1"
            px_res = con.execute(q_price).fetchone()
            if px_res: xsp_price = px_res[0]
            else: 
                con.close(); return [], None

        target_strike = round(float(xsp_price))
        
        dt = date_val if isinstance(date_val, (datetime, pd.Timestamp)) else datetime.strptime(str(date_val), '%Y-%m-%d')
        date_fmt = dt.strftime('%y%m%d')
        opt_code = 'C' if trade_type.upper() == 'CALL' else 'P'
        
        like_pattern = f"O:XSP{date_fmt}{opt_code}%"
        tickers = con.execute(f"SELECT DISTINCT ticker FROM {config.TBL_OPTIONS} WHERE ticker LIKE '{like_pattern}'").fetchall()
        con.close()
        
        if not tickers: return [], None
        
        temp_options = []
        atm_ticker = None
        min_dist = float('inf')
        
        for t in tickers:
            ticker = t[0]
            try:
                strike_val = int(ticker[-8:]) / 1000.0
                diff = strike_val - target_strike
                
                if diff == 0: label = f"{strike_val:.0f} (ATM)"
                elif diff > 0: label = f"{strike_val:.0f} (+{int(diff)})"
                else: label = f"{strike_val:.0f} ({int(diff)})"
                
                temp_options.append({'label': label, 'value': ticker, 'strike': strike_val})
                
                if abs(diff) < min_dist:
                    min_dist = abs(diff)
                    atm_ticker = ticker
            except: continue
            
        temp_options.sort(key=lambda x: x['strike'])
        final_options = [{'label': x['label'], 'value': x['value']} for x in temp_options]
        
        return final_options, atm_ticker

    except Exception as e:
        print(f"Strike Fetch Error: {e}")
        return [], None

# ==============================================================================
# 3. DATA LOADING
# ==============================================================================
def load_replay_tape(entry_ts, ticker_override=None):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # 1. Try Manifest
        res = None
        try:
            res = con.execute(f"SELECT xsp_price, trade_type, date FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc={entry_ts}").fetchone()
        except: pass

        if res:
            xsp_est, trade_type, date_val = res
        else:
            # 2. Fallback for Manual Review
            entry_dt_utc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc)
            date_val = entry_dt_utc.date()
            trade_type = 'CALL' # Default, overriden by ticker_override usually
            
            # Estimate price
            s_str = entry_dt_utc.strftime('%Y-%m-%d %H:%M:%S')
            px_res = con.execute(f"SELECT close FROM {config.TBL_INDICES} WHERE ticker='XSP' AND datetime_utc <= '{s_str}' ORDER BY datetime_utc DESC LIMIT 1").fetchone()
            xsp_est = px_res[0] if px_res else 0

        dt = date_val if isinstance(date_val, (datetime, pd.Timestamp)) else datetime.strptime(str(date_val), '%Y-%m-%d').date()
        s_str = config.TZ_NY.localize(datetime.combine(dt, time(9, 30))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        e_str = config.TZ_NY.localize(datetime.combine(dt, time(16, 0))).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        # Indices
        df_idx = con.execute(f"SELECT datetime_utc, ticker, open, high, low, close FROM {config.TBL_INDICES} WHERE ticker IN ('VIX', 'XSP') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        
        # Futures
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        tbl_fut = getattr(config, 'TBL_FUTURES', 'futures_1m')
        if tbl_fut in tables:
             try: 
                 df_fut = con.execute(f"SELECT datetime_utc, ticker, close FROM {tbl_fut} WHERE (ticker LIKE 'ES%' OR ticker = '/ES') AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
             except: df_fut = pd.DataFrame()
        else:
             df_fut = pd.DataFrame()

        # Options
        if ticker_override:
            ticker = ticker_override
        else:
            date_fmt = dt.strftime('%y%m%d')
            opt_code = 'C' if trade_type == 'CALL' else 'P'
            strike = int(round(float(xsp_est)) * 1000)
            ticker = f"O:XSP{date_fmt}{opt_code}{strike:08d}"
        
        if config.TBL_OPTIONS in tables:
            df_opt = con.execute(f"SELECT datetime_utc, open, high, low, close FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' AND datetime_utc >= '{s_str}' AND datetime_utc <= '{e_str}' ORDER BY datetime_utc ASC").df()
        else:
            df_opt = pd.DataFrame()
            
        con.close()
        
        # Process XSP
        xsp = pd.DataFrame()
        if not df_idx.empty and 'XSP' in df_idx['ticker'].values:
            xsp = df_idx[df_idx['ticker'] == 'XSP'].copy()
            xsp['datetime_local'] = to_wall_clock(pd.to_datetime(xsp['datetime_utc']))
            xsp = xsp.sort_values('datetime_local')
            xsp['sma_50'] = xsp['close'].rolling(50).mean()
            xsp = calculate_linreg(xsp)
            # OPTIMIZATION: Round floats
            cols_to_round = ['open', 'high', 'low', 'close', 'sma_50', 'reg_line', 'upper_band', 'lower_band']
            for c in cols_to_round:
                if c in xsp.columns: xsp[c] = xsp[c].round(2)

        # Process VIX
        vix = pd.DataFrame()
        if not df_idx.empty and 'VIX' in df_idx['ticker'].values:
            vix = df_idx[df_idx['ticker'] == 'VIX'].copy()
            vix['datetime_local'] = to_wall_clock(pd.to_datetime(vix['datetime_utc']))
            vix = vix.sort_values('datetime_local')
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
            # OPTIMIZATION: Round VIX metrics
            for c in ['close', 'macd', 'signal', 'hist', 'rsi']:
                if c in vix.columns: vix[c] = vix[c].round(3)

        # Process ES
        es = pd.DataFrame()
        if not df_fut.empty:
            es = df_fut.copy()
            es['datetime_local'] = to_wall_clock(pd.to_datetime(es['datetime_utc']))
            es = es.sort_values('datetime_local')
            es['scaled_close'] = es['close'] / 10.0
            es['scaled_close'] = es['scaled_close'].round(2)

        # Process Options
        opt = pd.DataFrame()
        entry_price = 0
        max_gain = 0.0
        
        if not df_opt.empty:
            opt = df_opt.copy()
            opt['datetime_local'] = to_wall_clock(pd.to_datetime(opt['datetime_utc']))
            opt = opt.sort_values('datetime_local')
            entry_dt_wc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc).astimezone(config.TZ_LOCAL).replace(tzinfo=None)
            try:
                idx = opt['datetime_local'].sub(entry_dt_wc).abs().idxmin()
                entry_price = opt.loc[idx, 'open']
                # Calculate Max Gain
                post_entry = opt.loc[idx:]
                max_price = post_entry['open'].max() if not post_entry.empty else entry_price
                if entry_price > 0.05:
                    max_gain = ((max_price - entry_price) / entry_price) * 100
            except:
                entry_price = opt.iloc[0]['open'] if len(opt) > 0 else 1.0
                
            entry_price_safe = entry_price if entry_price > 0.05 else 9999.9
            opt['pnl_pct'] = ((opt['open'] - entry_price) / entry_price_safe) * 100
            
            # OPTIMIZATION: Round Option Data
            for c in ['open', 'high', 'low', 'close', 'pnl_pct']:
                if c in opt.columns: opt[c] = opt[c].round(2)

        if xsp.empty: return None
        
        packet = {
            'xsp': xsp.to_dict('records'),
            'vix': vix.to_dict('records'),
            'es': es.to_dict('records'),
            'opt': opt.to_dict('records'),
            'entry_ts': entry_ts,
            'ticker': ticker,
            'entry_price': round(entry_price, 2),
            'max_gain': round(max_gain, 1)
        }
        return packet

    except Exception as e:
        print(f"Tape Load Error: {e}")
        return None

# ==============================================================================
# 4. LAYOUT
# ==============================================================================
def render():
    # REMOVED: Crash-prone html.Style block
    # STYLES ARE NOW HANDLED BY assets/custom_style.css

    return dbc.Container([
        # --- TITLE ROW ---
        dbc.Row([
            dbc.Col([
                html.H2("CHRONICLES COMMAND", className="magitek-h2"),
                html.P("REPLAY ANALYSIS | HISTORICAL SIMULATION", className="magitek-note"),
                html.Div([
                    html.Span("PROTOCOL: ", className="fw-bold text-warning small me-2 font-monospace"),
                    dbc.RadioItems(
                        id='replay-mode-select',
                        options=[{'label': 'CALLS', 'value': 'call'}, {'label': 'PUTS', 'value': 'put'}],
                        value='call',
                        inline=True,
                        class_name="btn-group",
                        input_class_name="btn-check",
                        label_class_name="btn btn-outline-secondary btn-sm font-monospace",
                        label_checked_class_name="active"
                    )
                ], className="d-inline-block mt-1")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: REPLAY", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9", "backgroundColor": "#283878", "color": "#f3f5f9"}),

        # CONTROLS DECK
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    # COL 1: TARGETING
                    dbc.Col([
                        html.Label("1. Mission Date", className="small text-muted font-monospace"),
                        dcc.Dropdown(id='replay-date-dropdown', placeholder="Select Day...", className="mb-2"),
                        html.Label("2. Target Signal", className="small text-muted font-monospace"),
                        dcc.Dropdown(id='replay-signal-dropdown', placeholder="Loading...", className="mb-2"),
                        html.Label("3. Strike Selection", className="small text-muted font-monospace"),
                        dcc.Dropdown(id='replay-strike-dropdown', placeholder="Select Strike...", style={"fontFamily": "monospace"})
                    ], width=4),
                    
                    # COL 2: VCR CONTROLS
                    dbc.Col([
                        html.Label("4. Playback Controls", className="small text-muted d-block font-monospace"),
                        dbc.ButtonGroup([
                            dbc.Button("▶ PLAY", id="btn-play", color="success", n_clicks=0, className="font-monospace"),
                            dbc.Button("⏸ PAUSE", id="btn-pause", color="warning", n_clicks=0, className="font-monospace"),
                            dbc.Button("⏪ RESET", id="btn-reset", color="danger", n_clicks=0, className="font-monospace"),
                        ], className="me-2 mb-2 w-100"),
                        
                        html.Div([
                             html.Label("Speed:", className="small text-muted me-2 font-monospace"),
                             dbc.RadioItems(
                                id="speed-selector",
                                options=[
                                    {"label": "1x", "value": 1000},
                                    {"label": "5x", "value": 200},
                                    {"label": "MAX", "value": 50},
                                ],
                                value=200, 
                                inline=True,
                                className="font-monospace text-white"
                            )
                        ], className="text-center")
                    ], width=4),

                    # COL 3: BLIND MODE & STATUS
                    dbc.Col([
                        html.Label("5. Blind Mode", className="small text-muted d-block font-monospace"),
                        dbc.Checklist(
                            options=[{"label": "REVEAL STRATEGY (Show Options Data)", "value": "show"}],
                            value=[], # Default OFF (Blind)
                            id="show-signal-toggle",
                            switch=True,
                            inputClassName="form-check-input",
                            labelClassName="form-check-label text-warning fw-bold font-monospace"
                        ),
                        html.H2(id="clock-display", className="text-info text-end mt-2 font-monospace", children="09:30"),
                        html.Div(id="frame-info", className="text-end text-muted small font-monospace", children="Frame: 0"),
                        html.Div(id="combat-metric-display", className="mt-2 font-monospace")
                    ], width=4)
                ]),
                
                # TIMELINE SLIDER
                dbc.Row([
                    dbc.Col([
                        dcc.Slider(
                            id='timeline-slider',
                            min=0, max=390, step=1, value=0,
                            marks={0: 'Open', 390: 'Close'},
                            tooltip={"placement": "bottom", "always_visible": True}
                        )
                    ], width=12, className="mt-3")
                ])
            ])
        ], className="mb-3 shadow-sm"),

        # CHART
        dbc.Row([dbc.Col([dcc.Graph(id='replay-chart', style={'height': '900px'}, config={'displayModeBar': True})], width=12)]),

        # HIDDEN STORES
        dcc.Store(id='replay-tape-store'),
        dcc.Interval(id='replay-interval', interval=1000, n_intervals=0, disabled=True)
        
    ], fluid=True)

# ==============================================================================
# 5. CALLBACKS
# ==============================================================================

# A. Populate Dropdowns
@callback(
    [Output('replay-date-dropdown', 'options'), Output('replay-date-dropdown', 'value')],
    Input('replay-mode-select', 'value')
)
def update_date_options(mode):
    options = fetch_unique_dates(mode)
    return options, options[0]['value'] if options else None

@callback(
    [Output('replay-signal-dropdown', 'options'), Output('replay-signal-dropdown', 'value')],
    [Input('replay-date-dropdown', 'value'), Input('replay-mode-select', 'value')]
)
def update_signal_options(date_str, mode):
    if not date_str: return [], None
    options, best_ts = scout_day_performance(date_str, mode)
    return options, best_ts

@callback(
    [Output('replay-strike-dropdown', 'options'), Output('replay-strike-dropdown', 'value')],
    [Input('replay-signal-dropdown', 'value')],
    [State('replay-mode-select', 'value')]
)
def update_strike_options(entry_ts, mode):
    if not entry_ts: return [], None
    options, atm_ticker = fetch_available_strikes_for_replay(entry_ts, mode)
    return options, atm_ticker

# B. Load Tape (Added allow_duplicate to timeline-slider)
@callback(
    [Output('replay-tape-store', 'data'),
     Output('timeline-slider', 'max'),
     Output('timeline-slider', 'value', allow_duplicate=True),
     Output('btn-play', 'disabled')],
    [Input('replay-signal-dropdown', 'value'),
     Input('replay-strike-dropdown', 'value')],
    prevent_initial_call=True
)
def load_tape(entry_ts, ticker):
    if not entry_ts: return no_update, 390, 0, True
    packet = load_replay_tape(entry_ts, ticker)
    if not packet: return None, 390, 0, True
    max_steps = len(packet['xsp']) - 1
    return packet, max_steps, 0, False

# C. VCR Logic (Added allow_duplicate to replay-interval)
@callback(
    [Output('replay-interval', 'disabled', allow_duplicate=True),
     Output('replay-interval', 'interval'),
     Output('timeline-slider', 'value', allow_duplicate=True)],
    [Input('btn-play', 'n_clicks'),
     Input('btn-pause', 'n_clicks'),
     Input('btn-reset', 'n_clicks'),
     Input('speed-selector', 'value')], 
    [State('replay-interval', 'disabled')],
    prevent_initial_call=True
)
def control_playback(play, pause, reset, speed, is_disabled):
    ctx = dash.callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    trig_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    speed_ms = int(speed) if speed else 200

    if trig_id == 'btn-play': return False, speed_ms, no_update
    elif trig_id == 'btn-pause': return True, speed_ms, no_update
    elif trig_id == 'btn-reset': return True, speed_ms, 0
    elif trig_id == 'speed-selector': return no_update, speed_ms, no_update
    
    return no_update, no_update, no_update

# D. Render Frame
@callback(
    [Output('replay-chart', 'figure'),
     Output('clock-display', 'children'),
     Output('frame-info', 'children'),
     Output('timeline-slider', 'value', allow_duplicate=True),
     Output('replay-interval', 'disabled', allow_duplicate=True),
     Output('combat-metric-display', 'children')],
    [Input('replay-interval', 'n_intervals'),
     Input('timeline-slider', 'value'),
     Input('show-signal-toggle', 'value'),
     Input('replay-tape-store', 'data')],
    prevent_initial_call=True
)
def render_frame(n, slider_val, show_signal, packet):
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Ensure slider_val is int
    current_idx = int(slider_val) if slider_val is not None else 0
    
    # Increment only if the interval caused the update
    if trigger == 'replay-interval': 
        current_idx += 1
    
    # Initialize empty figure
    empty_fig = go.Figure()
    empty_fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    
    if not packet: return empty_fig, "--:--", "Frame: 0", 0, True, ""

    xsp_data = packet['xsp']
    vix_data = packet['vix']
    es_data = packet['es']
    opt_data = packet['opt']
    entry_ts = packet['entry_ts']
    ticker = packet['ticker']
    entry_price = packet.get('entry_price', 0)
    max_gain = packet.get('max_gain', 0)
    
    # ⚡ STOP LOGIC
    max_len = len(xsp_data) - 1
    should_disable = False
    
    if current_idx >= max_len: 
        current_idx = max_len
        should_disable = True
    
    # Only update disabled state if we hit the end, otherwise no_update
    disable_output = True if should_disable else no_update

    # Slice XSP
    xsp_slice = pd.DataFrame(xsp_data[:current_idx+1])
    if xsp_slice.empty: return empty_fig, "09:30", "Frame: 0", 0, True, ""
    
    curr_time_str = pd.to_datetime(xsp_slice.iloc[-1]['datetime_local']).strftime('%H:%M')
    curr_dt_wc = pd.to_datetime(xsp_slice.iloc[-1]['datetime_local'])
    
    day_start = pd.to_datetime(xsp_data[0]['datetime_local']).replace(hour=6, minute=30, second=0)
    day_end = day_start.replace(hour=13, minute=0, second=0)

    # Slice Others
    vix_slice = pd.DataFrame(vix_data)
    if not vix_slice.empty: vix_slice = vix_slice[pd.to_datetime(vix_slice['datetime_local']) <= curr_dt_wc]
    
    es_slice = pd.DataFrame(es_data)
    if not es_slice.empty: es_slice = es_slice[pd.to_datetime(es_slice['datetime_local']) <= curr_dt_wc]
    
    opt_slice = pd.DataFrame(opt_data)
    if not opt_slice.empty: opt_slice = opt_slice[pd.to_datetime(opt_slice['datetime_local']) <= curr_dt_wc]

    fig = make_subplots(
        rows=4, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.3, 0.25, 0.25, 0.2], 
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("CONTEXT: XSP + LinReg + ORB", f"STRATEGY: {ticker}", "VIX FRACTAL FLOW", "VIX RSI")
    )

    # 1. XSP CONTEXT
    fig.add_trace(go.Candlestick(x=xsp_slice['datetime_local'], open=xsp_slice['open'], high=xsp_slice['high'], low=xsp_slice['low'], close=xsp_slice['close'], name="XSP"), row=1, col=1)
    if 'sma_50' in xsp_slice.columns:
        fig.add_trace(go.Scatter(x=xsp_slice['datetime_local'], y=xsp_slice['sma_50'], name="SMA 50", line=dict(color='orange', width=1)), row=1, col=1)
    
    if 'reg_line' in xsp_slice.columns:
        fig.add_trace(go.Scatter(x=xsp_slice['datetime_local'], y=xsp_slice['reg_line'], line=dict(color='yellow', width=1, dash='dot'), name="Mean"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp_slice['datetime_local'], y=xsp_slice['upper_band'], line=dict(color='cyan', width=1), name="+2σ"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xsp_slice['datetime_local'], y=xsp_slice['lower_band'], line=dict(color='cyan', width=1), name="-2σ"), row=1, col=1)

    orb_end = day_start + timedelta(minutes=30)
    if curr_dt_wc > orb_end:
        orb_df = pd.DataFrame(xsp_data)
        orb_df['datetime_local'] = pd.to_datetime(orb_df['datetime_local'])
        orb_df = orb_df[(orb_df['datetime_local'] >= day_start) & (orb_df['datetime_local'] <= orb_end)]
        if not orb_df.empty:
            orb_h = orb_df['high'].max()
            orb_l = orb_df['low'].min()
            fig.add_hline(y=orb_h, line_dash="solid", line_color="green", opacity=0.5, row=1, col=1)
            fig.add_hline(y=orb_l, line_dash="solid", line_color="red", opacity=0.5, row=1, col=1)

    if not es_slice.empty:
        fig.add_trace(go.Scatter(x=es_slice['datetime_local'], y=es_slice['scaled_close'], name="/ES", line=dict(color='#00d2ff', width=1, dash='dot')), row=1, col=1)

    # 2. STRATEGY (BLIND MODE)
    entry_wc = datetime.fromtimestamp(entry_ts / 1000, tz=pytz.utc).astimezone(config.TZ_LOCAL).replace(tzinfo=None)
    reveal_strategy = (show_signal and "show" in show_signal) and (curr_dt_wc >= entry_wc)
    
    combat_report = ""
    
    if reveal_strategy:
        combat_report = html.Div([
            html.Div(f"ENTRY: ${entry_price:.2f}", className="text-white fw-bold"),
            html.Div(f"POTENTIAL: +{max_gain:.1f}%", className="text-success fw-bold")
        ])
        
        if not opt_slice.empty:
            fig.add_trace(go.Candlestick(
                x=opt_slice['datetime_local'],
                open=opt_slice['open'], high=opt_slice['high'],
                low=opt_slice['low'], close=opt_slice['close'],
                name="Option",
            ), row=2, col=1, secondary_y=False)
            
            fig.add_trace(go.Scatter(x=opt_slice['datetime_local'], y=opt_slice['open'], name="Price", line=dict(color='white', width=1.5)), row=2, col=1, secondary_y=True)
            fig.add_vline(x=entry_wc, line_width=1, line_dash="dash", line_color="lime")
            fig.add_annotation(x=entry_wc, y=1.0, yref="paper", text="SIGNAL", showarrow=False, font=dict(color="lime", size=10), bgcolor="rgba(0,0,0,0.5)")
    
    elif not reveal_strategy:
        fig.add_annotation(x=day_start + timedelta(hours=3), y=0.5, yref="y2", text="STRATEGY HIDDEN (WAIT FOR SIGNAL)", showarrow=False, font=dict(color="gray", size=20))

    # 3. MACD
    if not vix_slice.empty:
        fig.add_trace(go.Bar(x=vix_slice['datetime_local'], y=vix_slice['hist'], name="Macro", marker_color='rgba(255, 255, 255, 0.2)'), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_slice['datetime_local'], y=vix_slice['macd'], name="Micro", line=dict(color='#f1c40f', width=1)), row=3, col=1)
        
        # 4. RSI
        fig.add_trace(go.Scatter(x=vix_slice['datetime_local'], y=vix_slice['rsi'], name="RSI", line=dict(color='#a855f7', width=1.5, shape='spline')), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#e74c3c", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    fig.update_xaxes(matches='x', range=[day_start, day_end], type='date', fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    
    fig.update_layout(
        uirevision=entry_ts, # ⚡ CRITICAL FIX: Preserves zoom state during playback
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=50, r=50, t=30, b=50), 
        showlegend=True, 
        height=900, 
        legend=dict(orientation="h", yanchor="top", y=-0.05, xanchor="center", x=0.5),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1e1e1e", font=dict(color="#f3f5f9", family="monospace"))
    )
    
    return fig, curr_time_str, f"Frame: {current_idx}", current_idx, disable_output, combat_report

if __name__ == '__main__':
    app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
    app.layout = render()
    app.run_server(debug=True, port=8050)