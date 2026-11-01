 # %% STEP 5.1 - Read the clean data from SQL Server
import os
import pyodbc
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

PROJECT = Path(r"C:\VolveProject")
load_dotenv(PROJECT / ".env")
conn = pyodbc.connect(
    "DRIVER={" + os.getenv("SQL_DRIVER") + "};"
    "SERVER=" + os.getenv("SQL_SERVER") + ";"
    "DATABASE=" + os.getenv("SQL_DATABASE") + ";"
    "Trusted_Connection=yes;TrustServerCertificate=yes;"
)
cur = conn.cursor()

cur.execute("SELECT * FROM daily_production_clean ORDER BY well, prod_date")
columns = [col[0] for col in cur.description]          # column names
df = pd.DataFrame.from_records(cur.fetchall(), columns=columns)
df["prod_date"] = pd.to_datetime(df["prod_date"])

print("Rows read from SQL:", len(df))
print(f"Total oil: {df['oil_vol'].sum():,.2f}")

# Show big numbers with commas and no decimals
pd.options.display.float_format = "{:,.0f}".format

# One summary line per well (only days that produced oil)
producing = df[df["oil_vol"] > 0]
summary = producing.groupby("well").agg(
    first_oil=("prod_date", "min"),
    last_oil=("prod_date", "max"),
    producing_days=("oil_vol", "size"),
    cum_oil=("oil_vol", "sum"),
    peak_daily_oil=("oil_vol", "max"),
)
summary["cum_water"] = df.groupby("well")["water_vol"].sum()
summary = summary.sort_values("cum_oil", ascending=False)
print(summary)


# %% STEP 5.2 - Monthly production and water cut
pd.set_option("display.width", 200)          # show all columns
pd.set_option("display.max_columns", 20)
pd.options.display.float_format = "{:,.1f}".format

# --- Monthly totals per well ---
monthly = (
    df.set_index("prod_date")
      .groupby("well")[["oil_vol", "gas_vol", "water_vol", "on_stream_hrs"]]
      .resample("MS").sum()          # MS = Month Start: one row per month
      .reset_index()
)
monthly = monthly[monthly["oil_vol"] > 0].copy()     # producing months only

monthly["water_cut_pct"] = 100 * monthly["water_vol"] / (monthly["oil_vol"] + monthly["water_vol"])
monthly["days_on"] = monthly["on_stream_hrs"] / 24
monthly["oil_rate"] = monthly["oil_vol"] / monthly["days_on"]    # oil per day on stream

print("Well-months with oil:", len(monthly))
print(monthly.head())

# --- Whole field, per year ---
yearly = df.groupby(df["prod_date"].dt.year)[["oil_vol", "water_vol"]].sum()
yearly = yearly[yearly["oil_vol"] > 0]
yearly["water_cut_pct"] = 100 * yearly["water_vol"] / (yearly["oil_vol"] + yearly["water_vol"])
print(yearly)

# --- Best month for the whole field ---
field_monthly = monthly.groupby("prod_date")["oil_vol"].sum()
print("Peak field month:", field_monthly.idxmax().date(),
      f"with {field_monthly.max():,.0f} oil")

# %% STEP 5.3 - Decline curve analysis (Arps) on F-14 H
import numpy as np
from scipy.optimize import curve_fit

WELL = "NO 15/9-F-14 H"
FIT_START = "2013-01-01"     # after water breakthrough: a steady decline period
TEST_START = "2015-07-01"    # last ~12 months are hidden from the fit

# 1. Prepare the data: one well, months with at least 10 producing days
w = monthly[(monthly["well"] == WELL) & (monthly["days_on"] >= 10)]
w = w[w["prod_date"] >= FIT_START].copy()
w["t"] = (w["prod_date"] - w["prod_date"].iloc[0]).dt.days / 30.4375   # months since start

train = w[w["prod_date"] < TEST_START]
test  = w[w["prod_date"] >= TEST_START]
print(f"Fit on {len(train)} months, test on {len(test)} months")

# 2. The two Arps models
def exponential(t, qi, D):
    return qi * np.exp(-D * t)

def hyperbolic(t, qi, D, b):
    return qi / (1 + b * D * t) ** (1 / b)

# 3. Fit both models to the TRAINING months only
p_exp, _ = curve_fit(exponential, train["t"], train["oil_rate"],
                     p0=[train["oil_rate"].iloc[0], 0.05])
p_hyp, _ = curve_fit(hyperbolic, train["t"], train["oil_rate"],
                     p0=[train["oil_rate"].iloc[0], 0.05, 0.5],
                     bounds=([0, 1e-4, 0.01], [1e5, 1, 2]))
