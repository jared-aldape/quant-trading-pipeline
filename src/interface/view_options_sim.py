import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, ALL, ctx, no_update
import dash_bootstrap_components as dbc
from dash.dash_table.Format import Format, Scheme, Symbol, Group
from datetime import datetime, time, timedelta
import pandas as pd
import sys
import json
import pytz
import numpy as np
from pathlib import Path

# ==============================================================================
# PATH CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_simulator
from src.utils import config

# DATA SOURCES FOR TACTICAL STRIP
SNAPSHOT_FILE = ROOT_DIR / "data" / "live_snapshot.json"
MACRO_FILE = ROOT_DIR / "data" / "macro_sentiment.json"

# ==============================================================================
# 0. TEMPORAL & DATA INTELLIGENCE
# ==============================================================================
HOLIDAYS = {
    "2025-01-01": "New Year's Day", "2025-01-20": "MLK Jr. Day",
    "2025-02-17": "Presidents Day", "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence Day", "2025-09-01": "Labor Day",
    "2025-10-13": "Columbus Day",   "2025-11-11": "Veterans Day",
    "2025-11-27": "Thanksgiving",   "2025-12-25": "Christmas Day"
}

EARLY_CLOSES = {
    "2025-07-03": time(13, 0), 
    "2025-11-28": time(13, 0), 
    "2025-12-24": time(13, 0)
}

# STYLES
STYLE_MONO = {'fontFamily': "'VT323', monospace"}
STYLE_VALUE = {'fontFamily': "'VT323', monospace", 'fontSize': '1.2rem', 'color': '#fff'}

def get_market_status():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = EARLY_CLOSES.get(today_str, time(16, 0))

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS
    is_active_hours = market_open <= current_time < market_close
    
    status_text = "CLOSED"
    status_color = "#ff5555" # Hard Red
    reason = ""
    
    if is_holiday: reason = f"({HOLIDAYS[today_str]})"
    elif is_weekend: reason = "(WEEKEND)"
    elif is_active_hours:
        status_text = "OPEN"
        status_color = "#00ff41" # Hard Green
        reason = "(LIVE)"
    elif current_time < market_open: reason = "(PRE-MARKET)"
    else: reason = "(POST-MARKET)"

    html_status = html.Span([
        html.Span(f"MARKET: {status_text}", style={'color': status_color, 'fontWeight': 'bold', 'fontFamily': "'VT323', monospace", 'fontSize': '1.2rem'}),
        html.Span(f" {reason}", className="small ms-2", style={'color': '#b5b8b9', 'fontFamily': "'VT323', monospace"})
    ])

    info_line = ""
    if is_active_hours:
        close_str = market_close.strftime("%H:%M")
        info_line = f"SESSION: 09:30 - {close_str} ET"
    else:
        info_line = "MARKET CLOSED"

    return html_status, info_line, is_active_hours

