# Zomic Deployment

## Requirements

- Python 3.11+ (tested on 3.14)
- Docker + Docker Compose (for containerized deployment)
- sqlite3 CLI (for backup scripts)
- Network access to the source API (`https://be.komikcast.cc/`) and image CDN

## 1. Installation (local)

```bash
cd zomic
python3 -m pip install -r requirements.txt
cp .env.example .env
```

## 2. Environment setup

Edit `.env`:

| Variable | Purpose |
| --- | --- |
| `ZOMIC_DB` | SQLite database file path (default `zomic.db`) |
| `STORAGE_ROOT` | Where downloaded images are stored |
| `IMAGE_REFERER` | Referer required by the image CDN (default `https://v3.komikcast.fit/`) |
| `ZOMIC_ADMIN_TOKEN` | Bearer token required for all `/api/admin/*` endpoints |

Admin endpoints return `503` until `ZOMIC_ADMIN_TOKEN` is set.

## 3. Scrape initial data

```bash
# one-off full scrape of a series (comic + chapters + pages into the DB)
python3 -m scraper.cli scrape kidnapped-the-youngest-daughter-of-the-sichuan-tang-family

# run the worker loop (processes queued jobs, downloads images)
python3 -m scraper.worker_cli --db zomic.db --storage data/images --referer https://v3.komikcast.fit/

# run the scheduler once (incremental update: only new chapters)
python3 -m scraper.cli schedule
```

## 4. Start (API)

```bash
ZOMIC_DB=zomic.db uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Public: `/api/comics`, `/api/search`, `/api/chapters/{id}/pages`
- Admin (Bearer token): `/api/admin/sources`, `/api/admin/jobs`, `/api/admin/scrape`

## 5. Start (Docker)

```bash
export ZOMIC_ADMIN_TOKEN=$(openssl rand -hex 32)
docker compose up -d --build
```

## 6. Stop

```bash
# local: Ctrl+C on the uvicorn/worker processes
# docker:
docker compose down
```

## 7. Backup

```bash
./scripts/backup.sh backup
./scripts/backup.sh verify backups/zomic-*.db
```

Restore:

```bash
./scripts/backup.sh restore backups/zomic-<timestamp>.db
```

## 8. Logs

- Local: stdout of the uvicorn/worker processes.
- Docker: `docker compose logs -f backend worker`

## 9. Troubleshooting

- **Images return 403**: the CDN requires the Referer header. Make sure the worker
  is started with `--referer https://v3.komikcast.fit/` (or `IMAGE_REFERER` set).
- **Admin returns 503**: `ZOMIC_ADMIN_TOKEN` is not set.
- **Chapter 404 on scrape**: the pages endpoint is keyed by chapter **index**, not id;
  the adapter handles this automatically.
- **Rate limit (429)**: public endpoints are rate limited per client IP (60 req/min).
- **`pydantic`/`watchfiles` build failures on some platforms**: pin
  `pydantic<2` and install plain `uvicorn` (not `uvicorn[standard]`).
