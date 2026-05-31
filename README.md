# wikiplast-data-collector

Scraper for polymer raw material prices from [wikiplast.ir](https://wikiplast.ir) — extracts product title, price (IRR), timestamp, and petrochemical company into SQL Server.

## Extracted Columns

| Column | DB Field | Type |
|---|---|---|
| عنوان | `Title` | NVARCHAR(200) |
| زمان | `Time` | NVARCHAR(50) |
| قیمت (ريال) | `Price` | BigInteger |
| پتروشیمی | `Petro` | NVARCHAR(200) |
| — | `ScrapeDate` | CHAR(10) |
| — | `ScrapeTime` | CHAR(8) |

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` from [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector) and set:

```env
DB_SERVER=your_server
DB_NAME=your_database
DB_TABLE_NAME=wikiplast_prices
DB_TRUSTED_CONNECTION=yes   # or set DB_USER / DB_PASSWORD
```

> `config.py` is shared with ice-data-collector. Copy it to this project directory.

## Usage

```python
from wikiplast_scraper import WikiplastScraper

scraper = WikiplastScraper()
success, df = scraper.scrape_and_store()
```

Or from CLI:

```bash
python wikiplast_scraper.py
python wikiplast_scraper.py --show-config
```

## Notes

- No Selenium required — data is served as static HTML embedded in a JS widget.
- Uses the same `Config` / `DatabaseConfig` / `create_engine` pattern as [ice-data-collector](https://github.com/alisadeghiaghili/ice-data-collector).
