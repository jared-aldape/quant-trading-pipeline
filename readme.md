# **🚀 Quant OS v2.2 (Anti-Rate-Limit Edition)**

"UTC in the Vault, Local on the Glass. Real Data in the Engine."

A professional-grade quantitative trading pipeline designed for VIX/SPX signals and XSP Option execution. This repository operates as a hybrid Calculation Engine (Python/DuckDB) and Single-Page Application (Dash/Plotly).

## **🏛️ The Four Laws (Strict Enforcement)**

### **🕰️ The Timezone Law (Amended v2.2)**

**"UTC in the Vault, Local on the Glass."**

* **Storage:** ALL timestamps in the database (DuckDB) must be stored as **Naive UTC** (UTC timestamps with no timezone information attached).  
* **Ingestion (The Handshake):** \* Data sources sending **Relative Time** (e.g., YFinance Wall Clock) must be explicitly localized to the machine's timezone (e.g., America/Los\_Angeles), converted to UTC, and then **stripped of timezone info** (tz\_localize(None)) before insertion.  
  * Data sources sending **Absolute Time** (e.g., Polygon Unix) must be converted directly to Naive UTC.  
* **Display:** Conversion to Local Time (PST) happens *only* at the visualization layer (Dashboard/Simulator).

### **🛡️ The Integrity Law**

**"The Golden Source"**

* market\_data/quant\_strategy.duckdb is the single source of truth. No CSV patching.  
* Sanitization: Dirty data is rejected or cleaned *before* database insertion.

### **👁️ The Observability Law**

**"No Silent Failures"**

* All actions are logged to src/utils/logger.py.  
* Critical data ingestion steps must be verifiable via src/ops/audit\_time.py.

### **🚦 The Rate-Limit Law**

**"Free Tier Safety"**

* All external API calls must respect Free Tier limits via Caching, Throttling (sleep timers), and "Smart Deduplication" (checking DB before fetching).

## **🏗️ Architecture v2.2**

We enforce a strict separation of concerns between Data Engineering (Pipeline) and User Interface (Tools).

### **📂 Directory Structure**

quant-trading-pipeline/

│

├── app.py                      \<-- 🚀 MASTER LAUNCHER (Run this\!)

│

├── src/

│   ├── pipeline/               \<-- ⚙️ THE ENGINE ROOM (ETL)

│   │   ├── 00\_daily\_update.py  \<-- Batch Orchestrator (Indices \-\> Signals \-\> Options)

│   │   ├── 00\_setup\_database.py \<-- Schema & Reset Tool

│   │   ├── ingest\_indices.py   \<-- Yahoo Finance Index Data (Naive UTC Enforced)

│   │   ├── scan\_signals.py     \<-- VIX RSI Signal Generator

│   │   ├── fetch\_options.py    \<-- Polygon Option Data (Rate-Limit Safe)

│   │   └── calc\_greeks.py      \<-- \[Optional\] Black-Scholes Engine

│   │

│   ├── tools/                  \<-- 🖥️ THE CONTROL PANEL (GUI)

│   │   ├── 10\_backtest.py      \<-- Backtest Engine (Real Data)

│   │   ├── 11\_backtest.py      \<-- Backtest UI

│   │   ├── 12\_forecast.py      \<-- Capital Growth Projector

│   │   ├── 08\_dashboard.py     \<-- Analysis Dashboard ("Smart Session" Logic)

│   │   ├── 09\_simulator.py     \<-- "Fog of War" Replay Tool

│   │   └── 14\_live\_dashboard.py \<-- Command Center (Home Page)

│   │

│   └── ops/                    \<-- 🔧 THE REPAIR SHOP

│       ├── audit\_time.py       \<-- Forensic Timestamp Inspector

│       ├── reset\_indices.py    \<-- Nuclear Option (Drop & Recapture Indices)

│       └── check\_db.py         \<-- General Health Diagnostic

## **🛠️ The Tool Suite (v2.2)**

### **1\. 🏠 Command Center (Home)**

* **Role:** Real-time market monitoring and news aggregation.  
* **Features:** Live Chart (5-minute Intraday SPX), Dual News Streams (Global \+ SPX Specific).  
* **Safety:** Protected by Global Session & Caching to prevent API bans.

### **2\. 🟦 Backtester (Tool 1\)**

* **Role:** Forensic Validation of strategy profitability using Real Option Pricing.  
* **Logic:**  
  * **Entry:** Triggered by VIX RSI signals.  
  * **Exit:** Managed by 30% Trailing Stop or 40% Profit Target.  
  * **Selection:** Supports "First Signal" (Standard) or "Best Signal" (Optimized) modes.

### **3\. 🟩 Forecaster (Tool 2\)**

* **Role:** Trajectory Simulation.  
* **Logic:** Projects capital growth using "Risk Buckets" to simulate periodic drawdown exposure.

### **4\. 💎 Analysis (Tool 3\)**

* **Role:** Post-Mortem Review.  
* **Key Feature:** **"Smart Session Awareness"**. Visualizes VIX signals against price action, correctly handling the difference between 24-hour Futures data and RTH Options data without clipping errors.

### **5\. 🟠 Simulator (Tool 4\)**

* **Role:** Training Environment.  
* **Tech:** "Fog of War" replay mode to practice execution without hindsight bias. Solves the "Double Shift" timezone bug to perfectly align UTC Options with Local Market Data.

## **🚀 Quick Start (Desktop)**

1. **Install Dependencies**

pip install \-r requirements.txt

2.   
3. Initialize the Vault (First Run Only)  
   Creates the optimized database schema with Primary Keys.

python src/pipeline/00\_setup\_database.py

4.   
5. Ingest Data (The Morning Routine)  
   Runs the ETL chain: Indices \-\> Signals \-\> Options.

python src/pipeline/00\_daily\_update.py

6.   
7. Launch Command Terminal  
   Opens the Master Launcher. Access via http://localhost:8050.

python app.py

8. 

## **🔧 Recovery Protocol (Timezone Ops)**

**Mission Debrief (Nov 28, 2025):** We identified and fixed a critical 7-hour drift caused by yfinance sending localized timestamps that were being stored incorrectly as UTC.

**If chart alignment breaks or timestamps look suspicious:**

1. **Audit:** Run the forensic tool.

python src/ops/audit\_time.py

2.   
   * *Check:* Do SPX and Options start at the same UTC hour (approx 14:30)?  
3. **Reset:** If misalignment is found, run the nuclear reset.

python src/ops/reset\_indices.py

4.   
   * *Action:* This drops the Indices table, re-downloads with strict PST-aware logic, and regenerates signals.

## **📱 Mobile Deployment (PWA)**

Quant OS v2.2 features a Responsive Grid layout optimized for mobile devices.

* **Desktop:** Run python app.py (Host 0.0.0.0).  
* **Mobile:** Connect to the same Wi-Fi. Go to http://YOUR\_PC\_IP:8050.  
* **Install:** Tap "Add to Home Screen" to install as a PWA app.

