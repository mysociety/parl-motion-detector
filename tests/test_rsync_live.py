from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from mysoc_validator import Transcript

from parl_motion_detector.downloader import TranscriptXMl, get_latest_for_date


@pytest.mark.live_rsync
@pytest.mark.parametrize(
    "date",
    [
        "2023-06-27",
        "2022-10-19",
        "2019-06-24",
        "2024-02-21",
        "2024-04-24",
        "2024-04-22",
    ],
)
def test_fresh_transcript_download(date: str, tmp_path: Path) -> None:
    """
    Exercise production discovery, verified transfer and parsing without cache reuse.
    """
    requested = datetime.date.fromisoformat(date)
    cached = TranscriptXMl.UK_COMMONS_DEBATES.construct_path(
        requested, download_path=tmp_path
    )
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"invalid cached transcript")
    downloaded = get_latest_for_date(
        requested, download_path=tmp_path, force_download=True
    )
    assert downloaded.is_relative_to(tmp_path)
    assert downloaded.read_bytes() != b"invalid cached transcript"
    assert Transcript.from_xml_path(downloaded).items
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.live_rsync
def test_non_sitting_date(tmp_path: Path) -> None:
    """
    Let the production year loop distinguish absent transcripts from daemon errors.
    """
    with pytest.raises(FileNotFoundError):
        get_latest_for_date(datetime.date(2026, 1, 1), download_path=tmp_path)
    assert not list(tmp_path.rglob("*.xml"))