def load_tactical_data():
    """Fetches VIX, Macro, and Heuristics for the Strip."""
    # 1. MACRO BIAS
    macro_bias, macro_color = "NEUTRAL", "#fde722"
    if MACRO_FILE.exists():
        try:
            with open(MACRO_FILE, 'r') as f:
                mdata = json.load(f)
                macro_bias = mdata.get('bias', 'NEUTRAL')
                if macro_bias == "BULLISH": macro_color = "#00ff41"
                elif macro_bias == "BEARISH": macro_color = "#ff5555"
        except: pass

    # 2. SNAPSHOT (VIX & NEURAL)
    vix_val, vix_pct = 0.0, 50
    p_call, p_put = 50, 50
    alert_msg, alert_color = "SYSTEM NOMINAL", "success"
    
    if SNAPSHOT_FILE.exists():
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                sdata = json.load(f)
                
            # VIX Logic
            vix_df = pd.DataFrame(sdata['vix'])
            if not vix_df.empty:
                curr_vix = vix_df.iloc[-1]['close']
                vix_val = curr_vix
                vix_pct = min(max(((curr_vix - 12) / (20 - 12)) * 100, 0), 100)
                
                # Neural Heuristic (Replicated from Live Scope)
                vix_df['ema12'] = vix_df['close'].ewm(span=12).mean()
                vix_df['ema26'] = vix_df['close'].ewm(span=26).mean()
                vix_df['macd'] = vix_df['ema12'] - vix_df['ema26']
                vix_df['signal'] = vix_df['macd'].ewm(span=9).mean()
                vix_df['hist'] = vix_df['macd'] - vix_df['signal']
                
                delta = vix_df['close'].diff()
                up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
                rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                hist = vix_df.iloc[-1]['hist']

                score = 50.0 + (float(hist) * -200.0)
                if rsi > 70: score += 5
                if rsi < 30: score -= 5
                p_call = int(max(0, min(100, score)))
                p_put = 100 - p_call
                
                # Alerts
                if curr_vix > 20: alert_msg, alert_color = "HIGH VOLATILITY", "warning"
                if curr_vix > 30: alert_msg, alert_color = "EXTREME FEAR", "danger"

        except Exception as e: pass

    return macro_bias, macro_color, vix_val, vix_pct, p_call, p_put, alert_msg, alert_color

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- ROW 1: HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("TRAINING GROUNDS", className="fw-bold text-white mb-0", style={"fontFamily": "'VT323', monospace", "letterSpacing": "2px", "textShadow": "2px 2px #000"}), 
                html.P("OPTIONS SIMULATOR | TACTICAL EXECUTION DECK", className="text-info lead mb-0", style=STYLE_MONO)
            ], width=6),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        html.Div("SIMULATION MODE:", className="text-end small fw-bold", style={"color": "#b5b8b9", **STYLE_MONO}),
                        html.Div("ACTIVE", className="text-end fw-bold", style={"color": "#fde722", "fontSize": "1.2rem", **STYLE_MONO}),
                    ], width=4),
                    dbc.Col([
                        html.H4(id='trainer-clock', className="mb-0 text-end fw-bold", style={"color": "#fde722", "textShadow": "1px 1px #000", **STYLE_MONO}),
                        html.Div(id='trainer-market-status', className="text-end"),
                        html.Div(id='trainer-next-info', className="text-end small", style={"color": "#b5b8b9", **STYLE_MONO})
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-3 pb-2", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "padding": "10px", "boxShadow": "0px 0px 15px rgba(0,0,0,0.8)"}),

        # --- ROW 2: TACTICAL STRIP (NAMESPACED FOR SIMULATOR) ---
        dbc.Row([
            # 1. VIX THERMOMETER
            dbc.Col([
                html.Div("VIX THERMOMETER", className="small text-muted fw-bold mb-1", style=STYLE_MONO),
                dbc.Row([
                    dbc.Col(dbc.Progress(id="trainer-vix-thermometer", value=50, color="warning", className="mt-1", style={"height": "16px", "border": "1px solid #fff"}), width=8),
                    dbc.Col(html.Span(id="trainer-vix-val-text", className="ps-2", style=STYLE_VALUE), width=4),
                ], className="g-0 align-items-center"),
            ], width=3, className="border-end border-secondary pe-2"),
            
            # 2. MACRO REGIME
            dbc.Col([
                html.Div("MACRO REGIME", className="small text-muted fw-bold mb-1 text-center", style=STYLE_MONO),
                html.Div(id="trainer-macro-regime-display", className="text-center fw-bold", style={'fontSize': '1.3rem', 'letterSpacing': '1px', **STYLE_MONO})
            ], width=3, className="border-end border-secondary px-2"),

            # 3. NEURAL CONFIDENCE
            dbc.Col([
                html.Div("NEURAL CONFIDENCE", className="small text-muted fw-bold mb-1 text-center", style=STYLE_MONO),
                html.Div(id="trainer-oracle-readout", className="text-center d-flex align-items-center justify-content-center", style={'fontSize': '1.2rem', 'color': '#00bc8c', **STYLE_MONO})
            ], width=3, className="border-end border-secondary px-2"),

            # 4. SYSTEM ALERTS
            dbc.Col([
                html.Div("SYSTEM ALERTS", className="small text-muted fw-bold mb-1", style=STYLE_MONO),
                html.Div(id="trainer-hud-alerts", className="text-start d-flex align-items-center h-100", style={'fontSize': '1.1rem', **STYLE_MONO})
            ], width=3, className="ps-2")
        ], className="py-2 mb-3", style={"backgroundColor": "#050a18", "border": "1px solid #444", "borderRadius": "4px", "padding": "10px"}),

        # --- ROW 3: BALANCES ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div("TOTAL PORTFOLIO VALUE", className="small text-muted font-monospace"),
                                html.Div(id='trainer-hero-balance', className="font-monospace", style={"lineHeight": "1"}),
                            ], width=4, className="border-end border-secondary"),
                            dbc.Col([
                                html.Div("DAY P&L (UNREALIZED)", className="small text-muted font-monospace"),
                                html.Div(id='trainer-hero-pnl', className="fs-2 font-monospace"),
                            ], width=4, className="border-end border-secondary"),
                            dbc.Col([
                                html.Div("LIQUID BUYING POWER", className="small text-muted font-monospace"),
                                html.Div(id='trainer-hero-cash', className="fs-2 font-monospace text-info"),
                                dcc.Store(id='trainer-cash-store')
                            ], width=4),
                        ])
                    ], className="py-2")
                ], className="mb-3 border-secondary", style={"backgroundColor": "#050a18", "border": "1px solid #444"})
            ], width=12)
        ]),

        # --- ROW 4: COMMAND DECK ---
        dbc.Row([
            # LEFT: ORDER ENTRY
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("TACTICAL ORDER ENTRY", className="card-header font-monospace text-center", style={"backgroundColor": "#1a2a4a"}),
                    dbc.CardBody([
                        html.H2(id='trainer-live-price', className="text-center text-warning mb-4 font-monospace", style={"fontSize": "2.5rem"}),
                        
                        dbc.Row([
                            dbc.Col([
                                html.Label("SIDE", className="small text-muted font-monospace"),
                                dbc.RadioItems(
                                    id="trainer-opt-type",
                                    options=[{"label": "CALL", "value": "CALL"}, {"label": "PUT", "value": "PUT"}],
                                    value="CALL", inline=True,
                                    class_name="btn-group w-100", input_class_name="btn-check",
                                    label_class_name="btn btn-outline-info font-monospace", label_checked_class_name="active"
                                )
                            ], width=6),
                            dbc.Col([
                                html.Label("MODE", className="small text-muted font-monospace"),
                                dbc.RadioItems(
                                    id="trainer-order-type",
                                    options=[{"label": "MKT", "value": "MARKET"}, {"label": "LMT", "value": "LIMIT"}],
                                    value="MARKET", inline=True,
                                    class_name="btn-group w-100", input_class_name="btn-check",
                                    label_class_name="btn btn-outline-warning font-monospace", label_checked_class_name="active"
                                )
                            ], width=6)
                        ], className="mb-3"),

                        html.Label("STRIKE SELECTION (0DTE)", className="small text-muted font-monospace"),
                        dcc.Dropdown(id='trainer-strike', placeholder="Scanning...", className="mb-3", style={"fontFamily": "monospace", "backgroundColor": "#000", "color": "#fff", "border": "1px solid #444"}),

                        dbc.Row([
                            dbc.Col([html.Label("LIMIT PX", className="small text-muted font-monospace"), dbc.Input(id='trainer-limit-price', type='number', step=0.01, placeholder="AUTO", disabled=True, className="font-monospace text-center bg-black text-white border-secondary")], width=6),
                            dbc.Col([html.Label("QTY", className="small text-muted font-monospace"), dbc.Input(id='trainer-qty', type='number', min=1, value=1, className="font-monospace text-center bg-black text-white border-secondary")], width=6)
                        ], className="mb-2"),

                        html.Div(id='trainer-cost-preview', className="text-center mb-3 font-monospace", style={"fontSize": "1.2rem", "minHeight": "25px"}),
                        dbc.Button("EXECUTE SIGNAL", id='trainer-btn-buy', color="success", className="w-100 fw-bold font-monospace py-3", size="lg"),
                        html.Div(id='trainer-feedback', className="text-center mt-2 small font-monospace text-warning")
                    ])
                ], className="shadow border-secondary h-100", style={"backgroundColor": "#0a0f1e"})
            ], width=5),

            # RIGHT: POSITIONS
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ACTIVE COMBAT POSITIONS", className="card-header font-monospace py-1", style={"backgroundColor": "#1a2a4a"}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col("CONTRACT", width=4, className="small text-muted font-monospace fw-bold"),
                            dbc.Col("EQUITY / MARK", width=3, className="text-center small text-muted font-monospace fw-bold"),
                            dbc.Col("P&L / ROI", width=3, className="text-end small text-muted font-monospace fw-bold"),
                            dbc.Col("ACTION", width=2, className="text-end small text-muted font-monospace fw-bold"),
                        ], className="border-bottom border-secondary px-2 py-1 mx-2 mb-2"),
                        html.Div(id='trainer-positions-container', style={'minHeight': '150px'})
                    ], className="p-0 pt-2")
                ], className="mb-3 border-secondary", style={"backgroundColor": "#0a0f1e"}),

                dbc.Card([
                    dbc.CardHeader("TRANSACTION LEDGER (FULL AUDIT)", className="card-header font-monospace py-1 text-muted", style={"backgroundColor": "#1a2a4a"}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='trainer-ledger',
                            columns=[
                                {'name': 'TIME', 'id': 'exit_time'},
                                {'name': 'TICKER', 'id': 'ticker'},
                                {'name': 'ACTION', 'id': 'action'},
                                {'name': 'QTY', 'id': 'qty'},
                                {'name': 'ENTRY', 'id': 'entry_px', 'type': 'numeric', 'format': Format(group=Group.yes, precision=2, scheme=Scheme.fixed, symbol=Symbol.yes)},
                                {'name': 'EXIT', 'id': 'price', 'type': 'numeric', 'format': Format(group=Group.yes, precision=2, scheme=Scheme.fixed, symbol=Symbol.yes)},
                                {'name': 'PnL', 'id': 'pnl', 'type': 'numeric', 'format': Format(group=Group.yes, precision=2, scheme=Scheme.fixed, symbol=Symbol.yes)},
                                {'name': 'REASON', 'id': 'reason'},
                            ],
                            style_header={'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '1px solid #777', 'fontFamily': 'monospace', 'fontSize': '0.85rem'},
                            style_cell={'backgroundColor': '#050a18', 'color': '#fff', 'border': 'none', 'fontFamily': 'monospace', 'textAlign': 'left', 'fontSize': '0.85rem'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{pnl} > 0', 'column_id': 'pnl'}, 'color': '#00ff41'},
                                {'if': {'filter_query': '{pnl} < 0', 'column_id': 'pnl'}, 'color': '#ff5555'}
                            ],
                            page_size=6,
                            style_table={'overflowX': 'auto'}
                        )
                    ], className="p-0")
                ], className="border-secondary", style={"backgroundColor": "#0a0f1e"})
            ], width=7)
        ]),

        dcc.Interval(id='trainer-refresh-fast', interval=1000, n_intervals=0),
        dcc.Interval(id='trainer-refresh-slow', interval=3000, n_intervals=0),

    ], fluid=True, style={"backgroundColor": "#050a18", "minHeight": "100vh", "padding": "20px"})

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================

