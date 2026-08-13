import os
import time
import urllib.request
from collections import deque
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from scraper.downloader import DownloadError, UnsupportedUrl, detect_image_type, sanitize_url
from scraper.queue import JobQueue
from scraper.repository import Repository

DB_PATH = os.environ.get("ZOMIC_DB", "zomic.db")
ADMIN_TOKEN = os.environ.get("ZOMIC_ADMIN_TOKEN", "")

app = FastAPI(title="Zomic API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)


def db_path():
    return os.environ.get("ZOMIC_DB", DB_PATH)


def admin_token():
    return os.environ.get("ZOMIC_ADMIN_TOKEN", "")


def get_repo():
    return Repository(db_path())


def get_queue():
    return JobQueue(db_path())


def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> None:
    token = admin_token()
    if not token:
        raise HTTPException(status_code=503, detail="admin token not configured")
    if credentials is None or credentials.credentials != token:
        raise HTTPException(status_code=401, detail="unauthorized")


class RateLimiter:
    def __init__(self, max_requests=60, window=60):
        self.max_requests = max_requests
        self.window = window
        self.hits = {}

    def allow(self, key):
        now = time.time()
        bucket = self.hits.get(key)
        if bucket is None:
            self.hits[key] = deque([now], maxlen=self.max_requests)
            return True
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            return False
        bucket.append(now)
        return True


limiter = RateLimiter()

IMAGE_MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp", "jxl": "image/jxl"}


def image_cdn_hosts():
    return tuple(
        h.strip()
        for h in os.environ.get(
            "IMAGE_CDN_HOSTS",
            "sv1.imgkc1.my.id,minio.imgkc1.my.id",
        ).split(",")
        if h.strip()
    )


def image_referer():
    return os.environ.get("IMAGE_REFERER", "https://v3.komikcast.fit/")


def image_allow_private():
    return os.environ.get("IMAGE_ALLOW_PRIVATE", "0") == "1"


def rate_limit(request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not limiter.allow(key):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


@app.get("/api/images", dependencies=[Depends(rate_limit)])
def proxy_image(url: str = Query(..., min_length=1)):
    try:
        sanitize_url(url, allowed_hosts=image_cdn_hosts(), allow_private=image_allow_private())
    except UnsupportedUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Zomic/0.1 (comic scraper)",
            "Referer": image_referer(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            data = res.read(11 * 1024 * 1024)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="upstream fetch failed") from exc
    ext = detect_image_type(data)
    if ext is None:
        raise HTTPException(status_code=502, detail="upstream returned non-image")
    return Response(
        content=data,
        media_type=IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/search", dependencies=[Depends(rate_limit)])
def search_comics(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),
):
    repo = get_repo()
    offset = (page - 1) * limit
    items = repo.search_comics(q, limit=limit, offset=offset)
    return {
        "data": items,
        "meta": {"query": q, "page": page, "limit": limit, "total": repo.count_search_comics(q)},
    }


@app.get("/api/comics", dependencies=[Depends(rate_limit)])
def list_comics(limit: int = Query(20, ge=1, le=100), page: int = Query(1, ge=1)):
    repo = get_repo()
    offset = (page - 1) * limit
    items = repo.list_comics(limit=limit, offset=offset)
    return {"data": items, "meta": {"page": page, "limit": limit, "total": repo.counts()["comic"]}}


@app.get("/api/comics/{comic_id}")
def get_comic(comic_id: int):
    repo = get_repo()
    comic = repo.get_comic_by_id(comic_id)
    if comic is None:
        raise HTTPException(status_code=404, detail="comic not found")
    return {"data": comic}


@app.get("/api/comics/{comic_id}/chapters")
def list_comic_chapters(comic_id: int):
    repo = get_repo()
    if repo.get_comic_by_id(comic_id) is None:
        raise HTTPException(status_code=404, detail="comic not found")
    return {"data": repo.list_chapters(comic_id)}


@app.get("/api/chapters/{chapter_id}")
def get_chapter(chapter_id: int):
    repo = get_repo()
    chapter = repo.get_chapter_by_id(chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return {"data": chapter}


@app.get("/api/chapters/{chapter_id}/pages")
def list_chapter_pages(chapter_id: int):
    repo = get_repo()
    if repo.get_chapter_by_id(chapter_id) is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return {"data": repo.list_pages(chapter_id)}


@app.get("/api/admin/sources", dependencies=[Depends(require_admin)])
def admin_list_sources():
    return {"data": get_repo().list_sources()}


@app.post(
    "/api/admin/sources/{source_id}/enable",
    dependencies=[Depends(require_admin)],
)
def admin_enable_source(source_id: int):
    repo = get_repo()
    if repo.get_source(source_id) is None:
        raise HTTPException(status_code=404, detail="source not found")
    repo.set_source_enabled(source_id, True)
    return {"data": repo.get_source(source_id)}


@app.post(
    "/api/admin/sources/{source_id}/disable",
    dependencies=[Depends(require_admin)],
)
def admin_disable_source(source_id: int):
    repo = get_repo()
    if repo.get_source(source_id) is None:
        raise HTTPException(status_code=404, detail="source not found")
    repo.set_source_enabled(source_id, False)
    return {"data": repo.get_source(source_id)}


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def admin_jobs(status: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=200)):
    queue = get_queue()
    return {"counts": queue.counts(), "data": queue.list_jobs(status=status, limit=limit)}


@app.post("/api/admin/scrape", dependencies=[Depends(require_admin)])
def admin_scrape(
    slug: str = Query(..., min_length=1),
    action: str = Query(..., pattern="^(scrape_comic|refresh_chapters|retry_failed)$"),
):
    queue = get_queue()
    if action == "scrape_comic":
        job_id = queue.enqueue_scrape_comic(slug)
    elif action == "refresh_chapters":
        job_id = queue.enqueue_scrape_chapters(slug)
    else:
        job_ids = queue.retry_failed()
        return {"data": {"retried": job_ids, "count": len(job_ids)}}
    return {"data": {"job_id": job_id, "action": action, "slug": slug}}