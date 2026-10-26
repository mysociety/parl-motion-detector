from __future__ import annotations

import json
from pathlib import Path

from mysoc_validator import Transcript

from parl_motion_detector.mapper import MotionMapper

debates_path = Path("data")
tests_path = Path("data") / "tests" / "mapper"


def compare_date(debate_date: str, cached_transcripts: Path) -> None:
    paths = list(cached_transcripts.glob(f"debates{debate_date}*.xml"))
    assert len(paths) == 1, f"Expected one pinned transcript for {debate_date}"
    transcript_path = paths[0]
    transcript = Transcript.from_xml_path(transcript_path)

    mm = MotionMapper(transcript, debate_date, Transcript.Chamber.COMMONS, debates_path)
    mm.assign()
    snapshot = mm.snapshot()
    with (tests_path / f"{debate_date}.json").open() as f:
        past_data = json.load(f)
    assert snapshot == past_data


def test_basic_motions(cached_transcripts: Path) -> None:
    # from oppositon day 2023-06-27
    compare_date("2023-06-27", cached_transcripts)


def test_complex_motions(cached_transcripts: Path) -> None:
    # complex timetable change motion
    compare_date("2022-10-19", cached_transcripts)


def test_one_line_bills(cached_transcripts: Path) -> None:
    # one line bills
    compare_date("2019-06-24", cached_transcripts)


def test_sit_in_private(cached_transcripts: Path) -> None:
    # sit in private
    compare_date("2024-02-21", cached_transcripts)


def amendment_to_kings_speech(cached_transcripts: Path) -> None:
    compare_date("2024-07-23", cached_transcripts)


def test_new_clauses(cached_transcripts: Path) -> None:
    compare_date("2024-04-24", cached_transcripts)


def inline_amendments(cached_transcripts: Path) -> None:
    compare_date("2024-03-25", cached_transcripts)


def test_lords_amendments(cached_transcripts: Path) -> None:
    compare_date("2024-04-22", cached_transcripts)


def test_manual_wildcard_matching():
    """Test that manual linking supports wildcard version letters."""
    from parl_motion_detector.mapper import find_manual_connection, gid_matches_pattern

    # Test basic wildcard matching
    assert gid_matches_pattern(
        "uk.org.publicwhip/debate/2025-11-05e.996.4",
        "uk.org.publicwhip/debate/2025-11-05x.996.4",
    )
    assert gid_matches_pattern(
        "uk.org.publicwhip/debate/2025-11-05f.996.4",
        "uk.org.publicwhip/debate/2025-11-05x.996.4",
    )
    assert gid_matches_pattern(
        "uk.org.publicwhip/debate/2025-11-05a.996.4",
        "uk.org.publicwhip/debate/2025-11-05x.996.4",
    )

    # Test that different parts don't match
    assert not gid_matches_pattern(
        "uk.org.publicwhip/debate/2025-11-06e.996.4",
        "uk.org.publicwhip/debate/2025-11-05x.996.4",
    )

    # Test manual connection finding
    manual_lookup = {
        "uk.org.publicwhip/debate/2025-11-05x.953.5.6": "uk.org.publicwhip/debate/2025-11-05x.1000.2"
    }

    # Should find connection with wildcard matching
    result = find_manual_connection(
        "uk.org.publicwhip/debate/2025-11-05e.953.5.6", manual_lookup
    )
    assert result == "uk.org.publicwhip/debate/2025-11-05x.1000.2"

    # Should not find connection for non-matching GID
    result = find_manual_connection(
        "uk.org.publicwhip/debate/2025-11-06e.953.5.6", manual_lookup
    )
    assert result is None
