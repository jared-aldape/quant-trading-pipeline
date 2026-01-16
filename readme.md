# **⚔️ QUANT OS v4.0: INSTITUTIONAL COMMAND SYSTEM**

**"Precision in the Vault. Clarity on the Glass. Alpha in the Machine."**

* **Version:** v4.0 (Institutional GUI / Snapshot Engine)  
* **Status:** **LIVE / BATTLE READY**  
* **Node:** Quant-OS-Node-1 (Local/AWS Hybrid)  
* **Last Update:** January 14, 2026

## **I. THE PRIME DIRECTIVE**

Quant OS is a **Tactical Command System** designed for high-frequency options trading on the **XSP** (Mini-SPX) instrument. It operates on a **Federated Architecture** with four distinct nodes:

1. **GEM 1 (The Gauntlet):** Root Config, Pipeline Orchestration, & Data Ingestion.  
2. **GEM 2 (The Core):** Execution Logic, Fractal Scanners, & ML Models.  
3. **GEM 3 (The Lab):** Backtesting Engines, Forensics, & Optimization.  
4. **GEM 4 (The Glass):** The Visual Interface (Dash/Plotly).

## **II. THE INSTITUTIONAL 12 (TOOL INVENTORY)**

The system interface is divided into three operational domains.

### **A. OPERATIONS (Real-Time Execution)**

* **1\. LIVE SCOPE (/scope):** The Real-Time Market Monitor. Displays XSP Price, VIX Momentum, and RSI Flow on a strictly locked RTH axis (06:30–13:00 PST).  
* **2\. OPTIONS SIMULATOR (/sim):** The "Flight Deck" for paper trading. Features a high-contrast order entry panel and a local transaction ledger.  
* **3\. REPLAY ANALYSIS (/replay):** The "VCR" for market data. Re-watches historical sessions bar-by-bar to study trade anatomy.

### **B. ANALYTICS & STRATEGY (Pattern Recognition)**

* **4\. CHART SCANNER (/chart):** The heavy-duty forensic scanner. Visualizes the 4-Layer Truth (Price, Option, VIX, RSI).  
* **5\. OPTIMAL LAB (/lab):** The "Expert-in-the-Loop" training system. Allows manual labeling of "Ground Truth" data for the ML engine.  
* **6\. TRADE AUDIT & PATTERNS (/audit):** The behavioral analyst. Visualizes frequency (Hourly/Daily) and duration physics.  
* **7\. STATISTICAL METRICS (/stats):** The quantitative companion to the Audit. Tracks Win Rate, Profit Factor, and Premium Burn.  
* **8\. RH LEDGER (/ledger):** The raw transaction feed from Robinhood (Atomized).  
* **9\. CAPITAL GROWTH (/growth):** The projection engine. Simulates compound growth trajectories with tax liabilities and "Net Goal" targeting.

### **C. SYSTEM INFRASTRUCTURE (Backend)**

* **10\. BACKTEST SEQUENCER (/generator):** The simulation controller. Runs historical strategies against the database.  
* **11\. RH MIRROR (/mirror):** The verification tool. Overlays actual executions onto historical charts to prove "Execution Quality."  
* **12\. SYSTEM MONITOR (/info):** The engineering deck. Monitors DB size, latency, disk usage, and provides the "Nuclear Reset" option.

## **III. CORE PROTOCOLS (THE LAWS)**

### **1\. The Timezone Law**

* **Vault (DB):** Always **UTC**.  
* **Glass (UI):** Always **US/Pacific (PST)**.  
* **Protocol:** Data is converted to PST and then *stripped* of timezone metadata (tz\_localize(None)) before rendering. This forces Plotly to display "Wall Clock" time, preventing UTC offsets from shifting the chart.

### **2\. The Snapshot Protocol (Anti-Lock)**

* **Problem:** DuckDB on Windows does not allow concurrent reading while the Pipeline is writing.  
* **Solution:** The Backtester and Lab use a **Binary Stream Copy** to clone the database to a temp file (temp\_view.duckdb) before reading. This bypasses the Write Lock, allowing you to run simulations while the pipeline downloads data.

### **3\. The RTH Lock**

* **Definition:** Regular Trading Hours are **06:30 – 13:00 PST** (09:30 – 16:00 ET).  
* **Enforcement:** All charts are hard-locked to this X-Axis range. Data outside this window is clipped to prevent "Pre-Market Distortion."

### **4\. The High-Contrast Standard**

* **Visuals:** The UI uses a "Midnight Blue" theme (\#0f172a) for containers.  
* **Inputs:** All interactive inputs (Dropdowns, Inputs) are strictly **Black Text on White Background** to ensure 100% legibility in all lighting conditions.

## **IV. OPERATIONAL WORKFLOWS**

### **1\. The Morning Routine (06:00 PST)**

1. **Launch:** Run python quant\_launcher.py.  
2. **Verify:** Check **SYSTEM MONITOR** for "Nominal" status and DB connectivity.  
3. **Deploy:** Open **LIVE SCOPE** on the main monitor.

### **2\. The Analysis Routine (Post-Market)**

1. **Ingest:** The background pipeline (DailyHarvest) auto-fills missing data.  
2. **Audit:** Use **TRADE AUDIT** to review the day's performance and tag behavioral errors.  
3. **Train:** Use **OPTIMAL LAB** to manually label missed opportunities ("Optimal Calls") to retrain the Oracle.

### **3\. The Development Routine**

1. **Debug:** Comment out the main\_pipeline thread in quant\_launcher.py to stop the auto-downloader.  
2. **Simulate:** Use **BACKTEST SEQUENCER** to run "What If" scenarios on the static data.

## **V. STRATEGIC ROADMAP (v4.x)**

* ✅ **v4.0:** Institutional GUI Overhaul (Completed).  
* ✅ **v4.1:** Snapshot Protocol / Lock Bypass (Completed).  
* ⚪ **v4.2:** **Headless Automation.** Wiring engine\_scanner to robin\_client for auto-execution.  
* ⚪ **v4.3:** **Multi-Leg Spreads.** Automating Vertical Spreads to cap risk.

*"We do not predict price. We predict volatility flow."*