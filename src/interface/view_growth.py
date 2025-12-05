import sys
import dash
from dash import dcc, html, dash_table, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import duckdb
from pathlib import Path
from datetime import date, timedelta
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

# ==============================================================================
# 1. PATH CONSTITUTION
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("CapitalLab")

# ==============================================================================
# 2. CORE LOGIC
# ==============================================================================
def get_business_days(start_date_str, end_date_str):
    """Generates valid US business days between dates."""
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    start = pd.to_datetime(start_date_str)
    end = pd.to_datetime(end_date_str)
    return pd.date_range(start=start, end=end, freq=us_bd)

def calculate_silver_arrow(start_bal, daily_goal_pct, business_days):
    """Calculates the geometric growth target (The Silver Arrow)."""
    dates = [business_days[0]]
    balances = [float(start_bal)]
    current_bal = float(start_bal)
    goal_multiplier = 1 + (float(daily_goal_pct) / 100.0)
    for current_date in business_days[1:]:
        current_bal *= goal_multiplier
        dates.append(current_date)
        balances.append(current_bal)
    return pd.DataFrame({'Date': dates, 'TargetBalance': balances})

def fetch_backtest_distribution():
    """Fetches real trade returns from the Backtest Log (The DNA)."""
    if not config.DB_FILE.exists(): return None, "Vault Not Found"
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = con.execute("SHOW TABLES").fetchall()
        table_list = [t[0] for t in tables]
        if config.TBL_SIM_LOG not in table_list:
            con.close()
            return None, "No Backtest Data Found."
        columns = [c[0] for c in con.execute(f"DESCRIBE {config.TBL_SIM_LOG}").fetchall()]
        pnl_col = 'pnl' if 'pnl' in columns else 'net_pnl'
        query = f"SELECT return_pct, {pnl_col} as pnl FROM {config.TBL_SIM_LOG} WHERE return_pct IS NOT NULL"
        df = con.execute(query).df()
        con.close()
        if df.empty: return None, "Backtest Log is Empty."
        
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] <= 0]
        
        stats = {
            'count': len(df),
            'win_rate': (len(wins) / len(df)) * 100,
            'avg_win': wins['return_pct'].mean() if not wins.empty else 0,
            'avg_loss': losses['return_pct'].mean() if not losses.empty else 0,
            'pool': df['return_pct'].values
        }
        return stats, "OK"
    except Exception as e: return None, f"DB Error: {e}"

def run_monte_carlo(start_bal, risk_val, risk_mode, sim_days, num_sims, return_pool):
    """
    Runs Monte Carlo simulation with Dynamic Position Sizing.
    risk_mode: 'PCT' (Compound) or 'FIXED' (Linear)
    """
    if return_pool is None or len(return_pool) == 0: return np.zeros((num_sims, sim_days))
    sim_results = []
    
    decimal_pool = return_pool / 100.0
    
    for _ in range(num_sims):
        balance = float(start_bal)
        curve = [balance]
        daily_returns = np.random.choice(decimal_pool, size=sim_days-1)
        
        for ret in daily_returns:
            if risk_mode == 'PCT':
                # Compounding: Risk % of current balance
                bet_size = balance * (float(risk_val) / 100.0)
            else:
                # Linear: Risk fixed $ amount (cannot exceed balance)
                bet_size = min(float(risk_val), balance)
                
            pnl = bet_size * ret
            balance += pnl
            
            # Blowup Protection
            if balance < 0.01: balance = 0.01
            
            curve.append(balance)
        sim_results.append(curve)
    return np.array(sim_results)

