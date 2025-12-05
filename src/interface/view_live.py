import dash
from dash import dcc, html, callback, Input, Output, State, ALL, MATCH, ctx
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from datetime import datetime
import pandas as pd
from src.utils import config  # <--- CRITICAL IMPORT FOR TIMEZONE
from src.core import engine_simulator
from src.core import engine_ml 

# ==============================================================================
# 1. LAYOUT 
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER
        dbc.Row([
            dbc.Col([
                html.H2("LIVE TRADING COMMAND", className="display-6 fw-bold text-white"),
                html.P("Real-time execution interface with Multi-Lot Management.", className="text-muted lead")
            ], width=9),
            dbc.Col([
                html.Small(id='live-clock', className="text-end text-info font-monospace display-6 float-end")
            ], width=3)
        ], className="mb-3"),

        # MAIN CONSOLE
        dbc.Row([
            # LEFT: EXECUTION & CONTROLS
            dbc.Col([
                # ACCOUNT BALANCE & STATS
                dbc.Card([
                    dbc.CardHeader("💰 ACCOUNT OVERVIEW", className="fw-bold text-info", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody(id='account-stats-container') # <-- NEW ID for Dynamic Content
                ], className="shadow mb-3"),
                
                # EXECUTION TERMINAL
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("EXECUTION TERMINAL", className="fw-bold text-warning"),
                        dbc.Button("↺ RESET SIM", id='btn-reset-sim', color="danger", size="sm", outline=True, className="float-end py-0")
                    ], style={'backgroundColor': '#1a1a1a'}),
                    
                    dbc.CardBody([
                        # PRICE
                        html.H4(id='live-price-display', className="text-center text-white mb-3 font-monospace"),
                        html.Div(id='oracle-display', className="text-center mb-4 font-monospace", style={'fontSize': '1.1rem'}),

                        # INPUTS
                        dbc.Row([
                            dbc.Col([
                                html.Label("Order Type", className="small text-muted"),
                                dbc.Select(
                                    id='input-order-type',
                                    options=[{'label': 'Market', 'value': 'MARKET'}, {'label': 'Limit', 'value': 'LIMIT'}],
                                    value='MARKET', className="mb-2 btn-sm bg-dark text-white border-secondary"
                                )
                            ], width=6),
                            dbc.Col([
                                html.Label("Qty (Contracts)", className="small text-muted"),
                                dbc.Input(id='input-qty', type='number', value=1, min=1, step=1, className="mb-2 bg-dark text-white border-secondary"),
                            ], width=6),
                        ]),

                        dbc.Row([
                            dbc.Col([
                                dbc.Input(id='input-limit-price', type='number', placeholder="Limit Price ($)", disabled=True, className="mb-3 bg-dark text-white border-secondary"),
                            ], width=12)
                        ]),
                        
                        # --- NEW: COST PREVIEW DISPLAY ---
                        html.Div(id='cost-preview-display', className="mb-3 p-2 border border-secondary rounded bg-black small font-monospace", style={'minHeight': '60px'}),

                        # BUY BUTTONS
                        dbc.Row([
                            dbc.Col(dbc.Button("BUY CALL", id='btn-buy-call', color="success", className="w-100 fw-bold"), width=6),
                            dbc.Col(dbc.Button("BUY PUT", id='btn-buy-put', color="danger", className="w-100 fw-bold"), width=6)
                        ], className="mb-3"),
                        
                        html.Div(id='execution-feedback', className="mt-2 text-center small text-info")
                    ])
                ], className="shadow mb-3"),

            ], width=12, lg=4),

            # RIGHT: POSITIONS & CHART
            dbc.Col([
                # CHART
                dbc.Card([
                    dbc.CardBody([
                        dcc.Loading(dcc.Graph(id='live-chart', style={'height': '350px'}, config={'displayModeBar': False}))
                    ], className="p-1", style={'backgroundColor': '#000'})
                ], className="mb-3 shadow"),

                # ACTIVE POSITIONS (INTERACTIVE LEDGER)
                dbc.Card([
                    dbc.CardHeader("ACTIVE POSITIONS (Click 'Close' to Sell)", className="fw-bold text-white", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody(html.Div(id='active-positions-container', style={'minHeight': '100px'}))
                ], className="shadow mb-3"),

                # TRADE HISTORY
                dbc.Card([
                    dbc.CardHeader("HISTORY LOG", className="fw-bold text-muted small", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody(html.Div(id='history-ledger-table', style={'maxHeight': '200px', 'overflowY': 'auto'}))
                ], className="shadow")

            ], width=12, lg=8)
        ]),

        # THROTTLE
        dcc.Interval(id='live-interval', interval=5000, n_intervals=0) # 5s refresh

    ], fluid=True)

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================

