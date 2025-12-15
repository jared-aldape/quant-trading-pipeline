import dash
from dash import dcc, html, callback, Input, Output, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
import duckdb
import pathlib
import sys
import pytz
from datetime import datetime

# ==============================================================================
# 1. PATH & CONFIG
# ==============================================================================
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config
# Import hydration logic
from src.data.hydrate_simulator import hydrate_ledger 

# CONSTANTS
TBL_RH_LEDGER = "active_rh_log"
TZ_VAULT = pytz.UTC
TZ_GLASS = pytz.timezone('US/Pacific') # The Glass is Local

# ==============================================================================
# 2. DATA CONTROLLER
# ==============================================================================
def fetch_ledger_data():
    """
    Fetches the Reality Ledger (active_rh_log) from the Vault.
    Performs Timezone Conversion (UTC -> PST) for display.
    """
    if not config.DB_FILE.exists():
        return pd.DataFrame()

    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        
        # Check if table exists
        tables = con.execute("SHOW TABLES").fetchall()
        table_list = [t[0] for t in tables]
        
        if TBL_RH_LEDGER not in table_list:
            con.close()
            return pd.DataFrame()

        # Query the Atomized Data
        query = f"""
            SELECT 
                entry_time_utc, 
                action, 
                root, 
                strike, 
                option_right, 
                expiry_date, 
                quantity, 
                fill_price, 
                fees,
                net_pnl, 
                status, 
                opra_code
            FROM {TBL_RH_LEDGER}
            ORDER BY entry_time_utc DESC
        """
        df = con.execute(query).df()
        con.close()

        if df.empty:
            return df

        # --- TIMEZONE LAW (Vault -> Glass) ---
        # 1. Ensure UTC awareness
        df['entry_time_utc'] = pd.to_datetime(df['entry_time_utc']).dt.tz_localize('UTC')
        
        # 2. Convert to Local (PST) and Format
        df['time_local'] = df['entry_time_utc'].dt.tz_convert(TZ_GLASS).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        return df

    except Exception as e:
        print(f"❌ Ledger Fetch Error: {e}")
        return pd.DataFrame()

