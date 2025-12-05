import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from datetime import datetime
import pandas as pd
from src.core import engine_simulator
from src.core import engine_ml 

# ==============================================================================
# 1. LAYOUT (REFACTORED)
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER & CLOCK (BALANCE MOVED)
        dbc.Row([
            dbc.Col([
                html.H2("LIVE TRADING COMMAND", className="display-6 fw-bold text-white"),
                html.P("Real-time execution interface with Project Delta pricing & ML Oracle.", className="text-muted lead")
            ], width=9),
            dbc.Col([
                html.Small(id='live-clock', className="text-end text-info font-monospace display-6 float-end")
            ], width=3)
        ], className="mb-3"),

        # MAIN CONSOLE
        dbc.Row([
            # LEFT: CONTROLS & SESSION STATS
            dbc.Col([
                
                # ACCOUNT BALANCE & ACTIVE POSITION MANIFEST (COMBINED & REFACTORED)
                dbc.Card([
                    dbc.CardHeader("💰 ACCOUNT & ACTIVE POSITION MANIFEST", className="fw-bold text-info", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody([
                        # BALANCE DISPLAY (Improved Visibility)
                        html.H6("ACCOUNT BALANCE", className="text-muted small mb-0"),
                        html.H3(id='live-balance-display', className="text-white fw-bold font-monospace mb-3", style={'color': '#00bc8c !important'}),
                        
                        # ACTIVE POSITION (Status Check)
                        html.Div(id='active-position-display', className="text-center font-monospace")
                    ])
                ], className="shadow mb-3"),
                
                # EXECUTION PANEL
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("EXECUTION TERMINAL", className="fw-bold text-warning"),
                        dbc.Button("↺ RESET SIM", id='btn-reset-sim', color="danger", size="sm", outline=True, className="float-end py-0")
                    ], style={'backgroundColor': '#1a1a1a'}),
                    
                    dbc.CardBody([
                        # PRICE CONTEXT
                        html.H4(id='live-price-display', className="text-center text-white mb-3 font-monospace"),
                        
                        # ORACLE
                        html.Div(id='oracle-display', className="text-center mb-4 font-monospace", style={'fontSize': '1.1rem'}),

                        # ORDER PARAMETERS
                        dbc.Row([
                            dbc.Col([
                                html.Label("Order Type", className="small text-muted"),
                                dbc.Select(
                                    id='input-order-type',
                                    options=[
                                        {'label': 'Market Order', 'value': 'MARKET'},
                                        {'label': 'Limit Order', 'value': 'LIMIT'}
                                    ],
                                    value='MARKET',
                                    className="mb-2 btn-sm bg-dark text-white border-secondary"
                                )
                            ], width=6),
                            dbc.Col([
                                html.Label("Quantity (Contracts)", className="small text-muted"),
                                dbc.Input(id='input-qty', type='number', value=1, min=1, step=1, className="mb-2 bg-dark text-white border-secondary"),
                            ], width=6),
                        ]),

                        dbc.Row([
                            dbc.Col([
                                html.Label("Limit Price ($)", className="small text-muted"),
                                dbc.Input(id='input-limit-price', type='number', placeholder="MKT", disabled=True, className="mb-3 bg-dark text-white border-secondary"),
                            ], width=12)
                        ]),

                        # ENTRY BUTTONS (With disabled check)
                        dbc.Row([
                            dbc.Col(dbc.Button("BUY CALL", id='btn-buy-call', color="success", className="w-100 fw-bold"), width=6),
                            dbc.Col(dbc.Button("BUY PUT", id='btn-buy-put', color="danger", className="w-100 fw-bold"), width=6)
                        ], className="mb-3"),

                        html.Hr(className="border-secondary"),

                        # EXIT CONTROLS
                        html.Label("Position Management", className="small text-warning mb-2"),
                        dbc.InputGroup([
                            dbc.InputGroupText("Sell Qty"),
                            dbc.Input(id='input-sell-qty', type='number', value=1, min=1, step=1),
                            dbc.Button("CLOSE / SELL", id='btn-sell', color="warning", className="fw-bold"),
                        ], className="mb-3"),
                        
                        html.Div(id='execution-feedback', className="mt-2 text-center small text-info")
                    ])
                ], className="shadow mb-3"),
                
                # --- NEW OUTPUTS FOR DYNAMIC BUTTON STATES ---
                html.Div(id='dummy-output-disable-call', style={'display': 'none'}),
                html.Div(id='dummy-output-disable-put', style={'display': 'none'}),

            ], width=12, lg=4),

            # RIGHT: CHART & LEDGER
            dbc.Col([
                # CHART
                dbc.Card([
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(id='live-chart', style={'height': '400px'}, config={'displayModeBar': False})
                        )
                    ], className="p-1", style={'backgroundColor': '#000'})
                ], className="mb-3 shadow"),

                # LEDGER
                dbc.Card([
                    dbc.CardHeader("TRANSACTION LEDGER", className="fw-bold text-white", style={'backgroundColor': '#1a1a1a'}),
                    dbc.CardBody(html.Div(id='live-ledger-table', style={'maxHeight': '300px', 'overflowY': 'auto'}))
                ], className="shadow")
            ], width=12, lg=8)
        ]),

        # THROTTLE: 15 seconds
        dcc.Interval(id='live-interval', interval=15000, n_intervals=0)

    ], fluid=True)

