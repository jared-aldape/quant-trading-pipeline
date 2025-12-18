import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, ALL, ctx, no_update
import dash_bootstrap_components as dbc
from dash.dash_table.Format import Format, Scheme, Symbol, Group
from datetime import datetime, time, timedelta
import pandas as pd
import sys
import pytz
from pathlib import Path

# ==============================================================================
# PATH CONFIGURATION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_simulator
from src.utils import config

# ==============================================================================
# 0. TEMPORAL INTELLIGENCE (2025 UPDATED)
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
    
    if is_holiday:
        reason = f"({HOLIDAYS[today_str]})"
    elif is_weekend:
        reason = "(WEEKEND)"
    elif is_active_hours:
        status_text = "OPEN"
        status_color = "#00ff41" # Hard Green
        reason = "(LIVE)"
    elif current_time < market_open:
        reason = "(PRE-MARKET)"
    else:
        reason = "(POST-MARKET)"

    html_status = html.Span([
        html.Span(f"MARKET: {status_text}", style={'color': status_color, 'fontWeight': 'bold', 'fontFamily': "'VT323', monospace", 'fontSize': '1.2rem'}),
        html.Span(f" {reason}", className="small ms-2", style={'color': '#b5b8b9', 'fontFamily': "'VT323', monospace"})
    ])

    info_line = ""
    if is_active_hours:
        close_str = market_close.strftime("%H:%M")
        info_line = f"SESSION: 09:30 - {close_str} ET"
    else:
        target_date = now_ny.date()
        if not is_weekend and not is_holiday and current_time < market_open:
            date_label = "TODAY"
        else:
            target_date += timedelta(days=1)
            while True:
                d_str = target_date.strftime("%Y-%m-%d")
                if target_date.weekday() < 5 and d_str not in HOLIDAYS:
                    break
                target_date += timedelta(days=1)
            date_label = target_date.strftime("%A, %b %d")
        info_line = f"NEXT OPEN: {date_label} @ 09:30 ET"

    return html_status, info_line, is_active_hours

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- COMMAND HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("TRAINING GROUNDS", className="fw-bold text-white mb-0", style={"fontFamily": "'VT323', monospace", "letterSpacing": "2px", "textShadow": "2px 2px #000"}), 
                html.P("OPTIONS SIMULATOR | TACTICAL EXECUTION DECK", className="text-info lead mb-0", style={"fontFamily": "'VT323', monospace", "fontSize": "1.1rem"})
            ], width=6),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        html.Div("SIMULATION MODE:", className="text-end small fw-bold", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"}),
                        html.Div("ACTIVE", className="text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}),
                    ], width=4),
                    dbc.Col([
                        html.H4(id='trainer-clock', className="mb-0 text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "textShadow": "1px 1px #000"}),
                        html.Div(id='trainer-market-status', className="text-end"),
                        html.Div(id='trainer-next-info', className="text-end small", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"})
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-4 pb-2", style={"backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "padding": "10px", "boxShadow": "0px 0px 15px rgba(0,0,0,0.8)"}),

        # --- 2. BALANCES (HERO ROW) ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div("TOTAL PORTFOLIO VALUE", className="small text-muted font-monospace"),
                                html.Div(id='trainer-hero-balance', className="display-4 fw-bold font-monospace", style={"color": "#00ff41", "lineHeight": "1"}),
                            ], width=4, className="border-end border-secondary"),
                            dbc.Col([
                                html.Div("DAY P&L (UNREALIZED)", className="small text-muted font-monospace"),
                                html.Div(id='trainer-hero-pnl', className="fs-2 font-monospace"),
                            ], width=4, className="border-end border-secondary"),
                            dbc.Col([
                                html.Div("LIQUID BUYING POWER", className="small text-muted font-monospace"),
                                html.Div(id='trainer-hero-cash', className="fs-2 font-monospace text-info"),
                            ], width=4),
                        ])
                    ], className="py-2")
                ], className="mb-3 border-secondary", style={"backgroundColor": "#050a18", "border": "1px solid #444"})
            ], width=12)
        ]),

        # --- 3. THE COMMAND DECK ---
        dbc.Row([
            # LEFT: ORDER TERMINAL
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
                        dcc.Dropdown(
                            id='trainer-strike', 
                            placeholder="Scanning...", 
                            className="mb-3", 
                            style={
                                "fontFamily": "monospace", 
                                "backgroundColor": "#000", 
                                "color": "#fff", 
                                "border": "1px solid #444"
                            }
                        ),

                        dbc.Row([
                            dbc.Col([
                                html.Label("LIMIT PX", className="small text-muted font-monospace"),
                                dbc.Input(id='trainer-limit-price', type='number', step=0.01, placeholder="AUTO", disabled=True, className="font-monospace text-center bg-black text-white border-secondary")
                            ], width=6),
                            dbc.Col([
                                html.Label("QTY", className="small text-muted font-monospace"),
                                dbc.Input(id='trainer-qty', type='number', min=1, value=1, className="font-monospace text-center bg-black text-white border-secondary")
                            ], width=6)
                        ], className="mb-4"),

                        dbc.Button("EXECUTE SIGNAL", id='trainer-btn-buy', color="success", className="w-100 fw-bold font-monospace py-3", size="lg"),
                        html.Div(id='trainer-feedback', className="text-center mt-2 small font-monospace text-warning")
                    ])
                ], className="shadow border-secondary h-100", style={"backgroundColor": "#0a0f1e"})
            ], width=5),

            # RIGHT: POSITIONS & LEDGER
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ACTIVE COMBAT POSITIONS", className="card-header font-monospace py-1", style={"backgroundColor": "#1a2a4a"}),
                    dbc.CardBody(html.Div(id='trainer-positions-container', style={'minHeight': '150px'}), className="p-0")
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
     Output('trainer-btn-buy', 'disabled')],
    [Input('trainer-refresh-fast', 'n_intervals')]
)
def update_fast_ui(n):
    tz_local = pytz.timezone('US/Pacific')
    now_pst = datetime.now(tz_local)
    time_str = now_pst.strftime("%m/%d/%y | %I:%M:%S %p")
    status_html, next_info, is_active = get_market_status()
    return time_str, status_html, next_info, not is_active

