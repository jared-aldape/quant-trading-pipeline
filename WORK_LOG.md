# QUANT OS v4.0 - ARCHITECTURAL CONSTITUTION & WORK LOG

## 🛑 CRITICAL INTEGRITY RULES
1. **NO DELETIONS:** Do not remove "unused" functions. This is a modular system; functions like `run_backtest` are used by the UI even if the pipeline script doesn't call them.
2. **DUAL ENGINE PROTOCOL:** `engine_backtest.py` MUST contain BOTH:
   - `run_backtest()` -> For the UI/Visualizer (returns complex tuples).
   - `run_backtest_session()` -> For the Automation/Pipeline (returns simple DataFrames).
3. **DATA HYBRID MODEL:** `ingest_indices.py` MUST maintain:
   - Yahoo Finance (5m interval) for deep history.
   - Polygon.io (Backup) for redundancy.
   - `generate_snapshot_from_db` for the UI dashboard.
4. **SNAPSHOT PROTOCOL:** All UI tools reading from DuckDB *must* use the binary copy / snapshot method if on Windows to avoid `[WinError 32]` lock collisions with the pipeline.

---

## 📂 CRITICAL FILE MANIFEST (DO NOT SIMPLIFY)
| File | Critical Functions (Do Not Remove) | Reason |
| :--- | :--- | :--- |
| `src/core/engine_backtest.py` | `run_backtest`, `run_backtest_session`, `get_safe_connection` | Powers UI simulations and Pipeline daily checks. |
| `src/data/ingest_indices.py` | `fetch_polygon_backup`, `generate_snapshot_from_db`, `run_ingest` | UI relies on the JSON snapshot; Pipeline relies on the DB ingest. |
| `src/core/engine_ml_precision.py` | `train_precision_oracle`, `build_precision_dataset` | Direct dependency for the Daily Pipeline. |
| `src/interface/view_data_generator.py` | `update_gen_stats` | Relies on specific return signature from `engine_backtest.run_backtest`. |

---

## 📝 REVISION LOG

### [2026-01-14] - The "Institutional" Modernization (v4.0)
- **GUI OVERHAUL:** Converted all 12 tools to "Midnight Blue" institutional theme with high-contrast inputs (`dbc.Select`) to fix visibility issues.
- **INFRASTRUCTURE:** Implemented **"Snapshot Protocol"** in `engine_backtest.py`. The system now clones the database to a temp file before reading, bypassing Windows Write Locks during live ingestion.
- **FIXED:** `view_live_scope.py` temporal drift. Logic now anchors charts to the **Data Date**, not the System Date, preventing blank charts when viewing backup data.
- **FIXED:** `view_replay_analysis.py` circular callback logic and subplot rendering. Restored the 4-row forensic layout (Price, Option, VIX, RSI).
- **RESTRUCTURED:** `quant_launcher.py` navigation updated to a 3-tier hierarchy: **Operations** (Real-Time), **Analytics** (Research), and **Infrastructure** (Backend).
- **DOCUMENTATION:** Updated `README.md` to reflect the v4.0 standard and tool inventory.

### [2025-12-23] - The "Restoration" Update
- **FIXED:** `engine_backtest.py` was stripped of UI logic. Restored `run_backtest` alongside `run_backtest_session`.
- **FIXED:** `ingest_indices.py` was stripping Snapshot/Backup logic. Restored full functionality.
- **FIXED:** `main_pipeline.py` updated to use dynamic imports and fail gracefully rather than crashing on missing attributes.
- **ADDED:** `engine_chop_guard.py` integration into `engine_scanner.py` to prevent "machine gun" trading in chop.
- **ADDED:** Serial Execution Lock added to `engine_backtest.py` to prevent overlapping trades in simulation.

---

## ⚠️ NEXT STEPS
1. **Archive Obsolete:** Move legacy files (e.g., `debug_*.py`, `master_forensic_auditor.py`) to an `archive/` folder.
2. **Headless Automation:** Wire `engine_scanner.py` directly to an execution client (`robin_client.py`) for the v4.2 milestone.
3. **Multi-Leg Spreads:** Begin research on Vertical Spread logic for the next major feature update.