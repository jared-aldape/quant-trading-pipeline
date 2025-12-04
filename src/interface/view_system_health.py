import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output
import time
import requests
import duckdb
import psutil
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
        return False, str(e)

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
    """Checks storage space in the correct Data Directory."""
    # FIXED: Use dynamic path from config instead of hardcoded '/app/data'
    try:
        total, used, free = shutil.disk_usage(str(config.DATA_DIR))
        free_gb = free / (2**30)
        pct = (used / total) * 100
        return f"{free_gb:.1f} GB Free", pct
    except Exception as e:
        return "Path Error", 0

def render():
    # 1. Run Diagnostics
    db_ok, db_msg = get_db_status()
    net_ok, net_msg = get_api_status()
    disk_msg, disk_pct = get_disk_status()
    
    # 2. Styles
    card_style = {"border": "1px solid #333", "backgroundColor": "#000"}
    
    def status_badge(is_ok):
        color = "#00ff41" if is_ok else "#ff3333"
        text = "ONLINE" if is_ok else "OFFLINE"
        return html.Span(text, style={"color": color, "fontWeight": "bold", "float": "right"})

    return html.Div([
        html.H2("🏥 SYSTEM HEALTH MONITOR", className="text-white mb-4"),
        
        dbc.Row([
            # DATABASE CARD
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H4("The Vault (DuckDB)", className="card-title text-info"),
                    html.Hr(),
                    html.P([
                        "Status: ", status_badge(db_ok),
                        html.Br(),
                        f"Latency: {db_msg}",
                        html.Br(),
                        f"Path: {config.DB_FILE}"
                    ], className="text-white")
                ])
            ], style=card_style), width=4),

            # NETWORK CARD
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H4("The Glass (Network)", className="card-title text-info"),
                    html.Hr(),
                    html.P([
                        "Yahoo Feed: ", status_badge(net_ok),
                        html.Br(),
                        f"Latency: {net_msg}",
                    ], className="text-white")
                ])
            ], style=card_style), width=4),

            # STORAGE CARD
            dbc.Col(dbc.Card([
                dbc.CardBody([
                    html.H4("System Storage", className="card-title text-info"),
                    html.Hr(),
                    html.P(disk_msg, className="text-white mb-2"),
                    dbc.Progress(value=disk_pct, color="success" if disk_pct < 80 else "danger", className="mb-2"),
                ])
            ], style=card_style), width=4),
        ]),
        
        html.Hr(className="my-4"),
        html.Div("Diagnostics run at: " + time.strftime("%Y-%m-%d %H:%M:%S UTC"), className="text-muted")
    ])