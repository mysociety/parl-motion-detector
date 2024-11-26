from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, TypeVar

import pandas as pd
from bs4 import BeautifulSoup
from mysoc_validator import Transcript
from pydantic import BaseModel, Field, computed_field

from parl_motion_detector.detector import PhraseDetector, StartsWith, Stringifiable
from parl_motion_detector.enum_helpers import StrEnum
from parl_motion_detector.motion_title_extraction import extract_motion_title

from .sp_motions import SPMotionManager

sp_motion_pattern = re.compile(r"\b[A-Z0-9]{2}M-[0-9]{5}\.?[0-9]?\b")


@lru_cache
def get_sp_manager() -> SPMotionManager:
    return SPMotionManager()


def extract_sp_motions(text: str) -> list[str]:
    """
    returns the longest amendment
    """
    matches = sp_motion_pattern.findall(text)
    return [x for x in matches if not any(y in x for y in matches if x != y)]


def html_to_markdown(html_table: str) -> str | None:
    # Parse the HTML table
    soup = BeautifulSoup(html_table, "html.parser")
    table = soup.find("tbody")

    # Extract table rows
    rows = []
    for tr in table.find_all("tr"):  # type: ignore
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        rows.append(cells)
    try:
        headers = rows[0]
        rows = rows[1:]
        df = pd.DataFrame(rows, columns=headers)
        markdown_table = df.to_markdown(index=False)
    except Exception:
        return None
    return markdown_table


T = TypeVar("T")

contentless_lines = [
    "Question put forthwith (Standing Order No. 163).",
    "The House proceeded to a Division.",
]


class Flag(StrEnum):
    """
    Store Flags for different kinds of motion processe
    """

    COMPLEX_MOTION = "complex_motion"
    CLAUSE_MOTION = "clause_motion"
    ASKED_IMMEDIATELY = "asked_immediately"
    INLINE_AMENDMENT = "inline_amendment"
    ONE_LINE_MOTION = "one_line_motion"
    AFTER_DECISION = "after_decision"
    ABSTRACT_MOTION = "abstract_motion"  # use for when the question is entirely about 'the question' without actual content
    MAIN_QUESTION = "main_question"
    MOTION_AMENDMENT = "motion_amendment"
    SCOTTISH_EXPANDED_MOTION = "scottish_expanded_motion"


class Motion(BaseModel):
    date: str
    motion_title: str = ""
    major_heading_id: str = ""
    minor_heading_id: str = ""
    major_heading_title: str = ""
    minor_heading_title: str = ""
    speech_start_pid: str = ""
    speech_id: str
    final_speech_id: str = ""
    end_reason: str = ""
    motion_lines: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    def flat(self) -> dict[str, str]:
        return {
            "gid": self.gid,
            "speech_id": self.speech_id,
            "date": self.date,
            "motion_title": self.motion_title,
            "motion_text": "\n".join(self.motion_lines),
        }

    @classmethod
    def merge(cls, motions: list[Motion]) -> Motion:
        if len(motions) == 0:
            raise ValueError("No motions to merge")
        if len(motions) == 1:
            return motions[0]
        first = motions[0]
        for motion in motions[1:]:
            first.motion_lines.extend(motion.motion_lines)
            first.flags.extend(motion.flags)
        return first

    @computed_field
    @property
    def gid(self) -> str:
        if self.speech_start_pid:
            paragraph = self.speech_start_pid.split("/")[-1]
            return self.speech_id + "." + paragraph
        return self.speech_id

    def contentless(self) -> bool:
        motion_lines = [
            line for line in self.motion_lines if line not in contentless_lines
        ]
        return len(motion_lines) == 0

    def add_title(self):
        if not self.motion_title:
            self.motion_title = extract_motion_title(self)
        return self

    def has_flag(self, flag: Flag) -> bool:
        return flag in self.flags

    def add_flag(self, flag: Flag):
        if flag not in self.flags:
            self.flags.append(flag)

    def __add__(self, other: Flag):
        self.add_flag(other)
        return self

    def add(self, item: Stringifiable, new_final_id: str = ""):
        if not new_final_id and hasattr(item, "id"):
            new_final_id = item.id  # type: ignore

        if new_final_id:
            self.final_speech_id = new_final_id

        if hasattr(item, "tag") and getattr(item, "tag") == "table":
            str_item = html_to_markdown(item.content.raw)  # type: ignore
            if str_item is None:
                str_item = str(item)
        else:
            str_item = str(item)

        str_item = str_item.replace("\xa0", " ")

        self.motion_lines.append(str_item)

    def self_flag(self):
        """
        Any extra tags to add based on the final content
        """
        content = str(self).lower()
        if len(self.motion_lines) < 3:
            if abstract_motion(content):
                self.add_flag(Flag.ABSTRACT_MOTION)

        if amendment_flag(content):
            self.add_flag(Flag.MOTION_AMENDMENT)
        elif main_question(content):
            self.add_flag(Flag.MAIN_QUESTION)

    def finish(self, collection: MotionCollection, end_reason: str):
        self.end_reason = end_reason
        self.add_title()
        self.self_flag()
        collection.motions.append(self)
        return None

    def __len__(self):
        return len(self.motion_lines)

    def __str__(self):
        return "\n".join(self.motion_lines)


