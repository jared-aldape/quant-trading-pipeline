# **🚀 Quant OS v2.5: The Hybrid Engine (Pro)**

**"Hybrid Truth in the Vault. Proxy Speed on the Glass."**

Quant OS v2.5 is a professional-grade financial operating system designed for retail algorithmic trading. It implements the **Free Hybrid Data Protocol**, securing institutional-grade data ($0/mo) via a delay-tolerant architecture while providing real-time execution signals through liquid proxies.

## **🏛️ The Six Laws of Quant OS**

1. **🕰️ The Timezone Law:**  
   * **Vault:** All database timestamps are **Naive UTC**.  
   * **Glass:** All visualizations convert strictly to **Local Time (PST)**.  
   * **Protocol:** T-1 Enforcement prevents API errors by rejecting "Same Day" option requests from Polygon Basic.  
2. **⚖️ The Scaling Law:**  
   * **Reality:** We trade **XSP** (Mini-SPX).  
   * **Normalization:** SPX (^GSPC) is divided by 10\. SPY (ETF) is used 1:1.  
   * **Result:** Charts, Strikes, and P\&L align perfectly on the $600 scale.  
3. **🛡️ The Hybrid Law:**  
   * **The Vault (Truth):** Nightly ingestion uses **Polygon.io (Basic)** for exchange-grade EOD data.  
   * **The Glass (Speed):** Live monitoring uses yfinance for free real-time data via proxies (SPY/VIX).  
4. **🐇 The Proxy Law:**  
   * **Dead Zone:** Free Futures data (/ES) is unreliable.  
   * **The Fix:** We watch **SPY (ETF)** as the real-time proxy for market context. It trades parallel to XSP and serves as a valid leading indicator.  
5. **⚓ The Hard Deck Law:**  
   * **Safety:** The Backtester is forbidden from executing trades within **15 minutes** of the Opening Bell (09:30 ET).  
   * **Reality:** This prevents the engine from "filling" orders at unrealistic prices during opening spread chaos.  
6. **🌊 The Flow Law (Strategy):**  
   * **Logic:** "The River and the Ripple."  
   * **Macro (River):** 1-Hour VIX MACD Histogram must be **NEGATIVE** (Red Bars \= Bullish Market).  
   * **Micro (Ripple):** 5-Minute VIX MACD Line must cross **BELOW** Signal Line.  
   * **Trigger:** VIX\_FRACTAL\_LONG (Bullish SPX Entry).

## **📂 System Architecture (v2.5)**

The system uses a **Domain-Driven Design** to separate concerns:

QUANT-OS/  
├── data/                   \<-- The Vault (DuckDB file)  
├── logs/                   \<-- Execution Logs  
├── src/  
│   ├── core/               \<-- The "Brains" (Logic & Engines)  
│   │   ├── engine\_backtest.py      (Historical Simulation)  
│   │   ├── engine\_scanner.py       (Signal Detection)  
│   │   ├── engine\_greeks.py        (Delta/Gamma/Theta Math)  
│   │   └── strat\_fractal.py        (Strategy Logic Source of Truth)  
│   │  
│   ├── data/               \<-- The "Ingest" (Fetchers)  
│   │   ├── ingest\_indices.py       (SPX, VIX, IRX)  
│   │   ├── ingest\_options.py       (XSP Option Chains)  
│   │   └── db\_schema.py            (Database Initialization)  
│   │  
│   ├── interface/          \<-- The "Glass" (Dash UI)  
│   │   ├── view\_command.py         (Live Dashboard)  
│   │   ├── view\_forensics.py       (Post-Trade Analysis)  
│   │   ├── view\_backtester.py      (Strategy Tester UI)  
│   │   ├── view\_simulator.py       (Trade Replay)  
│   │   └── view\_forecast.py        (Monte Carlo)  
│   │  
│   └── utils/              \<-- Shared Utilities  
│       ├── config.py  
│       └── logger.py  
│  
├── main\_pipeline.py        \<-- Daily Data Update Script  
└── app.py                  \<-- Main UI Entry Point

## **🛠️ The Tool Suite**

### **1\. Pipeline: The Morning Routine**

Run this daily to synchronize the Vault with Hybrid Truth.

python main\_pipeline.py

* **Ingest:** Fetches SPX/VIX/IRX (Hybrid Mode). **Retains history forever.**  
* **Scan:** Runs strat\_fractal.py to identify trade signals.  
* **Fetch:** Downloads XSP option chains for identified signal days.  
* **Calc:** Computes Greeks (IV, Delta) for all new options.

### **2\. Command Center (Live)**

python app.py

* **URL:** http://localhost:8050/  
* **Role:** Real-Time Execution Monitor.  
* **Features:** Live "Signal Status" Badge (Armed/Wait), Proxy Context, Fractal Flow Charts.

### **3\. Forensic Lab**

* **URL:** http://localhost:8050/analysis  
* **Role:** Post-Game Review.  
* **Features:** Visual proof of signal timing, Option P\&L overlay vs Spot Price.

### **4\. Strategy Backtester**

* **URL:** http://localhost:8050/backtester  
* **Role:** Verification Time Machine.  
* **Features:** Hard Deck enforcement, Tax Engine (Section 1256), Equity Curve visualization.

## **🔧 Database Schema (DuckDB)**

| Table Name | Content | Update Frequency | Retention Policy |
| :---- | :---- | :---- | :---- |
| indices\_1m | SPX, VIX OHLCV | Daily | **Permanent Append** |
| options\_1m | XSP Options \+ Greeks | T-1 (Daily) | **Permanent Append** |
| trade\_manifest | Valid Signals | On Scan | Rebuilt Daily |
| risk\_free\_rate\_daily | IRX (13-Week T-Bill) | Daily | Upsert |
| active\_simulation\_log | Backtest Results | On Run | Overwritten |

## **🚀 Operational Workflow**

1. Ingest & Scan (8:00 PM PST):  
   Run python main\_pipeline.py. This repairs the Vault with official Polygon data from the closed session and generates the trade manifest. IMPORTANT: Do not delete the database file; this script builds history over time.  
2. Live Monitoring (06:30 AM PST):  
   Run python app.py and open the Command Center.  
   * **Watch Status Badge:** Wait for "ARMED" (Green).  
   * **Confirm:** Check SPY Context (Row 1).  
3. Review (Post-Close):  
   Open the Forensic Analysis tab to verify trade execution against the "Hard Deck" and pricing logic.