import duckdb
from src.utils import config
from src.utils.logger import get_logger

log = get_logger("SetupDB")

def initialize_database():
    log.info(f"🔌 Connecting to Vault: {config.DB_FILE}")
    con = duckdb.connect(str(config.DB_FILE))
    
    # 1. INDICES (SPX/VIX)
    log.info(f"🔨 Initializing: {config.TBL_INDICES}")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_INDICES}")
    con.execute(f"""
    CREATE TABLE {config.TBL_INDICES} (
        datetime_utc TIMESTAMP NOT NULL,
        ticker VARCHAR NOT NULL,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
        PRIMARY KEY (datetime_utc, ticker)
    )""")
    
    # 2. FUTURES (ES)
    log.info(f"🔨 Initializing: {config.TBL_FUTURES}")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_FUTURES}")
    con.execute(f"""
    CREATE TABLE {config.TBL_FUTURES} (
        datetime_utc TIMESTAMP NOT NULL,
        ticker VARCHAR NOT NULL,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
        PRIMARY KEY (datetime_utc, ticker)
    )""")

    # 3. OPTIONS (XSP)
    log.info(f"🔨 Initializing: {config.TBL_OPTIONS}")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_OPTIONS}")
    con.execute(f"""
    CREATE TABLE {config.TBL_OPTIONS} (
        datetime_utc TIMESTAMP NOT NULL,
        ticker VARCHAR NOT NULL,
        expiration DATE, strike DOUBLE, type VARCHAR,
        open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT,
        iv DOUBLE, delta DOUBLE, gamma DOUBLE, vega DOUBLE, theta DOUBLE,
        PRIMARY KEY (datetime_utc, ticker)
    )""")

    # 4. RISK FREE RATE (IRX)
    log.info(f"🔨 Initializing: {config.TBL_IRX}")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_IRX}")
    con.execute(f"""
    CREATE TABLE {config.TBL_IRX} (
        date DATE NOT NULL PRIMARY KEY,
        rate DOUBLE
    )""")

    # 5. MANIFEST
    log.info(f"🔨 Initializing: {config.TBL_MANIFEST}")
    con.execute(f"DROP TABLE IF EXISTS {config.TBL_MANIFEST}")
    con.execute(f"""
    CREATE TABLE {config.TBL_MANIFEST} (
        entry_timestamp_utc BIGINT NOT NULL PRIMARY KEY,
        date DATE,
        signal_type VARCHAR,
        vix_close DOUBLE, vix_rsi DOUBLE, vix_macd DOUBLE,
        xsp_price DOUBLE
    )""")
    
    # Verify
    tables = con.execute("SHOW TABLES").fetchall()
    table_names = [t[0] for t in tables]
    log.info(f"✅ Database Initialized. Tables: {table_names}")
    con.close()

if __name__ == "__main__":
    print("⚠️  WARNING: This will WIPE the database and start fresh.")
    if input("Type 'yes' to confirm: ").lower() == 'yes':
        initialize_database()