print(f"Exponential: qi = {p_exp[0]:,.0f}  D = {p_exp[1]:.4f} per month")
print(f"Hyperbolic : qi = {p_hyp[0]:,.0f}  D = {p_hyp[1]:.4f}  b = {p_hyp[2]:.2f}")

# 4. How well does the exponential model fit, and how well does it PREDICT?
def r_squared(actual, predicted):
    return 1 - ((actual - predicted) ** 2).sum() / ((actual - actual.mean()) ** 2).sum()

fit_r2 = r_squared(train["oil_rate"], exponential(train["t"], *p_exp))
pred_rate = exponential(test["t"], *p_exp)
mape = (abs(test["oil_rate"] - pred_rate) / test["oil_rate"]).mean() * 100

actual_oil = (test["oil_rate"] * test["days_on"]).sum()
pred_oil   = (pred_rate * test["days_on"]).sum()
annual_decline = (1 - np.exp(-12 * p_exp[1])) * 100

print(f"R-squared on fit months       : {fit_r2:.3f}")
print(f"Average error on test months  : {mape:.1f} %")
print(f"Test-period oil  actual {actual_oil:,.0f} | predicted {pred_oil:,.0f} "
      f"({100 * (pred_oil - actual_oil) / actual_oil:+.1f} %)")
print(f"Annual decline rate           : {annual_decline:.0f} % per year")

# %% STEP 5.4 - Plotly charts
import plotly.graph_objects as go
import webbrowser

CHART_DIR = PROJECT / "reports" / "charts"
CHART_DIR.mkdir(parents=True, exist_ok=True)

# Fixed colours: each well keeps the SAME colour in every chart
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
WELLS = summary.index.tolist()                 # the 6 producers, biggest first
WELL_COLOR = dict(zip(WELLS, PALETTE))
GREY = "#52514e"

def short(well):
    """'NO 15/9-F-12 H' -> 'F-12 H'"""
    return well.replace("NO 15/9-", "")

