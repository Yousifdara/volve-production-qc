# %% STEP 4.1 - Connect to SQL Server
import os
import pyodbc
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

PROJECT = Path(r"C:\VolveProject")
load_dotenv(PROJECT / ".env")          # read the settings file

conn_str = (
    "DRIVER={" + os.getenv("SQL_DRIVER") + "};"
    "SERVER=" + os.getenv("SQL_SERVER") + ";"
    "DATABASE=" + os.getenv("SQL_DATABASE") + ";"
    "Trusted_Connection=yes;"          # use your Windows login
    "TrustServerCertificate=yes;"      # same as the tick box in SSMS
)

conn = pyodbc.connect(conn_str)        # open the connection
cur = conn.cursor()                    # the "cursor" sends SQL and reads results

cur.execute("SELECT DB_NAME(), COUNT(*) FROM daily_production")
print("Connected to:", cur.fetchone())
# %% STEP 4.2 - Create the clean table and the load log

# Start fresh every run, so the script can be run again safely
cur.execute("DROP TABLE IF EXISTS daily_production_clean")

cur.execute("""
CREATE TABLE daily_production_clean (
    prod_date      DATE         NOT NULL,
    well           VARCHAR(20)  NOT NULL,
    well_type      VARCHAR(5),
    flow_kind      VARCHAR(15),
    on_stream_hrs  FLOAT,
    downhole_press FLOAT,
    choke_pct      FLOAT,
    whp            FLOAT,
    oil_vol        FLOAT,
    gas_vol        FLOAT,
    water_vol      FLOAT,
    water_inj_vol  FLOAT,
    qc_flag        VARCHAR(60),
    CONSTRAINT pk_daily_clean PRIMARY KEY (well, prod_date)
)
""")

# The load log keeps a record of EVERY load. It is created once, never dropped.
cur.execute("""
IF OBJECT_ID('load_log') IS NULL
CREATE TABLE load_log (
    load_id      INT IDENTITY(1,1) PRIMARY KEY,
    load_time    DATETIME2 DEFAULT SYSDATETIME(),
    source_file  VARCHAR(200),
    rows_in_file INT,
    rows_loaded  INT,
    oil_in_file  FLOAT,
    oil_loaded   FLOAT,
    status       VARCHAR(10)
)
""")

conn.commit()      # save the changes permanently
print("Tables ready.")

cur.execute("SELECT name FROM sys.tables ORDER BY name")
print("Tables in the database:", [row[0] for row in cur.fetchall()])

# %% STEP 4.3 - Load the clean data with a parameterized INSERT
CLEAN_FILE = PROJECT / "data" / "volve_daily_clean.csv"

clean = pd.read_csv(CLEAN_FILE, parse_dates=["prod_date"])
clean["prod_date"] = clean["prod_date"].dt.date
print("Rows in file:", len(clean))

COLS = ["prod_date", "well", "well_type", "flow_kind", "on_stream_hrs",
        "downhole_press", "choke_pct", "whp", "oil_vol", "gas_vol",
        "water_vol", "water_inj_vol", "qc_flag"]
clean = clean[COLS]

# pandas writes empty values as NaN. SQL Server needs None (= NULL).
clean = clean.astype(object).where(clean.notna(), None)

# Turn the table into a list of rows (one tuple per row)
rows = list(clean.itertuples(index=False, name=None))
print("First row:", rows[0])

# The SQL has 13 question marks: one placeholder per column
sql = (f"INSERT INTO daily_production_clean ({', '.join(COLS)}) "
       f"VALUES ({', '.join('?' * len(COLS))})")
print(sql)

cur.fast_executemany = True      # send rows in large batches (much faster)
cur.executemany(sql, rows)       # run the INSERT once per row
conn.commit()
print("Loaded.")

# A parameterized SELECT, the same idea used for reading
cur.execute("SELECT COUNT(*) FROM daily_production_clean WHERE well = ?",
            "NO 15/9-F-12 H")
print("F-12 H rows in SQL:", cur.fetchone()[0])

# %% STEP 4.4 - Reconciliation and load log

# --- What the FILE says ---
file_rows = len(clean)
file_oil = pd.to_numeric(clean["oil_vol"]).sum()

# --- What SQL Server says ---
cur.execute("SELECT COUNT(*), SUM(oil_vol) FROM daily_production_clean")
sql_rows, sql_oil = cur.fetchone()

# Check 1: row count
rows_ok = file_rows == sql_rows
# Check 2: total oil (allow a tiny rounding difference)
oil_ok = abs(file_oil - sql_oil) < 0.01

print(f"Rows : file {file_rows:,} | SQL {sql_rows:,} -> {'OK' if rows_ok else 'MISMATCH'}")
print(f"Oil  : file {file_oil:,.2f} | SQL {sql_oil:,.2f} -> {'OK' if oil_ok else 'MISMATCH'}")

# Check 3: row count PER WELL
file_by_well = clean.groupby("well").size()
cur.execute("SELECT well, COUNT(*) FROM daily_production_clean GROUP BY well")
sql_by_well = pd.Series({well: n for well, n in cur.fetchall()})

compare = pd.DataFrame({"file": file_by_well, "sql": sql_by_well})
compare["match"] = compare["file"] == compare["sql"]
print(compare)

status = "PASS" if rows_ok and oil_ok and compare["match"].all() else "FAIL"
print("Load status:", status)

# --- Write one line to the load log (parameterized again) ---
cur.execute("""
    INSERT INTO load_log (source_file, rows_in_file, rows_loaded,
                          oil_in_file, oil_loaded, status)
    VALUES (?, ?, ?, ?, ?, ?)
""", CLEAN_FILE.name, file_rows, sql_rows, float(file_oil), float(sql_oil), status)
conn.commit()

cur.execute("SELECT TOP 5 load_id, load_time, rows_loaded, status "
            "FROM load_log ORDER BY load_id DESC")
for row in cur.fetchall():
    print(row)