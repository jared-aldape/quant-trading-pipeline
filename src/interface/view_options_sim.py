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
    "2026-01-01": "New Year's Day", "2026-01-19": "MLK Jr. Day",
    "2026-02-16": "Presidents Day"
}

def get_market_status():
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = time(16, 0)

    is_weekend = now_ny.weekday() >= 5
    is_active_hours = market_open <= current_time < market_close and not is_weekend
    
    status_text = "OPEN" if is_active_hours else "CLOSED"
    status_color = "#22c55e" if is_active_hours else "#ef4444"
    
    html_status = html.Span([
        html.Span(f"MARKET {status_text}", className="fw-bold", style={'color': status_color, 'fontSize': '1.1rem'}),
        html.Span(" (LIVE)" if is_active_hours else " (STBY)", className="small ms-1 text-muted")
    ])

    info_line = html.Div([
        html.Span("LOCAL PST: 06:30 - 13:00", className="me-2"),
        html.Span("| Standard Session", className="text-warning fw-bold")
    ], className="small text-muted font-monospace")

    return html_status, info_line, is_active_hours

def load_tactical_data():
    """Fetches VIX, Macro, and Heuristics for the Strip."""
    macro_bias, macro_color = "NEUTRAL", "#94a3b8"
    if MACRO_FILE.exists():
        try:
            with open(MACRO_FILE, 'r') as f:
                mdata = json.load(f)
                macro_bias = mdata.get('bias', 'NEUTRAL')
                if macro_bias == "BULLISH": macro_color = "#22c55e"
                elif macro_bias == "BEARISH": macro_color = "#ef4444"
                else: macro_color = "#f59e0b"
        except: pass

    vix_val, vix_pct = 0.0, 50
    p_call, p_put = 50, 50
    alert_msg, alert_color = "SYSTEM NOMINAL", "success"
    
    if SNAPSHOT_FILE.exists():
        try:
            with open(SNAPSHOT_FILE, 'r') as f:
                sdata = json.load(f)
            vix_df = pd.DataFrame(sdata.get('vix', []))
            if not vix_df.empty:
                curr_vix = float(vix_df.iloc[-1]['close'])
                vix_val = curr_vix
                vix_pct = min(max(((curr_vix - 12) / (20 - 12)) * 100, 0), 100)
                
                if curr_vix > 20: alert_msg, alert_color = "HIGH VOLATILITY", "warning"
                if curr_vix > 30: alert_msg, alert_color = "EXTREME FEAR", "danger"

        except Exception as e: pass

    return macro_bias, macro_color, vix_val, vix_pct, p_call, p_put, alert_msg, alert_color

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    # ⚡ NUCLEAR STYLE: HIGH CONTRAST (Black Text / White Background)
    INPUT_STYLE = {
        'color': '#000000', 
        'backgroundColor': '#ffffff', 
        'fontFamily': 'monospace',
        'border': '1px solid #ccc'
    }
    
    CARD_HEADER_STYLE = {"backgroundColor": "#1e293b", "color": "white", "fontWeight": "bold", "fontFamily": "monospace", "fontSize": "0.9rem"}
    CARD_BODY_STYLE = {"backgroundColor": "#0f172a", "border": "1px solid #334155"}

    return dbc.Container([
        # --- HEADER ---
        dbc.Row([
            dbc.Col([
                html.H2("OPTIONS SIMULATOR", className="fw-bold text-white mb-0"),
                html.P("REAL-TIME PAPER TRADING | 0DTE STRATEGY TESTER", className="text-muted small fw-bold mb-0")
            ], width=6),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        html.Div("SIMULATION MODE:", className="text-end small fw-bold text-muted"),
                        html.Div("ACTIVE", className="text-end fw-bold text-warning", style={"fontSize": "1.1rem"}),
                    ], width=4),
                    dbc.Col([
                        html.H3(id='trainer-clock', className="mb-0 text-end fw-bold font-monospace text-info"),
                        html.Div(id='trainer-market-status', className="text-end"),
                        html.Div(id='trainer-next-info', className="text-end small")
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        # --- TACTICAL STRIP ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Volatility Index (VIX)", style=CARD_HEADER_STYLE),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col(dbc.Progress(id="trainer-vix-thermometer", value=50, style={"height": "8px"}, color="info"), width=8),
                            dbc.Col(html.Span(id="trainer-vix-val-text", className="fw-bold font-monospace text-white"), width=4, className="text-end"),
                        ], className="align-items-center"),
                    ], style=CARD_BODY_STYLE)
                ])
            ], width=3),
            dbc.Col(dbc.Card([dbc.CardHeader("Market Bias", style=CARD_HEADER_STYLE), dbc.CardBody(html.Div(id="trainer-macro-regime-display", className="text-center fw-bold", style={'fontSize': '1.2rem'}), style=CARD_BODY_STYLE)]), width=3),
            dbc.Col(dbc.Card([dbc.CardHeader("Neural Alpha", style=CARD_HEADER_STYLE), dbc.CardBody(html.Div(id="trainer-oracle-readout", className="text-center fw-bold font-monospace"), style=CARD_BODY_STYLE)]), width=3),
            dbc.Col(dbc.Card([dbc.CardHeader("Guardrails", style=CARD_HEADER_STYLE), dbc.CardBody(html.Div(id="trainer-hud-alerts", className="text-center"), style=CARD_BODY_STYLE)]), width=3)
        ], className="mb-4"),

        # --- BALANCES ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div("TOTAL PORTFOLIO VALUE", className="small text-muted fw-bold font-monospace"),
                                html.Div(id='trainer-hero-balance', className="font-monospace fw-bold fs-3 text-white"),
                            ], width=4, className="border-end border-secondary"),
                            dbc.Col([
                                html.Div("DAY P&L (UNREALIZED)", className="small text-muted fw-bold font-monospace"),
                                html.Div(id='trainer-hero-pnl', className="fs-3 font-monospace fw-bold"),
                            ], width=4, className="border-end border-secondary"),
                            dbc.Col([
                                html.Div("LIQUID BUYING POWER", className="small text-muted fw-bold font-monospace"),
                                html.Div(id='trainer-hero-cash', className="fs-3 font-monospace text-info fw-bold"),
                                dcc.Store(id='trainer-cash-store')
                            ], width=4),
                        ])
                    ], style={"backgroundColor": "#1e293b", "border": "1px solid #334155"})
                ], className="mb-4 shadow-sm")
            ], width=12)
        ]),

        # --- COMMAND DECK ---
        dbc.Row([
            # LEFT: ENTRY PANEL
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("TACTICAL ORDER ENTRY", style=CARD_HEADER_STYLE),
                    dbc.CardBody([
                        html.H2(id='trainer-live-price', className="text-center text-warning mb-4 font-monospace fw-bold", style={"fontSize": "2.5rem"}),
                        dbc.Row([
                            dbc.Col([
                                html.Label("SIDE", className="small text-muted fw-bold font-monospace"),
                                dbc.RadioItems(
                                    id="trainer-opt-type",
                                    options=[{"label": "CALL", "value": "CALL"}, {"label": "PUT", "value": "PUT"}],
                                    value="CALL", inline=True,
                                    class_name="btn-group w-100", input_class_name="btn-check",
                                    label_class_name="btn btn-outline-info font-monospace fw-bold", label_checked_class_name="active"
                                )
                            ], width=6),
                            dbc.Col([
                                html.Label("MODE", className="small text-muted fw-bold font-monospace"),
                                dbc.RadioItems(
                                    id="trainer-order-type",
                                    options=[{"label": "MKT", "value": "MARKET"}, {"label": "LMT", "value": "LIMIT"}],
                                    value="MARKET", inline=True,
                                    class_name="btn-group w-100", input_class_name="btn-check",
                                    label_class_name="btn btn-outline-warning font-monospace fw-bold", label_checked_class_name="active"
                                )
                            ], width=6)
                        ], className="mb-3"),
                        
                        html.Label("STRIKE SELECTION (0DTE)", className="small text-muted fw-bold font-monospace"),
                        dcc.Dropdown(id='trainer-strike', placeholder="Scanning Chain...", className="mb-3", style=INPUT_STYLE),
                        
                        dbc.Row([
                            dbc.Col([
                                html.Label("LIMIT PX", className="small text-muted fw-bold font-monospace"), 
                                dbc.Input(id='trainer-limit-price', type='number', step=0.01, placeholder="AUTO", disabled=True, className="font-monospace text-center", style=INPUT_STYLE)
                            ], width=6),
                            dbc.Col([
                                html.Label("QTY", className="small text-muted fw-bold font-monospace"), 
                                dbc.Input(id='trainer-qty', type='number', min=1, value=1, className="font-monospace text-center", style=INPUT_STYLE)
                            ], width=6)
                        ], className="mb-2"),
                        
                        html.Div(id='trainer-cost-preview', className="text-center mb-3 font-monospace fw-bold", style={"fontSize": "1.2rem", "minHeight": "25px", "color": "white"}),
                        dbc.Button("EXECUTE SIGNAL", id='trainer-btn-buy', color="success", className="w-100 fw-bold font-monospace py-3", size="lg"),
                        html.Div(id='trainer-feedback', className="text-center mt-2 small font-monospace text-warning")
                    ], style=CARD_BODY_STYLE)
                ], className="h-100 shadow-sm")
            ], width=5),
            
            # RIGHT: POSITIONS & LEDGER
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ACTIVE COMBAT POSITIONS", style=CARD_HEADER_STYLE),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col("CONTRACT", width=4, className="small text-muted font-monospace fw-bold"),
                            dbc.Col("EQUITY", width=3, className="text-center small text-muted font-monospace fw-bold"),
                            dbc.Col("P&L", width=3, className="text-end small text-muted font-monospace fw-bold"),
                            dbc.Col("ACT", width=2, className="text-end small text-muted font-monospace fw-bold"),
                        ], className="border-bottom border-secondary px-2 py-1 mx-2 mb-2"),
                        html.Div(id='trainer-positions-container', style={'minHeight': '150px'})
                    ], className="p-0 pt-2", style=CARD_BODY_STYLE)
                ], className="mb-3 shadow-sm"),
                
                dbc.Card([
                    dbc.CardHeader("TRANSACTION LEDGER", style=CARD_HEADER_STYLE),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='trainer-ledger',
                            columns=[
                                {'name': 'TIME', 'id': 'exit_time'},
                                {'name': 'TICKER', 'id': 'ticker'},
                                {'name': 'ACT', 'id': 'action'},
                                {'name': 'QTY', 'id': 'qty'},
                                {'name': 'IN', 'id': 'entry_px', 'type': 'numeric', 'format': Format(precision=2, scheme=Scheme.fixed)},
                                {'name': 'OUT', 'id': 'price', 'type': 'numeric', 'format': Format(precision=2, scheme=Scheme.fixed)},
                                {'name': 'PnL', 'id': 'pnl', 'type': 'numeric', 'format': Format(precision=2, scheme=Scheme.fixed)},
                            ],
                            style_header={'backgroundColor': '#1e293b', 'color': '#f8fafc', 'fontWeight': 'bold', 'fontFamily': 'monospace'},
                            style_cell={'backgroundColor': '#0f172a', 'color': '#cbd5e1', 'border': '1px solid #334155', 'fontFamily': 'monospace'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{pnl} > 0', 'column_id': 'pnl'}, 'color': '#22c55e', 'fontWeight': 'bold'},
                                {'if': {'filter_query': '{pnl} < 0', 'column_id': 'pnl'}, 'color': '#ef4444', 'fontWeight': 'bold'}
                            ],
                            page_size=5,
                            style_table={'overflowX': 'auto'}
                        )
                    ], className="p-0", style=CARD_BODY_STYLE)
                ])
            ], width=7)
        ]),

        dcc.Interval(id='trainer-refresh-fast', interval=1000, n_intervals=0),
        dcc.Interval(id='trainer-refresh-slow', interval=3000, n_intervals=0),

    ], fluid=True, className="px-4 py-3")

