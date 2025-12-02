import logging
import sys
from pathlib import Path
from . import config

# ==============================================================================
# ANSI COLOR CODES (The Matrix Look)
# ==============================================================================
class ColorFormatter(logging.Formatter):
    """
    Custom formatter to inject colors into the Console Output only.
    """
    grey = "\x1b[38;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    
    # Format: Time | Level | [Logger] Message
    fmt = "%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s"

    FORMATS = {
        logging.DEBUG: grey + fmt + reset,
        logging.INFO: green + fmt + reset,
        logging.WARNING: yellow + fmt + reset,
        logging.ERROR: red + fmt + reset,
        logging.CRITICAL: bold_red + fmt + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%H:%M:%S')
        return formatter.format(record)

# ==============================================================================
# LOGGER FACTORY
# ==============================================================================
def get_logger(name="QuantOS"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Singleton Check: Don't add handlers if they exist (prevents dupes)
    if logger.hasHandlers():
        return logger

    # 1. FILE HANDLER (The Black Box - Plain Text, Detailed)
    # Stores full history in logs/system.log
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Ensure Path object is string for safety
    file_handler = logging.FileHandler(str(config.LOG_FILE), mode='a', encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    # 2. CONSOLE HANDLER (The Glass - Colorized, Speed)
    # Shows real-time activity in the terminal
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter())
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    return logger