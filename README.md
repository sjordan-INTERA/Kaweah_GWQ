# Kaweah groundwater-quality workflow

Append seasonal FGL lab results to the Kaweah RMS master workbook and generate
time-series charts for the wells and constituents with current-season exceedances.

## Set up and run

Create the environment with micromamba from the repo root.

```sh
micromamba create -f environment.yml
```

Edit the `Config` dataclass in `Kaweah_GWQ_Casesheet_Workflow.py`, then run the workflow.

```sh
micromamba run -n kaweah-gwq python Kaweah_GWQ_Casesheet_Workflow.py
```

Set `analysis_year` and `analysis_season` (`spring` or `fall`). Together they
determine the cycle tag, such as `2026F`.

- Set `analysis = True` to process lab results and write the season's workbooks.
- Set `plotting = True` to generate charts from the season's saved workbooks.
- Enable both to process the data and generate charts in one run.

## Prepare a new season

- Set `previous_main_spreadsheet` to the preceding season's master workbook.
  For Fall 2026, the configured starting point is
  `data/legacy_source_data/KSB_RMS_master_2026S.xlsx`.
- Set `tracking_file` to the RMS tracking workbook. The workflow uses the
  **Current RMS Network** tab to match samples and refresh well metadata.
- Put the season's FGL `.xls` or `.xlsx` files in `data/FGL_samples/<cycle>/`.
  Put optional confirmation files in `data/FGL_confirmations/<cycle>/` and
  optional QC workbooks in `data/FGL_samples/<cycle>/SAMPS_DUPS_BLANKS/`.
- Check `output/<cycle>/qa/sample_match_audit_<cycle>.csv` for unresolved
  samples. Record confirmed well-name corrections and exclusions in
  `data/sample_match_decisions/<cycle>.csv` using the columns
  `Description,Action,RMS_ID,Notes`. Use the original FGL description and set
  `Action` to `map` with a current RMS ID, or `exclude` with a blank RMS ID.
  Rerun the analysis after reviewing any unresolved samples.

## Outputs

| Path under `output/<cycle>/` | Contents |
| --- | --- |
| `spreadsheet/KSB_RMS_master_<cycle>.xlsx` | `DMS_Data`, `Current_RMS_Metadata`, and `QA_Issues` sheets |
| `spreadsheet/<Season>_<Year>_exceedances.xlsx` | Current-season exceedance results used to select charts |
| `qa/` | Sample match audit, QC results, and validation summary |
| `png/` | Individual exceedance charts by well and constituent |
| `pdf/all_exceedances_<cycle>.pdf` | All exceedance charts in a single PDF |
