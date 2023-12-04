# SPDX-FileCopyrightText: Florian Maurer, Jonathan Sejdija
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import logging
import os
from datetime import date, timedelta

import pandas as pd
import requests
from sqlalchemy import create_engine, text

from crawler.config import db_uri

log = logging.getLogger("smard")
default_start_date = "2023-01-01 22:45:00" # "2023-11-26 22:45:00"


class SmardCrawler:
    def __init__(self, db_uri):
        self.engine = create_engine(db_uri)

    def create_table(self):
        try:
            query_create_hypertable = "SELECT create_hypertable('smard', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);"
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS smard( "
                        "timestamp timestamp without time zone NOT NULL, "
                        "commodity_id text, "
                        "commodity_name text, "
                        "mwh double precision, "
                        "PRIMARY KEY (timestamp , commodity_id));"
                    )
                )
                conn.execute(text(query_create_hypertable))
            log.info(f"created hypertable smard")
        except Exception as e:
            log.error(f"could not create hypertable: {e}")

    def get_data_per_commodity(self):
        energy = ["strom", "wasser", "waerme"]
        end_date = date.today().strftime("%d.%m.%Y")
        keys = {
                    # 411: 'Prognostizierter Stromverbrauch',
                    410: 'Realisierter Stromverbrauch',
                    4066: 'Biomasse',
                    1226: 'Wasserkraft',
                    1225: 'Wind Offshore',
                    4067: 'Wind Onshore',
                    4068: 'Photovoltaik',
                    1228: 'Sonstige Erneuerbare',
                    1223: 'Braunkohle',
                    4071: 'Erdgas',
                    4070: 'Pumpspeicher',
                    1227: 'Sonstige Konventionelle',
                    4069: 'Steinkohle'
                    # 5097: 'Prognostizierte Erzeugung PV und Wind Day-Ahead'
                }

        for commodity_id, commodity_name in keys.items():
            start_date = self.select_latest(commodity_id) + timedelta(minutes=15)
            # start_date_tz to unix time
            start_date_unix = int(start_date.timestamp() * 1000)
            url = f"https://www.smard.de/app/chart_data/{commodity_id}/DE/{commodity_id}_DE_quarterhour_{start_date_unix}.json"
            log.info(url)
            response = requests.get(url)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                log.error(f"Could not get data for commodity: {commodity_id} {e}")
                continue
            data = json.loads(response.text)
            timeseries = pd.DataFrame.from_dict(data["series"])
            if timeseries.empty:
                log.info(f"Received empty data for commodity: {commodity_id}")
                continue
            timeseries[0] = pd.to_datetime(timeseries[0], unit="ms", utc=True)
            timeseries.columns = ["timestamp", "mwh"]
            timeseries["commodity_id"] = commodity_id
            timeseries["commodity_name"] = commodity_name
            timeseries = timeseries.dropna(subset='mwh')

            yield timeseries

    def select_latest(self, commodity_id) -> pd.Timestamp:
        # day = default_start_date
        # today = date.today().strftime('%d.%m.%Y')
        # sql = f"select timestamp from smard where timestamp > '{day}' and timestamp < '{today}' order by timestamp desc limit 1"
        sql = f"select timestamp from smard where commodity_id='{commodity_id}' order by timestamp desc limit 1"
        try:
            with self.engine.begin() as conn:
                latest = pd.read_sql(sql, conn, parse_dates=["timestamp"]).values[0][0]
            latest = pd.to_datetime(latest, unit="ns")
            log.info(f"The latest date in the database is {latest}")
            return latest
        except Exception as e:
            log.info(f"Using the default start date {e}")
            return pd.to_datetime(default_start_date)

    def feed(self):
        for data_for_commodity in self.get_data_per_commodity():
            if data_for_commodity.empty:
                continue
            data_for_commodity = data_for_commodity.set_index(
                ["timestamp", "commodity_id"]
            )
            # delete timezone duplicate
            # https://stackoverflow.com/a/34297689
            data_for_commodity = data_for_commodity[
                ~data_for_commodity.index.duplicated(keep="first")
            ]

            log.info(data_for_commodity)
            with self.engine.begin() as conn:
                data_for_commodity.to_sql("smard", con=conn, if_exists="append")


def main(db_uri):
    ec = SmardCrawler(db_uri)
    ec.create_table()
    ec.feed()


if __name__ == "__main__":
    logging.basicConfig(filename="smard.log", encoding="utf-8", level=logging.INFO)
    # db_uri = 'sqlite:///./data/smard.db'
    main(db_uri("smard"))
