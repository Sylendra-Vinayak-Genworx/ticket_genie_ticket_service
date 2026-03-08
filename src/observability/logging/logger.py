import logging
import sys
from typing import cast

import structlog

from src.config.settings import get_settings


def setup_logging() -> None:
    log_level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger,
                 structlog.get_logger(name).bind(service="ticketing_service"))