# ==============================================================================
# 3. RENDER LAYOUT
# ==============================================================================
def render():
    today = date.today()
    default_end = today + timedelta(days=60)

    return dbc.Container([
        # --- TITLE ---
        dbc.Row([
            dbc.Col([
                html.H2("CAPITAL FORECAST", className="display-6 fw-bold text-white"),
                html.P("Strategic Reality (Monte Carlo) vs. The Silver Arrow (Goal)", className="lead", style={'color': '#AAA'}),
                html.Hr(style={'borderColor': '#444'})
            ], width=12)
        ]),

        # --- MAIN CONTROL BOARD ---
        dbc.Row([
            # LEFT: CONTROLS
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("⚙️ MISSION PARAMETERS", className="fw-bold", style={'backgroundColor': '#1E222D', 'color': '#f39c12', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        html.Label("Start Capital ($)", style={'color': '#FFF'}),
                        dbc.Input(id='cap-start', type='number', value=600, step=100, className="mb-3", style={'backgroundColor': '#2A2E39', 'color': 'white', 'border': '1px solid #555'}),
                        
                        html.Label("Silver Arrow Goal (Daily %)", style={'color': '#f39c12', 'fontWeight': 'bold'}),
                        dbc.Input(id='cap-goal', type='number', value=10.0, step=0.5, className="mb-3", style={'backgroundColor': '#2A2E39', 'color': '#f39c12', 'border': '1px solid #f39c12'}),
                        
                        html.Hr(style={'borderColor': '#444'}),
                        
                        # --- NEW: POSITION SIZING TOGGLE ---
                        html.Label("Position Sizing Model", style={'color': '#00d2ff', 'fontWeight': 'bold'}),
                        dbc.RadioItems(
                            id='cap-sizing-mode',
                            options=[
                                {'label': 'Compound (% Equity)', 'value': 'PCT'},
                                {'label': 'Fixed ($ Risk)', 'value': 'FIXED'},
                            ],
                            value='PCT',
                            inline=True,
                            className="mb-2 text-white"
                        ),
                        
                        html.Label("Risk Value (% or $)", style={'color': '#AAA'}),
                        dbc.Input(id='cap-risk', type='number', value=20.0, className="mb-3", style={'backgroundColor': '#2A2E39', 'color': '#00d2ff', 'border': '1px solid #00d2ff'}),
                        # -----------------------------------

                        html.Label("Projection Horizon", style={'color': '#FFF'}),
                        dcc.DatePickerRange(
                            id='cap-dates',
                            min_date_allowed=date(2024, 1, 1),
                            start_date=today,
                            end_date=default_end,
                            className="mb-3 w-100",
                            style={'backgroundColor': '#2A2E39', 'color': 'white', 'border': '1px solid #444'}
                        ),
                        
                        dbc.Button("🎲 RUN SIMULATION", id='cap-run-btn', color="success", className="w-100 fw-bold mt-2", style={'borderRadius': '0px'})
                    ], style={'backgroundColor': '#131722'})
                ], className="shadow mb-4", style={'border': '1px solid #333'}),

                # SOURCE STATS CARD
                dbc.Card([
                    dbc.CardHeader("🧬 STRATEGY DNA (From Backtester)", className="fw-bold", style={'backgroundColor': '#1E222D', 'color': '#00d2ff', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        html.Div(id='cap-dna-status', className="small mb-3", style={'color': '#AAA'}), 
                        dbc.Row([
                            dbc.Col([html.H6("Win Rate", className="small", style={'color': '#CCC'}), html.H4(id='cap-dna-win', style={'color': '#00ff41'})]),
                            dbc.Col([html.H6("Count", className="small", style={'color': '#CCC'}), html.H4(id='cap-dna-count', style={'color': '#FFF'})])
                        ], className="mb-2"),
                        dbc.Row([
                            dbc.Col([html.H6("Avg Win", className="small", style={'color': '#CCC'}), html.H4(id='cap-dna-awin', style={'color': '#00ff41'})]),
                            dbc.Col([html.H6("Avg Loss", className="small", style={'color': '#CCC'}), html.H4(id='cap-dna-aloss', style={'color': '#ff3860'})])
                        ])
                    ], style={'backgroundColor': '#131722'})
                ], className="shadow", style={'border': '1px solid #333'})

            ], width=12, md=3),

            # RIGHT: THE CONE
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("📉 PROBABILITY CONE (Log Scale)", className="fw-bold", style={'backgroundColor': '#1E222D', 'color': '#FFF', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='cap-chart', 
                                style={'height': '750px', 'width': '100%'}, 
                                config={'responsive': True} 
                            ),
                            type="cube", color="#00bc8c"
                        )
                    ], style={'backgroundColor': '#000000', 'padding': '0px'})
                ], className="shadow h-100", style={'border': '1px solid #333'})
            ], width=12, md=9)
        ]),

        # --- OUTCOMES ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.H6("Silver Arrow Target", className="text-uppercase", style={'color': '#CCC'}),
                                html.H2(id='cap-out-target', className="display-6", style={'color': '#f39c12'})
                            ], className="text-center", style={'borderRight': '1px solid #333'}),
                            dbc.Col([
                                html.H6("Median Reality (50%)", className="text-uppercase", style={'color': '#CCC'}),
                                html.H2(id='cap-out-median', className="display-6", style={'color': '#00d2ff'})
                            ], className="text-center", style={'borderRight': '1px solid #333'}),
                            dbc.Col([
                                html.H6("Probability of Success", className="text-uppercase", style={'color': '#CCC'}),
                                html.H2(id='cap-out-prob', className="display-6", style={'color': '#00ff41'})
                            ], className="text-center", style={'borderRight': '1px solid #333'}),
                            dbc.Col([
                                html.H6("Risk of Ruin (<10% Cap)", className="text-uppercase", style={'color': '#CCC'}),
                                html.H2(id='cap-out-ruin', className="display-6", style={'color': '#ff3860'})
                            ], className="text-center")
                        ])
                    ], style={'backgroundColor': '#131722'})
                ], className="mt-4 shadow", style={'border': '1px solid #444'})
            ], width=12)
        ]),

        # --- NEW: SPECULATIVE LEDGER ---
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("📜 SPECULATIVE LEDGER (Daily Median Variance)", className="fw-bold", style={'backgroundColor': '#1E222D', 'color': '#AAA', 'borderBottom': '1px solid #444'}),
                    dbc.CardBody([
                        dash_table.DataTable(
                            id='cap-ledger',
                            columns=[
                                {"name": "Business Day", "id": "date"},
                                {"name": "Silver Arrow Target", "id": "target"},
                                {"name": "Median Reality", "id": "reality"},
                                {"name": "Variance ($)", "id": "variance"},
                                {"name": "Variance (%)", "id": "pct_var"},
                            ],
                            data=[],
                            style_header={
                                'backgroundColor': '#1E222D',
                                'color': 'white',
                                'fontWeight': 'bold',
                                'border': '1px solid #333'
                            },
                            style_cell={
                                'backgroundColor': '#000000',
                                'color': '#DDD',
                                'border': '1px solid #333',
                                'fontFamily': 'monospace',
                                'textAlign': 'right'
                            },
                            style_data_conditional=[
                                {
                                    'if': {'filter_query': '{variance} > 0', 'column_id': 'variance'},
                                    'color': '#00ff41', 'fontWeight': 'bold'
                                },
                                {
                                    'if': {'filter_query': '{variance} < 0', 'column_id': 'variance'},
                                    'color': '#ff3860', 'fontWeight': 'bold'
                                },
                            ],
                            page_size=15,
                            style_as_list_view=True
                        )
                    ], style={'backgroundColor': '#000000'})
                ], className="mt-4 shadow mb-5", style={'border': '1px solid #444'})
            ], width=12)
        ])

    ], fluid=True, style={'backgroundColor': '#000000', 'minHeight': '100vh', 'padding': '20px'})

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    [Output('cap-chart', 'figure'),
     Output('cap-dna-status', 'children'), Output('cap-dna-win', 'children'), Output('cap-dna-count', 'children'),
     Output('cap-dna-awin', 'children'), Output('cap-dna-aloss', 'children'),
     Output('cap-out-target', 'children'), Output('cap-out-median', 'children'),
     Output('cap-out-prob', 'children'), Output('cap-out-ruin', 'children'),
     Output('cap-ledger', 'data')],
    [Input('cap-run-btn', 'n_clicks')],
    [State('cap-start', 'value'), State('cap-goal', 'value'), State('cap-risk', 'value'),
     State('cap-dates', 'start_date'), State('cap-dates', 'end_date'),
     State('cap-sizing-mode', 'value')]  # <--- NEW STATE INPUT
)
def update_capital_lab(n_clicks, start_bal, goal_pct, risk_val, start_date, end_date, sizing_mode):
    start_bal = float(start_bal) if start_bal else 600.0
    goal_pct = float(goal_pct) if goal_pct else 10.0
    risk_val = float(risk_val) if risk_val else 20.0
    
    empty_fig = go.Figure()
    empty_fig.update_layout(
        template="plotly_dark", 
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        xaxis={'showgrid': False, 'visible': False}, 
        yaxis={'showgrid': False, 'visible': False},
        font=dict(color="white"),
        margin=dict(l=0, r=0, t=50, b=0)
    )
    
    if not start_date or not end_date: 
        return empty_fig, "Select Dates", "--", "--", "--", "--", "$0", "$0", "0%", "0%", []

    stats, msg = fetch_backtest_distribution()
    if not stats:
        empty_fig.update_layout(
            annotations=[dict(text=f"DATA LINK SEVERED: {msg}", x=0.5, y=0.5, showarrow=False, font=dict(color="#ff3333", size=16))]
        )
        return empty_fig, msg, "--", "--", "--", "--", "$0", "$0", "0%", "0%", []

    business_days = get_business_days(start_date, end_date)
    if len(business_days) < 2: 
        return empty_fig, "Date Range Too Short", "--", "--", "--", "--", "$0", "$0", "0%", "0%", []
        
    silver_arrow_df = calculate_silver_arrow(start_bal, goal_pct, business_days)
    
    # Run Monte Carlo with Sizing Mode
    sim_paths = run_monte_carlo(start_bal, risk_val, sizing_mode, len(business_days), 1000, stats['pool'])

    final_values = sim_paths[:, -1]
    median_outcome = np.median(final_values)
    median_path = np.median(sim_paths, axis=0)
    
    target_outcome = silver_arrow_df['TargetBalance'].iloc[-1]
    prob_success = (np.sum(final_values >= target_outcome) / 1000.0) * 100
    prob_ruin = (np.sum(final_values < (start_bal * 0.1)) / 1000.0) * 100

    # --- CHART GENERATION ---
    fig = go.Figure()
    for i in range(min(50, len(sim_paths))):
        fig.add_trace(go.Scatter(x=silver_arrow_df['Date'], y=sim_paths[i], mode='lines', line=dict(width=1, color='rgba(0, 210, 255, 0.05)'), hoverinfo='skip', showlegend=False))
    
    fig.add_trace(go.Scatter(x=silver_arrow_df['Date'], y=median_path, mode='lines', name='Median Reality', line=dict(color='#00d2ff', width=3)))
    fig.add_trace(go.Scatter(x=silver_arrow_df['Date'], y=silver_arrow_df['TargetBalance'], mode='lines', name=f'Silver Arrow ({goal_pct}%)', line=dict(color='#f39c12', width=3, dash='dot')))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=50, r=50, t=50, b=50),
        yaxis_title="Account Balance ($) - Log Scale",
        font=dict(color="white"),
        yaxis=dict(gridcolor='#333', showgrid=True, type="log"),
        xaxis=dict(gridcolor='#333', showgrid=True),
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center")
    )

    # --- LEDGER GENERATION ---
    ledger_data = []
    for i, date_obj in enumerate(silver_arrow_df['Date']):
        tgt = silver_arrow_df['TargetBalance'].iloc[i]
        reality = median_path[i]
        diff = reality - tgt
        pct_diff = (diff / tgt) * 100 if tgt != 0 else 0
        
        ledger_data.append({
            'date': date_obj.strftime('%Y-%m-%d'),
            'target': f"${tgt:,.2f}",
            'reality': f"${reality:,.2f}",
            'variance': round(diff, 2), # Keep raw number for conditional formatting check
            'pct_var': f"{pct_diff:+.2f}%"
        })

    return (fig, "Connected to Vault", 
            f"{stats['win_rate']:.1f}%", 
            f"{stats['count']}", 
            f"{stats['avg_win']:.1f}%", 
            f"{stats['avg_loss']:.1f}%", 
            f"${target_outcome:,.0f}", 
            f"${median_outcome:,.0f}", 
            f"{prob_success:.1f}%", 
            f"{prob_ruin:.1f}%",
            ledger_data)