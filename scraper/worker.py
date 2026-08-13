from .downloader import DownloadError, ImageDownloader
from .queue import JobQueue
from .repository import Repository
from .sources.komikcast import KomikCastSource
from .storage import FileStorage

def make_source(name):
    if name == "komikcast":
        return KomikCastSource()
    raise ValueError(f"unknown source: {name}")


class Worker:
    def __init__(
        self,
        db_path,
        *,
        storage_root,
        storage_base_url=None,
        referer=None,
        source_factory=make_source,
        allow_private=False,
    ):
        self.db_path = db_path
        self.repo = Repository(db_path)
        self.queue = JobQueue(db_path)
        self.storage = FileStorage(storage_root, storage_base_url)
        self.downloader = ImageDownloader(
            self.storage,
            referer=referer,
            allowed_hosts=referer_hosts(referer),
            allow_private=allow_private,
        )
        self.source_factory = source_factory

    def process_job(self, job):
        job_type = job["type"]
        payload = job["payload"]
        if job_type == "scrape_comic":
            return self._scrape_comic(payload["slug"])
        if job_type == "scrape_chapters":
            return self._scrape_chapters(payload["slug"])
        if job_type == "scrape_pages":
            return self._scrape_pages(payload["slug"], payload["chapter"])
        if job_type == "download_images":
            return self._download_images(payload.get("slug"))
        raise ValueError(f"unknown job type: {job_type}")

    def _scrape_comic(self, slug):
        source = self._source_for_slug(slug)
        if source is None:
            return False
        source_id = self.repo.get_or_create_source(source.name, source.base_url)
        comic = source.get_comic(slug)
        comic_id = self.repo.upsert_comic(source_id, comic)
        for chapter in source.get_chapters(slug):
            self.repo.upsert_chapter(comic_id, chapter)
            self.queue.enqueue_scrape_pages(slug, chapter.index)
        return True

    def _scrape_chapters(self, slug):
        source = self._source_for_slug(slug)
        if source is None:
            return False
        source_id = self.repo.get_or_create_source(source.name, source.base_url)
        comic = source.get_comic(slug)
        comic_id = self.repo.upsert_comic(source_id, comic)
        for chapter in source.get_chapters(slug):
            self.repo.upsert_chapter(comic_id, chapter)
        return True

    def _scrape_pages(self, slug, chapter_ref):
        source = self._source_for_slug(slug)
        if source is None:
            return False
        chapter_id = self._chapter_id_for_ref(slug, chapter_ref)
        if chapter_id is None:
            return False
        pages = source.get_pages(slug, chapter_ref)
        self.repo.upsert_pages(chapter_id, pages)
        return True

    def _download_images(self, slug=None):
        pending = self.repo.get_pending_pages(limit=50)
        for page in pending:
            if slug and page["slug"] != slug:
                continue
            try:
                key = self.downloader.download(page["url"])
                self.repo.mark_page_downloaded(page["page_id"], key)
            except DownloadError:
                continue
        return True

    def _source_for_slug(self, slug):
        source_row = self.repo.conn.execute(
            "SELECT s.name, s.base_url, s.enabled FROM source s"
            " JOIN comic c ON c.source_id = s.id WHERE c.slug = ? LIMIT 1",
            (slug,),
        ).fetchone()
        if source_row is None:
            source_row = self.repo.conn.execute(
                "SELECT name, base_url, enabled FROM source LIMIT 1"
            ).fetchone()
        if source_row is None:
            source = self.source_factory("komikcast")
        else:
            source = self.source_factory(source_row["name"])
        if source_row is not None and not source_row["enabled"]:
            raise RuntimeError("source disabled")
        return source

    def _chapter_id_for_ref(self, slug, chapter_ref):
        row = self.repo.conn.execute(
            """
            SELECT ch.id FROM chapter ch
            JOIN comic c ON c.id = ch.comic_id
            WHERE c.slug = ? AND (ch.external_id = ? OR ch.idx = ?)
            LIMIT 1
            """,
            (slug, str(chapter_ref), int(chapter_ref)),
        ).fetchone()
        return row["id"] if row else None

    def drain(self):
        processed = 0
        while True:
            job = self.queue.claim_next()
            if job is None:
                break
            processed += 1
            try:
                self.process_job(job)
                self.queue.complete(job["id"])
            except Exception as exc:  # noqa: BLE001
                self.queue.fail(job["id"], exc)
        return processed


def referer_hosts(referer):
    if not referer:
        return ()
    from urllib.parse import urlparse

    host = urlparse(referer).hostname
    return (host,) if host else ()