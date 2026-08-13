from dataclasses import dataclass, field
from typing import List


@dataclass
class ComicInfo:
    source: str
    external_id: str
    slug: str
    title: str
    synopsis: str = ""
    author: str = ""
    cover_url: str = ""
    status: str = ""
    format: str = ""
    rating: float = 0.0
    genres: List[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class ChapterInfo:
    source: str
    external_id: str
    index: int
    slug: str = ""
    title: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class PageInfo:
    source: str
    url: str
    position: int
    raw: dict = field(default_factory=dict)


class ComicSource:
    name = "base"

    def search(self, keyword: str, page: int = 1) -> List[ComicInfo]:
        raise NotImplementedError

    def get_comic(self, slug: str) -> ComicInfo:
        raise NotImplementedError

    def get_chapters(self, slug: str) -> List[ChapterInfo]:
        raise NotImplementedError

    def get_pages(self, slug: str, chapter_ref) -> List[PageInfo]:
        raise NotImplementedError