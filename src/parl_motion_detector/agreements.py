from __future__ import annotations

import json
import re
from pathlib import Path
from typing import (
    Generic,
    Optional,
    Protocol,
    TypeVar,
)

from mysoc_validator import Transcript
from mysoc_validator.models.transcripts import (
    Chamber,
    Division,
    MajorHeading,
    MinorHeading,
    Speech,
)
from pydantic import BaseModel, computed_field

from .detector import PhraseDetector
from .enum_helpers import StrEnum
from .motions import Motion


class Stringable(Protocol):
    def __str__(self) -> str: ...


class HasSpeechAndDate(BaseModel):
    date: str
    speech_id: str


T = TypeVar("T", bound=HasSpeechAndDate)


class Flag(StrEnum):
    """
    Store Flags for different kinds of motion processe
    """

    COMPLEX_MOTION = "complex_motion"
    CLAUSE_MOTION = "clause_motion"
    ASKED_IMMEDIATELY = "asked_immediately"


construct_reading_pass = PhraseDetector(
    criteria=[
        "read the Third time",
        "read a third time",
        "read the Second time",
        "read a Second time",
        "read the First time",
        "read a First time",
    ]
)


class Agreement(HasSpeechAndDate):
    date: str
    major_heading_id: str
    minor_heading_id: str
    major_heading_title: str = ""
    speech_id: str
    chamber: Chamber
    paragraph_pid: str = ""
    end_reason: str = ""
    agreement_pid: str = ""
    agreed_text: str
    preceeding_text: str
    after_text: str
    motion: Optional[Motion] = None
    motion_assignment_reason: str = ""

    @computed_field
    @property
    def negative(self) -> bool:
        if "negatived" in self.agreed_text.lower():
            return True
        return False

    def flat(self):
        return {
            "gid": self.gid,
            "date": self.date,
            "major_heading_id": self.major_heading_id,
            "minor_heading_id": self.minor_heading_id,
            "speech_id": self.speech_id,
            "paragraph_pid": self.paragraph_pid,
            "agreed_text": self.agreed_text,
            "negative": self.negative,
            "motion_title": self.motion.motion_title if self.motion else "",
            "motion_gid": self.motion.gid if self.motion else "",
        }

    @property
    def preceeding(self):
        return self.preceeding_text

    @property
    def after(self):
        return self.after_text

    def motion_speech_id(self):
        if self.motion:
            return self.motion.gid
        else:
            return ""

    def construct_motion(self, use_agreed_only: bool = False):
        if use_agreed_only:
            motion_lines = [self.agreed_text]
        else:
            if construct_reading_pass(self.after_text.lower()):
                motion_lines = [self.agreed_text, self.after_text]
            else:
                motion_lines = [self.preceeding_text, self.agreed_text]

        motion = Motion(
            date=self.date,
            chamber=self.chamber,
            major_heading_id=self.major_heading_id,
            minor_heading_id=self.minor_heading_id,
            major_heading_title=self.major_heading_title,
            speech_id=self.speech_id,
            speech_start_pid=self.paragraph_pid,
            motion_lines=motion_lines,
        )
        motion.add_title()
        motion.self_flag()
        return motion

    @computed_field
    @property
    def gid(self) -> str:
        paragraph = self.paragraph_pid.split("/")[-1]
        return self.speech_id + "." + paragraph

    def finish(self, collection: AgreementCollection, end_reason: str):
        self.end_reason = end_reason
        collection.motions.append(self)
        return None

    @property
    def relevant_text(self):
        return self.agreed_text


class DivisionHolder(HasSpeechAndDate):
    date: str
    major_heading_id: str
    minor_heading_id: str
    minor_heading_text: str
    chamber: Chamber
    speech_id: str  # actually the division id for these purposes
    paragraph_pid: str = ""
    preceding_speech: str
    after_speech: str
    motion: Optional[Motion] = None
    motion_assignment_reason: str = ""

    @property
    def preceeding(self):
        return self.preceding_speech

    @property
    def after(self):
        return self.after_speech

    def motion_speech_id(self):
        if self.motion:
            return self.motion.gid
        else:
            return ""

    def construct_motion(self, use_agreed_only: bool = False):
        """
        Sometimes (like for clauses) there isn't actually a perfect motion to hold onto
        We're just going to cheat and make one.
        use_agreed_only - does nothing but compatible with agreement vesion.
        """
        motion = Motion(
            date=self.date,
            chamber=self.chamber,
            major_heading_id=self.major_heading_id,
            minor_heading_id=self.minor_heading_id,
            speech_id=self.speech_id,
            speech_start_pid="",
            motion_lines=[self.minor_heading_text, self.preceding_speech],
        )
        motion.add_title()
        motion.self_flag()
        return motion

    @computed_field
    @property
    def gid(self) -> str:
        return self.speech_id

    @property
    def relevant_text(self):
        return self.preceding_speech

    def finish(self, collection: DivisionCollection, end_reason: str):
        self.end_reason = end_reason
        collection.motions.append(self)
        return None


