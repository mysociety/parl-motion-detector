from __future__ import annotations

import datetime
import re
import tempfile
from pathlib import Path
from typing import ClassVar, Optional

from mysoc_validator.models.popolo import Chamber
from pydantic import BaseModel

from .enum_helpers import MiniEnum, StrEnum
from .rsync import RsyncDaemonClient

RSYNC_HOST = "data.theyworkforyou.com"
RSYNC_MODULE = "parldata"


def persistent_download_path() -> Path:
    return Path(tempfile.gettempdir()) / "parl_motion_detector"


class TranscriptType(StrEnum):
    DEBATES = "debates"
    WRITTEN_QUESTIONS = "written_questions"
    WRITTEN_STATEMENTS = "written_statements"


class XMLManager(BaseModel):
    letter_options: ClassVar[list[str]] = [
        "",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
    ]
    label: str
    relative_path: str
    file_structure_pre_date: str
    transcript_type: TranscriptType
    chamber_type: Chamber

    def construct_path(
        self,
        date: datetime.date,
        letter: str = "",
        download_path: Optional[Path] = None,
    ) -> Path:
        if not download_path:
            download_path = persistent_download_path()
        download_path.mkdir(parents=True, exist_ok=True)
        file_name = f"{self.file_structure_pre_date}{date.isoformat()}{letter}.xml"
        return download_path / self.relative_path / file_name

    def is_transcript_for_date(self, name: str, date: datetime.date) -> bool:
        """
        Match revision letters and Scottish Parliament meeting identifiers.
        """
        prefix = f"{self.file_structure_pre_date}{date.isoformat()}"
        if name in {f"{prefix}{letter}.xml" for letter in self.letter_options}:
            return True
        return (
            self.chamber_type == Chamber.SCOTLAND
            and re.fullmatch(rf"{re.escape(prefix)}_[0-9]+\.xml", name) is not None
        )

    def download_for_date(
        self, date: datetime.date, download_path: Optional[Path] = None
    ) -> Path:
        """
        Discover the latest revision and download it from the rsync daemon.
        """
        client = RsyncDaemonClient(RSYNC_HOST, RSYNC_MODULE)
        prefix = f"{self.file_structure_pre_date}{date.isoformat()}"
        candidates = client.list(f"{self.relative_path}{prefix}*.xml")
        available = [
            entry
            for entry in candidates
            if entry.is_file and self.is_transcript_for_date(entry.name, date)
        ]
        if not available:
            raise FileNotFoundError(f"No files found for {date}")
        latest = max(available, key=lambda entry: entry.name)
        base_path = self.construct_path(date, download_path=download_path)
        file_path = base_path.parent / latest.name
        client.fetch(f"{self.relative_path}{latest.name}", file_path)
        return file_path

    def get_latest_for_date(
        self,
        date: datetime.date,
        download_path: Optional[Path] = None,
        *,
        force_download: bool = False,
    ) -> Path:
        base_path = self.construct_path(date, download_path=download_path)
        prefix = f"{self.file_structure_pre_date}{date.isoformat()}"
        existing = [
            path
            for path in base_path.parent.glob(f"{prefix}*.xml")
            if path.is_file() and self.is_transcript_for_date(path.name, date)
        ]
        if existing and not force_download:
            # sort and return the latest
            existing.sort()
            return existing[-1]
        else:
            return self.download_for_date(date, download_path=download_path)


class TranscriptXMl(MiniEnum[XMLManager]):
    UK_COMMONS_DEBATES = XMLManager(
        label="uk_commons_debates",
        relative_path="scrapedxml/debates/",
        file_structure_pre_date="debates",
        transcript_type=TranscriptType.DEBATES,
        chamber_type=Chamber.COMMONS,
    )
    UK_LORDS_DEBATES = XMLManager(
        label="uk_lords_debates",
        relative_path="scrapedxml/lordspages/",
        file_structure_pre_date="daylord",
        transcript_type=TranscriptType.DEBATES,
        chamber_type=Chamber.COMMONS,
    )
    SCOTTISH_PARLIAMENT_DEBATES = XMLManager(
        label="scottish_parliament_debates",
        relative_path="scrapedxml/sp-new/meeting-of-the-parliament/",
        file_structure_pre_date="",
        transcript_type=TranscriptType.DEBATES,
        chamber_type=Chamber.SCOTLAND,
    )
    WELSH_SENEDD_DEBATES = XMLManager(
        label="welsh_senedd_debates",
        relative_path="scrapedxml/senedd/en/",
        file_structure_pre_date="senedd",
        transcript_type=TranscriptType.DEBATES,
        chamber_type=Chamber.SENEDD,
    )
    NI_ASSEMBLY_DEBATES = XMLManager(
        label="ni_assembly_debates",
        relative_path="scrapedxml/ni/",
        file_structure_pre_date="ni",
        transcript_type=TranscriptType.DEBATES,
        chamber_type=Chamber.NORTHERN_IRELAND,
    )

    @classmethod
    def get_transcript_manager(
        cls,
        chamber: Chamber,
        transcript: TranscriptType,
    ) -> XMLManager:
        for option in cls.options():
            if option.chamber_type == chamber and option.transcript_type == transcript:
                return option
        raise ValueError(
            f"No option found for chamber {chamber} and transcript {transcript}"
        )


def get_latest_for_date(
    date: datetime.date,
    *,
    chamber: Chamber = Chamber.COMMONS,
    transcript_type: TranscriptType = TranscriptType.DEBATES,
    download_path: Optional[Path] = None,
    force_download: bool = False,
) -> Path:
    transcript_manager = TranscriptXMl.get_transcript_manager(
        chamber=chamber, transcript=transcript_type
    )
    return transcript_manager.get_latest_for_date(
        date, download_path, force_download=force_download
    )
