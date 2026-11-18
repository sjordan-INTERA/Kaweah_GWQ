# -*- coding: utf-8 -*-
"""
Load, append, validate, and format the RMS measurement workbook.
"""

from pathlib import Path
import pandas as pd
from lab_utils import normalize_id
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


# -- Add to these as needed
COCS = [
    "Nitrate as N", 
    "1,2,3-Trichloropropane (1,2,3 TCP)",
    "Gross Alpha radioactivity", 
    "Uranium", 
    "Arsenic",
    "1,2-Dibromo-3-chloropropane (DBCP)",
    "Perchlorate",
    "Tetrachloroethene (PCE)", 
    "Chromium, Hexavalent (Cr6)",
    "Total Dissolved Solids",
    "Specific Conductivity",
    "Chloride",
    "Sulfate", 
    "pH", 
    "Sodium",
    "Boron",
]

# -- Abbreviated short-names
COCS_ABB = {
    "1,2,3-Trichloropropane (1,2,3 TCP)": "1,2,3 TCP",
    "1,2-Dibromo-3-chloropropane (DBCP)": "DBCP",
    "Tetrachloroethene (PCE)": "PCE", 
    "Chromium, Hexavalent (Cr6)": "Cr6",
    "Total Dissolved Solids": "TDS",
}


def load_measurements(path):
    """
    Read the previous season's main workbook
    """
    # -- Path to previous season's workbook
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Previous measurements not found: {path}")
    df = pd.read_excel(path, sheet_name="DMS_Data")
    
    # -- Normalize well id, chemical name, and datetime formatting
    df = df.copy()
    df["GM_WELL_ID"] = df.GM_WELL_ID.map(normalize_id)
    df["GM_CHEMICAL_NAME"] = df.GM_CHEMICAL_NAME.fillna("").astype(str).str.strip()
    df["GM_SAMP_COLLECTION_DATE"] = pd.to_datetime(df.GM_SAMP_COLLECTION_DATE, errors="coerce")
    df["SRC_ANALYSIS_DATE"] = pd.to_datetime(df.SRC_ANALYSIS_DATE, errors="coerce")
    
    # -- Normalize whitespace in the LAB_ID and GM_CHEMICAL_UNITS
    df["LAB_ID"] = df.LAB_ID.fillna("").astype(str).str.strip()
    df["GM_CHEMICAL_UNITS"] = df.GM_CHEMICAL_UNITS.fillna("").astype(str).str.strip().str.upper()
    
    print(f"Loaded {len(df):,} previous measurement rows from {path}")
    
    return df


def load_rms_network(path):
    """
    Read the current network of RMS wells to use as reference for which wells
    to include on the main spreadsheet for the season.
    """
    # -- Load the current tracking sheet
    df = pd.read_excel(
        path, 
        sheet_name="Current RMS Network",
        # Current version has 6 header rows that need to be skipped
        # -> I could see this needing updates in future itterations
        skiprows=6
        ).dropna(how="all")
    
    # -- Columns with only spaces and/or tabs are treated as Na
    for column in df.select_dtypes(include=["object"]).columns:
        df[column] = df[column].replace(r"^\s*$", pd.NA, regex=True)
    
    # -- Normalize RMS ID the same way it was in the main spreadsheet
    df["RMS ID"] = df["RMS ID"].map(normalize_id)
    
    # -- If any RMS ID is blank, fails
    if df["RMS ID"].eq("").any():
        raise ValueError("Current RMS Network contains a blank RMS ID")
        
    # -- Deal with potential duplicate listed RMS wells
    # 1. If exact matches exist (all colummns are the same) keep first
    # 2. If matching RMS ID with differing metadata values exist, fail
    duplicates = df.loc[df["RMS ID"].duplicated(keep=False)]
    for rms_id, group in duplicates.groupby("RMS ID"):
        if len(group.drop_duplicates()) != 1:
            raise ValueError(f"Conflicting current RMS metadata for {rms_id}")
    
    # -- Reset index
    df = df.drop_duplicates("RMS ID", keep="first").reset_index(drop=True)
    
    # -- Clean up GSA names to match the main workbook
    df["GSA"] = df.GSA.astype("string").str.strip().replace({
        "Greater Kaweah GSA": "GKGSA", "Mid-Kaweah GSA": "MKGSA",
        "East Kaweah GSA": "EKGSA",
    })
    print(f"Loaded {len(df)} unique current RMS wells")
    
    return df


