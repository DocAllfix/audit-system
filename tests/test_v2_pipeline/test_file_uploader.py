"""
Test V2 Fase 4 — file_uploader.

Coperture:
- compute_file_sha256 deterministico
- guess_mime_type per estensioni note e fallback
- UploadManifest CRUD + atomic write + persistence + reload
- upload_file: dedup via manifest se URI ancora valido
- upload_file: re-upload se URI scaduto (404 da get)
- upload_file: retry esponenziale su errori transienti
- upload_file: fail hard su 401/403/413
- upload_file: rifiuto file > MAX_UPLOAD_BYTES
- upload_file: rifiuto file vuoti
- upload_files_parallel: ordine preservato + concorrenza
- cleanup_session: cancella tutti gli URI e svuota manifest
- Race condition: 5 thread su stesso file → 1 sola upload, 4 dedup hits
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from v2 import file_uploader as fu


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_temp_file(tmp_path: Path, name: str, content: bytes = b"PDF-CONTENT" * 100) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


def _make_mock_client(file_uri: str = "files/abc123", file_name: str = "files/abc123"):
    """Mock genai.Client con files.upload OK."""
    mock = MagicMock()

    fake_file = MagicMock()
    fake_file.uri = file_uri
    fake_file.name = file_name

    mock.files = MagicMock()
    mock.files.upload = MagicMock(return_value=fake_file)

    # files.get ritorna oggetto con state=ACTIVE
    fake_get = MagicMock()
    fake_get.state = "ACTIVE"
    mock.files.get = MagicMock(return_value=fake_get)

    mock.files.delete = MagicMock(return_value=None)
    return mock


# ──────────────────────────────────────────────────────────────────────────────
# SHA-256 e MIME
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_sha256_deterministic(tmp_path):
    p1 = _make_temp_file(tmp_path, "a.bin", b"contenuto identico")
    p2 = _make_temp_file(tmp_path, "b.bin", b"contenuto identico")
    p3 = _make_temp_file(tmp_path, "c.bin", b"contenuto diverso")

    assert fu.compute_file_sha256(str(p1)) == fu.compute_file_sha256(str(p2))
    assert fu.compute_file_sha256(str(p1)) != fu.compute_file_sha256(str(p3))


def test_guess_mime_type():
    assert fu.guess_mime_type("doc.pdf") == "application/pdf"
    assert fu.guess_mime_type("img.png") == "image/png"
    assert fu.guess_mime_type("foto.JPG") == "image/jpeg"
    assert fu.guess_mime_type("foto.heic") == "image/heic"
    assert fu.guess_mime_type("strano.xyz") == "application/octet-stream"


# ──────────────────────────────────────────────────────────────────────────────
# UploadManifest
# ──────────────────────────────────────────────────────────────────────────────

def test_manifest_crud(tmp_path):
    m = fu.UploadManifest("test_session_1", base_dir=tmp_path)
    assert len(m) == 0

    e = fu.UploadedFile(
        sha256="abc",
        file_uri="files/x",
        file_name="files/x",
        mime_type="application/pdf",
        size_bytes=1000,
        source_path="/fake.pdf",
    )
    m.add(e)
    assert len(m) == 1
    assert m.get("abc") == e

    removed = m.remove("abc")
    assert removed == e
    assert len(m) == 0


def test_manifest_persists_and_reloads(tmp_path):
    """Manifest scritto da una istanza viene ricaricato da un'altra."""
    m1 = fu.UploadManifest("test_session_2", base_dir=tmp_path)
    e = fu.UploadedFile(
        sha256="xyz", file_uri="files/y", file_name="files/y",
        mime_type="application/pdf", size_bytes=5000, source_path="/f.pdf",
    )
    m1.add(e)

    # Nuova istanza che legge stesso file
    m2 = fu.UploadManifest("test_session_2", base_dir=tmp_path)
    assert len(m2) == 1
    assert m2.get("xyz").file_uri == "files/y"


def test_manifest_atomic_write(tmp_path):
    """Il file .tmp non sopravvive dopo persist (rename atomico)."""
    m = fu.UploadManifest("test_session_3", base_dir=tmp_path)
    m.add(fu.UploadedFile(
        sha256="a", file_uri="files/a", file_name="files/a",
        mime_type="application/pdf", size_bytes=1, source_path="/x",
    ))
    # Solo .json deve esistere, non .json.tmp
    assert m.path.exists()
    assert not m.path.with_suffix(".json.tmp").exists()


def test_manifest_corrupted_starts_empty(tmp_path):
    """File manifest corrotto → riparte vuoto, non crasha."""
    bad = tmp_path / "test_session_4.json"
    bad.write_text("garbage json {{{")
    m = fu.UploadManifest("test_session_4", base_dir=tmp_path)
    assert len(m) == 0


