# -*- coding: utf-8 -*-
"""
Secure Configuration Module for Wikiplast Data Collector.

Provides secure credential management using environment variables.
Compatible with SQLAlchemy 2.0+ and supports both SQL authentication
and Windows trusted connection.

NO credentials should ever be hardcoded in this file.

Usage:
    from config import Config

    config = Config.from_env()
    engine = config.create_engine()
"""

import os
import logging
from typing import Optional
from urllib.parse import quote_plus
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# .env loader  (no python-dotenv required)
# ---------------------------------------------------------------------------

def load_env_file(env_path: str = '.env') -> None:
    """Load environment variables from .env file.

    System environment variables always take priority over .env values.
    """
    if not os.path.exists(env_path):
        logger.debug(f"No {env_path} file found – using system environment variables")
        return

    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue

                key, value = line.split('=', 1)
                key   = key.strip()
                value = value.strip()

                # Strip surrounding quotes
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]

                if key not in os.environ:
                    os.environ[key] = value

        logger.info(f"Loaded environment variables from {env_path}")
    except Exception as e:
        logger.warning(f"Failed to load {env_path}: {e}")


def _validate_no_placeholders(value: str, var_name: str) -> None:
    """Raise ValueError if value still contains a template placeholder."""
    placeholders = ('your_', 'example', 'placeholder', 'changeme', 'change_me')
    if any(ph in value.lower() for ph in placeholders):
        raise ValueError(
            f"\u26a0\ufe0f  {var_name} contains a placeholder value: '{value}'\n"
            f"Edit your .env file and replace it with an actual value.\n"
            f"See .env.example for a template."
        )


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

@dataclass
class DatabaseConfig:
    """Database connection configuration."""
    server:             str
    database:           str
    driver:             str  = 'ODBC Driver 17 for SQL Server'
    port:               int  = 1433
    user:               Optional[str] = None
    password:           Optional[str] = None
    trusted_connection: bool = False
    table_name:         str  = 'wikiplast_prices'
    connection_timeout: int  = 30

    def __post_init__(self) -> None:
        if not self.trusted_connection and (not self.user or not self.password):
            raise ValueError(
                "Either set DB_TRUSTED_CONNECTION=yes "
                "or provide DB_USER and DB_PASSWORD in .env"
            )
        _validate_no_placeholders(self.server,   'DB_SERVER')
        _validate_no_placeholders(self.database, 'DB_NAME')

    def get_connection_string(self) -> str:
        """Build a SQLAlchemy 2.0-compatible connection string."""
        driver_enc = quote_plus(self.driver)

        if self.trusted_connection:
            logger.debug("Using Windows trusted connection")
            return (
                f"mssql+pyodbc://@{self.server}:{self.port}/{self.database}"
                f"?driver={driver_enc}&trusted_connection=yes"
            )

        logger.debug(f"Using SQL authentication for user: {self.user}")
        return (
            f"mssql+pyodbc://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.server}:{self.port}/{self.database}"
            f"?driver={driver_enc}"
        )

    @classmethod
    def from_env(cls, prefix: str = 'DB') -> 'DatabaseConfig':
        """Build from environment variables with the given prefix.

        Required:
            {PREFIX}_SERVER, {PREFIX}_NAME
        Optional:
            {PREFIX}_USER, {PREFIX}_PASSWORD, {PREFIX}_DRIVER,
            {PREFIX}_PORT, {PREFIX}_TRUSTED_CONNECTION,
            {PREFIX}_TABLE_NAME, {PREFIX}_CONNECTION_TIMEOUT
        """
        server   = os.getenv(f'{prefix}_SERVER')
        database = os.getenv(f'{prefix}_NAME')

        if not server or not database:
            raise ValueError(
                f"\u274c Missing required environment variables: "
                f"{prefix}_SERVER and {prefix}_NAME\n"
                f"Set them in your .env file. See .env.example for a template."
            )

        trusted = os.getenv(f'{prefix}_TRUSTED_CONNECTION', 'no').lower() in ('yes', 'true', '1')

        return cls(
            server=server,
            database=database,
            driver=os.getenv(f'{prefix}_DRIVER', 'ODBC Driver 17 for SQL Server'),
            port=int(os.getenv(f'{prefix}_PORT', '1433')),
            user=os.getenv(f'{prefix}_USER'),
            password=os.getenv(f'{prefix}_PASSWORD'),
            trusted_connection=trusted,
            table_name=os.getenv(f'{prefix}_TABLE_NAME', 'wikiplast_prices'),
            connection_timeout=int(os.getenv(f'{prefix}_CONNECTION_TIMEOUT', '30')),
        )


