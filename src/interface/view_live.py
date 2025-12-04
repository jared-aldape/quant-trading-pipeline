import dash
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from datetime import datetime
from src.core import engine_simulator

# ==============================================================================
# LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        # HEADER & TICKER
        dbc.Row([
            dbc.Col([
                html.H2("LIVE OPTIONS SIMULATOR", className="display-6 fw-bold text-white"),
                html.H5(id="live-ticker-display", className="text-warning font-monospace")
            ], width=8),
            dbc.Col([
                dbc.Button("RESET SESSION", id="btn-reset-sim", color="danger", outline=True, size="sm", className="float-end")
            ], width=4)
        ], className="mb-4"),

        # CONSOLE: CHART + CONTROLS
        dbc.Row([
            # LEFT (Controls - 4/12)
            dbc.Col([
                # ACCOUNT STATUS
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.H6("Cash", className="text-muted"), html.H3(id="sim-balance", className="text-success")], width=6),
                            dbc.Col([html.H6("Active P&L", className="text-muted"), html.H3(id="sim-pnl", className="text-white")], width=6),
                        ]),
                    ])
                ], className="shadow mb-3", style={'backgroundColor': '#131722', 'border': '1px solid #444'}),

                # ENTRY PANEL
                dbc.Card([
                    dbc.CardHeader("ENTRY COMMAND", className="fw-bold text-info", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("Size Value", className="text-white"),
                                dbc.Input(id="sim-entry-size", type="number", value=600, className="mb-2", style={'backgroundColor': '#2A2E39', 'color': 'white', 'border': '1px solid #555'}),
                            ], width=7),
                            dbc.Col([
                                html.Label("Type", className="text-white"),
                                dcc.Dropdown(
                                    id="sim-entry-mode",
                                    options=[
                                        {'label': 'USD ($)', 'value': 'AMT'},
                                        {'label': 'Contracts (#)', 'value': 'QTY'}
                                    ],
                                    value='AMT',
                                    clearable=False,
                                    style={'color': '#000'} 
                                )
                            ], width=5),
                        ]),
                        dbc.Row([
                            dbc.Col(dbc.Button("BUY CALL 🟢", id="btn-buy-call", color="success", className="w-100 mt-3 fw-bold"), width=6),
                            dbc.Col(dbc.Button("BUY PUT 🔴", id="btn-buy-put", color="danger", className="w-100 mt-3 fw-bold"), width=6),
                        ]),
                    ], style={'backgroundColor': '#131722'})
                ], className="shadow mb-3", style={'border': '1px solid #444'}),
                
                # EXIT PANEL (Scale Out)
                dbc.Card([
                    dbc.CardHeader("EXIT COMMAND", className="fw-bold text-warning", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("Qty to Close", className="text-white"),
                                dbc.Input(id="sim-exit-qty", type="number", placeholder="All", className="mb-2", style={'backgroundColor': '#2A2E39', 'color': 'white', 'border': '1px solid #555'}),
                            ], width=6),
                            dbc.Col([
                                html.Label("Action", className="text-white"),
                                dbc.Button("SELL QTY", id="btn-close-qty", color="warning", outline=True, className="w-100"),
                            ], width=6),
                        ]),
                        dbc.Button("CLOSE ALL (FLATTEN)", id="btn-close-all", color="danger", className="w-100 mt-3 fw-bold"),
                        html.Div(id="sim-action-msg", className="text-white small mt-2 text-center fst-italic")
                    ], style={'backgroundColor': '#131722'})
                ], className="shadow mb-4", style={'border': '1px solid #444'}),
                
            ], width=12, md=4),

            # RIGHT (Chart - 8/12)
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("LIVE CANDLESTICK CHART (5m)", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id="sim-live-chart", style={'height': '450px'}), type="cube", color="#00bc8c"),
                        style={'backgroundColor': '#000000'} # Pitch Black Chart BG
                    )
                ], className="shadow mb-4", style={'border': '1px solid #444'}),
                
                # Ledger
                dbc.Card([
                    dbc.CardHeader("SESSION LEDGER", className="fw-bold text-white", style={'backgroundColor': '#1E222D', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody(html.Div(id="sim-ledger-table"), style={'backgroundColor': '#131722'})
                ], className="shadow mb-4", style={'border': '1px solid #444'})

            ], width=12, md=8)
        ]),

        dcc.Interval(id="sim-heartbeat", interval=15*1000, n_intervals=0)

    ], fluid=True, style={'minHeight': '100vh', 'backgroundColor': '#000000'}) 

