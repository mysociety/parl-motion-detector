from __future__ import annotations

import datetime
from pathlib import Path

from mysoc_validator import Transcript

from .downloader import get_latest_for_date
from .mapper import MotionMapper
from .motions import get_motions

debates_path = Path("data")
tests_path = Path("data", "tests")

anchor_dates = [
    "2023-06-27",
    "2022-10-19",
    "2019-06-24",
    "2024-02-21",
    "2024-07-23",
    "2024-04-24",
    "2024-03-25",
    "2024-04-22",
]


def generate_motion_snapshot(date: str):
    transcript_path = get_latest_for_date(
        datetime.date.fromisoformat(date), download_path=debates_path
    )
    transcript = Transcript.from_xml_path(transcript_path)
    found_motions = get_motions(transcript, date)
    found_motions.dump_test_data(tests_path / "motions")


def generate_mapper_snapshot(date: str):
    transcript_path = get_latest_for_date(
        datetime.date.fromisoformat(date), download_path=debates_path
    )
    transcript = Transcript.from_xml_path(transcript_path)
    mapper = MotionMapper(transcript, date, debates_path)
    mapper.assign()
    mapper.dump_test_data(tests_path / "mapper")


def generate_all_snapshots():
    for date in anchor_dates:
        generate_motion_snapshot(date)
        generate_mapper_snapshot(date)
