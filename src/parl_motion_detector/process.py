from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
from mysoc_validator import Transcript
from mysoc_validator.models.transcripts import Chamber
from tqdm import tqdm

from parl_motion_detector.downloader import get_latest_for_date

from .mapper import MotionMapper, ResultsHolder

data_dir = Path(__file__).parent.parent.parent / "data"


def render_year(
    data_dir: Path, year: int | None = None, chamber: Chamber = Chamber.COMMONS
):
    """
    Render motions for a specify year
    """
    current_date = datetime.datetime.now().date()
    if year is None:
        year = current_date.year
    # all dates in year to date
    dates_in_year = [
        datetime.date(year, 1, 1) + datetime.timedelta(days=i) for i in range(365)
    ]
    # all dates in year to date
    dates_in_year = [x.isoformat() for x in dates_in_year if x <= current_date]

    for debate_date in tqdm(dates_in_year, desc=str(year)):
        try:
            transcript_path = get_latest_for_date(
                datetime.date.fromisoformat(debate_date), download_path=data_dir
            )
        except FileNotFoundError:
            continue
        # fix 2019 error
        txt = transcript_path.read_text()
        if "21&#10;14" in txt:
            txt = txt.replace("21&#10;14", "2114")
            transcript_path.write_text(txt)
        transcript = Transcript.from_xml_path(transcript_path)

        mm = MotionMapper(
            transcript, debate_date=debate_date, data_dir=data_dir, chamber=chamber
        )

        mm.assign()
        results = mm.export()
        results.to_data_dir(data_dir / "interim" / "results")

    rh = ResultsHolder.from_data_dir_composite(
        data_dir / "interim" / "results", date=str(year), chamber=chamber
    )
    rh.export(data_dir / "processed" / "parquet")


def render_historical(data_dir: Path):
    """
    Render motions for all historical dates
    """
    current_year = datetime.datetime.now().year
    for year in range(2019, current_year):
        render_year(data_dir, year=year, chamber=Chamber.COMMONS)


def render_latest(data_dir: Path):
    """
    Render motions for the latest date
    """
    render_year(data_dir)


def delete_current_year_parquets(data_dir: Path):
    parquet_dir = data_dir / "processed" / "parquet"
    current_year = datetime.datetime.now().year
    current_year_str = f"-{current_year}-"
    for file in parquet_dir.glob(f"*{current_year_str}*"):
        file.unlink()


def move_to_package(data_dir: Path = data_dir):
    """
    Move all processed data to the package
    """
    package_dir = data_dir / "packages" / "parliamentary_motions"
    parquet_dir = data_dir / "processed" / "parquet"

    file_endings = ["agreements.parquet", "motions.parquet", "division-links.parquet"]

    for file_ending in file_endings:
        dfs = []
        for file in parquet_dir.glob(f"*-{file_ending}"):
            dfs.append(pd.read_parquet(file))

        df = pd.concat(dfs)
        # sort by first column
        df = df.sort_values(by=df.columns[0])

        # remove duplicate rows
        df = df.drop_duplicates()

        # check there are no duplicated values in the first column

        if df[df.columns[0]].duplicated().sum() != 0:
            raise ValueError("Duplicated values in the first column")

        df.to_parquet(package_dir / file_ending)
