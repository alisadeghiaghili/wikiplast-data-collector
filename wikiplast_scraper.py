# -*- coding: utf-8 -*-
"""
Wikiplast Petrochemical Price Scraper
======================================
Fetches polymer raw-material prices from wikiplast.com and returns them
as a clean pandas DataFrame using the same Config / safe_request() pattern
as ice-data-collector and tgju-data-collector.

Extracted columns:
    - عنوان       (product title)
    - زمان        (price timestamp from source)
    - قیمت (ریال) (price in IRR)
    - پتروشیمی   (petrochemical company)

Dependencies: requests, beautifulsoup4, pandas
No Selenium required – data is served as static HTML.

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

# The widget endpoint serves a full HTML page with the price table inline.
# No JavaScript execution or document.write() extraction is needed.
WIKIPLAST_WIDGET_URL = "https://www.wikiplast.com/widget/price/"

# Column names as they appear in the source HTML <th> cells.
# Index positions map directly to <td> order inside each <tr>.
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

    Use this when you want full control over scraper behaviour without
    setting up a database connection.  When an app-level Config (from
    config.py) is passed to WikiplastScraper instead, its
    ``retry.max_attempts`` and ``database.connection_timeout`` values are
    mapped onto these fields automatically.

    Attributes:
        url (str): Target URL for the price widget.
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
    """
    Normalise any config object into a ScraperConfig.

    Accepts:
      - ``None``              → default ScraperConfig()
      - ``ScraperConfig``     → returned as-is
      - app-level ``Config``  → retry.max_attempts and
                                database.connection_timeout are mapped;
                                all other HTTP defaults are kept

    Returns:
        ScraperConfig: A fully-populated scraper configuration.
    """
    if config is None:
        return ScraperConfig()

    if isinstance(config, ScraperConfig):
        return config

    # App-level Config from config.py – extract what we need
    try:
        max_retries = config.retry.max_attempts
    except AttributeError:
        max_retries = DEFAULT_MAX_RETRIES

    try:
        timeout = config.database.connection_timeout
    except AttributeError:
        timeout = DEFAULT_TIMEOUT

    logger.debug(
        "App-level Config detected – mapped retry.max_attempts=%d, "
        "database.connection_timeout=%d into ScraperConfig",
        max_retries,
        timeout,
    )
    return ScraperConfig(max_retries=max_retries, timeout=timeout)


# ===== RESULT CONTAINER =====

class ScrapeResult:
    """
    Container returned by ``WikiplastScraper.scrape()``.

    Supports **two usage patterns** so existing code keeps working:

    Attribute access (recommended)::

        result = scraper.scrape()
        if result:            # bool(result) == result.success
            print(result.df)  # the DataFrame

    Tuple unpacking (backward compatible)::

        success, df = scraper.scrape()

    Attributes:
        success (bool): True if scraping and parsing both succeeded.
        df (Optional[pd.DataFrame]): DataFrame with columns
            [عنوان, زمان, قیمت (ریال), پتروشیمی], or None on failure.
        rows_fetched (int): Number of data rows extracted (0 on failure).
        error (Optional[str]): Human-readable error description, or None on success.
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

    # ----- bool / tuple protocol -----

    def __bool__(self) -> bool:
        """Allow ``if result:`` checks."""
        return self.success

    def __iter__(self) -> Iterator:
        """
        Enable tuple unpacking::

            success, df = scraper.scrape()
        """
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
    Execute an HTTP GET request with automatic retry logic and error handling.

    Implements resilience patterns for transient network failures:

    - Retries on timeout or connection errors with a short random back-off
    - Validates HTTP status codes via ``raise_for_status()``
    - Logs every attempt and final failure at appropriate log levels

    Args:
        url (str): Target URL for the GET request.
        headers (dict, optional): HTTP headers to include.
        max_retries (int): Maximum number of attempts.  Defaults to 3.
        timeout (int): Per-request timeout in seconds.  Defaults to 30.

    Returns:
        requests.Response: Successful response object, or None if all
        retries are exhausted.
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


# ===== HTML PARSING MODULE =====