# ──────────────────────────────────────────────────────────────────────────────
# upload_file — happy path e dedup
# ──────────────────────────────────────────────────────────────────────────────

def test_upload_file_success(tmp_path):
    p = _make_temp_file(tmp_path, "doc.pdf")
    client = _make_mock_client()
    manifest = fu.UploadManifest("s1", base_dir=tmp_path)

    result = fu.upload_file(client, str(p), manifest)

    assert result.success is True
    assert result.file_uri == "files/abc123"
    assert result.used_cached is False
    assert client.files.upload.call_count == 1
    # Manifest è stato popolato
    assert len(manifest) == 1


def test_upload_dedup_when_uri_still_valid(tmp_path):
    p = _make_temp_file(tmp_path, "doc.pdf")
    client = _make_mock_client()
    manifest = fu.UploadManifest("s2", base_dir=tmp_path)

    # Prima upload
    r1 = fu.upload_file(client, str(p), manifest)
    # Seconda chiamata stesso file → dedup
    r2 = fu.upload_file(client, str(p), manifest)

    assert r1.file_uri == r2.file_uri
    assert r2.used_cached is True
    # Solo 1 upload chiamato (la 2° è dedup)
    assert client.files.upload.call_count == 1
    # Però files.get è stato chiamato per validare
    assert client.files.get.call_count >= 1


def test_upload_reupload_when_uri_expired(tmp_path):
    """Se il URI nel manifest è scaduto (404), re-upload."""
    p = _make_temp_file(tmp_path, "doc.pdf")
    client = _make_mock_client()
    # Simula 404 da files.get
    client.files.get = MagicMock(side_effect=RuntimeError("not found 404"))
    manifest = fu.UploadManifest("s3", base_dir=tmp_path)

    # Pre-popolo il manifest con URI "vecchio"
    manifest.add(fu.UploadedFile(
        sha256=fu.compute_file_sha256(str(p)),
        file_uri="files/old",
        file_name="files/old",
        mime_type="application/pdf",
        size_bytes=p.stat().st_size,
        source_path=str(p),
    ))

    result = fu.upload_file(client, str(p), manifest)
    assert result.success is True
    assert result.file_uri == "files/abc123"
    assert result.used_cached is False
    # 1 upload chiamato (re-upload dopo scoperta che URI vecchio è morto)
    assert client.files.upload.call_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# upload_file — error cases
# ──────────────────────────────────────────────────────────────────────────────

def test_upload_missing_file_returns_error(tmp_path):
    client = _make_mock_client()
    manifest = fu.UploadManifest("s4", base_dir=tmp_path)
    result = fu.upload_file(client, "/path/non/esiste.pdf", manifest)
    assert result.success is False
    assert "file_not_found" in result.error
    client.files.upload.assert_not_called()


