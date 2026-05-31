# Wikiplast Data Collector

> Lightweight Python scraper for real-time polymer raw-material prices from
> [wikiplast.com](https://www.wikiplast.com) — built with the same
> architecture as
> [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector)
> and
> [tgju-data-collector](https://github.com/alisadeghiaghili/tgju-data-collector).

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## Features

| | |
|---|---|
| ⚡ **No browser required** | Pure `requests` + `BeautifulSoup` — zero Selenium overhead |
| 🔄 **Auto-retry** | Configurable retry with jitter back-off for transient failures |
| 📄 **CSV export** | UTF-8-BOM output that opens natively in Microsoft Excel |
| 🧩 **Dual return API** | `result.df` **and** `success, df = scraper.scrape()` both work |
| 🔧 **Pluggable config** | Drop-in with the shared `Config` from `config.py` or standalone `ScraperConfig` |
| 📝 **Structured logging** | Console + rotating file log at `wikiplast_scraper.log` |

---

## Extracted Columns

| Column | Description |
|---|---|
| `عنوان` | Product / grade name |
| `زمان` | Price timestamp (Persian calendar) |
| `قیمت (ریال)` | Price in Iranian Rial |
| `پتروشیمی` | Petrochemical company / origin |

---

## Quick Start

### Prerequisites

- Python ≥ 3.10
- pip

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/alisadeghiaghili/wikiplast-data-collector.git
cd wikiplast-data-collector

# 2. (Recommended) Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the environment template
cp .env.example .env
```

### Run

```bash
python wikiplast_scraper.py
```

Output is printed to stdout **and** saved to `wikiplast_prices.csv`.

---

## Usage

### Attribute access (recommended)

```python
from wikiplast_scraper import WikiplastScraper

scraper = WikiplastScraper()
result = scraper.scrape()

if result:                         # bool(result) == result.success
    print(result.df)               # pandas DataFrame
    print(result.rows_fetched)     # number of rows
else:
    print(result.error)            # human-readable error message
```

### Tuple unpacking (backward compatible)

```python
success, df = WikiplastScraper().scrape()
if success:
    print(df)
```

### With app-level Config

```python
from config import Config
from wikiplast_scraper import WikiplastScraper

config = Config.from_env()
result = WikiplastScraper(config=config).scrape()

if result:
    print(result.df[['عنوان', 'قیمت (ریال)']].head(10))
```

### With ScraperConfig for full HTTP control

```python
from wikiplast_scraper import WikiplastScraper, ScraperConfig

cfg = ScraperConfig(
    max_retries=5,
    timeout=60,
    output_csv="prices_today.csv",
)
result = WikiplastScraper(config=cfg).scrape()
```

---

## Return Value — `ScrapeResult`

`scraper.scrape()` always returns a `ScrapeResult` object.

| Attribute | Type | Description |
|---|---|---|
| `success` | `bool` | `True` if scraping and parsing both succeeded |
| `df` | `pd.DataFrame \| None` | Parsed price table, `None` on failure |
| `rows_fetched` | `int` | Number of product rows extracted |
| `error` | `str \| None` | Error description, `None` on success |

The object supports:
- **`bool()` / `if result:`** — evaluates `success`
- **`success, df = result`** — tuple unpacking for backward compatibility

---

## Configuration

### Environment variables (`.env`)

Copy `.env.example` and fill in values:

```dotenv
# Database (optional — only needed for pipeline integration)
DB_SERVER=localhost
DB_NAME=market_data
DB_USERNAME=sa
DB_PASSWORD=
DB_DRIVER=ODBC Driver 17 for SQL Server

# Retry settings
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_FACTOR=2
```

### `ScraperConfig` options

| Parameter | Default | Description |
|---|---|---|
| `url` | `https://www.wikiplast.com/widget/price/` | Widget endpoint |
| `max_retries` | `3` | HTTP retry attempts |
| `timeout` | `30` | Request timeout (seconds) |
| `output_csv` | `None` | CSV export path (`None` disables export) |
| `user_agent` | Chrome/124 UA string | `User-Agent` header |

---

## Data Pipeline

```
wikiplast.com/widget/price/
        │  (HTTP GET × 1–3 with jitter back-off)
        ▼
  safe_request()
        │  (raw HTML response)
        ▼
  _parse_price_table()          ← BeautifulSoup HTML parser
        │  (pd.DataFrame)
        ▼
  WikiplastScraper.scrape()
        │  (ScrapeResult)
        ▼
  ├── result.df        → downstream analytics / DB insert
  └── result.output_csv → wikiplast_prices.csv  (UTF-8-BOM)
```

---

## Project Structure

```
wikiplast-data-collector/
├── wikiplast_scraper.py   # Scraper, ScrapeResult, ScraperConfig, safe_request()
├── config.py              # Shared app-level Config (DB, retry, logging)
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variable template
├── .gitignore
└── README.md
```

---

## Logging

All activity is written to both **stdout** and **`wikiplast_scraper.log`**.

| Level | When |
|---|---|
| `INFO` | Scrape start / end, rows fetched, CSV saved |
| `WARNING` | Retried HTTP attempts |
| `ERROR` | Final HTTP failure, parse failure, CSV write error |
| `DEBUG` | Per-attempt detail, retry delays, row counts |

Sample output:

```
2026-05-31 19:08:28 - WikiplastScraper - INFO - ============================================================
2026-05-31 19:08:28 - WikiplastScraper - INFO - Starting Wikiplast scraper
2026-05-31 19:08:28 - WikiplastScraper - INFO - ============================================================
2026-05-31 19:08:29 - WikiplastScraper - INFO - Successfully scraped 87 product rows.
2026-05-31 19:08:29 - WikiplastScraper - INFO - Data saved to 'wikiplast_prices.csv'.
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Failed to fetch … after 3 retries` | Network / firewall / VPN | Check connectivity to `wikiplast.com`; increase `max_retries` |
| `No <table> element found` | Site HTML structure changed | Open the widget URL in a browser and inspect the DOM |
| `zero valid data rows` | All rows filtered out | Check `COLUMN_INDICES` against current `<td>` positions |
| Persian text garbled in Excel | Wrong encoding | Always open the CSV via **Data → From Text/CSV** with UTF-8 |

---

## Dependencies

```
requests
beautifulsoup4
pandas
python-dotenv
pyodbc          # optional — only for DB pipeline via config.py
```

---

## Related Projects

| Project | Source |
|---|---|
| ICE Data Collector | [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector) |
| TGJU Data Collector | [tgju-data-collector](https://github.com/alisadeghiaghili/tgju-data-collector) |

---

## License

[MIT](LICENSE) © Ali Sadeghi Aghili
