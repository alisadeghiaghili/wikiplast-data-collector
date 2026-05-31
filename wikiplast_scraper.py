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
    - قیمت (ريال) (price in IRR)
    - پتروشیمی   (petrochemical company)

Dependencies: requests, beautifulsoup4, pandas
No Selenium required – data is served as static HTML inside a JS widget.

Author : Ali Sadeghi Aghili
Created: 2026-05-31

Usage patterns
--------------
# 1. Standalone – no config needed
success, df = WikiplastScraper().scrape()
if success:
    print(df)

# 2. With app-level Config from config.py (retry settings are reused)
from config import Config
config = Config.from_env()
success, df = WikiplastScraper(config=config).scrape()

# 3. With ScraperConfig for full HTTP control
from wikiplast_scraper import ScraperConfig
scraper_cfg = ScraperConfig(max_retries=5, timeout=60, output_csv="out.csv")
success, df = WikiplastScraper(config=scraper_cfg).scrape()
"""

import sys
import logging
import time
import random
import re
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

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

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
SHORT_RETRY_DELAY_MIN = 2
SHORT_RETRY_DELAY_JITTER = 1

WIKIPLAST_WIDGET_URL = "https://www.wikiplast.com/widget/price/"

OUTPUT_COLUMNS = ["عنوان", "زمان", "قیمت (ريال)", "پتروشیمی"]
COLUMN_INDICES = {
    "عنوان": 0,
    "قیمت (ريال)": 1,
    "زمان": 2,
    "پتروشیمی": 3,
}


# ===== SCRAPER-SPECIFIC CONFIGURATION =====

@dataclass
class ScraperConfig:
    """
    HTTP-level configuration for WikiplastScraper.

    Use this when you want full control over scraper behaviour without
    setting up a database. When an app-level Config (from config.py) is
    passed to WikiplastScraper instead, its retry.max_attempts and
    database.connection_timeout values are mapped onto these fields
    automatically.

    Attributes:
        url (str): Target URL for the price widget.
        max_retries (int): HTTP retry attempts before giving up.
        timeout (int): Per-request timeout in seconds.
        output_csv (Optional[str]): Path for CSV export; None disables export.
        user_agent (str): User-Agent header sent with each request.

    Example:
        >>> cfg = ScraperConfig(output_csv="prices.csv", max_retries=5)
        >>> cfg.url
        'https://www.wikiplast.com/widget/price/'
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
      - None                  → default ScraperConfig()
      - ScraperConfig         → returned as-is
      - app-level Config      → retry.max_attempts and database.connection_timeout
                                are mapped; all other HTTP defaults are kept

    Args:
        config: One of None, ScraperConfig, or the app-level Config dataclass.

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
        f"App-level Config detected – mapped retry.max_attempts={max_retries}, "
        f"database.connection_timeout={timeout} into ScraperConfig"
    )
    return ScraperConfig(max_retries=max_retries, timeout=timeout)


# ===== RESULT CONTAINER =====

@dataclass
class ScrapeResult:
    """
    Container for the outcome of a single scrape run.

    Attributes:
        success (bool): True if scraping and parsing both succeeded.
        data (Optional[pd.DataFrame]): DataFrame with columns
            [عنوان, زمان, قیمت (ريال), پتروشیمی], or None on failure.
        rows_fetched (int): Number of data rows extracted (0 on failure).
        error (Optional[str]): Human-readable error description, or None on success.

    Example:
        >>> result = ScrapeResult(success=True, data=df, rows_fetched=42)
        >>> result.success
        True
    """
    success: bool
    data: Optional[pd.DataFrame] = None
    rows_fetched: int = 0
    error: Optional[str] = None


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
    - Validates HTTP status codes via raise_for_status()
    - Logs every attempt and final failure at appropriate log levels

    Args:
        url (str): Target URL for the GET request.
        headers (dict, optional): HTTP headers to include. Defaults to None.
        max_retries (int): Maximum number of attempts. Defaults to 3.
        timeout (int): Per-request timeout in seconds. Defaults to 30.

    Returns:
        requests.Response: Successful response object, or None if all
        retries are exhausted.

    Example:
        >>> response = safe_request("https://www.wikiplast.com/widget/price/")
        >>> if response:
        ...     print(response.status_code)
        200
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            logger.debug(f"Successfully fetched {url} (attempt {attempt + 1})")
            return response

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as conn_err:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url}: {conn_err}")
            if attempt < max_retries - 1:
                delay = SHORT_RETRY_DELAY_MIN + random.random() * SHORT_RETRY_DELAY_JITTER
                logger.debug(f"Waiting {delay:.2f}s before retry...")
                time.sleep(delay)

        except (requests.exceptions.HTTPError, requests.exceptions.RequestException) as http_err:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url}: {http_err}")
            if attempt < max_retries - 1:
                delay = SHORT_RETRY_DELAY_MIN + random.random() * SHORT_RETRY_DELAY_JITTER
                logger.debug(f"Waiting {delay:.2f}s before retry...")
                time.sleep(delay)

    logger.error(f"Failed to fetch {url} after {max_retries} retries.")
    return None


