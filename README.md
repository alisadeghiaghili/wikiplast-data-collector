# wikiplast-data-collector 🧪

A lightweight, production-grade scraper for extracting polymer raw-material prices from [wikiplast.com](https://www.wikiplast.com) and returning them as a clean pandas DataFrame — built with the same architecture as [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector).

> **No browser automation needed.** Wikiplast serves its data inside a JS `document.write()` widget, so `requests` + `BeautifulSoup` are sufficient — faster and more reliable than Selenium.

---

## ✨ Features

- 🕸️ **Lightweight Scraping**: Pure `requests` + `BeautifulSoup` — no Firefox, no geckodriver
- 🏭 **Petrochemical Coverage**: Captures title, price (IRR), timestamp, and company for every listed product
- 🔁 **Retry Logic**: Automatic back-off and retry on network failures
- 📁 **Optional CSV Export**: UTF-8-BOM encoded output ready to open in Excel
- 📝 **Structured Logging**: Dual console + file logs with configurable level
- ⚙️ **Dataclass Config**: All settings in a simple `Config` dataclass — no `.env` required for basic use

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+**

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/alisadeghiaghili/wikiplast-data-collector.git
   cd wikiplast-data-collector
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run**
   ```bash
   python wikiplast_scraper.py
   ```

---

## ⚙️ Configuration

All settings are controlled via the `Config` dataclass — no `.env` file required for basic usage.

```python
from wikiplast_scraper import Config

cfg = Config(
    url="https://www.wikiplast.com/widget/price/",  # widget endpoint
    max_retries=3,                                   # retry attempts on failure
    timeout=30,                                      # per-request timeout (seconds)
    output_csv="prices.csv",                         # set to None to skip CSV export
    user_agent="Mozilla/5.0 ...",                    # custom User-Agent header
)
```

---

## 🛠️ Usage

### Command Line
```bash
python wikiplast_scraper.py
```

Outputs a preview of all scraped rows to stdout and saves `wikiplast_prices.csv`.

### Scrape only (no CSV)
```python
from wikiplast_scraper import WikiplastScraper

scraper = WikiplastScraper()
success, df = scraper.scrape()

if success:
    print(df[["عنوان", "قیمت (ريال)", "پتروشیمی"]].head())
```

### Scrape with CSV export
```python
from wikiplast_scraper import WikiplastScraper, Config

config = Config(output_csv="wikiplast_prices.csv")
scraper = WikiplastScraper(config=config)
success, df = scraper.scrape()

if success:
    print(f"✅ {len(df)} records saved to wikiplast_prices.csv")
else:
    print("❌ Failed. Check wikiplast_scraper.log for details.")
```

### Custom retries and timeout
```python
config = Config(max_retries=5, timeout=60, output_csv="out.csv")
scraper = WikiplastScraper(config=config)
success, df = scraper.scrape()
```

---

## 📊 Data Pipeline

```
wikiplast.com
    │
    ▼
safe_request()            → HTTP GET with retry logic
    │
    ▼
_extract_widget_html()    → Unwraps document.write() JS payload
    │
    ▼
_parse_price_table()      → Locates <table>, skips headers/banners,
                            extracts 4 target columns
    │
    ▼
WikiplastScraper.scrape() → Orchestrates pipeline, optionally exports CSV
    │
    ▼
Tuple[bool, DataFrame]    → (success flag, clean DataFrame)
```

---

## 📋 Output Schema

| Column | Description |
|---|---|
| `عنوان` | Product name |
| `زمان` | Price timestamp from source |
| `قیمت (ريال)` | Price in Iranian Rials (string, as published) |
| `پتروشیمی` | Petrochemical company name |

---

## 📝 Logging

### Log Location
- **File**: `./wikiplast_scraper.log` — full DEBUG-level trace
- **Console**: real-time INFO-level output

### Log Levels

| Level | When |
|---|---|
| `DEBUG` | HTML parsing internals, row-level extraction |
| `INFO` | Workflow progress, record counts |
| `WARNING` | Unexpected data or skipped rows |
| `ERROR` | Network failures, parse errors, empty results |

### Sample Output
```
2026-05-31 18:00:01 - WikiplastScraper - INFO - ============================================================
2026-05-31 18:00:01 - WikiplastScraper - INFO - Starting Wikiplast scraper
2026-05-31 18:00:01 - WikiplastScraper - INFO - ============================================================
2026-05-31 18:00:02 - root - DEBUG - Successfully fetched https://www.wikiplast.com/widget/price/ (attempt 1)
2026-05-31 18:00:02 - root - DEBUG - Parsed 87 rows from price table.
2026-05-31 18:00:02 - WikiplastScraper - INFO - Successfully scraped 87 product rows.
2026-05-31 18:00:02 - WikiplastScraper - INFO - Data saved to 'wikiplast_prices.csv'.
```

---

## 🗂️ Project Structure

```
wikiplast-data-collector/
├── wikiplast_scraper.py   ← Main scraper (Config, WikiplastScraper, helpers)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🛠️ Troubleshooting

**`Could not locate document.write() payload in response`**
→ The site's JS widget structure may have changed. Inspect the page source at `wikiplast.com/widget/price/` and update the regex in `_extract_widget_html()`.

**`No <table> element found in widget HTML`**
→ The HTML embedded in the JS payload no longer contains a `<table>`. Check the widget endpoint directly and update `_parse_price_table()`.

**`Table found but contained zero valid data rows`**
→ Row structure has changed (column count or header class). Inspect the raw HTML and update `COLUMN_INDICES` and the skip conditions in `_parse_price_table()`.

**`Failed to fetch ... after 3 retries`**
→ The site may be temporarily down or blocking the request. Try increasing `max_retries` or updating `user_agent` in `Config`.

---

## 📦 Dependencies

```
requests>=2.31.0
beautifulsoup4>=4.12.0
pandas>=2.0.0
```

---

## 🔗 Related Projects

| Project | Description |
|---|---|
| [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector) | Prices from Iran Commodity Exchange (ICE.ir) — uses Selenium |
| [tgju-data-collector](https://github.com/alisadeghiaghili/tgju-data-collector) | Real-time market data from TGJU.org with SQL Server integration |

---

## 📞 Support

1. Check `./wikiplast_scraper.log` for detailed error traces
2. Review the [Troubleshooting](#️-troubleshooting) section above
3. Open a GitHub issue with your log output and Python version
4. Contact: [alisadeghiaghili@gmail.com](mailto:alisadeghiaghili@gmail.com)
