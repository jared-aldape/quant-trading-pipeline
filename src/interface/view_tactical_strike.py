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
    return (pdf / np.max(pdf)) * 100 

# ==============================================================================
# 2. LAYOUT ARCHITECTURE
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                html.H2("📊 STRATEGIC OPTIONS MATRIX", className="fw-bold text-white mb-0"),
                html.P("REAL-WORLD DOLLAR PnL & MULTI-STRIKE ARRAY", className="text-muted small fw-bold")
            ], width=12)
        ], className="mb-3 py-2 border-bottom border-secondary"),

        dbc.Row([
            # --- LEFT COL: INPUTS & CONTEXT ---
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("TRADE SETUP & ARRAY METRICS", className="fw-bold small text-info font-monospace"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([html.Label("XSP SPOT", className="small text-muted mb-0"), dbc.Input(id="ts-spot", type="number", value=585.00, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")]),
                            dbc.Col([html.Label("IV (%) [Match VIX]", className="small text-muted mb-0"), dbc.Input(id="ts-iv", type="number", value=29.0, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")])
                        ]),
                        dbc.Row([
                            dbc.Col([html.Label("ENTRY TIME (PST)", className="small text-warning fw-bold mb-0"), dbc.Input(id="ts-time", type="time", value="06:40", className="font-monospace bg-dark text-warning border-warning form-control-sm mb-2")]),
                            dbc.Col([html.Label("CAPITAL ($)", className="small text-success fw-bold mb-0"), dbc.Input(id="ts-capital", type="number", value=2000, step="any", className="font-monospace bg-dark text-success border-success form-control-sm mb-2")])
                        ]),
                        
                        html.Hr(className="border-secondary mt-1 mb-2"),
                        html.Label("REAL MARKET PREMIUMS ($)", className="small text-info fw-bold mb-1"),
                        dbc.Row([
                            dbc.Col([html.Label("Offset 1", className="small text-info mb-0"), dbc.Input(id="ts-prem-1", type="number", value=1.54, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")], width=4),
                            dbc.Col([html.Label("Offset 2", className="small text-info mb-0"), dbc.Input(id="ts-prem-2", type="number", value=0.95, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")], width=4),
                            dbc.Col([html.Label("Offset 3", className="small text-info mb-0"), dbc.Input(id="ts-prem-3", type="number", value=0.55, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")], width=4),
                        ]),

                        html.Label("RISK & TIME THRESHOLDS", className="small text-info fw-bold mt-2 mb-1"),
                        dbc.Row([
                            dbc.Col([html.Label("GOAL (%)", className="small text-muted mb-0"), dbc.Input(id="ts-target-pct", type="number", value=50, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")], width=4),
                            dbc.Col([html.Label("STOP (%)", className="small text-muted mb-0"), dbc.Input(id="ts-stop-pct", type="number", value=30, step="any", className="font-monospace bg-dark text-white form-control-sm mb-2")], width=4),
                            dbc.Col([html.Label("HOLD MINS", className="small text-warning mb-0"), dbc.Input(id="ts-hold-mins", type="number", value=45, step="any", className="font-monospace bg-dark text-warning border-warning form-control-sm mb-2")], width=4)
                        ]),

                        dbc.RadioItems(id="ts-type", options=[{"label": "CALL", "value": "CALL"}, {"label": "PUT", "value": "PUT"}], value="CALL", inline=True, className="text-white mb-2 font-monospace small"),
                        dbc.Button("GENERATE SCENARIO MATRIX", id="ts-btn-calc", color="info", className="w-100 fw-bold font-monospace mt-1")
                    ], className="p-2")
                ], className="border-secondary bg-black shadow-sm mb-3"),
                
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

                html.Div(id="ts-stats-readout")

            ], width=12, lg=3),

            # --- RIGHT COL: THE CHART ---
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("REAL-WORLD DOLLAR PnL (ULTRA-TIGHT ZOOM)", className="fw-bold small text-info font-monospace"),
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
     State("ts-capital", "value"), State("ts-prem-1", "value"), State("ts-prem-2", "value"), State("ts-prem-3", "value"),
     State("ts-target-pct", "value"), State("ts-stop-pct", "value"), State("ts-hold-mins", "value"), State("ts-type", "value")]
)
def update_matrix(n, spot, iv, entry_time_str, capital, prem1, prem2, prem3, target_pct, stop_pct, hold_mins, otype):
    # Failsafe: Ensure all inputs are present and valid
    if None in [spot, iv, capital, prem1, prem2, prem3, target_pct, stop_pct, hold_mins] or not entry_time_str:
        err_fig = go.Figure()
        err_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        return err_fig, html.Div("AWAITING VALID PARAMETERS - PLEASE CHECK INPUTS", className="text-danger p-3 fw-bold font-monospace text-center")
    
    try:
        # Standardize time string parsing to handle browser inconsistencies
        entry_dt = datetime.strptime(entry_time_str[:5], "%H:%M")
        expiry_dt = datetime.strptime("13:00", "%H:%M")
    except Exception:
        err_fig = go.Figure()
        err_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        return err_fig, html.Div("INVALID TIME FORMAT", className="text-danger p-3 fw-bold font-monospace text-center")

    hours_left = (expiry_dt - entry_dt).total_seconds() / 3600.0
    if hours_left <= 0: 
        err_fig = go.Figure()
        err_fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        return err_fig, html.Div("MARKET CLOSED", className="text-danger p-3 fw-bold font-monospace text-center")

    t_y_start = hours_left / (24 * 365.0)
    
    hold_hours = hold_mins / 60.0
    hours_remaining_after_hold = max(0.0001, hours_left - hold_hours)
    t_y_eval = hours_remaining_after_hold / (24 * 365.0)
    
    sigma = iv / 100.0
    r = 0.045

    # ZONES
    target_pnl = capital * (target_pct / 100.0)
    stop_pnl = -capital * (stop_pct / 100.0)

    # --- ⚡ ULTRA-TIGHT ZOOM CALIBRATION ---
    expected_move_hold = spot * sigma * np.sqrt(hold_hours / 1638.0)
    
    # X-Axis: Restrict to just 20% past the expected hold move to keep the chart tightly focused.
    zoom_range = max(1.5, expected_move_hold * 1.2)
    prices = np.linspace(spot - zoom_range, spot + zoom_range, 200)
    
    # Y-Axis: Crop the chart to just outside your Stop and Goal. 
    y_lower_bound = stop_pnl * 1.5
    y_upper_bound = target_pnl * 1.5

    offsets = [1, 2, 3] if otype == "CALL" else [-1, -2, -3]
    premiums = [prem1, prem2, prem3]
    colors = ["#38bdf8", "#a855f7", "#00ff41"]
    
    fig = go.Figure()

    # RENDER ZONES
    fig.add_hrect(y0=y_lower_bound * 2, y1=stop_pnl, fillcolor="rgba(255, 0, 0, 0.15)", line_width=0, annotation_text="STOP LOSS ZONE", annotation_position="inside top left", annotation_font_color="#ff5555")
    fig.add_hrect(y0=target_pnl, y1=y_upper_bound * 2, fillcolor="rgba(0, 255, 0, 0.08)", line_width=0, annotation_text="PROFIT TARGET ZONE", annotation_position="inside bottom left", annotation_font_color="#00ff41")

    # RESTORED ±$ INDICATOR BOX
    fig.add_vrect(
        x0=spot - expected_move_hold, x1=spot + expected_move_hold,
        fillcolor="rgba(0, 255, 65, 0.08)", line_width=1, line_dash="dash", line_color="rgba(0, 255, 65, 0.3)",
        annotation_text=f"{hold_mins}m EXPECTED MOVE (±${expected_move_hold:.2f})", annotation_position="top left",
        annotation_font_color="rgba(0, 255, 65, 0.6)", annotation_font_size=10
    )

    pdf = calculate_probability_density(prices, spot, iv, hold_hours / 24.0)
    fig.add_trace(go.Scatter(x=prices, y=pdf, fill='tozeroy', mode='none', name="Prob. Density", fillcolor='rgba(148, 163, 184, 0.15)', hoverinfo='skip', yaxis="y2"))

    # --- THE MULTI-STRIKE ARRAY ARRAY ---
    array_readouts = []
    
    for i, off in enumerate(offsets):
        K_ref = spot + off
        p_real = premiums[i]
        
        contract_cost = p_real * 100
        qty = math.floor(capital / contract_cost) if contract_cost > 0 else 0
        actual_invested = qty * contract_cost
        
        if qty == 0: continue

        pnl_decay = [((bs_price_and_greeks(p, K_ref, t_y_eval, r, sigma, otype)[0] - p_real) * 100 * qty) for p in prices]
        
        fig.add_trace(go.Scatter(
            x=prices, y=pnl_decay, name=f"Offset {off:+d} (T+{hold_mins}m)", line=dict(color=colors[i], width=4, dash="solid"),
            hovertemplate="<b>Strike:</b> " + str(K_ref) + "<br><b>XSP:</b> $%{x:.2f}<br><b>PnL:</b> $%{y:,.2f}<extra></extra>"
        ))
        
        _, delta, _, theta_daily = bs_price_and_greeks(spot, K_ref, t_y_start, r, sigma, otype)
        total_hourly_theta = (theta_daily / 24.0) * 100 * qty
        
        array_readouts.append(dbc.Row([
            dbc.Col(html.Div(f"{off:+d} ({K_ref:.0f})", style={"color": colors[i]}, className="fw-bold text-center"), width=2),
            dbc.Col(html.Div(f"${p_real:.2f}"), width=2),
            dbc.Col(html.Div(f"{qty} Cts"), width=3),
            dbc.Col(html.Div(f"${actual_invested:,.0f}", className="text-danger"), width=3),
            dbc.Col(html.Div(f"${abs(total_hourly_theta):.0f}/h", className="text-warning"), width=2)
        ], className="small font-monospace mb-2 border-bottom border-dark pb-1"))

    # HORIZONTALS AND VERTICALS
    fig.add_hline(y=0, line_dash="solid", line_color="#475569")
    fig.add_vline(x=spot, line_dash="dash", line_color="#94a3b8", annotation_text="CURRENT SPOT", annotation_position="bottom right")

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=20, b=40), font=dict(family="monospace", color="#f8fafc"),
        xaxis_title="Underlying XSP Price", 
        yaxis=dict(title="Dollar PnL ($)", side="left", range=[y_lower_bound, y_upper_bound]),
        yaxis2=dict(title="Probability Density", overlaying="y", side="right", showgrid=False, showticklabels=False),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)"), hovermode="x unified"
    )

    try: prob = engine_ml_precision.predict_success(otype, vix_val=iv, rsi_val=50, trade_hour=entry_dt.hour)
    except: prob = 50.0

    readout = dbc.Card([
        dbc.CardHeader("ARRAY PHYSICS & RISK METRICS", className="small fw-bold text-muted p-2"),
        dbc.CardBody([
            html.Div("ORACLE PROBABILITY", className="small text-info fw-bold mb-1"),
            html.Div(f"{prob:.1f}% Win Probability", className="fs-5 fw-bold text-info font-monospace mb-3"),

            html.Div(f"TIME VELOCITY: T+{hold_mins} MINS", className="small text-warning fw-bold mb-2 border-top border-secondary pt-2"),
            html.P(f"Chart is dynamically zoomed to the ±$ boundary of your expected {hold_mins}m window.", className="small text-muted font-monospace lh-sm mb-3"),

            html.Div("STRIKE ARRAY METRICS", className="small text-info fw-bold mb-2 border-top border-secondary pt-2"),
            dbc.Row([
                dbc.Col([html.Div("STRK", className="small text-muted fw-bold text-center")], width=2),
                dbc.Col([html.Div("PREM", className="small text-muted fw-bold")], width=2),
                dbc.Col([html.Div("QTY", className="small text-muted fw-bold")], width=3),
                dbc.Col([html.Div("RISK", className="small text-muted fw-bold")], width=3),
                dbc.Col([html.Div("THETA", className="small text-muted fw-bold")], width=2)
            ], className="mb-1 pb-1 border-bottom border-secondary"),
            *array_readouts,
            
            html.Hr(className="border-secondary mt-3"),
            html.Div("STRATEGIC DECISION ENGINE", className="small text-warning fw-bold mb-2"),
            html.P(f"1. Chart lines now show the exact dollar return accounting for {hold_mins}m of theta decay.", className="small text-muted font-monospace lh-sm mb-1"),
            html.P("2. The Green Box explicitly tells you the realistic range (±$) the market can move during this window.", className="small text-muted font-monospace lh-sm mb-1"),
            html.P("3. Choose the offset that reliably breaks into the Green Zone BEFORE it exits the VIX Expected Move Box.", className="small text-muted font-monospace lh-sm mb-0")

        ], className="p-3")
    ], className="bg-transparent border-secondary mt-3")

    return fig, readout