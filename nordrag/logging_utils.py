"""Bounded local event logs: callers log fixed event names/counts, never contents."""
import logging
from logging.handlers import RotatingFileHandler
from .util import data_home

logger = logging.getLogger('nordrag')
logger.addHandler(logging.NullHandler())
logger.propagate = False


def configure_logging(mode):
    if mode not in ('builder', 'chat'):
        raise ValueError('Unknown log mode')
    folder = data_home() / 'logs'
    folder.mkdir(parents=True, exist_ok=True)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(folder / f'{mode}.log', maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info('application_started mode=%s', mode)