@callback(
    [Output('trainer-live-price', 'children'),
     Output('trainer-hero-balance', 'children'),
     Output('trainer-hero-pnl', 'children'),
     Output('trainer-hero-cash', 'children'),
     Output('trainer-positions-container', 'children'),
     Output('trainer-feedback', 'children'),
     Output('trainer-ledger', 'data'),
     Output('trainer-strike', 'options')],
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

    bal_str = f"${data['balance']:,.2f}"
    pnl_val = data['day_pnl']
    p_color = "#00ff41" if pnl_val >= 0 else "#ff5555"
    pnl_str = html.Span(f"{pnl_val:+.2f}", style={"color": p_color})
    cash_str = f"${data['cash']:,.2f}"

    pos_ui = []
    if not data['positions']:
        pos_ui = html.Div("NO ACTIVE COMBAT POSITIONS", className="text-center text-muted font-monospace py-4")
    else:
        for p in data['positions']:
            try:
                pnl_v = p['current_val'] - p['cost_basis']
                pnl_p = (pnl_v / p['cost_basis']) * 100 if p['cost_basis'] > 0 else 0
                c_color = "#00ff41" if pnl_v >= 0 else "#ff5555"
                
                row = dbc.Row([
                    dbc.Col([
                        html.Div(p['ticker'], className="fw-bold text-white font-monospace"),
                        html.Div(f"{p['contracts']}x @ ${p['entry_px']:.2f}", className="text-muted small")
                    ], width=5),
                    dbc.Col([
                        html.Div(f"${pnl_v:+.2f}", className="text-end fw-bold font-monospace", style={"color": c_color}),
                        html.Div(f"{pnl_p:+.1f}%", className="text-end small", style={"color": c_color})
                    ], width=4),
                    dbc.Col([
                        dbc.Button("EXIT", id={'type': 'trainer-close', 'index': p['id']}, size="sm", color="warning", className="py-0 px-2 font-monospace")
                    ], width=3, className="text-end")
                ], className="border-bottom border-secondary py-2 mx-2 align-items-center")
                pos_ui.append(row)
            except: continue

    try:
        ledger = engine_simulator.fetch_recent_transactions()
    except: ledger = []
    
    price_disp = f"${price:.2f}" if price else "OFFLINE"
    
    return price_disp, bal_str, pnl_str, cash_str, pos_ui, msg, ledger, strike_opts

@callback(Output('trainer-limit-price', 'disabled'), Input('trainer-order-type', 'value'))
def toggle_limit(mode): return mode == 'MARKET'