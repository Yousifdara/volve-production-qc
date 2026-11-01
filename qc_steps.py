 # %% STEP 3.1 - Load and look
import pandas as pd
from pathlib import Path

PROJECT = Path(r"C:\VolveProject")
RAW_FILE = PROJECT / "data" / "Volve_production_data.xlsx"

# Read the daily sheet of the Excel file
raw = pd.read_excel(RAW_FILE, sheet_name="Daily Production Data")
print("Raw shape:", raw.shape)

# Keep 12 columns and give them short names (same as the SQL table)
COLUMNS = {
    "DATEPRD": "prod_date",
    "WELL_BORE_CODE": "well",
    "WELL_TYPE": "well_type",
    "FLOW_KIND": "flow_kind",
    "ON_STREAM_HRS": "on_stream_hrs",
    "AVG_DOWNHOLE_PRESSURE": "downhole_press",
    "AVG_CHOKE_SIZE_P": "choke_pct",
    "AVG_WHP_P": "whp",
    "BORE_OIL_VOL": "oil_vol",
    "BORE_GAS_VOL": "gas_vol",
    "BORE_WAT_VOL": "water_vol",
    "BORE_WI_VOL": "water_inj_vol",
}
df = raw[list(COLUMNS)].rename(columns=COLUMNS)

# Sort by well, then date
df = df.sort_values(["well", "prod_date"]).reset_index(drop=True)

print("Clean shape:", df.shape)
print(df.head())
print(df.dtypes)

# %% STEP 3.2 - Duplicates
rows_in = len(df)     # remember the starting row count
issues = []           # every problem we find will be added here

# A "mask" is a True/False answer for every row
dup_mask = df.duplicated(subset=["well", "prod_date"], keep="first")
print("Duplicate well+date rows:", dup_mask.sum())

# Record the duplicates (if any) in the issues list
issues.append(
    df.loc[dup_mask, ["prod_date", "well"]]
      .assign(check="Duplicate well+date", action="Removed")
)

# Keep only the rows that are NOT duplicates
df = df[~dup_mask].copy()
print("Rows before:", rows_in, "| Rows after:", len(df))

# --- Prove the check works, using a tiny fake table ---
test = pd.DataFrame({
    "well": ["A", "A", "B"],
    "prod_date": ["2020-01-01", "2020-01-01", "2020-01-01"],
})
print("Fake table duplicates found:",
      test.duplicated(subset=["well", "prod_date"]).sum(), "(should be 1)")

# %% STEP 3.3 - Negative volumes
VOLUME_COLS = ["oil_vol", "gas_vol", "water_vol", "water_inj_vol"]

# 1. Find rows with ANY negative volume, and show them BEFORE fixing
neg_any = (df[VOLUME_COLS] < 0).any(axis=1)
print("Rows with a negative volume:", neg_any.sum())
print(df.loc[neg_any, ["prod_date", "well", "oil_vol", "water_vol"]])

# 2. Check each volume column, record the problem, then fix it
for col in VOLUME_COLS:
    mask = df[col] < 0
    print(f"{col}: {mask.sum()} negative")

    issues.append(
        df.loc[mask, ["prod_date", "well", col]]
          .rename(columns={col: "value"})
          .assign(column=col, check="Negative volume", action="Set to NaN")
    )

    df.loc[mask, col] = pd.NA      # the fix: make it "unknown"

# 3. Show the same rows AFTER fixing, and prove none are left
print(df.loc[neg_any, ["prod_date", "well", "oil_vol", "water_vol"]])
print("Negatives left:", (df[VOLUME_COLS] < 0).sum().sum(), "(should be 0)")

# %% STEP 3.4 - Sentinel zero pressure
producing  = df["oil_vol"] > 0
zero_press = df["downhole_press"] == 0
sentinel_mask = producing & zero_press      # & means AND

print("Producing days:", producing.sum())
print("Zero pressure while producing:", sentinel_mask.sum())
print(df.loc[sentinel_mask].groupby("well").size())

# When did F-12 H's gauge stop working?
f12 = df["well"] == "NO 15/9-F-12 H"
bad_days = df.loc[sentinel_mask & f12, "prod_date"]
good_days = df.loc[producing & f12 & (df["downhole_press"] > 0), "prod_date"]
print("F-12 H last real reading:", good_days.max().date())
print("F-12 H fake zeros from:", bad_days.min().date(), "to", bad_days.max().date())

# Why it matters: average pressure WITH the fake zeros
avg_wrong = df.loc[producing & f12, "downhole_press"].mean()

# Record and fix
issues.append(
    df.loc[sentinel_mask, ["prod_date", "well", "downhole_press"]]
      .rename(columns={"downhole_press": "value"})
      .assign(column="downhole_press",
              check="Zero pressure while producing",
              action="Set to NaN (gauge failure)")
)
df.loc[sentinel_mask, "downhole_press"] = pd.NA

# Average pressure WITHOUT the fake zeros
avg_right = df.loc[producing & f12, "downhole_press"].mean()
print(f"F-12 H average pressure with fake zeros:    {avg_wrong:.1f}")
print(f"F-12 H average pressure without fake zeros: {avg_right:.1f}")

print("Left:", (producing & (df["downhole_press"] == 0)).sum(), "(should be 0)")
# %% STEP 3.5 - On-stream hours

# A function: a reusable block of code with a name.
# It does exactly what the issues.append(...) blocks did before.
def record(mask, column, check, action):
    issues.append(
        df.loc[mask, ["prod_date", "well", column]]
          .rename(columns={column: "value"})
          .assign(column=column, check=check, action=action)
    )
    return mask.sum()