class MotionCollection(BaseModel):
    motions: list[Motion] = []

    def __len__(self):
        return len(self.motions)

    def prune(self):
        self.motions = [m for m in self.motions if not m.contentless()]

    def __iter__(self):
        return iter(self.motions)

    def basic_dict(self):
        return {
            m.gid: {"title": m.motion_title, "content": str(m)} for m in self.motions
        }

    def dump_test_data(self, tests_data_path: Path):
        debate_date = self.motions[0].date
        with (tests_data_path / f"{debate_date}.json").open("w") as f:
            json.dump(self.basic_dict(), f, indent=2)


# Abstract motions are motions usually triggered by standing orders
# that are about management of the original question and amendments
# and will often not in themeselves have detectable content
abstract_motion = PhraseDetector(
    criteria=[
        "That the proposed words be there added",
        "That the original words stand part of the Question",
        "Question put forthwith (Standing Order No. 33), That the amendment be made.",
    ]
)

# for adding a flag after bringing the contents together
amendment_flag = PhraseDetector(
    criteria=[
        "I beg to move an amendment",
        "I beg to move amendment",
        "Amendment proposed: at the end of the Question",
        re.compile(
            r"The question is, that amendment \d+ be agreed to\. Are we(?: all)? agreed\?",
            re.IGNORECASE,
        ),
    ]
)

# for adding a flag after bringing the contents together
main_question = PhraseDetector(
    criteria=[
        "I beg to move",
        "That the clause stand part of the Bill.",
        "Question again proposed,",
    ]
)

# This is phrases that should cause us to crash out of a motion
end_motion = PhraseDetector(criteria=["I rise to continue the debate"])

# These are phrases that appear when a motion text is
# *after* the decision, saying what was ordered.
resolved_start = PhraseDetector(
    criteria=[
        re.compile(r"^Resolved,", re.IGNORECASE),
        re.compile(r"^Ordered,", re.IGNORECASE),
        re.compile(r"^Motion agreed to,", re.IGNORECASE),
        re.compile(r"^Motion, as amended,", re.IGNORECASE),
        re.compile(r"^Motion, as amended, agreed to,", re.IGNORECASE),
    ]
)

# this deals with an edge case where someone forgot to
# beg to move
malformed_motion_start = PhraseDetector(
    criteria=[
        re.compile(r"^That the draft", re.IGNORECASE),
    ]
)

motion_amendment_jump_in = PhraseDetector(
    criteria=[
        re.compile(r"^[‘“]\(1\)", re.IGNORECASE),
    ]
)

# when several are happening in sequence - need to split
motion_start_sequence = PhraseDetector(
    criteria=[re.compile(r"^That this House", re.IGNORECASE)]
)