@callback(
    Output('input-limit-price', 'disabled'),
    Input('input-order-type', 'value')
)
def toggle_limit(val): return val != 'LIMIT'

# NEW: PREVIEW CALLBACK
@callback(
    Output('cost-preview-display', 'children'),
    [Input('input-qty', 'value'),
     Input('input-limit-price', 'value'),
     Input('input-order-type', 'value'),
     Input('live-interval', 'n_intervals')]
)
def update_cost_preview(qty, limit_price, order_type, n):
    if not qty or qty < 1: return html.Div("Enter Quantity", className="text-muted text-center")
    
    # Fetch preview data
    # Note: If Limit, it uses limit_price. If Market, it fetches live "Proxy" ATM price.
    limit_val = limit_price if order_type == 'LIMIT' else None
    
    data = engine_simulator.preview_entry(qty, limit_val)
    if not data: return html.Div("Calculating...", className="text-muted text-center")
    
    # Check Solvency
    session = engine_simulator.load_session()
    balance = session.get('balance', 0)
    is_solvent = balance >= data['total_cost']
    
    total_color = "#00bc8c" if is_solvent else "#e74c3c"
    warning_text = "" if is_solvent else " (INSUFFICIENT FUNDS)"
    
    return html.Div([
        dbc.Row([
            dbc.Col(f"Est. Fill: ${data['est_fill']:.2f}", width=6, className="text-muted"),
            dbc.Col(f"Qty: {data['qty']}", width=6, className="text-end text-muted")
        ]),
        dbc.Row([
            dbc.Col(f"Fees: ${data['fees_total']:.2f}", width=12, className="text-warning small")
        ]),
        html.Div(f"Reg: ${data['fees_reg']:.2f} | Contract: ${data['fees_contract']:.2f}", className="text-muted small mb-1", style={'fontSize': '0.7em'}),
        html.Hr(className="my-1 border-secondary"),
        dbc.Row([
            dbc.Col("TOTAL ESTIMATED COST:", width=6, className="text-white fw-bold"),
            dbc.Col([
                html.Span(f"${data['total_cost']:.2f}", style={'color': total_color, 'fontSize': '1.2em'}),
                html.Span(warning_text, className="small text-danger fw-bold")
            ], width=6, className="text-end fw-bold")
        ])
    ])


