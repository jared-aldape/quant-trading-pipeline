import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, ALL, ctx, no_update
import dash_bootstrap_components as dbc
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
# 0. DATA & TEMPORAL INTELLIGENCE
# ==============================================================================
HOLIDAYS = {
    "2025-01-01": "New Year's Day", "2025-01-20": "MLK Jr. Day",
    "2025-02-17": "Presidents Day", "2025-04-18": "Good Friday",
    "2025-05-26": "Memorial Day", "2025-06-19": "Juneteenth",
    "2025-07-04": "Independence Day", "2025-09-01": "Labor Day",
    "2025-11-27": "Thanksgiving", "2025-12-25": "Christmas Day"
}

EARLY_CLOSES = {
    "2025-07-03": time(13, 0), "2025-11-28": time(13, 0), "2025-12-24": time(13, 0)
}

def get_market_status():
    # Use config timezone or fallback to NY
    tz_ny = pytz.timezone('America/New_York')
    now_ny = datetime.now(tz_ny)
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = EARLY_CLOSES.get(today_str, time(16, 0))

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS
    is_active_hours = market_open <= current_time < market_close
    
    # 1. Determine Status & Color
    status_text = "CLOSED"
    status_color = "#e74c3c"
    reason = ""
    
    if is_holiday:
        reason = f"({HOLIDAYS[today_str]})"
    elif is_weekend:
        reason = "(WEEKEND)"
    elif is_active_hours:
        status_text = "OPEN"
        status_color = "#00bc8c"
        reason = "(LIVE)"
    elif current_time < market_open:
        reason = "(PRE-MARKET)"
    else:
        reason = "(POST-MARKET)"

    html_status = html.Span([
        html.Span(f"STATUS: {status_text}", style={'color': status_color, 'fontWeight': 'bold', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'}),
        html.Span(f" {reason}", className="small ms-2", style={'color': '#b5b8b9', 'fontFamily': "'VT323', monospace"})
    ])

    # 2. Determine "Next Event" or "Current Session" Info
    info_line = ""
    
    if is_active_hours:
        close_str = market_close.strftime("%H:%M")
        info_line = f"SESSION: 09:30 - {close_str} ET"
    else:
        target_date = now_ny.date()
        # If trading day and before open, next is today
        if not is_weekend and not is_holiday and current_time < market_open:
            date_label = "TODAY"
        else:
            # Look forward
            target_date += timedelta(days=1)
            while True:
                d_str = target_date.strftime("%Y-%m-%d")
                if target_date.weekday() < 5 and d_str not in HOLIDAYS:
                    break
                target_date += timedelta(days=1)
            date_label = target_date.strftime("%A, %b %d")

        info_line = f"NEXT: {date_label} @ 09:30 ET"

    return html_status, info_line, is_active_hours

def fetch_recent_transactions():
    """Fetches transaction history safely."""
    try:
        session = engine_simulator.load_session()
        trades = session.get('trades', [])
        if not trades: return []
        
        df = pd.DataFrame(trades)
        if not df.empty and 'exit_time' in df.columns:
            df = df.sort_values('exit_time', ascending=False)
            return df.head(50).to_dict('records')
        return []
    except Exception as e:
        print(f"Ledger Error: {e}")
        return []

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW ---
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
                        dbc.Button("↺ RESET DECK", id='deck-reset-btn', color="secondary", size="sm", className="float-end mt-2", style={"fontFamily": "'VT323', monospace", "fontSize": "1.1rem"})
                    ], width=4),
                    dbc.Col([
                        # CLOCK/STATUS BLOCK
                        html.H4(id='deck-clock', className="mb-0 text-end fw-bold", style={"color": "#fde722", "fontFamily": "'VT323', monospace", "textShadow": "1px 1px #000"}),
                        html.Div(id='deck-status', className="text-end", style={"fontFamily": "'VT323', monospace", "fontSize": "1.1rem"}),
                        html.Div(id='deck-next-day', className="text-end small", style={"color": "#b5b8b9", "fontFamily": "'VT323', monospace"})
                    ], width=8)
                ])
            ], width=6, className="align-self-center")
        ], className="mb-4 pb-2", style={
            "backgroundColor": "#283878", "border": "2px solid #b5b8b9", "borderRadius": "4px", "color": "#f3f5f9", "padding": "10px", "boxShadow": "0px 0px 10px rgba(0,0,0,0.5)"
        }),

        # MAIN CONTROL BOARD
        dbc.Row([
            # LEFT: ORDER ENTRY
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ORDER ENTRY", className="card-header text-center", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}),
                    dbc.CardBody([
                        html.H3(id='deck-price-display', className="text-center text-white mb-4", style={"fontFamily": "'VT323', monospace", "fontSize": "2rem"}),
                        
                        # ROW 1: TYPE | LIMIT PRICE
                        dbc.Row([
                            dbc.Col([
                                html.Label("TYPE", className="small text-muted", style={"fontFamily": "'VT323', monospace"}),
                                dbc.Select(id='deck-type', options=[{'label': 'MKT', 'value': 'MARKET'}, {'label': 'LMT', 'value': 'LIMIT'}], value='MARKET', className="mb-2", style={"fontFamily": "'VT323', monospace"})
                            ], width=6),
                            
                            dbc.Col([
                                html.Label("LIMIT PRICE", className="small text-muted", style={"fontFamily": "'VT323', monospace"}),
                                dbc.Input(id='deck-limit-px', type='number', placeholder="Limit", disabled=True, className="mb-2", style={"fontFamily": "'VT323', monospace"}),
                            ], width=6)
                        ]),
                        
                        # ROW 2: OFFSET | QTY
                        dbc.Row([
                            dbc.Col([
                                html.Label("OFFSET", className="small text-muted", style={"fontFamily": "'VT323', monospace"}),
                                dbc.Select(
                                    id='deck-offset',
                                    options=[
                                        {'label': 'ITM (-1)', 'value': "-1"},
                                        {'label': 'ATM',      'value': "0"},
                                        {'label': 'OTM (+1)', 'value': "1"}
                                    ],
                                    value="0", # String '0' ensures the label 'ATM' displays on load
                                    className="mb-3",
                                    style={"fontFamily": "'VT323', monospace"}
                                )
                            ], width=6),
                            
                            dbc.Col([
                                html.Label("QTY", className="small text-muted", style={"fontFamily": "'VT323', monospace"}),
                                dbc.Input(id='deck-qty', type='number', value=1, min=1, className="mb-3", style={"fontFamily": "'VT323', monospace"})
                            ], width=6),
                        ]),
                        
                        html.Div(id='deck-preview', className="mb-3 p-2 border border-secondary rounded bg-black small text-muted", style={"fontFamily": "'VT323', monospace"}),

                        # BUY BUTTONS
                        dbc.Row([
                            dbc.Col(dbc.Button("BUY CALL", id='deck-buy-call', color="success", className="w-100 py-3 fw-bold", style={'fontSize': '1.5rem', "fontFamily": "'VT323', monospace"}), width=6),
                            dbc.Col(dbc.Button("BUY PUT", id='deck-buy-put', color="danger", className="w-100 py-3 fw-bold", style={'fontSize': '1.5rem', "fontFamily": "'VT323', monospace"}), width=6)
                        ]),
                        html.Div(id='deck-feedback', className="mt-2 text-center text-warning small", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem"})
                    ])
                ], className="shadow mb-3", style={"backgroundColor": "#101830", "border": "1px solid #444"})
            ], width=12, lg=5),

            # RIGHT: LEDGER & STATS
            dbc.Col([
                dbc.Card([dbc.CardBody(id='deck-account-stats')], className="shadow mb-3", style={"backgroundColor": "#101830", "border": "1px solid #444"}),
                dbc.Card([
                    dbc.CardHeader("ACTIVE POSITIONS", className="card-header", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}),
                    dbc.CardBody(html.Div(id='deck-positions-container', style={'minHeight': '200px'}))
                ], className="shadow", style={"backgroundColor": "#101830", "border": "1px solid #444"})
            ], width=12, lg=7)
        ]),

        # --- TRANSACTION LEDGER ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("RECENT TRANSACTIONS", className="card-header", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem"}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='deck-ledger-table',
                            columns=[
                                {'name': 'Date', 'id': 'exit_time'}, 
                                {'name': 'Ticker', 'id': 'ticker'},
                                {'name': 'Action', 'id': 'action'},
                                {'name': 'Price', 'id': 'price', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                                {'name': 'PnL', 'id': 'pnl', 'type': 'numeric', 'format': {'specifier': '+$.2f'}},
                                {'name': 'Reason', 'id': 'reason'},
                            ],
                            data=[],
                            style_header={'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9', 'fontWeight': 'bold', "fontFamily": "'VT323', monospace", "fontSize": "1.1rem"},
                            style_cell={'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{pnl} > 0', 'column_id': 'pnl'}, 'color': '#00ff41', 'fontWeight': 'bold'},
                                {'if': {'filter_query': '{pnl} < 0', 'column_id': 'pnl'}, 'color': '#ff3333'},
                                {'if': {'filter_query': '{action} contains "BUY"', 'column_id': 'action'}, 'color': '#3498db'},
                                {'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'}, 'color': '#f39c12'},
                                {'if': {'filter_query': '{action} = "EXPIRE"', 'column_id': 'action'}, 'color': '#888'},
                            ],
                            page_size=10,
                            style_table={'overflowX': 'auto'}
                        )
                    ], className="p-0")
                ], className="shadow mb-4", style={"backgroundColor": "#101830", "border": "1px solid #444"})
            ], width=12)
        ]),

        dcc.Interval(id='deck-interval-fast', interval=1000, n_intervals=0), # 1s Clock
        dcc.Interval(id='deck-interval-slow', interval=3000, n_intervals=0)  # 3s Data
    ], fluid=True)

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================
@callback(Output('deck-limit-px', 'disabled'), Input('deck-type', 'value'))
def toggle_limit(val): return val != 'LIMIT'

