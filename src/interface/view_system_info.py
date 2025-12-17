import dash
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc
import time
import requests
import duckdb
import shutil
import pandas as pd
from pathlib import Path
import sys
from datetime import datetime, date, timedelta

# ==============================================================================
# 0. CONFIG & SETUP
# ==============================================================================
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

# 2025 Market Calendar (Expandable)
MARKET_EVENTS = [
    {"date": "2025-01-01", "event": "New Year's Day", "status": "CLOSED"},
    {"date": "2025-01-20", "event": "MLK Jr. Day", "status": "CLOSED"},
    {"date": "2025-02-17", "event": "Presidents Day", "status": "CLOSED"},
    {"date": "2025-04-18", "event": "Good Friday", "status": "CLOSED"},
    {"date": "2025-05-26", "event": "Memorial Day", "status": "CLOSED"},
    {"date": "2025-06-19", "event": "Juneteenth", "status": "CLOSED"},
    {"date": "2025-07-03", "event": "Indep. Day (Early)", "status": "13:00 CLOSE"},
    {"date": "2025-07-04", "event": "Independence Day", "status": "CLOSED"},
    {"date": "2025-09-01", "event": "Labor Day", "status": "CLOSED"},
    {"date": "2025-11-27", "event": "Thanksgiving", "status": "CLOSED"},
    {"date": "2025-11-28", "event": "Black Friday", "status": "13:00 CLOSE"},
    {"date": "2025-12-24", "event": "Christmas Eve", "status": "13:00 CLOSE"},
    {"date": "2025-12-25", "event": "Christmas Day", "status": "CLOSED"},
]

# ==============================================================================
# 1. DIAGNOSTIC FUNCTIONS
# ==============================================================================
def get_db_status():
    """Checks connection to the Vault."""
    start = time.time()
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        con.execute("SELECT 1").fetchone()
        con.close()
        latency = (time.time() - start) * 1000
        return True, f"{latency:.1f}ms"
    except Exception as e:
        return False, "ERR"

def get_api_status():
    """Checks latency to Data Source (Yahoo)."""
    start = time.time()
    try:
        requests.get("https://finance.yahoo.com", timeout=5)
        latency = (time.time() - start) * 1000
        return True, f"{latency:.0f}ms"
    except:
        return False, "TIMEOUT"

def get_disk_status():
    """Checks storage space."""
    try:
        target_path = config.DATA_DIR if config.DATA_DIR.exists() else config.PROJECT_ROOT
        total, used, free = shutil.disk_usage(str(target_path))
        free_gb = free / (2**30)
        pct = (used / total) * 100
        return f"{free_gb:.1f} GB Free", pct
    except Exception as e:
        return f"Path Error: {e}", 0

# ==============================================================================
# 2. INTELLIGENCE FUNCTIONS
# ==============================================================================
def get_market_regime():
    """Fetches VIX from DB to determine environment."""
    if not config.DB_FILE.exists(): return "UNKNOWN", "N/A", "secondary"
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        # Check if table exists
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if getattr(config, 'TBL_INDICES', 'indices_1m') not in tables:
            con.close(); return "NO DATA", "0.00", "secondary"
            
        q = f"SELECT close FROM {config.TBL_INDICES} WHERE ticker='VIX' ORDER BY datetime_utc DESC LIMIT 1"
        res = con.execute(q).fetchone()
        con.close()
        
        if res:
            vix = res[0]
            if vix < 12: return "COMPLACENT", f"{vix:.2f}", "success"
            elif vix < 20: return "NOMINAL", f"{vix:.2f}", "info"
            elif vix < 30: return "HIGH FLOW", f"{vix:.2f}", "warning"
            else: return "EXTREME", f"{vix:.2f}", "danger"
    except: pass
    return "OFFLINE", "0.00", "secondary"

