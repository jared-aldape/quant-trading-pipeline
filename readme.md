# 🏛️ Quant Trading Pipeline (v2.0 Architecture)

**"UTC in the Vault, Local on the Glass."**

This repository hosts a professional-grade quantitative trading pipeline designed for VIX/SPX signals and XSP Option execution. It prioritizes data integrity, strict timezone normalization, and total observability.

---

## 📜 The Project Constitution (The Laws)

### 1. The Timezone Law
* **Storage:** ALL timestamps in the database (`DuckDB`) are stored as **UTC**. No exceptions.
* **Ingestion:** Data is converted to UTC *immediately* upon entry.
    * Yahoo Finance (SPX/VIX) → Assumed `America/New_York` → Converted to UTC.
    * Polygon.io (Options) → Native UTC → Stored as UTC.
* **Display:** Conversion to Local Time (`US/Pacific`) happens *only* at the visualization layer (Dashboard/Simulator).

### 2. The Data Integrity Law
* **Golden Schema:** Tables enforce strict types (`TIMESTAMP`, `DOUBLE`, `BIGINT`).
* **Uniqueness:** Composite Primary Keys (e.g., `datetime_utc + ticker`) prevent duplicate rows.
* **Sanitization:** Dirty data is rejected before insertion. We do not "patch" data errors in the UI; we fix them at the source.

### 3. The Observability Law
* **No Silent Failures:** Every script uses the centralized `src.utils.logger`.
* **Forensics:** All execution logs are saved to `logs/pipeline.log` for audit trails.

---

## 📂 Workflow & Scripts

### Phase 1: Foundation
* **`src/utils/config.py`**: The single source of truth for Paths, Keys, and Constants.
* **`00_setup_database.py`**: The "Big Bang." Wipes the database and rebuilds the empty Golden Schema tables.

### Phase 2: Ingestion (The Gatekeeper)
* **`01_ingest_indices.py`**: Fetches Context Data.
    * **SPX/VIX:** Market Hours context.
    * **ES=F (Futures):** Overnight/24h context.
    * **^IRX (Rates):** Daily Risk-Free Rate for Greek calculations.

### Phase 3: Processing (The Engine)
* **`02_scan_signals.py`**:
    * Loads VIX data.
    * Calculates Technicals (Standard MACD 12/26/9 + Wilder's RSI 14).
    * Detects `VIX_MACD_BEAR_CROSS` events.
    * Writes signals to `trade_manifest`.
* **`03_fetch_options.py`**:
    * Reads the Manifest.
    * Performs **Hybrid Price Lookup** (Uses SPX during day, Futures during night) to determine ATM Strike.
    * Fetches Option Chains (ATM +/- 2) from Polygon.io.
* **`04_calc_greeks.py`**:
    * Calculates IV, Delta, Gamma, Vega, Theta using Newton-Raphson.
    * Uses **Dynamic Interest Rates** (from `^IRX`) for historical accuracy.

### Phase 4: Visualization (The Fruit)
* **`08_dashboard.py`**: Post-Mortem Analysis. 4-Row layout (Price, SPX/Futures, MACD, RSI).
* **`09_simulator.py`**: Training Environment. 5-Row layout. "Fog of War" replay mode.

---

## 💾 Database Schema

| Table | PK | Content | Source |
| :--- | :--- | :--- | :--- |
| **`indices_1m`** | `datetime_utc`, `ticker` | SPX, VIX Price History | Yahoo |
| **`futures_1m`** | `datetime_utc`, `ticker` | /ES Futures Price History | Yahoo |
| **`options_1m`** | `datetime_utc`, `ticker` | XSP Option Chains (OHLCV) | Polygon |
| **`trade_manifest`** | `entry_timestamp_utc` | Signal Events & Metadata | Calculated |
| **`risk_free_rate_daily`**| `date` | 13-Week T-Bill Yields | Yahoo |

---

## 🛠️ Setup Instructions

1.  **Configure:** Add API Keys to `src/utils/config.py`.
2.  **Initialize:** `python 00_setup_database.py`
3.  **Ingest:** `python 01_ingest_indices.py`
4.  **Scan:** `python 02_scan_signals.py`
5.  **Fetch:** `python 03_fetch_options.py`
6.  **Calc:** `python 04_calc_greeks.py`
7.  **Run:** `python 09_simulator.py`