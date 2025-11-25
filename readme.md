# 🚀 Quant OS v2.0 (Trade Master Architecture)

**"UTC in the Vault, Local on the Glass."**

A professional-grade quantitative trading pipeline designed for **VIX/SPX** signals and **XSP** Option execution. This repository has evolved into a unified **Single-Page Application (SPA)** known as **Quant OS**, capable of running on Desktop (PC) and Mobile (Android/Termux).

---

## 🏗️ Architecture: The "Master Launcher"

We have migrated from independent scripts to a unified **dashboard ecosystem**.

* **Entry Point:** `app.py` (The Shell)
* **Engine Room:** `10_backtest.py` + Batch Scripts (The Brain)
* **Interface:** `pages/` (The Face)

### 📂 Directory Structure
```text
QUANT-TRADING-PIPELINE/
│
├── app.py                   <-- 🚀 MASTER LAUNCHER (Run this only)
├── 10_backtest.py           <-- 🧠 Math Engine (Subprocess)
├── 00_daily_update.py       <-- ⚙️ Batch Data Ingestion
├── 00_setup_database.py     <-- ⚙️ DB Initialization
│
├── pages/                   <-- 📱 THE TOOLS (GUI)
│   ├── home.py              <-- System Status
│   ├── 11_backtest.py       <-- Tool 1: Forensic Validator
│   ├── 12_forecast.py       <-- Tool 2: Wealth Projector
│   ├── 08_dashboard.py      <-- Tool 3: Trade Analysis
│   ├── 09_simulator.py      <-- Tool 4: Flight Simulator
│   ├── 14_live_dashboard.py <-- Tool 5: Live Ops Center
│   └── 13_market_state.py   <-- Tool 6: Market Periscope
│
├── market_data/             <-- 🏦 The Vault (DuckDB)
└── reports/                 <-- 📄 Artifacts (CSVs)
🛠️ The Six-Tool EcosystemIDTool NameThemeFunction1Backtester🔵 BlueValidation. Tests strategy against history with tax-aware compounding.2Forecaster🟢 GreenPlanning. Projects future wealth using "Risk Buckets" and ROI goals.3Analysis💎 CyanForensics. Deep-dive visualization of past trades (MACD/RSI/Price).4Simulator🟠 OrangeTraining. "Fog of War" replay mode to practice execution.5Live Ops🔴 RedExecution. Real-time 5-minute interval monitoring of SPX/VIX.6Periscope🔭 TealAwareness. High-level market regime scanner & global news wire.🚀 Quick Start (Desktop)Install Dependencies:Bashpip install -r requirements.txt
Initialize Database:Bashpython 00_setup_database.py
Ingest Data:Bashpython 00_daily_update.py
Launch Quant OS:Bashpython app.py
Access: Open http://localhost:8080 in your browser.📱 Mobile Deployment (Google Pixel / Android)Quant OS supports two mobile modes:Mode A: Client (Recommended)Run the engine on your PC, view on your phone.Run python app.py on your PC.Find your PC's LAN IP (e.g., 192.168.1.50).On Mobile Chrome, go to http://192.168.1.50:8080.Tap "Add to Home Screen" to install as a PWA.Mode B: Standalone (Termux)Run the engine entirely on the phone.Install Termux (F-Droid version).Run the auto-setup script:Bashpkg install git -y
git clone [https://github.com/jared-aldape/quant-trading-pipeline.git](https://github.com/jared-aldape/quant-trading-pipeline.git)
cd quant-trading-pipeline
chmod +x 99_mobile_setup.sh
./99_mobile_setup.sh