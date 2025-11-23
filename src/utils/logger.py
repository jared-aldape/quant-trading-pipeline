import logging
import sys
from . import config

def get_logger(name="QuantPipe"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if logger.hasHandlers():
        return logger

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File Handler (The Black Box)
    file_handler = logging.FileHandler(config.LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console Handler (The Dashboard)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger