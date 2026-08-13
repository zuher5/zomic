import hashlib
import os


class Storage:
    def save(self, data: bytes, key: str) -> str:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def get_url(self, key: str) -> str:
        raise NotImplementedError


class FileStorage(Storage):
    def __init__(self, root, base_url=None):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.base_url = (base_url or "").rstrip("/")

    def _path(self, key):
        return os.path.join(self.root, key)

    def save(self, data: bytes, key: str) -> str:
        path = self._path(key)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return self.get_url(key)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def delete(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)

    def get_url(self, key: str) -> str:
        if self.base_url:
            return f"{self.base_url}/{key}"
        return self._path(key)

    @staticmethod
    def key_from_url(url: str, ext: str = "jpg") -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return f"images/{digest[:2]}/{digest[2:]}.{ext}"