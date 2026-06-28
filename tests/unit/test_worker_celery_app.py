from __future__ import annotations

from worker import celery_app as celery_module


def test_prepare_worker_runtime_initializes_and_migrates(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(celery_module, "init_database", lambda: calls.append("init"))
    monkeypatch.setattr(
        celery_module,
        "run_database_migrations",
        lambda: calls.append("migrate"),
    )

    celery_module.prepare_worker_runtime()

    assert calls == ["init", "migrate"]


def test_worker_init_signal_prepares_runtime(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(celery_module, "init_database", lambda: calls.append("init"))
    monkeypatch.setattr(
        celery_module,
        "run_database_migrations",
        lambda: calls.append("migrate"),
    )

    celery_module.worker_init.send(sender=celery_module.celery_app)

    assert calls == ["init", "migrate"]
