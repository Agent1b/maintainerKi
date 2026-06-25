from __future__ import annotations

import argparse

from server.ingestion import requeue_persisted_deliveries


def main() -> None:
    parser = argparse.ArgumentParser(description="Requeue persisted maintainerKi webhook deliveries.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of deliveries to requeue.")
    args = parser.parse_args()

    count = requeue_persisted_deliveries(limit=args.limit)
    print(f"Requeued {count} persisted webhook deliveries.")


if __name__ == "__main__":
    main()