hrs = df["on_stream_hrs"]
d = df["prod_date"]

# --- A. More than 24 hours ---
over24 = hrs > 24
print("Days over 24 hours:", over24.sum())
print(df.loc[over24, "prod_date"].dt.date.value_counts().sort_index())

# Norway turns clocks back on the LAST SUNDAY OF OCTOBER -> that day has 25 h.
# dayofweek: Monday = 0 ... Sunday = 6
clock_change_day = (d.dt.month == 10) & (d.dt.dayofweek == 6) & (d.dt.day >= 25)

valid_25h  = over24 & clock_change_day & (hrs <= 25)
impossible = (over24 & ~valid_25h) | (hrs < 0)

print("Valid 25-hour days:", record(valid_25h, "on_stream_hrs",
      "Over 24 h on clock-change day", "Kept - valid"))
print("Impossible hours:", record(impossible, "on_stream_hrs",
      "Impossible on-stream hours", "Set to NaN"))
df.loc[impossible, "on_stream_hrs"] = pd.NA

# --- B. Oil reported but 0 hours on stream ---
oil_0h = (df["oil_vol"] > 0) & (df["on_stream_hrs"] == 0)
print("Oil with 0 hours:", record(oil_0h, "oil_vol",
      "Oil reported with 0 on-stream hours", "Flagged only - needs review"))
print(df.loc[oil_0h, ["prod_date", "well", "on_stream_hrs", "oil_vol"]])

# %% STEP 3.6 - Missing days
missing_list = []

for well, g in df.groupby("well"):
    # every calendar day from this well's first date to its last date
    all_days = pd.date_range(g["prod_date"].min(), g["prod_date"].max(), freq="D")
    # days in the calendar that are NOT in the data
    missing = all_days.difference(g["prod_date"])
    print(f"{well}: {len(missing)} missing days")
    missing_list.append(pd.DataFrame({"prod_date": missing, "well": well}))

missing_df = pd.concat(missing_list, ignore_index=True)
print("Total missing days:", len(missing_df))

# Are the SAME dates missing in several wells at once?
wells_per_day = missing_df.groupby("prod_date")["well"].nunique()
shared = wells_per_day[wells_per_day >= 2]
print("Dates missing in 2 or more wells at the same time:", len(shared))
print(shared.sort_values(ascending=False).head(5))

# Record them (listed only - we do NOT invent rows)
issues.append(
    missing_df.assign(column=None, value=None,
                      check="Missing day", action="Listed only - no row created")
)

# %% STEP 3.7 - QC flag column, save files, summary

# 1. Add a qc_flag column: which rows were touched, and why.
#    A row can have more than one problem, so flags are joined with ";"
flag_masks = {
    "NEGATIVE_VOLUME_REMOVED": neg_any,
    "PRESS_SENTINEL_REMOVED":  sentinel_mask,
    "25H_DAY":                 valid_25h,
    "BAD_HOURS_REMOVED":       impossible,
    "OIL_WITH_0_HRS":          oil_0h,
}
df["qc_flag"] = ""
for flag, mask in flag_masks.items():
    df.loc[mask, "qc_flag"] += flag + ";"
df["qc_flag"] = df["qc_flag"].str.rstrip(";").replace("", "OK")
print(df["qc_flag"].value_counts())

# 2. Combine all the issues into one table
issues_df = pd.concat([i for i in issues if len(i) > 0], ignore_index=True)
issues_df = issues_df[["prod_date", "well", "check", "column", "value", "action"]]
issues_df["prod_date"] = pd.to_datetime(issues_df["prod_date"]).dt.date
print(issues_df["check"].value_counts())

# 3. Save the files
(PROJECT / "reports").mkdir(exist_ok=True)
clean_out = df.copy()
clean_out["prod_date"] = clean_out["prod_date"].dt.strftime("%Y-%m-%d")
clean_out.to_csv(PROJECT / "data" / "volve_daily_clean.csv", index=False)
issues_df.to_csv(PROJECT / "reports" / "qc_issues.csv", index=False)

# 4. Reconciliation: no rows lost by accident
rows_out = len(df)
expected = rows_in - dup_mask.sum()
status = "PASS" if rows_out == expected else "FAIL"

summary = f"""VOLVE DAILY PRODUCTION - QC SUMMARY
====================================
Rows in        : {rows_in:,}
Rows out       : {rows_out:,}
Wells          : {df['well'].nunique()}
Date range     : {df['prod_date'].min().date()} to {df['prod_date'].max().date()}

CHECK                                  FOUND   ACTION
Duplicate well+date rows             {dup_mask.sum():>6}   removed
Negative volumes                     {neg_any.sum():>6}   set to NaN
Zero pressure while producing        {sentinel_mask.sum():>6}   set to NaN
Over 24 h on clock-change day        {valid_25h.sum():>6}   kept (valid)
Impossible on-stream hours           {impossible.sum():>6}   set to NaN
Oil reported with 0 hours            {oil_0h.sum():>6}   flagged for review
Missing calendar days                {len(missing_df):>6}   listed, not filled

Reconciliation : expected {expected:,} rows, got {rows_out:,} -> {status}
"""
(PROJECT / "reports" / "qc_summary.txt").write_text(summary, encoding="utf-8")
print(summary)
print("Saved: data/volve_daily_clean.csv, reports/qc_issues.csv, reports/qc_summary.txt")

