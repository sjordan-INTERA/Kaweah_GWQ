# Kaweah groundwater-quality seasonal append

Run the top-level workflow in the jea environment:

    micromamba run -n jea python Kaweah_GWQ_Casesheet_Workflow.py

The supplied Fall 2026 files are legacy XLS workbooks. The jea environment
needs xlrd 2.0.2 as well as its existing pandas and openpyxl packages.
The reader uses the xlrd corruption-tolerance option because the Fall files
have nonstandard workbook containers. Every file still must pass column,
date, result, and reporting-limit checks. Source files are never rewritten.

## New season

Change analysis_year and analysis_season in the driver's Config. All run
settings are in that dataclass; the script does not take command-line options.
Put regular lab files in data/FGL_samples/<cycle>/.
If there are confirmation files, put them in
data/FGL_confirmations/<cycle>/. Set previous_main_spreadsheet explicitly
to the preceding season's saved workbook. Fall 2026 starts from the supplied
data/legacy_source_data/KSB_RMS_master_2026S.xlsx.

Unresolved descriptions are listed in the season's QA sample match audit.
Record confirmed FGL well-name corrections and exclusions in
data/sample_match_decisions/<cycle>.csv with Description,Action,RMS_ID,Notes.
Use the original FGL description and the action map or exclude. For map,
enter the RMS ID from the Current RMS Network tab. Then rerun. Different LAB_IDs
are separate samples, including supplemental analyses of one constituent.
Blank and duplicate descriptions stay in the separate QC CSV.

The final plotting input is
output/<cycle>/spreadsheet/KSB_RMS_master_<cycle>.xlsx. The workbook
keeps the DMS_Data, Current_RMS_Metadata, and QA_Issues sheets.
The qa folder also contains the match audit, QC table, and validation summary.
An input or matching error stops before the season workbook is written.

## 2026 validation

The saved Spring 2026 replay has 12,669 RMS rows: 1,056 regular and 19
confirmation Spring rows, with 32 QC rows outside the master. It agrees with
the supplied workbook on all measurement keys and 72 columns; a few historical
coordinates and elevations differ only at approximately 1e-14 after Excel
read/write. The current workflow reads the previous Excel workbook, so it
does not regenerate Spring 2026 from the older historical CSV.

Compare the saved Spring replay and Fall append with:

    micromamba run -n jea python validate_2026.py
