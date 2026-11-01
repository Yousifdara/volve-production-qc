"""
STEP 6.1 - AUTOMATED EXCEL REPORT
Reads the clean data from SQL Server and writes a formatted Excel report.
Run it any time (e.g. every month) and a fresh, dated report appears in reports/.
"""
# %% STEP 6.1 - Automated Excel report
import os
from datetime import date
from pathlib import Path

import pandas as pd
import pyodbc
from dotenv import load_dotenv
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

PROJECT = Path(r"C:\VolveProject")
load_dotenv(PROJECT / ".env")
conn = pyodbc.connect(
    "DRIVER={" + os.getenv("SQL_DRIVER") + "};"
    "SERVER=" + os.getenv("SQL_SERVER") + ";"
    "DATABASE=" + os.getenv("SQL_DATABASE") + ";"
    "Trusted_Connection=yes;TrustServerCertificate=yes;"
)


def read_sql(query, *params):
    """Run a SELECT (with optional ? parameters) and return a pandas table."""
    cur = conn.cursor()
    cur.execute(query, *params)
    columns = [col[0] for col in cur.description]
    return pd.DataFrame.from_records(cur.fetchall(), columns=columns)


# ---------- 1. Get the numbers (calculated inside SQL Server) ----------
wells = read_sql("""
    SELECT well,
           MIN(CASE WHEN oil_vol > 0 THEN prod_date END)  AS first_oil,
           MAX(CASE WHEN oil_vol > 0 THEN prod_date END)  AS last_oil,
           SUM(CASE WHEN oil_vol > 0 THEN 1 ELSE 0 END)   AS producing_days,
           SUM(oil_vol)   AS cum_oil,
           MAX(oil_vol)   AS peak_daily_oil,
           SUM(water_vol) AS cum_water
    FROM daily_production_clean
    GROUP BY well
    HAVING SUM(oil_vol) > 0
    ORDER BY cum_oil DESC
""")

monthly = read_sql("""
    SELECT well,
           DATEFROMPARTS(YEAR(prod_date), MONTH(prod_date), 1) AS month,
           SUM(oil_vol)   AS oil,
           SUM(gas_vol)   AS gas,
           SUM(water_vol) AS water,
           SUM(on_stream_hrs) / 24.0 AS days_on
    FROM daily_production_clean
    GROUP BY well, DATEFROMPARTS(YEAR(prod_date), MONTH(prod_date), 1)
    HAVING SUM(oil_vol) > 0
    ORDER BY well, month
""")
monthly["water_cut_pct"] = 100 * monthly["water"] / (monthly["oil"] + monthly["water"])
monthly["oil_rate"] = monthly["oil"] / monthly["days_on"]

yearly = read_sql("""
    SELECT YEAR(prod_date) AS year,
           SUM(oil_vol)   AS oil,
           SUM(water_vol) AS water
    FROM daily_production_clean
    GROUP BY YEAR(prod_date)
    HAVING SUM(oil_vol) > 0
    ORDER BY year
""")
yearly["water_cut_pct"] = 100 * yearly["water"] / (yearly["oil"] + yearly["water"])

load_log = read_sql("SELECT load_id, load_time, rows_in_file, rows_loaded, "
                    "oil_in_file, oil_loaded, status FROM load_log ORDER BY load_id")
qc_log = pd.read_csv(PROJECT / "reports" / "qc_issues.csv")

print("Wells:", len(wells), "| Months:", len(monthly), "| Years:", len(yearly),
      "| QC lines:", len(qc_log), "| Loads:", len(load_log))

# ---------- 2. Write every table to its own sheet ----------
OUT = PROJECT / "reports" / f"Volve_production_report_{date.today():%Y-%m-%d}.xlsx"

with pd.ExcelWriter(OUT, engine="openpyxl") as xl:
    wells.to_excel(xl, sheet_name="Summary", index=False, startrow=4)
    yearly.to_excel(xl, sheet_name="Field by year", index=False)
    monthly.to_excel(xl, sheet_name="Monthly by well", index=False)
    qc_log.to_excel(xl, sheet_name="QC log", index=False)
    load_log.to_excel(xl, sheet_name="Load log", index=False)

    # Title lines at the top of the Summary sheet
    ws = xl.sheets["Summary"]
    ws["A1"] = "Volve field - production summary"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Generated {date.today():%d %b %Y} from SQL Server table daily_production_clean"
    ws["A3"] = (f"Total oil {wells['cum_oil'].sum():,.0f} Sm³ (assumed units) | "
                f"Latest load: {load_log['status'].iloc[-1]}")

    # ---------- 3. Make every sheet readable ----------
    HEADER_FILL = PatternFill("solid", fgColor="DCE6F2")
    NUMBER_FORMATS = {
        "cum_oil": "#,##0", "peak_daily_oil": "#,##0", "cum_water": "#,##0",
        "oil": "#,##0", "gas": "#,##0", "water": "#,##0",
        "days_on": "0.0", "water_cut_pct": "0.0", "oil_rate": "#,##0",
        "oil_in_file": "#,##0.00", "oil_loaded": "#,##0.00", "value": "#,##0.00",
        "first_oil": "yyyy-mm-dd", "last_oil": "yyyy-mm-dd", "month": "yyyy-mm",
        "prod_date": "yyyy-mm-dd", "load_time": "yyyy-mm-dd hh:mm",
    }

    for ws in xl.book.worksheets:
        header_row = 5 if ws.title == "Summary" else 1
        for cell in ws[header_row]:
            if cell.value is None:
                continue
            cell.font = Font(bold=True)
            cell.fill = HEADER_FILL
            fmt = NUMBER_FORMATS.get(cell.value)
            col = get_column_letter(cell.column)
            if fmt:
                for row in range(header_row + 1, ws.max_row + 1):
                    ws[f"{col}{row}"].number_format = fmt
            ws.column_dimensions[col].width = max(14, len(str(cell.value)) + 4)
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)   # header stays visible
        ws.auto_filter.ref = (f"A{header_row}:"
                              f"{get_column_letter(ws.max_column)}{ws.max_row}")

print("Report saved:", OUT)