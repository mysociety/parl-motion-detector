from __future__ import annotations

import datetime
import shutil
import stat
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from lxml.etree import XMLSyntaxError

from parl_motion_detector import process
from parl_motion_detector.rsync import (
    RemoteEntry,
    RsyncDaemonClient,
    RsyncMissingPathError,
)


def test_render_year_uses_rsync_and_skips_missing_dates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cached_transcripts: Path
) -> None:
    """
    Exercise production processing through the local downloader rather than HTTP.
    """
    (tmp_path / "raw").mkdir()
    shutil.copyfile(
        Path("data/raw/manual_motion_linking.json"),
        tmp_path / "raw/manual_motion_linking.json",
    )
    source = next(cached_transcripts.glob("debates2023-06-27*.xml"))
    entry = RemoteEntry(source.name, source.stat().st_size, 1234, stat.S_IFREG)
    requests: list[str] = []

    def list_files(self: RsyncDaemonClient, path: str) -> list[RemoteEntry]:
        """
        Return the pinned sitting day and a daemon-style missing-day error.
        """
        requests.append(path)
        if "2023-06-25" in path:
            raise RsyncMissingPathError("No such file or directory (2)")
        return [entry]

    def fetch(self: RsyncDaemonClient, path: str, destination: Path) -> RemoteEntry:
        """
        Supply the actual XML fixture to the parser and motion mapper.
        """
        requests.append(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return entry

    def unexpected_http(*args: object, **kwargs: object) -> NoReturn:
        """
        Fail immediately if production wiring switches back to the HTTP downloader.
        """
        pytest.fail("Processing must use the local rsync downloader")

    monkeypatch.setattr(RsyncDaemonClient, "list", list_files)
    monkeypatch.setattr(RsyncDaemonClient, "fetch", fetch)
    monkeypatch.setattr(httpx, "get", unexpected_http)
    monkeypatch.setattr(httpx.AsyncClient, "head", unexpected_http)
    process.render_year(
        tmp_path,
        dates_in_year=[datetime.date(2023, 6, 25), datetime.date(2023, 6, 27)],
    )
    assert requests == [
        "scrapedxml/debates/debates2023-06-25*.xml",
        "scrapedxml/debates/debates2023-06-27*.xml",
        f"scrapedxml/debates/{entry.name}",
    ]
    result = tmp_path / "interim/results/house-of-commons-2023-06-27.json"
    assert result.is_file()
    assert '"date": "2023-06-27"' in result.read_text()


def test_invalid_xml_reports_date_and_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Identify the actual transcript if malformed source or cached XML is encountered.
    """
    transcript = tmp_path / "bad.xml"
    transcript.write_text("<html><head><link></head></html>")
    monkeypatch.setattr(
        process, "get_latest_for_date", lambda *args, **kwargs: transcript
    )
    with pytest.raises(XMLSyntaxError) as failure:
        process.render_year(tmp_path, dates_in_year=[datetime.date(2026, 1, 12)])
    assert any(
        "2026-01-12" in note and str(transcript) in note
        for note in failure.value.__notes__
    )