# ==============================================================================
# 2. CALLBACKS
# ==============================================================================

# Enable/Disable Limit Price Input
@callback(
    Output('input-limit-price', 'disabled'),
    Input('input-order-type', 'value')
)
def toggle_limit_input(order_type):
    return order_type != 'LIMIT'
    
# DYNAMIC BUTTON DISABLING (Constraint Override Fix)
@callback(
    [Output('btn-buy-call', 'disabled'),
     Output('btn-buy-put', 'disabled')],
    [Input('live-interval', 'n_intervals')] # Check every interval
)
def update_entry_button_state(n):
    session = engine_simulator.load_session()
    active_trade = session.get('active_trade')
    
    # If an active trade exists, disable both entry buttons 
    # (Enforcing the current single-position limitation in engine_simulator.py)
    if active_trade:
        return True, True
    return False, False


@callback(
    [Output('live-price-display', 'children'),
     Output('oracle-display', 'children'),
     Output('live-chart', 'figure'),
     Output('live-clock', 'children'),
     Output('live-ledger-table', 'children'),
     Output('live-balance-display', 'children'),
     Output('execution-feedback', 'children'),
     Output('active-position-display', 'children'),
     Output('dummy-output-disable-call', 'children'), # Dummy output to trigger button callback
     Output('dummy-output-disable-put', 'children')], # Dummy output
    [Input('live-interval', 'n_intervals'),
     Input('btn-buy-call', 'n_clicks'),
     Input('btn-buy-put', 'n_clicks'),
     Input('btn-sell', 'n_clicks'),
     Input('btn-reset-sim', 'n_clicks')],
    [State('input-qty', 'value'),
     State('input-sell-qty', 'value'),
     State('input-order-type', 'value'),
     State('input-limit-price', 'value')]
)
def update_live_console(n, btn_call, btn_put, btn_sell, btn_reset, qty, sell_qty, order_type, limit_price):
    ctx_id = dash.callback_context.triggered_id
    feedback = ""

    # 1. HANDLE EXECUTION
    if ctx_id == 'btn-reset-sim':
        engine_simulator.reset_session()
        feedback = "Simulation Reset Complete."
        
    elif ctx_id in ['btn-buy-call', 'btn-buy-put']:
        side = "CALL" if ctx_id == 'btn-buy-call' else "PUT"
        # Pass QTY mode to engine
        feedback = engine_simulator.execute_entry(side, size_val=qty, size_mode="QTY")
        if order_type == 'LIMIT' and limit_price:
            feedback += f" (Limit: ${limit_price})" 

    elif ctx_id == 'btn-sell':
        # NOTE: execute_exit handles partial fills.
        feedback = engine_simulator.execute_exit(exit_qty=sell_qty)

    # 2. FETCH DATA & CONTEXT
    price = engine_simulator.get_live_price()
    price_disp = f"SPY: ${price:.2f}" if price else "OFFLINE"
    
    # 3. ASK THE ORACLE
    vix_val, vix_rsi = engine_simulator.get_vix_metrics()
    prob_call = engine_ml.predict_success("CALL", vix_val, vix_rsi)
    
    # --- [BUG FIX APPLIED HERE] ---
    # OLD: prob_put = engine_ml.predict_success("PUT", "PUT", vix_val, vix_rsi)
    # NEW: Removed redundant argument
    prob_put = engine_ml.predict_success("PUT", vix_val, vix_rsi)
    
    oracle_disp = [
        html.Span(f"🤖 CALL: {prob_call}%", style={'color': '#00bc8c' if prob_call > 60 else '#666', 'marginRight': '15px'}),
        html.Span(f"PUT: {prob_put}%", style={'color': '#e74c3c' if prob_put > 60 else '#666'})
    ]
    
    # 4. BUILD CHART
    chart_df = engine_simulator.get_live_chart_data()
    fig = go.Figure()
    if chart_df is not None and not chart_df.empty:
        fig.add_trace(go.Candlestick(
            x=chart_df['Datetime'],
            open=chart_df['Open'], high=chart_df['High'],
            low=chart_df['Low'], close=chart_df['Close'],
            increasing_line_color='#00bc8c', decreasing_line_color='#e74c3c'
        ))
    fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        margin=dict(l=40, r=40, t=20, b=40), 
        xaxis_rangeslider_visible=False,
        uirevision='live_chart'
    )

    # 5. FETCH SESSION STATE
    session = engine_simulator.load_session()
    trades = session.get('trades', [])
    balance = session.get('balance', 600.0)
    active_trade = session.get('active_trade')
    
    balance_str = f"${balance:,.2f}"
    
    # 6. BUILD ACTIVE POSITION MANIFEST 
    active_disp = html.Div("NO ACTIVE POSITION", className="text-muted small p-2")
    current_m2m_pnl = 0.0
    
    if active_trade and price:
        # Calculate Mark-to-Market (M2M) P&L
        r, sigma = engine_simulator.get_market_context()
        T = engine_simulator.get_time_to_close()
        
        raw_premium = engine_simulator.black_scholes(price, active_trade['strike'], T, r, sigma, active_trade['type'].lower())
        m2m_price = raw_premium # Using raw premium as M2M price proxy
        
        current_contract_value = (m2m_price * 100)
        total_market_value = current_contract_value * active_trade['contracts']
        current_m2m_pnl = total_market_value - active_trade['cost_basis']
        
        pnl_color = "#00bc8c" if current_m2m_pnl >= 0 else "#e74c3c"
        
        active_disp = html.Div([
            html.Span(f"{active_trade['contracts']}x {active_trade['type'].upper()} {active_trade['strike']}", className="fw-bold text-white me-3"),
            html.Span(f"Entry: ${active_trade['entry_px']:.2f}", className="text-muted small me-3"),
            html.Span(f"M2M: ${m2m_price:.2f}", className="text-muted small me-3"),
            html.Span(f"P&L: ${current_m2m_pnl:.2f}", style={'color': pnl_color}, className="fw-bold")
        ], className="p-2")


    # 7. BUILD LEDGER (MODIFIED LOGIC: Include Active Trade Entry)
    
    ledger_entries = []
    
    # ADD ACTIVE TRADE ENTRY (FIX: Must show BUY immediately after entry)
    if active_trade:
        # Check if the active trade represents a fresh entry
        entry_time_str = active_trade['entry_time'].split(' ')[1]
        
        # Only add the entry if its action wasn't a CLOSE (which would be in session['trades'])
        # NOTE: A more robust ledger needs a single journal table, but this hack works for display
        
        # Check if this active entry hasn't been closed/logged yet
        is_closed = any(t['entry_time'] == active_trade['entry_time'] for t in trades)
        
        if not is_closed:
             ledger_entries.append({
                'time': entry_time_str,
                'ticker': f"{active_trade['type']} {active_trade['ticker']}",
                'action': "BUY",
                'qty': active_trade['contracts'],
                'price': active_trade['entry_px'],
                'pnl': current_m2m_pnl, # Show current M2M P&L for open trade
                'color': 'text-success'
            })


    # Add all closed trades (exit leg is recorded here)
    for t in trades:
        # Entry Leg (Historical)
        ledger_entries.append({
            'time': t['entry_time'].split(' ')[1],
            'ticker': f"{t['type']} {t['ticker']}",
            'action': "BUY",
            'qty': t['contracts'],
            'price': t['entry_px'],
            'pnl': 0.0,
            'color': 'text-success'
        })
        # Exit Leg 
        ledger_entries.append({
            'time': t['exit_time'].split(' ')[1],
            'ticker': f"{t['type']} {t['ticker']}",
            'action': "CLOSE",
            'qty': t['contracts'],
            'price': t['exit_px'],
            'pnl': t['pnl'],
            'color': 'text-warning'
        })
        
    
    if not ledger_entries:
        table_content = html.Div("No transaction records.", className="text-muted text-center italic mt-4")
    else:
        # Sort by time string (latest entry at the top)
        ledger_entries.sort(key=lambda x: x['time'], reverse=True)
        
        rows = []
        for entry in ledger_entries:
            pnl_val = entry['pnl']
            is_open_buy = (entry['action'] == "BUY" and active_trade and entry['entry_time'] == active_trade['entry_time'])
            
            # P&L coloring logic
            if entry['action'] == "CLOSE":
                pnl_color = "#00bc8c" if pnl_val >= 0 else "#e74c3c"
                pnl_str = f"${pnl_val:.2f}"
            elif is_open_buy:
                pnl_color = "#00bc8c" if pnl_val >= 0 else "#e74c3c"
                pnl_str = f"M2M: ${pnl_val:.2f}" # Label open trade P&L
            else:
                pnl_color = "text-muted"
                pnl_str = "-" # Historical BUY entries show no P&L
            
            
            rows.append(html.Tr([
                html.Td(entry['time'], className="small"),
                html.Td(entry['ticker'], className="small fw-bold text-white"),
                html.Td(entry['action'], className=f"small fw-bold {entry['color']}"),
                html.Td(entry['qty'], className="small text-center"),
                html.Td(f"${entry['price']:.2f}", className="small text-end"),
                html.Td(pnl_str, style={'color': pnl_color}, className="text-end fw-bold"),
            ]))
            
        table_content = dbc.Table([
            html.Thead(html.Tr([
                html.Th("Time"), html.Th("Instrument"), html.Th("Action"), 
                html.Th("Qty", className="text-center"), html.Th("Price", className="text-end"), html.Th("P&L", className="text-end")
            ]))
        ] + [html.Tbody(rows)], bordered=False, hover=True, size='sm', color='dark', className="m-0")

    # The button disabling logic is handled by a separate callback (update_entry_button_state)
    return price_disp, oracle_disp, fig, datetime.now().strftime("%H:%M:%S"), table_content, balance_str, feedback, active_disp, "", ""