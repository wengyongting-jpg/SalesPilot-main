# -*- coding: utf-8 -*-
"""Conversation and decision logging (minimal implementation of FR-13)."""
import logging

from . import config

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure a logger writing to both file and console; safe to call repeatedly."""
    global _CONFIGURED
    logger = logging.getLogger("salespilot")
    if _CONFIGURED:
        return logger

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(level)

    file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    console_handler.setLevel(logging.WARNING)  # Keep the console quiet; full log to file

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    _CONFIGURED = True
    return logger
