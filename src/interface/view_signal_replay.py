import sys
import dash
from dash import dcc, html, Input, Output, callback, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import duckdb
import pandas as pd
import numpy as np
from datetime import timedelta
import pytz
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger
from src.core import strat_fractal

log = get_logger("SignalReplay")
STRIKE_RANGE = 2

# ... [Keep clean_df, get_signal_events, get_tickers_for_event exactly as they were] ...
# (Omitting helper functions for brevity, assume they are unchanged from previous working version)
def clean_df(df, target_timezone=config.TZ_LOCAL):
    if df is None or df.empty: return pd.DataFrame(columns=['dt', 'close'])
    df.columns = df.columns.str.strip().str.lower()
    df = df.loc[:, ~df.columns.duplicated()]
    rename_map = {'datetime_utc': 'dt', 'datetime': 'dt', 'date': 'dt', 'timestamp': 'dt', 'close': 'close'}
    df.rename(columns=rename_map, inplace=True)
    if 'dt' not in df.columns: return pd.DataFrame(columns=['dt', 'close'])
    if not pd.api.types.is_datetime64_any_dtype(df['dt']): df['dt'] = pd.to_datetime(df['dt'], errors='coerce')
    df = df.dropna(subset=['dt'])
    if df['dt'].dt.tz is None: df['dt'] = df['dt'].dt.tz_localize(config.TZ_UTC)
    else: df['dt'] = df['dt'].dt.tz_convert(config.TZ_UTC)
    df['dt'] = df['dt'].dt.tz_convert(target_timezone)
    return df.sort_values('dt')

def get_signal_events():
    if not config.DB_FILE.exists(): return []
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        if (config.TBL_MANIFEST,) not in tables: con.close(); return []
        df = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} ORDER BY entry_timestamp_utc DESC").df()
    except: con.close(); return []
    con.close()
    options = []
    for _, row in df.iterrows():
        try:
            ts_utc = pd.to_datetime(row['entry_timestamp_utc'], unit='ms', utc=True)
            ts_local = ts_utc.tz_convert(config.TZ_LOCAL)
            t_type = row.get('trade_type', 'call')
            if pd.isna(t_type): t_type = 'call'
            sig_type = row.get('signal_type', 'MANUAL')
            if pd.isna(sig_type): sig_type = 'MANUAL'
            label = f"{ts_local.strftime('%Y-%m-%d %H:%M')} | {sig_type} | {t_type.upper()} | Est. ATM: ${row['xsp_price']:.2f}"
            options.append({'label': label, 'value': row['entry_timestamp_utc']})
        except: continue
    return options

def get_tickers_for_event(event_ts):
    if not event_ts: return [], None
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        row = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {event_ts}").df().iloc[0]
        trade_date = pd.to_datetime(row['date'])
        atm = round(row['xsp_price'])
        t_type = row.get('trade_type', 'call')
        if pd.isna(t_type): t_type = 'call'
        type_letter = 'P' if t_type.lower() == 'put' else 'C'
        tickers = []
        best = None
        date_str = trade_date.strftime("%y%m%d")
        for offset in range(-STRIKE_RANGE, STRIKE_RANGE + 1):
            strike = atm + offset
            ticker = f"O:XSP{date_str}{type_letter}{int(strike*1000):08d}"
            label = f"{ticker} ({'ATM' if offset==0 else 'OTM' if offset>0 else 'ITM'} ${strike})"
            tickers.append({'label': label, 'value': ticker})
            if offset == 0: best = ticker
        con.close()
        return tickers, best
    except: con.close(); return [], None

# ==============================================================================
# 3. RENDER LAYOUT (PITCH BLACK THEME)
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("SIGNAL REPLAY (Deep Dive)", className="display-6 fw-bold text-white"),
                html.Small("Forensic Analysis: XSP vs /ES Futures Overlay", className="text-muted"),
                html.Hr(className="my-2")
            ], width=12)
        ], className="mb-4"),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("🎯 TARGET ACQUISITION", className="fw-bold text-info", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("1. Select Signal Event", className="text-white small"),
                                dcc.Dropdown(id='replay-event-selector', options=get_signal_events(), clearable=False, className="mb-2", style={'color': '#000'}),
                            ], width=12, md=6),
                            dbc.Col([
                                html.Label("2. Select Contract Strike", className="text-white small"),
                                dcc.Dropdown(id='replay-strike-selector', options=[], disabled=True, clearable=False, style={'color': '#000'})
                            ], width=12, md=6)
                        ])
                    ], style={'backgroundColor': '#131722'})
                ], className="mb-3 shadow", style={'border': '1px solid #444'}),
            ], width=12),
            
            dbc.Col([html.Div(id='replay-stats-panel', className="text-end fw-bold mb-2", style={'color': '#00ff41'})], width=12)
        ]),

        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("🔬 THE MICROSCOPE (Intraday Replay)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        dcc.Loading(dcc.Graph(id='replay-chart', style={'height': '1200px'}), type="cube", color="#00bc8c")
                    ], className="p-1", style={'backgroundColor': '#000000'}) # Pitch Black
                ], className="shadow mb-5", style={'border': '1px solid #444'})
            ], width=12)
        ])
    ], fluid=True, style={'backgroundColor': '#000', 'minHeight': '100vh'})

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback([Output('replay-strike-selector', 'options'), Output('replay-strike-selector', 'value'), Output('replay-strike-selector', 'disabled')], [Input('replay-event-selector', 'value')])
def update_dropdown(ts):
    if not ts: return [], None, True
    options, best = get_tickers_for_event(ts)
    return options, best, False

