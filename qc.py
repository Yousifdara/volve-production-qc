# qc.py - QC PIPELINE: raw Excel -> checked, flagged, clean CSV
# Uses the tested rules in qc_rules.py.  Run:   python qc.py
# Outputs: data/volve_daily_clean.csv, reports/qc_issues.csv, reports/qc_summary.txt
# Principle: never invent data. Remove what is impossible, keep what is proven real,
# flag what cannot be decided.
from pathlib import Path

import pandas as pd

import qc_rules as qc

PROJECT = Path(__file__).resolve().parent
RAW_FILE = PROJECT / "data" / "Volve_production_data.xlsx"
(PROJECT / "reports").mkdir(exist_ok=True)

COLUMNS = {
    "DATEPRD": "prod_date", "WELL_BORE_CODE": "well", "WELL_TYPE": "well_type",
    "FLOW_KIND": "flow_kind", "ON_STREAM_HRS": "on_stream_hrs",
    "AVG_DOWNHOLE_PRESSURE": "downhole_press", "AVG_CHOKE_SIZE_P": "choke_pct",
    "AVG_WHP_P": "whp", "BORE_OIL_VOL": "oil_vol", "BORE_GAS_VOL": "gas_vol",
    "BORE_WAT_VOL": "water_vol", "BORE_WI_VOL": "water_inj_vol",
}

# ---- Load ----
raw = pd.read_excel(RAW_FILE, sheet_name="Daily Production Data")
df = raw[list(COLUMNS)].rename(columns=COLUMNS)
df["prod_date"] = pd.to_datetime(df["prod_date"])
df = df.sort_values(["well", "prod_date"]).reset_index(drop=True)
rows_in = len(df)
issues = []


def record(mask, column, check, action):
    """Add the rows where mask is True to the issues list."""
    cols = ["prod_date", "well"] + ([column] if column else [])
    part = df.loc[mask, cols].copy()
    part["value"] = part.pop(column) if column else None
    issues.append(part.assign(column=column, check=check, action=action))
    return int(mask.sum())


# ---- 1. Duplicates: removed ----
dup = qc.duplicate_rows(df)
n_dup = record(dup, None, "Duplicate well+date", "Removed (kept first)")
df = df[~dup].copy()

# ---- 2. Negative volumes: set to NaN ----
neg_any = qc.negative_volume(df)
for col in qc.VOLUME_COLS:
    mask = df[col] < 0
    record(mask, col, "Negative volume", "Set to NaN")
    df.loc[mask, col] = pd.NA

# ---- 3. Sentinel zero pressure: set to NaN ----
sentinel = qc.sentinel_zero_pressure(df)
n_sentinel = record(sentinel, "downhole_press", "Zero pressure while producing",
                    "Set to NaN (gauge failure)")
df.loc[sentinel, "downhole_press"] = pd.NA

# ---- 4. On-stream hours: 25 h kept, impossible set to NaN ----
valid_25 = qc.valid_25h_day(df)
bad_hrs = qc.impossible_hours(df)
n_25 = record(valid_25, "on_stream_hrs", "Over 24 h on clock-change day", "Kept - valid (25-hour day)")
n_bad = record(bad_hrs, "on_stream_hrs", "Impossible on-stream hours", "Set to NaN")
df.loc[bad_hrs, "on_stream_hrs"] = pd.NA

# ---- 5. Oil with zero hours: flagged only ----
oil_0h = qc.oil_with_zero_hours(df)
n_oil0 = record(oil_0h, "oil_vol", "Oil reported with 0 on-stream hours", "Flagged only - needs review")

# ---- 6. Missing days: listed only ----
gaps = qc.missing_days(df)
issues.append(gaps.assign(column=None, value=None, check="Missing day",
                          action="Listed only - no row created"))

# ---- qc_flag column ----
flags = {"NEGATIVE_VOLUME_REMOVED": neg_any, "PRESS_SENTINEL_REMOVED": sentinel,
         "25H_DAY": valid_25, "BAD_HOURS_REMOVED": bad_hrs, "OIL_WITH_0_HRS": oil_0h}
df["qc_flag"] = ""
for flag, mask in flags.items():
    df.loc[mask, "qc_flag"] += flag + ";"
df["qc_flag"] = df["qc_flag"].str.rstrip(";").replace("", "OK")

# ---- Save ----
out = df.copy()
out["prod_date"] = out["prod_date"].dt.strftime("%Y-%m-%d")
out.to_csv(PROJECT / "data" / "volve_daily_clean.csv", index=False)

issues_df = pd.concat([i for i in issues if len(i) > 0], ignore_index=True)
issues_df = issues_df[["prod_date", "well", "check", "column", "value", "action"]]
issues_df["prod_date"] = pd.to_datetime(issues_df["prod_date"]).dt.date
issues_df.to_csv(PROJECT / "reports" / "qc_issues.csv", index=False)

rows_out = len(df)
expected = rows_in - n_dup
status = "PASS" if rows_out == expected else "FAIL"
summary = f"""VOLVE DAILY PRODUCTION - QC SUMMARY
====================================
Rows in        : {rows_in:,}
Rows out       : {rows_out:,}
Wells          : {df['well'].nunique()}
Date range     : {df['prod_date'].min().date()} to {df['prod_date'].max().date()}

CHECK                                  FOUND   ACTION
Duplicate well+date rows             {n_dup:>6}   removed
Negative volumes                     {int(neg_any.sum()):>6}   set to NaN
Zero pressure while producing        {n_sentinel:>6}   set to NaN
Over 24 h on clock-change day        {n_25:>6}   kept (valid)
Impossible on-stream hours           {n_bad:>6}   set to NaN
Oil reported with 0 hours            {n_oil0:>6}   flagged for review
Missing calendar days                {len(gaps):>6}   listed, not filled

Reconciliation : expected {expected:,} rows, got {rows_out:,} -> {status}
"""
(PROJECT / "reports" / "qc_summary.txt").write_text(summary, encoding="utf-8")
print(summary)