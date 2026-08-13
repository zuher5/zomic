from .repository import Repository


def scrape_series(source, repository: Repository, slug, *, with_pages=True):
    source_id = repository.get_or_create_source(source.name, source.base_url)
    comic = source.get_comic(slug)
    comic_id = repository.upsert_comic(source_id, comic)

    for chapter in source.get_chapters(slug):
        repository.upsert_chapter(comic_id, chapter)
        if with_pages:
            chapter_id = repository.get_chapter_id(comic_id, chapter.external_id)
            pages = source.get_pages(slug, chapter.index)
            repository.upsert_pages(chapter_id, pages)