def style(fig, title, y_title):
    """One common look for every chart."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=17)),
        template="plotly_white",
        paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
        font=dict(family="Arial", size=13, color="#0b0b0b"),
        hovermode="x unified",                  # hover shows every series at that date
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0),
        margin=dict(l=70, r=20, t=90, b=50),
        yaxis_title=y_title,
    )
    fig.update_xaxes(showgrid=False, linecolor="#c3c2b7")
    fig.update_yaxes(gridcolor="#ebeae6", zeroline=False)
    return fig

# ---------- Chart 1: field oil and water per month ----------
field = monthly.groupby("prod_date")[["oil_vol", "water_vol"]].sum().reset_index()
fig1 = go.Figure()
fig1.add_trace(go.Scatter(mode="lines", x=field["prod_date"], y=field["water_vol"], name="Water",
                          line=dict(color=PALETTE[0], width=2)))
fig1.add_trace(go.Scatter(mode="lines", x=field["prod_date"], y=field["oil_vol"], name="Oil",
                          line=dict(color=PALETTE[1], width=2)))
fig1.update_traces(hovertemplate="%{y:,.0f}")
style(fig1, "Field production per month: water overtook oil in 2010",
      "Volume per month (Sm³, assumed)")

# ---------- Chart 2: field water cut ----------
field["water_cut_pct"] = 100 * field["water_vol"] / (field["oil_vol"] + field["water_vol"])
fig2 = go.Figure(go.Scatter(mode="lines", x=field["prod_date"], y=field["water_cut_pct"], name="Water cut",
                            line=dict(color=PALETTE[0], width=2),
                            hovertemplate="%{y:.1f} %"))
style(fig2, "Field water cut: from almost 0 % in 2008 to over 80 % by 2013",
      "Water cut (%)")
fig2.update_yaxes(range=[0, 100])

# ---------- Chart 3: oil rate per well ----------
fig3 = go.Figure()
for well in WELLS:
    g = monthly[monthly["well"] == well]
    fig3.add_trace(go.Scatter(mode="lines", x=g["prod_date"], y=g["oil_rate"], name=short(well),
                              line=dict(color=WELL_COLOR[well], width=2),
                              hovertemplate="%{y:,.0f}"))
style(fig3, "Oil rate per well (per producing day)",
      "Oil rate (Sm³ per producing day)")

# ---------- Chart 4: decline curve, F-14 H ----------
t_line = np.linspace(0, w["t"].max(), 200)
d_line = w["prod_date"].iloc[0] + pd.to_timedelta(t_line * 30.4375, unit="D")
fig4 = go.Figure()
fig4.add_trace(go.Scatter(x=train["prod_date"], y=train["oil_rate"], mode="markers",
                          name="Actual - fit months",
                          marker=dict(color=PALETTE[0], size=8)))
fig4.add_trace(go.Scatter(x=test["prod_date"], y=test["oil_rate"], mode="markers",
                          name="Actual - hidden test months",
                          marker=dict(color=PALETTE[1], size=8)))
fig4.add_trace(go.Scatter(x=d_line, y=exponential(t_line, *p_exp), mode="lines",
                          name=f"Arps exponential ({annual_decline:.0f} %/yr decline)",
                          line=dict(color=GREY, width=2, dash="dash")))
fig4.add_vline(x=pd.Timestamp(TEST_START), line_dash="dot", line_color="#8a8984")
fig4.update_traces(hovertemplate="%{y:,.0f}")
style(fig4, f"F-14 H decline curve: R² {fit_r2:.3f} on fit, {mape:.0f} % error on hidden months",
      "Oil rate (Sm³ per producing day)")

# ---------- Chart 5: QC proof, F-12 H pressure raw vs clean ----------
cur.execute("SELECT prod_date, downhole_press FROM daily_production "
            "WHERE well = ? ORDER BY prod_date", "NO 15/9-F-12 H")
raw_f12 = pd.DataFrame.from_records(cur.fetchall(), columns=["prod_date", "downhole_press"])
raw_f12["prod_date"] = pd.to_datetime(raw_f12["prod_date"])
clean_f12 = df[df["well"] == "NO 15/9-F-12 H"]

fig5 = go.Figure()
fig5.add_trace(go.Scatter(mode="lines", x=raw_f12["prod_date"], y=raw_f12["downhole_press"],
                          name="Raw (gauge zeros included)",
                          line=dict(color=PALETTE[1], width=2)))
fig5.add_trace(go.Scatter(mode="lines", x=clean_f12["prod_date"], y=clean_f12["downhole_press"],
                          name="Clean (zeros treated as missing)",
                          line=dict(color=PALETTE[0], width=2)))
fig5.update_traces(hovertemplate="%{y:,.1f}")
style(fig5, "F-12 H downhole pressure: the gauge failed in Oct 2010 and logged zeros for 6 years",
      "Downhole pressure (units not stated)")

# ---------- Save every chart as its own HTML file ----------
charts = {
    "01_field_production.html": fig1,
    "02_water_cut.html": fig2,
    "03_oil_rate_per_well.html": fig3,
    "04_decline_curve_F14H.html": fig4,
    "05_qc_pressure_F12H.html": fig5,
}
for name, fig in charts.items():
    fig.write_html(CHART_DIR / name, include_plotlyjs="cdn")
    print("Saved:", CHART_DIR / name)

webbrowser.open((CHART_DIR / "05_qc_pressure_F12H.html").as_uri())   # open one to look at


# %% STEP 5.5 - One HTML dashboard page
import html
from datetime import date

DOCS = PROJECT / "docs"            # GitHub Pages can publish this folder later
DOCS.mkdir(exist_ok=True)

# ---- Numbers for the headline tiles ----
total_oil = df["oil_vol"].sum()
wc_2008 = yearly.loc[2008, "water_cut_pct"]
wc_2016 = yearly.loc[2016, "water_cut_pct"]
issues_csv = pd.read_csv(PROJECT / "reports" / "qc_issues.csv")
n_issue_lines = len(issues_csv)

cur.execute("SELECT TOP 1 load_time, rows_loaded, status FROM load_log ORDER BY load_id DESC")
load_time, rows_loaded, load_status = cur.fetchone()

tiles = [
    (f"{total_oil / 1e6:.2f} M", "Total oil, Sm³ (assumed units)"),
    (f"{wc_2008:.0f} % → {wc_2016:.0f} %", "Field water cut, 2008 → 2016"),
    (f"{annual_decline:.0f} %/yr", "F-14 H decline rate (Arps fit)"),
    (f"{n_issue_lines:,}", "QC issues found and logged"),
    (f"{rows_loaded:,} {load_status}", "Rows loaded to SQL Server"),
]
tiles_html = "".join(
    f'<div class="tile"><div class="num">{html.escape(n)}</div>'
    f'<div class="lbl">{html.escape(l)}</div></div>' for n, l in tiles
)

# ---- Tables (the same numbers, readable without hovering) ----
well_table = summary.copy()
well_table.index = [short(i) for i in well_table.index]
well_table["first_oil"] = well_table["first_oil"].dt.strftime("%Y-%m-%d")
well_table["last_oil"] = well_table["last_oil"].dt.strftime("%Y-%m-%d")
for col in ["cum_oil", "peak_daily_oil", "cum_water"]:
    well_table[col] = well_table[col].map("{:,.0f}".format)
well_table.columns = ["First oil", "Last oil", "Producing days",
                      "Cumulative oil", "Peak daily oil", "Cumulative water"]
well_table_html = well_table.to_html(classes="tbl", border=0)

qc_table = issues_csv.groupby(["check", "action"]).size().reset_index(name="rows")
qc_table = qc_table.sort_values("rows", ascending=False)
qc_table.columns = ["Check", "Action taken", "Rows"]
qc_table_html = qc_table.to_html(classes="tbl", border=0, index=False)

# ---- Charts: the first one brings the Plotly library, the rest reuse it ----
chart_html = ""
for i, fig in enumerate([fig5, fig1, fig2, fig3, fig4]):
    chart_html += '<div class="card">' + fig.to_html(
        full_html=False, include_plotlyjs="cdn" if i == 0 else False) + "</div>"

findings = [
    "F-12 H's downhole gauge failed on 12 Oct 2010 and logged zeros for almost 6 years. "
    "Left in, those zeros made the average pressure look 3 times too low (83.9 instead of 256.9).",
    "The 20 'impossible' 25-hour days are real: every one is the last Sunday of October, "
    "when Norway turns its clocks back. They were kept, not deleted.",
    "Water broke through in 2010: field water cut jumped from 8 % to 53 % in one year, "
    "and the yearly average stayed at 70 % or higher from 2011 on.",
    "New wells in 2013-2014 (F-11 H, F-15 D, F-1 C) coincide with higher oil output and a lower water cut in 2014-2015.",
    f"An Arps exponential decline fitted F-14 H with R² {fit_r2:.3f}. On 13 hidden months it "
    f"over-predicted oil by {100 * (pred_oil - actual_oil) / actual_oil:.0f} %: the well declined faster than the curve.",
    "The daily-to-monthly roll-up matches Equinor's own monthly sheet "
    "(e.g. F-1 C, April 2014: 11,142.5 oil, 227.5 hours).",
]
findings_html = "".join(f"<li>{html.escape(f)}</li>" for f in findings)

page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Volve Production QC Dashboard</title>
<style>
  :root {{ --bg:#f4f3f0; --card:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --line:#e2e1dc; --accent:#2a78d6; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family: Arial, Helvetica, sans-serif; line-height:1.5; }}
  main {{ max-width:1150px; margin:0 auto; padding:24px 16px 48px; }}
  h1 {{ font-size:28px; margin:0 0 4px; }}
  h2 {{ font-size:20px; margin:32px 0 12px; }}
  .sub {{ color:var(--ink2); margin:0 0 20px; }}
  .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
  .tile {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .num {{ font-size:24px; font-weight:bold; }}
  .lbl {{ color:var(--ink2); font-size:13px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:8px; margin-bottom:16px; overflow-x:auto; }}
  ul {{ padding-left:20px; }} li {{ margin-bottom:8px; }}
  .tbl {{ border-collapse:collapse; width:100%; background:var(--card); font-size:14px; }}
  .tbl th, .tbl td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:right; }}
  .tbl th:first-child, .tbl td:first-child {{ text-align:left; }}
  .tbl thead th {{ color:var(--ink2); }}
  .wrap {{ overflow-x:auto; }}
  footer {{ color:var(--ink2); font-size:13px; margin-top:32px; }}
</style>
</head><body><main>
<h1>Volve Field: Production Data QC &amp; Analysis</h1>
<p class="sub">Excel → Python QC → SQL Server → analysis. 7 wells, 15,634 daily records, 2008-2016.
Built by Yousif Dara Abdullah. Generated {date.today():%d %b %Y}.</p>

<div class="tiles">{tiles_html}</div>

<h2>Key findings</h2>
<ul>{findings_html}</ul>

<h2>Charts</h2>
{chart_html}

<h2>Wells</h2>
<div class="wrap">{well_table_html}</div>

<h2>Quality control log</h2>
<div class="wrap">{qc_table_html}</div>

<h2>Method and limitations</h2>
<ul>
<li>QC rules: never invent data. Remove what is physically impossible, keep what is proven real, flag what cannot be decided.</li>
<li>Units are not stated in the daily sheet. Volumes are assumed to be Sm³ (as in Equinor's monthly sheet); pressure units are not stated.</li>
<li>Known limitation: zero-pressure values were removed only on producing days. F-12 H zeros on shut-in days after 11 Oct 2010 are also likely gauge failures and remain in the clean data.</li>
<li>Missing days (228) are listed in the QC log, not filled in.</li>
</ul>

<footer>Data: Equinor Volve field data set, released under the Equinor Open Data Licence.
Data provided "as is" by Equinor and the former Volve licence partners. This is an independent study project.</footer>
</main></body></html>"""

out = DOCS / "index.html"
out.write_text(page, encoding="utf-8")
print("Dashboard saved:", out)
webbrowser.open(out.as_uri())