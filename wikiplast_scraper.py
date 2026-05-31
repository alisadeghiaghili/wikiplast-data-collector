# -*- coding: utf-8 -*-
"""
Wikiplast Polymer Price Scraper
================================
Fetches polymer raw-material prices from wikiplast.ir and pushes them
to SQL Server using the same Config / DatabaseConfig pattern as ice-data-collector.

Extracted columns:
    - عنوان       (product title)
    - زمان        (timestamp)
    - قیمت (ریال) (price in IRR)
    - پتروشیمی   (petrochemical company)

Dependencies: requests, beautifulsoup4, pandas, sqlalchemy, pyodbc
No Selenium required – the data is served as static HTML.

Author : Ali Sadeghi Aghili
Created: 2026-05-31
"""

import logging
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import requests
import pandas as pd
from bs4 import BeautifulSoup

from sqlalchemy import Table, Column, MetaData, inspect
from sqlalchemy import NVARCHAR, BigInteger, CHAR
from sqlalchemy.exc import SQLAlchemyError

from config import Config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDGET_URL = "https://wikiplast.ir/prices/5/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa,en;q=0.9",
    "Referer": "https://wikiplast.ir/",
}
REQUEST_TIMEOUT: int = 30

COL_TITLE = "عنوان"
COL_PRICE = "قیمت (ریال)"
COL_TIME  = "زمان"
COL_PETRO = "پتروشیمی"
TARGET_COLS = [COL_TITLE, COL_TIME, COL_PRICE, COL_PETRO]


# ---------------------------------------------------------------------------
# Logging  (identical pattern to ice_scraper.py)
# ---------------------------------------------------------------------------

