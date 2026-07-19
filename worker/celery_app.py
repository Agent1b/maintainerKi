from __future__ import annotations

from celery import Celery
from celery.signals import worker_init

from server.config import settings
from server.db import init_database, run_database_migrations

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
    # Bound the broker socket wait so a black-holed broker can't hang health checks
    # (or task dispatch) for the OS TCP timeout.
    broker_transport_options={
        "socket_timeout": 3,
        "socket_connect_timeout": 3,
        "retry_on_timeout": True,
    },
    task_always_eager=settings.celery_task_always_eager,
    task_ignore_result=True,
)


def prepare_worker_runtime(**_: object) -> None:
    init_database()
    run_database_migrations()


worker_init.connect(prepare_worker_runtime, weak=False)