# These kick the detector into action - basically a set of phrases that indicate a motion is starting
motion_start = PhraseDetector(
    criteria=[
        "I beg to move",
        "I beg move to move",
        "I therefore beg to move,",
        "Amendment proposed: at the end of the Question to add:",
        "Amendment proposed : at the end of the Question to add:",
        "Motion made, and Question put",
        "The Deputy Speaker put forthwith",
        re.compile(r"^To leave out from “That”", re.IGNORECASE),
        # catching a minority of approaches where this is the preamble - but *not* where it is the closure to the actual text
        re.compile(r"^Question put,$", re.IGNORECASE),
        re.compile(
            r"^Question put, That this House disagrees with Lords amendment",
            re.IGNORECASE,
        ),
        re.compile(
            r"^Question put, That this House agrees with Lords amendment",
            re.IGNORECASE,
        ),
        re.compile(r"^Amendment \([a-zA-Z]+\) proposed", re.IGNORECASE),
        re.compile(
            r"^Amendments \([a-zA-Z]+\) and \([a-zA-Z]+\) proposed", re.IGNORECASE
        ),
        re.compile(
            r"^Amendments \([a-zA-Z]+\) to \([a-zA-Z]+\) proposed", re.IGNORECASE
        ),
        re.compile(
            r"Question, That new clause \d+ be added to the Bill.", re.IGNORECASE
        ),
        "Question put accordingly",
        "Question again proposed",
        "Question put forthwith",
        "Question put, That the clause stand part of the Bill",
        "Question proposed",
        "Question put (Standing Order No. 31(2))",
        "That this House authorises",
        "Motion made, and Question proposed",
        "Motion made, Question put forthwith",
        "Motion made , and Question proposed",
        "Motion made and Question proposed",
        "Motion made and Question put forthwith",
        "Motion made, and Question put forthwith",
        re.compile(r"^Motion \([A-Z]\)", re.IGNORECASE),
        StartsWith(
            "If, on the day before the end of the penultimate House of Commons sitting"
        ),
        re.compile(
            r"^That an humble Address be presented to (His|Her) Majesty", re.IGNORECASE
        ),
        # including variants here to avoid false positives - but an option in future
        re.compile(r"^That this House at its rising", re.IGNORECASE),
        re.compile(r"^That this House, at its rising", re.IGNORECASE),
        re.compile(r"^That this House—", re.IGNORECASE),
        re.compile(r"^That this House insists", re.IGNORECASE),
        re.compile(r"^That this House agrees", re.IGNORECASE),
        re.compile(r"^That this House directs", re.IGNORECASE),
        re.compile(r"^That this House recognises", re.IGNORECASE),
        re.compile(r"^That this House instructs", re.IGNORECASE),
        re.compile(r"^That this House requires", re.IGNORECASE),
        re.compile(r"^That this House will not allow", re.IGNORECASE),
        re.compile(r"^That this House takes note", re.IGNORECASE),
        re.compile(r"^Resolved,", re.IGNORECASE),
        re.compile(r"^Ordered,", re.IGNORECASE),
        re.compile(r"^Motion agreed to,", re.IGNORECASE),
        re.compile(r"^Motion, as amended,", re.IGNORECASE),
        re.compile(r"^Motion, as amended, agreed to,", re.IGNORECASE),
        re.compile(
            r"amendment proposed: \(.+?\), at the end of the Question to add:",
            re.IGNORECASE,
        ),
        re.compile(r"amended proposed: \(.+?\)", re.IGNORECASE),
        re.compile(r"^Amendment proposed: \(.+?\)", re.IGNORECASE),
        re.compile(r"^That the .+ be approved", re.IGNORECASE),
        re.compile(r"Question put, That amendment \(.+?\) be made.", re.IGNORECASE),
        re.compile(r"Amendment proposed to new clause \d+: \(.+?\),", re.IGNORECASE),
        re.compile(
            r"^Amendments made:\s*\d+,\s*page\s*\d+,\s*line\s*\d+", re.IGNORECASE
        ),
        re.compile(
            r"^Amendment\s*\d+\s*,\s*page\s*\d+\s*,\s*line\s*\d+\s*", re.IGNORECASE
        ),
        re.compile(
            r"The question is, that amendment \d+ be agreed to\. Are we(?: all)? agreed\?",
            re.IGNORECASE,
        ),
    ]
)


