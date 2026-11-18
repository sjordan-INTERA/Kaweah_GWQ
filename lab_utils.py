# -*- coding: utf-8 -*-
"""
Read, classify, match, and translate FGL laboratory spreadsheets.
"""

from pathlib import Path
import os
import re
import pandas as pd


#-- Define the lab fields and constituent names needed for the RMS master.
REQUIRED_COLUMNS = [
    "Description", 
    "LAB_ID", 
    "Constituent", 
    "Result", 
    "Units",
    "Date_Sampled", 
    "Date_Analyzed",
    "PQL",
    "MDA"
    ]

CONSTITUENT_MAP = {
    "Arsenic": "Arsenic",
    "Boron": "Boron", 
    "Sodium": "Sodium",
    "Uranium": "Uranium",
    "Chloride": "Chloride",
    "Chromium VI": "Chromium, Hexavalent (Cr6)",
    "Specific Conductance": "Specific Conductivity",
    "Nitrate Nitrogen": "Nitrate as N",
    "pH": None,
    "pH (Field)": "pH",
    "Total Dissolved Solids (TFR)": "Total Dissolved Solids",
    "Sulfate": "Sulfate", "Perchlorate": "Perchlorate",
    "1,3-Dibromopropane": None,
    "DBCP": "1,2-Dibromo-3-chloropropane (DBCP)",
    "EDB": None,
    "4-Bromofluorobenzene": None,
    "1,2-Dichlorobenzene-d4": None,
    "Tetrachloroethylene": "Tetrachloroethene (PCE)",
    "1,2,3-Trichloropropane": "1,2,3-Trichloropropane (1,2,3 TCP)",
    "Gross Alpha": "Gross Alpha radioactivity", 
    "Depth to Water": None,
}


def normalize_id(value):
    """
    Normalize case and whitespace in LAB_IDs for more consistent matches
    """
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip().upper()


def load_lab_folder(folder, source, required=False):
    """
    Read top-level XLS/XLSX files without modifying the originals.
    """
    # -- Primary folder must exist
    if folder is None or not Path(folder).exists():
        if required:
            raise FileNotFoundError(f"Lab folder does not exist: {folder}")
        return pd.DataFrame()
    
    # -- Get all the Excel files in the folder
    files = sorted(p for p in Path(folder).iterdir()
                   if p.is_file() and p.suffix.lower() in {".xls", ".xlsx"}
                   and not p.name.startswith("~$"))
    if required and not files:
        raise FileNotFoundError(f"No lab spreadsheets in {folder}")
    frames = []
    
    # -- Loop through and process all the raw lab spreadsheet input
    for path in files:
        # Some of the workbooks are corrupted, need to ignore that error
        try:
            if path.suffix.lower() == ".xls":
                with open(os.devnull, "w") as log:
                    df = pd.read_excel(
                        path, 
                        engine="xlrd", 
                        engine_kwargs={
                            "ignore_workbook_corruption": True, 
                            "logfile": log
                            }
                        )
            else:
                df = pd.read_excel(path, engine="openpyxl")
        except Exception as exc:
            raise ValueError(f"Cannot read lab workbook {path}: {exc}") from exc
            
        # -- Check each file before combining rows so an issue names its source workbook.
        missing = sorted(set(REQUIRED_COLUMNS) - set(df.columns))
        # missing required input column
        if missing:
            raise ValueError(f"{path.name} missing required columns: {missing}")
        # Has no data
        if df.empty:
            raise ValueError(f"{path.name} contains no laboratory rows")
        # Column check
        for column in ["Description", "LAB_ID", "Constituent", "Units"]:
            if df[column].isna().any() or df[column].astype(str).str.strip().eq("").any():
                raise ValueError(f"{path.name} has missing {column}")

        # NaN lab result (missing value)
        if df["Result"].isna().any():
            raise ValueError(f"{path.name} has missing Result")
            
        # -- Field pH and excluded lab fields may lack a laboratory analysis date
        for column in ["Date_Sampled", "Date_Analyzed"]:
            parsed = pd.to_datetime(df[column], errors="coerce")
            missing_allowed = column == "Date_Analyzed" and (
                df["Constituent"].eq("pH (Field)")
                | df["Constituent"].map(CONSTITUENT_MAP).isna()
            )
            if (parsed.isna() & ~missing_allowed).any():
                raise ValueError(f"{path.name} has invalid {column}")
            df[column] = parsed
        unknown = sorted(set(df["Constituent"].astype(str).str.strip()) - set(CONSTITUENT_MAP))
        if unknown:
            raise ValueError(f"{path.name} has unreviewed constituents: {unknown}")
            
        # -- Non-detects need a numeric limit because that limit is stored as the result.
        nd = df["Result"].astype(str).str.strip().str.upper().eq("ND")
        gross = df["Constituent"].astype(str).str.strip().eq("Gross Alpha")
        missing_limit = (nd & ~gross & pd.to_numeric(df["PQL"], errors="coerce").isna())
        missing_limit |= nd & gross & pd.to_numeric(df["MDA"], errors="coerce").isna()
        if missing_limit.any():
            raise ValueError(f"{path.name} has non-detects without reporting limits")
        if pd.to_numeric(df.loc[~nd, "Result"], errors="coerce").isna().any():
            raise ValueError(f"{path.name} has nonnumeric detected results")
            
        # -- Keep the filename and sample source for the match audit and final workbook.
        df["SOURCE_FILE"] = path.name
        df["SOURCE"] = source
        frames.append(df)
        
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def combine_raw(*frames):
    """
    Combine optional sources only after each workbook has passed its own checks.
    """
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        raise ValueError("No laboratory rows were read")
        
    return pd.concat(nonempty, ignore_index=True, sort=False)