@callback([Output('replay-chart', 'figure'), Output('replay-stats-panel', 'children')], [Input('replay-event-selector', 'value'), Input('replay-strike-selector', 'value')])
def update_chart(ts, ticker):
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color="white"))
    if not ts or not ticker: return empty_fig, ""

    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        trade_info = con.execute(f"SELECT * FROM {config.TBL_MANIFEST} WHERE entry_timestamp_utc = {ts}").df().iloc[0]
        trade_date_str = str(pd.to_datetime(trade_info['date']).date())
        t_type = trade_info.get('trade_type', 'call')
        if pd.isna(t_type): t_type = 'call'
        sig_type = trade_info.get('signal_type', 'MANUAL')
        
        tz_ny = pytz.timezone('America/New_York')
        rth_open_ny = tz_ny.localize(pd.Timestamp(f"{trade_date_str} 09:30:00"))
        rth_close_ny = tz_ny.localize(pd.Timestamp(f"{trade_date_str} 16:00:00"))
        rth_open_local = rth_open_ny.astimezone(config.TZ_LOCAL)
        rth_close_local = rth_close_ny.astimezone(config.TZ_LOCAL)
        
        spx_df = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='SPX' AND CAST(datetime_utc AS DATE) = '{trade_date_str}' ORDER BY datetime_utc ASC").df()
        spx_df = clean_df(spx_df)
        if not spx_df.empty: spx_df[['open', 'high', 'low', 'close']] = spx_df[['open', 'high', 'low', 'close']] / 10.0
        spx_df = spx_df[(spx_df['dt'] >= rth_open_local) & (spx_df['dt'] <= rth_close_local)]

        es_df = pd.DataFrame()
        try:
            es_df = con.execute(f"SELECT * FROM {config.TBL_FUTURES} WHERE ticker='ES' AND CAST(datetime_utc AS DATE) = '{trade_date_str}' ORDER BY datetime_utc ASC").df()
            es_df = clean_df(es_df)
            if not es_df.empty: es_df[['open', 'high', 'low', 'close']] = es_df[['open', 'high', 'low', 'close']] / 10.0
            es_df = es_df[(es_df['dt'] >= rth_open_local) & (es_df['dt'] <= rth_close_local)]
        except: pass

        opt_df = con.execute(f"SELECT * FROM {config.TBL_OPTIONS} WHERE ticker='{ticker}' ORDER BY datetime_utc ASC").df()
        opt_df = clean_df(opt_df)
        opt_df = opt_df[(opt_df['dt'] >= rth_open_local) & (opt_df['dt'] <= rth_close_local)]
        
        start_date = str(pd.to_datetime(trade_date_str) - timedelta(days=60))
        vix_raw = con.execute(f"SELECT * FROM {config.TBL_INDICES} WHERE ticker='VIX' AND CAST(datetime_utc AS DATE) BETWEEN '{start_date}' AND '{trade_date_str}' ORDER BY datetime_utc ASC").df()
        vix_raw = clean_df(vix_raw)
        
        if not vix_raw.empty:
            vix_1h = vix_raw.set_index('dt').resample('1h').agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna().reset_index()
            vix_1h = strat_fractal.calculate_macd(vix_1h)
            vix_1h_plot = vix_1h[(vix_1h['dt'] >= rth_open_local) & (vix_1h['dt'] <= rth_close_local)]
        else: vix_1h_plot = pd.DataFrame()

        vix_5m = strat_fractal.calculate_macd(vix_raw.copy())
        vix_5m = strat_fractal.calculate_rsi(vix_5m)
        vix_5m_plot = vix_5m[(vix_5m['dt'] >= rth_open_local) & (vix_5m['dt'] <= rth_close_local)]
        
    except Exception as e: con.close(); return empty_fig, f"Error: {str(e)}"
    con.close()

    signal_dt_utc = pd.to_datetime(ts, unit='ms', utc=True)
    signal_dt_local = signal_dt_utc.tz_convert(config.TZ_LOCAL)
    entry_price, entry_time, max_gain_price, max_gain_time, max_gain_pct = 0, None, 0, None, 0
    stats_text = "No Option Data"

    if not opt_df.empty:
        entry_slice = opt_df[opt_df['dt'] >= signal_dt_local]
        if not entry_slice.empty:
            entry_row = entry_slice.iloc[0]
            entry_price = entry_row['close']
            entry_time = entry_row['dt']
            trade_window = entry_slice.copy()
            if not trade_window.empty:
                max_idx = trade_window['high'].idxmax()
                max_gain_price = trade_window.loc[max_idx, 'high']
                max_gain_time = trade_window.loc[max_idx, 'dt']
                max_gain_pct = ((max_gain_price - entry_price) / entry_price) * 100
            opt_df['P&L_Pct'] = ((opt_df['close'] - entry_price) / entry_price) * 100
            opt_df['P&L_Color'] = np.where(opt_df['P&L_Pct'] >= 0, 'rgba(0, 255, 65, 0.8)', 'rgba(255, 51, 51, 0.8)')
            stats_text = f"ENTRY: ${entry_price:.2f} | PEAK: ${max_gain_price:.2f} (+{max_gain_pct:.1f}%)"
        else: stats_text = "Signal outside RTH Data range"

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, row_heights=[0.4, 0.3, 0.15, 0.15], vertical_spacing=0.08,
        specs=[[{"secondary_y": False}], [{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]],
        subplot_titles=("Context: XSP (Candles) vs /ES (Line)", f"Strategy: {sig_type} ({t_type.upper()}) | Price vs P&L", "VIX Fractal Flow (1H Hist vs 5m Line)", "VIX RSI (Momentum)"))

    if not spx_df.empty:
        fig.add_trace(go.Candlestick(x=spx_df['dt'], open=spx_df['open'], high=spx_df['high'], low=spx_df['low'], close=spx_df['close'], name="XSP (Syn)", increasing_line_color='#00bc8c', decreasing_line_color='#ef5350'), row=1, col=1)
    if not es_df.empty:
         fig.add_trace(go.Scatter(x=es_df['dt'], y=es_df['close'], mode='lines', line=dict(color='#00d2ff', width=1, dash='dot'), name="/ES (1/10th)"), row=1, col=1)
    
    if not opt_df.empty:
        fig.add_trace(go.Bar(x=opt_df['dt'], y=opt_df['P&L_Pct'], marker_color=opt_df['P&L_Color'], name="P&L %", opacity=0.8), row=2, col=1, secondary_y=True)
        fig.add_trace(go.Scatter(x=opt_df['dt'], y=opt_df['close'], mode='lines', line=dict(color='#ffffff', width=2), name="Option Price"), row=2, col=1, secondary_y=False)
        if entry_price > 0 and entry_time is not None:
            fig.add_vline(x=entry_time, line_dash="dash", line_color="#ffff00", row=2, col=1)
            fig.add_trace(go.Scatter(x=[entry_time], y=[entry_price], mode='markers', marker=dict(color='#ffff00', size=12, symbol='triangle-up'), name="Entry"), row=2, col=1, secondary_y=False)
        if max_gain_time is not None:
            fig.add_trace(go.Scatter(x=[max_gain_time], y=[max_gain_price], mode='markers+text', marker=dict(color='#00ff41', size=14, symbol='star'), text=[f"+{max_gain_pct:.1f}%"], textposition="top center", textfont=dict(color='#00ff41', weight='bold'), name="Max Gain"), row=2, col=1, secondary_y=False)

    if not vix_1h_plot.empty and not vix_5m_plot.empty:
        colors_1h = ['rgba(0, 188, 140, 0.4)' if v < 0 else 'rgba(231, 76, 60, 0.4)' for v in vix_1h_plot['hist']]
        fig.add_trace(go.Bar(x=vix_1h_plot['dt'], y=vix_1h_plot['hist'], marker_color=colors_1h, name="Macro (1h)"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_5m_plot['dt'], y=vix_5m_plot['macd'], line=dict(color='#f39c12', width=1.5), name="Micro (5m) MACD"), row=3, col=1)
        fig.add_trace(go.Scatter(x=vix_5m_plot['dt'], y=vix_5m_plot['signal'], line=dict(color='#00d2ff', width=1, dash='dot'), name="Micro (5m) Sig"), row=3, col=1)
        fig.add_hline(y=0, line_width=1, line_color="#666", row=3, col=1)

    if not vix_5m_plot.empty:
        fig.add_trace(go.Scatter(x=vix_5m_plot['dt'], y=vix_5m_plot['rsi'], line=dict(color='#9b59b6', width=2), name="RSI"), row=4, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="#ef5350", row=4, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="#00bc8c", row=4, col=1)

    fig.update_layout(template="plotly_dark", height=1200, xaxis_rangeslider_visible=False, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50, b=50, l=60, r=60), font=dict(color="white"), yaxis=dict(gridcolor='#333'), xaxis=dict(gridcolor='#333'), legend=dict(orientation="h", y=-0.02, x=0.5, xanchor="center"))
    fig.update_yaxes(gridcolor='#333')
    fig.update_xaxes(gridcolor='#333')

    return fig, stats_text