# these are criteria that say the motion is wrapped up in a single line (and will stop looking)
one_line_motion = PhraseDetector(
    criteria=[
        "Main Question again proposed.",
        "Question put forthwith, That the Question be now put",
        "Motion made, That the Bill be now read a Secondtime.",
        "Question put forthwith (Standing Order No. 33), That the amendment be made.",
        "Motion made, That the Bill be read be now read a Second time.",
        "Question put, That the Bill be read a Second time.",
        "Question put, That the clause be a Second time.",
        "Question put, That the clause stand part of the Bill",
        "That the Bill be now read a second time",
        "That the Bill be now read a third time.",
        "That the Bill be read the Third time.",
        "That the Bill now be read a third time.",
        "That the Bill will be now read a second time.",
        "That the House sit in private.",
        "That the clause be read a Second time.",
        "the Bill be now read a Second time.",
        "the Bill be now read the Third time.",
        "That the original words stand part of the Question",
        "That this House authorises",
        "That this House do now adjourn.",
        re.compile(
            r"Question, That new clause \d+ be added to the Bill.", re.IGNORECASE
        ),
        re.compile(r"^That this House at its rising", re.IGNORECASE),
        re.compile(r"^That this House, at its rising", re.IGNORECASE),
        re.compile(
            r"^Amendment ([a-zA-Z]+) proposed in lieu of Lords amendment \d+",
            re.IGNORECASE,
        ),
        re.compile(
            r"^Amendments? \((?:[a-zA-Z]+(?: and )?)+\) proposed in lieu of Lords amendments? \d+(?:, \d+)*(?: and \d+)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"^Amendments? \((?:[a-zA-Z]+(?: and )?)+\) proposed in lieu of Lords amendments? \d+[A-Z]?(?:, \d+[A-Z]?)*(?: and \d+[A-Z]?)?",
            re.IGNORECASE,
        ),
        re.compile(
            r"^Amendments \([a-zA-Z]+\) to \([a-zA-Z]+\) proposed in lieu of Lords amendment \d+[A-Z]?",
            re.IGNORECASE,
        ),
        re.compile(r"^That the draft .+ be approved", re.IGNORECASE),
        re.compile(r"^That the .+ be approved", re.IGNORECASE),
        re.compile(
            r"^That an humble Address be presented to (His|Her) Majesty.*?be annulled\.$",
            re.IGNORECASE,
        ),
        re.compile(
            r"The question is, that amendment \d+ be agreed to\. Are we(?: all)? agreed\?",
            re.IGNORECASE,
        ),
    ]
)

# remember that regular expression and other criteria are applied to lower cased versions of the text.
# Criteria are automatically adjusted - but if you're using a regular expression, you need to make sure it's case insensitive

# This immediately follows a motion saying the question is about to be asked.
asked_immediately = PhraseDetector(criteria=["Question put forthwith"])

# This picks up when we're in a rapid fire amendment mood
discussion_mode = PhraseDetector(criteria=["discuss the following:"])

# catches (1) (10) (a) (i) (iii) (1zb) etc
is_subitem = PhraseDetector(
    criteria=[re.compile(r"^\((\d+[a-zA-Z]*|[a-z]+|\d*)\)", re.IGNORECASE)]
)

# end on a full stop or a quote
valid_ender_character = PhraseDetector(criteria=[re.compile(r'[.\”"]$', re.IGNORECASE)])

# continutation character - ends on comma or semicolon or some kind of dash
ends_in_continuation_character = PhraseDetector(criteria=[re.compile(r"[,;-–—‑]$")])

# end on number or letter (more expansive than the reverse of valid ender)
end_on_alphanumeric = PhraseDetector(criteria=[re.compile(r"[a-zA-Z0-9]+$")])

# this is picking up when something is being inserted into something else
# it opens and closes with quotes - ambigious about if ends in a dot or not
is_inserted = PhraseDetector(criteria=[re.compile(r"^\“(.+)\”\.*$")])

