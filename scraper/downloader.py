import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath

from .storage import FileStorage

IMG_MAGIC = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",
    b"\x89JP\r\n\x1a\n": "jxl",
}


class DownloadError(Exception):
    pass


class UnsupportedUrl(DownloadError):
    pass


class OversizedContent(DownloadError):
    pass


class InvalidImage(DownloadError):
    pass


PRIVATE_PREFIXES = (
    "127.",
    "10.",
    "192.168.",
    "169.254.",
)


def sanitize_url(url, allowed_hosts=(), allow_private=False):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsupportedUrl(f"unsupported scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise UnsupportedUrl("missing host")
    host = parsed.hostname.lower()
    if not allow_private and (
        host in ("localhost", "::1")
        or host.startswith(PRIVATE_PREFIXES)
        or host == "0.0.0.0"
    ):
        raise UnsupportedUrl(f"blocked private host: {host}")
    if allowed_hosts and host not in {h.lower() for h in allowed_hosts}:
        raise UnsupportedUrl(f"host not allowed: {host}")
    return url


def detect_image_type(data: bytes):
    for magic, ext in IMG_MAGIC.items():
        if data.startswith(magic):
            return ext
    return None


class ImageDownloader:
    def __init__(
        self,
        storage: FileStorage,
        *,
        timeout=15.0,
        retries=3,
        backoff=1.0,
        referer=None,
        max_bytes=10 * 1024 * 1024,
        allowed_hosts=(),
        concurrency=4,
        allow_private=False,
    ):
        self.storage = storage
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.referer = referer
        self.max_bytes = max_bytes
        self.allowed_hosts = tuple(allowed_hosts)
        self.concurrency = concurrency
        self.allow_private = allow_private

    def _request(self, url):
        sanitize_url(url, self.allowed_hosts, self.allow_private)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Zomic/0.1 (comic scraper)",
                "Accept": "image/*",
                **({"Referer": self.referer} if self.referer else {}),
            },
        )
        res = urllib.request.urlopen(req, timeout=self.timeout)
        try:
            if res.headers.get("Content-Length"):
                length = int(res.headers["Content-Length"])
                if length > self.max_bytes:
                    raise OversizedContent(f"too large: {length}")
            return res.read(self.max_bytes + 1)
        finally:
            res.close()

    def _download_bytes(self, url):
        last_error = None
        for attempt in range(self.retries):
            try:
                data = self._request(url)
                if len(data) > self.max_bytes:
                    raise OversizedContent(f"too large: {len(data)}")
                return data
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(self.backoff * (2 ** attempt))
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    last_error = exc
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                raise DownloadError(f"HTTP {exc.code}: {url}") from exc
        raise DownloadError(f"failed after {self.retries} attempts: {url}") from last_error

    def download(self, url) -> str:
        data = self._download_bytes(url)
        ext = detect_image_type(data)
        if ext is None:
            raise InvalidImage(f"not an image: {url}")
        key = self.storage.key_from_url(url, ext)
        self.storage.save(data, key)
        return key

    def download_many(self, urls):
        results = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = {pool.submit(self.download, u): u for u in urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    results[url] = future.result()
                except DownloadError as exc:
                    results[url] = f"error: {exc}"
        return results