def _parse_price_table(html: str) -> Optional[pd.DataFrame]:
    """
    Parse the Wikiplast price HTML table into a structured DataFrame.

    The widget endpoint delivers a standalone HTML page; this function
    locates the first ``<table>`` element and extracts product rows.

    Processing steps:

    1. Parse HTML with BeautifulSoup.
    2. Locate the first ``<table>`` element.
    3. Iterate over ``<tr>`` rows, skipping:

       - Header rows (``class='ratehead'``)
       - Banner/title rows (any cell carries a ``colspan`` attribute)
       - Short rows with fewer cells than required

    4. Extract text from each ``<td>`` at the fixed column indices
       defined in :data:`COLUMN_INDICES`.
    5. Assemble rows into a DataFrame with columns in
       :data:`OUTPUT_COLUMNS` order.

    Args:
        html (str): Raw HTML string of the widget page.

    Returns:
        pd.DataFrame: DataFrame with columns
        [عنوان, زمان, قیمت (ریال), پتروشیمی] and one row per product,
        or None if the table cannot be found or no valid data rows exist.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        logger.error("No <table> element found in widget HTML.")
        return None

    rows_data = []
    for tr in table.find_all("tr"):
        # skip header rows
        if "ratehead" in tr.get("class", []):
            continue

        cells = tr.find_all("td")

        # skip title/banner rows and rows that are too short
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
    Scraper for petrochemical product prices published on Wikiplast.com.

    Accepts either a :class:`ScraperConfig` (for standalone use) or the
    app-level ``Config`` from ``config.py`` (for full-pipeline use with DB).
    When an app-level Config is supplied, retry and timeout values are
    mapped automatically via :func:`_resolve_scraper_config`.

    Example::

        # Recommended — attribute access
        result = WikiplastScraper().scrape()
        if result:
            print(result.df.head())

        # Backward compatible — tuple unpacking
        success, df = WikiplastScraper().scrape()
    """

    def __init__(self, config=None) -> None:
        """
        Initialise the scraper.

        Args:
            config: One of:

                - ``None``                  → default ScraperConfig is used
                - :class:`ScraperConfig`    → full HTTP control
                - app-level ``Config``      → retry + timeout are reused
        """
        self.config: ScraperConfig = _resolve_scraper_config(config)
        self.logger = logging.getLogger(self.__class__.__name__)

    def scrape(self) -> ScrapeResult:
        """
        Run the full scrape pipeline and return a :class:`ScrapeResult`.

        Workflow:

        1. Send HTTP GET to the configured widget URL (with retry logic).
        2. Parse the price table from the raw HTML response.
        3. Optionally export the DataFrame to CSV.

        Returns:
            ScrapeResult: Always returned.  Check ``result.success`` or
            use ``if result:`` to test for success.

        Example::

            result = WikiplastScraper().scrape()
            if result:
                print(f"Fetched {result.rows_fetched} products.")
                print(result.df)
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
        df = _parse_price_table(response.text)

        if df is None or df.empty:
            return ScrapeResult(success=False, error="Failed to parse price table from response.")

        self.logger.info("Successfully scraped %d product rows.", len(df))

        if self.config.output_csv:
            self._save_csv(df)

        return ScrapeResult(success=True, df=df, rows_fetched=len(df))

    def _save_csv(self, df: pd.DataFrame) -> None:
        """
        Write the DataFrame to CSV at the configured output path.

        Uses UTF-8-BOM encoding so the file opens correctly in Microsoft
        Excel without manual encoding configuration.

        Args:
            df (pd.DataFrame): DataFrame to export.
        """
        try:
            df.to_csv(self.config.output_csv, index=False, encoding="utf-8-sig")
            self.logger.info("Data saved to '%s'.", self.config.output_csv)
        except OSError as err:
            self.logger.error("Could not write CSV to '%s': %s", self.config.output_csv, err)


# ===== ENTRY POINT =====

def main() -> None:
    """
    CLI entry point — run the scraper and print a preview to stdout.

    Example::

        $ python wikiplast_scraper.py
        ============================================================
        Starting Wikiplast scraper
        ============================================================
        Successfully scraped 87 product rows.

        Fetched 87 rows.

           عنوان          زمان    قیمت (ریال)  پتروشیمی
        0  PVC S65 Ghadir  ...
    """
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
