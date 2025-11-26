🚀 Quant OS v2.1 (Architectural Purity Edition)

**"UTC in the Vault, Local on the Glass."**

A professional-grade quantitative trading pipeline designed for **VIX/SPX** signals and **XSP** Option execution. This repository operates as a hybrid **Calculation Engine (Python/DuckDB)** and **Single-Page Application (Dash/Plotly)**.

---

## 🏛️ The Three Laws (Strict Enforcement)

1.  **🕰️ The Timezone Law:** All database storage is **UTC**. All GUI display is **US/Pacific**. No exceptions.
2.  **🛡️ The Integrity Law:** `market_data/quant_strategy.duckdb` is the Golden Source. No CSV patching. No inference.
3.  **👁️ The Observability Law:** No silent failures. All actions are logged to `src/utils/logger.py`.

---

## 🏗️ Architecture v2.1

We enforce a strict separation of concerns between **Data Engineering (Pipeline)** and **User Interface (Tools)**.

### 📂 Directory Structure
```text
quant-trading-pipeline/
│
├── app.py                      <-- 🚀 MASTER LAUNCHER (Run this!)
│
├── src/
│   ├── pipeline/               <-- ⚙️ THE ENGINE ROOM (ETL)
│   │   ├── 00_daily_update.py  <-- Batch Orchestrator
│   │   ├── 00_setup_database.py
│   │   ├── 01_ingest_indices.py
│   │   ├── 02_scan_signals.py
│   │   ├── 03_fetch_options.py
│   │   └── 04_calc_greeks.py
│   │
│   ├── tools/                  <-- 🖥️ THE USER INTERFACE (GUI)
│   │   ├── 10_backtest.py      <-- Calculation Engine (Backend)
│   │   ├── 11_backtest.py      <-- Tool 1: Historical Validator
│   │   ├── 12_forecast.py      <-- Tool 2: Wealth Projector
│   │   ├── 08_dashboard.py     <-- Tool 3: Analysis Dash
│   │   ├── 09_simulator.py     <-- Tool 4: Flight Simulator
│   │   ├── 14_live_dashboard.py<-- Tool 5: Live Ops Center
│   │   └── 13_market_state.py  <-- Tool 6: Market Periscope
│   │
│   └── utils/                  <-- 🧱 SHARED LOGIC
│       ├── config.py           <-- Paths & Constants
│       └── logger.py           <-- Centralized Logging
│
└── ops/                        <-- 🛠️ MAINTENANCE
    └── diagnostic_audit.py     <-- Forensic Tools
🛠️ The Six-Tool EcosystemIDTool NameColorFunction
1 Backtester🔵 BlueValidation. Tests strategy against history with tax-aware compounding.
2 Forecaster🟢 GreenPlanning. Projects future wealth using "Risk Buckets".
3 Analysis💎 CyanForensics. Deep-dive visualization of past trades (MACD/RSI/Price).
4 Simulator🟠 OrangeTraining. "Fog of War" replay mode to practice execution.
5 Live Ops🔴 RedExecution. Real-time 5-minute interval monitoring of SPX/VIX.
6 Periscope🔭 TealAwareness. High-level market regime scanner & global news wire.🚀 Quick Start (Desktop)
1. Install DependenciesBashpip install -r requirements.txt
2. Initialize the Vault (DuckDB)This wipes the database and creates the schema.Bashpython src/pipeline/00_setup_database.py
3. Ingest Data (The Pipeline)Runs the ETL chain (Ingest -> Scan -> Fetch Options -> Calc Greeks).Bashpython src/pipeline/00_daily_update.py
4. Launch Command TerminalThis opens the Master Launcher to access all tools.
Bashpython app.py
Access: Open http://localhost:8050 in your browser.📱 Mobile Deployment (PWA)Quant OS v2.1 is designed to run on a Desktop Host (0.0.0.0) and be accessed via Mobile Client (Pixel 9).On Desktop: Run python app.py.
On Mobile: Connect to the same Wi-Fi.Browse: Go to http://YOUR_PC_IP:8050.Install: Tap "Add to Home Screen" to install as a PWA app.🧩 Architectural NotesETL Pipeline: The pipeline scripts (01-04) reside in src/pipeline. They resolve paths dynamically to find config.py.
Backtesting: The GUI (11_backtest.py) calls the Engine (10_backtest.py) as a subprocess. Both must exist in src/tools/.Styles: All styling is Python-Native (defined in app.py and tool files). No external CSS files are required.