@dataclass
class LogConfig:
    """Logging configuration."""
    level:          int = logging.INFO
    directory:      str = 'logs'
    format_detailed: str = (
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    format_simple:  str = '%(asctime)s - %(levelname)s - %(message)s'

    @classmethod
    def from_env(cls) -> 'LogConfig':
        levels = {
            'DEBUG': logging.DEBUG, 'INFO': logging.INFO,
            'WARNING': logging.WARNING, 'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL,
        }
        level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        return cls(
            level=levels.get(level_str, logging.INFO),
            directory=os.getenv('LOG_DIR', 'logs'),
        )


@dataclass
class RetryConfig:
    """Retry / back-off configuration."""
    max_attempts:              int   = 3
    wait_exponential_multiplier: int = 1
    wait_exponential_max:      int   = 10

    @classmethod
    def from_env(cls) -> 'RetryConfig':
        return cls(
            max_attempts=int(os.getenv('RETRY_MAX_ATTEMPTS', '3')),
            wait_exponential_multiplier=int(os.getenv('RETRY_WAIT_MULTIPLIER', '1')),
            wait_exponential_max=int(os.getenv('RETRY_WAIT_MAX', '10')),
        )


# ---------------------------------------------------------------------------
# Main Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """Top-level application configuration."""
    database: DatabaseConfig
    logging:  LogConfig
    retry:    RetryConfig

    @classmethod
    def from_env(cls, db_prefix: str = 'DB') -> 'Config':
        """Build full Config from environment / .env file."""
        return cls(
            database=DatabaseConfig.from_env(db_prefix),
            logging=LogConfig.from_env(),
            retry=RetryConfig.from_env(),
        )

    def create_engine(self, **kwargs):
        """Create and return a SQLAlchemy 2.0 Engine."""
        from sqlalchemy import create_engine as _create_engine

        defaults = {
            'echo': False,
            'pool_pre_ping': True,
            'pool_recycle': 3600,
            'connect_args': {'timeout': self.database.connection_timeout},
        }
        defaults.update(kwargs)
        return _create_engine(self.database.get_connection_string(), **defaults)

    def print_status(self) -> None:
        """Print resolved config to stdout (passwords masked)."""
        sep = '=' * 60
        print(f"\n{sep}\nConfiguration Status\n{sep}")

        db = self.database
        print("\nDatabase:")
        print(f"  Server   : {db.server}:{db.port}")
        print(f"  Database : {db.database}")
        print(f"  Driver   : {db.driver}")
        print(f"  Table    : {db.table_name}")
        print(f"  Auth     : {'Windows (trusted)' if db.trusted_connection else f'SQL ({db.user})'}")

        lg = self.logging
        print("\nLogging:")
        print(f"  Level    : {logging.getLevelName(lg.level)}")
        print(f"  Directory: {lg.directory}")

        rt = self.retry
        print("\nRetry:")
        print(f"  Max attempts : {rt.max_attempts}")
        print(f"  Back-off max : {rt.wait_exponential_max}s")
        print(f"\n{sep}\n")


# Auto-load .env on import
load_env_file()


if __name__ == '__main__':
    try:
        cfg = Config.from_env()
        cfg.print_status()
        engine = cfg.create_engine()
        print("\u2705 SQLAlchemy engine created successfully")
        engine.dispose()
    except (ValueError, FileNotFoundError) as e:
        print(f"\u274c Configuration error:\n{e}")
        raise SystemExit(1)
