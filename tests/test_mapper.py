import datetime
import json
from pathlib import Path

from mysoc_validator import Transcript

from parl_motion_detector.downloader import get_latest_for_date
from parl_motion_detector.mapper import MotionMapper

debates_path = Path("data")
tests_path = Path("data") / "tests" / "mapper"


def compare_date(debate_date: str):
    transcript_path = get_latest_for_date(
        datetime.date.fromisoformat(debate_date), download_path=debates_path
    )
    transcript = Transcript.from_xml_path(transcript_path)

    mm = MotionMapper(transcript, debate_date, debates_path)
    mm.assign()
    snapshot = mm.snapshot()
    with (tests_path / f"{debate_date}.json").open() as f:
        past_data = json.load(f)
    assert snapshot == past_data


def test_basic_motions():
    # from oppositon day 2023-06-27
    compare_date("2023-06-27")


def test_complex_motions():
    # complex timetable change motion
    compare_date("2022-10-19")


def test_one_line_bills():
    # one line bills
    compare_date("2019-06-24")


def test_sit_in_private():
    # sit in private
    compare_date("2024-02-21")


def amendment_to_kings_speech():
    compare_date("2024-07-23")


def test_new_clauses():
    compare_date("2024-04-24")


def inline_amendments():
    compare_date("2024-03-25")


def test_lords_amendments():
    compare_date("2024-04-22")
