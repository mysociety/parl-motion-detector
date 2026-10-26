from __future__ import annotations

import json
from pathlib import Path

from mysoc_validator import Transcript
from mysoc_validator.models.transcripts import Chamber

from parl_motion_detector.motions import get_motions

debates_path = Path("data")
tests_path = Path("data") / "tests" / "motions"


def compare_date(debate_date: str, cached_transcripts: Path) -> None:
    chamber = Chamber.COMMONS
    paths = list(cached_transcripts.glob(f"debates{debate_date}*.xml"))
    assert len(paths) == 1, f"Expected one pinned transcript for {debate_date}"
    transcript_path = paths[0]
    transcript = Transcript.from_xml_path(transcript_path)
    current_data = get_motions(chamber, transcript, debate_date).basic_dict()
    with (tests_path / f"{debate_date}.json").open() as f:
        past_data = json.load(f)
    assert current_data == past_data


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