# starts with new clause
new_clause = PhraseDetector(criteria=[re.compile(r"^new clause\b.")])

# amendment close  e.g. '—(Jacob C. Young.)'
signature_close = PhraseDetector(criteria=[re.compile(r"—\([A-Za-z\.\s]+\.\)$")])

# used to pick up the start of amendments when they're all being grouped together in a debate on new legislation
in_line_amendment = PhraseDetector(
    criteria=[
        re.compile(r"^new clause \d+—"),
        re.compile(r"^amendment \d+,"),
        re.compile(r"^amendment proposed\: \d+"),
        re.compile(r"^amendment made\: \d+"),
    ]
)

# after an inline amendment there is a little explainer bubble - we're excluding this for consistuency
amendment_explainer = PhraseDetector(
    criteria=[
        StartsWith("This Amendment"),
        StartsWith("This probing Amendment"),
        StartsWith("This amendment would ensure"),
    ],
)

not_sp_motion_ref = PhraseDetector(
    criteria=[
        "To ask the Scottish Government",
        "To ask the First Minister when",
        "as amended",
        re.compile(r"\([A-Z0-9]{3}-[0-9]{5}\.?[0-9]?\)$", re.IGNORECASE),
    ]
)

# disagree with lords amendment
disagree_with_lords_amendment = PhraseDetector(
    criteria=[re.compile(r"disagrees with lords amendment [a-zA-Z0-9]+\.?$")]
)


class HereTest:
    def __init__(self, criteria: str):
        self.criteria = criteria.lower()

    def __call__(self, paragraph: Stringifiable, message: Stringifiable = "here"):
        if self.criteria and self.criteria in str(paragraph).lower():
            print(message)


# For tracing specific text through the system.
debug_test = HereTest("")
debug_mode = debug_test.criteria != ""


