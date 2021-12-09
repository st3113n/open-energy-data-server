import requests
import bz2
import pygrib
import pandas as pd
import numpy as np
import logging
import os
import sqlite3
from tqdm import tqdm

log = logging.getLogger('openDWD_cosmo')
log.setLevel(logging.INFO)


class OpenDWDCrawler:

    def __init__(self, engine, folder='./grb_files'):
        log.info('creating crawler')
        # base url and parameters to get the weather data from open dwd cosmo model
        self.base_url = 'https://opendata.dwd.de/climate_environment/REA/COSMO_REA6/hourly/2D/'
        self.codecs = dict(temperature_avg='T_2M/T_2M.2D.',
                           # temperature_max='TMAX_2M/TMAX_2M.2D.',     # not in hourly resolution
                           # temperature_min='TMIN_2M/TMIN_2M.2D.',     # not in hourly resolution
                           radiation_sum='ASOB_S/ASOB_S.2D.',
                           radiation_dif='ASWDIFD_S/ASWDIFD_S.2D.',
                           radiation_dir='ASWDIR_S/ASWDIR_S.2D.',
                           wind_meridional='V_10M/V_10M.2D.',
                           wind_zonal='U_10M/U_10M.2D.',
                           rain_con='RAIN_CON/RAIN_CON.2D.',
                           rain_gsp='RAIN_GSP/RAIN_GSP.2D.',
                           cloud_cover='CLCT/CLCT.2D.')

        # connection to open data platform fh aachen
        self.engine = engine
        if type(self.engine) != sqlite3.Connection:
            query = "CREATE TABLE IF NOT EXISTS public.cosmo( "\
                    "time timestamp without time zone NOT NULL, "\
                    "plz double precision, "\
                    "lat double precision, "\
                    "lon double precision, "\
                    "temperature_avg double precision, "\
                    "temperature_min double precision, "\
                    "temperature_max double precision, "\
                    "radiation_sum double precision, " \
                    "radiation_dif double precision, "\
                    "radiation_dir double precision, "\
                    "wind_meridional double precision, "\
                    "wind_zonal double precision, "\
                    "rain_con double precision,"\
                    "rain_gsp double precision, "\
                    "cloud_cover double precision, "\
                    "PRIMARY KEY (time , lat, lon));"
            self.engine.execute(query)

            query = "SELECT create_hypertable('cosmo', 'time', create_default_indexes => FALSE, " \
                    "if_not_exists => TRUE, migrate_data => TRUE);"

            self.engine.execute(query)

        self.weather_file = 'weather.grb'
        self.folder = folder

        if not os.path.exists(self.folder):
            os.makedirs(self.folder)

        self.plz3_matrix = np.load(r'./data/plz3_matrix.npy')
        self.plz5_matrix = np.load(r'./data/plz5_matrix.npy')

        log.info('crawler created')

    def __del__(self):
        for key in self.codecs.keys():
            try:
                file_name = f'{self.folder}/{key}_{self.weather_file}'
                os.remove(file_name)
            except Exception:
                log.exception('error cleaning up file')
        self.engine.dispose()

    def save_dwd_in_file(self, typ='temperature', year='1995', month='01'):
        # get weather parameter with given typ
        url = f'{self.base_url}{self.codecs[typ]}{year}{month}.grb.bz2'
        response = requests.get(url)
        log.info(f'get weather for {typ} with status code {response.status_code}')
        # unzip an save data in file (parameter_weather.grb)
        weather_data = bz2.decompress(response.content)
        file_name = f'{self.folder}/{typ}_{self.weather_file}'
        with open(file_name, 'wb') as file:
            file.write(weather_data)
        log.info(f'file {file_name} saved')

    def read_grb_file(self, hour, counter, typ):
        # load dwd file with given typ
        file_name = f'{self.folder}/{typ}_{self.weather_file}'
        weather_data = pygrib.open(file_name)
        # extract the selector to get the correct parameter
        selector = str(weather_data.readline()).split('1:')[1].split(':')[0]

        # slice the current hour with counter
        size = len(weather_data.select(name=selector))
        data_ = weather_data.select(name=selector)[counter]
        df = pd.DataFrame()
        # build dataframe
        df[typ] = data_.values.reshape(-1,)[self.plz5_matrix.reshape(-1,) > 0]
        lat_values, lon_values = data_.latlons()
        df['lat'] = lat_values.reshape(-1,)[self.plz5_matrix.reshape(-1,) > 0]
        df['lon'] = lon_values.reshape(-1,)[self.plz5_matrix.reshape(-1,) > 0]
        df['plz'] = self.plz5_matrix.reshape(-1,)[self.plz5_matrix.reshape(-1,) > 0]
        df['plz3'] = self.plz3_matrix.reshape(-1, )[self.plz3_matrix.reshape(-1, ) > 0]
        df['time'] = hour

        log.info(f'read data for typ: {typ} and hour: {counter} of {size} in month {hour.month}')
        weather_data.close()
        log.info('closed weather file')

        return df

    def write_weather_in_timescale(self, start='199501', end='199502'):
        # build date range with the given start and stop points with an monthly frequency
        date_range = pd.date_range(start=pd.to_datetime(start, format='%Y%m'), end=pd.to_datetime(end, format='%Y%m'),
                                   freq='MS')

        for date in tqdm(date_range):
            try:
                # for each month get the dwd data for all given parameters in __init__
                for parameter in self.codecs.keys():
                    month = f'{date.month:02d}'
                    self.save_dwd_in_file(year=str(date.year), month=month, typ=parameter)

                # build dataframe and write data for each hour in month
                hours = pd.date_range(start=pd.to_datetime(date), end=pd.to_datetime(date) + pd.DateOffset(months=1),
                                      freq='h')[:-1]

                counter = 0                                                 # month hour counter
                for hour in hours:
                    init_df = True                                          # bool for first df
                    df = pd.DataFrame()                                     # init empty dataframe
                    for parameter in self.codecs.keys():
                        if init_df:
                            df = self.read_grb_file(hour, counter, parameter)
                            init_df = False
                        else:
                            df[parameter] = self.read_grb_file(hour, counter, parameter)[parameter]

                    log.info('build dataset for import')

                    index = pd.MultiIndex.from_arrays([df['time'], df['lat'], df['lon']],
                                                      names=['timestamp', 'lat', 'lon'])
                    df.index = index
                    del df['lon']
                    del df['lat']
                    del df['time']
                    log.info(f'built data for hour {counter} in {date.month_name()} and start import to postgres')
                    df.to_sql('cosmo', con=self.engine, if_exists='append')
                    log.info('import in postgres complete --> start with next hour')
                    counter += 1

            except Exception:
                log.exception(f'could not read {date}')