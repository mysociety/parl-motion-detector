from __future__ import annotations

import datetime
import stat
from pathlib import Path

import pytest

from parl_motion_detector.downloader import TranscriptXMl, XMLManager
from parl_motion_detector.rsync import RemoteEntry, RsyncDaemonClient, RsyncError


@pytest.mark.parametrize("manager", list(TranscriptXMl.options()))
def test_latest_revision_is_selected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, manager: XMLManager
) -> None:
    """
    Discover only the requested date and preserve each chamber's naming scheme.
    """
    date = datetime.date(2024, 4, 22)
    prefix = f"{manager.file_structure_pre_date}{date}"

    def list_files(self: RsyncDaemonClient, path: str) -> list[RemoteEntry]:
        assert path == f"{manager.relative_path}{prefix}*.xml"
        return [
            RemoteEntry(f"{prefix}b.xml", 4, 1, stat.S_IFREG),
            RemoteEntry(f"{prefix}a.xml", 4, 1, stat.S_IFREG),
            RemoteEntry(f"{prefix}z.xml", 4, 1, stat.S_IFREG),
            RemoteEntry(f"{prefix}j.xml", 0, 1, stat.S_IFDIR),
            RemoteEntry("../escape.xml", 4, 1, stat.S_IFREG),
        ]

    def fetch(self: RsyncDaemonClient, remote: str, dest: Path) -> RemoteEntry:
        assert remote == f"{manager.relative_path}{prefix}b.xml"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"<xml")
        return RemoteEntry(dest.name, 4, 1, stat.S_IFREG)

    monkeypatch.setattr(RsyncDaemonClient, "list", list_files)
    monkeypatch.setattr(RsyncDaemonClient, "fetch", fetch)
    result = manager.download_for_date(date, tmp_path)
    assert result == tmp_path / manager.relative_path / f"{prefix}b.xml"
    assert result.read_bytes() == b"<xml"


def test_missing_date_and_server_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Missing transcripts and daemon failures remain distinct.
    """
    manager = TranscriptXMl.UK_COMMONS_DEBATES
    monkeypatch.setattr(RsyncDaemonClient, "list", lambda self, path: [])
    with pytest.raises(FileNotFoundError, match="No files found"):
        manager.download_for_date(datetime.date(1900, 1, 1), tmp_path)

    def fail(self: RsyncDaemonClient, path: str) -> list[RemoteEntry]:
        raise RsyncError("permission denied")

    monkeypatch.setattr(RsyncDaemonClient, "list", fail)
    with pytest.raises(RsyncError, match="permission denied"):
        manager.download_for_date(datetime.date(2024, 4, 22), tmp_path)
    assert not list(tmp_path.rglob("*.xml"))


def test_cache_and_forced_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Cached transcripts avoid networking unless a refresh is requested.
    """
    manager = TranscriptXMl.UK_COMMONS_DEBATES
    date = datetime.date(2024, 4, 22)
    cached = manager.construct_path(date, "b", tmp_path)
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached")
    calls: list[datetime.date] = []

    def download(self: XMLManager, date: datetime.date, download_path: Path) -> Path:
        calls.append(date)
        return cached

    monkeypatch.setattr(type(manager), "download_for_date", download)
    assert manager.get_latest_for_date(date, tmp_path) == cached
    assert calls == []
    assert manager.get_latest_for_date(date, tmp_path, force_download=True) == cached
    assert calls == [date]


def test_scottish_meeting_identifiers_are_downloaded_and_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Scottish filenames include a meeting ID rather than a revision letter.
    """
    manager = TranscriptXMl.SCOTTISH_PARLIAMENT_DEBATES
    date = datetime.date(2024, 4, 23)
    entry = RemoteEntry("2024-04-23_15813.xml", 4, 1, stat.S_IFREG)
    monkeypatch.setattr(RsyncDaemonClient, "list", lambda self, path: [entry])

    def fetch(self: RsyncDaemonClient, remote: str, dest: Path) -> RemoteEntry:
        assert remote == manager.relative_path + entry.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"<xml")
        return entry

    monkeypatch.setattr(RsyncDaemonClient, "fetch", fetch)
    result = manager.get_latest_for_date(date, tmp_path)
    assert result.name == entry.name
    monkeypatch.setattr(
        RsyncDaemonClient, "list", lambda self, path: pytest.fail("cache missed")
    )
    assert manager.get_latest_for_date(date, tmp_path) == result
    assert not manager.is_transcript_for_date("2024-04-23_15813.xml/../escape", date)