# ⚡ PREVIEW (Independent)
@callback(Output('deck-preview', 'children'), 
          [Input('deck-qty', 'value'), Input('deck-limit-px', 'value'), 
           Input('deck-type', 'value'), Input('deck-offset', 'value')])
def update_preview(qty, limit, type, offset):
    try:
        # Convert String Offset back to int for engine
        off_int = int(offset) if offset else 0
        data = engine_simulator.preview_entry(qty, limit if type=='LIMIT' else None, off_int)
        if not data: return "CALCULATING..."
        return f"Est. Cost: ${data['total_cost']:.2f} (Strike: {data['strike_desc']})"
    except: return "WAITING FOR DATA..."

# ⚡ CLOCK & STATUS (Fast - 1s)
@callback(
    [Output('deck-clock', 'children'), Output('deck-status', 'children'), 
     Output('deck-next-day', 'children'), Output('deck-buy-call', 'disabled'), 
     Output('deck-buy-put', 'disabled'), Output('deck-buy-call', 'children'), 
     Output('deck-buy-put', 'children')],
    [Input('deck-interval-fast', 'n_intervals')]
)
def update_deck_clock(n):
    # Local Time for Display
    tz_local = getattr(config, 'TZ_LOCAL', pytz.timezone('US/Pacific'))
    now_pst = datetime.now(tz_local)
    time_str = now_pst.strftime("%m/%d/%y | %I:%M:%S %p")
    
    stat_html, info_line, is_active = get_market_status()
    
    # RTH Logic
    is_disabled = not is_active
    btn_text_call = "BUY CALL" if is_active else "CLOSED"
    btn_text_put = "BUY PUT" if is_active else "CLOSED"
    
    return time_str, stat_html, info_line, is_disabled, is_disabled, btn_text_call, btn_text_put

