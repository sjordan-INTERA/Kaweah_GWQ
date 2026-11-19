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
from gis_utils import get_nearby_constituent_data, get_nearby_well_locations


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
            well_dat = well_dat.loc[well_dat['GM_RESULT_MODIFIER'].isin(['=','<'])]
            modifier = well_dat['GM_RESULT_MODIFIER'].astype('string').str.strip()
            detected = well_dat.loc[modifier.eq('=')]
            nd = well_dat.loc[modifier.eq('<')]
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
                
            # Plot MCL
            ax.axhline(
                mcl,
                color='maroon',
                label='MCL',
                ls='--'
                )
            
            # Format figure
            # ax.set_xlabel('Sample Date')
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
            
            # -- Create three mile buffer constituent figures
            plot_3_mile_figures(
                master, well_id, constit, constit_abb, mcl, units, out_folder
             )

    
def plot_3_mile_figures(master, well_id, constit, constit_abb, mcl, units, out_folder):
    """
    Select the series to use when plotting nearby wells for an exceedance.

    Returns measurement rows with distance_miles; add plotting below when ready.
    """
    # -- Find wells within three miles that have dated results for this constituent
    nearby_data = get_nearby_constituent_data(master, well_id, constit)
    nearby_locations = get_nearby_well_locations(master, well_id)
    map_points = gpd.GeoDataFrame(
        nearby_locations,
        geometry=gpd.points_from_xy(
            nearby_locations['Long'], nearby_locations['Lat']
            ),
        crs='EPSG:4326'
        ).to_crs('EPSG:3857')
    source_point = map_points.loc[
        map_points['GM_WELL_ID'] == well_id
        ].to_crs('EPSG:32611').geometry.iloc[0]
    radius = gpd.GeoSeries(
        [source_point.buffer(3 * 1609.344)], crs='EPSG:32611'
        ).to_crs(map_points.crs)
    center = map_points.loc[
        map_points['GM_WELL_ID'] == well_id, 'geometry'
        ].iloc[0]
    minx, miny, maxx, maxy = radius.total_bounds
    map_half_width = max(maxx - minx, maxy - miny) * 0.55
    neighbor_ids = nearby_data.loc[
        nearby_data['GM_WELL_ID'] != well_id, 'GM_WELL_ID'
        ].unique()

    if len(neighbor_ids) == 0:
        print(f"...No other wells within 3 miles with {constit} data for {well_id}")
        return

    # -- Make a plot for each well within three miles
    for _id in neighbor_ids:
        
        fig,ax = plt.subplots(1,2,figsize=(11,6),width_ratios=[0.66,0.34])
        
        # -- Plot well
        dat = nearby_data.loc[nearby_data['GM_WELL_ID'] == _id]
        dat = dat.set_index('GM_SAMP_COLLECTION_DATE').sort_index()
        dat['GM_RESULT'].plot(
            ax=ax[0],
            label=_id,
            marker='o',
            color='green',
            markeredgecolor='black',
            markeredgewidth=0.6,
            ls='',
            )
        dat['GM_RESULT'].plot(
            ax=ax[0],
            color='green',
            label='_nolegend_',
            ls='--',
            alpha=0.5,
            lw=0.8
            )
        
        # Plot current source well
        dat = nearby_data.loc[nearby_data['GM_WELL_ID'] == well_id]
        dat = dat.set_index('GM_SAMP_COLLECTION_DATE').sort_index()
        dat['GM_RESULT'].plot(
            ax=ax[0],
            label=f"{well_id} (case-sheet well)",
            marker='o',
            color='orange',
            markeredgecolor='black',
            markeredgewidth=0.6,
            ls='',
            )
        dat['GM_RESULT'].plot(
            ax=ax[0],
            color='orange',
            label='_nolegend_',
            ls='--',
            alpha=0.5,
            lw=0.8
            )
        
        # MCL
        ax[0].axhline(
            mcl,
            color='maroon',
            label='MCL',
            ls='--',
            )
        
        # Format
        fig.suptitle(
            f"{constit_abb}: 3-mile Buffer Time Series"
            )
        ax[0].set_xlabel('')
        ax[0].set_ylabel(f'Analytical Result [{units}]',fontsize=11)
        ax[0].grid()
        ax[0].xaxis.set_major_formatter(DateFormatter('%b-%Y'))
        ax[0].tick_params(axis='x',labelrotation=30)
        y_lims = ax[0].get_ylim()
        ax[0].set_ylim(0, y_lims[1] + (y_lims[1] * 0.25))
        ax[0].legend(loc=2,fontsize=9)

        # -- Map the three-mile radius and highlight the plotted pair
        radius.boundary.plot(
            ax=ax[1], color='black', linewidth=1.2,
            label='3-mile radius', zorder=2
            )
        other_wells = map_points.loc[
            ~map_points['GM_WELL_ID'].isin([well_id, _id])
            ]
        if not other_wells.empty:
            other_wells.plot(
                ax=ax[1],
                color='steelblue',
                marker='o',
                markersize=35,
                edgecolor='black',
                linewidth=0.5,
                label='Other wells', 
                zorder=3
                )
        map_points.loc[map_points['GM_WELL_ID'] == well_id].plot(
            ax=ax[1], 
            color='orange',
            marker='*',
            markersize=180,
            edgecolor='black',
            linewidth=0.8,
            label='Case-sheet well',
            zorder=5
            )
        map_points.loc[map_points['GM_WELL_ID'] == _id].plot(
            ax=ax[1], 
            color='green',
            marker='D',
            markersize=75,
            edgecolor='black', 
            linewidth=0.8, 
            label=_id, 
            zorder=4
            )

        ax[1].set_xlim(center.x - map_half_width, center.x + map_half_width)
        ax[1].set_ylim(center.y - map_half_width, center.y + map_half_width)
        ax[1].set_aspect('equal')
        # cx.add_basemap(
        #     ax=ax[1],
        #     source=cx.providers.OpenStreetMap.Mapnik,
        #     zoom_adjust=1,
        #     attribution_size=6
        #     )
        ax[1].set_title('Wells within 3 miles')
        ax[1].set_xticks([])
        ax[1].set_yticks([])
        legend = ax[1].legend(
            bbox_to_anchor=(1.07,-0.02) if len(_id) > 15 else (1.02,-0.02),
            ncols=2
            )
        legend.get_frame().set_edgecolor('black')
        fig.tight_layout()
        
        # -- Savefig
        fig.savefig(
            out_folder / f"{_id}_3_mile.png",
            bbox_inches='tight',
            dpi=250
            )
        plt.close(fig)
        
    