@callback(
    [Output('trainer-clock', 'children'), 
     Output('trainer-market-status', 'children'), 
     Output('trainer-next-info', 'children'),
     Output('trainer-btn-buy', 'disabled'),
     # NEW TACTICAL OUTPUTS (NAMESPACED)
     Output('trainer-vix-thermometer', 'value'),
     Output('trainer-vix-thermometer', 'color'),
     Output('trainer-vix-val-text', 'children'),
     Output('trainer-macro-regime-display', 'children'),
     Output('trainer-macro-regime-display', 'style'),
     Output('trainer-oracle-readout', 'children'),
     Output('trainer-hud-alerts', 'children')],
    [Input('trainer-refresh-fast', 'n_intervals')]
)
def update_fast_ui(n):
    # Time & Status
    tz_local = pytz.timezone('US/Pacific')
    now_pst = datetime.now(tz_local)
    time_str = now_pst.strftime("%m/%d/%y | %I:%M:%S %p")
    status_html, next_info, is_active = get_market_status()

    # Tactical Data Fetch
    m_bias, m_color, v_val, v_pct, p_call, p_put, a_msg, a_col = load_tactical_data()

    # Formatted Outputs
    macro_style = {'color': m_color, 'fontSize': '1.3rem', 'letterSpacing': '1px', **STYLE_MONO}
    
    oracle_html = html.Span([
        html.Span(f"CALL: {p_call}%", style={'color': '#00bc8c' if p_call > 55 else '#555', 'marginRight': '15px', **STYLE_MONO}),
        html.Span(f"PUT: {p_put}%", style={'color': '#e74c3c' if p_put > 55 else '#555', **STYLE_MONO})
    ])

    badges = [dbc.Badge(a_msg, color=a_col, className="me-2", style=STYLE_MONO)]
    therm_color = "danger" if v_pct > 75 else "info" if v_pct < 25 else "success"

    return (time_str, status_html, next_info, not is_active, 
            v_pct, therm_color, f"{v_val:.2f}", m_bias, macro_style, oracle_html, badges)

