import dash
from dash import dcc, html, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import pathlib
import sys
import pytz
import calendar

# PATH SETUP
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.core import engine_forensics as forensics
from src.utils.date_profiles import DATE_PROFILES

TZ_UTC = pytz.UTC
TZ_PST = pytz.timezone('US/Pacific')

# ==============================================================================
# LAYOUT
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("JOB STATS COMMAND", className="magitek-h2"),
                html.P("FORENSICS LAB | PERFORMANCE ANALYTICS | EQUITY CURVE", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: ANALYSIS", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # --- CONTROL STRIP ---
        dbc.Row([
            dbc.Col(dcc.Dropdown(
                id='stats-source-dropdown',
                options=[
                    {'label': 'GIL LEDGER (Robinhood)', 'value': 'rh'},
                    {'label': 'SAVE CRYSTAL', 'value': 'gen'},
                    {'label': 'TRAINING GROUNDS', 'value': 'manual'},
                    {'label': 'RAW SIGNAL HISTORY', 'value': 'sig'}
                ],
                value='rh',
                clearable=False,
                className="mb-3"
            ), width=6),

            dbc.Col(dcc.Dropdown(
                id='stats-date-dropdown',
                options=[{'label': k, 'value': k} for k in DATE_PROFILES.keys()],
                value='Year To Date',
                clearable=False,
                className="mb-3"
            ), width=6)
        ], className="mb-3"),

        # KPIs
        dbc.Row(id='stats-kpi-row', className="mb-4"),

        # CHART ROW 1
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("PRIMARY ANALYSIS", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-1', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow h-100"), width=8),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("SECONDARY ANALYSIS", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-2', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow h-100"), width=4),
        ], className="mb-4"),

        # CHART ROW 2
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("ACTIVITY / DISTRIBUTION", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-3', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow"), width=6),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("TEMPORAL / RISK", className="card-header text-center"), 
                dbc.CardBody(dcc.Graph(id='stats-chart-4', style={'height': '300px'}, config={'displayModeBar': False}))
            ], className="shadow"), width=6),
        ], className="mb-4"),

        # CHART ROW 3 (Extra)
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("SEASONALITY MAP", className="card-header text-center"),
                dbc.CardBody(dcc.Graph(id='stats-chart-5', config={'displayModeBar': False}))
            ], className="shadow"), width=12)
        ], className="mb-4"),

        # LEDGER
        dbc.Row([
            dbc.Col([
                html.H4(id='stats-ledger-title', className="text-info font-monospace mt-2"), 
                html.Div(id='stats-table-container')
            ], width=12)
        ])

    ], fluid=True)

