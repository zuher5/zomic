def sync_series(source, repo, queue, slug, *, with_pages=True):
    stats = {"new_chapters": 0, "existing_chapters": 0, "queued_pages": 0}

    source_id = repo.get_or_create_source(source.name, source.base_url)
    comic = source.get_comic(slug)
    comic_id = repo.upsert_comic(source_id, comic)

    for chapter in source.get_chapters(slug):
        existing = repo.get_chapter_id(comic_id, chapter.external_id)
        if existing is not None:
            stats["existing_chapters"] += 1
            continue
        repo.upsert_chapter(comic_id, chapter)
        stats["new_chapters"] += 1
        if with_pages:
            queue.enqueue_scrape_pages(slug, chapter.index)
            stats["queued_pages"] += 1

    if with_pages:
        queue.enqueue_download_images(slug)

    return stats