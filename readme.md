# 🏛️ Quant Trading Pipeline (v2.0 Architecture)

**"UTC in the Vault, Local on the Glass."**

This repository hosts a professional-grade quantitative trading pipeline designed for **VIX/SPX** signals and **XSP** Option execution. It prioritizes data integrity, strict timezone normalization, and total observability, utilizing a modular **Five-Tool Ecosystem** for validation, planning, and execution.

---

## 📜 1. The Project Constitution (The Laws)

1.  **The Timezone Law:**
    * **Storage:** ALL timestamps in `DuckDB` are stored as **UTC**.
    * **Ingestion:** Data is converted to UTC **immediately** upon entry.
    * **Display:** Conversion to Local Time (**US/Pacific**) happens **only** at the visualization layer (Dashboards/GUIs).

2.  **The Data Integrity Law:**
    * **Golden Schema:** Tables enforce strict types (TIMESTAMP, DOUBLE).
    * **Uniqueness:** Composite Primary Keys (`datetime_utc + ticker`) prevent duplicates.
    * **Sanitization:** Dirty data is rejected before insertion; no downstream patching.

3.  **The Observability Law:**
    * **No Silent Failures:** Centralized logging (`src.utils.logger`) for all scripts.
    * **Visual Confirmation:** Live "Terminal-style" ledgers and status icons provide instant feedback during execution.

---

## 📂 2. Workflow & Data Pipeline (Batch Process)

The system operates on a linear data pipeline managed by the orchestrator.

| Phase | Script | Function | Artifacts |
| :--- | :--- | :--- | :--- |
| **Foundation** | `00_setup_database.py` | Initializes the empty **Golden Schema**. | `quant_strategy.duckdb` |
| **Ingestion** | `01_ingest_indices.py` | Fetches `SPX`, `VIX`, `ES=F`, `^IRX` and normalizes to **UTC**. | `indices_1m`, `futures_1m` |
| **Processing** | `02_scan_signals.py` | Calculates VIX Technicals (`MACD`, `RSI`) and detects signals. | `trade_manifest` |
| **Fetching** | `03_fetch_options.py` | Hybrid Price Lookup (`SPX/ES`) $\rightarrow$ ATM Strike $\rightarrow$ Fetch `XSP` Chains. | `options_1m` |
| **Compute** | `04_calc_greeks.py` | Calculates `IV`, `Delta`, `Gamma` using Newton-Raphson. | Updates `options_1m` |

---

## 📊 3. The Five-Tool Ecosystem (Consumption)

The pipeline feeds five independent, modular tools. Each tool is a separate program.

| ID | Tool Name | Script | Role & Logic Source |
| :--- | :--- | :--- | :--- |
| **1** | **Historical Backtester** | `11_backend_gui.py` | **Forensic Validation (The Judge):** Runs `10_backtest.py` on **historical data** to prove strategy viability. Features **Tax-Adjusted Compounding** and Streaming Logs. |
| **2** | **Trajectory Forecaster** | `12_forecaster_gui.py` | **Goal Simulation (The Planner):** A standalone **Math Engine** (no DB) that projects future equity based on your **ROI Goals** and **Risk Buckets** (Stop Loss Cycles). |
| **3** | **Analysis Dashboard** | `08_dashboard.py` | **Post-Mortem Review:** Visualizes VIX signals against price action with **Greek Hovercards** for forensic trade review. |
| **4** | **Flight Simulator** | `09_simulator.py` | **Training Environment:** Interactive, "fog of war" replay mode for practicing execution timing. |
| **5** | **Real-Time Status** | `13_live_dashboard.py` | **Operational Awareness:** "Near-Live" monitoring of proprietary analysis (Managed Data Service model). |

---

## 🛠️ 4. Setup Instructions

1.  **Environment:** `pip install -r requirements.txt`
2.  **Configure:** Set API Keys and `TAX_RATE_SECTION_1256` in `src/utils/config.py`.
3.  **Initialize:** `python 00_setup_database.py`
4.  **Update Data:** `python 00_daily_update.py` (Runs Phases 1-4)
5.  **Launch Tools:**
    * *Validate History:* `python 11_backend_gui.py`
    * *Plan Future:* `python 12_forecaster_gui.py`