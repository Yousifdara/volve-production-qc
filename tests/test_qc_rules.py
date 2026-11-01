"""
Tests for qc_rules.py.  Run from the project folder with:   python -m pytest -v

Each test builds a TINY fake table where we already know the right answer,
runs one rule, and checks the rule gives that answer.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # find qc_rules.py
import qc_rules as qc


def make(rows):
    """Build a small test table from a list of dictionaries."""
    df = pd.DataFrame(rows)
    df["prod_date"] = pd.to_datetime(df["prod_date"])
    return df


def test_duplicate_rows_finds_the_second_copy_only():
    df = make([
        {"well": "A", "prod_date": "2020-01-01"},
        {"well": "A", "prod_date": "2020-01-01"},   # duplicate
        {"well": "B", "prod_date": "2020-01-01"},   # same date, other well: fine
    ])
    assert qc.duplicate_rows(df).tolist() == [False, True, False]


def test_negative_volume_flags_any_negative_column():
    df = make([
        {"well": "A", "prod_date": "2020-01-01", "oil_vol": 10, "gas_vol": 5, "water_vol": -1, "water_inj_vol": 0},
        {"well": "A", "prod_date": "2020-01-02", "oil_vol": 10, "gas_vol": 5, "water_vol": 0, "water_inj_vol": 0},
    ])
    assert qc.negative_volume(df).tolist() == [True, False]


def test_sentinel_zero_pressure_only_when_producing():
    df = make([
        {"well": "A", "prod_date": "2020-01-01", "oil_vol": 500, "downhole_press": 0},    # fake zero
        {"well": "A", "prod_date": "2020-01-02", "oil_vol": 500, "downhole_press": 250},  # real reading
        {"well": "A", "prod_date": "2020-01-03", "oil_vol": 0,   "downhole_press": 0},    # shut in: not flagged
    ])
    assert qc.sentinel_zero_pressure(df).tolist() == [True, False, False]


def test_clock_change_day_is_last_sunday_of_october():
    dates = pd.Series(["2014-10-26",   # last Sunday of Oct 2014  -> True
                       "2014-10-19",   # a Sunday, but not the last -> False
                       "2014-10-27",   # the Monday after           -> False
                       "2014-03-30"])  # last Sunday of MARCH       -> False
    assert qc.clock_change_day(dates).tolist() == [True, False, False, False]


def test_25_hours_is_valid_only_on_clock_change_day():
    df = make([
        {"well": "A", "prod_date": "2014-10-26", "on_stream_hrs": 25.0},   # clock change: valid
        {"well": "A", "prod_date": "2014-06-15", "on_stream_hrs": 25.0},   # normal day: impossible
        {"well": "A", "prod_date": "2014-10-26", "on_stream_hrs": 26.0},   # 26 h never valid
        {"well": "A", "prod_date": "2014-06-16", "on_stream_hrs": 24.0},   # normal full day: fine
        {"well": "A", "prod_date": "2014-06-17", "on_stream_hrs": -1.0},   # negative: impossible
    ])
    assert qc.valid_25h_day(df).tolist() == [True, False, False, False, False]
    assert qc.impossible_hours(df).tolist() == [False, True, True, False, True]


def test_oil_with_zero_hours_is_flagged():
    df = make([
        {"well": "A", "prod_date": "2020-01-01", "oil_vol": 1000, "on_stream_hrs": 0},
        {"well": "A", "prod_date": "2020-01-02", "oil_vol": 1000, "on_stream_hrs": 24},
        {"well": "A", "prod_date": "2020-01-03", "oil_vol": 0,    "on_stream_hrs": 0},
    ])
    assert qc.oil_with_zero_hours(df).tolist() == [True, False, False]


def test_missing_days_lists_the_gap_per_well():
    df = make([
        {"well": "A", "prod_date": "2020-01-01"},
        {"well": "A", "prod_date": "2020-01-04"},   # 2nd and 3rd missing
        {"well": "B", "prod_date": "2020-01-01"},
        {"well": "B", "prod_date": "2020-01-02"},   # no gap
    ])
    gaps = qc.missing_days(df)
    assert len(gaps) == 2
    assert set(gaps["well"]) == {"A"}
    assert gaps["prod_date"].dt.strftime("%Y-%m-%d").tolist() == ["2020-01-02", "2020-01-03"]


def test_rules_do_not_change_the_input():
    df = make([{"well": "A", "prod_date": "2020-01-01", "oil_vol": 500, "downhole_press": 0}])
    before = df.copy()
    qc.sentinel_zero_pressure(df)
    pd.testing.assert_frame_equal(df, before)