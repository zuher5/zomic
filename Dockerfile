FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY web/ ./web/
COPY app.py komiku_web.py kiryuu_web.py ./

ENV PYTHONUNBUFFERED=1 \
    IMAGE_CACHE_DIR=/tmp/zomic-image-cache

RUN mkdir -p /tmp/zomic-image-cache

EXPOSE 8000

CMD ["python", "app.py"]