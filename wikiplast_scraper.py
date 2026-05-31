# -*- coding: utf-8 -*-
"""
Wikiplast Petrochemical Price Scraper
======================================
Fetches polymer raw-material prices from wikiplast.ir and returns them
as a clean pandas DataFrame using the same Config / safe_request() pattern
as ice-data-collector and tgju-data-collector.

The endpoint ``wikiplast.ir/pricescodeime`` returns a JavaScript snippet
like::

    document.write("<link rel='stylesheet' ...><div id='econorate'><table>...</table></div>")

This scraper extracts the HTML string from inside ``document.write(...)``
and parses the embedded ``<table>`` with BeautifulSoup — no browser
automation required.

Extracted columns:
    - عنوان       (product title)
    - زمان        (price timestamp from source)
    - قیمت (ریال) (price in IRR)
    - پتروشیمی   (petrochemical company)

Dependencies: requests, beautifulsoup4, pandas

Author : Ali Sadeghi Aghili
Created: 2026-05-31

Usage patterns
--------------
# 1. Standalone – no config needed
result = WikiplastScraper().scrape()
if result:
    print(result.df)

# 2. Tuple-unpacking (backward compatible)
success, df = WikiplastScraper().scrape()
if success:
    print(df)

# 3. With app-level Config from config.py
from config import Config
config = Config.from_env()
result = WikiplastScraper(config=config).scrape()

# 4. With ScraperConfig for full HTTP control
from wikiplast_scraper import ScraperConfig
scraper_cfg = ScraperConfig(max_retries=5, timeout=60, output_csv="out.csv")
result = WikiplastScraper(config=scraper_cfg).scrape()
"""

import re
import sys
import logging
import time
import random
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple

import requests
import pandas as pd
from bs4 import BeautifulSoup

# ===== LOGGING CONFIGURATION =====

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wikiplast_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== CONFIGURATION CONSTANTS =====

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
RETRY_DELAY_MIN = 2
RETRY_DELAY_JITTER = 1

# The endpoint returns a JS file containing document.write("<html>...").
# The HTML table with prices is embedded inside the JS string.
WIKIPLAST_WIDGET_URL = "https://wikiplast.ir/pricescodeime"

# Column names and their index positions inside each <tr>.
OUTPUT_COLUMNS = ["عنوان", "زمان", "قیمت (ریال)", "پتروشیمی"]
COLUMN_INDICES: dict[str, int] = {
    "عنوان": 0,
    "قیمت (ریال)": 1,
    "زمان": 2,
    "پتروشیمی": 3,
}
_MIN_REQUIRED_CELLS = max(COLUMN_INDICES.values()) + 1  # 4


# ===== SCRAPER-SPECIFIC CONFIGURATION =====

@dataclass
class ScraperConfig:
    """
    HTTP-level configuration for WikiplastScraper.

    Attributes:
        url (str): Target URL for the price widget JS endpoint.
        max_retries (int): HTTP retry attempts before giving up.
        timeout (int): Per-request timeout in seconds.
        output_csv (Optional[str]): Path for CSV export; None disables export.
        user_agent (str): User-Agent header sent with each request.
    """
    url: str = WIKIPLAST_WIDGET_URL
    max_retries: int = DEFAULT_MAX_RETRIES
    timeout: int = DEFAULT_TIMEOUT
    output_csv: Optional[str] = None
    user_agent: str = DEFAULT_USER_AGENT


def _resolve_scraper_config(config) -> ScraperConfig:
    """Normalise any config object into a ScraperConfig."""
    if config is None:
        return ScraperConfig()
    if isinstance(config, ScraperConfig):
        return config
    try:
        max_retries = config.retry.max_attempts
    except AttributeError:
        max_retries = DEFAULT_MAX_RETRIES
    try:
        timeout = config.database.connection_timeout
    except AttributeError:
        timeout = DEFAULT_TIMEOUT
    logger.debug(
        "App-level Config mapped: retry.max_attempts=%d, connection_timeout=%d",
        max_retries, timeout,
    )
    return ScraperConfig(max_retries=max_retries, timeout=timeout)


# ===== RESULT CONTAINER =====

class ScrapeResult:
    """
    Container returned by ``WikiplastScraper.scrape()``.

    Supports attribute access and tuple unpacking::

        result = scraper.scrape()
        if result:
            print(result.df)

        success, df = scraper.scrape()
    """

    __slots__ = ("success", "df", "rows_fetched", "error")

    def __init__(
        self,
        success: bool,
        df: Optional[pd.DataFrame] = None,
        rows_fetched: int = 0,
        error: Optional[str] = None,
    ) -> None:
        self.success = success
        self.df = df
        self.rows_fetched = rows_fetched
        self.error = error

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self) -> Iterator:
        yield self.success
        yield self.df

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAILED: {self.error}"
        return f"ScrapeResult({status}, rows={self.rows_fetched})"


# ===== SAFE HTTP REQUEST MODULE =====

