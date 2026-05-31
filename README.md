# wikiplast-data-collector 🧪

A lightweight, production-grade scraper for extracting polymer raw-material prices from [wikiplast.ir](https://wikiplast.ir) and pushing them directly into SQL Server — built with the same architecture as [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector).

> **No browser automation needed.** Wikiplast serves its data as static HTML inside a JS widget, so `requests` + `BeautifulSoup` are sufficient — faster and more reliable than Selenium.

---

## ✨ Features

- 🕸️ **Lightweight Scraping**: Pure `requests` + `BeautifulSoup` — no Firefox, no geckodriver
- 🏭 **Petrochemical Coverage**: Captures title, price (IRR), timestamp, and company for every listed product
- 🗄️ **SQL Server Integration**: Auto-creates the target table and appends data using SQLAlchemy 2.0+
- 📋 **Shared Config Pattern**: Uses the same `Config` / `DatabaseConfig` / `create_engine()` design as `ice-data-collector`
- 📝 **Enterprise Logging**: Dual console + rotating file logs with configurable log level
- 🔁 **Duplicate Guard**: Drops duplicate rows within each batch before inserting
- ⚙️ **Environment-based Config**: All credentials and settings live in `.env` — nothing hardcoded

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+**
- **SQL Server** with ODBC Driver 17
- `config.py` copied from [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector)

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

3. **Copy `config.py`** from ice-data-collector into this directory
   ```bash
   cp ../ice-data-collector/config.py .
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Then edit .env with your actual DB credentials
   ```

---

## ⚙️ Configuration

All settings are loaded from `.env` via `config.py`. Copy `.env.example` to `.env` and fill in your values:

```env
DB_SERVER=your_sql_server_hostname
DB_NAME=your_database_name
DB_USER=your_username
DB_PASSWORD=your_secure_password
DB_TABLE_NAME=wikiplast_prices
LOG_LEVEL=INFO
```

For **Windows Authentication** (trusted connection), leave `DB_USER` and `DB_PASSWORD` empty and set:
```env
DB_TRUSTED_CONNECTION=yes
```

### Show current config
```bash
python wikiplast_scraper.py --show-config
```

---

## 🛠️ Usage

### Command Line
```bash
python wikiplast_scraper.py
```

### Programmatic
```python
from wikiplast_scraper import WikiplastScraper

scraper = WikiplastScraper()
success, df = scraper.scrape_and_store()

if success:
    print(f"✅ {len(df)} records saved.")
else:
    print("❌ Failed. Check logs/wikiplast_*.log for details.")
```

### With custom config
```python
from config import Config
from wikiplast_scraper import WikiplastScraper

config = Config.from_env()
scraper = WikiplastScraper(config=config)
success, df = scraper.scrape_and_store()
```

---

## 📊 Data Pipeline

```
wikiplast.ir
    │
    ▼
 _fetch_page()          → HTTP GET, returns raw HTML/JS widget
    │
    ▼
 _parse_html()          → Unwraps document.write(), parses with BeautifulSoup
    │
    ▼
 _extract_table()       → Locates <table>, skips headers, extracts 4 target columns
    │
    ▼
 _process_data()        → Cleans price column, drops duplicates, adds scrape metadata
    │
    ▼
 _save_to_database()    → Auto-creates table if missing, appends rows via SQLAlchemy
```

---

## 📋 Database Schema

| Column | Type | Description |
|---|---|---|
| `Title` | NVARCHAR(200) | عنوان — Product name |
| `Time` | NVARCHAR(50) | زمان — Price timestamp from source |
| `Price` | BigInteger | قیمت (ريال) — Price in Iranian Rials |
| `Petro` | NVARCHAR(200) | پتروشیمی — Petrochemical company name |
| `ScrapeDate` | CHAR(10) | Date the row was scraped (YYYY-MM-DD) |
| `ScrapeTime` | CHAR(8) | Time the row was scraped (HH:MM:SS) |

The table is created automatically on first run if it does not exist.

---

## 📝 Logging

### Log Locations
- **File**: `./logs/wikiplast_YYYYMMDD.log` — full DEBUG-level trace
- **Console**: real-time INFO-level output

### Log Levels
| Level | When |
|---|---|
| `DEBUG` | HTML parsing internals, row-level extraction |
| `INFO` | Workflow progress, record counts, timing |
| `WARNING` | Duplicate rows removed, unexpected data |
| `ERROR` | Network failures, parse errors, DB errors |

### Sample Output
```
INFO     | ─── Wikiplast scraping workflow started ───
INFO     | Fetching: https://wikiplast.ir/prices/5/
INFO     | Response: HTTP 200, 49,219 chars
INFO     | Found 183 rows in table (including headers).
INFO     | Extracted 178 product records.
INFO     | Data processing complete: 178 rows ready for DB.
INFO     | Saving 178 rows to 'wikiplast_prices'...
INFO     | Data saved to database successfully.
INFO     | Workflow completed in 2.41s
```

---

## 🗂️ Project Structure

```
wikiplast-data-collector/
├── wikiplast_scraper.py   ← Main scraper class (WikiplastScraper)
├── config.py              ← Shared config (copy from ice-data-collector)
├── .env                   ← Your credentials (never committed)
├── .env.example           ← Template for .env
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🛠️ Troubleshooting

**`ModuleNotFoundError: No module named 'config'`**
→ Copy `config.py` from [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector) into this directory.

**`ValueError: No <table> found in the fetched content`**
→ The site structure may have changed. Inspect `wikiplast.ir/prices/5/` and update the parser in `_extract_table()`.

**`SQLAlchemyError: Database connection failed`**
→ Verify SQL Server is running, ODBC Driver 17 is installed, and `.env` credentials are correct. Run `--show-config` to inspect the resolved config.

**`ValueError: Missing required environment variables`**
→ Ensure `.env` exists in the project directory and contains `DB_SERVER` and `DB_NAME`.

---

## 📦 Dependencies

```
requests>=2.31.0
beautifulsoup4>=4.12.0
pandas>=2.0.0
sqlalchemy>=2.0.0
pyodbc>=4.0.39
```

---

## 🔗 Related Projects

| Project | Description |
|---|---|
| [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector) | Prices from Iran Commodity Exchange (ICE.ir) — uses Selenium |

---

## 📞 Support

1. Check `./logs/wikiplast_*.log` for detailed error traces
2. Review the [Troubleshooting](#️-troubleshooting) section above
3. Open a GitHub issue with your log output and Python version
4. Contact: [alisadeghiaghili@gmail.com](mailto:alisadeghiaghili@gmail.com)
