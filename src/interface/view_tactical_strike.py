import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import numpy as np
from scipy.stats import norm
import sys
import math
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

try:
    from src.core import engine_ml_precision
except ImportError:
    class DummyEngine:
        def predict_success(self, *args, **kwargs): return 55.0
    engine_ml_precision = DummyEngine()

# ==============================================================================
# 1. MATH ENGINES (Black-Scholes & Probability)
# ==============================================================================
def bs_price_and_greeks(S, K, T_years, r, sigma, option_type):
    if T_years <= 0 or sigma <= 0:
        return (max(0.0, S - K) if option_type == "CALL" else max(0.0, K - S)), 0, 0, 0
    
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T_years) / (sigma * np.sqrt(T_years))
    d2 = d1 - sigma * np.sqrt(T_years)
    
    if option_type == "CALL":
        price = S * norm.cdf(d1) - K * np.exp(-r * T_years) * norm.cdf(d2)
        delta = norm.cdf(d1)
        theta = (- (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T_years)) - r * K * np.exp(-r * T_years) * norm.cdf(d2))
    else:
        price = K * np.exp(-r * T_years) * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1
        theta = (- (S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T_years)) + r * K * np.exp(-r * T_years) * norm.cdf(-d2))
        
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T_years))
    return price, delta, gamma, theta / 365.0

def calculate_probability_density(prices, spot, iv_pct, days_to_expiry):
    sigma = iv_pct / 100.0
    t_years = max(0.0001, days_to_expiry / 365.0)
    mu = np.log(spot) - (0.5 * sigma**2) * t_years
    std_dev = sigma * np.sqrt(t_years)
    pdf = (1 / (prices * std_dev * np.sqrt(2 * np.pi))) * np.exp(-((np.log(prices) - mu)**2) / (2 * std_dev**2))
    pdf_normalized = (pdf / np.max(pdf)) * 100 
    return pdf_normalized

# ==============================================================================
# 2. LAYOUT ARCHITECTURE
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("📊 STRATEGIC OPTIONS MATRIX", className="fw-bold text-white mb-0"),
                html.P("REAL-WORLD DOLLAR PnL & TIME DECAY RADAR", className="text-muted small fw-bold")
            ], width=12)
        ], className="mb-3 py-2 border-bottom border-secondary"),

        dbc.Row([
            # --- LEFT COL: INPUTS & CONTEXT ---
            dbc.Col([
                # 1. MARKET INPUTS
                dbc.Card([
                    dbc.CardHeader("TRADE SETUP", className="fw-bold small text-info font-monospace"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Label("XSP SPOT", className="small text-muted mb-0"), dbc.Input(id="ts-spot", type="number", value=585.00, step=0.01, className="font-monospace bg-dark text-white form-control-sm mb-2")]),
                            dbc.Col([html.Label("IV (%) [Match VIX]", className="small text-muted mb-0"), dbc.Input(id="ts-iv", type="number", value=29.0, step=0.1, className="font-monospace bg-dark text-white form-control-sm mb-2")])
                        ]),
                        dbc.Row([
                            dbc.Col([html.Label("ENTRY TIME (PST)", className="small text-warning fw-bold mb-0"), dbc.Input(id="ts-time", type="time", value="06:40", className="font-monospace bg-dark text-warning border-warning form-control-sm mb-2")]),
                            dbc.Col([html.Label("CAPITAL ($)", className="small text-success fw-bold mb-0"), dbc.Input(id="ts-capital", type="number", value=2000, step=100, className="font-monospace bg-dark text-success border-success form-control-sm mb-2")])
                        ]),
                        
                        html.Hr(className="border-secondary mt-1 mb-2"),
                        html.Label("PRIMARY PARAMETERS", className="small text-info fw-bold mb-1"),
                        dbc.Row([
                            dbc.Col([html.Label("STRIKE PRICE", className="small text-muted mb-0"), dbc.Input(id="ts-strike", type="number", value=586.00, step=1, className="font-monospace bg-dark text-white form-control-sm mb-2")]),
                            dbc.Col([html.Label("PREMIUM ($)", className="small text-muted mb-0"), dbc.Input(id="ts-prem", type="number", value=1.54, step=0.01, className="font-monospace bg-dark text-white form-control-sm mb-2")])
                        ]),
                        dbc.Row([
                            dbc.Col([html.Label("GOAL (%)", className="small text-muted mb-0"), dbc.Input(id="ts-target-pct", type="number", value=50, step=1, className="font-monospace bg-dark text-white form-control-sm mb-2")]),
                            dbc.Col([html.Label("STOP (%)", className="small text-muted mb-0"), dbc.Input(id="ts-stop-pct", type="number", value=30, step=1, className="font-monospace bg-dark text-white form-control-sm mb-2")])
                        ]),

                        dbc.RadioItems(id="ts-type", options=[{"label": "CALL", "value": "CALL"}, {"label": "PUT", "value": "PUT"}], value="CALL", inline=True, className="text-white mb-2 font-monospace small"),
                        dbc.Button("GENERATE SCENARIO MATRIX", id="ts-btn-calc", color="info", className="w-100 fw-bold font-monospace mt-1")
                    ], className="p-2")
                ], className="border-secondary bg-black shadow-sm mb-3"),
                
                # 2. MACRO CONTEXT RADAR
                dbc.Card([
                    dbc.CardHeader("ENVIRONMENTAL RADAR", className="fw-bold small text-warning font-monospace"),
                    dbc.CardBody([
                        html.Div("VIX TRAJECTORY (PRESSURE)", className="small text-muted fw-bold"),
                        dbc.Progress(value=75, color="danger", className="mb-2", style={"height": "5px"}),
                        html.Div("Expanding (Gamma Favorable)", className="small text-danger font-monospace mb-3"),
                        
                        html.Div("TREND ALIGNMENT (XSP)", className="small text-muted fw-bold"),
                        dbc.Row([
                            dbc.Col([html.Div("1m", className="small text-muted"), html.Div("BULL", className="badge bg-success font-monospace")], width=4),
                            dbc.Col([html.Div("5m", className="small text-muted"), html.Div("BULL", className="badge bg-success font-monospace")], width=4),
                            dbc.Col([html.Div("1D", className="small text-muted"), html.Div("BEAR", className="badge bg-danger font-monospace")], width=4),
                        ], className="text-center mb-0"),
                    ], className="p-2")
                ], className="border-secondary bg-black shadow-sm mb-3"),

                # 3. LIVE TRADE READOUT
                html.Div(id="ts-stats-readout")

            ], width=12, lg=3),

            # --- RIGHT COL: THE CHART ---
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("REAL-WORLD DOLLAR PnL & PROBABILITY DENSITY", className="fw-bold small text-info font-monospace"),
                    dbc.CardBody([
                        dcc.Graph(id="ts-chart", style={"height": "850px"})
                    ], className="p-0")
                ], className="border-secondary bg-black shadow-sm")
            ], width=12, lg=9)
        ])
    ], fluid=True)

