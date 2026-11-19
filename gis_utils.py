# -*- coding: utf-8 -*-
"""
Created on Wed Nov 11 14:31:59 2026

GIS export and analysis helpers

@author: shjordan
"""

import geopandas as gpd
import pandas as pd


def get_nearby_well_locations(master, well_id, radius_miles=3):
    """
    Return all current RMS well locations within radius_miles of a well.

    The source well is included at zero miles. Distances use UTM zone 11N,
    where coordinates are measured in meters.
    """
    # -- Build one location per well from the current RMS master
    locations = master[["GM_WELL_ID", "Lat", "Long"]].drop_duplicates().copy()
    locations["Lat"] = pd.to_numeric(locations["Lat"], errors="coerce")
    locations["Long"] = pd.to_numeric(locations["Long"], errors="coerce")

    conflicts = locations.loc[
        locations["GM_WELL_ID"].duplicated(keep=False), "GM_WELL_ID"
        ].unique()
    if len(conflicts):
        raise ValueError(f"Conflicting coordinates for RMS wells: {list(conflicts)}")

    if well_id not in locations["GM_WELL_ID"].values:
        raise ValueError(f"Well {well_id} is not in the current RMS master")

    source = locations.loc[locations["GM_WELL_ID"] == well_id]
    if source[["Lat", "Long"]].isna().any(axis=None):
        raise ValueError(f"Well {well_id} has no usable coordinates")

    locations = locations.dropna(subset=["Lat", "Long"])
    points = gpd.GeoDataFrame(
        locations,
        geometry=gpd.points_from_xy(locations["Long"], locations["Lat"]),
        crs="EPSG:4326"
        ).to_crs("EPSG:32611")

    # -- Measure from the exceeded well and keep sites inside the radius
    source_point = points.loc[points["GM_WELL_ID"] == well_id, "geometry"].iloc[0]
    points["distance_miles"] = points.distance(source_point) / 1609.344
    nearby = points.loc[
        points["distance_miles"] <= radius_miles,
        ["GM_WELL_ID", "Lat", "Long", "distance_miles"]
        ]

    return nearby.sort_values("distance_miles").reset_index(drop=True)


def get_nearby_constituent_data(master, well_id, constituent, radius_miles=3):
    """
    Return dated results for a constituent at wells within radius_miles.
    """
    # -- Find all nearby RMS wells
    nearby = get_nearby_well_locations(master, well_id, radius_miles)

    # -- Keep only measurements available for this constituent
    data = master.loc[
        master["GM_CHEMICAL_NAME"].eq(constituent)
        & master["GM_RESULT"].notna()
        & master["GM_SAMP_COLLECTION_DATE"].notna()
        ].merge(
            nearby[["GM_WELL_ID", "distance_miles"]],
            on="GM_WELL_ID",
            how="inner",
            validate="many_to_one"
            )

    return data.sort_values(
        ["distance_miles", "GM_WELL_ID", "GM_SAMP_COLLECTION_DATE"]
        ).reset_index(drop=True)

