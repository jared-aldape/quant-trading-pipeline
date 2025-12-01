# **🚀 Quant OS v2.2: Trade Master Operating Manual**

**"UTC in the Vault, Local on the Glass. Real Data in the Engine."**

This document outlines the architecture, protocols, and usage of the **Quant OS v2.2** financial operating system. This version introduces Database Persistence, Hybrid Forecasting ("Silver Arrow"), and the optimized Trade Master signal logic.

## **🏛️ The Four Laws (v2.2 Amendments)**

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
   * **Protocol:** T-1 Enforcement prevents API errors by strictly rejecting "Same Day" option requests.  
2. **🛡️ The Integrity Law:**  
   * **Golden Source:** market\_data/quant\_strategy.duckdb is the single source of truth.  
   * **Persistence:** Tools do not pass CSV files. Tool 1 writes to the DB; Tool 2 reads from the DB.  
3. **👁️ The Observability Law:**  
   * **No Silent Failures:** Every script logs forensic details to the console.  
   * **Visual Validation:** The Dashboard must visually confirm what the Backtester executes.  
4. **🚦 The Rate-Limit Law:**  
   * **Cluster Fetching:** Efficiently downloads ATM ±2 strikes while respecting API limits.  
   * **Smart Audit:** Automatically detects and repairs fragmented/partial data.

## **🧠 Trade Master Strategy Protocols**

The system uses a mean-reversion logic based on VIX overextension. It supports two distinct operating modes for src/pipeline/scan\_signals.py.

**Optimization Finding:** The "MACD Trap" was identified and removed. Momentum confirmation (MACD) was found to be a lagging indicator that reduced profitability. Pure RSI mean-reversion is the validated edge.

### **1\. 🟢 "Active Trader" Protocol (Current Default)**

* **Logic:** RSI(10) \< 30  
* **Philosophy:** High frequency, balanced risk.  
  * **Sensitivity:** Uses a faster RSI period (10) to capture moderate volatility dips in strong trends.  
  * **Why:** Standard RSI(14) is too smooth to trigger often during strong Bull Markets.  
* **Use Case:** Daily income generation.

### **2\. 🎯 "Sniper" Protocol (High Conviction)**

* **Logic:** RSI(14) \< 22  
* **Philosophy:** Extreme selectivity.  
  * **Sensitivity:** Uses standard RSI period (14) but a deeper compression threshold (22).  
  * **Stats:** Historically 100% Win Rate (Small Sample Size).  
* **Use Case:** Capital preservation or aggressive sizing on rare setups.

To Switch Protocols:  
Edit the configuration block in src/pipeline/scan\_signals.py:  
\# Active Mode  
VIX\_RSI\_THRESHOLD \= 30  
VIX\_RSI\_PERIOD \= 10

\# Sniper Mode  
VIX\_RSI\_THRESHOLD \= 22  
VIX\_RSI\_PERIOD \= 14

## **🛠️ The Tool Suite**

### **Pipeline: The Morning Routine**

Run this daily to synchronize the Vault.

python src/pipeline/00\_daily\_update.py

* **Step 1:** Ingest Indices (SPX, VIX) & Futures (/ES).  
* **Step 2:** Generate Signals (Wipes/Rebuilds Manifest based on active Protocol).  
* **Step 3:** Ingest Options (Smart Audit \+ Cluster Fetching).

### **Tool 3: Analysis Dashboard**

* **Role:** Visual Verification.  
* **Features:**  
  * **RTH Mode:** Hides pre-market noise.  
  * **Cluster View:** Dropdown allows selection of OTM/ITM strikes.  
  * **Ghost Line:** Futures data overlay for 24h context.  
* **Access:** http://localhost:8050/analysis

### **Tool 1: The Backtester**

* **Role:** Forensic Execution & Logging.  
* **New Features:**  
  * **Skip Open:** Ignores the first 15 mins (06:30-06:45 PST) to avoid spread volatility.  
  * **Strike Offset:** Test **OTM (+1)** vs **ATM (0)** strategies.  
  * **DB Write:** Saves trade log to active\_simulation\_log table.  
* **Usage:**  
  1. Select Date Range & Start Capital.  
  2. Choose "Best Signal" (Optimized) or "First Signal".  
  3. Click **Run Simulation**.

### **Tool 2: The Forecaster ("Silver Arrow")**

* **Role:** Expectation Management & Projection.  
* **Logic:** Hybrid Model.  
  * **Gold Line (Silver Arrow):** Your Ideal Daily Goal (e.g., 20% compounding).  
  * **Green Cone (Reality):** Monte Carlo simulation using **Real Data** from Tool 1\.  
* **Metrics:**  
  * **Probability of Hitting Target:** The % chance your strategy can keep up with your goal.  
  * **Ruin Probability:** The odds of blowing up the account (\<10% balance).  
* **Requirement:** You **must** run Tool 1 at least once to populate the database before running Tool 2\.

## **🔧 Database Schema**

| Table Name | Content | Update Frequency |
| :---- | :---- | :---- |
| indices\_1m | SPX, VIX OHLCV (UTC) | Daily |
| futures\_1m | /ES Futures (UTC) | Daily |
| options\_1m | XSP Options (UTC) | T-1 (Daily) |
| trade\_manifest | List of valid signal timestamps | On Scan |
| active\_simulation\_log | Logs of the last Backtest run | On Backtest |

## **🚀 Quick Launch**

\# 1\. Update Data  
python src/pipeline/00\_daily\_update.py

\# 2\. Launch GUI  
python app.py  
