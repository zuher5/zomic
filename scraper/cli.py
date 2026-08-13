import argparse
import os

from .queue import JobQueue
from .repository import Repository
from .scheduler import run_scheduler_once
from .service import scrape_series
from .sources.komikcast import KomikCastSource


def cmd_scrape(args):
    repo = Repository(args.db)
    scrape_series(KomikCastSource(), repo, args.slug, with_pages=args.pages)
    print(repo.counts())
    repo.close()


def cmd_schedule(args):
    reports = run_scheduler_once(args.db, with_pages=True)
    for report in reports:
        print(report)


def main():
    parser = argparse.ArgumentParser(description="Zomic CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    scrape = sub.add_parser("scrape", help="scrape a full series")
    scrape.add_argument("slug")
    scrape.add_argument("--db", default=os.environ.get("ZOMIC_DB", "zomic.db"))
    scrape.add_argument("--no-pages", action="store_false", dest="pages")
    scrape.set_defaults(func=cmd_scrape)

    schedule = sub.add_parser("schedule", help="run scheduler once (incremental)")
    schedule.add_argument("--db", default=os.environ.get("ZOMIC_DB", "zomic.db"))
    schedule.set_defaults(func=cmd_schedule)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()