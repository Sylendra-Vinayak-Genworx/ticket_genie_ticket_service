from celery import Celery
from celery.schedules import crontab

from src.config.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "ticketing_service",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
    include=[
        "src.core.tasks.sla_tasks",
        "src.core.tasks.assignment_task",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    "detect-sla-breaches": {
        "task": "tasks.detect_sla_breaches",
        "schedule": crontab(minute="*/5"),
    },
    "auto-close-resolved-tickets": {
        "task": "tasks.auto_close_resolved_tickets",
        "schedule": crontab(minute="0"),
    },
    "check-lead-timeout": {
        "task": "tasks.check_lead_timeout",
        "schedule": crontab(minute="*/2"),  
    },
}