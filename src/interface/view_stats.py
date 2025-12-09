import dash
from dash import dcc, html, callback, Input, Output, dash_table, no_update
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import duckdb
import calendar
from datetime import date, datetime
from src.utils import config
from src.utils.date_profiles import DATE_PROFILES 

# --- THEME CONSTANTS ---
THEME = {
    'BG_CARD': '#283878',
    'BORDER': '2px solid #b5b8b9',
    'TEXT_MAIN': '#ffffff',
    'TEXT_GOLD': '#fde722',
    'TEXT_ACCENT': '#00d2ff',
    'SUCCESS': '#00ff41',
    'DANGER': '#ff5555',
    'FONT': 'VT323, monospace'
}
STYLE_CARD = {'backgroundColor': THEME['BG_CARD'], 'border': THEME['BORDER'], 'borderRadius': '6px', 'boxShadow': '0 0 15px rgba(0,0,0,0.5)', 'marginBottom': '20px'}
STYLE_HEADER = {'backgroundColor': 'rgba(0,0,0,0.3)', 'borderBottom': '1px solid #fff', 'color': THEME['TEXT_GOLD'], 'fontWeight': 'bold', 'fontFamily': THEME['FONT'], 'fontSize': '1.2rem', 'letterSpacing': '1px'}

# ... [DATA ENGINE FUNCTIONS - Preserved] ...
def fetch_dropdown_options():
    options = [{'label': '🔴 LIVE COMBAT LOG (Raw Ledger)', 'value': 'LIVE_LEDGER'}]
    options.append({'label': '--- PROFILES ---', 'value': 'SEP_1', 'disabled': True})
    for k in DATE_PROFILES.keys(): options.append({'label': k, 'value': k})
    if config.DB_FILE.exists():
        try:
            con = duckdb.connect(str(config.DB_FILE), read_only=True)
            tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
            if config.TBL_SIM_LOG in tables:
                months = con.execute(f"SELECT DISTINCT strftime(CAST(entry_time AS TIMESTAMP), '%Y-%m') FROM {config.TBL_SIM_LOG} ORDER BY 1 DESC").fetchall()
                if months:
                    options.append({'label': '--- MONTHLY ARCHIVES ---', 'value': 'SEP_2', 'disabled': True})
                    for m in months: options.append({'label': f'📅 Archive: {m[0]}', 'value': m[0]})
            con.close()
        except: pass
    return options

def fetch_data(query_type, start=None, end=None):
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if config.TBL_SIM_LOG not in tables: con.close(); return pd.DataFrame()
        if query_type == 'LEDGER': q = f"SELECT * FROM {config.TBL_SIM_LOG} ORDER BY entry_time DESC LIMIT 2000"
        else: q = f"SELECT * FROM {config.TBL_SIM_LOG} WHERE entry_time >= '{start}' AND entry_time <= '{end}' ORDER BY entry_time ASC"
        df = con.execute(q).df()
        con.close()
        return df
    except: return pd.DataFrame()

def style_chart(fig):
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=40, r=20, t=30, b=40), font=dict(family="monospace", color="#fff"))
    return fig

# --- VIEW GENERATORS ---
def generate_ledger_view(df):
    if df.empty: return html.Div("NO DATA ACQUIRED", className="text-center text-muted p-5 display-6", style={'fontFamily': 'monospace'})
    return dbc.Card([
        dbc.CardHeader("RAW TRANSACTION LEDGER", style={'backgroundColor': '#d63031', 'color': '#fff', 'fontWeight': 'bold', 'fontFamily': 'monospace'}),
        dbc.CardBody(
            dash_table.DataTable(
                data=df.to_dict('records'),
                columns=[{"name": i, "id": i} for i in ['entry_time','ticker','net_pnl','return_pct','reason']],
                style_header={'backgroundColor': '#000', 'color': THEME['TEXT_GOLD'], 'fontWeight': 'bold', 'border': '1px solid #333'},
                style_cell={'backgroundColor': '#111', 'color': '#fff', 'border': '1px solid #333', 'fontFamily': 'monospace'},
                style_data_conditional=[
                    {'if': {'filter_query': '{net_pnl} > 0', 'column_id': 'net_pnl'}, 'color': THEME['SUCCESS'], 'fontWeight': 'bold'},
                    {'if': {'filter_query': '{net_pnl} < 0', 'column_id': 'net_pnl'}, 'color': THEME['DANGER'], 'fontWeight': 'bold'},
                ],
                page_size=20, sort_action="native"
            )
        )
    ], style=STYLE_CARD)