def _setup_logger(name: str, config: Config) -> logging.Logger:
    log_dir = Path(config.logging.directory)
    log_dir.mkdir(exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(config.logging.level)
    logger.handlers.clear()

    fmt_detailed = logging.Formatter(config.logging.format_detailed)
    fmt_simple   = logging.Formatter(config.logging.format_simple)

    fh = logging.FileHandler(
        log_dir / f"wikiplast_{datetime.now().strftime('%Y%m%d')}.log",
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_detailed)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(config.logging.level)
    ch.setFormatter(fmt_simple)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_html_from_js(js_text: str) -> str:
    """Unwrap document.write(\"...\") to get the inner HTML string."""
    match = re.search(r'document\.write\("(.+)"\)', js_text, re.DOTALL)
    if match:
        raw = match.group(1)
        raw = raw.replace('\\\\', '\\').replace('\\"', '"').replace("\\'"  , "'")
        return raw
    return js_text


# ---------------------------------------------------------------------------
# Core scraper class
# ---------------------------------------------------------------------------

class WikiplastScraper:
    """
    Scraper for polymer raw-material prices published on wikiplast.ir.

    Usage
    -----
    scraper = WikiplastScraper()
    success, df = scraper.scrape_and_store()
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_env()
        self.logger = _setup_logger(self.__class__.__name__, self.config)

        # SQLAlchemy table schema (mirrors ice_scraper.py pattern)
        self.metadata = MetaData()
        self._define_table_schema()

        self.logger.info("WikiplastScraper initialised successfully")

    # ------------------------------------------------------------------
    # Schema definition
    # ------------------------------------------------------------------

    def _define_table_schema(self) -> None:
        """Define DB table using SQLAlchemy 2.0 Table construct."""
        self.table = Table(
            self.config.database.table_name,
            self.metadata,
            Column("Title",      NVARCHAR(200), nullable=False),
            Column("Time",       NVARCHAR(50),  nullable=False),
            Column("Price",      BigInteger,    nullable=False),
            Column("Petro",      NVARCHAR(200), nullable=False),
            Column("ScrapeDate", CHAR(10),      nullable=False),
            Column("ScrapeTime", CHAR(8),       nullable=False),
            extend_existing=True,
        )
        self.logger.debug(f"Table schema defined: {self.config.database.table_name}")

    # ------------------------------------------------------------------
    # Scraping steps
    # ------------------------------------------------------------------

    def _fetch_page(self) -> str:
        self.logger.info(f"Fetching: {WIDGET_URL}")
        resp = requests.get(WIDGET_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        self.logger.info(
            f"Response: HTTP {resp.status_code}, {len(resp.text):,} chars"
        )
        return resp.text

    def _parse_html(self, raw: str) -> BeautifulSoup:
        html = _extract_html_from_js(raw) if "document.write(" in raw else raw
        soup = BeautifulSoup(html, "html.parser")
        self.logger.debug("HTML parsed successfully")
        return soup

    def _extract_table(self, soup: BeautifulSoup) -> pd.DataFrame:
        """
        Locate the pricing <table> and build a raw DataFrame.

        Widget column order (left-to-right):
            0: عنوان | 1: قیمت (ریال) | 2: زمان | 3: پتروشیمی | 4+: other
        """
        table = soup.find("table")
        if table is None:
            raise ValueError("No <table> found in the fetched content.")

        rows = table.find_all("tr")
        self.logger.info(f"Found {len(rows)} rows in table (including headers).")

        records = []
        for row in rows:
            cells = row.find_all("td")
            if not cells or len(cells) < 4:
                continue
            if row.get("class") and "ratehead" in row.get("class", []):
                continue
            if cells[0].get("colspan"):
                continue

            title = cells[0].get_text(strip=True)
            price = cells[1].get_text(strip=True)
            time_ = cells[2].get_text(strip=True)
            petro = cells[3].get_text(strip=True)

            if not title or title == COL_TITLE:
                continue

            records.append({
                COL_TITLE: title,
                COL_TIME:  time_,
                COL_PRICE: price,
                COL_PETRO: petro,
            })

        if not records:
            raise ValueError("Table parsed but no data rows were extracted.")

        df = pd.DataFrame(records, columns=TARGET_COLS)
        self.logger.info(f"Extracted {len(df)} product records.")
        return df

    def _process_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and enrich the raw DataFrame before DB insert."""
        df[COL_PRICE] = (
            df[COL_PRICE]
            .str.replace(",",  "", regex=False)
            .str.replace("٬", "", regex=False)   # Persian thousand-separator
            .pipe(pd.to_numeric, errors="coerce")
            .fillna(0)
            .astype("int64")
        )

        now = datetime.now()
        df["ScrapeDate"] = now.strftime("%Y-%m-%d")
        df["ScrapeTime"] = now.strftime("%H:%M:%S")

        df = df.rename(columns={
            COL_TITLE: "Title",
            COL_TIME:  "Time",
            COL_PRICE: "Price",
            COL_PETRO: "Petro",
        })

        initial = len(df)
        df = df.drop_duplicates(subset=["Title", "Time"], keep="first")
        removed = initial - len(df)
        if removed:
            self.logger.warning(f"Removed {removed} duplicate rows in batch.")

        self.logger.info(f"Data processing complete: {len(df)} rows ready for DB.")
        return df

    # ------------------------------------------------------------------
    # Database storage  (identical pattern to ice_scraper._save_to_database)
    # ------------------------------------------------------------------

    def _save_to_database(self, df: pd.DataFrame) -> bool:
        """
        Push processed DataFrame to SQL Server using SQLAlchemy 2.0.

        Uses the same create_engine() / inspect / to_sql pattern as
        ice_scraper.py so the two scrapers share identical DB behaviour.
        """
        try:
            self.logger.info(
                f"Saving {len(df)} rows to "
                f"'{self.config.database.table_name}'..."
            )

            engine = self.config.create_engine()

            inspector = inspect(engine)
            if not inspector.has_table(self.config.database.table_name):
                self.logger.info(
                    f"Table not found – creating: {self.config.database.table_name}"
                )
                self.metadata.create_all(engine)

            df.to_sql(
                name=self.config.database.table_name,
                con=engine,
                if_exists="append",
                index=False,
                method="multi",
                chunksize=1000,
            )

            engine.dispose()
            self.logger.info("Data saved to database successfully.")
            return True

        except SQLAlchemyError as e:
            self.logger.error(f"Database error: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error saving to database: {e}")
            return False

    # ------------------------------------------------------------------
    # Public orchestrator  (mirrors ice_scraper.scrape_and_store)
    # ------------------------------------------------------------------

    def scrape_and_store(self) -> Tuple[bool, Optional[pd.DataFrame]]:
        """
        Execute the full scrape → process → store workflow.

        Returns
        -------
        (success: bool, df: pd.DataFrame | None)
        """
        start = datetime.now()
        self.logger.info("─── Wikiplast scraping workflow started ───")

        try:
            raw  = self._fetch_page()
            soup = self._parse_html(raw)
            df   = self._extract_table(soup)
            df   = self._process_data(df)

            success = self._save_to_database(df)

            elapsed = (datetime.now() - start).total_seconds()
            self.logger.info(f"Workflow completed in {elapsed:.2f}s")
            return success, df if success else None

        except requests.HTTPError as e:
            self.logger.error(f"HTTP error: {e}")
        except requests.RequestException as e:
            self.logger.error(f"Network error: {e}")
        except ValueError as e:
            self.logger.error(f"Parsing error: {e}")
        except Exception as e:
            self.logger.exception(f"Unexpected error: {e}")

        return False, None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        config = Config.from_env()

        if "--show-config" in sys.argv:
            config.print_status()
            return

        scraper = WikiplastScraper(config)
        success, df = scraper.scrape_and_store()

        if success:
            print(f"\n✅ Scraping completed successfully! Saved {len(df)} records.")
            sys.exit(0)
        else:
            print("❌ Scraping failed. Check logs for details.")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except (ValueError, FileNotFoundError) as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        logging.exception("Unexpected error in main()")
        sys.exit(1)


if __name__ == "__main__":
    main()
