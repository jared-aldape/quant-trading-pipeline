# **📊 QUANT OS v4.1.0: INSTITUTIONAL EXECUTION SYSTEM**

*"Hybrid Truth in the Vault. Surgical Precision on the Glass. Vigilance in the Void."*

* **Version:** v4.1.0 (Institutional UI & Strategic Matrix Update)  
* **Status:** **LIVE / PRODUCTION READY** \* **Node:** Quant-OS-Node-1 (Local/AWS Hybrid)  
* **Last Update:** March 2026

## **I. THE PRIME DIRECTIVE**

Quant OS is an **Institutional Execution System** designed to eliminate emotional bias through strict algorithmic enforcement, real-time probability density modeling, and superior data visualization. It operates on a **Hybrid Architecture**:

* **Truth (The Vault):** Polygon.io (Historical Ingestion) & DuckDB (High-Speed Local Storage).  
* **Speed (The Glass):** Dash/Plotly (Visualization Interface) utilizing Zero-Latency layout protocols.  
* **Vigilance (The Sentinel):** Python Daemon (Background Automation & Reconciliations).

## **II. THE SIX LAWS OF QUANT OS (CORE PROTOCOL)**

Non-negotiable rules for data integrity and execution.

* 🕰️ **The Timezone Law:**  
  * **Vault:** All database timestamps are **Naive UTC** (Universal Time).  
  * **Glass:** All visualizations convert strictly to **Naive US/Pacific** (Local Time).  
  * *Rationale:* Prevents "look-ahead bias" and "ghost signals" caused by timezone shifts.  
* ⚖️ **The Scaling Law:**  
  * **Reality:** We trade **XSP** (Mini-SPX) for optimal tax efficiency (Section 1256 60/40 rule).  
  * **Context:** **SPY** is the proxy for trend context. SPX is purged to reduce API overhead and latency.  
* 🛡️ **The Hard Deck Law:**  
  * **RTH Only:** No signals generated outside 09:30 \- 16:00 ET.  
  * **Orphan Control:** Trades left open at 16:00 ET are force-closed in all simulations.  
* 💰 **The Friction Law:**  
  * **Simulation:** $0.03 Reg Fee \+ $1.00 Slippage calculated per contract.  
  * **Reality:** Actual fills execute directly via the Robinhood ledger API.  
* 📉 **The Gatekeeper Law:**  
  * **Filter:** Signals must pass a strict Fractal Trend \+ VIX Regime validation check.  
  * **Oracle:** The ML model (Precision Engine) validates signals against 100k+ historical option outcomes.  
* 🌊 **The Flow Law:**  
  * **Context:** Intraday trades must align with the 20-Day Macro Flow (Bull/Bear Bias).

## **III. SYSTEM ARCHITECTURE & INVENTORY**

### **A. The Core (Logic Engines)**

* quant\_launcher.py: **Central Command.** Unified dashboard entry point and thread manager.  
* engine\_scanner.py: **The Brain.** Scans XSP/VIX for Fractal setups. Purges old signals daily to prevent fragmentation.  
* engine\_backtest.py: **The Simulator.** Deterministic physics engine supporting "What If" parameters (Ideal Gain, Trailing Stop).  
* engine\_forensics.py: **The Auditor.** FIFO Reconciler that pairs independent Buy/Sell rows into closed PnL trades.  
* engine\_ml\_precision.py: **The Oracle.** Random Forest model trained on real 0DTE option pricing to predict setup success.

### **B. The Data (Ingestion Pipeline)**

* ingest\_indices.py: Fetches underlying XSP/VIX OHLCV data.  
* ingest\_options\_daily.py: **Precision Harvester.** Downloads 1-minute bars for ATM \+/- 3 strikes *only*, minimizing database bloat.  
* ingest\_ledger.py: **The Bookkeeper.** Hydrates the local database with raw Robinhood execution CSVs.

### **C. The Interface (The Institutional 13\)**

