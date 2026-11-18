# -*- coding: utf-8 -*-
"""
Created on Wed Nov 11 14:28:01 2026

Plotting helpers for Kaweah GWQ Data

@author: shjordan
"""

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.dates import DateFormatter
from matplotlib.ticker import MaxNLocator
import contextily as cx
import geopandas as gpd


def plot_exceedance_charts(master,exceeded,out_path,season):
    """
    Create the stand-alone chart for each exceeded well/constituent combination
    """
    pdf_path = out_path / 'pdf' / f'all_exceedances_{season}.pdf'
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # -- Loop through and plot all exceedances
    with PdfPages(pdf_path) as pdf:
        for _,row in exceeded.iterrows():
            # Grab all data for this entry
            well_id = row['GM_WELL_ID']
            constit = row['constituent']
            constit_abb = row["constituent_abb"]
            print(f"...Plotting exceedance: {well_id}, {constit}")
            well_dat = master.loc[
                (master['GM_WELL_ID'] == well_id) &
                (master['GM_CHEMICAL_NAME'] == constit)
                ]
            well_dat = well_dat.set_index('GM_SAMP_COLLECTION_DATE').sort_index()
            # TODO: Review this
            well_dat = well_dat.loc[well_dat['GM_RESULT_MODIFIER'].isin(['=','<'])]
            modifier = well_dat['GM_RESULT_MODIFIER'].astype('string').str.strip()
            detected = well_dat.loc[modifier.eq('=')]
            nd = well_dat.loc[modifier.eq('<')]
            # unclassified = well_dat.loc[
            #     ~modifier.isin(['=', '<']) & well_dat['GM_RESULT'].notna()
            #     ]
            mcl = row['MCL']
            units = row['MCL_UNITS']
            
            # Init plot
            fig,ax = plt.subplots(figsize=(7,4))
            
            # Plot all data as dashed line w/ no markers
            ax.plot(
                well_dat.index,
                well_dat['GM_RESULT'],
                ls='--',
                color='grey',
                alpha=0.5,
                lw=0.9
                )
            # Plot detected values
            ax.plot(
                detected.index,
                detected['GM_RESULT'],
                marker='o',
                color='green',
                markeredgecolor='black',
                markeredgewidth=0.6,
                ls='',
                label='Measurements'
                )
            # Plot non-detects
            if not nd.empty:
                ax.plot(
                    nd.index,
                    nd['GM_RESULT'],
                    marker='o',
                    markerfacecolor='none',
                    markeredgecolor='black',
                    markeredgewidth=0.6,
                    ls='',
                    label='Non-Detect'
                    )
            # Plot historical results whose detection status is unknown.
            # if not unclassified.empty:
            #     ax.plot(
            #         unclassified.index,
            #         unclassified['GM_RESULT'],
            #         marker='d',
            #         markerfacecolor='none',
            #         color='grey',
            #         ls='',
            #         label='Unknown detection status'
            #         )
            # Plot MCL
            ax.axhline(
                mcl,
                color='maroon',
                label='MCL',
                ls='--'
                )
            # Format figure
            ax.set_xlabel('Sample Date')
            ax.set_ylabel(f'Analytical Result [{units}]')
            if not nd.empty:
                ax.legend(bbox_to_anchor=(0.9,-0.24),ncols=3)
            else:
                ax.legend(bbox_to_anchor=(0.75,-0.24),ncols=2)
            ax.grid()
            ax.xaxis.set_major_formatter(DateFormatter('%b-%Y'))
            ax.tick_params(axis='x',labelrotation=30)
            y_locator = MaxNLocator(nbins=5, steps=[1, 2, 2.5, 5, 10])
            y_ticks = y_locator.tick_values(0, ax.get_ylim()[1])
            ax.set_yticks(y_ticks)
            ax.set_ylim(0, y_ticks[-1])
            ax.set_title(f"{well_id}: {constit_abb}")
            
            # Save figure
            out_folder = out_path / 'png' / f"{well_id.replace(' ','_')}_{constit.replace(' ','_')}"
            out_folder.mkdir(parents=True, exist_ok=True)
            fig.savefig(
                out_folder / "exceedance_plot.png", 
                bbox_inches='tight',
                dpi=250
                )
            pdf.savefig(
                fig,
                bbox_inches='tight',
                dpi=250
                )
            plt.close(fig)
    
    
def plot_3_mile_figures():
    ...
