import dash
from dash import dcc, html, dash_table, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import pathlib
import sys
import math
from datetime import date, timedelta, datetime
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

# PATH SETUP
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

# Fallback for imports
try:
    from src.core import engine_forensics as forensics
except ImportError:
    forensics = None

# ==============================================================================
# 1. CORE LOGIC (OBSTACLE ENGINE & GEOMETRICS)
# ==============================================================================
def format_money(val):
    """Institutional currency formatter fixing negative sign positioning."""
    if pd.isna(val): return "-"
    try:
        val = float(val)
        if val < 0: return f"-${abs(val):,.2f}"
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "-"

def get_business_days(start_date, days_forward=252):
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    rng = pd.date_range(start=start_date, periods=days_forward, freq=us_bd)
    return rng

def fetch_reality_overlay(source, start_date):
    """Attempts to fetch actual historical performance data from the local ledger."""
    if source == 'none' or forensics is None:
        return None
        
    try:
        if source == 'rh':
            df_actual = forensics.get_daily_equity_curve()
        elif source == 'sig':
            df_actual = forensics.get_backtest_equity_curve()
        else:
            return None
            
        if df_actual is None or df_actual.empty: return None
        
        # Ensure exact date format congruency for the merge
        df_actual['Date'] = pd.to_datetime(df_actual['Date']).dt.date
        df_actual = df_actual[df_actual['Date'] >= pd.to_datetime(start_date).date()]
        return df_actual
    except Exception as e:
        print(f"Overlay Fetch Failed: {e}")
        return None

def calculate_projection(start_bal, daily_rate_pct, tax_rate_pct, start_date, target_goal=None, source='none', loss_freq=4, stop_loss_pct=30.0):
    """
    Generates a Capital projection targeting a NET TAKE HOME goal.
    Includes an Obstacle Engine that sequences losses based on a 1-in-X frequency.
    """
    # Active Trading Realities
    if start_bal is None or start_bal <= 0: start_bal = 2000.0
    if daily_rate_pct is None or daily_rate_pct <= 0: daily_rate_pct = 18.0
    if stop_loss_pct is None: stop_loss_pct = 30.0

    rate = daily_rate_pct / 100.0
    tax_rate = tax_rate_pct / 100.0
    stop_rate = stop_loss_pct / 100.0

    # ⚡ Obstacle Engine: Precise Frequency Sequencing
    if loss_freq is None or loss_freq <= 0:
        base_sequence = ['W'] # Flawless
    else:
        loss_freq = int(loss_freq)
        if loss_freq == 1:
            base_sequence = ['L'] # Ruin
        else:
            base_sequence = ['W'] * (loss_freq - 1) + ['L']
            
    sequence_length = len(base_sequence)
    
    records = []
    current_bal = start_bal
    day_count = 1
    current_date = pd.to_datetime(start_date)
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())

    max_days = 756 # 3-year safety limit
    
    while day_count <= max_days:
        # Determine Status
        seq_idx = (day_count - 1) % sequence_length
        trade_result = base_sequence[seq_idx]

        if trade_result == 'W':
            pnl = current_bal * rate
        else:
            pnl = -(current_bal * stop_rate)

        gross_bal = current_bal + pnl
        
        # Hard stop math at zero
        if gross_bal < 0:
            gross_bal = 0.01

        # Tax logic (Section 1256 rules on aggregate profit)
        total_profit = gross_bal - start_bal
        tax_liability = total_profit * tax_rate if total_profit > 0 else 0
        take_home = gross_bal - tax_liability
        
        # USING EXACT VARIABLES FROM THE ORIGINAL WORKING SCRIPT
        records.append({
            'Day': day_count,
            'Date': current_date.date(),
            'BeginBal': current_bal,
            'TargetGain': pnl,
            'ProjectedBal': gross_bal,
            'TaxLiability': tax_liability,
            'TakeHome': take_home
        })
        
        if target_goal and take_home >= target_goal:
            break
            
        if gross_bal <= 10:
            break

        current_bal = gross_bal
        current_date = current_date + us_bd
        day_count += 1
        
    df_proj = pd.DataFrame(records)
    
    # REALITY OVERLAY MERGE
    df_actual = fetch_reality_overlay(source, start_date)
    
    if df_actual is not None and not df_actual.empty:
        df_proj = pd.merge(df_proj, df_actual[['Date', 'ActualBal']], on='Date', how='left')
        df_proj['Variance'] = df_proj['ActualBal'] - df_proj['ProjectedBal']
    else:
        df_proj['ActualBal'] = np.nan
        df_proj['Variance'] = np.nan
        
    return df_proj

