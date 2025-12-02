import sys
import duckdb
import csv
import pandas as pd
from pathlib import Path
import os

# ==============================================================================
# PATH CONSTITUTION
# ==============================================================================
# Assumes this script is in the ROOT directory (QUANT-OS/)
ROOT_DIR = Path(__file__).resolve().parents[1]  # Go up 2 levels
sys.path.append(str(ROOT_DIR))

from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SnapshotGenerator")

def generate_gem_snapshot():
    """
    Generates a flattened CSV containing Table Names, Column Definitions,
    Data Types, and a Sample Value for every field in the database.
    """
    db_path = config.DB_FILE
    
    # OUTPUT: Save to 'reports' folder instead of root
    output_file = config.REPORTS_DIR / "gem_db_snapshot.csv"
    
    log.info(f"📸 Connecting to Vault: {db_path}")
    
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as e:
        log.error(f"Failed to connect to DB: {e}")
        return

    # 1. Get List of Tables
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]
    except Exception as e:
        log.error(f"Could not list tables: {e}")
        return

    log.info(f"Found {len(table_names)} tables: {table_names}")

    # 2. Build Snapshot
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # Header optimized for LLM understanding
        writer.writerow(['Table_Name', 'Column_Name', 'Data_Type', 'Sample_Value_Row1', 'Is_Nullable'])

        for table in table_names:
            log.info(f"Scanning {table}...")
            
            # Fetch Schema (Column Name, Type, Nullable, etc.)
            schema_info = con.execute(f"DESCRIBE {table}").fetchall()
            
            # Fetch 1 Row of Sample Data
            try:
                sample_df = con.execute(f"SELECT * FROM {table} LIMIT 1").df()
            except:
                sample_df = pd.DataFrame()

            for col in schema_info:
                col_name = col[0]
                col_type = col[1]
                is_null = col[2]
                
                # Extract sample value if it exists
                sample_val = "NO_DATA"
                if not sample_df.empty and col_name in sample_df.columns:
                    val = sample_df.iloc[0][col_name]
                    sample_val = str(val) if pd.notna(val) else "NULL"
                
                writer.writerow([table, col_name, col_type, sample_val, is_null])

    con.close()
    log.info(f"✅ Snapshot Complete. File saved to: {output_file}")
    log.info("Upload this CSV to your Custom Gem knowledge base.")

if __name__ == "__main__":
    generate_gem_snapshot()