def generate_dashboard_view(df):
    if df.empty: return html.Div("NO DATA FOUND", className="text-center text-muted p-5 display-6", style={'fontFamily': 'monospace'})
    
    # Metrics
    net_pnl = df['net_pnl'].sum()
    wins = df[df['net_pnl'] > 0]; losses = df[df['net_pnl'] <= 0]
    win_rate = (len(wins)/len(df)*100) if len(df)>0 else 0
    pf = (wins['net_pnl'].sum()/abs(losses['net_pnl'].sum())) if not losses.empty else 0
    df['cum_pnl'] = df['net_pnl'].cumsum(); max_dd = (df['cum_pnl'] - df['cum_pnl'].cummax()).min()
    
    metrics = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("NET P&L", style={'color': THEME['TEXT_GOLD']}), html.H3(f"${net_pnl:,.0f}", style={'color': THEME['SUCCESS'] if net_pnl>0 else THEME['DANGER']})])], style=STYLE_CARD), width=3),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("WIN RATE", style={'color': THEME['TEXT_GOLD']}), html.H3(f"{win_rate:.1f}%", style={'color': THEME['TEXT_ACCENT']})])], style=STYLE_CARD), width=3),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("PROFIT FACTOR", style={'color': THEME['TEXT_GOLD']}), html.H3(f"{pf:.2f}", style={'color': '#fff'})])], style=STYLE_CARD), width=3),
        dbc.Col(dbc.Card([dbc.CardBody([html.H6("MAX DRAWDOWN", style={'color': THEME['TEXT_GOLD']}), html.H3(f"${max_dd:,.0f}", style={'color': THEME['DANGER']})])], style=STYLE_CARD), width=3),
    ], className="mb-3")

    # Standard Charts
    fig_eq = px.line(df, x='entry_time', y='cum_pnl', title="EQUITY CURVE"); fig_eq.update_traces(line_color=THEME['SUCCESS'], fill='tozeroy'); fig_eq = style_chart(fig_eq)
    fig_pie = go.Figure(data=[go.Pie(labels=['Win','Loss'], values=[len(wins), len(losses)], hole=.5, marker=dict(colors=[THEME['SUCCESS'], THEME['DANGER']]))]); fig_pie.update_layout(title="WIN RATIO"); fig_pie = style_chart(fig_pie)
    
    row_charts = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody(dcc.Graph(figure=fig_eq, style={'height':'300px'}))], style=STYLE_CARD), width=8),
        dbc.Col(dbc.Card([dbc.CardBody(dcc.Graph(figure=fig_pie, style={'height':'300px'}))], style=STYLE_CARD), width=4),
    ])

    # Forensic Charts
    df['hour'] = df['entry_time'].dt.hour
    hourly = df.groupby('hour').agg({'net_pnl':'sum','ticker':'count'}).rename(columns={'ticker':'count'})
    fig_hourly = go.Figure(); fig_hourly.add_trace(go.Bar(x=hourly.index, y=hourly['count'], name="Vol", marker_color='rgba(52,152,219,0.4)', yaxis='y2')); fig_hourly.add_trace(go.Scatter(x=hourly.index, y=hourly['net_pnl'], name="PnL", line=dict(color='#f1c40f'))); fig_hourly.update_layout(title="HOURLY PERFORMANCE", yaxis2=dict(overlaying='y', side='right', showgrid=False)); fig_hourly = style_chart(fig_hourly)

    fig_weekly = px.bar(df.groupby(df['entry_time'].dt.day_name())['net_pnl'].sum().reindex(['Monday','Tuesday','Wednesday','Thursday','Friday']).reset_index(), x='entry_time', y='net_pnl', title="WEEKDAY PERFORMANCE"); fig_weekly.update_traces(marker_color=THEME['TEXT_ACCENT']); fig_weekly = style_chart(fig_weekly)
    
    row_forensics = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody(dcc.Graph(figure=fig_hourly, style={'height':'300px'}))], style=STYLE_CARD), width=6),
        dbc.Col(dbc.Card([dbc.CardBody(dcc.Graph(figure=fig_weekly, style={'height':'300px'}))], style=STYLE_CARD), width=6)
    ])

    # Physics
    fig_dist = px.histogram(df, x="net_pnl", nbins=30, title="P&L DISTRIBUTION"); fig_dist.update_traces(marker_color=THEME['TEXT_ACCENT']); fig_dist = style_chart(fig_dist)
    try:
        if 'duration_mins' in df.columns: fig_dur = px.histogram(df, x="duration_mins", nbins=20, title="TRADE DURATION"); fig_dur.update_traces(marker_color='#9b59b6'); fig_dur = style_chart(fig_dur)
        else: fig_dur = go.Figure()
    except: fig_dur = go.Figure()

    row_physics = dbc.Row([
        dbc.Col(dbc.Card([dbc.CardBody(dcc.Graph(figure=fig_dist, style={'height':'300px'}))], style=STYLE_CARD), width=6),
        dbc.Col(dbc.Card([dbc.CardBody(dcc.Graph(figure=fig_dur, style={'height':'300px'}))], style=STYLE_CARD), width=6)
    ])

    # Heatmap
    try:
        df['year'] = df['entry_time'].dt.year; df['month'] = df['entry_time'].dt.month
        piv = df.groupby(['year','month'])['net_pnl'].sum().reset_index().pivot(index='year', columns='month', values='net_pnl').reindex(columns=range(1,13)).fillna(0)
        piv.columns = [calendar.month_abbr[i] for i in piv.columns]; piv.reset_index(inplace=True)
        hm = dash_table.DataTable(data=piv.to_dict('records'), columns=[{"name": str(i), "id": str(i)} for i in piv.columns], 
                                  style_header={'backgroundColor': '#000', 'color': THEME['TEXT_GOLD'], 'fontWeight': 'bold'}, 
                                  style_cell={'backgroundColor': '#111', 'color': '#fff', 'border': '1px solid #333'})
    except: hm = html.Div("No Heatmap Data")

    row_heatmap = dbc.Row([dbc.Col(dbc.Card([dbc.CardHeader("MONTHLY HEATMAP", style=STYLE_HEADER), dbc.CardBody(hm)], style=STYLE_CARD), width=12)])

    return html.Div([
        metrics, row_charts, 
        html.Hr(style={'borderColor': '#fff', 'opacity': '0.3'}), 
        html.H4("TEMPORAL FORENSICS", style={'color': THEME['TEXT_ACCENT'], 'fontFamily': THEME['FONT']}), row_forensics,
        html.H4("PROTOCOL PHYSICS", style={'color': THEME['TEXT_GOLD'], 'fontFamily': THEME['FONT']}), row_physics,
        html.Br(), row_heatmap
    ])

