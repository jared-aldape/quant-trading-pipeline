import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, ALL, ctx
import dash_bootstrap_components as dbc
from datetime import datetime, time, timedelta
import pandas as pd
import duckdb
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
    "2025-11-27": "Thanksgiving", "2025-12-25": "Christmas Day",
    "2026-01-01": "New Year's Day", "2026-01-19": "MLK Jr. Day",
    "2026-02-16": "Presidents Day", "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day", "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (Obs)", "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving", "2026-12-25": "Christmas Day"
}

EARLY_CLOSES = {
    "2025-07-03": time(13, 0), "2025-11-28": time(13, 0), "2025-12-24": time(13, 0),
    "2026-11-27": time(13, 0), "2026-12-24": time(13, 0)
}

def get_market_status():
    now_ny = datetime.now(config.TZ_NY)
    today_str = now_ny.strftime("%Y-%m-%d")
    current_time = now_ny.time()
    
    market_open = time(9, 30)
    market_close = EARLY_CLOSES.get(today_str, time(16, 0))

    is_weekend = now_ny.weekday() >= 5
    is_holiday = today_str in HOLIDAYS
    is_active_hours = market_open <= current_time < market_close
    
    if is_holiday: status_text, color, reason = "CLOSED", "#e74c3c", f"({HOLIDAYS[today_str]})"
    elif is_weekend: status_text, color, reason = "CLOSED", "#e74c3c", "(WEEKEND)"
    elif is_active_hours: status_text, color, reason = "OPEN", "#00ff41", "(LIVE)"
    elif current_time < market_open: status_text, color, reason = "CLOSED", "#e74c3c", "(PRE-MARKET)"
    else: status_text, color, reason = "CLOSED", "#e74c3c", "(POST-MARKET)"

    status_html = html.Span([
        html.Span(f"MARKET STATUS: {status_text}", style={'color': color, 'fontWeight': 'bold'}),
        html.Span(f" {reason}", className="text-muted small ms-2")
    ])

    next_date = now_ny.date() + timedelta(days=1)
    while True:
        d_str = next_date.strftime("%Y-%m-%d")
        if next_date.weekday() < 5 and d_str not in HOLIDAYS: break
        next_date += timedelta(days=1)
        
    return status_html, next_date.strftime("%m/%d/%y")

