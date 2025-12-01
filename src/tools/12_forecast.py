import sys
import os
import dash
from dash import dcc, html, Input, Output, State, register_page, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import duckdb
from pathlib import Path
from datetime import date, datetime, timedelta
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

register_page(__name__, path='/forecast', name='Forecaster')
logger = get_logger("Forecaster")

# Defaults
today = date.today()
default_end = today + timedelta(days=30)

def get_business_days(start_date_str, end_date_str):
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    start = pd.to_datetime(start_date_str)
    end = pd.to_datetime(end_date_str)
    return pd.date_range(start=start, end=end, freq=us_bd)

def calculate_silver_arrow(start_bal, daily_goal_pct, business_days):
    dates = [business_days[0]]
    balances = [start_bal]
    current_bal = start_bal
    goal_multiplier = 1 + (daily_goal_pct / 100.0)
    for current_date in business_days[1:]:
        current_bal *= goal_multiplier
        dates.append(current_date)
        balances.append(current_bal)
    return pd.DataFrame({'Date': dates, 'TargetBalance': balances})

def fetch_simulation_seed_from_db():
    """Queries the 'active_simulation_log' table from the Vault."""
    con = duckdb.connect(str(config.DB_FILE), read_only=True)
    try:
        # Check if table exists
        exists = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'active_simulation_log'").fetchone()[0]
        if not exists:
            return None, "No Simulation Data. Run Backtester First."
            
        df = con.execute("SELECT * FROM active_simulation_log").df()
        
        if df.empty: return None, "Simulation Log is Empty"
        
        wins = df[df['net_pnl'] > 0]
        losses = df[df['net_pnl'] <= 0]
        
        stats = {
            'total_trades': len(df),
            'win_rate': (len(wins) / len(df)) * 100,
            'avg_win': wins['return_pct'].mean() * 100 if not wins.empty else 0,
            'avg_loss': losses['return_pct'].mean() * 100 if not losses.empty else 0,
            'returns_distribution': df['return_pct'].tolist()
        }
        return stats, "Loaded from Database (active_simulation_log)"
    except Exception as e:
        return None, f"DB Error: {str(e)}"
    finally:
        con.close()

def run_monte_carlo(start_bal, risk_pct, sim_days, num_sims, returns_pool):
    if not returns_pool: return np.zeros((num_sims, sim_days))
    pool = np.array(returns_pool)
    sim_results = []
    
    for _ in range(num_sims):
        balance = start_bal
        curve = [balance]
        random_indices = np.random.randint(0, len(pool), size=sim_days-1)
        sampled_returns = pool[random_indices]
        
        for ret in sampled_returns:
            bet_size = balance * (risk_pct / 100.0)
            pnl = bet_size * ret
            balance += pnl
            if balance < 0: balance = 0
            curve.append(balance)
        sim_results.append(curve)
        
    return np.array(sim_results)

# LAYOUT
layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H6("TOOL ID: 2", className="text-muted mb-0"),
            html.H2("FORECASTER: SILVER ARROW INTEGRATION", className="display-6 fw-bold text-success"),
            html.Hr(className="my-2")
        ], width=12)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("SIMULATION PARAMETERS", className="fw-bold text-warning"),
                dbc.CardBody([
                    html.Label("Start Capital ($)"),
                    dbc.Input(id='fc-start-cap', type='number', value=5000, className="mb-2"),
                    html.Label("Daily Goal (%) - 'Silver Arrow' Target"),
                    dbc.Input(id='fc-daily-goal', type='number', value=20.0, step=0.1, className="mb-3 text-warning fw-bold"),
                    html.Label("Forecast Period (Business Days)"),
                    dcc.DatePickerRange(
                        id='fc-date-range',
                        min_date_allowed=date(2020, 1, 1),
                        start_date=today,
                        end_date=default_end,
                        className="mb-3 w-100",
                    ),
                    html.Label("Risk Allocation per Trade (%)"),
                    dbc.Input(id='fc-risk-pct', type='number', value=20, max=100, className="mb-2"),
                    dbc.Button("🎲 RUN HYBRID SIMULATION", id='fc-run-btn', color="success", className="w-100 fw-bold")
                ])
            ], className="shadow mb-3"),
            
            dbc.Card([
                dbc.CardHeader("DATA SOURCE (DB: active_simulation_log)", className="fw-bold text-info"),
                dbc.CardBody([
                    html.Div(id='fc-source-status', className="small text-muted mb-2"),
                    html.Table([
                        html.Tr([html.Td("Win Rate:"), html.Td(id='fc-stat-win', className="fw-bold text-success")]),
                        html.Tr([html.Td("Avg Win:"), html.Td(id='fc-stat-avg-win', className="fw-bold text-success")]),
                        html.Tr([html.Td("Avg Loss:"), html.Td(id='fc-stat-avg-loss', className="fw-bold text-danger")]),
                    ], className="table table-sm table-borderless mb-0")
                ])
            ], className="shadow")
        ], width=12, md=4),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader("PROBABILITY CONE vs. SILVER ARROW TARGET", className="fw-bold text-primary"),
                dbc.CardBody([
                    dcc.Loading(dcc.Graph(id='fc-chart', style={'height': '550px'}), type="graph")
                ])
            ], className="shadow h-100")
        ], width=12, md=8)
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([html.H6("Silver Arrow Target"), html.H3(id='fc-res-target', className="text-warning")], className="text-center"),
                         dbc.Col([html.H6("Prob. of Hitting Target"), html.H3(id='fc-res-prob-target', className="text-info")], className="text-center"),
                        dbc.Col([html.H6("Realistic Median Outcome"), html.H3(id='fc-res-median', className="text-primary")], className="text-center"),
                        dbc.Col([html.H6("Risk of Ruin (<10%)"), html.H3(id='fc-res-ruin', className="text-danger")], className="text-center"),
                    ])
                ])
            ], className="mt-3 shadow")
        ], width=12)
    ])
], fluid=True)

