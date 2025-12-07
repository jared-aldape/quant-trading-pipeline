import dash
from dash import dcc, html, callback, Input, Output, State, ctx
import dash_bootstrap_components as dbc
from src.core import engine_simulator, engine_ml
from src.utils import config
from datetime import datetime

def render():
    return dbc.Container([
        # 1. HEADS UP DISPLAY (Top)
        dbc.Row([
            dbc.Col([
                html.H6("QUANT OS MOBILE", className="text-muted text-center mb-0 font-monospace"),
                html.H1(id='mob-pnl', className="display-2 fw-bold text-center mb-0"),
                html.Div(id='mob-balance', className="text-center text-info small font-monospace")
            ], width=12)
        ], className="mt-4 mb-4"),

        # 2. ORACLE SENTIMENT
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H5("ORACLE FORECAST", className="text-center text-muted small"),
                        dbc.Row([
                            dbc.Col(html.H3(id='mob-oracle-call', className="text-center"), width=6),
                            dbc.Col(html.H3(id='mob-oracle-put', className="text-center"), width=6),
                        ])
                    ])
                ], className="shadow mb-3", style={'backgroundColor': '#1a1a1a'})
            ], width=12)
        ]),

        # 3. ACTIVE POSITIONS
        dbc.Row([
            dbc.Col([
                html.Div(id='mob-positions-container')
            ], width=12)
        ], className="mb-3"),

        # 4. PANIC BUTTON
        dbc.Row([
            dbc.Col([
                dbc.Button("CLOSE ALL POSITIONS", id='mob-panic-btn', color="danger", size="lg", className="w-100 py-3 fw-bold shadow")
            ], width=12)
        ], className="fixed-bottom mb-3 mx-2"),

        dcc.Interval(id='mob-interval', interval=2000, n_intervals=0),
        html.Div(id='mob-feedback', className="d-none") 

    ], fluid=True, style={'minHeight': '100vh', 'paddingBottom': '100px'})

# --- CALLBACKS ---
@callback(
    [Output('mob-pnl', 'children'), Output('mob-pnl', 'style'),
     Output('mob-balance', 'children'),
     Output('mob-oracle-call', 'children'), Output('mob-oracle-put', 'children'),
     Output('mob-positions-container', 'children'),
     Output('mob-feedback', 'children')],
    [Input('mob-interval', 'n_intervals'),
     Input('mob-panic-btn', 'n_clicks')]
)
def update_mobile(n, panic_clicks):
    trigger = ctx.triggered_id
    
    if trigger == 'mob-panic-btn':
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, "PANIC CLOSE INITIATED"

    # Global Stats
    stats = engine_simulator.get_portfolio_stats()
    vix, rsi = engine_simulator.get_vix_metrics()
    p_call = engine_ml.predict_success("CALL", vix, rsi)
    p_put = engine_ml.predict_success("PUT", vix, rsi)
    
    pnl = stats['pnl_abs']
    color = "#00ff41" if pnl >= 0 else "#ff3333"
    pnl_str = f"${pnl:+.2f}"
    bal_str = f"LIQ: ${stats['liquid_cash']:.2f} | EQ: ${stats['total_value']:.2f}"

    # Oracle UI
    c_style = {'color': '#00bc8c'} if p_call > 60 else {'color': '#555'}
    p_style = {'color': '#e74c3c'} if p_put > 60 else {'color': '#555'}
    call_ui = html.Span(f"C {p_call}%", style=c_style)
    put_ui = html.Span(f"P {p_put}%", style=p_style)

    # Positions
    session = engine_simulator.load_session()
    positions = session.get('positions', [])
    pos_ui = []
    
    price = engine_simulator.get_live_price("XSP") 
    r, sigma = engine_simulator.get_market_context()
    T = engine_simulator.get_time_to_close()

    if not positions:
        pos_ui = html.Div("NO ACTIVE THREATS", className="text-center text-muted mt-4 font-monospace")
    else:
        for p in positions:
            cost_basis = p.get('cost_basis', 0.0) 

            if price is None:
                pnl_display = "N/A"
                pnl_pct_display = ""
                u_color = "#555"
            else:
                curr_prem = engine_simulator.black_scholes(price, p['strike'], T, r, sigma, p['type'].lower())
                mkt_val = curr_prem * 100 * p['contracts']
                u_pnl = mkt_val - cost_basis
                
                pct_val = 0.0
                if cost_basis > 0:
                    pct_val = (u_pnl / cost_basis) * 100
                
                pnl_display = f"${u_pnl:+.0f}"
                pnl_pct_display = f"{pct_val:+.1f}%"
                u_color = "#00ff41" if u_pnl >= 0 else "#ff3333"

            card = dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.H5(f"{p['ticker']}", className="text-white fw-bold mb-0"),
                            html.Small(f"{p['contracts']}x @ ${p['entry_px']:.2f}", className="text-muted")
                        ], width=7),
                        dbc.Col([
                            html.H4(pnl_display, style={'color': u_color}, className="text-end mb-0"),
                            html.Div(pnl_pct_display, style={'color': u_color}, className="text-end small")
                        ], width=5)
                    ])
                ])
            ], className="mb-2 bg-dark border-secondary")
            pos_ui.append(card)

    return pnl_str, {'color': color}, bal_str, call_ui, put_ui, pos_ui, ""