@callback(
    [Output('trainer-live-price', 'children'),
     Output('trainer-hero-balance', 'children'),
     Output('trainer-hero-pnl', 'children'),
     Output('trainer-hero-cash', 'children'),
     Output('trainer-positions-container', 'children'),
     Output('trainer-feedback', 'children'),
     Output('trainer-ledger', 'data'),
     Output('trainer-strike', 'options'),
     Output('trainer-cash-store', 'data')],
    [Input('trainer-refresh-slow', 'n_intervals'),
     Input('trainer-btn-buy', 'n_clicks'),
     Input({'type': 'trainer-close', 'index': ALL}, 'n_clicks'),
     Input('trainer-opt-type', 'value')],
    [State('trainer-strike', 'value'),
     State('trainer-qty', 'value'),
     State('trainer-order-type', 'value'),
     State('trainer-limit-price', 'value')]
)
def update_slow_ui(n, buy_clicks, close_clicks, trade_type, strike, qty, order_mode, limit_px):
    msg = ""
    trigger = ctx.triggered_id
    
    if trigger == 'trainer-btn-buy' and strike:
        l_px = float(limit_px) if limit_px else 0.0
        msg = engine_simulator.execute_trade(strike, qty, trade_type, order_mode, l_px)
    elif isinstance(trigger, dict) and trigger['type'] == 'trainer-close':
        msg = engine_simulator.close_position(trigger['index'])

    try:
        data = engine_simulator.get_portfolio_stats()
        price = data.get('price', 0)
    except:
        data = {"balance": 2000, "cash": 2000, "equity": 0, "day_pnl": 0, "positions": []}
        price = 0
    
    strike_opts = engine_simulator.generate_strikes(price, trade_type) if price > 0 else []

    # HERO METRICS
    current_bal = data['balance']
    day_gain = data['day_pnl']
    start_bal = current_bal - day_gain
    total_pct = (day_gain / start_bal * 100) if start_bal > 0 else 0.0
    
    if day_gain > 0: bal_color = "#00ff41" 
    elif day_gain < 0: bal_color = "#ff5555" 
    else: bal_color = "#ffffff" 
    
    bal_str = html.Div([
        html.Span(f"${current_bal:,.2f}", className="me-2", style={"fontSize": "2.5rem", "fontWeight": "bold", "color": bal_color}),
        html.Span(f"({total_pct:+.1f}%)", style={"fontSize": "1.5rem", "color": bal_color})
    ], className="d-flex align-items-baseline")
    
    pnl_str = html.Div([
        html.Span(f"${day_gain:+.2f}", className="me-2"),
        html.Span(f"({total_pct:+.1f}%)", style={"fontSize": "1.2rem", "opacity": "0.8"})
    ], style={"color": bal_color})

    cash_str = f"${data['cash']:,.2f}"

    # POSITIONS RENDER
    pos_ui = []
    if not data['positions']:
        pos_ui = html.Div("NO ACTIVE COMBAT POSITIONS", className="text-center text-muted font-monospace py-4")
    else:
        for p in data['positions']:
            try:
                pnl_v = p['current_val'] - p['cost_basis']
                pnl_p = (pnl_v / p['cost_basis']) * 100 if p['cost_basis'] > 0 else 0
                total_equity = p['current_val']
                
                if pnl_v > 0: c_color = "#00ff41"
                elif pnl_v < 0: c_color = "#ff5555"
                else: c_color = "#ffffff"
                
                contracts = p.get('contracts', 1)
                curr_mark = (total_equity / (contracts * 100)) if contracts > 0 else 0.0
                
                row = dbc.Row([
                    dbc.Col([
                        html.Div(p['ticker'], className="fw-bold text-white font-monospace"),
                        html.Div(f"{contracts}x @ ${p['entry_px']:.2f}", className="text-muted small")
                    ], width=4),
                    dbc.Col([
                        html.Div(f"${total_equity:,.2f}", className="text-center fw-bold font-monospace text-info"),
                        html.Div(f"@{curr_mark:.2f}", className="text-center text-muted x-small font-monospace")
                    ], width=3),
                    dbc.Col([
                        html.Div(f"${pnl_v:+.2f}", className="text-end fw-bold font-monospace", style={"color": c_color}),
                        html.Div(f"{pnl_p:+.1f}%", className="text-end small", style={"color": c_color})
                    ], width=3),
                    dbc.Col([
                        dbc.Button("EXIT", id={'type': 'trainer-close', 'index': p['id']}, size="sm", color="warning", className="py-0 px-2 font-monospace")
                    ], width=2, className="text-end")
                ], className="border-bottom border-secondary py-2 mx-2 align-items-center")
                pos_ui.append(row)
            except: continue

    try: ledger = engine_simulator.fetch_recent_transactions()
    except: ledger = []
    
    price_disp = f"${price:.2f}" if price else "OFFLINE"
    
    return price_disp, bal_str, pnl_str, cash_str, pos_ui, msg, ledger, strike_opts, data['cash']