# ==============================================================================
# 2. CALLBACKS (LOGIC UNTOUCHED)
# ==============================================================================

@callback(
    [Output('trainer-clock', 'children'), 
     Output('trainer-market-status', 'children'), 
     Output('trainer-next-info', 'children'),
     Output('trainer-btn-buy', 'disabled'),
     Output('trainer-vix-thermometer', 'value'),
     Output('trainer-vix-val-text', 'children'),
     Output('trainer-macro-regime-display', 'children'),
     Output('trainer-macro-regime-display', 'style'),
     Output('trainer-oracle-readout', 'children'),
     Output('trainer-hud-alerts', 'children')],
    [Input('trainer-refresh-fast', 'n_intervals')]
)
def update_fast_ui(n):
    tz_local = pytz.timezone('US/Pacific')
    now_pst = datetime.now(tz_local)
    time_str = now_pst.strftime("%H:%M:%S")
    status_html, next_info, is_active = get_market_status()

    m_bias, m_color, v_val, v_pct, p_call, p_put, a_msg, a_col = load_tactical_data()

    macro_style = {'color': m_color}
    
    oracle_html = html.Span([
        html.Span(f"CALL: {p_call}%", className="me-3", style={'color': '#22c55e' if p_call > 55 else '#94a3b8'}),
        html.Span(f"PUT: {p_put}%", style={'color': '#ef4444' if p_put > 55 else '#94a3b8'})
    ])

    badges = [dbc.Badge(a_msg, color=a_col, className="fw-bold")]

    return (time_str, status_html, next_info, not is_active, 
            v_pct, f"{v_val:.2f}", m_bias, macro_style, oracle_html, badges)

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
    
    try: ledger = engine_simulator.fetch_recent_transactions()
    except: ledger = []

    tz_local = pytz.timezone('US/Pacific')
    today_str = datetime.now(tz_local).strftime('%Y-%m-%d')
    
    realized_today = 0.0
    for tx in ledger:
        exit_ts = str(tx.get('exit_time', ''))
        if today_str in exit_ts:
            realized_today += float(tx.get('pnl', 0.0))

    unrealized_today = 0.0
    if data.get('positions'):
        for p in data['positions']:
            try: unrealized_today += (float(p.get('current_val', 0)) - float(p.get('cost_basis', 0)))
            except: pass
            
    day_gain = realized_today + unrealized_today
    current_bal = data['balance']
    
    NOMINAL_START = 2000.0
    total_val_gain = current_bal - NOMINAL_START
    total_pct = (total_val_gain / NOMINAL_START * 100) if NOMINAL_START != 0 else 0
    
    bal_color = "#22c55e" if total_val_gain >= 0 else "#ef4444"
    
    start_of_day_bal = current_bal - day_gain
    day_pct = (day_gain / start_of_day_bal * 100) if start_of_day_bal > 0 else 0.0
    day_color = "#22c55e" if day_gain >= 0 else "#ef4444"
    
    bal_str = html.Div([
        html.Span(f"${current_bal:,.2f}", className="me-2", style={"color": bal_color}),
        html.Span(f"({total_pct:+.1f}%)", className="small text-muted")
    ])
    
    pnl_str = html.Div([
        html.Span(f"${day_gain:+.2f}", className="me-2"),
        html.Span(f"({day_pct:+.1f}%)", className="small text-muted")
    ], style={"color": day_color})

    cash_str = f"${data['cash']:,.2f}"

    strike_opts = engine_simulator.generate_strikes(price, trade_type) if price > 0 else []

    pos_ui = []
    if not data['positions']:
        pos_ui = html.Div("NO ACTIVE POSITIONS", className="text-center text-muted font-monospace py-4 small")
    else:
        for p in data['positions']:
            try:
                pnl_v = p['current_val'] - p['cost_basis']
                cost_basis = p['cost_basis'] if p['cost_basis'] > 0 else 1.0
                pnl_p = (pnl_v / cost_basis) * 100
                total_equity = p['current_val']
                
                c_color = "#22c55e" if pnl_v >= 0 else "#ef4444"
                
                contracts = p.get('contracts', 1)
                curr_mark = (total_equity / (contracts * 100)) if contracts > 0 else 0.0
                
                row = dbc.Row([
                    dbc.Col([
                        html.Div(p['ticker'], className="fw-bold text-white font-monospace"),
                        html.Div(f"{contracts}x @ ${p['entry_px']:.2f}", className="text-muted small")
                    ], width=4),
                    dbc.Col([
                        html.Div(f"${total_equity:,.2f}", className="text-center fw-bold font-monospace text-info"),
                        html.Div(f"@{curr_mark:.2f}", className="text-center text-muted small font-monospace")
                    ], width=3),
                    dbc.Col([
                        html.Div(f"${pnl_v:+.2f}", className="text-end fw-bold font-monospace", style={"color": c_color}),
                        html.Div(f"{pnl_p:+.1f}%", className="text-end small", style={"color": c_color})
                    ], width=3),
                    dbc.Col([
                        dbc.Button("EXIT", id={'type': 'trainer-close', 'index': p['id']}, size="sm", color="warning", className="py-0 px-2 font-monospace fw-bold")
                    ], width=2, className="text-end")
                ], className="border-bottom border-secondary py-2 mx-2 align-items-center")
                pos_ui.append(row)
            except: continue
    
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
    def render_msg(val, color="white"):
         return html.Span(f"EST. COST: ${val:,.2f}", style={"color": color})

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
    color = "white"
    if cost > cash: color = "#ef4444"
    elif cost > 0: color = "#f59e0b"
    return render_msg(cost, color)