# ==============================================================================
# 3. CORE LOGIC & VISUALIZATION
# ==============================================================================
@callback(
    [Output("ts-chart", "figure"), Output("ts-stats-readout", "children")],
    Input("ts-btn-calc", "n_clicks"),
    [State("ts-spot", "value"), State("ts-iv", "value"), State("ts-time", "value"),
     State("ts-capital", "value"), State("ts-strike", "value"), State("ts-prem", "value"),
     State("ts-target-pct", "value"), State("ts-stop-pct", "value"), State("ts-type", "value")]
)
def update_matrix(n, spot, iv, entry_time_str, capital, strike, premium, target_pct, stop_pct, otype):
    if not all([spot, iv, entry_time_str, capital, strike, premium, target_pct, stop_pct]): 
        return go.Figure(), html.Div()
    
    # --- DYNAMIC QUANTITY CALCULATION (PRIMARY TRADE) ---
    contract_cost = premium * 100
    if contract_cost <= 0: return go.Figure(), html.Div("INVALID PREMIUM")
    qty = math.floor(capital / contract_cost)
    if qty == 0: return go.Figure(), html.Div("INSUFFICIENT CAPITAL FOR 1 CONTRACT", className="text-danger p-3 fw-bold")
    actual_invested = qty * contract_cost

    # 1. Time Horizon Math
    try:
        entry_dt = datetime.strptime(entry_time_str, "%H:%M")
        expiry_dt = datetime.strptime("13:00", "%H:%M")
    except Exception:
        return go.Figure(), html.Div("INVALID TIME", className="text-danger")

    hours_left = (expiry_dt - entry_dt).total_seconds() / 3600.0
    if hours_left <= 0: return go.Figure(), html.Div("MARKET CLOSED", className="text-danger p-3")

    t_y = hours_left / (24 * 365.0)
    sigma = iv / 100.0
    r = 0.045

    # EXPECTED MOVE & CLASSIFICATION
    expected_move = spot * sigma * np.sqrt(hours_left / 1638.0)
    strike_dist = abs(strike - spot)
    z_score = strike_dist / expected_move if expected_move > 0 else 99
    
    if z_score <= 1.0: viability_text, v_color = "DELTA HEAVY (1-SD SCALP)", "text-success"
    elif z_score <= 2.2: viability_text, v_color = "THE SWEET SPOT (GAMMA)", "text-info"
    else: viability_text, v_color = "LOW PROBABILITY (OUTSIDE 1-SD)", "text-danger"

    # LIMIT PRICE RECOMMENDATION
    sd_target_price = spot + expected_move if otype == "CALL" else spot - expected_move
    rec_premium, _, _, _ = bs_price_and_greeks(sd_target_price, strike, t_y / 2.0, r, sigma, otype)
    rec_return_pct = ((rec_premium - premium) / premium) * 100
    
    if rec_return_pct < 0:
        rec_status, rec_color = "SEVERE THETA DECAY WARNING", "text-danger"
    else:
        rec_status, rec_color = f"VIX-IMPLIED LIMIT: +{rec_return_pct:.1f}%", "text-success"

    # TARGET DOLLAR AMOUNTS
    target_pnl = actual_invested * (target_pct / 100.0)
    stop_pnl = -actual_invested * (stop_pct / 100.0)

    # --- CHART GENERATION (DOLLAR PNL ZOOM) ---
    prices = np.linspace(spot - (expected_move * 1.5), spot + (expected_move * 1.5), 200)
    fig = go.Figure()

    # SHADED RISK/REWARD ZONES
    fig.add_hrect(y0=-actual_invested, y1=stop_pnl, fillcolor="rgba(255, 0, 0, 0.15)", line_width=0, annotation_text="STOP LOSS ZONE", annotation_position="inside top left", annotation_font_color="#ff5555")
    fig.add_hrect(y0=target_pnl, y1=actual_invested * 3, fillcolor="rgba(0, 255, 0, 0.08)", line_width=0, annotation_text="PROFIT TARGET ZONE", annotation_position="inside bottom left", annotation_font_color="#00ff41")

    # VOLATILITY CURVE (PROBABILITY DENSITY)
    pdf = calculate_probability_density(prices, spot, iv, hours_left / 24.0)
    fig.add_trace(go.Scatter(x=prices, y=pdf, fill='tozeroy', mode='none', name="Prob. Density", fillcolor='rgba(148, 163, 184, 0.15)', hoverinfo='skip', yaxis="y2"))

    # --- THEORETICAL ARRAY OVERLAY (Calculated in Dollars for a $2k Investment) ---
    offsets = [1, 2, 3] if otype == "CALL" else [-1, -2, -3]
    array_colors = ["#38bdf8", "#a855f7", "#00ff41"]
    array_readouts = []
    
    for i, off in enumerate(offsets):
        K_ref = spot + off
        p_ref, _, _, _ = bs_price_and_greeks(spot, K_ref, t_y, r, sigma, otype)
        p_ref = max(0.01, p_ref)
        
        # Assume same capital allocation for theoretical lines
        theory_qty = math.floor(capital / (p_ref * 100)) if p_ref > 0 else 0
        
        # Calculate PnL in DOLLARS halfway through the day
        theory_pnl = [((bs_price_and_greeks(p, K_ref, t_y/2, r, sigma, otype)[0] - p_ref) * 100 * theory_qty) for p in prices]
        
        fig.add_trace(go.Scatter(
            x=prices, y=theory_pnl, name=f"Theory {off:+d} (Mid-Day)", line=dict(color=array_colors[i], width=1.5, dash="dot"),
            hovertemplate="<b>Ref Strike:</b> " + str(K_ref) + "<br><b>XSP:</b> $%{x:.2f}<br><b>PnL:</b> $%{y:,.2f}<extra></extra>"
        ))
        
        array_readouts.append(dbc.Row([
            dbc.Col(html.Div(f"{off:+d} ({K_ref:.0f})", style={"color": array_colors[i]}, className="fw-bold"), width=3),
            dbc.Col(html.Div(f"${p_ref:.2f}"), width=3),
            dbc.Col(html.Div(f"{theory_qty} Cts", className="text-muted"), width=6)
        ], className="small font-monospace mb-1"))

    # --- PRIMARY MANUAL STRIKE (THE DECAY GHOST) ---
    pnl_now = [(bs_price_and_greeks(p, strike, t_y, r, sigma, otype)[0] - premium) * 100 * qty for p in prices]
    pnl_decay = [(bs_price_and_greeks(p, strike, t_y/2, r, sigma, otype)[0] - premium) * 100 * qty for p in prices]

    fig.add_trace(go.Scatter(
        x=prices, y=pnl_now, name=f"PRIMARY (T=Now)", line=dict(color="#ffffff", width=4),
        hovertemplate="<b>PRIMARY NOW</b><br><b>XSP:</b> $%{x:.2f}<br><b>PnL:</b> $%{y:,.2f}<extra></extra>"
    ))
    fig.add_trace(go.Scatter(
        x=prices, y=pnl_decay, name=f"PRIMARY (T=Mid-Day)", line=dict(color="#a855f7", width=2, dash="dash"),
        hovertemplate="<b>PRIMARY LATER</b><br><b>XSP:</b> $%{x:.2f}<br><b>PnL:</b> $%{y:,.2f}<extra></extra>"
    ))

    # HORIZONTALS AND VERTICALS
    fig.add_hline(y=0, line_dash="solid", line_color="#475569")
    fig.add_vline(x=spot, line_dash="dash", line_color="#94a3b8", annotation_text="CURRENT SPOT", annotation_position="bottom right")

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=20, b=40), font=dict(family="monospace", color="#f8fafc"),
        xaxis_title="Underlying XSP Price", 
        yaxis=dict(title="Dollar PnL ($)", side="left", range=[-actual_invested * 1.1, target_pnl * 2.5]),
        yaxis2=dict(title="Probability Density", overlaying="y", side="right", showgrid=False, showticklabels=False),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)"), hovermode="x unified"
    )

    # PHYSICS & EV MATH FOR THE PRIMARY STRIKE
    _, delta, gamma, theta_daily = bs_price_and_greeks(spot, strike, t_y, r, sigma, otype)
    total_hourly_theta = (theta_daily / 24.0) * 100 * qty

    try: prob = engine_ml_precision.predict_success(otype, vix_val=iv, rsi_val=50, trade_hour=entry_dt.hour)
    except: prob = 50.0
    
    win_rate = prob / 100.0
    loss_rate = 1.0 - win_rate
    ev_dollars = (win_rate * target_pnl) - (loss_rate * abs(stop_pnl))
    ev_pct = (ev_dollars / actual_invested) * 100

    # READOUT PANEL
    readout = dbc.Card([
        dbc.CardHeader("LIVE TRADE READOUT", className="small fw-bold text-muted p-2"),
        dbc.CardBody([
            html.Div("PRIMARY POSITION METRICS", className="small text-info fw-bold mb-2"),
            dbc.Row([
                dbc.Col([html.Div("CONTRACTS", className="small text-muted"), html.Div(f"{qty} QTY", className="text-warning font-monospace fw-bold")]),
                dbc.Col([html.Div("ACTUAL RISK", className="small text-muted"), html.Div(f"${actual_invested:,.0f}", className="text-danger font-monospace fw-bold")]),
            ], className="mb-3"),

            html.Div("STRIKE PROFILE (BASED ON IV)", className="small text-muted mb-1"),
            html.Div(viability_text, className=f"{v_color} font-monospace fw-bold fs-6 mb-3"),
            
            html.Div("SYSTEM RECOMMENDED LIMIT", className="small text-info fw-bold mb-1 border-top border-secondary pt-2"),
            html.Div(f"${max(0, rec_premium):.2f}", className=f"{rec_color} font-monospace fw-bold fs-3"),
            html.Div(rec_status, className=f"{rec_color} font-monospace small mb-3"),
            
            html.Hr(className="border-secondary"),

            html.Div("TOTAL POSITION THETA BURN", className="small text-danger fw-bold"),
            html.Div(f"-${abs(total_hourly_theta):,.2f} / hr", className="text-danger font-monospace fw-bold fs-5 mb-3"),
            
            html.Hr(className="border-secondary"),
            
            html.Div("CASINO MATH (E.V. BREAKDOWN)", className="small text-info fw-bold mb-2"),
            dbc.Row([
                dbc.Col([html.Div("WIN PROB", className="small text-muted"), html.Div(f"{prob:.1f}%", className="text-info font-monospace fw-bold")]),
                dbc.Col([html.Div("REWARD", className="small text-muted"), html.Div(f"+${target_pnl:,.0f}", className="text-success font-monospace fw-bold")]),
                dbc.Col([html.Div("RISK", className="small text-muted"), html.Div(f"-${abs(stop_pnl):,.0f}", className="text-danger font-monospace fw-bold")]),
            ], className="mb-2"),
            
            dbc.Row([
                dbc.Col([html.Div(f"${ev_dollars:,.2f}", className=f"{'text-success' if ev_dollars > 0 else 'text-danger'} font-monospace fw-bold fs-4")]),
                dbc.Col([html.Div(f"{ev_pct:+.2f}% Edge", className=f"{'text-success' if ev_dollars > 0 else 'text-danger'} font-monospace fw-bold mt-1 text-end")]),
            ]),

            html.Hr(className="border-secondary mt-3"),
            html.Div("THEORETICAL REFERENCE (T=ENTRY)", className="small text-warning fw-bold mb-2"),
            html.P("Estimated values for nearby strikes assuming a $2,000 investment.", className="small text-muted font-monospace lh-sm mb-2"),
            *array_readouts

        ], className="p-3")
    ], className="bg-transparent border-secondary mt-3")

    return fig, readout