# ==============================================================================
# CALLBACKS
# ==============================================================================
@callback(
    [Output("live-ticker-display", "children"),
     Output("sim-balance", "children"),
     Output("sim-pnl", "children"),
     Output("sim-ledger-table", "children"),
     Output("sim-live-chart", "figure"), 
     Output("sim-action-msg", "children")],
    [Input("sim-heartbeat", "n_intervals"),
     Input("btn-buy-call", "n_clicks"),
     Input("btn-buy-put", "n_clicks"),
     Input("btn-close-qty", "n_clicks"),
     Input("btn-close-all", "n_clicks"),
     Input("btn-reset-sim", "n_clicks")],
    [State("sim-entry-size", "value"),
     State("sim-entry-mode", "value"),
     State("sim-exit-qty", "value")]
)
def update_simulator(n, btn_call, btn_put, btn_close_qty, btn_close_all, btn_reset, 
                     entry_val, entry_mode, exit_qty):
    
    ctx = dash.callback_context
    trigger = ctx.triggered[0]['prop_id'] if ctx.triggered else "interval"
    msg = ""
    
    # --- 1. HANDLE ACTIONS ---
    if "btn-reset-sim" in trigger:
        engine_simulator.reset_session()
        msg = "Session Reset."
    elif "btn-buy-call" in trigger:
        msg = engine_simulator.execute_entry("CALL", entry_val, entry_mode)
    elif "btn-buy-put" in trigger:
        msg = engine_simulator.execute_entry("PUT", entry_val, entry_mode)
    elif "btn-close-qty" in trigger:
        if exit_qty:
            msg = engine_simulator.execute_exit(exit_qty, "MANUAL_PARTIAL")
        else:
            msg = "Enter Qty to Close."
    elif "btn-close-all" in trigger:
        msg = engine_simulator.execute_exit(None, "MANUAL_FLATTEN")

    # --- 2. LOAD STATE & DATA ---
    state = engine_simulator.load_session()
    chart_data = engine_simulator.get_live_chart_data(ticker="SPY", interval="5m")
    
    # --- 3. UI GENERATION ---
    live_price = engine_simulator.get_live_price("SPY", use_cache=True)
    ticker_text = f"SPY LIVE: ${live_price:.2f}" if live_price else "MARKET OFFLINE"
    bal_text = f"${state['balance']:,.2f}"
    
    # Live P&L Calculation
    active_pnl_display = "--"
    if state['active_trade']:
        t = state['active_trade']
        if live_price:
            T = engine_simulator.get_time_to_close()
            curr_opt_px = engine_simulator.black_scholes(live_price, t['strike'], T, 0.045, 0.15, t['type'].lower())
            
            gross_val = t['contracts'] * curr_opt_px * 100
            est_exit_fees = engine_simulator.calculate_fees(t['contracts']) 
            unrealized_pnl = gross_val - est_exit_fees - t['cost_basis']
            
            color = "#00ff41" if unrealized_pnl >= 0 else "#ff3333" # Neon Green / Hot Red
            active_pnl_display = html.Span(f"${unrealized_pnl:+.2f}", style={'color': color, 'fontWeight': 'bold', 'fontSize': '2rem'})
        else:
            active_pnl_display = "NO FEED"
    
    # Chart Generation (TRADINGVIEW STYLE)
    fig = go.Figure()
    if chart_data is not None and not chart_data.empty:
        fig.add_trace(go.Candlestick(
            x=chart_data['Datetime'], open=chart_data['Open'], 
            high=chart_data['High'], low=chart_data['Low'], 
            close=chart_data['Close'], name='SPY',
            increasing_line_color='#00bc8c', decreasing_line_color='#ef5350' # Standard TV Colors
        ))
        if state['active_trade']:
            fig.add_hline(y=state['active_trade']['underlying_at_entry'], 
                          line_dash="dot", line_color="#ffff00", 
                          annotation_text=f"Entry: ${state['active_trade']['underlying_at_entry']:.2f}")

    fig.update_layout(
        template="plotly_dark", title=None, 
        xaxis_rangeslider_visible=False, 
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        height=450, margin=dict(l=10, r=40, t=10, b=10),
        font=dict(color="white"),
        yaxis=dict(gridcolor='#333', zerolinecolor='#333'), 
        xaxis=dict(gridcolor='#333', zerolinecolor='#333')
    )

    # LEDGER TABLE
    rows = []
    if state['active_trade']:
        t = state['active_trade']
        rows.append(html.Tr([
            html.Td("OPEN", className="text-warning fw-bold"),
            html.Td(t['type']),
            html.Td(f"${t['entry_px']:.2f}"),
            html.Td(t['contracts']),
            html.Td(active_pnl_display), 
            html.Td("--")
        ], style={'backgroundColor': '#1E222D'}))
    
    for t in reversed(state['trades']):
        color = '#00ff41' if t['pnl'] >= 0 else '#ff3333'
        rows.append(html.Tr([
            html.Td(t['exit_time'].split(' ')[1], className="small"),
            html.Td(t['type']),
            html.Td(f"${t['entry_px']:.2f}"),
            html.Td(t['contracts']),
            html.Td(f"${t['pnl']:,.2f}", style={'color': color, 'fontWeight': 'bold'}),
            html.Td(t['reason'], className="small fst-italic text-white-50")
        ]))

    ledger = dbc.Table(
        [html.Thead(html.Tr([html.Th("Time"), html.Th("Type"), html.Th("Entry"), html.Th("Qty"), html.Th("P&L"), html.Th("Reason")]))] +
        [html.Tbody(rows)],
        bordered=True, hover=True, striped=False, color="dark", size="sm", className="text-white"
    )

    return ticker_text, bal_text, active_pnl_display, ledger, fig, msg