# ===== HTML PARSING MODULE =====

def _extract_widget_html(response: requests.Response) -> Optional[str]:
    """
    Extract the raw HTML table markup from a Wikiplast widget response.

    The widget page delivers table content inside a document.write(...)
    JavaScript call. This helper locates that call and returns the embedded
    HTML string so it can be parsed independently.

    Args:
        response (requests.Response): HTTP response returned by safe_request().

    Returns:
        str: Raw HTML string containing the price table, or None if the
        document.write pattern is not found in the response body.

    Example:
        >>> html = _extract_widget_html(response)
        >>> if html:
        ...     soup = BeautifulSoup(html, "html.parser")
    """
    match = re.search(r"document\.write\('(.+?)'\);", response.text, re.DOTALL)
    if not match:
        logger.error("Could not locate document.write() payload in response.")
        return None

    raw = match.group(1)
    return raw.replace("\\'", "'")


def _parse_price_table(html: str) -> Optional[pd.DataFrame]:
    """
    Parse the Wikiplast price HTML table into a structured DataFrame.

    Processing steps:
    1. Parse HTML with BeautifulSoup.
    2. Locate the first <table> element.
    3. Iterate over <tr> rows, skipping header rows (class='ratehead')
       and banner rows (cells with colspan attribute).
    4. Extract text from each <td> at the fixed column indices defined
       in COLUMN_INDICES.
    5. Assemble rows into a DataFrame with columns in OUTPUT_COLUMNS order.

    Args:
        html (str): Raw HTML string containing the price table.

    Returns:
        pd.DataFrame: DataFrame with columns [عنوان, زمان, قیمت (ريال), پتروشیمی]
        and one row per product, or None if the table cannot be found or
        no data rows are present.

    Raises:
        ValueError: If the extracted table contains zero valid data rows.

    Example:
        >>> df = _parse_price_table(html)
        >>> df.columns.tolist()
        ['عنوان', 'زمان', 'قیمت (ريال)', 'پتروشیمی']
        >>> len(df) > 0
        True
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        logger.error("No <table> element found in widget HTML.")
        return None

    rows_data = []
    for tr in table.find_all("tr"):
        if "ratehead" in tr.get("class", []):
            continue

        cells = tr.find_all("td")

        if not cells or any(cell.get("colspan") for cell in cells):
            continue
        if len(cells) < max(COLUMN_INDICES.values()) + 1:
            continue

        row = {
            col_name: cells[idx].get_text(strip=True)
            for col_name, idx in COLUMN_INDICES.items()
        }
        rows_data.append(row)

    if not rows_data:
        raise ValueError("Table found but contained zero valid data rows.")

    df = pd.DataFrame(rows_data, columns=OUTPUT_COLUMNS)
    logger.debug(f"Parsed {len(df)} rows from price table.")
    return df


# ===== MAIN SCRAPER CLASS =====

class WikiplastScraper:
    """
    Scraper for petrochemical product prices published on Wikiplast.com.

    Accepts either a ScraperConfig (for standalone use) or the app-level
    Config from config.py (for full-pipeline use with DB). When an app-level
    Config is supplied, retry and timeout values are mapped automatically.

    Attributes:
        config (ScraperConfig): Resolved HTTP configuration.
        logger (logging.Logger): Module-level logger instance.

    Example:
        >>> scraper = WikiplastScraper()
        >>> success, df = scraper.scrape()
        >>> if success:
        ...     print(df[["عنوان", "قیمت (ريال)"]].head())
    """

    def __init__(self, config=None) -> None:
        """
        Initialise the scraper.

        Args:
            config: One of:
                - None (default ScraperConfig is used)
                - ScraperConfig (full HTTP control)
                - app-level Config from config.py (retry + timeout are reused)

        Example:
            >>> from config import Config
            >>> scraper = WikiplastScraper(config=Config.from_env())
        """
        self.config: ScraperConfig = _resolve_scraper_config(config)
        self.logger = logging.getLogger(self.__class__.__name__)

    def scrape(self) -> Tuple[bool, Optional[pd.DataFrame]]:
        """
        Run the full scrape pipeline and return results.

        Workflow:
        1. Send HTTP GET to the configured widget URL (with retry logic).
        2. Extract the raw HTML table from the document.write() payload.
        3. Parse the table into a DataFrame.
        4. Optionally export the DataFrame to CSV.

        Returns:
            Tuple[bool, Optional[pd.DataFrame]]: A two-element tuple where:
                - [0] bool: True if the pipeline completed without error.
                - [1] pd.DataFrame | None: Parsed data on success, None on failure.

        Example:
            >>> scraper = WikiplastScraper()
            >>> ok, df = scraper.scrape()
            >>> if ok:
            ...     print(f"Fetched {len(df)} products.")
            Fetched 87 products.
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
            return False, None

        widget_html = _extract_widget_html(response)
        if widget_html is None:
            return False, None

        try:
            df = _parse_price_table(widget_html)
        except ValueError as parse_err:
            self.logger.error(f"Parse error: {parse_err}")
            return False, None

        if df is None or df.empty:
            self.logger.error("Parsing returned an empty DataFrame.")
            return False, None

        self.logger.info(f"Successfully scraped {len(df)} product rows.")

        if self.config.output_csv:
            self._save_csv(df)

        return True, df

    def _save_csv(self, df: pd.DataFrame) -> None:
        """
        Write the DataFrame to a CSV file at the configured output path.

        Uses UTF-8-BOM encoding so the file opens correctly in Microsoft Excel
        without manual encoding configuration.

        Args:
            df (pd.DataFrame): DataFrame to export.

        Example:
            >>> cfg = ScraperConfig(output_csv="wikiplast_prices.csv")
            >>> scraper = WikiplastScraper(config=cfg)
            >>> ok, df = scraper.scrape()
            # CSV written to wikiplast_prices.csv after successful scrape
        """
        try:
            df.to_csv(self.config.output_csv, index=False, encoding="utf-8-sig")
            self.logger.info(f"Data saved to '{self.config.output_csv}'.")
        except OSError as file_err:
            self.logger.error(f"Could not write CSV to '{self.config.output_csv}': {file_err}")


# ===== ENTRY POINT =====

def main() -> None:
    """
    CLI entry point — run the scraper and print a preview to stdout.

    Workflow:
    1. Instantiate WikiplastScraper with CSV export enabled.
    2. Call scrape() and capture the result tuple.
    3. On success, print the full DataFrame and summary statistics.
    4. On failure, log the error and exit with code 1.

    Example:
        $ python wikiplast_scraper.py
        Successfully scraped 87 product rows.

           عنوان          زمان    قیمت (ريال)  پتروشیمی
        0  پلی‌اتیلن ...  1403/...  145,000      مارون
        ...
    """
    config = ScraperConfig(output_csv="wikiplast_prices.csv")
    scraper = WikiplastScraper(config=config)
    success, df = scraper.scrape()

    if not success or df is None:
        logger.error("Scraping failed. Check wikiplast_scraper.log for details.")
        sys.exit(1)

    print(f"\nFetched {len(df)} rows.\n")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
