🚀 Quant OS v2.2 (Anti-Rate-Limit Edition)"UTC in the Vault, Local on the Glass. Real Data in the Engine."A professional-grade quantitative trading pipeline designed for VIX/SPX signals and XSP Option execution. This repository operates as a hybrid Calculation Engine (Python/DuckDB) and Single-Page Application (Dash/Plotly).🏛️ The Four Laws (Strict Enforcement)🕰️ The Timezone Law: All database storage is UTC. All GUI display is US/Pacific.🛡️ The Integrity Law: market_data/quant_strategy.duckdb is the Golden Source. No CSV patching.👁️ The Observability Law: No silent failures. All actions are logged to src/utils/logger.py.🚦 The Rate-Limit Law: All external API calls must respect Free Tier limits via Caching & Throttling.🏗️ Architecture v2.2We enforce a strict separation of concerns between Data Engineering (Pipeline) and User Interface (Tools).📂 Directory Structurequant-trading-pipeline/
│
├── app.py                      <-- 🚀 MASTER LAUNCHER (Run this!)
│
├── src/
│   ├── pipeline/               <-- ⚙️ THE ENGINE ROOM (ETL)
│   │   ├── 00_daily_update.py  <-- Batch Orchestrator (Ingest -> Scan -> Fetch)
│   │   ├── 00_setup_database.py <-- Schema & Reset Tool
│   │   ├── ingest_indices.py   <-- Yahoo Finance Index Data (SPX/VIX)
│   │   ├── scan_signals.py     <-- VIX RSI Signal Generator (Intraday)
│   │   ├── fetch_options.py    <-- Polygon Option Data (Rate-Limit Safe)
│   │   └── calc_greeks.py      <-- [Optional] Black-Scholes Engine
│   │
│   ├── tools/                  <-- 🖥️ THE CONTROL PANEL (GUI)
│   │   ├── 10_backtest.py      <-- Simulation Engine (Real Data)
│   │   ├── 11_backtest.py      <-- Backtester UI
│   │   ├── 12_forecast.py      <-- Capital Growth Projector
│   │   ├── 08_dashboard.py     <-- Analysis Dashboard (RTH Clipped)
│   │   ├── 09_simulator.py     <-- "Fog of War" Replay Tool
│   │   └── 14_live_dashboard.py <-- Command Center (Home Page)
│   │
│   └── utils/
│       ├── config.py           <-- Global Settings & Session
│       └── logger.py           <-- Centralized Logging
🛠️ The Tool Suite (v2.2)
1. 🏠 Command Center (Home) $$Tool 5$$Function: Real-time market monitoring and news aggregation.Features:Live Chart: 5-minute Intraday SPX (Timezone Corrected).Intel: Dual News Streams (Global Wire + S&P 500 Specific).Safety: Protected by Global Session & Caching to prevent API bans.
2. 🟦 Backtester $$Tool 1$$Function: Validates strategy profitability using Real Option Pricing.Logic:Entry: Triggered by VIX RSI signals.Exit: Managed by 30% Trailing Stop or 40% Profit Target.Selection: Supports "First Signal" (Standard) or "Best Signal" (Optimized) modes.Safety: Includes Bankruptcy Protection and Max Invest clamping.
3. 🟩 Forecaster $$Tool 2$$Function: Projects capital growth based on Backtest metrics.Logic: Simulates "Risk Buckets" (periodic resets) to manage drawdown exposure.
4. 💎 Analysis $$Tool 3$$Function: Deep-dive forensics on past execution.Features:RTH Clipper: Filters data strictly to 9:30 AM - 4:00 PM ET (Market Hours).Visuals: High-contrast Dark Mode charts with Legend/Title spacing fixes.
5. 🟠 Simulator $$Tool 4$$Function: "Fog of War" replay mode to practice execution without hindsight bias.Tech: Solves the "Double Shift" timezone bug to perfectly align UTC Options with EST Market Data.🚀 Quick Start (Desktop)1. Install Dependenciespip install -r requirements.txt
2. Initialize the Vault (First Run Only)This creates the optimized database schema with Primary Keys.python src/ops/00_setup_database.py
3. Ingest Data (The Morning Routine)Runs the ETL chain: Ingest Indices -> Scan Signals -> Fetch Options (Safe Mode).python src/pipeline/00_daily_update.py
Note: The Option Fetcher uses "Smart Deduplication" and a 15s throttle to respect Free Tier limits.4. Launch Command TerminalOpens the Master Launcher. The Command Center loads by default.python app.py

Access: Open http://localhost:8050 in your browser.📱 Mobile Deployment (PWA)Quant OS v2.2 features a Responsive Grid layout optimized for mobile devices.On Desktop: Run python app.py (Host is set to 0.0.0.0).On Mobile: Connect to the same Wi-Fi network.Browse: Go to http://YOUR_PC_IP:8050.Install: Tap "Add to Home Screen" to install as a PWA app.🧩 Architectural NotesGlobal Session: All tools share a single requests.Session (defined in config.py) to maintain a consistent browser identity and avoid 429 errors.Data Hygiene: The pipeline automatically detects schema mismatches (e.g., missing columns or keys) and self-heals by rebuilding the table.Visuals: All dropdowns and inputs are styled for readability in Dark Mode (Black text on White background).