from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


@dataclass(frozen=True)
class StoredArtifact:
    run_id: str
    kind: str
    name: str
    uri: str
    media_type: str
    size_bytes: int
    sha256: str


class FileSystemArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def write_bytes(
        self,
        run_id: str,
        kind: str,
        name: str,
        data: bytes,
        media_type: str,
    ) -> StoredArtifact:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("artifact name must be relative and contained")
        digest = hashlib.sha256(data).hexdigest()
        target = self._root / run_id / kind / digest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredArtifact(
            run_id=run_id,
            kind=kind,
            name=name,
            uri=target.as_uri(),
            media_type=media_type,
            size_bytes=len(data),
            sha256=digest,
        )

    def read_bytes(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError("artifact URI must be a file URI")
        if parsed.netloc not in {"", "localhost"}:
            raise ValueError("artifact URI must refer to a local file")

        path = Path(url2pathname(parsed.path)).resolve()
        path.relative_to(self._root)
        return path.read_bytes()
