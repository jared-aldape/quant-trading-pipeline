import duckdb
import sys
from pathlib import Path

# Path Constitution
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT_DIR))

from src.utils import config

def clean_manifest():
    print(f"🧹 Cleaning Manifest Table in {config.DB_FILE}...")
    
    if not config.DB_FILE.exists():
        print("❌ DB File not found.")
        return

    con = duckdb.connect(str(config.DB_FILE))
    
    try:
        # Check count before
        try:
            count_before = con.execute(f"SELECT COUNT(*) FROM {config.TBL_MANIFEST}").fetchone()[0]
            print(f"📉 Found {count_before} old signals.")
        except:
            print("⚠️ Table might not exist yet.")

        # DELETE COMMAND
        con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
        
        print("✅ Manifest table dropped. The scanner will rebuild it fresh.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        
    con.close()

if __name__ == "__main__":
    clean_manifest()