def add_regulatory_fields(current, previous):
    """
    Attach prior-workbook regulatory fields to current-season measurements.

    Use prior rows with an MCL to find one definition per constituent. Stop if
    required columns are missing or a constituent has conflicting MCL definitions.
    Join the MCL, its units, notes, and label by GM_CHEMICAL_NAME while retaining
    current measurements that have no MCL.

    Mark mcl_exceedance only when a detected result (marked '=') exceeds its
    MCL. Non-detects and results without an MCL are not flagged.
    """
    # -- Reuse the previous main as the regulatory lookup for the same COC names
    columns = [
        "GM_CHEMICAL_NAME", "MCL", "MCL UNITS", "MCL_NOTES", "MCL_LABEL"
        ]
    missing = sorted(set(columns) - set(previous.columns))
    if missing:
        raise ValueError(
            f"Previous measurements missing regulatory columns: {missing}"
            )
        
    # -- Read previous documented MCL values, fails if multiple exist
    lookup = previous.loc[
        previous.MCL.notna(), columns
        ].drop_duplicates()
    conflicting = lookup.loc[
        lookup.GM_CHEMICAL_NAME.duplicated(keep=False),
        "GM_CHEMICAL_NAME"
        ].unique()
    if len(conflicting):
        raise ValueError(f"Conflicting MCL definitions for {sorted(conflicting)}")
        
    # -- Merge current data to MCL lookup table
    result = current.merge(
        lookup,
        on="GM_CHEMICAL_NAME", 
        how="left", 
        validate="many_to_one"
        )
    
    # -- Calculate exceedances
    result["mcl_exceedance"] = (
        # Only exceed on detected results
        result.GM_RESULT_MODIFIER.eq("=")
        # Cannot be NA
        & result.MCL.notna()
        # Has a valid MCL
        & result.GM_RESULT.gt(pd.to_numeric(result.MCL, errors="coerce"))
        )
    
    return result


def append_season(previous, current, sampling_round):
    """
    Append the current season's measurements to the previous dataset
    """
    # -- If entries exist for the current season being ran, remove them first
    previous = previous.loc[~previous.Sampling_Round.eq(sampling_round)].copy()
    
    # -- Check if any of the new lab analyses already exist in the workbook
    keys = ["GM_WELL_ID", "LAB_ID", "GM_CHEMICAL_NAME"]
    with_lab = previous.loc[previous.LAB_ID.ne(""), keys]
    overlap = pd.MultiIndex.from_frame(current[keys]).isin(pd.MultiIndex.from_frame(with_lab))
    if overlap.any():
        examples = current.loc[overlap, keys].head(5).to_dict("records")
        raise ValueError(f"Current lab analysis already exists in another season: {examples}")
    
    # -- Append on the new data
    columns = list(previous.columns) + [c for c in current.columns if c not in previous.columns]
    updated = pd.concat(
        [previous.reindex(columns=columns),
         current.reindex(columns=columns)],
        ignore_index=True
        )
    
    # -- Sort by well, chemical, sample date, and lab id
    updated = updated.sort_values(
        ["GM_WELL_ID", "GM_CHEMICAL_NAME", "GM_SAMP_COLLECTION_DATE", "LAB_ID"],
        na_position="last"
        ).reset_index(drop=True)

    return updated


def build_rms_master(updated, rms, previous_columns):
    """
    Takes the updated dataset (previous main + current season), the current RMS
    network wells, and the COCs list defined at the top of this script to 
    produce the final work-product: the updated DMS.
    
    Things to note:
        1. This refreshes all well's metadata based on the current RMS network
           spreadsheet. So if the RMS spreadsheet changes a well's attribute, 
           that will be applied to the entire workbook for the season
        2. If the RMS network changes, that change is applied to the whole
           spreadsheet. For example, is a well is removed from the network,
           that well and all its historical records will be dropped from the 
           spreadsheet. 
    """
    # -- Filter to only current RMS wells and specified COCs
    valid = set(rms["RMS ID"])
    df = updated.loc[
        updated.GM_WELL_ID.isin(valid)
        & updated.GM_CHEMICAL_NAME.isin(COCS)
        ].copy()
    
    # -- Match name
    metadata = rms.rename(columns={"RMS ID": "GM_WELL_ID"})
    
    # -- Refresh well metadata if needed
    stale = [c for c in metadata if c in df and c != "GM_WELL_ID"]
    df = df.drop(columns=stale).merge(
        metadata, 
        on="GM_WELL_ID", 
        how="left",
        validate="many_to_one"
        )
    # -- Keep the prior workbook's column order and append new fields at the end
    ordered = [c for c in previous_columns if c in df]
    ordered += [c for c in df if c not in ordered]
    df = df[ordered]
    
    # -- Sort to useful order on the spreadsheet
    df = df.sort_values(
        ["GSA", "GM_WELL_ID", "GM_CHEMICAL_NAME", "GM_SAMP_COLLECTION_DATE"],
        na_position="last"
        ).reset_index(drop=True)
    
    return df


