#!/bin/bash
# Image proxy benchmark: legacy vs optimized vs cache hit.
cd "$(dirname "$0")/.."
PORT="${PORT:-18081}"
LOG=/tmp/zomic-bench.log
PORT="$PORT" IMAGE_CACHE_DIR=/tmp/zomic-bench-cache .venv/bin/python app.py > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 6

URL="https://img.komiku.org/cover/wmkomiku2.webp"
ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$URL")

echo "== legacy (no w) =="
curl -s -D /tmp/h1.txt -o /tmp/legacy.bin --max-time 30 "http://localhost:$PORT/api/img?url=$ENC"
grep -iE "^(HTTP|content-type|cache-control|x-image-cache)" /tmp/h1.txt
echo "legacy bytes: $(stat -c%s /tmp/legacy.bin)"

echo "== optimized w=400 format=auto q=78 (Accept avif/webp) =="
H='Accept: image/avif,image/webp,image/*'
curl -s -D /tmp/h2.txt -o /tmp/opt1.bin -H "$H" --max-time 30 "http://localhost:$PORT/api/img?url=$ENC&w=400&format=auto&q=78"
grep -iE "^(HTTP|content-type|cache-control|x-image-cache)" /tmp/h2.txt
echo "opt1 bytes: $(stat -c%s /tmp/opt1.bin)"

echo "== second request (cache) =="
curl -s -D /tmp/h3.txt -o /tmp/opt2.bin -H "$H" --max-time 30 "http://localhost:$PORT/api/img?url=$ENC&w=400&format=auto&q=78"
grep -iE "^(HTTP|content-type|cache-control|x-image-cache)" /tmp/h3.txt
echo "opt2 bytes: $(stat -c%s /tmp/opt2.bin)"

echo "== webp 800 =="
curl -s -D /tmp/h4.txt -o /tmp/opt3.bin --max-time 30 "http://localhost:$PORT/api/img?url=$ENC&w=800&format=webp&q=80"
grep -iE "^(HTTP|content-type|x-image-cache)" /tmp/h4.txt
echo "opt3 bytes: $(stat -c%s /tmp/opt3.bin)"

echo "== validity (can open + dims) =="
python3 -c "
from PIL import Image
import io
for f in ('/tmp/legacy.bin','/tmp/opt1.bin','/tmp/opt3.bin'):
    im = Image.open(f); im.load()
    print(f, im.format, im.size)
"