# ==============================================================================
# 2. LAYOUT ARCHITECTURE
# ==============================================================================
def render():
    return html.Div(className="px-4 py-3 container-fluid", children=[
        dbc.Row([
            dbc.Col([
                html.H2("📈 AUM FORECAST & STRESS TEST", className="fw-bold text-white mb-0"),
                html.P("SECTION 1256 TAX MODELING | REALITY OVERLAY | OBSTACLE ENGINE", className="text-muted small fw-bold mb-0")
            ], width=8),
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: STRESS TEST PROJECTION", className="text-end text-warning font-monospace small")
            ], width=4, className="align-self-center")
        ], className="mb-4 py-3 border-bottom border-secondary"),

        dbc.Row([
            # --- LEFT COL: INPUTS ---
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("FORENSIC PARAMETERS", className="fw-bold font-monospace small text-info"),
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col([
                                html.Label("START AUM ($)", className="small text-muted fw-bold"),
                                dbc.Input(id="cap-start", type="number", value=2000, step="any", className="mb-2 font-monospace bg-dark text-white border-secondary")
                            ], width=6),
                            dbc.Col([
                                html.Label("NET TARGET GOAL ($)", className="small text-muted fw-bold"),
                                dbc.Input(id="cap-goal", type="number", value=25000, step="any", className="mb-2 font-monospace bg-dark text-white border-secondary")
                            ], width=6)
                        ], className="mb-2"),

                        dbc.Row([
                            dbc.Col([
                                html.Label("TARGET EDGE (%)", className="small text-success fw-bold"),
                                dbc.Input(id="cap-rate", type="number", value=18.0, step="any", className="mb-2 font-monospace bg-dark text-success border-success")
                            ], width=6),
                            dbc.Col([
                                html.Label("SEC 1256 TAX (%)", className="small text-danger fw-bold"),
                                dbc.Input(id="cap-tax", type="number", value=26.0, step="any", className="mb-2 font-monospace bg-dark text-danger border-danger")
                            ], width=6)
                        ], className="mb-2"),
                        
                        html.Hr(className="border-secondary mt-1 mb-2"),
                        html.Label("OBSTACLE ENGINE (STRESS TEST)", className="small text-warning fw-bold mb-1"),
                        dbc.Row([
                            dbc.Col([
                                html.Label("LOSS FREQ (1 IN X)", className="small text-muted fw-bold"),
                                dbc.Input(id="cap-loss-freq", type="number", value=4, step="any", min=0, className="mb-2 font-monospace bg-dark text-white border-warning")
                            ], width=6),
                            dbc.Col([
                                html.Label("STOP LOSS (%)", className="small text-muted fw-bold"),
                                dbc.Input(id="cap-stop-loss", type="number", value=30, step="any", className="mb-2 font-monospace bg-dark text-white border-warning")
                            ], width=6)
                        ], className="mb-2"),

                        html.Label("START DATE", className="small text-muted fw-bold mt-2"),
                        dcc.DatePickerSingle(
                            id='cap-date',
                            date=date.today(),
                            className="mb-3 d-block",
                            style={"backgroundColor": "#0f172a", "color": "white"}
                        ),

                        html.Hr(className="border-secondary"),
                        
                        html.Label("REALITY OVERLAY SOURCE", className="small text-warning fw-bold mb-2"),
                        dbc.Select(
                            id="cap-source",
                            options=[
                                {"label": "NONE (Pure Geometric Simulation)", "value": "none"},
                                {"label": "🦁 LIVE LEDGER (Robinhood API)", "value": "rh"},
                                {"label": "📡 RAW SIGNAL HISTORY (Backtest)", "value": "sig"}
                            ],
                            value="none",
                            className="mb-4 font-monospace bg-dark text-white border-secondary"
                        ),

                        dbc.Button("CALCULATE STRESS TEST", id="cap-btn", color="warning", className="w-100 fw-bold font-monospace")
                    ])
                ], className="shadow-sm border-secondary h-100 bg-black")
            ], width=4),

            # --- RIGHT COL: DATA ---
            dbc.Col([
                dbc.Row(id="cap-kpi-row", className="mb-3"),

                dbc.Card([
                    dbc.CardHeader("GEOMETRIC TRAJECTORY (GROSS vs NET vs ACTUAL)", className="fw-bold font-monospace small text-info"),
                    dbc.CardBody([
                        dcc.Graph(id="cap-growth-chart", style={"height": "430px"})
                    ], className="p-0")
                ], className="shadow-sm border-secondary mb-3 bg-black")
            ], width=8)
        ]),

        # TABLE
        dbc.Row([
            dbc.Col([
                html.H5("RECONCILIATION LEDGER", className="text-info font-monospace fw-bold mt-2"),
                html.Div(id="cap-table-container")
            ], width=12)
        ])
    ])

