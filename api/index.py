"""Vercel serverless entrypoint untuk aplikasi FastAPI Zomic.

Vercel Python runtime auto-deteksi app ASGI yang di-export sebagai `app`.
File ini ada di subfolder `api/`, jadi tambahkan root project ke sys.path
agar `from app import app` berhasil di runtime serverless.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import app  # noqa: E402  (ASGI app Zomic)