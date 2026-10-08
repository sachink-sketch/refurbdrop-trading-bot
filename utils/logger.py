import logging
import os
from pathlib import Path
from rich.logging import RichHandler
from rich.console import Console

console = Console()


def setup_logger(name: str = "trading_bot", log_file: str = "./logs/bot.log", level: str = "INFO") -> logging.Logger:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        # Console (rich)
        rich_handler = RichHandler(console=console, rich_tracebacks=True, markup=True)
        rich_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.addHandler(rich_handler)

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

    return logger


logger = setup_logger()