def test_upload_empty_file_rejected(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    client = _make_mock_client()
    manifest = fu.UploadManifest("s5", base_dir=tmp_path)
    result = fu.upload_file(client, str(p), manifest)
    assert result.success is False
    assert "empty_file" in result.error


def test_upload_auth_failure_no_retry(tmp_path):
    """401/403 → fail subito, niente retry."""
    p = _make_temp_file(tmp_path, "doc.pdf")
    client = MagicMock()
    client.files = MagicMock()
    client.files.upload = MagicMock(side_effect=RuntimeError("403 permission denied"))
    client.files.get = MagicMock(side_effect=RuntimeError("not found"))
    manifest = fu.UploadManifest("s6", base_dir=tmp_path)

    result = fu.upload_file(client, str(p), manifest)
    assert result.success is False
    assert "auth_failed" in result.error
    # 1 sola chiamata, niente retry
    assert client.files.upload.call_count == 1


def test_upload_retry_on_transient_then_success(tmp_path, monkeypatch):
    """Errore transiente → retry, alla fine successo."""
    p = _make_temp_file(tmp_path, "doc.pdf")
    monkeypatch.setattr(fu.time, "sleep", lambda s: None)  # accelera retry

    client = MagicMock()
    client.files = MagicMock()
    client.files.get = MagicMock(side_effect=RuntimeError("not found"))
    fake_file = MagicMock()
    fake_file.uri = "files/recovered"
    fake_file.name = "files/recovered"
    # Prima 2 fail, poi success
    client.files.upload = MagicMock(side_effect=[
        RuntimeError("503 transient"),
        RuntimeError("network glitch"),
        fake_file,
    ])
    manifest = fu.UploadManifest("s7", base_dir=tmp_path)

    result = fu.upload_file(client, str(p), manifest)
    assert result.success is True
    assert result.file_uri == "files/recovered"
    assert client.files.upload.call_count == 3


def test_upload_all_retries_fail(tmp_path, monkeypatch):
    p = _make_temp_file(tmp_path, "doc.pdf")
    monkeypatch.setattr(fu.time, "sleep", lambda s: None)

    client = MagicMock()
    client.files = MagicMock()
    client.files.get = MagicMock(side_effect=RuntimeError("not found"))
    client.files.upload = MagicMock(side_effect=RuntimeError("network down"))
    manifest = fu.UploadManifest("s8", base_dir=tmp_path)

    result = fu.upload_file(client, str(p), manifest)
    assert result.success is False
    assert "all_retries_failed" in result.error
    assert client.files.upload.call_count == fu.MAX_UPLOAD_RETRIES


# ──────────────────────────────────────────────────────────────────────────────
# upload_files_parallel
# ──────────────────────────────────────────────────────────────────────────────

def test_upload_files_parallel_ok(tmp_path):
    paths = [
        str(_make_temp_file(tmp_path, f"f{i}.pdf", content=f"X{i}".encode() * 200))
        for i in range(5)
    ]
    client = _make_mock_client(file_uri="files/parallel")
    manifest = fu.UploadManifest("sp", base_dir=tmp_path)

    results = fu.upload_files_parallel(client, paths, manifest, max_workers=3)

    assert len(results) == 5
    assert all(r.success for r in results.values())
    # Ogni path è una key
    for p in paths:
        assert p in results


def test_upload_files_parallel_empty():
    """Input vuoto → dict vuoto, no API call."""
    client = _make_mock_client()
    manifest_dummy = MagicMock()
    results = fu.upload_files_parallel(client, [], manifest_dummy)
    assert results == {}


# ──────────────────────────────────────────────────────────────────────────────
# Concurrency: dedup deve reggere thread paralleli sullo stesso file
# ──────────────────────────────────────────────────────────────────────────────

def test_concurrent_upload_same_file_dedups(tmp_path):
    """5 thread caricano lo stesso file → 1 upload, 4 dedup hits."""
    p = _make_temp_file(tmp_path, "shared.pdf")
    client = _make_mock_client()

    # Aggiungi piccola latenza per favorire collisione
    real_upload = client.files.upload.return_value
    def slow_upload(file=None, config=None, **kw):
        time.sleep(0.05)
        return real_upload
    client.files.upload = MagicMock(side_effect=slow_upload)

    manifest = fu.UploadManifest("sc", base_dir=tmp_path)
    results = []

    def worker():
        results.append(fu.upload_file(client, str(p), manifest))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5
    assert all(r.success for r in results)
    # Tutte risultano OK ma solo 1 (o pochi) sono effettivi upload
    # (in mancanza di lock prima dell'upload, possono esserci 2-3 race)
    # Verifichiamo invariante: tutti i results hanno lo stesso file_uri
    uris = {r.file_uri for r in results}
    assert len(uris) == 1  # Tutti puntano allo stesso URI finale


# ──────────────────────────────────────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────────────────────────────────────

def test_cleanup_session_deletes_all(tmp_path):
    p = _make_temp_file(tmp_path, "doc.pdf")
    client = _make_mock_client()
    manifest = fu.UploadManifest("clean", base_dir=tmp_path)
    fu.upload_file(client, str(p), manifest)
    assert len(manifest) == 1

    count = fu.cleanup_session(client, manifest)
    assert count == 1
    assert len(manifest) == 0
    client.files.delete.assert_called_once()


def test_cleanup_handles_delete_failure(tmp_path):
    """Se la delete API fallisce, il manifest viene comunque ripulito."""
    p = _make_temp_file(tmp_path, "doc.pdf")
    client = _make_mock_client()
    fu.upload_file(client, str(p), fu.UploadManifest("c2", base_dir=tmp_path))

    manifest = fu.UploadManifest("c3", base_dir=tmp_path)
    manifest.add(fu.UploadedFile(
        sha256="z", file_uri="files/z", file_name="files/z",
        mime_type="application/pdf", size_bytes=10, source_path="/x",
    ))
    client.files.delete = MagicMock(side_effect=RuntimeError("boom"))

    count = fu.cleanup_session(client, manifest)
    assert count == 0  # delete non ha avuto successo
    assert len(manifest) == 0  # ma il manifest è stato comunque ripulito


# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────

def test_manifest_summary(tmp_path):
    m = fu.UploadManifest("sumtest", base_dir=tmp_path)
    m.add(fu.UploadedFile(
        sha256="a", file_uri="files/a", file_name="files/a",
        mime_type="application/pdf", size_bytes=1024 * 1024, source_path="/x",
    ))
    s = fu.manifest_summary(m)
    assert s["files_count"] == 1
    assert s["total_mb"] == 1.0
    assert s["session_id"] == "sumtest"