# ⚡ DATA (Slow - 3s)
@callback(
    [Output('deck-price-display', 'children'), Output('deck-account-stats', 'children'),
     Output('deck-positions-container', 'children'), Output('deck-feedback', 'children'),
     Output('deck-ledger-table', 'data')],
    [Input('deck-interval-slow', 'n_intervals'), Input('deck-buy-call', 'n_clicks'), Input('deck-buy-put', 'n_clicks'),
     Input('deck-reset-btn', 'n_clicks'), Input({'type': 'deck-close', 'index': ALL}, 'n_clicks')],
    [State('deck-qty', 'value'), State('deck-type', 'value'), State('deck-offset', 'value')]
)
def master_deck_data(n, b_call, b_put, b_reset, b_closes, qty, type, offset):
    trigger = ctx.triggered_id
    msg = ""
    
    try:
        # Convert offset string to int
        off_int = int(offset) if offset else 0

        # 1. EXECUTION
        if trigger == 'deck-reset-btn': 
            engine_simulator.reset_session()
            msg = "DECK RESET"
        elif trigger == 'deck-buy-call' and b_call: 
            msg = engine_simulator.execute_entry("CALL", qty, type, off_int)
        elif trigger == 'deck-buy-put' and b_put: 
            msg = engine_simulator.execute_entry("PUT", qty, type, off_int)
        elif isinstance(trigger, dict) and trigger['type'] == 'deck-close':
            msg = engine_simulator.execute_exit(trigger['index'])

        # 2. FETCH (Fault Tolerant)
        price = engine_simulator.get_live_price()
        stats = engine_simulator.get_portfolio_stats()
        session = engine_simulator.load_session()
        
        # 3. STATS UI
        stats_ui = dbc.Row([
            dbc.Col([html.H6("LIQUID", className="", style={"fontFamily": "'VT323', monospace"}), html.H3(f"${stats['liquid']:,.2f}", className="text-success", style={"fontFamily": "'VT323', monospace"})], width=4),
            dbc.Col([html.H6("BALANCE", className="", style={"fontFamily": "'VT323', monospace"}), html.H3(f"${stats['balance']:,.2f}", className="text-info", style={"fontFamily": "'VT323', monospace"})], width=4),
            dbc.Col([html.H6("OPEN P&L", className="", style={"fontFamily": "'VT323', monospace"}), html.H3(f"${stats['open_pnl']:+.2f}", className="text-white", style={"fontFamily": "'VT323', monospace"})], width=4)
        ])

        # 4. POSITIONS UI
        r, sigma = engine_simulator.get_market_context()
        T = engine_simulator.get_time_to_close()
        
        pos_ui = []
        if not session['positions']: 
            pos_ui = html.Div("NO ACTIVE TRADES", className="text-center text-muted mt-4", style={"fontFamily": "'VT323', monospace", "fontSize": "1.2rem"})
        else:
            for p in session['positions']:
                curr_px = engine_simulator.black_scholes(price, p['strike'], T, r, sigma, p['type'])
                curr_val = curr_px * 100 * p['contracts']
                cost_basis = p.get('cost_basis', 0.0)
                pnl_val = curr_val - cost_basis
                pnl_pct = (pnl_val / cost_basis) * 100 if cost_basis > 0 else 0
                
                pnl_color = "#00ff41" if pnl_val >= 0 else "#ff3333"

                pos_ui.append(dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Div(f"{p['ticker']}", className="fw-bold text-white", style={"fontFamily": "'VT323', monospace", "fontSize": "1.1rem"}),
                                html.Div(f"{p['contracts']}x @ ${p['entry_px']:.2f}", className="small text-muted", style={"fontFamily": "'VT323', monospace"})
                            ], width=4),
                            dbc.Col([
                                html.Div(f"${pnl_val:+.2f}", style={'color': pnl_color, 'fontWeight': 'bold', "fontFamily": "'VT323', monospace", "fontSize": "1.1rem"}),
                                html.Div(f"{pnl_pct:+.1f}%", className="small", style={'color': pnl_color, "fontFamily": "'VT323', monospace"})
                            ], width=4, className="text-center"),
                            
                            dbc.Col(dbc.Button("CLOSE", id={'type': 'deck-close', 'index': p['id']}, size="sm", color="warning", className="w-100", style={"fontFamily": "'VT323', monospace"}), width=4)
                        ], align="center")
                    ], className="p-2")
                ], className="mb-2 bg-dark border-secondary"))

        # 5. LEDGER
        ledger_data = fetch_recent_transactions()
        
        px_display = f"XSP: ${price:.2f}" if price else "OFFLINE"
        
        return px_display, stats_ui, pos_ui, msg, ledger_data

    except Exception as e:
        # Fallback: Return what we can (Error message + Empty Stats)
        return "ERROR", html.Div("ENGINE FAIL"), html.Div(), f"ERR: {str(e)}", []