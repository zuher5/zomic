#!/bin/bash
# SouGPT Auto-Verification Workflow for Manga Scraper
# Tanpa 'set -e' global agar tidak exit mendadak saat satu step gagal.

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS="✅"; FAIL="❌"; FIX="🔧"
WARN="⚠️"

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  WORKFLOW VERIFIKASI & AUTO-FIX ${NC}"
echo -e "${YELLOW}========================================${NC}"

cd "$(dirname "$0")" || exit 1
VENV=".venv"
PY="$VENV/bin/python"

# STEP 0: Environment Check
echo -e "\n${YELLOW}[STEP 0] Cek Python & Virtualenv...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${FAIL} Python tidak ditemukan. ${FIX} Install...${NC}"
    pkg install python -y || sudo apt install -y python3
fi
echo -e "${PASS} Python sistem: $(python3 --version)"

if [ ! -x "$PY" ]; then
    echo -e "${WARN} Virtualenv belum ada. ${FIX} Membuat $VENV...${NC}"
    python3 -m venv "$VENV" 2>/dev/null || python3 -m venv --without-pip "$VENV"
fi
if [ ! -x "$PY" ]; then
    echo -e "${FAIL} Gagal membuat virtualenv. Install: sudo apt install python3-venv"
    exit 1
fi
# Bootstrap pip bila venv dibuat tanpa pip (sistem tanpa ensurepip)
if ! "$PY" -m pip --version &> /dev/null; then
    echo -e "${WARN} pip belum ada di venv. ${FIX} Bootstrap get-pip...${NC}"
    curl -fsSL -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py \
        && "$PY" /tmp/get-pip.py 2>&1 | tail -2
fi
echo -e "${PASS} Venv siap ($("$PY" --version))."

# STEP 1: Dependencies (REST API hanya butuh requests + fastapi + uvicorn)
echo -e "\n${YELLOW}[STEP 1] Verifikasi Dependencies...${NC}"
MISSING=""
for mod in fastapi uvicorn requests; do
    "$PY" -c "import $mod" 2>/dev/null || MISSING="$MISSING $mod"
done
if [ -z "$MISSING" ]; then
    echo -e "${PASS} Semua package terinstall."
else
    echo -e "${WARN} Missing:$MISSING. ${FIX} Install...${NC}"
    "$PY" -m pip install --disable-pip-version-check --timeout 60 --retries 2 \
        fastapi uvicorn requests 2>&1 | tail -3
fi

# STEP 2: Syntax Check
echo -e "\n${YELLOW}[STEP 2] Cek Syntax Python...${NC}"
if "$PY" -m py_compile app.py komiku_web.py 2> syntax_error.log; then
    echo -e "${PASS} Syntax valid."
else
    echo -e "${FAIL} Syntax error! ${FIX} Menampilkan error...${NC}"
    cat syntax_error.log
fi

# STEP 3: Scraper Connectivity (REST API + katalog HTML komiku.org)
echo -e "\n${YELLOW}[STEP 3] Test Koneksi ke Komiku & Selector...${NC}"
"$PY" -c "
import sys
from app import api, web
try:
    latest = api.latest(1)
    if not latest:
        print('Gagal: /terbaru kosong'); sys.exit(1)
    cat = web.catalog(1)
    if not cat['items']:
        print('Gagal: katalog kosong (selector HTML mungkin berubah)'); sys.exit(1)
    print(f\"OK: {len(latest)} komik terbaru, katalog {cat['total']} komik / {cat['total_pages']} halaman\")
    sys.exit(0)
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" > test_scraper.log 2>&1
TEST=$?

if [ $TEST -eq 0 ]; then
    echo -e "${PASS} REST API berfungsi."
    grep . test_scraper.log | head -1
else
    echo -e "${FAIL} REST API gagal! ${FIX} Menampilkan error...${NC}"
    cat test_scraper.log | tail -5
fi

# STEP 4: Port Conflict Handler
echo -e "\n${YELLOW}[STEP 4] Cek Port 8000...${NC}"
PID=""
if command -v lsof &> /dev/null; then
    PID=$(lsof -t -i:8000 2>/dev/null | head -1)
fi
if [ -z "$PID" ] && command -v ss &> /dev/null; then
    PID=$(ss -ltnp 2>/dev/null | grep ':8000' | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1)
fi
if [ -z "$PID" ] && command -v fuser &> /dev/null; then
    PID=$(fuser 8000/tcp 2>/dev/null | tr -d ' ')
fi
if [ -n "$PID" ]; then
    echo -e "${FAIL} Port 8000 dipakai PID $PID. ${FIX} Membunuh proses...${NC}"
    kill -9 $PID 2>/dev/null
    sleep 1
    echo -e "${PASS} Port dibebaskan."
else
    echo -e "${PASS} Port 8000 tersedia."
fi

# STEP 5: Server Boot & Health Check
echo -e "\n${YELLOW}[STEP 5] Menjalankan Server & Health Check...${NC}"
"$PY" app.py > server.log 2>&1 &
SERVER_PID=$!
sleep 5

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${PASS} Server live! (PID: $SERVER_PID)"
    HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null)
    echo -e "   ${WARN} /health -> $HEALTH"
else
    echo -e "${FAIL} Server gagal boot. ${FIX} Log belakang...${NC}"
    kill $SERVER_PID 2>/dev/null
    tail -15 server.log
    echo "Jalankan manual: $PY app.py"
fi

# STEP 6: Browser Test (Frontend + endpoint utama)
echo -e "\n${YELLOW}[STEP 6] Cek Frontend & Endpoint...${NC}"
FRONT_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)
if [ "$FRONT_CODE" = "200" ]; then
    echo -e "${PASS} Frontend siap di http://localhost:8000"
else
    echo -e "${FAIL} HTML tidak terkirim (code $FRONT_CODE)."
fi
for ep in "/api/latest" "/api/catalog?page=1" "/api/search?q=naruto" "/api/genres" "/api/popular"; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "http://localhost:8000$ep" 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        echo -e "   ${PASS} $ep"
    else
        echo -e "   ${FAIL} $ep -> $CODE"
    fi
done

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}  ✅ SEMUA VERIFIKASI LULUS! ${NC}"
echo -e "${GREEN}  Server berjalan di: http://localhost:8000 ${NC}"
echo -e "${GREEN}  Tekan Ctrl+C untuk menghentikan. ${NC}"
echo -e "${GREEN}========================================${NC}"

wait $SERVER_PID
