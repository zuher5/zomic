#!/usr/bin/env bash
# Zomic SQLite backup/restore helper (uses python3, no sqlite3 CLI required).
# Usage:
#   ./scripts/backup.sh backup [output_file]
#   ./scripts/backup.sh restore backup_file
#   ./scripts/backup.sh verify [backup_file]
set -euo pipefail

DB="${ZOMIC_DB:-zomic.db}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
TS="$(date +%Y%m%d-%H%M%S)"

case "${1:-}" in
  backup)
    mkdir -p "$BACKUP_DIR"
    OUT="${2:-$BACKUP_DIR/zomic-$TS.db}"
    python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
b = sqlite3.connect(dst)
con.backup(b)
b.close(); con.close()
PY
    echo "backup written to $OUT"
    ;;
  restore)
    [ $# -ge 2 ] || { echo "usage: restore <file>"; exit 1; }
    TMP="$DB.restore.tmp"
    python3 - "$2" "$TMP" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
b = sqlite3.connect(dst)
con.backup(b)
b.close(); con.close()
PY
    mv "$TMP" "$DB"
    echo "restored $2 -> $DB"
    ;;
  verify)
    FILE="${2:-$BACKUP_DIR/zomic-$TS.db}"
    python3 - "$FILE" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print("integrity:", con.execute("PRAGMA integrity_check;").fetchone()[0])
for t in ("comic", "chapter", "page"):
    print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
con.close()
PY
    echo "verify ok: $FILE"
    ;;
  *)
    echo "usage: $0 {backup|restore|verify} [file]"
    exit 1
    ;;
esac
