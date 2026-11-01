\# Volve Field: Production Data QC \& Analysis Pipeline



An end-to-end pipeline on real oil-field data: \*\*raw Excel → Python quality control → SQL Server → analysis → dashboard and Excel report\*\*, with automated tests.



\*\*Live dashboard:\*\* LIVE\_DASHBOARD\_LINK



Data: 7 wells, 15,634 daily records (2008–2016) from Equinor's public Volve field data set (North Sea).



\## Key findings



1\. \*\*A failed gauge, caught.\*\* Well F-12 H's downhole pressure gauge failed on 12 Oct 2010 and logged zeros for almost 6 years (1,906 days). Left in, those zeros make the well's average pressure look 3× too low (83.9 instead of 256.9). They were treated as missing, not as real readings.

2\. \*\*"Impossible" data that was real.\*\* 20 days show more than 24 on-stream hours. Every one falls on the last Sunday of October, when Norway turns its clocks back, so the day really has 25 hours. They were kept.

3\. \*\*Water breakthrough in 2010.\*\* Field water cut jumped from 8 % to 53 % in one year; the yearly average stayed at 70 % or higher from 2011 on.

4\. \*\*Decline curve, tested on hidden data.\*\* An Arps exponential decline fitted well F-14 H (2013 onward) with R² = 0.975. On 13 months hidden from the fit it over-predicted oil by about 15 %: the well declined faster than the curve. Annual decline ≈ 46 %.

5\. \*\*Validated against the operator's own numbers.\*\* The daily-to-monthly roll-up reproduces Equinor's published monthly sheet (e.g. F-1 C, April 2014: 11,142.5 oil, 227.5 on-stream hours).



\## Pipeline



| Stage | Script | What it does |

|---|---|---|

| 1. Quality control | `qc.py` + `qc\_rules.py` | Runs 6 checks, fixes or flags each problem, writes a clean CSV and a QC log |

| 2. Load | `load\_sql.py` | Loads the clean data into SQL Server with parameterized queries, then reconciles row counts, oil totals and per-well counts, and writes a load log |

| 3. Analysis | `analysis.py` | Monthly production, water cut, Arps decline curve, 5 Plotly charts, HTML dashboard |

| 4. Report | `report\_excel.py` | Builds a formatted, dated Excel report (5 sheets), with totals calculated in SQL |

| Tests | `tests/test\_qc\_rules.py` | 8 pytest tests for the QC rules |



`qc\_steps.py` is the same QC written step by step, as a learning walkthrough.



\## Quality control rules



Principle: \*\*never invent data.\*\* Remove what is physically impossible, keep what is proven real, flag what cannot be decided.



| Check | Found | Action |

|---|---|---|

| Duplicate well + date | 0 | Remove |

| Negative volumes | 4 | Set to missing |

| Zero downhole pressure while producing | 1,923 | Set to missing (gauge failure) |

| Over 24 h on the clock-change day | 20 | Keep (valid 25-hour day) |

| Impossible on-stream hours | 0 | Set to missing |

| Oil reported with 0 on-stream hours | 1 | Flag for human review |

| Missing calendar days | 228 | List only, no rows invented |



Load reconciliation: 15,634 rows and 10,037,080.61 total oil in the file = 15,634 rows and 10,037,080.61 in SQL Server → \*\*PASS\*\*.



\## Run it yourself



1\. Install SQL Server (Express or Developer) and create a database: `CREATE DATABASE VolveProduction;`

2\. Download the Volve production data (Excel) from Equinor and save it as `data/Volve\_production\_data.xlsx`.

3\. Copy `.env.example` to `.env` and adjust the server name if needed.

4\. Install the packages: `pip install -r requirements.txt`

5\. Run, in order:

