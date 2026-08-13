import hashlib
import json
import time
import urllib.error
import urllib.request

HEADERS = {
    "User-Agent": "Zomic/0.1 (comic scraper; contact: none)",
    "Accept": "application/json",
}


class HttpError(Exception):
    pass


def request_json(
    url,
    *,
    referer=None,
    timeout=15.0,
    retries=3,
    backoff=1.0,
    max_backoff=8.0,
):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer

    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                last_error = exc
            elif exc.code == 404:
                raise HttpError(f"not found: {url}") from exc
            else:
                raise HttpError(
                    f"HTTP {exc.code} for {url}"
                ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc

        if last_error is not None and attempt < retries - 1:
            time.sleep(min(backoff * (2 ** attempt), max_backoff))

    raise HttpError(f"request failed after {retries} attempts: {url}") from last_error


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()