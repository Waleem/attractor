from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


def _validate_artifact_segment(label: str, value: str) -> None:
    path = Path(value)
    if (
        value in {"", "."}
        or path.is_absolute()
        or ".." in path.parts
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} must be a single relative path segment")


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
        _validate_artifact_segment("artifact run_id", run_id)
        _validate_artifact_segment("artifact kind", kind)
        _validate_artifact_segment("artifact name", name)
        digest = hashlib.sha256(data).hexdigest()
        target = self._root / run_id / kind / digest / name
        target = target.resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("artifact path must be contained by artifact root") from exc
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
