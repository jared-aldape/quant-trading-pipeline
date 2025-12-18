import sys
import duckdb
import pandas as pd
from pathlib import Path
import datetime

# ==============================================================================
# PATH CONFIGURATION
# ==============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.append(str(SCRIPT_DIR))

# Centralized Reports Directory
REPORTS_DIR = SCRIPT_DIR / "reports"

try:
    from src.utils import config
except ImportError:
    print("❌ ERROR: Could not import 'src.utils.config'. Ensure script is in root.")
    sys.exit(1)

# ==============================================================================
# LOGIC: FILE SYSTEM DISCOVERY
# ==============================================================================
def get_file_structure():
    """Emulates the User CLI: Get-ChildItem -Recurse -File with exclusions."""
    exclusions = {'.git', '.venv', '__pycache__', '.idea', 'node_modules', '.ipynb_checkpoints'}
    file_list = []
    
    for path in SCRIPT_DIR.rglob('*'):
        # Check if any part of the path is in the exclusion list
        if not any(excluded in path.parts for excluded in exclusions):
            if path.is_file():
                # Get relative path for cleaner reading
                file_list.append(str(path.relative_to(SCRIPT_DIR)))
    
    return sorted(file_list)

# ==============================================================================
# LOGIC: DATABASE DISCOVERY
# ==============================================================================
def get_db_report(db_path):
    """Audits the DuckDB schema and row counts."""
    report_lines = []
    if not db_path.exists():
        return ["Database file not found."]

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        tables_df = con.execute("SHOW TABLES").df()
        
        if tables_df.empty:
            return ["No tables found in database."]

        table_names = tables_df['name'].tolist()
        
        for table in table_names:
            report_lines.append(f"\n[TABLE: {table}]")
            
            # Row Count
            res = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            count = res[0] if res else 0
            report_lines.append(f"Rows: {count:,}")
            
            # Schema
            report_lines.append("Columns:")
            schema = con.execute(f"DESCRIBE {table}").df()
            for _, col in schema.iterrows():
                report_lines.append(f"  - {col['column_name']:<20} ({col['column_type']})")
        
        con.close()
    except Exception as e:
        report_lines.append(f"Error auditing database: {str(e)}")
    
    return report_lines

# ==============================================================================
# MAIN PROTOCOL
# ==============================================================================
def run_master_audit():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / "master_system_report.txt"
    
    print(f"🚀 INITIATING MASTER FORENSIC AUDIT...")
    
    with open(report_file, 'w', encoding='utf-8') as f:
        # Header
        f.write("="*80 + "\n")
        f.write(f"MAGITEK MASTER SYSTEM REPORT\n")
        f.write(f"GENERATED: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*80 + "\n\n")

        # Section 1: File Structure
        f.write("PART 1: FILE SYSTEM STRUCTURE\n")
        f.write("-" * 30 + "\n")
        files = get_file_structure()
        for file in files:
            f.write(f"{file}\n")
        f.write("\n")

        # Section 2: Database Schema
        f.write("PART 2: DATABASE SCHEMA & METRICS\n")
        f.write("-" * 30 + "\n")
        f.write(f"Source: {config.DB_FILE.name}\n")
        db_lines = get_db_report(config.DB_FILE)
        for line in db_lines:
            f.write(f"{line}\n")
        
        # Section 3: Simulator Session Snapshot (Bonus)
        session_file = SCRIPT_DIR / "data" / "sim_session.json"
        if session_file.exists():
            f.write("\nPART 3: ACTIVE SIM SESSION\n")
            f.write("-" * 30 + "\n")
            f.write(session_file.read_text())

    print(f"✅ AUDIT COMPLETE.")
    print(f"📂 MASTER REPORT: {report_file.absolute()}")

if __name__ == "__main__":
    run_master_audit()