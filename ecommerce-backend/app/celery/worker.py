from celery import Celery
from fastapi import HTTPException
from kombu.exceptions import OperationalError

from app.core.config import settings



celery_app = Celery(
    "ecommerce",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)


celery_app.autodiscover_tasks(
    [
        "app.celery"
    ]
)

celery_app.conf.beat_schedule = {
    "system-heartbeat-every-minute": {
        "task": "periodic_system_heartbeat",
        "schedule": 60.0,
    },
}
celery_app.conf.timezone = "UTC"


def require_celery_worker() -> None:
    try:
        workers = celery_app.control.ping(timeout=1)
    except OperationalError as error:
        raise HTTPException(
            status_code=503,
            detail="Background processing is unavailable. Start the Celery worker and try again.",
        ) from error
    if not workers:
        raise HTTPException(
            status_code=503,
            detail="No Celery worker is running. Start the worker and try again.",
        )