# ==============================================================================
# 3. INTERFACE LAYOUT (WRAPPED)
# ==============================================================================
def render():
    return dbc.Container([
        
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("GIL LEDGER COMMAND", className="magitek-h2"),
                html.P("REALITY LEDGER | ROBINHOOD FEED | ATOMIZED LOG", className="magitek-note")
            ], width=7),
            
            dbc.Col([
                dbc.Row([
                    dbc.Col([
                        html.Div("SOURCE: LIVE API", className="text-end text-success font-monospace fw-bold"),
                        html.Div(id="hydration-status", className="text-end text-warning font-monospace small")
                    ], width=8),
                    dbc.Col([
                        dbc.Button("🌊 HYDRATE", id="btn-hydrate", color="info", size="sm", className="w-100 font-monospace")
                    ], width=4, className="align-self-center")
                ])
            ], width=5, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        # KPI ROW (The Scoreboard)
        dbc.Row([
            dbc.Col(dbc.Card([
                dbc.CardHeader("NET LIQUID PnL", className="card-header"),
                dbc.CardBody(html.H3("$0.00", id="kpi-pnl", className="text-success font-monospace"))
            ], className="shadow"), width=3),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("REGULATORY FEES", className="card-header"),
                dbc.CardBody(html.H3("$0.00", id="kpi-fees", className="text-warning font-monospace"))
            ], className="shadow"), width=3),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("FILLED ORDERS", className="card-header"),
                dbc.CardBody(html.H3("0", id="kpi-filled", className="text-info font-monospace"))
            ], className="shadow"), width=3),
            
            dbc.Col(dbc.Card([
                dbc.CardHeader("CANCELLATIONS", className="card-header"),
                dbc.CardBody(html.H3("0", id="kpi-cancel", className="text-secondary font-monospace"))
            ], className="shadow"), width=3),
        ], className="mb-4"),

        # THE GRID (Atomized Data Table)
        dbc.Row([
            dbc.Col(dash_table.DataTable(
                id='ledger-table',
                columns=[
                    {'name': 'Time (PST)', 'id': 'time_local'},
                    {'name': 'Side', 'id': 'action'},
                    {'name': 'Symbol', 'id': 'root'},
                    {'name': 'Strike', 'id': 'strike'},
                    {'name': 'Right', 'id': 'option_right'},
                    {'name': 'Expiry', 'id': 'expiry_date'},
                    {'name': 'Qty', 'id': 'quantity'},
                    {'name': 'Fill Price', 'id': 'fill_price'},
                    {'name': 'Fees', 'id': 'fees'},
                    {'name': 'Net PnL', 'id': 'net_pnl'},
                    {'name': 'Status', 'id': 'status'},
                    {'name': 'OPRA Code', 'id': 'opra_code'}, 
                ],
                style_table={'overflowX': 'auto'},
                # FIXED: Magitek Blue Background
                style_cell={
                    'backgroundColor': '#101830', # Dark Blue
                    'color': '#f3f5f9',           # Off White
                    'border': '1px solid #444',
                    'textAlign': 'left',
                    'fontFamily': "'VT323', monospace",
                    'fontSize': '1.1rem'
                },
                style_header={
                    'backgroundColor': '#283878', # Magitek Blue
                    'fontWeight': 'bold',
                    'color': '#fde722',           # Gold
                    'borderBottom': '2px solid #b5b8b9'
                },
                style_data_conditional=[
                    # Color Net PnL
                    {
                        'if': {'filter_query': '{net_pnl} > 0', 'column_id': 'net_pnl'},
                        'color': '#00ff41', 'fontWeight': 'bold'
                    },
                    {
                        'if': {'filter_query': '{net_pnl} < 0', 'column_id': 'net_pnl'},
                        'color': '#ff3333', 'fontWeight': 'bold'
                    },
                    # Color Action
                    {
                        'if': {'filter_query': '{action} = "BUY"', 'column_id': 'action'},
                        'color': '#33ccff'
                    },
                    {
                        'if': {'filter_query': '{action} = "SELL"', 'column_id': 'action'},
                        'color': '#ff9900'
                    },
                    # Dim Cancelled
                    {
                        'if': {'filter_query': '{status} contains "CANCEL"', 'column_id': 'status'},
                        'color': '#666', 'textDecoration': 'line-through'
                    }
                ],
                page_size=20
            ), width=12)
        ])

    ], fluid=True)

# ==============================================================================
# 4. CALLBACKS
# ==============================================================================
@callback(
    [Output('ledger-table', 'data'),
     Output('kpi-pnl', 'children'),
     Output('kpi-pnl', 'style'),
     Output('kpi-fees', 'children'),
     Output('kpi-filled', 'children'),
     Output('kpi-cancel', 'children'),
     Output('hydration-status', 'children')],
    [Input('btn-hydrate', 'n_clicks')]
)
def update_ledger_view(n_clicks):
    # 1. Handle Hydration Request
    status_msg = "READY"
    if n_clicks:
        try:
            hydrate_ledger()
            status_msg = "✅ HYDRATED"
        except Exception as e:
            status_msg = f"❌ ERROR: {e}"

    # 2. Fetch Data
    df = fetch_ledger_data()
    
    if df.empty:
        return [], "$0.00", {'color': 'white'}, "$0.00", "0", "0", status_msg

    # 3. Calculate KPIs
    total_pnl = df['net_pnl'].sum()
    total_fees = df['fees'].sum()
    
    if 'status' in df.columns:
        filled_count = len(df[df['status'].astype(str).str.contains("FILLED", na=False)])
        cancel_count = len(df[df['status'].astype(str).str.contains("CANCEL", na=False)])
    else:
        filled_count = 0
        cancel_count = 0

    # 4. Format Output
    pnl_str = f"${total_pnl:,.2f}"
    pnl_style = {'color': '#00ff41'} if total_pnl >= 0 else {'color': '#ff3333'}
    
    fees_str = f"${total_fees:,.2f}"
    filled_str = f"{filled_count}"
    cancel_str = f"{cancel_count}"

    data = df.to_dict('records')

    return data, pnl_str, pnl_style, fees_str, filled_str, cancel_str, status_msg