def get_recent_ops():
    """Fetches last 5 filled trades."""
    if not config.DB_FILE.exists(): return pd.DataFrame()
    try:
        con = duckdb.connect(str(config.DB_FILE), read_only=True)
        tables = [x[0] for x in con.execute("SHOW TABLES").fetchall()]
        if 'active_rh_log' not in tables:
            con.close(); return pd.DataFrame()
            
        q = """
            SELECT 
                entry_time_utc, 
                root || ' ' || option_type as ticker, 
                action, 
                fill_price 
            FROM active_rh_log 
            WHERE status='FILLED' 
            ORDER BY entry_time_utc DESC 
            LIMIT 5
        """
        df = con.execute(q).df()
        con.close()
        return df
    except:
        return pd.DataFrame()

def get_upcoming_events():
    """Finds next 3 market events."""
    today = date.today()
    upcoming = []
    for evt in MARKET_EVENTS:
        evt_date = datetime.strptime(evt['date'], "%Y-%m-%d").date()
        if evt_date >= today:
            days_until = (evt_date - today).days
            label = "TODAY" if days_until == 0 else f"T-{days_until}d"
            upcoming.append({**evt, "countdown": label})
            if len(upcoming) >= 3: break
    return upcoming

# ==============================================================================
# 3. RENDER
# ==============================================================================
def render():
    # A. Run Diagnostics
    db_ok, db_msg = get_db_status()
    net_ok, net_msg = get_api_status()
    disk_msg, disk_pct = get_disk_status()
    
    # B. Run Intel
    regime_txt, regime_val, regime_color = get_market_regime()
    recent_ops_df = get_recent_ops()
    upcoming_evts = get_upcoming_events()
    
    # C. Read Mission Log
    readme_content = "### 🛑 Mission Log Not Found"
    readme_path = config.PROJECT_ROOT / "readme.md"
    if not readme_path.exists(): readme_path = config.PROJECT_ROOT / "README.md"
    if readme_path.exists():
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_content = f.read()
        except: pass

    # D. Helpers
    def status_badge(is_ok):
        color = "#00ff41" if is_ok else "#ff3333"
        text = "ONLINE" if is_ok else "OFFLINE"
        return html.Span(text, style={"color": color, "fontWeight": "bold", "float": "right", "fontFamily": "'VT323', monospace"})

    # --- LAYOUT ---
    return dbc.Container([
        
        # TITLE HEADER
        dbc.Row([
            dbc.Col([
                html.H2("SYSTEM STATUS COMMAND", className="magitek-h2"),
                html.P("DIAGNOSTICS | INTELLIGENCE | MISSION LOG", className="magitek-note")
            ], width=8),
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div(f"REGIME: {regime_txt}", className=f"text-end text-{regime_color} font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9", "backgroundColor": "#283878", "color": "#f3f5f9"}),

        dbc.Row([
            # --- COL 1: SYSTEM HARDWARE ---
            dbc.Col([
                # LOGO
                html.Div([
                    html.Img(src=dash.get_asset_url("quant_logo.svg"), style={"height": "80px", "opacity": "0.9"}),
                    html.H5("QUANT CORE", className="text-white font-monospace mt-2")
                ], className="text-center mb-4 p-3", style={"borderBottom": "1px solid #444"}),

                html.H5("HARDWARE TELEMETRY", className="text-info font-monospace mb-3 small"),
                
                # VAULT CARD
                dbc.Card([
                    dbc.CardHeader("THE VAULT (DB)", className="card-header py-2"),
                    dbc.CardBody([
                        html.Div([html.Span("Status: ", className="font-monospace"), status_badge(db_ok)]),
                        html.Small(f"Latency: {db_msg}", className="text-muted font-monospace"),
                        html.Br(),
                        html.Small(f"Ref: {config.DB_FILE.name}", className="text-muted font-monospace", style={"fontSize": "10px"})
                    ], className="py-2")
                ], className="mb-3 shadow-sm"),
                
                # GLASS CARD
                dbc.Card([
                    dbc.CardHeader("THE GLASS (FEED)", className="card-header py-2"),
                    dbc.CardBody([
                        html.Div([html.Span("Uplink: ", className="font-monospace"), status_badge(net_ok)]),
                        html.Small(f"Latency: {net_msg}", className="text-muted font-monospace")
                    ], className="py-2")
                ], className="mb-3 shadow-sm"),

                # STORAGE CARD
                dbc.Card([
                    dbc.CardHeader("STORAGE (NODE)", className="card-header py-2"),
                    dbc.CardBody([
                        html.P(disk_msg, className="text-white mb-1 font-monospace small"),
                        dbc.Progress(value=disk_pct, color="success" if disk_pct < 80 else "danger", className="mb-0", style={"height": "5px"}),
                    ], className="py-2")
                ], className="mb-3 shadow-sm"),
                
                html.Div("Updated: " + time.strftime("%H:%M:%S UTC"), className="text-muted mt-4 font-monospace small text-center")

            ], width=12, lg=3),

            # --- COL 2: TACTICAL INTELLIGENCE ---
            dbc.Col([
                html.H5("TACTICAL BRIEFING", className="text-warning font-monospace mb-3 small"),
                
                # REGIME CARD
                dbc.Card([
                    dbc.CardBody([
                        html.Div("MARKET REGIME", className="small text-muted font-monospace mb-1"),
                        html.H2(regime_txt, className=f"text-{regime_color} font-monospace fw-bold mb-0"),
                        html.Div(f"VIX: {regime_val}", className="text-white font-monospace small")
                    ])
                ], className="mb-3 shadow-sm", style={"borderLeft": f"4px solid var(--bs-{regime_color})"}),

                # UPCOMING EVENTS
                dbc.Card([
                    dbc.CardHeader("HORIZON SCAN (Next 3 Events)", className="card-header py-2"),
                    dbc.CardBody([
                        html.Table([
                            html.Tbody([
                                html.Tr([
                                    html.Td(e['countdown'], className="text-warning fw-bold pe-3"),
                                    html.Td(e['event'], className="text-white"),
                                    html.Td(e['status'], className="text-end text-muted small")
                                ], style={"fontSize": "14px"}) for e in upcoming_evts
                            ])
                        ], className="table table-borderless table-sm mb-0 font-monospace")
                    ], className="p-2")
                ], className="mb-3 shadow-sm"),

                # RECENT OPS (COMBAT LOG)
                dbc.Card([
                    dbc.CardHeader("RECENT OPS (Last 5 Trades)", className="card-header py-2"),
                    dbc.CardBody([
                        dash_table.DataTable(
                            data=recent_ops_df.to_dict('records'),
                            columns=[
                                {'name': 'TICKER', 'id': 'ticker'},
                                {'name': 'ACT', 'id': 'action'},
                                {'name': 'PX', 'id': 'fill_price'}
                            ] if not recent_ops_df.empty else [],
                            style_header={'backgroundColor': '#1e1e1e', 'color': '#888', 'fontWeight': 'bold', 'border': 'none'},
                            style_cell={'backgroundColor': '#1e1e1e', 'color': '#fff', 'border': 'none', 'fontFamily': "'VT323', monospace", 'fontSize': '13px'},
                            style_data_conditional=[
                                {'if': {'filter_query': '{action} = "BUY"'}, 'color': '#00ff41'},
                                {'if': {'filter_query': '{action} = "SELL"'}, 'color': '#ff9900'},
                            ],
                            page_size=5
                        ) if not recent_ops_df.empty else html.Div("No recent missions logged.", className="text-muted small p-2")
                    ], className="p-0")
                ], className="mb-3 shadow-sm")

            ], width=12, lg=4),

            # --- COL 3: MISSION LOG ---
            dbc.Col([
                html.H5("MISSION LOG", className="text-secondary font-monospace mb-3 small"),
                dbc.Card([
                    dbc.CardBody([
                        dcc.Markdown(
                            readme_content, 
                            className="text-white font-monospace",
                            style={"fontSize": "14px", "lineHeight": "1.6"}
                        )
                    ])
                ], className="mb-3 shadow", style={"maxHeight": "80vh", "overflowY": "auto"})
            ], width=12, lg=5)
        ])
    ], fluid=True)