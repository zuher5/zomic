import argparse
import os
import time

from .worker import Worker


def main():
    parser = argparse.ArgumentParser(description="Run the Zomic worker.")
    parser.add_argument("--db", default=os.environ.get("ZOMIC_DB", "zomic.db"))
    parser.add_argument(
        "--storage", default=os.environ.get("STORAGE_ROOT", "data/images")
    )
    parser.add_argument("--referer", default=os.environ.get("IMAGE_REFERER", ""))
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()

    worker = Worker(args.db, storage_root=args.storage, referer=args.referer or None)
    while True:
        processed = worker.drain()
        time.sleep(args.interval if processed == 0 else 0.5)


if __name__ == "__main__":
    main()