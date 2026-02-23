"""
config/logging_config.py
------------------------
Structured, production-grade logging setup.
Writes JSON-formatted logs in production, human-readable in development.
"""

from __future__ import annotations

import logging
import logging.config
import sys
from pathlib import Path
from typing import Any, Dict

from config.settings import AppEnvironment, get_settings

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def _build_formatters(is_production: bool) -> Dict[str, Any]:
    if is_production:
        return {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            }
        }
    return {
        "console": {
            "format": (
                "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    }


def _build_handlers(is_production: bool) -> Dict[str, Any]:
    formatter = "json" if is_production else "console"
    handlers: Dict[str, Any] = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": formatter,
            "level": "DEBUG",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "devmanager.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10 MB
            "backupCount": 5,
            "formatter": formatter,
            "encoding": "utf-8",
            "level": "INFO",
        },
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "errors.log"),
            "maxBytes": 5 * 1024 * 1024,  # 5 MB
            "backupCount": 3,
            "formatter": formatter,
            "encoding": "utf-8",
            "level": "ERROR",
        },
    }
    return handlers


def configure_logging() -> None:
    """
    Configure the root logger and per-package loggers.
    Must be called once at application startup (main.py).
    """
    settings = get_settings()
    is_prod = settings.is_production
    log_level = settings.log_level.value

    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": _build_formatters(is_prod),
        "handlers": _build_handlers(is_prod),
        "loggers": {
            # Application namespaces
            "devmanager": {
                "handlers": ["console", "file", "error_file"],
                "level": log_level,
                "propagate": False,
            },
            # Silence noisy third-party loggers
            "watchdog": {"level": "WARNING"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "uvicorn.access": {"level": "WARNING"},
        },
        "root": {
            "handlers": ["console"],
            "level": "WARNING",
        },
    }

    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """
    Return a namespaced logger under the 'devmanager' hierarchy.

    Usage:
        logger = get_logger(__name__)
    """
    return logging.getLogger(f"devmanager.{name}")


# ── Reserved LogRecord field protection ──────────────────────────────────────
# Python's logging raises KeyError if extra={} contains reserved field names
# like "name", "message", "args", etc. This patch silently prefixes them with
# "ctx_" so logging calls never crash regardless of key names used.

_RESERVED_LOG_FIELDS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "taskName",
})

_original_make_record = logging.Logger.makeRecord


def _safe_make_record(self, name, level, fn, lno, msg, args, exc_info,
                      func=None, extra=None, sinfo=None):
    if extra:
        extra = {
            (f"ctx_{k}" if k in _RESERVED_LOG_FIELDS else k): v
            for k, v in extra.items()
        }
    return _original_make_record(
        self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
    )


logging.Logger.makeRecord = _safe_make_record