# ==============================================================================
# CALLBACKS
# ==============================================================================
@callback(
    [Output('stats-kpi-row', 'children'),
     Output('stats-chart-1', 'figure'),
     Output('stats-chart-2', 'figure'),
     Output('stats-chart-3', 'figure'),
     Output('stats-chart-4', 'figure'),
     Output('stats-chart-5', 'figure'),
     Output('stats-ledger-title', 'children'),
     Output('stats-table-container', 'children')],
    [Input('stats-source-dropdown', 'value'),
     Input('stats-date-dropdown', 'value')]
)
def update_stats(source, date_profile):
    df = forensics.fetch_scorecard_data(source, date_profile)
    
    empty_fig = go.Figure().update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    if df.empty:
        return [], empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, "", html.Div("No Data", className="text-muted text-center mt-5")

    # PRE-PROCESS (Timezone)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    if df['entry_time'].dt.tz is None: df['entry_time'] = df['entry_time'].dt.tz_localize(TZ_UTC)
    df['entry_time'] = df['entry_time'].dt.tz_convert(TZ_PST)
    
    if 'exit_time' in df.columns:
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        if df['exit_time'].dt.tz is None: df['exit_time'] = df['exit_time'].dt.tz_localize(TZ_UTC)
        df['exit_time'] = df['exit_time'].dt.tz_convert(TZ_PST)
    else:
        df['exit_time'] = df['entry_time']

    df = df.sort_values('entry_time')
    df['trade_seq'] = df.groupby(df['entry_time'].dt.date).cumcount() + 1
    df = df.sort_values('entry_time', ascending=False)

    # ==========================================================================
    # MODE: RAW SIGNALS (SIG)
    # ==========================================================================
    if source == 'sig':
        # KPIs
        calls = len(df[df['ticker'].str.contains('CALL')])
        puts = len(df[df['ticker'].str.contains('PUT')])
        ratio = (calls / puts) if puts > 0 else calls
        kpis = [
            dbc.Col(dbc.Card([html.H6("TOTAL SIGNALS"), html.H3(f"{len(df)}", className="text-info")], body=True, color="dark", inverse=True)),
            dbc.Col(dbc.Card([html.H6("CALLS"), html.H3(f"{calls}", className="text-success")], body=True, color="dark", inverse=True)),
            dbc.Col(dbc.Card([html.H6("PUTS"), html.H3(f"{puts}", className="text-danger")], body=True, color="dark", inverse=True)),
            dbc.Col(dbc.Card([html.H6("C/P RATIO"), html.H3(f"{ratio:.2f}", className="text-warning")], body=True, color="dark", inverse=True)),
        ]
        
        # Charts
        daily = df.groupby(df['entry_time'].dt.date).size()
        fig1 = go.Figure(data=[go.Bar(x=daily.index, y=daily.values, marker_color='#00d2ff')])
        fig1.update_layout(title="Daily Frequency", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        
        fig2 = go.Figure(data=[go.Pie(labels=['CALL','PUT'], values=[calls,puts], hole=.4, marker=dict(colors=['#00ff41', '#ff5555']))])
        fig2.update_layout(title="Directional Bias", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False)

        hourly = df.groupby(df['entry_time'].dt.hour).size()
        fig3 = go.Figure(data=[go.Bar(x=hourly.index, y=hourly.values, marker_color='#f39c12')])
        fig3.update_layout(title="Hourly Activity", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

        df['dow'] = df['entry_time'].dt.day_name()
        dow = df.groupby('dow').size().reindex(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])
        fig4 = go.Figure(data=[go.Bar(x=dow.index, y=dow.values, marker_color='#e74c3c')])
        fig4.update_layout(title="Weekday Activity", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

        # Table
        df['time_str'] = df['entry_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Styles
        header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9'}
        cell_style = {'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'}

        tbl = dash_table.DataTable(
            data=df[['trade_seq', 'time_str', 'ticker']].to_dict('records'),
            columns=[{'name': '#', 'id': 'trade_seq'}, {'name': 'TIME', 'id': 'time_str'}, {'name': 'TICKER', 'id': 'ticker'}],
            style_header=header_style,
            style_cell=cell_style,
            page_size=10
        )
        return kpis, fig1, fig2, fig3, fig4, empty_fig, "SIGNAL LOG", tbl

    # ==========================================================================
    # MODE: TRADES (RH / GEN / MANUAL)
    # ==========================================================================
    else:
        metrics = forensics.calculate_metrics(df)
        kpis = [
            dbc.Col(dbc.Card([html.H6("NET PnL"), html.H3(f"${metrics['net_pnl']:,.2f}", className="text-success" if metrics['net_pnl'] >=0 else "text-danger")], body=True, color="dark", inverse=True)),
            dbc.Col(dbc.Card([html.H6("WIN RATE"), html.H3(f"{metrics['win_rate']:.1f}%", className="text-info")], body=True, color="dark", inverse=True)),
            dbc.Col(dbc.Card([html.H6("PROFIT FACTOR"), html.H3(f"{metrics['pf']:.2f}", className="text-warning")], body=True, color="dark", inverse=True)),
            dbc.Col(dbc.Card([html.H6("TRADES"), html.H3(f"{metrics['total_trades']}", className="text-white")], body=True, color="dark", inverse=True)),
        ]

        # 1. Equity
        fig1 = go.Figure(data=[go.Scatter(x=df['entry_time'], y=df['equity_curve'], mode='lines', fill='tozeroy', line=dict(color='#00bc8c'))])
        fig1.update_layout(title="Equity Curve", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

        # 2. Win/Loss Pie
        wins = len(df[df['pnl']>0])
        losses = len(df[df['pnl']<=0])
        fig2 = go.Figure(data=[go.Pie(labels=['Win','Loss'], values=[wins,losses], hole=.4, marker=dict(colors=['#00ff41', '#ff5555']))])
        fig2.update_layout(title="Win Ratio", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False)

        # 3. PnL Dist
        fig3 = go.Figure(data=[go.Histogram(x=df['pnl'], nbinsx=30, marker_color='#375a7f')])
        fig3.update_layout(title="PnL Distribution", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

        # 4. Theta
        fig4 = go.Figure(data=[go.Scatter(x=df['duration_mins'], y=df['return_pct'], mode='markers', marker=dict(size=8, color=df['return_pct'], colorscale='RdYlGn', cmid=0))])
        fig4.update_layout(title="Theta Risk", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_title="Mins", yaxis_title="ROI%")

        # 5. Monthly Heatmap
        df['year'] = df['entry_time'].dt.year
        df['month'] = df['entry_time'].dt.month
        piv = df.groupby(['year','month'])['pnl'].sum().reset_index().pivot(index='year', columns='month', values='pnl').fillna(0)
        for m in range(1,13): 
            if m not in piv.columns: piv[m] = 0
        piv = piv[sorted(piv.columns)]
        fig5 = go.Figure(data=go.Heatmap(z=piv.values, x=[calendar.month_abbr[i] for i in piv.columns], y=piv.index, colorscale='RdYlGn', zmid=0))
        fig5.update_layout(title="Monthly Seasonality", template="plotly_dark", margin=dict(l=20,r=20,t=40,b=20), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')

        # DUAL-ROW LEDGER
        df_buys = df.copy()
        df_buys['time'] = df_buys['entry_time']
        df_buys['action'] = 'BUY'
        df_buys['price'] = df_buys['entry_price']
        df_buys['pnl'] = 0
        df_buys['return_pct'] = 0
        df_buys['duration_mins'] = 0
        
        df_sells = df.copy()
        df_sells['time'] = df_sells['exit_time']
        df_sells['action'] = 'SELL'
        df_sells['price'] = df_sells['exit_price']
        
        df_view = pd.concat([df_buys, df_sells], ignore_index=True).sort_values('time', ascending=False)
        
        df_view['time_str'] = df_view['time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df_view['pnl_str'] = df_view['pnl'].apply(lambda x: f"${x:,.2f}" if x != 0 else "-")
        df_view['roi_str'] = df_view['return_pct'].apply(lambda x: f"{x:+.1f}%" if x != 0 else "-")
        df_view['dur_str'] = df_view['duration_mins'].apply(lambda x: f"{x:.1f}m" if x > 0 else "-")
        df_view['price_str'] = df_view['price'].apply(lambda x: f"${x:.2f}" if pd.notnull(x) else "$0.00")

        # MAGITEK STYLES
        header_style = {'backgroundColor': '#283878', 'color': '#fde722', 'borderBottom': '2px solid #b5b8b9'}
        cell_style = {'backgroundColor': '#101830', 'color': '#f3f5f9', 'border': '1px solid #444', 'textAlign': 'left', 'fontFamily': "'VT323', monospace", 'fontSize': '1.1rem'}

        dt = dash_table.DataTable(
            data=df_view.to_dict('records'),
            columns=[
                {'name': '#', 'id': 'trade_seq'},
                {'name': 'TIME (PST)', 'id': 'time_str'},
                {'name': 'TICKER', 'id': 'ticker'},
                {'name': 'ACTION', 'id': 'action'},
                {'name': 'PRICE', 'id': 'price_str'},
                {'name': 'DUR', 'id': 'dur_str'},
                {'name': 'ROI', 'id': 'roi_str'},
                {'name': 'PnL', 'id': 'pnl_str'}
            ],
            style_header=header_style,
            style_cell=cell_style,
            style_data_conditional=[
                {'if': {'filter_query': '{pnl_str} contains "$"', 'column_id': 'pnl_str'}, 'color': '#00ff41'},
                {'if': {'filter_query': '{pnl_str} contains "-"', 'column_id': 'pnl_str'}, 'color': '#ff5555'},
                {'if': {'filter_query': '{roi_str} contains "%"', 'column_id': 'roi_str'}, 'color': '#00ff41'},
                {'if': {'filter_query': '{roi_str} contains "-"', 'column_id': 'roi_str'}, 'color': '#ff5555'},
                {'if': {'filter_query': '{action} = "BUY"', 'column_id': 'action'}, 'color': '#33ccff'},
                {'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'}, 'color': '#ff9900'},
            ],
            page_size=15, 
            style_table={'overflowX': 'auto'}
        )
        return kpis, fig1, fig2, fig3, fig4, fig5, "TRADE LEDGER (ENTRIES & EXITS)", dt