import os.path as osp

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

# Download shp zip for EU NUTS here:
# https://ec.europa.eu/eurostat/web/gisco/geodata/reference-data/administrative-units-statistical-units/nuts
geo_path = osp.join(osp.dirname(__file__), "shapes", "NUTS_RG_01M_2021_4326.shp")
geo_information = gpd.read_file(geo_path)
geo_information = geo_information.to_crs(4326)
nuts_levels = {
    "DE": 3,
    "NL": 1,
    "BE": 1,
    "LU": 1,
    "PO": 1,
    "DK": 1,
    "FR": 1,
    "CZ": 1,
    "AT": 1,
    "CH": 1,
}

data_frames = []
for key, value in nuts_levels.items():
    df = geo_information[
        (geo_information["CNTR_CODE"] == key) & (geo_information["LEVL_CODE"] == value)
    ]
    data_frames.append(df)

geo_information = gpd.GeoDataFrame(pd.concat(data_frames))
data_path = osp.join(osp.dirname(__file__), "data")
dwd_latitude = np.load(data_path + "/lat_coordinates.npy")
dwd_longitude = np.load(data_path + "/lon_coordinates.npy")


def create_nuts_map(coords):
    i, j = coords
    nut = "x"
    point = Point(dwd_longitude[i][j], dwd_latitude[i][j])
    zipping = [
        nuts_id
        for geom, nuts_id in zip(
            geo_information["geometry"], geo_information["NUTS_ID"]
        )
        if geom.contains(point)
    ]
    if not zipping:
        return "x"
    else:
        return zipping[0]


def main(db_uri):
    print("nuts_mapper has no main")
