import dash
from dash import dcc, html, Input, Output, State, register_page, callback
import dash_bootstrap_components as dbc
import pandas as pd
from datetime import date
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

register_page(__name__, path='/forecaster', name='Forecaster')

# --- LOGIC ---
def get_trading_days(start_date, end_date):
    us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return pd.date_range(start=start_date, end=end_date, freq=us_bd)

def calculate_trajectory(start_date, end_date, start_bal, roi_goal_pct, tax_rate, stop_period, max_dd_pct):
    dates = get_trading_days(start_date, end_date)
    history = []
    balance = start_bal
    risk_bucket_counter = 0
    total_tax_paid = 0
    
    for d in dates:
        risk_bucket_counter += 1
        is_loss_day = (risk_bucket_counter >= stop_period)
        
        if is_loss_day:
            risk_bucket_counter = 0
            gross_gain = balance * -(max_dd_pct / 100.0)
            tax_deduction = 0.0 
            net_gain = gross_gain
            risk_label = "🛑 STOP HIT"
        else:
            gross_gain = balance * (roi_goal_pct / 100.0)
            tax_deduction = gross_gain * tax_rate
            total_tax_paid += tax_deduction
            net_gain = gross_gain - tax_deduction
            risk_label = ""

        new_balance = balance + net_gain
        history.append({"Date": d, "Start Balance": balance, "Net Gain": net_gain, "End Balance": new_balance, "Risk Label": risk_label, "Is Loss": is_loss_day})
        balance = new_balance

    return pd.DataFrame(history), total_tax_paid

# --- LAYOUT ---
layout = dbc.Container([
    dbc.Row([dbc.Col(html.H2("Trajectory Forecaster (Tool 2)", className="text-center text-info mb-4"), width=12)]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("1. Goal Parameters"),
                dbc.CardBody([
                    html.Label("Projection Period"),
                    dcc.DatePickerRange(id='fc-date-range', start_date=date(2025, 11, 1), end_date=date(2025, 12, 31), className="mb-3 w-100"),
                    dbc.Row([
                        dbc.Col([html.Label("Start Capital ($)"), dcc.Input(id='fc-start-bal', type='number', value=600, className="form-control")], width=6),
                        dbc.Col([html.Label("Daily ROI Goal (%)"), dcc.Input(id='fc-roi-goal', type='number', value=88, className="form-control")], width=6),
                    ], className="mb-2"),
                    dbc.Row([
                        dbc.Col([html.Label("Tax Rate (1256)"), dcc.Input(id='fc-tax-rate', type='number', value=0.268, className="form-control")], width=6),
                        dbc.Col([html.Label("Sim. Stop Loss %"), dcc.Input(id='fc-max-dd', type='number', value=30, className="form-control")], width=6),
                    ]),
                    html.Label("Stop Loss Frequency (Days)"),
                    dcc.Slider(id='fc-stop-period', min=2, max=20, step=1, value=4, marks={2:'2d', 4:'4d', 20:'20d'}, className="mb-3"),
                ])
            ], className="mb-3 shadow"),
        ], width=12, lg=5),

        dbc.Col([
            dbc.Card([
                dbc.CardHeader("2. Projection Summary"),
                dbc.CardBody([
                    dbc.Button("🔮 Stress Test Future", id='fc-run-btn', color="info", size="lg", className="w-100 mb-4"),
                    dbc.Row([
                        dbc.Col([html.H6("Accumulated Tax"), html.H4(id='fc-tax-paid', children="$0.00", className="text-warning")], width=6, className="text-center"),
                        dbc.Col([html.H6("Final Net Balance"), html.H3(id='fc-final-net', children="$0.00", className="text-success")], width=6, className="text-center"),
                    ]),
                ])
            ], className="mb-3 shadow"),
            
             dbc.Card([
                dbc.CardHeader("3. Daily Ledger"),
                dbc.CardBody([html.Div(id='fc-traj-table', style={'height': '300px', 'overflowY': 'scroll'})])
            ], className="mb-5 shadow"),
        ], width=12, lg=7)
    ])
], fluid=True)

# --- CALLBACKS ---
@callback(
    [Output('fc-traj-table', 'children'), Output('fc-tax-paid', 'children'), Output('fc-final-net', 'children')],
    [Input('fc-run-btn', 'n_clicks')],
    [State('fc-date-range', 'start_date'), State('fc-date-range', 'end_date'),
     State('fc-start-bal', 'value'), State('fc-roi-goal', 'value'),
     State('fc-tax-rate', 'value'), State('fc-stop-period', 'value'), State('fc-max-dd', 'value')]
)
def update_forecast(n, start, end, bal, roi, tax, stop, max_dd):
    if not n: return html.Div("Ready...", className="text-muted text-center p-3"), "$0.00", "$0.00"

    df, total_tax = calculate_trajectory(start, end, float(bal), float(roi), float(tax), int(stop), float(max_dd))
    
    table_rows = []
    for _, row in df.iterrows():
        pnl_style = {'color': '#ff5555', 'fontWeight': 'bold'} if row['Is Loss'] else {'color': '#00ff41'}
        bg_style = {'backgroundColor': 'rgba(255, 0, 0, 0.2)'} if row['Is Loss'] else {}
        
        table_rows.append(html.Tr([
            html.Td(row['Date'].strftime("%Y-%m-%d")),
            html.Td(f"${row['Start Balance']:,.2f}"),
            html.Td(f"{'+' if row['Net Gain'] > 0 else ''}${row['Net Gain']:,.2f}", style=pnl_style),
            html.Td(f"${row['End Balance']:,.2f}", className="fw-bold"),
            html.Td(row['Risk Label'])
        ], style=bg_style))

    table = dbc.Table([html.Thead(html.Tr([html.Th("Date"), html.Th("Start"), html.Th("Net P&L"), html.Th("End Bal"), html.Th("Status")])), html.Tbody(table_rows)], bordered=True, color="dark", hover=True, size="sm")
    
    return table, f"${total_tax:,.2f}", f"${df.iloc[-1]['End Balance']:,.2f}"