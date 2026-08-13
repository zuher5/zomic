FROM python:3.11-slim

WORKDIR /app

COPY scraper/ ./scraper/
COPY backend/ ./backend/
COPY web/ ./web/
COPY app.py komiku_web.py ./
COPY requirements.txt .
COPY .env.example .env.example

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1 \
    IMAGE_CACHE_DIR=/tmp/zomic-image-cache

RUN mkdir -p /tmp/zomic-image-cache

EXPOSE 8000

# Jalankan web komik utama (app.py / app:app), bukan backend.api yang hanya
# menyediakan API scraper tanpa endpoint frontend Zomic.
CMD ["python", "app.py"]
