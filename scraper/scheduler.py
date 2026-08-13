from .incremental import sync_series
from .queue import JobQueue
from .repository import Repository
from .worker import make_source


def run_scheduler_once(db_path, *, with_pages=True, source_factory=make_source):
    repo = Repository(db_path)
    queue = JobQueue(db_path)
    comics = repo.conn.execute(
        "SELECT c.slug, s.name FROM comic c JOIN source s ON s.id = c.source_id"
    ).fetchall()
    reports = []
    for row in comics:
        slug = row["slug"]
        name = row["name"]
        try:
            source = source_factory(name)
            stats = sync_series(source, repo, queue, slug, with_pages=with_pages)
            reports.append({"slug": slug, "stats": stats})
        except Exception as exc:  # noqa: BLE001
            reports.append({"slug": slug, "error": str(exc)})
    repo.close()
    queue.close()
    return reports