@callback(
    [Output('fc-chart', 'figure'), Output('fc-source-status', 'children'),
     Output('fc-stat-win', 'children'), Output('fc-stat-avg-win', 'children'), Output('fc-stat-avg-loss', 'children'),
     Output('fc-res-target', 'children'), Output('fc-res-prob-target', 'children'),
     Output('fc-res-median', 'children'), Output('fc-res-ruin', 'children')],
    [Input('fc-run-btn', 'n_clicks')],
    [State('fc-start-cap', 'value'), State('fc-daily-goal', 'value'), 
     State('fc-date-range', 'start_date'), State('fc-date-range', 'end_date'),
     State('fc-risk-pct', 'value')]
)
def update_forecast(n_clicks, start_cap, daily_goal, start_date, end_date, risk_pct):
    start_cap = start_cap if start_cap is not None else 5000
    daily_goal = daily_goal if daily_goal is not None else 20.0
    risk_pct = risk_pct if risk_pct is not None else 20.0
    if not start_date or not end_date: return go.Figure(), "Enter Dates", "--", "--", "--", "--", "--", "--", "--"

    business_days = get_business_days(start_date, end_date)
    sim_days = len(business_days)
    if sim_days < 2: return go.Figure(), "Date range too short", "--", "--", "--", "--", "--", "--", "--"

    # SWITCHED TO DB FETCH
    stats, msg = fetch_simulation_seed_from_db()
    if not stats:
        empty_fig = go.Figure()
        empty_fig.update_layout(template="plotly_dark", title=f"Waiting for Data... ({msg})", xaxis={'visible': False}, yaxis={'visible': False})
        return empty_fig, msg, "--", "--", "--", "--", "--", "--", "--"

    silver_df = calculate_silver_arrow(start_cap, daily_goal, business_days)
    target_final_bal = silver_df['TargetBalance'].iloc[-1]

    paths = run_monte_carlo(start_cap, risk_pct, sim_days, 1000, stats['returns_distribution'])
    
    final_values = paths[:, -1]
    median_val = np.median(final_values)
    ruin_prob = (np.sum(final_values < (start_cap * 0.1)) / 1000) * 100
    hit_target_count = np.sum(final_values >= target_final_bal)
    prob_hit_target = (hit_target_count / 1000) * 100

    fig = go.Figure()
    x_axis = silver_df['Date']

    for i in range(min(50, len(paths))):
        fig.add_trace(go.Scatter(x=x_axis, y=paths[i], mode='lines', line=dict(width=1, color='rgba(0, 255, 65, 0.1)'), showlegend=False))
        
    fig.add_trace(go.Scatter(x=x_axis, y=np.median(paths, axis=0), mode='lines', name='Median Reality', line=dict(color='#00ff41', width=3)))
    fig.add_trace(go.Scatter(x=x_axis, y=silver_df['TargetBalance'], mode='lines', name=f'Silver Arrow Goal ({daily_goal}%)', line=dict(color='#FFD700', width=3, dash='dash')))
    
    fig.update_layout(template="plotly_dark", margin=dict(t=30, b=30, l=60, r=50), xaxis_title="Business Days", yaxis_title="Account Balance ($)", legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"))
    
    return (fig, msg, f"{stats['win_rate']:.1f}%", f"+{stats['avg_win']:.1f}%", f"{stats['avg_loss']:.1f}%", f"${target_final_bal:,.0f}", f"{prob_hit_target:.1f}%", f"${median_val:,.0f}", f"{ruin_prob:.1f}%")