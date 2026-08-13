from typing import Callable, List

from .base import ChapterInfo, ComicInfo, ComicSource, PageInfo
from ..http import request_json


class KomikCastSource(ComicSource):
    """Adapter for KomikCast v3 (backend: https://be.komikcast.cc/)."""

    name = "komikcast"

    def __init__(
        self,
        base_url="https://be.komikcast.cc/",
        referer="https://v3.komikcast.fit/",
        fetcher: Callable = request_json,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.referer = referer
        self._fetcher = fetcher

    def _url(self, path):
        return self.base_url + path.lstrip("/")

    def _get(self, path):
        return self._fetcher(self._url(path), referer=self.referer)

    def search(self, keyword: str, page: int = 1) -> List[ComicInfo]:
        data = self._get(f"series?search={keyword}&page={page}")
        items = data.get("data") or []
        return [self._to_comic(item) for item in items]

    def get_comic(self, slug: str) -> ComicInfo:
        return self._to_comic(self._get(f"series/{slug}")["data"])

    def get_chapters(self, slug: str) -> List[ChapterInfo]:
        items = self._get(f"series/{slug}/chapters")["data"]
        return [self._to_chapter(item) for item in items]

    def get_pages(self, slug: str, chapter_ref) -> List[PageInfo]:
        data = self._get(f"series/{slug}/chapters/{chapter_ref}")["data"]
        images = data.get("data", {}).get("images") or []
        return [
            PageInfo(source=self.name, url=url, position=i)
            for i, url in enumerate(images, start=1)
        ]

    def _to_comic(self, item: dict) -> ComicInfo:
        d = item.get("data") or {}
        return ComicInfo(
            source=self.name,
            external_id=str(item.get("id", "")),
            slug=d.get("slug", ""),
            title=d.get("title", ""),
            synopsis=d.get("synopsis", ""),
            author=d.get("author", ""),
            cover_url=d.get("coverImage", ""),
            status=d.get("status", ""),
            format=d.get("format", ""),
            rating=float(d.get("rating", 0) or 0),
            genres=[g.get("data", {}).get("name", "") for g in (d.get("genres") or [])],
            raw=item,
        )

    def _to_chapter(self, item: dict) -> ChapterInfo:
        d = item.get("data") or {}
        return ChapterInfo(
            source=self.name,
            external_id=str(item.get("id", "")),
            index=int(d.get("index", 0) or 0),
            slug=d.get("slug") or "",
            title=d.get("title") or "",
            raw=item,
        )