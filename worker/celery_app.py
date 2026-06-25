from __future__ import annotations

from celery import Celery

from server.config import settings

broker_url = settings.celery_broker_url or settings.redis_url
result_backend = settings.celery_result_backend or broker_url

celery_app = Celery(
    "maintainerki",
    broker=broker_url,
    backend=result_backend,
    include=["worker.tasks.score_task"],
)

celery_app.conf.update(
    task_default_queue="maintainerki",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_ignore_result=True,
)