def fetch_recent_transactions():
    """Fetches the last 50 transactions for the deck view."""
    if not config.DB_FILE.exists(): return []
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        try:
            query = f"""
                SELECT timestamp, ticker, action, price, fees, amount, balance_snapshot 
                FROM {config.TBL_LIVE_LOG} 
                ORDER BY timestamp DESC
                LIMIT 50
            """
            df = con.execute(query).df()
            con.close()
            if not df.empty: df['timestamp'] = df['timestamp'].astype(str)
            return df.to_dict('records')
        except:
            con.close()
            return []
    except: return []

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER (RENAMED TO OPTION SIMULATOR)
        dbc.Row([
            dbc.Col([
                # CHANGED TEXT TO "OPTION SIMULATOR" AND COLOR TO WHITE
                html.H2("OPTION SIMULATOR", className="display-6 fw-bold text-white"), 
                html.Small("TACTICAL EXECUTION DECK", className="text-muted font-monospace")
            ], width=6),
            
            dbc.Col([
                html.H4(id='deck-clock', className="text-info font-monospace mb-0 text-end fw-bold"),
                html.Div(id='deck-status', className="text-end small font-monospace"),
                html.Div(id='deck-next-day', className="text-end text-muted small font-monospace mb-2"),
                
                html.Div([
                    dbc.Button("↺ RESET DECK", id='deck-reset-btn', color="secondary", size="sm", outline=True)
                ], className="text-end")
            ], width=6, className="align-self-center")
        ], className="mb-4 mt-2 border-bottom border-secondary pb-2"),

        # MAIN CONTROL BOARD
        dbc.Row([
            # LEFT: ORDER ENTRY
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ORDER ENTRY", className="fw-bold text-center", style={'backgroundColor': '#1E222D', 'color': 'white'}),
                    dbc.CardBody([
                        html.H3(id='deck-price-display', className="text-center text-white mb-4 font-monospace"),
                        
                        dbc.Row([
                            dbc.Col([
                                html.Label("TYPE"),
                                dbc.Select(id='deck-type', options=[{'label': 'MKT', 'value': 'MARKET'}, {'label': 'LMT', 'value': 'LIMIT'}], value='MARKET', className="mb-2 bg-dark text-white")
                            ], width=6),
                            dbc.Col([
                                html.Label("QTY"),
                                dbc.Input(id='deck-qty', type='number', value=1, min=1, className="mb-2 bg-dark text-white")
                            ], width=6),
                        ]),
                        dbc.Input(id='deck-limit-px', type='number', placeholder="Limit Price", disabled=True, className="mb-3 bg-dark text-white"),
                        
                        html.Div(id='deck-preview', className="mb-3 p-2 border border-secondary rounded bg-black small font-monospace text-muted"),

                        dbc.Row([
                            dbc.Col(dbc.Button("BUY CALL", id='deck-buy-call', color="success", className="w-100 py-3 fw-bold", style={'fontSize': '1.2rem'}), width=6),
                            dbc.Col(dbc.Button("BUY PUT", id='deck-buy-put', color="danger", className="w-100 py-3 fw-bold", style={'fontSize': '1.2rem'}), width=6)
                        ]),
                        html.Div(id='deck-feedback', className="mt-2 text-center text-warning small")
                    ])
                ], className="shadow mb-3")
            ], width=12, lg=5),

            # RIGHT: LEDGER & STATS
            dbc.Col([
                dbc.Card([dbc.CardBody(id='deck-account-stats')], className="shadow mb-3", style={'backgroundColor': '#1a1a1a'}),
                dbc.Card([
                    dbc.CardHeader("ACTIVE POSITIONS", className="fw-bold small", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody(html.Div(id='deck-positions-container', style={'minHeight': '200px'}))
                ], className="shadow")
            ], width=12, lg=7)
        ]),

        # --- TRANSACTION LEDGER ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("RECENT TRANSACTIONS (Live Tape)", className="fw-bold small text-muted", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='deck-ledger-table',
                            columns=[
                                {'name': 'Date', 'id': 'timestamp'},
                                {'name': 'Ticker', 'id': 'ticker'},
                                {'name': 'Action', 'id': 'action'},
                                {'name': 'Price', 'id': 'price', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                                {'name': 'Fees', 'id': 'fees', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                                {'name': 'Amount', 'id': 'amount', 'type': 'numeric', 'format': {'specifier': '+$.2f'}},
                                {'name': 'Balance', 'id': 'balance_snapshot', 'type': 'numeric', 'format': {'specifier': '$.2f'}},
                            ],
                            data=[],
                            style_header={'backgroundColor': '#222', 'color': 'white', 'fontWeight': 'bold', 'border': '1px solid #444'},
                            style_cell={'backgroundColor': '#000', 'color': '#EEE', 'border': '1px solid #333', 'fontFamily': 'monospace', 'textAlign': 'left'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{amount} > 0', 'column_id': 'amount'}, 'color': '#00ff41', 'fontWeight': 'bold'},
                                {'if': {'filter_query': '{amount} < 0', 'column_id': 'amount'}, 'color': '#ffffff'},
                                {'if': {'filter_query': '{action} = "BUY"', 'column_id': 'action'}, 'color': '#00d2ff'},
                                {'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'}, 'color': '#f39c12'},
                            ],
                            page_size=10,
                            style_table={'overflowX': 'auto'}
                        )
                    ], className="p-0")
                ], className="shadow mb-4")
            ], width=12)
        ]),

        dcc.Interval(id='deck-interval', interval=2000, n_intervals=0) 
    ], fluid=True)

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================
@callback(Output('deck-limit-px', 'disabled'), Input('deck-type', 'value'))
def toggle_limit(val): return val != 'LIMIT'

@callback(Output('deck-preview', 'children'), [Input('deck-qty', 'value'), Input('deck-limit-px', 'value'), Input('deck-type', 'value')])
def update_preview(qty, limit, type):
    data = engine_simulator.preview_entry(qty, limit if type=='LIMIT' else None)
    if not data: return "..."
    return f"Est. Cost: ${data['total_cost']:.2f} (Fill: ${data['est_fill']:.2f})"

@callback(
    [Output('deck-price-display', 'children'), Output('deck-account-stats', 'children'),
     Output('deck-positions-container', 'children'), Output('deck-feedback', 'children'),
     Output('deck-clock', 'children'), Output('deck-status', 'children'), Output('deck-next-day', 'children'),
     Output('deck-ledger-table', 'data')],
    [Input('deck-interval', 'n_intervals'), Input('deck-buy-call', 'n_clicks'), Input('deck-buy-put', 'n_clicks'),
     Input('deck-reset-btn', 'n_clicks'), Input({'type': 'deck-close', 'index': ALL}, 'n_clicks')],
    [State('deck-qty', 'value'), State('deck-type', 'value')]
)
def master_deck_update(n, b_call, b_put, b_reset, b_closes, qty, type):
    trigger = ctx.triggered_id
    msg = ""
    
    if trigger == 'deck-reset-btn': engine_simulator.reset_session(); msg = "RESET"
    elif trigger == 'deck-buy-call': msg = engine_simulator.execute_entry("CALL", qty, "QTY")
    elif trigger == 'deck-buy-put': msg = engine_simulator.execute_entry("PUT", qty, "QTY")
    elif isinstance(trigger, dict) and trigger['type'] == 'deck-close':
        msg = engine_simulator.execute_exit(trigger['index'])

    # Data
    price = engine_simulator.get_live_price("XSP") # Enforce XSP
    stats = engine_simulator.get_portfolio_stats()
    session = engine_simulator.load_session()
    
    # Context for MTM
    r, sigma = engine_simulator.get_market_context()
    T = engine_simulator.get_time_to_close()
    
    # UI: Stats
    stats_ui = dbc.Row([
        dbc.Col([html.H6("LIQUID"), html.H3(f"${stats['liquid_cash']:.2f}", className="text-success")], width=4),
        dbc.Col([html.H6("EQUITY"), html.H3(f"${stats['open_equity']:.2f}", className="text-info")], width=4),
        dbc.Col([html.H6("TOTAL P&L"), html.H3(f"${stats['pnl_abs']:+.2f}", className="text-white")], width=4)
    ])

    # UI: Positions (UPGRADED: P&L % and $)
    pos_ui = []
    if not session['positions']: 
        pos_ui = html.Div("NO ACTIVE TRADES", className="text-center text-muted mt-4")
    else:
        for p in session['positions']:
            # Calculate MTM P&L on the fly for display
            curr_val = 0.0
            pnl_val = 0.0
            pnl_pct = 0.0
            
            if price:
                curr_prem = engine_simulator.black_scholes(price, p['strike'], T, r, sigma, p['type'].lower())
                curr_val = curr_prem * 100 * p['contracts']
                cost_basis = p.get('cost_basis', 0.0)
                pnl_val = curr_val - cost_basis
                if cost_basis > 0:
                    pnl_pct = (pnl_val / cost_basis) * 100
            
            pnl_color = "#00ff41" if pnl_val >= 0 else "#ff3333"

            pos_ui.append(dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Div(f"{p['ticker']}", className="fw-bold text-white"),
                            html.Div(f"{p['contracts']}x @ ${p['entry_px']:.2f}", className="small text-muted")
                        ], width=4),
                        # NEW COLUMNS FOR P&L
                        dbc.Col([
                            html.Div(f"${pnl_val:+.2f}", style={'color': pnl_color, 'fontWeight': 'bold'}),
                            html.Div(f"{pnl_pct:+.1f}%", className="small", style={'color': pnl_color})
                        ], width=4, className="text-center"),
                        
                        dbc.Col(dbc.Button("CLOSE", id={'type': 'deck-close', 'index': p['trade_id']}, size="sm", color="warning", className="w-100"), width=4)
                    ], align="center")
                ], className="p-2")
            ], className="mb-2 bg-dark border-secondary"))

    # UI: Ledger
    ledger_data = fetch_recent_transactions()

    # UI: Clock
    now_pst = datetime.now(config.TZ_LOCAL)
    time_str = now_pst.strftime("%m/%d/%y | %I:%M:%S %p PST")
    stat_html, next_day = get_market_status()
    next_day_str = f"Next Market Day: {next_day}"

    px_display = f"XSP: ${price:.2f}" if price else "OFFLINE"

    return px_display, stats_ui, pos_ui, msg, time_str, stat_html, next_day_str, ledger_data