def load_review_decisions(path):
    """
    Load explicit map/exclude decisions keyed by original lab Description
    """
    if not path.exists():
        return {}
    df = pd.read_csv(path, keep_default_na=False)
    required = {"Description", "Action", "RMS_ID", "Notes"}
    if not required.issubset(df.columns):
        raise ValueError(f"{path} requires columns {sorted(required)}")
    decisions = {}
    for row in df.itertuples(index=False):
        key = normalize_id(row.Description)
        action = str(row.Action).strip().lower()
        if not key or action not in {"map", "exclude"} or key in decisions:
            raise ValueError(f"Invalid or repeated review decision for {row.Description!r}")
        decisions[key] = (action, normalize_id(row.RMS_ID), str(row.Notes))
        
    return decisions


def match_samples(raw, rms, decisions):
    """
    Resolve unique current-network IDs and report every lab sample
    """
    # -- Index RMS IDs and local aliases 
    lookup = {}
    for _, row in rms.iterrows():
        canonical = normalize_id(row["RMS ID"])
        for column in ["RMS ID", "Local Well ID 1", "Local Well ID 2"]:
            alias = normalize_id(row.get(column))
            if alias:
                lookup.setdefault((column, alias), set()).add(canonical)
    valid = set(rms["RMS ID"].map(normalize_id))
    df = raw.copy()
    df["DESCRIPTION_KEY"] = df["Description"].map(normalize_id)
    
    # -- Identify blanks and duplicates before matching, so QC cannot enter the master.
    suffix = df["DESCRIPTION_KEY"].str.extract(r"\s*-\s*(BLANK|DUP)$", expand=False)
    df["QC_TYPE"] = suffix.map({"BLANK": "Field Blank", "DUP": "Duplicate"}).fillna("Regular")
    df.loc[df["SOURCE"].eq("qc") & df["QC_TYPE"].eq("Regular"), "QC_TYPE"] = "QC folder regular copy"
    audit_rows, errors, resolutions = [], [], {}
    groups = df.groupby(
        ["DESCRIPTION_KEY", "LAB_ID", "SOURCE_FILE", "SOURCE"],
        dropna=False, 
        sort=True
        )
    
    # -- Resolve each lab sample separately and retain its raw description in the audit
    for (key, lab_id, filename, source), group in groups:
        original_description = group["Description"].iloc[0]
        qc_type = group["QC_TYPE"].iloc[0]
        canonical, method, status = "", "", ""
        if qc_type == "QC folder regular copy":
            # Ignore an archive QC copy only when the regular sample exists elsewhere.
            has_primary = ((df.DESCRIPTION_KEY.eq(key)) & (df.LAB_ID.eq(lab_id))
                           & df.SOURCE.ne("qc")).any()
            status = "QC copy ignored" if has_primary else "Review required"
            method = "Regular row in a QC workbook; primary copy " + (
                "found" if has_primary else "missing")
        elif qc_type != "Regular":
            status, method = "QC only", "Description suffix"
        else:
            # Prefer an exact RMS ID, then a unique local alias, then a reviewed decision.
            for column in ["RMS ID", "Local Well ID 1", "Local Well ID 2"]:
                candidates = lookup.get((column, key), set())
                if candidates:
                    if len(candidates) == 1:
                        canonical = next(iter(candidates))
                        status, method = "Matched", column
                    else:
                        status, method = "Review required", f"Ambiguous {column}: {sorted(candidates)}"
                    break
            if status != "Matched" and key in decisions:
                action, approved, notes = decisions[key]
                if action == "exclude":
                    status, method = "Reviewed exclusion", notes
                elif approved in valid:
                    canonical, status, method = approved, "Matched", "Reviewed mapping"
                else:
                    status, method = "Review required", f"Invalid reviewed RMS ID: {approved}"
            if not status:
                status, method = "Review required", "No current RMS match or review decision"
                
        # -- Unresolved samples stop publication, but their audit rows are still returned
        if status == "Review required":
            errors.append(f"{original_description} / {lab_id}: {method}")
        audit_rows.append({
            "Description": original_description, "LAB_ID": lab_id,
            "SOURCE_FILE": filename, "SOURCE": source, "QC_TYPE": qc_type,
            "RMS_ID": canonical, "Status": status, "Match_Method": method,
            "Raw_Rows": len(group),
        })
        resolutions[(key, lab_id, filename, source)] = (canonical, status)
    df["GM_WELL_ID"] = [resolutions[(k, l, f, s)][0] for k, l, f, s in
                         zip(df.DESCRIPTION_KEY, df.LAB_ID, df.SOURCE_FILE, df.SOURCE)]
    df["MATCH_STATUS"] = [resolutions[(k, l, f, s)][1] for k, l, f, s in
                          zip(df.DESCRIPTION_KEY, df.LAB_ID, df.SOURCE_FILE, df.SOURCE)]
    
    return df, pd.DataFrame(audit_rows), errors