def get_motions(transcript: Transcript, date_str: str) -> MotionCollection:
    collection = MotionCollection()

    # iterate through the transcript
    # this returns a tuple of the major heading, minor heading speech, and speech index within a sub heading
    current_motion = None
    previous_speech = None
    transcript_groups = list(transcript.iter_headed_speeches())
    for transcript_index, transcript_group in enumerate(transcript_groups):

        def new_motion(speech_start_pid: Optional[str] = None):
            if speech_start_pid is None:
                speech_start_pid = ""
            return Motion(
                speech_start_pid=speech_start_pid,
                speech_id=transcript_group.speech.id,
                minor_heading_id=minor_heading_id,
                minor_heading_title=str(transcript_group.minor_heading),
                major_heading_title=str(transcript_group.major_heading),
                major_heading_id=major_heading_id,
                date=date_str,
            )

        minor_heading_id = (
            transcript_group.minor_heading.id if transcript_group.minor_heading else ""
        )
        major_heading_id = (
            transcript_group.major_heading.id if transcript_group.major_heading else ""
        )

        # speech is discussion is when we're grouping amendments for discussion, and a load are listed at once
        # most of these are not voted on - but lets capture them
        speech_is_discussion_mode = False

        # for formatting errors where part of a clause is being taken as the header
        add_minor_heading_to_motion = False

        if current_motion and previous_speech:
            if (
                previous_speech.person_id != transcript_group.speech.person_id
                and transcript_group.speech.person_id
            ):
                current_motion = current_motion.finish(collection, "new speaker")

        # iterate through paragraphs within a speech.
        # There is an assumption here that all of a relevant motion is *within* a speech
        # I think this holds

        for index, paragraph in enumerate(transcript_group.speech.items):
            if debug_mode and current_motion:
                print(index, current_motion)
            # Try and capture the next item, as some processing steps help to know about it
            try:
                next_item = transcript_group.speech.items[index + 1]
            except IndexError:
                try:
                    next_transcript_group = transcript_groups[transcript_index + 1]
                    next_item = next_transcript_group.speech.items[0]
                except IndexError:
                    next_item = None

            sp_motions = extract_sp_motions(str(paragraph))

            if sp_motions:
                if current_motion:
                    raise ValueError(
                        f"Multiple motions found in {paragraph} - {sp_motions}"
                    )
                if len(sp_motions) == 1 and not not_sp_motion_ref(paragraph):
                    # try and avoid creating sp motions we'll pick up normally
                    # as amended motions are usually described in full after
                    current_motion = new_motion(paragraph.pid or f"subitem/{index}")
                    current_motion.add(paragraph)
                    try:
                        actual_content = get_sp_manager().get_motion(sp_motions[0])
                        current_motion.add(actual_content.item_text)
                        current_motion.add_flag(Flag.SCOTTISH_EXPANDED_MOTION)
                        current_motion = current_motion.finish(collection, "sp_motion")
                    except KeyError as e:
                        print(f"Error: {e}, junking expanded motion")
                        current_motion = None

            if discussion_mode(paragraph):
                speech_is_discussion_mode = True

            if in_line_amendment(paragraph):
                speech_is_discussion_mode = True

            if add_minor_heading_to_motion:
                if current_motion:
                    current_motion.add(transcript_group.minor_heading)
                add_minor_heading_to_motion = False

            # if at the start of a new subquestion, we might be looking at a new clause
            # here we need to look at the text of the subheading
            if index == 0 and transcript_group.speech_index == 0:
                # start of a new subquestion

                if new_clause(transcript_group.minor_heading):
                    if current_motion:
                        current_motion = current_motion.finish(
                            collection, "new clause clean up"
                        )
                    current_motion = new_motion(paragraph.pid)
                    current_motion.add(transcript_group.minor_heading)
                    current_motion += Flag.CLAUSE_MOTION
                    current_motion += Flag.COMPLEX_MOTION

            if current_motion and motion_start_sequence(paragraph):
                # trigger word for new motion, need to finish the old one
                if "that this house" in str(current_motion).lower():
                    current_motion = current_motion.finish(collection, "new motion")

            # Here we're looking for ordinary phrases that herald the start of a motion
            # beg to move etc
            if current_motion is None and (
                motion_start(paragraph) or malformed_motion_start(paragraph)
            ):
                debug_test(paragraph, "motion start")
                current_motion = new_motion(paragraph.pid)
                if resolved_start(paragraph):
                    current_motion += Flag.AFTER_DECISION

            if current_motion is None:
                # similarly if there's the shortform amendment (and) the amendment close language in the same line
                if in_line_amendment(paragraph) and signature_close(paragraph):
                    current_motion = new_motion(paragraph.pid)
                    current_motion.add(
                        paragraph, new_final_id=transcript_group.speech.id
                    )
                    current_motion = current_motion.finish(
                        collection, "one line inline amendment close"
                    )
                    continue

            if current_motion is None:
                # this is picking up when motions are being restated before a vote
                # there's less preamble - but it's easier to make connections
                if (
                    transcript_group.speech.person_id is None
                    and motion_amendment_jump_in(paragraph)
                ):
                    current_motion = new_motion(paragraph.pid)
                    current_motion.add(
                        paragraph, new_final_id=transcript_group.speech.id
                    )
                    current_motion.add_flag(Flag.COMPLEX_MOTION)
                    continue

            # if doing lots of clauses and amendments in sequence
            if speech_is_discussion_mode:
                debug_test(paragraph, "speech is discussion")
                # if start of new one
                if in_line_amendment(paragraph):
                    # assume end of one one if exists
                    if current_motion:
                        # store the one in progress if hitting a new one
                        current_motion = current_motion.finish(
                            collection, "in line amendment"
                        )
                    # start new one
                    current_motion = new_motion(paragraph.pid)
                    current_motion += Flag.INLINE_AMENDMENT
                if amendment_explainer(paragraph):
                    # if the amendment is being explained - we're done
                    # some case for including this - but for consistency because
                    # we don't always get it
                    if current_motion:
                        current_motion = current_motion.finish(
                            collection, "amendment explainer"
                        )
                        continue

            # here's our main motion processing once a motion has been started
            if current_motion is not None:
                debug_test(paragraph, "main processing")

                if end_motion(paragraph):
                    current_motion = current_motion.finish(collection, "end motion")
                    continue

                # always add the first one
                if len(current_motion) == 0:
                    debug_test(paragraph, "first line")
                    current_motion.add(
                        paragraph, new_final_id=transcript_group.speech.id
                    )
                    debug_test(paragraph, current_motion)

                    # if we're seeing a one line motion - we're done
                    if (
                        one_line_motion(paragraph)
                        or disagree_with_lords_amendment(paragraph)
                        or signature_close(paragraph)
                    ):
                        debug_test(paragraph, "one line")
                        current_motion += Flag.ONE_LINE_MOTION
                        current_motion = current_motion.finish(
                            collection, "one line motion"
                        )
                        continue
                elif len(current_motion) > 0:
                    # lines after the first line

                    # sometimes the question is effectively immediately asked
                    if asked_immediately(paragraph):
                        debug_test(paragraph, "asked immediately")
                        # stash this infomration for iteration later
                        current_motion += Flag.ASKED_IMMEDIATELY
                        current_motion = current_motion.finish(
                            collection, "asked immediately"
                        )
                        continue

                    # here's where we add the current line to the motion
                    # before this are checks that reveal the current line is *not*
                    # part of the motion
                    current_motion.add(
                        paragraph, new_final_id=transcript_group.speech.id
                    )
                    debug_test(paragraph, "info added")
                    # if we're starting to see an itemised list - that means we're dealing with a more complex motion
                    # that's doing something to legislation or standing orders
                    # trigger advance processing modes
                    if is_subitem(paragraph) or ends_in_continuation_character(
                        paragraph
                    ):
                        debug_test(paragraph, "complex motion")
                        current_motion += Flag.COMPLEX_MOTION

                    # end of amendments have a distinctive bit where it is
                    # closed with the name in brackets of the person who said it
                    if signature_close(paragraph):
                        current_motion = current_motion.finish(
                            collection, "amendment closed with name"
                        )
                        continue

                    if current_motion.has_flag(Flag.COMPLEX_MOTION) is False:
                        # Normally a hint we're done for simple motions
                        #  motions will finish on a full stop of closed quote
                        if valid_ender_character(paragraph):
                            current_motion = current_motion.finish(
                                collection, "Valid end character"
                            )
                    else:
                        # ok this is fiddly. This is picking up more complex motions - and we need to peakahead at the next item.
                        # to see if we're already on the final one.
                        # here the next line after a line that is a subpoint might be the title of the next section rather than the end.
                        # if so, the hint is that it ends in a normal letter or number - good sign it's a title rather than a stop
                        # so we're looking for the next item to be a non subpoint and have something other than a 'letter' at the end
                        # however - if the next line is being inserted into something else, this throws our rules - so we exclude dashes
                        # and other continuation characters likedebug_mode
                        debug_test(paragraph, "complex motion handling")
                        if (
                            next_item
                            and not is_subitem(next_item)
                            and not end_on_alphanumeric(next_item)
                            and not is_inserted(next_item)
                            and not ends_in_continuation_character(paragraph)
                            and not signature_close(next_item)
                            and next_item.tag not in ["table"]
                        ) or (signature_close(paragraph)):
                            debug_test(paragraph, "complex motion end")
                            current_motion = current_motion.finish(
                                collection,
                                "next is not subitem, ends in non alphanumeric, not inserted; current does not end  continuation character",
                            )
                        elif next_item is None:
                            if ends_in_continuation_character(paragraph):
                                # ok, this is annoying one where part of a motion is being taken *as* the header
                                # hence how we've got to the end of the speech, there's nothing left - and yet we continue.
                                # so what we have to do here is add the next_minor_heading as part of the motion and let the process contine
                                # but we don't know what this is yet!
                                # so we just set a flag
                                add_minor_heading_to_motion = True
                            else:
                                current_motion = current_motion.finish(
                                    collection, "next is none"
                                )
        previous_speech = transcript_group.speech
    collection.prune()
    return collection
