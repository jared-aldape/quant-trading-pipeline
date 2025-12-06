# **⚔️ QUANT OS v3.3: THE TACTICAL COMMAND SYSTEM**

**"Hybrid Truth in the Vault. Surgical Precision on the Glass. Vigilance in the Void."**

* **Version:** v3.3.1 (Stable / Magitek Build)  
* **Status:** Command Mode Active  
* **Node:** Quant-OS-Node-1 (AWS US-East-2)  
* **Last Update:** December 06, 2025

## **I. THE PRIME DIRECTIVE**

Quant OS is not just a backtester; it is a **Tactical Command System** designed to eliminate emotional bias through strict algorithmic enforcement. It operates on a **Hybrid Architecture**:

1. **Truth (The Vault):** Polygon.io (Historical) & DuckDB (Storage).  
2. **Speed (The Glass):** Yahoo Finance (Real-time) & Dash (Visualization).  
3. **Vigilance (The Sentinel):** Python Daemon (Automation).

## **II. THE SIX LAWS OF QUANT OS (CORE PROTOCOL)**

*These laws are non-negotiable. Breaking them corrupts the data and invalidates the strategy.*

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
   * *Rationale:* Preventing "look-ahead bias" caused by timezone shifts.  
2. **⚖️ The Scaling Law:**  
   * **Reality:** We trade **XSP** (Mini-SPX) for tax efficiency (60/40 rule).  
   * **Alignment:** SPY is the high-speed proxy. Futures (/ES) are scaled (1/10th) for overlays.  
3. **🛡️ The Hard Deck Law:**  
   * **Restriction:** No executions within **15 minutes** of the Opening Bell (09:30 ET).  
   * **Expiration:** 0DTE options strictly expire at 16:00 ET (Value \= Intrinsic Only). No "Ghost Extrinsic" value allowed.  
4. **💰 The Friction Law:**  
   * **Cost:** Every simulation deducts **Slippage ($0.01)** and **Regulatory Fees** (Robinhood/SEC rates).  
   * *Rationale:* A strategy is only profitable if it beats the friction.  
5. **🧠 The Gatekeeper Law:**  
   * **Filter:** Entries require **Fractal Flow** (VIX Macro/Micro alignment) \+ **RSI Momentum**.  
   * *Rationale:* Preventing counter-trend entries during high-volatility chop.  
6. **🌊 The Flow Law:**  
   * **Bias:** Position sizing is weighted by the **20-Day Macro Flow Bias** (Bull/Bear).  
   * *Rationale:* "Don't fight the ocean."

## **III. SYSTEM ARCHITECTURE**

The system uses a smart config.py to auto-detect its environment (Local vs. Cloud).

QUANT-OS/  
├── data/                 \<-- The Vault (DuckDB \+ JSON State)  
├── assets/               \<-- Visual Protocols (Magitek SVG)  
├── src/  
│   ├── core/             \<-- Logic Engines  
│   │   ├── engine\_simulator.py  \<-- Live Execution (Multi-Threaded)  
│   │   ├── engine\_backtest.py   \<-- Historical Validation  
│   │   └── sentinel.py          \<-- Automation Daemon  
│   ├── interface/        \<-- The "Glass" (Dash Views)  
│   └── utils/            \<-- Config & Logging  
├── app.py                \<-- Main UI Entry Point (Port 8050\)  
└── main\_pipeline.py      \<-- Daily Data Cron Job (06:00 PST)

## **IV. OPERATIONAL WORKFLOW**

### **1\. The Morning Ritual (06:15 PST)**

* **Objective:** Ensure the "Vault" has ingested yesterday's closing data.  
* **Action:** Check the **System Health** page. Verify "DB Latency" is \< 24 hours.

### **2\. The Watch (06:30 \- 13:00 PST)**

* **Objective:** Monitor for Fractal Flow signals.  
* **Tool:** **Live Console**.  
* **Automation:** The **Sentinel** scans ^VIX every 60s and dispatches Discord alerts.

### **3\. The Review (Post-Market)**

* **Objective:** Audit performance against the model.  
* **Tool:** **Statistics Lab** & **Chart Analysis**.  
* **Action:** Run the **Data Generator** to see if the "Perfect Robot" would have taken your trades.

## **V. STRATEGIC ROADMAP**

### **🔴 Priority Alpha: The Hedge Protocol**

* **Objective:** Enable concurrent Long Call and Long Put positions (Straddles/Hedges).  
* **Status:** **DEPLOYED (v3.3.1)**.  
* **Notes:** engine\_simulator.py refactored to support multi-lot portfolios and atomic ledger writing.

### **🟡 Priority Bravo: Machine Learning Optimization**

* **Objective:** Train a Random Forest classifier on TBL\_SIM\_LOG.  
* **Goal:** Predict trade success probability based on VIX Level and Time of Day.  
* **Status:** **Pending Integration**. Logic exists but is not wired to Live Console.

### **⚪ Priority Charlie: Multi-Leg Execution**

* **Objective:** Vertical Spreads (Debit Spreads) to cap risk.  
* **Status:** Concept Phase.

## **VI. PROJECT LOG**

* **M16:** Cloud Injection (AWS EC2 Deployment).  
* **M17:** Memory Protocol (Swap File for low-RAM stability).  
* **M18:** Sentinel Daemon (Systemd Service).  
* **M19:** Environment Awareness (Dynamic Config).  
* **M20:** The Glass Refactor (Mobile Responsiveness).  
* **M21:** **Architecture Consolidation (v3.3)** – Merged "Training Gym" into Replay Analysis.  
* **M22:** **Visual Protocol Update** – Implemented **"Magitek" (Final Fantasy VI)** theme and SVG logic.  
* **M23:** **Simulation Core Patch** – Fixed "Ghost Trade" bug, enforced 0DTE Expiration Hard Deck, and enabled Multi-Threaded Portfolios.