def build_qa(previous, current, qc, master, rms, audit):
    """
    Summarize run coverage and format the main workbook.
    """
    # -- Distinguish retained measurements, QC results, and excluded samples
    current_wells = set(current.GM_WELL_ID)
    rms_ids = set(rms["RMS ID"])
    master_wells = set(master.GM_WELL_ID)
    values = [
        ("previous_rows", len(previous)),
        ("current_regular_rows", int(current.SOURCE.eq("new").sum())),
        ("current_confirmation_rows", int(current.SOURCE.eq("confirmation").sum())),
        ("separate_qc_rows", len(qc)),
        ("reviewed_exclusions", int(audit.Status.eq("Reviewed exclusion").sum())),
        ("current_rms_wells", len(rms_ids)),
        ("current_cycle_wells_with_results", len(current_wells)),
        ("rms_master_rows", len(master)),
        ("current_sample_date_min", current.GM_SAMP_COLLECTION_DATE.min()),
        ("current_sample_date_max", current.GM_SAMP_COLLECTION_DATE.max()),
    ]
    summary = pd.DataFrame(values, columns=["metric", "value"])
    
    # -- Report some possible issues
    # 1. RMS well has no current-cycle result
    # 2. RMS well has no previous data on the main spreadsheet
    # 3. Multiple units exist for the same constituent sample
    issues = []
    for well in sorted(rms_ids - current_wells):
        issues.append(("INFO", "RMS well has no current-cycle result", well))
    for well in sorted(rms_ids - master_wells):
        issues.append(("INFO", "RMS well has no previous main data", well))
    counts = master.loc[master.GM_CHEMICAL_UNITS.ne("")].groupby(
        "GM_CHEMICAL_NAME").GM_CHEMICAL_UNITS.nunique()
    for chemical in counts.loc[counts.gt(1)].index:
        units = sorted(master.loc[master.GM_CHEMICAL_NAME.eq(chemical),
                                  "GM_CHEMICAL_UNITS"].dropna().unique())
        issues.append(("INFO", "Constituent has multiple units", f"{chemical}: {units}"))
        
    return summary, pd.DataFrame(issues, columns=["level", "issue", "value"])


def write_rms_workbook(path, master, rms, issues):
    """
    Write the established three-sheet workbook with readable table formatting
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # -- Write and format the updated main workbook
    with pd.ExcelWriter(path, engine="openpyxl", date_format="yyyy-mm-dd") as writer:
        # Use established sheet names
        for name, df in [("DMS_Data", master), ("Current_RMS_Metadata", rms),
                         ("QA_Issues", issues)]:
            df.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.sheet_view.showGridLines = False
            
            # Keep field names visible and readable in wide measurement tables.
            for cell in ws[1]:
                cell.fill = PatternFill("solid", fgColor="1F4E78")
                cell.font = Font(color="FFFFFF", bold=True)
                cell.alignment = Alignment(
                    horizontal="center", 
                    vertical="center",
                    wrap_text=True
                    )
            ws.row_dimensions[1].height = 30
            
            for index, column in enumerate(df.columns, start=1):
                lengths = df[column].astype(str).head(2000).str.len()
                width = min(max(int(max([len(str(column)), *lengths.tolist()]) + 2), 10), 36)
                ws.column_dimensions[get_column_letter(index)].width = width
                
                # Store dates as typed Excel values with a consistent display format.
                if "DATE" in str(column).upper() or pd.api.types.is_datetime64_any_dtype(df[column]):
                    for row in ws.iter_rows(min_row=2, min_col=index, max_col=index):
                        row[0].number_format = "yyyy-mm-dd"


def export_exceedances(path,season,master):
    """
    Export current season's exceedances to a spreadsheet
    """
    # -- Get subset of current exceedances
    exceeded = master.loc[
        (master['Sampling_Round'] == season) &
        (master['mcl_exceedance'])
        ]
    
    # -- Create summary spreadsheet
    exceeded = exceeded[
        ['GM_WELL_ID','GM_CHEMICAL_NAME','GM_RESULT','MCL','MCL UNITS']
        ].rename(
            columns={
                'GM_CHEMICAL_NAME':'constituent',
                'GM_RESULT':'sample_value',
                'MCL UNITS':'MCL_UNITS'
                }
            )
    
    # -- Create abbreviated names
    chemical_names = exceeded["constituent"]
    exceeded["constituent_abb"] = chemical_names.map(COCS_ABB).fillna(chemical_names)
    
    # -- Reorder columns
    exceeded = exceeded[
        ['GM_WELL_ID','constituent','constituent_abb','sample_value','MCL','MCL_UNITS']
        ].sort_values(by='GM_WELL_ID')
    
    # -- Save as spreadsheet
    exceeded.to_excel(
        path,
        index=False
        )