# ==============================================================================
# 3. CALLBACK & GENERATION
# ==============================================================================
@callback(
    [Output("cap-kpi-row", "children"),
     Output("cap-growth-chart", "figure"),
     Output("cap-table-container", "children")],
    Input("cap-btn", "n_clicks"),
    [State("cap-start", "value"), State("cap-goal", "value"),
     State("cap-rate", "value"), State("cap-tax", "value"),
     State("cap-date", "date"), State("cap-source", "value"),
     State("cap-loss-freq", "value"), State("cap-stop-loss", "value")]
)
def update_growth(n, start_bal, target_goal, rate, tax, start_date, source, loss_freq, stop_loss):
    if not start_bal: start_bal = 2000
    if not target_goal: target_goal = 25000
    if not rate: rate = 18.0
    if not tax: tax = 26.0
    if loss_freq is None: loss_freq = 4
    if not stop_loss: stop_loss = 30.0
    if not start_date: start_date = date.today()

    # 1. Fetch Mathematical Data
    df = calculate_projection(start_bal, rate, tax, start_date, target_goal, source, loss_freq, stop_loss)
    
    final_row = df.iloc[-1]
    total_days = len(df)
    gross_ending = final_row['ProjectedBal']
    total_tax = final_row['TaxLiability']
    net_ending = final_row['TakeHome']
    end_date_str = final_row['Date'].strftime('%b %d, %Y')
    
    # Calculate Drawdown stats
    loss_count = len(df[df['TargetGain'] < 0])

    # 2. Build KPI Display EXACTLY matching older HTML headers
    kpi_html = [
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("GROSS ENDING", className="text-muted small fw-bold"),
            html.H3(f"${gross_ending:,.0f}", className="text-white font-monospace")
        ]), className="bg-transparent border-secondary")),
        
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("GOAL REACHED", className="text-muted small fw-bold"),
            html.H3(f"{total_days} Days", className="text-warning font-monospace" if loss_count > 0 else "text-success font-monospace"),
            html.Small(f"{end_date_str} | {loss_count} Stops", className="text-danger font-monospace" if loss_count > 0 else "text-muted font-monospace")
        ]), className="bg-transparent border-secondary")),
        
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("EST. TAXES", className="text-muted small fw-bold"),
            html.H3(f"${total_tax:,.0f}", className="text-danger font-monospace")
        ]), className="bg-transparent border-secondary")),
        
        dbc.Col(dbc.Card(dbc.CardBody([
            html.H6("NET TAKE HOME", className="text-muted small fw-bold"),
            html.H3(f"${net_ending:,.0f}", className="text-success font-monospace" if net_ending >= target_goal else "text-danger font-monospace")
        ]), className="bg-transparent border-secondary"))
    ]

    # 3. Build Chart
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(x=df['Date'], y=df['ProjectedBal'], name="Gross Path (Stress Test)", line=dict(color="#38bdf8", width=3)))
    fig.add_trace(go.Scatter(x=df['Date'], y=df['TakeHome'], name="Net Take Home", line=dict(color="#a855f7", width=2, dash="dash")))

    if 'ActualBal' in df.columns and not df['ActualBal'].isna().all():
        fig.add_trace(go.Scatter(x=df['Date'], y=df['ActualBal'], name="ACTUAL LEDGER", line=dict(color="#00ff41", width=4), mode="lines+markers"))

    fig.add_hline(y=target_goal, line_dash="solid", line_color="#00ff41", annotation_text="NET GOAL", annotation_position="top left")

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=20, b=20),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0.5)"),
        yaxis_title="CAPITAL ($)", font=dict(family="monospace", color="#f8fafc"), hovermode="x unified"
    )

    # 4. Build Congruent Table EXACTLY matching previous script
    df_view = df.copy()
    df_view['Date'] = pd.to_datetime(df_view['Date']).dt.strftime('%Y-%m-%d')
    
    # Establish original columns
    cols = ['Day', 'Date', 'BeginBal', 'TargetGain', 'ProjectedBal', 'TaxLiability', 'TakeHome']
    
    # Insert Actuals EXACTLY as they used to be injected
    if 'ActualBal' in df.columns and not df['ActualBal'].isna().all():
        cols.insert(5, 'ActualBal')
        cols.insert(6, 'Variance')
        
    # Format dates and currencies safely using our custom robust formatter
    for c in cols[2:]:
        if c in df_view.columns:
            df_view[c] = df_view[c].apply(format_money)

    table = dash_table.DataTable(
        data=df_view.to_dict('records'),
        columns=[{'name': i, 'id': i} for i in cols],
        style_header={
            'backgroundColor': '#0f172a', 'color': '#f8fafc', 'fontWeight': 'bold', 
            'borderBottom': '1px solid #475569', 'fontFamily': 'monospace'
        },
        style_cell={
            'backgroundColor': '#000000', 'color': '#e2e8f0', 'border': '1px solid #1e293b', 
            'textAlign': 'left', 'fontFamily': 'monospace', 'fontSize': '13px'
        },
        style_data_conditional=[
            {'if': {'column_id': 'TakeHome'}, 'color': '#facc15', 'fontWeight': 'bold'},
            {'if': {'column_id': 'TaxLiability'}, 'color': '#ff5555'},
            
            # --- ⚡ BULLETPROOF CONDITIONAL FORMATTING ---
            # Default to green for TargetGain, then override with red if the string starts with a negative sign
            {'if': {'column_id': 'TargetGain'}, 'color': '#00ff41'},
            {'if': {'column_id': 'TargetGain', 'filter_query': '{TargetGain} scontains "-"'}, 'color': '#ff5555', 'fontWeight': 'bold'},
            
            {'if': {'column_id': 'Variance'}, 'color': '#00ff41'},
            {'if': {'column_id': 'Variance', 'filter_query': '{Variance} scontains "-"'}, 'color': '#ff5555'},
            
            {'if': {'column_id': 'ActualBal'}, 'fontWeight': 'bold', 'backgroundColor': '#0f172a'}
        ],
        page_size=15,
        style_table={'overflowX': 'auto'}
    )

    return kpi_html, fig, table