@callback(Output('trainer-limit-price', 'disabled'), Input('trainer-order-type', 'value'))
def toggle_limit(mode): return mode == 'MARKET'

@callback(
    Output('trainer-cost-preview', 'children'),
    [Input('trainer-limit-price', 'value'),
     Input('trainer-qty', 'value'),
     Input('trainer-strike', 'value'),
     Input('trainer-cash-store', 'data')],
    [State('trainer-strike', 'options')]
)
def update_cost_preview(limit_px, qty, strike_val, available_cash, strike_opts):
    def render_msg(val, color="#fff"):
         return html.Span(f"EST. COST: ${val:,.2f}", style={"color": color, "fontWeight": "bold", "fontSize": "1.2rem"})

    if not qty: return render_msg(0)
    price = 0.0
    if limit_px:
        try: price = float(limit_px)
        except: price = 0.0
    elif strike_val and strike_opts:
        selected_opt = next((o for o in strike_opts if o['value'] == strike_val), None)
        if selected_opt:
            label = selected_opt['label']
            try: price = float(label.split('$')[-1].strip())
            except: price = 0.0
    cost = price * int(qty) * 100
    cash = float(available_cash) if available_cash else 0.0
    color = "#ffffff"
    if cost > cash: color = "#ff5555"
    elif cost > 0: color = "#fde722"
    return render_msg(cost, color)