def translate_samples(matched, sampling_round):
    """
    Translate retained analytes and keep all QC outside the main spreadsheet
    """
    # -- Exclude reviewed non-network samples and lab constituents outside the COC list.
    df = matched.loc[matched["MATCH_STATUS"].isin(["Matched", "QC only"])].copy()
    df["pH_source"] = df["Constituent"].eq("pH (Field)").map({True: "field", False: ""})
    df["GM_CHEMICAL_NAME"] = df["Constituent"].astype(str).str.strip().map(CONSTITUENT_MAP)
    df = df.loc[df.GM_CHEMICAL_NAME.notna()].copy()
    nd = df.Result.astype(str).str.strip().str.upper().eq("ND")
    gross = df.GM_CHEMICAL_NAME.eq("Gross Alpha radioactivity")
    
    # -- Store non-detects with '<' and the MDA for gross alpha or PQL otherwise.
    df["GM_RESULT_MODIFIER"] = nd.map({True: "<", False: "="})
    df["GM_RESULT"] = pd.to_numeric(df.Result, errors="coerce")
    df.loc[nd & gross, "GM_RESULT"] = pd.to_numeric(df.loc[nd & gross, "MDA"])
    df.loc[nd & ~gross, "GM_RESULT"] = pd.to_numeric(df.loc[nd & ~gross, "PQL"])
    df["GM_CHEMICAL_UNITS"] = df.Units.astype(str).str.strip().str.upper()
    df["GM_SAMP_COLLECTION_DATE"] = df.Date_Sampled
    df["SRC_ANALYSIS_DATE"] = df.Date_Analyzed
    df["Sampling_Round"] = sampling_round
    df["LAB_ID"] = df.LAB_ID.astype(str).str.strip()
    columns = [
        "GM_WELL_ID", "GM_CHEMICAL_NAME", "GM_SAMP_COLLECTION_DATE",
        "GM_RESULT", "GM_RESULT_MODIFIER", "GM_CHEMICAL_UNITS",
        "SRC_ANALYSIS_DATE", "Sampling_Round", "SOURCE", "LAB_ID",
        "QC_TYPE", "SOURCE_FILE", "pH_source"
        ]
    
    # -- Only regular and confirmation results are returned for the main append
    qc = df.loc[df.QC_TYPE.ne("Regular")].copy()
    regular = df.loc[df.QC_TYPE.eq("Regular")].copy()
    
    return regular[columns].reset_index(drop=True), qc[columns + ["Description"]].reset_index(drop=True)


def find_conflicting_analyses(df):
    """
    Identify repeated analytes that disagree in result
    """
    # -- One well, lab sample, and constituent should have one consistent measurement.
    keys = ["GM_WELL_ID", "LAB_ID", "GM_CHEMICAL_NAME"]
    comparison = [
        "GM_RESULT", "GM_RESULT_MODIFIER", "GM_CHEMICAL_UNITS",
        "GM_SAMP_COLLECTION_DATE", "SRC_ANALYSIS_DATE", "SOURCE"
        ]
    conflicts = []
    for key, group in df.loc[df.duplicated(keys, keep=False)].groupby(keys, dropna=False):
        if len(group[comparison].drop_duplicates()) > 1:
            conflicts.append(" / ".join(map(str, key)))
            
    return conflicts
