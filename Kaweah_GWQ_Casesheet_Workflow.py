# -*- coding: utf-8 -*-
"""
Seasonal Kaweah groundwater-quality spreadsheet workflow.
"""

from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import lab_utils
import spreadsheet_utils
import plot_utils

# -- Top level folder, everything is relative to this
ROOT = Path(__file__).resolve().parent


@dataclass
class Config:
    """
    Edit these settings to run a new season
    """
    
    # --------------------------------------------------------------------
    # -- Update these settings for the current sampling season.
    # --------------------------------------------------------------------
    analysis_year: int = 2026
    analysis_season: str = "fall"

    # -- Set the previous workbook explicitly for each new season.
    # e.g., if its 2026F, set this to the path to the 2026S file
    previous_main_spreadsheet: Path = ROOT / "data" / "legacy_source_data" / "KSB_RMS_master_2026S.xlsx"
    
    # -- Path to the spreadsheet defining the current set of RMS wells
    tracking_file: Path = ROOT / "data" / "GWQ RMS Tracking.xlsx"

    # -- Settings to choose to run analysis, plotting, or both
    analysis: bool = False
    plotting: bool = True

    # ---------------------------------------------------------------------
    # -- Derive this season's paths from the specified year and season
    # -- DO NOT edit these properties
    # ---------------------------------------------------------------------
    @property
    def tag(self) -> str:
        season = self.analysis_season.lower()
        if season not in {"spring", "fall"}:
            raise ValueError("analysis_season must be 'spring' or 'fall'")
        return f"{self.analysis_year}{season[0].upper()}"

    @property
    def primary_dir(self) -> Path:
        return ROOT / "data" / "FGL_samples" / self.tag

    @property
    def confirmation_dir(self) -> Path:
        return ROOT / "data" / "FGL_confirmations" / self.tag

    @property
    def qc_dir(self) -> Path:
        return self.primary_dir / "SAMPS_DUPS_BLANKS"

    @property
    def review_file(self) -> Path:
        return ROOT / "data" / "sample_match_decisions" / f"{self.tag}.csv"

    @property
    def output_folder(self) -> Path:
        return ROOT / "output" / self.tag

    @property
    def sampling_round(self) -> str:
        return f"{self.analysis_season.title()}_{self.analysis_year}"

    @property
    def spreadsheet_path(self) -> Path:
        return self.output_folder / "spreadsheet" / f"KSB_RMS_master_{self.tag}.xlsx"

    @property
    def exceeded_path(self) -> Path:
        return self.output_folder / "spreadsheet" / f"{self.sampling_round}_exceedances.xlsx"

    @property
    def qa_dir(self) -> Path:
        return self.output_folder / "qa"


def run_analysis(cfg):
    """
    Run the seaonal workflow
    """
    print(f"...Starting groundwater-quality update for {cfg.tag}")
    cfg.qa_dir.mkdir(parents=True, exist_ok=True)

    # -- Load prior seasons's main measurement spreadsheet and current RMS network
    previous = spreadsheet_utils.load_measurements(
        cfg.previous_main_spreadsheet
        )
    rms = spreadsheet_utils.load_rms_network(
        cfg.tracking_file
        )

    # -- Read this season's FGL laboratory workbooks
    # Required to have at least the primary data
    primary = lab_utils.load_lab_folder(
        cfg.primary_dir,
        "new",
        required=True
        )
    
    # Optional to have confirmation and QC samples
    confirmation = lab_utils.load_lab_folder(
        cfg.confirmation_dir, 
        "confirmation"
        )
    qc_files = lab_utils.load_lab_folder(
        cfg.qc_dir, 
        "qc"
        )
    
    # -- Combine primary, confirmation, and qc samples to one DataFrame
    raw = lab_utils.combine_raw(
        primary, 
        confirmation,
        qc_files
        )

    # -- Match lab descriptions to wells on the current RMS network
    decisions = lab_utils.load_review_decisions(cfg.review_file)
    matched, audit, match_errors = lab_utils.match_samples(
        raw,
        rms, 
        decisions
        )
    audit_path = cfg.qa_dir / f"sample_match_audit_{cfg.tag}.csv"
    audit.to_csv(audit_path, index=False)
    if match_errors:
        raise ValueError(
            f"{len(match_errors)} sample match issue(s); review {audit_path}: " + 
            "; ".join(match_errors[:5])
            )

    # -- Convert new laboratory rows to the main spreadsheet fields
    measurements, qc = lab_utils.translate_samples(
        matched,
        cfg.sampling_round
        )
    qc_path = cfg.qa_dir / f"qc_samples_{cfg.tag}.csv"
    qc.to_csv(qc_path, index=False)
    measurements = spreadsheet_utils.add_regulatory_fields(
        measurements,
        previous
        )
    
    # -- Conflicting analyses must be reviewed and manually resolved
    # Conflicts occur when the same RMS well, Lab_ID, and constituent combo
    # appears more than once in the current sampling round. 
    conflicts = lab_utils.find_conflicting_analyses(measurements)
    if conflicts:
        conflict_path = cfg.qa_dir / f"analysis_conflicts_{cfg.tag}.csv"
        pd.DataFrame({"conflicting_lab_analysis": conflicts}).to_csv(
            conflict_path, index=False)
        raise ValueError(
            f"Conflicting repeated lab analyses; review {conflict_path}: " + 
            "; ".join(conflicts[:5])
            )
    measurements = measurements.drop_duplicates(
        ["GM_WELL_ID", "LAB_ID", "GM_CHEMICAL_NAME"], keep="first"
    )

    # -- Append the new data to the previous season's spreadsheet
    updated = spreadsheet_utils.append_season(
        previous, 
        measurements, 
        cfg.sampling_round
        )
    
    # -- Build new main spreadsheet using the pevious season, current season, and RMS wells
    master = spreadsheet_utils.build_rms_master(
        updated, 
        rms,
        previous.columns
        )
    
    # -- Summarize any QA/QC issues to review
    summary, issues = spreadsheet_utils.build_qa(
        previous,
        measurements, 
        qc,
        master,
        rms,
        audit
        )
    
    # -- Write the QA/QC summary -> REVIEW THIS CSV EACH SEASON
    summary.to_csv(
        cfg.qa_dir / f"validation_summary_{cfg.tag}.csv", 
        index=False
        )
    
    # -- Write the current season's main workbook
    spreadsheet_utils.write_rms_workbook(
        cfg.spreadsheet_path,
        master,
        rms,
        issues
        )

    # -- Write the current season's exceedance spreadsheet
    spreadsheet_utils.export_exceedances(
        cfg.exceeded_path,
        cfg.sampling_round,
        master
        )
    
    print(f"Saved {len(master):,} measurements to {cfg.spreadsheet_path}")


def run_plotting(cfg):
    """
    Run plotting functions over all exceedances
    """
    print('...Starting plotting workflow')
    
    # -- Load the inputs
    master = pd.read_excel(
        cfg.spreadsheet_path,
        sheet_name='DMS_Data',
        parse_dates=['GM_SAMP_COLLECTION_DATE']
        )
    exceeded = pd.read_excel(
        cfg.exceeded_path
        )
    
    # -- Plot all the exceeded wells
    plot_utils.plot_exceedance_charts(
        master,
        exceeded,
        cfg.output_folder,
        cfg.tag
        )
    
    
def main():
    # -- Load config settings
    cfg = Config()
    
    # -- Process data
    if cfg.analysis:
        run_analysis(cfg)
        
    # -- Run plotting functions
    if cfg.plotting:
        run_plotting(cfg)


if __name__ == "__main__":
    main()