# ==============================================================================
# 5. CONTROLLER
# ==============================================================================
def render():
    return dbc.Container([
        dbc.Row([dbc.Col([html.H2("STATISTICAL LAB", className="display-4", style={'color': THEME['TEXT_MAIN'], 'textShadow': f"0 0 10px {THEME['TEXT_ACCENT']}", 'fontFamily': THEME['FONT']}), html.P("MICRO-STRUCTURE FORENSICS", style={'color': THEME['TEXT_GOLD'], 'letterSpacing': '2px'})], width=12)], className="mb-4"),
        dbc.Card([dbc.CardBody([dbc.Row([
            dbc.Col([html.Label("VIEW MODE", style={'color': THEME['TEXT_ACCENT'], 'fontWeight': 'bold'}), dcc.Dropdown(id='stats-view-selector', options=fetch_dropdown_options(), value='Year to Date (YTD)', clearable=False, style={'backgroundColor': '#fff', 'color': '#000'})], width=4),
            dbc.Col([html.Div(id='stats-picker-container', children=[html.Label("CUSTOM RANGE", style={'color': THEME['TEXT_ACCENT'], 'fontWeight': 'bold'}), dcc.DatePickerRange(id='stats-date-picker', start_date=date(2024,1,1), end_date=date.today(), style={'backgroundColor': THEME['BG_CARD'], 'border': '1px solid #555'})])], width=4),
            dbc.Col([dbc.Button("🔄 RUN ANALYSIS", id='stats-refresh-btn', color="primary", className="mt-4 w-100 fw-bold", style={'border': '1px solid #fff'})], width=4)
        ])], style=STYLE_CARD)], className="mb-4"),
        dcc.Loading(id="loading-stats", type="cube", color=THEME['SUCCESS'], children=html.Div(id='stats-content-area')),
        html.Div(id='stats-ledger-area')
    ], fluid=True)

@callback([Output('stats-date-picker', 'start_date'), Output('stats-date-picker', 'end_date'), Output('stats-picker-container', 'style')], Input('stats-view-selector', 'value'))
def update_inputs(selection):
    if selection == 'LIVE_LEDGER': return no_update, no_update, {'display': 'none'}
    style = {'display': 'block'}
    profile = DATE_PROFILES.get(selection)
    if profile: return profile.start_date, profile.end_date, style
    try:
        dt = datetime.strptime(selection, '%Y-%m')
        return date(dt.year, dt.month, 1), date(dt.year, dt.month, calendar.monthrange(dt.year, dt.month)[1]), style
    except: return no_update, no_update, style

@callback([Output('stats-content-area', 'children'), Output('stats-ledger-area', 'children')], [Input('stats-refresh-btn', 'n_clicks'), Input('stats-view-selector', 'value'), Input('stats-date-picker', 'start_date'), Input('stats-date-picker', 'end_date')])
def main_controller(n, view_mode, start, end):
    if view_mode == 'LIVE_LEDGER': return generate_ledger_view(fetch_data('LEDGER')), ""
    return generate_dashboard_view(fetch_data('STATS', start, end)), ""