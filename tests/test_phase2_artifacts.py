from __future__ import annotations

import pytest

from attractor_platform.artifacts import FileSystemArtifactStore


def test_filesystem_artifact_store_writes_content_addressed_file(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    record = store.write_bytes(
        run_id="run_1",
        kind="log",
        name="stdout.txt",
        data=b"hello",
        media_type="text/plain",
    )

    assert record.run_id == "run_1"
    assert record.kind == "log"
    assert record.name == "stdout.txt"
    assert record.size_bytes == 5
    assert len(record.sha256) == 64
    assert record.uri.startswith("file://")
    assert store.read_bytes(record.uri) == b"hello"


def test_filesystem_artifact_store_reads_escaped_file_uri(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    record = store.write_bytes(
        run_id="run_1",
        kind="log",
        name="file with space.txt",
        data=b"hello",
        media_type="text/plain",
    )

    assert "%20" in record.uri
    assert store.read_bytes(record.uri) == b"hello"


def test_filesystem_artifact_store_rejects_non_file_uri(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="file URI"):
        store.read_bytes("https://example.com/artifact.txt")


def test_artifact_store_rejects_path_escape_names(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact name"):
        store.write_bytes("run_1", "log", "../secret.txt", b"x", "text/plain")


def test_artifact_store_rejects_path_escape_run_ids(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact run_id"):
        store.write_bytes("..", "log", "stdout.txt", b"x", "text/plain")


def test_artifact_store_rejects_path_escape_kinds(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="artifact kind"):
        store.write_bytes("run_1", "../log", "stdout.txt", b"x", "text/plain")
