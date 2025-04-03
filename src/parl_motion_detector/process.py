from __future__ import annotations

import datetime
import json
from pathlib import Path

import pandas as pd
from mysoc_validator import Transcript
from mysoc_validator.models.transcripts import Chamber
from mysoc_validator.utils.parlparse.downloader import get_latest_for_date
from pydantic import ValidationError
from tqdm import tqdm

from .mapper import MotionMapper, ResultsHolder

data_dir = Path(__file__).parent.parent.parent / "data"


def render_year(
    data_dir: Path,
    year: int | None = None,
    dates_in_year: list[datetime.date] | None = None,
    chamber: Chamber = Chamber.COMMONS,
    fail_day: bool = False,
):
    """
    Render motions for a specify year
    """
    current_date = datetime.datetime.now().date()
    if year is None:
        year = current_date.year
    # all dates in year to date
    if dates_in_year:
        label = "custom"
    if not dates_in_year:
        label = str(year)
        dates_in_year = [
            datetime.date(year, 1, 1) + datetime.timedelta(days=i) for i in range(365)
        ]
    # all dates in year to date
    str_dates_in_year = [x.isoformat() for x in dates_in_year if x <= current_date]

    xml_path = data_dir / "scrapedxml" / chamber

    xml_path.mkdir(parents=True, exist_ok=True)

    fails_on = []

    for debate_date in tqdm(str_dates_in_year, desc=label):
        try:
            transcript_path = get_latest_for_date(
                datetime.date.fromisoformat(debate_date),
                download_path=xml_path,
                chamber=chamber,
            )
        except FileNotFoundError:
            continue
        # fix 2019 error
        txt = transcript_path.read_text()

        if "21&#10;14" in txt:
            txt = txt.replace("21&#10;14", "2114")
            transcript_path.write_text(txt)

        if "S6M-133651.1" in txt:
            txt = txt.replace("S6M-133651.1", "S6M-13365.1")
            transcript_path.write_text(txt)

        if "S6M-013368" in txt:
            txt = txt.replace("S6M-013368", "S6M-13368")
            transcript_path.write_text(txt)

        try:
            transcript = Transcript.from_xml_path(transcript_path)
        except ValidationError:
            print(f"Validation error for date: {debate_date}")
            continue

        mm = MotionMapper(
            transcript, debate_date=debate_date, data_dir=data_dir, chamber=chamber
        )

        try:
            mm.assign()
        except Exception as e:
            if fail_day:
                fails_on.append(debate_date)
                # just print the content of the error
                print(e)
                continue
            raise e
        results = mm.export()
        results.to_data_dir(data_dir / "interim" / "results")

    if fail_day:
        day_fails = len(fails_on)
        if day_fails > 0:
            print(f"Fails on {day_fails} days")
            print(fails_on)

    rh = ResultsHolder.from_data_dir_composite(
        data_dir / "interim" / "results", date=label, chamber=chamber
    )
    rh.export(data_dir / "processed" / "parquet")


def render_policy_days(data_dir: Path, chamber: Chamber = Chamber.COMMONS):
    data = json.loads(Path("data", "raw", "pre_2019_dates.json").read_text())
    dates = [datetime.date.fromisoformat(x) for x in data]
    dates.sort()
    render_year(data_dir, dates_in_year=dates, chamber=chamber, fail_day=True)


def render_historical(data_dir: Path, chamber: Chamber = Chamber.COMMONS):
    """
    Render motions for all historical dates
    """
    if chamber == Chamber.COMMONS:
        start_year = 2019
    elif chamber == Chamber.SCOTLAND:
        start_year = 2021
    else:
        raise ValueError("Chamber not supported")
    current_year = datetime.datetime.now().year
    for year in range(start_year, current_year):
        render_year(data_dir, year=year, chamber=chamber)


def render_latest(data_dir: Path, chamber: Chamber = Chamber.COMMONS):
    """
    Render motions for the latest date
    """
    render_year(data_dir, chamber=chamber)


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
            df = pd.read_parquet(file)
            if len(df) > 1:
                dfs.append(pd.read_parquet(file))

        df = pd.concat(dfs)

        # sort by first column
        df = df.sort_values(by=df.columns[0])

        # remove duplicate rows
        df = df.drop_duplicates()

        # ok, so a reason a duplicate might survive that is where one variant has picked up
        # the 'good' motion_title for scotland and the other is stuck on 'Decision Time'
        # so to deal with this, we want look at all duplicated, check there is at least
        # one non 'Decision Time' and then drop the rest
        # the first col is usually gid not motion_title
        indexes_to_drop = []
        if "motion_title" in df.columns:
            for gid, group_df in df.groupby(df.columns[0]):
                if len(group_df) > 1:
                    unique_titles = group_df["motion_title"].unique()
                    if len(unique_titles) > 1:
                        # check if there is a non 'Decision Time' title
                        if "Decision Time" in unique_titles:
                            # drop the 'Decision Time' title
                            indexes_to_drop.extend(
                                group_df[
                                    group_df["motion_title"] == "Decision Time"
                                ].index.tolist()
                            )

        # drop these indexes
        df = df.drop(indexes_to_drop)

        # check there are no remaining duplicated values in the first column

        if df[df.columns[0]].duplicated().sum() != 0:
            dulicate_vals = df[df.columns[0]][df[df.columns[0]].duplicated()].tolist()

            raise ValueError(
                f"Duplicated values in the first column for {file_ending}: {dulicate_vals}"
            )

        df.to_parquet(package_dir / file_ending)
