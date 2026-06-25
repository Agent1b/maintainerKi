from __future__ import annotations

from worker.celery_app import celery_app


@celery_app.task(
    name="maintainerki.process_contribution_event",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_contribution_event_task(delivery_id: str) -> None:
    from server.ingestion import process_webhook_delivery

    process_webhook_delivery(delivery_id)
