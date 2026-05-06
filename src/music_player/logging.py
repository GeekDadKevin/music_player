import logging
import os


def get_logger(name: str) -> logging.Logger:
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "music_player.log")
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    # Remove any existing handlers of the same type to avoid duplicates
    for h in list(logger.handlers):
        if isinstance(h, (logging.FileHandler, logging.StreamHandler)):
            logger.removeHandler(h)
    # File handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    return logger
