import dash
from dash import dcc, html, dash_table, callback, Input, Output, State, ALL, ctx
import dash_bootstrap_components as dbc
from datetime import datetime, time, timedelta
import pandas as pd
import duckdb
import sys
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
    tz = getattr(config, 'TZ_NY', None)
    if not tz:
        import pytz
        tz = pytz.timezone('America/New_York')
        
    now_ny = datetime.now(tz)
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
    """Fetches transaction history for the deck view."""
    # Pull directly from engine session to ensure sync
    session = engine_simulator.load_session()
    trades = session.get('trades', [])
    if not trades: return []
    
    df = pd.DataFrame(trades)
    if not df.empty and 'exit_time' in df.columns:
        df = df.sort_values('exit_time', ascending=False)
        
    # Format for table display
    return df.head(50).to_dict('records')

# ==============================================================================
# 1. LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("TRAINING GROUNDS", className="magitek-h2"), 
                html.P("OPTIONS SIMULATOR | TACTICAL EXECUTION DECK", className="magitek-note")
            ], width=6),
            
            dbc.Col([
                html.H4(id='deck-clock', className="text-info font-monospace mb-0 text-end fw-bold"),
                html.Div(id='deck-status', className="text-end small font-monospace"),
                html.Div(id='deck-next-day', className="text-end text-muted small font-monospace mb-2"),
                
                html.Div([
                    dbc.Button("↺ RESET DECK", id='deck-reset-btn', color="secondary", size="sm", outline=True, className="font-monospace")
                ], className="text-end")
            ], width=6, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # MAIN CONTROL BOARD
        dbc.Row([
            # LEFT: ORDER ENTRY
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("ORDER ENTRY", className="card-header text-center"),
                    dbc.CardBody([
                        html.H3(id='deck-price-display', className="text-center text-white mb-4 font-monospace"),
                        
                        # ROW 1: TYPE | QTY
                        dbc.Row([
                            dbc.Col([
                                html.Label("TYPE", className="small text-muted font-monospace"),
                                dbc.Select(id='deck-type', options=[{'label': 'MKT', 'value': 'MARKET'}, {'label': 'LMT', 'value': 'LIMIT'}], value='MARKET', className="mb-2")
                            ], width=6),
                            dbc.Col([
                                html.Label("QTY", className="small text-muted font-monospace"),
                                dbc.Input(id='deck-qty', type='number', value=1, min=1, className="mb-2")
                            ], width=6),
                        ]),
                        
                        # ROW 2: OFFSET | LIMIT PX (The Requested Change)
                        dbc.Row([
                            dbc.Col([
                                html.Label("OFFSET", className="small text-muted font-monospace"),
                                dbc.Select(
                                    id='deck-offset',
                                    options=[
                                        {'label': 'ITM (-1)', 'value': -1},
                                        {'label': 'ATM (0)', 'value': 0},
                                        {'label': 'OTM (+1)', 'value': 1}
                                    ],
                                    value=0,
                                    className="mb-3"
                                )
                            ], width=6),
                            
                            dbc.Col([
                                html.Label("LIMIT PX", className="small text-muted font-monospace"),
                                dbc.Input(id='deck-limit-px', type='number', placeholder="Limit", disabled=True, className="mb-3"),
                            ], width=6)
                        ]),
                        
                        html.Div(id='deck-preview', className="mb-3 p-2 border border-secondary rounded bg-black small font-monospace text-muted"),

                        dbc.Row([
                            dbc.Col(dbc.Button("BUY CALL", id='deck-buy-call', color="success", className="w-100 py-3 fw-bold font-monospace", style={'fontSize': '1.2rem'}), width=6),
                            dbc.Col(dbc.Button("BUY PUT", id='deck-buy-put', color="danger", className="w-100 py-3 fw-bold font-monospace", style={'fontSize': '1.2rem'}), width=6)
                        ]),
                        html.Div(id='deck-feedback', className="mt-2 text-center text-warning small font-monospace")
                    ])
                ], className="shadow mb-3")
            ], width=12, lg=5),

            # RIGHT: LEDGER & STATS
            dbc.Col([
                dbc.Card([dbc.CardBody(id='deck-account-stats')], className="shadow mb-3"),
                dbc.Card([
                    dbc.CardHeader("ACTIVE POSITIONS", className="card-header"),
                    dbc.CardBody(html.Div(id='deck-positions-container', style={'minHeight': '200px'}))
                ], className="shadow")
            ], width=12, lg=7)
        ]),

        # --- TRANSACTION LEDGER ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("RECENT TRANSACTIONS", className="card-header"),
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
                            
                            # MAGITEK STYLES
                            style_header={'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9', 'fontWeight': 'bold'},
                            style_cell={'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'},
                            
                            style_data_conditional=[
                                {'if': {'filter_query': '{pnl} > 0', 'column_id': 'pnl'}, 'color': '#00ff41', 'fontWeight': 'bold'},
                                {'if': {'filter_query': '{pnl} < 0', 'column_id': 'pnl'}, 'color': '#ff3333'},
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

@callback(Output('deck-preview', 'children'), 
          [Input('deck-qty', 'value'), Input('deck-limit-px', 'value'), 
           Input('deck-type', 'value'), Input('deck-offset', 'value')])
def update_preview(qty, limit, type, offset):
    data = engine_simulator.preview_entry(qty, limit if type=='LIMIT' else None, offset)
    if not data: return "..."
    return f"Est. Cost: ${data['total_cost']:.2f} (Strike: {data['strike_desc']})"

@callback(
    [Output('deck-price-display', 'children'), Output('deck-account-stats', 'children'),
     Output('deck-positions-container', 'children'), Output('deck-feedback', 'children'),
     Output('deck-clock', 'children'), Output('deck-status', 'children'), Output('deck-next-day', 'children'),
     Output('deck-ledger-table', 'data')],
    [Input('deck-interval', 'n_intervals'), Input('deck-buy-call', 'n_clicks'), Input('deck-buy-put', 'n_clicks'),
     Input('deck-reset-btn', 'n_clicks'), Input({'type': 'deck-close', 'index': ALL}, 'n_clicks')],
    [State('deck-qty', 'value'), State('deck-type', 'value'), State('deck-offset', 'value')]
)
def master_deck_update(n, b_call, b_put, b_reset, b_closes, qty, type, offset):
    trigger = ctx.triggered_id
    msg = ""
    
    # 1. EXECUTION HANDLING
    if trigger == 'deck-reset-btn': 
        engine_simulator.reset_session()
        msg = "RESET"
    elif trigger == 'deck-buy-call': 
        msg = engine_simulator.execute_entry("CALL", qty, type, offset)
    elif trigger == 'deck-buy-put': 
        msg = engine_simulator.execute_entry("PUT", qty, type, offset)
    elif isinstance(trigger, dict) and trigger['type'] == 'deck-close':
        msg = engine_simulator.execute_exit(trigger['index'])

    # 2. DATA FETCHING
    price = engine_simulator.get_live_price()
    stats = engine_simulator.get_portfolio_stats()
    session = engine_simulator.load_session()
    
    # Context for MTM
    r, sigma = engine_simulator.get_market_context()
    T = engine_simulator.get_time_to_close()
    
    # 3. STATS UI
    stats_ui = dbc.Row([
        dbc.Col([html.H6("LIQUID", className="font-monospace"), html.H3(f"${stats['liquid']:,.2f}", className="text-success font-monospace")], width=4),
        dbc.Col([html.H6("BALANCE", className="font-monospace"), html.H3(f"${stats['balance']:,.2f}", className="text-info font-monospace")], width=4),
        dbc.Col([html.H6("OPEN P&L", className="font-monospace"), html.H3(f"${stats['open_pnl']:+.2f}", className="text-white font-monospace")], width=4)
    ])

    # 4. POSITIONS UI
    pos_ui = []
    if not session['positions']: 
        pos_ui = html.Div("NO ACTIVE TRADES", className="text-center text-muted mt-4 font-monospace")
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
                            html.Div(f"{p['ticker']}", className="fw-bold text-white font-monospace"),
                            html.Div(f"{p['contracts']}x @ ${p['entry_px']:.2f}", className="small text-muted font-monospace")
                        ], width=4),
                        dbc.Col([
                            html.Div(f"${pnl_val:+.2f}", style={'color': pnl_color, 'fontWeight': 'bold'}, className="font-monospace"),
                            html.Div(f"{pnl_pct:+.1f}%", className="small font-monospace", style={'color': pnl_color})
                        ], width=4, className="text-center"),
                        
                        dbc.Col(dbc.Button("CLOSE", id={'type': 'deck-close', 'index': p['id']}, size="sm", color="warning", className="w-100 font-monospace"), width=4)
                    ], align="center")
                ], className="p-2")
            ], className="mb-2 bg-dark border-secondary"))

    # 5. LEDGER UI
    ledger_data = fetch_recent_transactions()

    # 6. CLOCK & STATUS
    import pytz
    # Use config timezone if available, else construct
    tz_local = getattr(config, 'TZ_LOCAL', pytz.timezone('US/Pacific'))
    now_pst = datetime.now(tz_local)
    
    time_str = now_pst.strftime("%m/%d/%y | %I:%M:%S %p")
    stat_html, next_day = get_market_status()
    next_day_str = f"Next Market Day: {next_day}"

    px_display = f"XSP: ${price:.2f}" if price else "OFFLINE"

    return px_display, stats_ui, pos_ui, msg, time_str, stat_html, next_day_str, ledger_data