*A strict Midnight Blue (\#0f172a) and Black (\#000000) theme utilizing Monospace fonts for rapid data parsing and reduced eye fatigue.*

**OPERATIONS (Real-Time Execution)**

1. **LIVE SCOPE (/scope):** The Real-Time Market Monitor. Displays XSP Price, VIX Momentum, and RSI Flow on a strictly locked RTH axis.  
2. **STRATEGIC OPTIONS MATRIX (/strike):** The 0DTE Scenario Modeler. Features real-world Dollar PnL, dynamic Time-Decay velocity, VIX expected move boundaries, and comparative \+1/+2/+3 array visualization for precise target limits.  
3. **OPTIONS SIMULATOR (/sim):** The paper-trading sandbox featuring a high-contrast order entry panel.  
4. **REPLAY ANALYSIS (/replay):** The post-market tape playback system. Reconstructs market conditions tick-by-tick with VCR controls.

**ANALYTICS & STRATEGY (Research)**

5\. **CHART SCANNER (/chart):** Multi-timeframe deep analysis terminal overlaying signals with VIX Regime tinting.

6\. **OPTIMAL LAB (/lab):** ML Training ground for manual tagging of high-probability setups.

7\. **TRADE AUDIT (/audit):** Behavioral forensics tool tracking manual errors vs. system discipline.

8\. **STATISTICAL METRICS (/stats):** High-level quantitative breakdown of system edge, win rate, and drawdown.

9\. **RH LEDGER (/ledger):** Raw transaction data viewer.

10\. **CAPITAL GROWTH (/growth):** Geometric growth forecaster with Reality Overlay and Compound Interest modeling.

**INFRASTRUCTURE (System & Config)**

11\. **BACKTEST SEQUENCER (/generator):** Headless simulation runner for bulk strategy testing.

12\. **RH MIRROR (/mirror):** API connectivity verification and synchronization status.

13\. **SYSTEM MONITOR (/info):** Database health, latency metrics, and pipeline status.

## **IV. OPERATIONAL WORKFLOWS**

### **1\. The Morning Protocol (06:00 PST)**

1. **Run:** python main\_pipeline.py (Updates XSP/VIX data).  
2. **Ingest:** Harvester downloads missing option chains (Targeted Strike Ingestion).  
3. **Scan:** Scanner engine generates fresh operational signals for the day.

### **2\. The Execution Watch (06:30 \- 10:30 PST)**

1. **Launch:** python quant\_launcher.py \-\> Select **LIVE SCOPE**.  
2. **Monitor:**  
   * *VIX Thermometer:* Is volatility crushed (\<20%)? Exercise caution on Longs.  
   * *RSI Flow:* Is the trend aligned with the 20-Day macro?  
   * *Oracle Confidence:* Is the ML score \> 60%? **Green light.**  
3. **Execute:** Upon signal, open **STRATEGIC MATRIX**. Input real-world premiums to calculate optimal strike, expected hold time, and limit price before routing to the broker.

### **3\. The Forensic Review (Post-Market)**

1. **Export:** Download Robinhood execution CSV.  
2. **Hydrate:** Run python src/data/ingest\_ledger.py to synchronize the local ledger.  
3. **Audit:** Launch **TRADE AUDIT** to review performance, log slippage, and tag behavioral deviations.

## **V. STRATEGIC ROADMAP (v4.x)**

* ✅ **Priority Alpha:** Unified Launcher & Institutional GUI Standardization (Completed).  
* ✅ **Priority Bravo:** FIFO Reconciler & Behavioral Audit Integration (Completed).  
* ✅ **Priority Charlie:** Oracle ML Integration & Strategic Options Matrix (Completed).  
* ⚪ **Priority Delta: Headless Automation.** Connect engine\_scanner.py directly to robin\_client.py for automated signal execution.  
* ⚪ **Priority Echo: Multi-Leg Spreads.** Automate Vertical Spreads and Iron Condors to mathematically cap risk parameters.

## **VI. PROJECT LOG (Recent)**

* **v4.1.0:** Strategic Options Matrix implementation. Replaced theoretical modeling with real-world premium inputs and hold-time velocity scaling.  
* **v4.0.0:** Institutional UI Overhaul. Transitioned all interfaces to high-contrast finance terminal aesthetics.  
* **v3.9.0:** Launcher Consolidation. Retired disparate app files into a unified dashboard.  
* **v3.8.0:** FIFO Engine. Built logic to automatically pair independent Buy/Sell transactions into closed trades for accurate PnL tracking.  
* **v3.7.0:** Surgical Ingestion. Replaced bulk historical downloads with targeted ATM \+/- 3 daily harvester to optimize database latency.