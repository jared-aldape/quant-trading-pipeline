import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
import time
import requests
import duckdb
import shutil
from pathlib import Path
import sys

# PATH CONSTITUTION
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))
from src.utils import config

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
    """Checks latency to Yahoo Finance."""
    start = time.time()
    try:
        requests.get("https://finance.yahoo.com", timeout=5)
        latency = (time.time() - start) * 1000
        return True, f"{latency:.0f}ms"
    except:
        return False, "TIMEOUT"

def get_disk_status():
    """Checks storage space in the correct Data Directory (Environment Aware)."""
    try:
        target_path = config.DATA_DIR if config.DATA_DIR.exists() else config.PROJECT_ROOT
        total, used, free = shutil.disk_usage(str(target_path))
        free_gb = free / (2**30)
        pct = (used / total) * 100
        return f"{free_gb:.1f} GB Free", pct
    except Exception as e:
        return f"Path Error: {e}", 0

def render():
    # 1. Run Diagnostics
    db_ok, db_msg = get_db_status()
    net_ok, net_msg = get_api_status()
    disk_msg, disk_pct = get_disk_status()
    
    # 2. Read Project Documentation (Mission Log)
    readme_content = "### 🛑 Mission Log Not Found\nEnsure `readme.md` is in the project root."
    readme_path = config.PROJECT_ROOT / "readme.md"
    if not readme_path.exists():
        readme_path = config.PROJECT_ROOT / "README.md"
        
    if readme_path.exists():
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_content = f.read()
        except Exception as e:
            readme_content = f"### ⚠️ Error Reading Log\n{e}"

    # 3. Status Badge Helper
    def status_badge(is_ok):
        color = "#00ff41" if is_ok else "#ff3333"
        text = "ONLINE" if is_ok else "OFFLINE"
        return html.Span(text, style={"color": color, "fontWeight": "bold", "float": "right", "fontFamily": "'VT323', monospace"})

    # 4. Layout
    return dbc.Container([
        
        # --- TITLE ROW (ATB SCOPE STYLE) ---
        dbc.Row([
            dbc.Col([
                html.H2("SYSTEM STATUS COMMAND", className="magitek-h2"),
                html.P("DIAGNOSTICS | LATENCY CHECK | MISSION LOG", className="magitek-note")
            ], width=8),
            
            dbc.Col([
                html.Div("SYSTEM STATUS: ONLINE", className="text-end text-success font-monospace fw-bold"),
                html.Div("MODE: DIAGNOSTIC", className="text-end text-warning font-monospace")
            ], width=4, className="align-self-center")
        ], className="mb-4 p-3 card flex-row align-items-center", style={"border": "2px solid #b5b8b9"}),

        dbc.Row([
            # --- LEFT COLUMN: METRICS (Tactical Status) ---
            dbc.Col([
                html.H4("HARDWARE TELEMETRY", className="text-info font-monospace mb-3"),
                
                dbc.Card([
                    dbc.CardHeader("THE VAULT (DB)", className="card-header"),
                    dbc.CardBody([
                        html.Div([
                            html.Span("DuckDB Status: ", className="font-monospace"), status_badge(db_ok)
                        ]),
                        html.Small(f"Latency: {db_msg}", className="text-muted font-monospace"),
                        html.Br(),
                        html.Small(f"Path: {config.DB_FILE.name}", className="text-muted font-monospace", style={"fontSize": "10px"})
                    ])
                ], className="mb-3 shadow"),
                
                dbc.Card([
                    dbc.CardHeader("THE GLASS (FEED)", className="card-header"),
                    dbc.CardBody([
                        html.Div([
                            html.Span("Data Feed: ", className="font-monospace"), status_badge(net_ok)
                        ]),
                        html.Small(f"Latency: {net_msg}", className="text-muted font-monospace")
                    ])
                ], className="mb-3 shadow"),

                dbc.Card([
                    dbc.CardHeader("STORAGE (NODE)", className="card-header"),
                    dbc.CardBody([
                        html.P(disk_msg, className="text-white mb-1 font-monospace"),
                        dbc.Progress(value=disk_pct, color="success" if disk_pct < 80 else "danger", className="mb-0", style={"height": "5px"}),
                    ])
                ], className="mb-3 shadow"),
                
                html.Div("Diagnostics: " + time.strftime("%H:%M:%S UTC"), className="text-muted mt-2 font-monospace")

            ], width=12, lg=4),

            # --- RIGHT COLUMN: MISSION LOG (Readme) ---
            dbc.Col([
                html.H4("MISSION LOG", className="text-warning font-monospace mb-3"),
                dbc.Card([
                    dbc.CardBody([
                        dcc.Markdown(
                            readme_content, 
                            className="text-white font-monospace",
                            style={"fontSize": "14px", "lineHeight": "1.6"}
                        )
                    ])
                ], className="mb-3 shadow", style={"maxHeight": "80vh", "overflowY": "auto"})
            ], width=12, lg=8)
        ])
    ], fluid=True)