# MASTER CALLBACK (Handles Updates, Buys, and Dynamic Closes)
@callback(
    [Output('live-price-display', 'children'),
     Output('oracle-display', 'children'),
     Output('live-chart', 'figure'),
     Output('live-clock', 'children'),
     Output('active-positions-container', 'children'), # DYNAMIC ROWS
     Output('history-ledger-table', 'children'),
     Output('account-stats-container', 'children'), # <-- NEW OUTPUT TARGET
     Output('execution-feedback', 'children')],
    [Input('live-interval', 'n_intervals'),
     Input('btn-buy-call', 'n_clicks'),
     Input('btn-buy-put', 'n_clicks'),
     Input('btn-reset-sim', 'n_clicks'),
     Input({'type': 'btn-close-position', 'index': ALL}, 'n_clicks')], # PATTERN MATCHING
    [State('input-qty', 'value'),
     State('input-order-type', 'value'),
     State('input-limit-price', 'value'),
     State({'type': 'input-close-qty', 'index': ALL}, 'value'),
     State({'type': 'input-close-qty', 'index': ALL}, 'id')] # Need IDs to map values
)
def master_update(n, btn_call, btn_put, btn_reset, btn_closes, qty, order_type, limit_price, close_qtys, close_ids):
    
    # Identify Trigger
    trigger_id = ctx.triggered_id if ctx.triggered_id else 'interval'
    feedback = ""
    
    # 1. EXECUTION LOGIC
    if trigger_id == 'btn-reset-sim':
        engine_simulator.reset_session()
        feedback = "System Reset."
        
    elif trigger_id in ['btn-buy-call', 'btn-buy-put']:
        side = "CALL" if trigger_id == 'btn-buy-call' else "PUT"
        feedback = engine_simulator.execute_entry(side, size_val=qty, size_mode="QTY")
        
    # HANDLE DYNAMIC CLOSE BUTTONS
    elif isinstance(trigger_id, dict) and trigger_id['type'] == 'btn-close-position':
        # Get the Trade ID from the button's index
        trade_id = trigger_id['index']
        
        # Find which input box corresponds to this button
        user_qty = None
        
        # Map the list of values to the list of IDs to find the match
        if close_qtys and close_ids:
            for val, id_obj in zip(close_qtys, close_ids):
                if id_obj['index'] == trade_id:
                    user_qty = val
                    break
        
        feedback = engine_simulator.execute_exit(trade_id, exit_qty=user_qty)

    # 2. DATA FETCH
    price = engine_simulator.get_live_price()
    price_str = f"SPY: ${price:.2f}" if price else "OFFLINE"
    
    # Oracle
    vix, vix_rsi = engine_simulator.get_vix_metrics()
    p_call = engine_ml.predict_success("CALL", vix, vix_rsi)
    p_put = engine_ml.predict_success("PUT", vix, vix_rsi)
    oracle_html = [
        html.Span(f"🤖 CALL: {p_call}%", style={'color': '#00bc8c' if p_call > 60 else '#666', 'marginRight': '15px'}),
        html.Span(f"PUT: {p_put}%", style={'color': '#e74c3c' if p_put > 60 else '#666'})
    ]

    # Chart
    chart_df = engine_simulator.get_live_chart_data()
    fig = go.Figure()
    if chart_df is not None:
        fig.add_trace(go.Candlestick(x=chart_df['Datetime'], open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close']))
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=40, r=40, t=20, b=40), xaxis_rangeslider_visible=False)

    # 3. RENDER LISTS
    session = engine_simulator.load_session()
    positions = session.get('positions', [])
    history = session.get('trades', [])
    balance = session.get('balance', 0)
    
    # --- A. ACTIVE POSITIONS (INTERACTIVE) ---
    active_rows = []
    if not positions:
        active_rows = html.Div("No active positions.", className="text-muted text-center p-3")
    else:
        # Sort by entry time (newest on top)
        positions.sort(key=lambda x: x['entry_time'], reverse=True)
        
        for p in positions:
            # Mark to Market
            r, sigma = engine_simulator.get_market_context()
            T = engine_simulator.get_time_to_close()
            curr_prem = engine_simulator.black_scholes(price, p['strike'], T, r, sigma, p['type'].lower())
            
            # Financial Calcs
            mkt_val = curr_prem * 100 * p['contracts']
            # P&L is Market Value - Cost Basis
            unrealized_pnl = mkt_val - p['cost_basis'] 
            pnl_pct = (unrealized_pnl / p['cost_basis']) * 100 if p['cost_basis'] > 0 else 0
            
            color = "#00bc8c" if unrealized_pnl >= 0 else "#e74c3c"
            
            # THE ROW LAYOUT (Robinhood Style)
            row = dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        # 1. INFO
                        dbc.Col([
                            html.Div(p['entry_time'].split(' ')[1], className="small text-muted"),
                            html.Div(f"{p['type']} {p['strike']}", className="fw-bold text-white"),
                            html.Div(f"{p['contracts']}x Contracts", className="small text-info"),
                        ], width=2),
                        
                        # 2. COST BASIS & FEES (The requested breakdown)
                        dbc.Col([
                            html.Div(f"Entry: ${p['entry_px']:.2f}", className="small text-muted"),
                            html.Div(f"Fees: ${p.get('fees_total', 0):.2f}", className="small text-warning", style={'fontSize': '0.7em'}),
                            html.Div(f"Cost: ${p['cost_basis']:.2f}", className="small text-white fw-bold"),
                        ], width=3),
                        
                        # 3. MARKET DATA & PNL
                        dbc.Col([
                            html.Div(f"Mark: ${curr_prem:.2f}", className="small text-muted"),
                            html.Div(f"${unrealized_pnl:.2f}", style={'color': color}, className="fw-bold"),
                            html.Div(f"{pnl_pct:+.2f}%", style={'color': color}, className="small fw-bold"),
                        ], width=3),
                        
                        # 4. ACTIONS (RIGHT SIDE)
                        dbc.Col([
                            dbc.InputGroup([
                                dbc.InputGroupText("Qty", className="bg-dark text-muted border-secondary small"),
                                dbc.Input(
                                    id={'type': 'input-close-qty', 'index': p['trade_id']},
                                    type='number', min=1, max=p['contracts'], value=p['contracts'], step=1,
                                    size="sm", className="bg-dark text-white border-secondary"
                                ),
                                dbc.Button(
                                    "CLOSE", 
                                    id={'type': 'btn-close-position', 'index': p['trade_id']},
                                    color="warning", size="sm", className="fw-bold"
                                )
                            ], size="sm")
                        ], width=4, className="text-end align-self-center"),
                    ], align="center")
                ], className="p-2")
            ], className="mb-2 border-secondary", style={'backgroundColor': '#222'})
            active_rows.append(row)

    # --- B. HISTORY LEDGER (STATIC TABLE) ---
    hist_rows = []
    for h in reversed(history): # Newest first
        pnl_col = "#00bc8c" if h['pnl'] >= 0 else "#e74c3c"
        hist_rows.append(html.Tr([
            html.Td(h['exit_time'].split(' ')[1], className="small"),
            html.Td(f"{h['type']} {h['ticker'].split(' ')[1]}", className="small text-white"),
            html.Td("CLOSE", className="small text-warning"),
            html.Td(h['contracts'], className="small"),
            html.Td(f"${h['exit_px']:.2f}", className="small"),
            html.Td(f"${h['pnl']:.2f}", style={'color': pnl_col}, className="fw-bold text-end")
        ]))
    
    hist_table = dbc.Table([
        html.Thead(html.Tr([html.Th("Time"), html.Th("Ticker"), html.Th("Action"), html.Th("Qty"), html.Th("Price"), html.Th("P&L")]))
    ] + [html.Tbody(hist_rows)], bordered=False, hover=True, size='sm', color='dark')

    # --- C. ACCOUNT STATS ---
    # Fetch stats using the new function
    stats = engine_simulator.get_portfolio_stats()
    
    # Check if we have valid stats to display
    if stats:
        pnl_color = "#00bc8c" if stats['pnl_abs'] >= 0 else "#e74c3c"
        
        account_stats_layout = dbc.Row([
            # Column 1: Available Balance
            dbc.Col([
                html.H6("AVAILABLE BALANCE", className="text-muted small mb-0"),
                html.H3(f"${stats['liquid_cash']:,.2f}", className="text-white fw-bold font-monospace mb-0", style={'color': '#00bc8c !important'}),
            ], width=6),
            
            # Column 2: P&L Metrics
            dbc.Col([
                html.H6("TOTAL P&L", className="text-muted small mb-0 text-end"),
                html.H4(f"${stats['pnl_abs']:+,.2f}", className="fw-bold font-monospace mb-0 text-end", style={'color': pnl_color}),
                html.Div(f"{stats['pnl_pct']:+.2f}%", className="small font-monospace text-end", style={'color': pnl_color})
            ], width=6)
        ])
    else:
        account_stats_layout = html.Div("Loading Stats...", className="text-muted")


    # --- TIMEZONE ENFORCEMENT: USE config.TZ_LOCAL ---
    current_time_pst = datetime.now(config.TZ_LOCAL).strftime("%H:%M:%S")

    return price_str, oracle_html, fig, current_time_pst, active_rows, hist_table, account_stats_layout, feedback