class Collection(BaseModel, Generic[T]):
    motions: list[T] = []

    def __iter__(self):
        return iter(self.motions)

    def basic_dict(self):
        return {m.speech_id: str(m) for m in self.motions}

    def dump_test_data(self, tests_data_path: Path):
        debate_date = self.motions[0].date
        with (tests_data_path / f"{debate_date}.json").open("w") as f:
            json.dump(self.basic_dict(), f)

    def __len__(self):
        return len(self.motions)


AgreementCollection = Collection[Agreement]
DivisionCollection = Collection[DivisionHolder]

agreement_made = PhraseDetector(
    criteria=[
        "Question put and agreed to.",
        "Question agreed to.",
        "read the First and Second time, and added to the Bill.",
        "question put and agreed to",
        "main question accordingly put and agreed to",
        "question put and agreed",
        "question agreed to",
        "Question put and agree d to",
        "Main Question put accordingly and agreed to",
        "Question put (Standing Order No. 23) and agreed to",
        "Main Question, as amended, put and agreed to",
        "Main Question, as amended, put forthwith and agreed to",
        "Question put forthwith (Standing Order No. 163) and negatived",
        "Question agreed to.",
        "read the First and Second time, and added to the Bill.",
        "Brought up, read the First and Second time, and added to the Bill",
        "Brought up, read the First Time and Second Time and added to the Bill",
        "Question put and agreed to.",
        "Question put (Standing Order No.23) and agreed to.",
        "question put and agreed to",
        "Motion agreed to,",
    ]
)
motion_amendment_agreed = PhraseDetector(
    criteria=[
        re.compile(r"^Amendment.{1,5}?agreed to", re.IGNORECASE),
        re.compile(
            r"Amendments? \d+( and \d+)* moved—\[.*?\]—and agreed to\.", re.IGNORECASE
        ),
    ]
)

amended_agreement = PhraseDetector(
    criteria=[
        "Main Question, as amended, put and agreed to",
        "Main Question, as amended, put forthwith and agreed to",
        "The Deputy Speaker declared the main Question, as amended, to be agreed to (Standing Order No. 31(2)).",
    ]
)

not_agreement_based_on_previous = PhraseDetector(
    criteria=[
        re.compile(r"^The result of the division on amendment", re.IGNORECASE),
        re.compile(r"^The result of the division is", re.IGNORECASE),
        re.compile(r"^The result of the division on", re.IGNORECASE),
    ]
)


def get_divisions(
    chamber: Chamber, transcript: Transcript, date_str: str
) -> DivisionCollection:
    previous = None
    major_heading = None
    minor_heading = None
    collection = DivisionCollection()
    for index, item in enumerate(transcript.items):
        if isinstance(item, MajorHeading):
            major_heading = item
            minor_heading = None
        if isinstance(item, MinorHeading):
            minor_heading = item
        if isinstance(item, Division):
            if isinstance(previous, Speech):
                previous_speech = str(previous.items[-1])
            else:
                previous_speech = ""
            try:
                next_item = transcript.items[index + 1]
                if isinstance(next_item, Speech):
                    next_speech = str(next_item.items[0])
                else:
                    next_speech = str(next_item)
            except IndexError:
                next_speech = ""
            current_division = DivisionHolder(
                date=date_str,
                chamber=chamber,
                major_heading_id=major_heading.id if major_heading else "",
                minor_heading_id=minor_heading.id if minor_heading else "",
                minor_heading_text=str(minor_heading) if minor_heading else "",
                speech_id=item.id,
                preceding_speech=previous_speech,
                after_speech=next_speech,
            )
            collection.motions.append(current_division)

        previous = item

    return collection


def get_agreements(
    chamber: Chamber, transcript: Transcript, date_str: str
) -> AgreementCollection:
    collection = AgreementCollection()

    for transcript_group in transcript.iter_headed_speeches():
        minor_heading_id = (
            transcript_group.minor_heading.id if transcript_group.minor_heading else ""
        )
        major_heading_id = (
            transcript_group.major_heading.id if transcript_group.major_heading else ""
        )

        major_heading_text = (
            str(transcript_group.major_heading)
            if transcript_group.major_heading
            else ""
        )

        for index, paragraph in enumerate(transcript_group.speech.items):
            try:
                previous_paragraph = str(transcript_group.speech.items[index - 1])
            except IndexError:
                previous_paragraph = ""
            try:
                next_paragraph = str(transcript_group.speech.items[index + 1])
            except IndexError:
                next_paragraph = ""

            end_reason = None
            if agreement_made(paragraph):
                end_reason = "one_line_agreement"
            if motion_amendment_agreed(paragraph):
                end_reason = "amendment_agreed"
            if amended_agreement(paragraph):
                end_reason = "amended_motion_agreed"

            if end_reason and not_agreement_based_on_previous(previous_paragraph):
                # this is catching divisions in the scottish govenrment which restate what happened
                end_reason = None

            if end_reason:
                current_agreement = Agreement(
                    chamber=chamber,
                    date=date_str,
                    major_heading_id=major_heading_id,
                    minor_heading_id=minor_heading_id,
                    major_heading_title=major_heading_text,
                    speech_id=transcript_group.speech.id,
                    paragraph_pid=paragraph.pid or f"para/{index}",
                    agreed_text=str(paragraph),
                    preceeding_text=previous_paragraph,
                    after_text=next_paragraph,
                )
                current_agreement = current_agreement.finish(collection, end_reason)

    return collection
