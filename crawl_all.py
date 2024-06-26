#!/usr/bin/env python3
# SPDX-FileCopyrightText: Florian Maurer, Christian Rieke
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import logging
import os.path as osp
from glob import glob

from crawler.config import db_uri

log = logging.getLogger("crawler")
log.setLevel(logging.INFO)


def import_and_exec(module, db_uri):
    """
    imports and executes the main(db_uri) method of each module.
    A module must reside in the crawler folder.
    """
    try:
        imported_module = __import__(f"crawler.{module}", fromlist=["eex.main"])
        imported_module.main(db_uri)
        log.info(f"executed main from {module}")
    except AttributeError as e:
        log.error(repr(e))
    except Exception as e:
        log.error(f"could not execute main of crawler: {module} - {e}")


def get_available_crawlers():
    crawler_path = osp.join(osp.dirname(__file__), "crawler")

    crawlers = []
    for f in glob(crawler_path + "/*.py"):
        crawler = osp.basename(f)[:-3]
        if crawler not in [
            "__init__",
            "base_crawler",
            "config",
            "config_example",
            "axxteq",
            "enet",
            "dwd",
        ]:
            crawlers.append(crawler)
    crawlers.sort()
    return crawlers


if __name__ == "__main__":
    logging.basicConfig()
    # remove crawlers without publicly available data
    available_crawlers = get_available_crawlers()
    crawlers = sorted(available_crawlers)
    for crawler_name in crawlers:
        if crawler_name in available_crawlers:
            log.info(f"executing crawler {crawler_name}")
            dbname = crawler_name.replace("_crawler", "")
            # the move to schemas does not allow to have multiple gis based databases
            # all gis based databases now have to write into the public schema
            if dbname == "nuts_mapper":
                dbname == "public"
            import_and_exec(crawler_name, db_uri(dbname))
