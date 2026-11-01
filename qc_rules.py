"""
QC RULES - the data quality checks as small, testable functions.

Each function takes a DataFrame and returns a True/False mask (one value per row),
except missing_days(), which returns a table of the missing dates.
Nothing here changes the data. Deciding what to DO with a flagged row is done in qc.py.
"""
import pandas as pd

VOLUME_COLS = ["oil_vol", "gas_vol", "water_vol", "water_inj_vol"]


def duplicate_rows(df):
    """True for the 2nd, 3rd... copy of the same well + date."""
    return df.duplicated(subset=["well", "prod_date"], keep="first")


def negative_volume(df, cols=VOLUME_COLS):
    """True where ANY volume column is below zero (physically impossible)."""
    return (df[cols] < 0).any(axis=1)


def sentinel_zero_pressure(df):
    """True where the well produced oil but downhole pressure reads exactly 0.
    A flowing well cannot have zero bottom-hole pressure: the 0 is a failed gauge."""
    return (df["oil_vol"] > 0) & (df["downhole_press"] == 0)


def clock_change_day(dates):
    """True for the last Sunday of October (Norway turns clocks back -> 25-hour day)."""
    dates = pd.to_datetime(dates)
    return (dates.dt.month == 10) & (dates.dt.dayofweek == 6) & (dates.dt.day >= 25)


def valid_25h_day(df):
    """More than 24 h on stream, but on a clock-change day and not above 25 h: REAL."""
    hrs = df["on_stream_hrs"]
    return (hrs > 24) & (hrs <= 25) & clock_change_day(df["prod_date"])


def impossible_hours(df):
    """Negative hours, or more than 24 h on a normal day: an ERROR."""
    hrs = df["on_stream_hrs"]
    return ((hrs > 24) & ~valid_25h_day(df)) | (hrs < 0)


def oil_with_zero_hours(df):
    """Oil reported while the well was on stream 0 hours: a contradiction to review."""
    return (df["oil_vol"] > 0) & (df["on_stream_hrs"] == 0)


def missing_days(df):
    """Every calendar day between a well's first and last date that has no row."""
    parts = []
    for well, g in df.groupby("well"):
        dates = pd.to_datetime(g["prod_date"])
        all_days = pd.date_range(dates.min(), dates.max(), freq="D")
        missing = all_days.difference(dates)
        parts.append(pd.DataFrame({"prod_date": missing, "well": well}))
    if not parts:
        return pd.DataFrame(columns=["prod_date", "well"])
    return pd.concat(parts, ignore_index=True)