def safe_request(
    url: str,
    headers: Optional[dict] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[requests.Response]:
    """
    Execute an HTTP GET with automatic retry and back-off.

    Returns the Response on success, or None after all retries are exhausted.
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            logger.debug("Fetched %s (attempt %d)", url, attempt + 1)
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as err:
            logger.warning("Attempt %d/%d failed for %s: %s", attempt + 1, max_retries, url, err)
        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as err:
            logger.warning("Attempt %d/%d failed for %s: %s", attempt + 1, max_retries, url, err)
        if attempt < max_retries - 1:
            delay = RETRY_DELAY_MIN + random.random() * RETRY_DELAY_JITTER
            logger.debug("Waiting %.2fs before retry…", delay)
            time.sleep(delay)
    logger.error("Failed to fetch %s after %d retries.", url, max_retries)
    return None


# ===== JS UNWRAP MODULE =====

def _extract_html_from_js(js_text: str) -> Optional[str]:
    """
    Extract the HTML string from inside a ``document.write("...")`` call.

    The wikiplast.ir/pricescodeime endpoint returns JavaScript like::

        document.write("<link ...><div id='econorate'><table>...</table></div>")

    This function strips the ``document.write(...)`` wrapper and returns
    the raw HTML string so it can be fed to BeautifulSoup.

    Args:
        js_text (str): Raw response text from the widget endpoint.

    Returns:
        str: Extracted HTML content, or None if the pattern is not found.
    """
    match = re.search(r'document\.write\("(.+)"\)', js_text, re.DOTALL)
    if not match:
        logger.error(
            "Could not find document.write(...) pattern in response. "
            "Response preview: %s", js_text[:300]
        )
        return None
    # Unescape JS-escaped double quotes that may appear inside the string
    html = match.group(1).replace('\\"', '"')
    logger.debug("Extracted %d chars of HTML from document.write().", len(html))
    return html


# ===== HTML PARSING MODULE =====

def _parse_price_table(html: str) -> Optional[pd.DataFrame]:
    """
    Parse the Wikiplast price HTML table into a structured DataFrame.

    Skips:
    - Header rows (``class='ratehead'``)
    - Banner rows (any cell with a ``colspan`` attribute)
    - Rows with fewer cells than required

    Args:
        html (str): HTML string containing the price ``<table>``.

    Returns:
        pd.DataFrame or None.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        logger.error("No <table> element found in extracted HTML.")
        return None

    rows_data = []
    for tr in table.find_all("tr"):
        if "ratehead" in tr.get("class", []):
            continue
        cells = tr.find_all("td")
        if not cells:
            continue
        if any(cell.get("colspan") for cell in cells):
            continue
        if len(cells) < _MIN_REQUIRED_CELLS:
            continue
        rows_data.append({
            col_name: cells[idx].get_text(strip=True)
            for col_name, idx in COLUMN_INDICES.items()
        })

    if not rows_data:
        logger.error("Table found but contained zero valid data rows.")
        return None

    df = pd.DataFrame(rows_data, columns=OUTPUT_COLUMNS)
    logger.debug("Parsed %d rows from price table.", len(df))
    return df


# ===== MAIN SCRAPER CLASS =====

class WikiplastScraper:
    """
    Scraper for petrochemical product prices on wikiplast.ir.

    Example::

        result = WikiplastScraper().scrape()
        if result:
            print(result.df.head())
    """

    def __init__(self, config=None) -> None:
        self.config: ScraperConfig = _resolve_scraper_config(config)
        self.logger = logging.getLogger(self.__class__.__name__)

    def scrape(self) -> ScrapeResult:
        """
        Run the full scrape pipeline.

        1. Fetch the JS endpoint at wikiplast.ir/pricescodeime.
        2. Extract the HTML string from inside document.write(...).
        3. Parse the price table.
        4. Optionally export to CSV.

        Returns:
            ScrapeResult
        """
        self.logger.info("=" * 60)
        self.logger.info("Starting Wikiplast scraper")
        self.logger.info("=" * 60)

        headers = {"User-Agent": self.config.user_agent}
        response = safe_request(
            self.config.url,
            headers=headers,
            max_retries=self.config.max_retries,
            timeout=self.config.timeout,
        )
        if response is None:
            return ScrapeResult(success=False, error="HTTP request failed after all retries.")

        response.encoding = "utf-8"

        html = _extract_html_from_js(response.text)
        if html is None:
            return ScrapeResult(success=False, error="Failed to extract HTML from document.write() response.")

        df = _parse_price_table(html)
        if df is None or df.empty:
            return ScrapeResult(success=False, error="Failed to parse price table from HTML.")

        self.logger.info("Successfully scraped %d product rows.", len(df))

        if self.config.output_csv:
            self._save_csv(df)

        return ScrapeResult(success=True, df=df, rows_fetched=len(df))

    def _save_csv(self, df: pd.DataFrame) -> None:
        """Write DataFrame to CSV (UTF-8-BOM for Excel compatibility)."""
        try:
            df.to_csv(self.config.output_csv, index=False, encoding="utf-8-sig")
            self.logger.info("Data saved to '%s'.", self.config.output_csv)
        except OSError as err:
            self.logger.error("Could not write CSV to '%s': %s", self.config.output_csv, err)


# ===== ENTRY POINT =====

def main() -> None:
    """CLI entry point — run the scraper and print a preview to stdout."""
    config = ScraperConfig(output_csv="wikiplast_prices.csv")
    scraper = WikiplastScraper(config=config)
    result = scraper.scrape()

    if not result:
        logger.error("Scraping failed: %s  Check wikiplast_scraper.log for details.", result.error)
        sys.exit(1)

    print(f"\nFetched {result.rows_fetched} rows.\n")
    print(result.df.to_string(index=False))


if __name__ == "__main__":
    main()
