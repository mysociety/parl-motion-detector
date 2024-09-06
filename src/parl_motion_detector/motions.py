from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, TypeVar

from mysoc_validator import Transcript
from pydantic import BaseModel, Field

from parl_motion_detector.detector import PhraseDetector, StartsWith, Stringifiable
from parl_motion_detector.enum_helpers import StrEnum
from parl_motion_detector.motion_title_extraction import extract_motion_title

T = TypeVar("T")


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


class Motion(BaseModel):
    date: str
    motion_title: str = ""
    major_heading_id: str
    minor_heading_id: str
    major_heading_title: str = ""
    minor_heading_title: str = ""
    speech_start_pid: str
    speech_id: str
    end_reason: str = ""
    motion_lines: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)

    def add_title(self):
        if not self.motion_title:
            self.motion_title = extract_motion_title(self)

    def has_flag(self, flag: Flag) -> bool:
        return flag in self.flags

    def add_flag(self, flag: Flag):
        if flag not in self.flags:
            self.flags.append(flag)

    def __add__(self, other: Flag):
        self.add_flag(other)
        return self

    def add(self, item: Stringifiable):
        self.motion_lines.append(str(item))

    def finish(self, collection: MotionCollection, end_reason: str):
        self.end_reason = end_reason
        self.add_title()
        collection.motions.append(self)
        return None

    def __len__(self):
        return len(self.motion_lines)

    def __str__(self):
        return "\n".join(self.motion_lines)


class MotionCollection(BaseModel):
    motions: list[Motion] = []

    def basic_dict(self):
        return {
            m.speech_id: {"title": m.motion_title, "content": str(m)}
            for m in self.motions
        }

    def dump_test_data(self, tests_data_path: Path):
        debate_date = self.motions[0].date
        with (tests_data_path / f"{debate_date}.json").open("w") as f:
            json.dump(self.basic_dict(), f, indent=2)


resolved_start = PhraseDetector(
    criteria=[
        re.compile(r"^Resolved,", re.IGNORECASE),
    ]
)

motion_start = PhraseDetector(
    criteria=[
        "I beg to move",
        "I beg move to move",
        "I therefore beg to move,",
        "Amendment proposed: at the end of the Question to add:",
        "Amendment proposed : at the end of the Question to add:",
        "Motion made, and Question put",
        "Question again proposed",
        "Motion made, and Question proposed",
        "Motion made, Question put forthwith",
        "Motion made , and Question proposed",
        "Motion made and Question proposed",
        "Motion made and Question put forthwith",
        "Motion made, and Question put forthwith",
        re.compile(r"^Resolved,", re.IGNORECASE),
        re.compile(r"amendment proposed: \(.+?\), at the end of the Question to add:"),
        re.compile(r"amended proposed: \(.+?\)"),
        re.compile(r"Amendment proposed to new clause \d+: \(.+?\),"),
    ]
)


one_line_motion = PhraseDetector(
    criteria=[
        "Main Question again proposed.",
        "Motion made, That the Bill be now read a Secondtime.",
        "Motion made, That the Bill be read be now read a Second time.",
        "Question put, That the Bill be read a Second time.",
        "Question put, That the clause be a Second time.",
        "That the Bill be now read a second time",
        "That the Bill be now read a third time.",
        "That the Bill be read the Third time.",
        "That the Bill now be read a third time.",
        "That the Bill will be now read a second time.",
        "That the House sit in private.",
        "That the clause be read a Second time.",
        "the Bill be now read a Second time.",
        "the Bill be now read the Third time.",
    ]
)

# remember that regular expression and other criteria are applied to lower cased versions of the text.
# Criteria are automatically adjusted - but if you're using a regular expression, you need to make sure it's case insensitive

# This immediately follows a motion saying the question is about to be asked -
asked_immediately = PhraseDetector(criteria=["Question put forthwith"])

# This picks up when we're in a rapid fire amendment mood
discussion_mode = PhraseDetector(criteria=["discuss the following:"])

# catches (1) (10) (a) (i) (iii) (1zb) etc
is_subitem = PhraseDetector(criteria=[re.compile(r"^\((\d+[a-zA-Z]*|[a-z]+|\d*)\)")])

# end on a full stop or a quote
valid_ender_character = PhraseDetector(criteria=[re.compile(r'[.\”"]$')])

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
    ]
)

# after an inline amendment there is a little explainer bubble - we're excluding this for consistuency
amendment_explainer = PhraseDetector(
    criteria=[StartsWith("This Amendment"), StartsWith("This probing Amendment")]
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
    for transcript_group in transcript.iter_headed_speeches():

        def new_motion(speech_start_pid: Optional[str]):
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
                next_item = None

            if discussion_mode(paragraph):
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

            # Here we're looking for ordinary phrases that herald the start of a motion
            # beg to move etc
            if current_motion is None and motion_start(paragraph):
                debug_test(paragraph, "motion start")
                current_motion = new_motion(paragraph.pid)
                if resolved_start(paragraph):
                    current_motion += Flag.AFTER_DECISION

            if current_motion is None:
                # similarly if there's the shortform amendment (and) the amendment close language in the same line
                if in_line_amendment(paragraph) and signature_close(paragraph):
                    current_motion = new_motion(paragraph.pid)
                    current_motion.add(paragraph)
                    current_motion = current_motion.finish(
                        collection, "one line inline amendment close"
                    )
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
                # always add the first one
                if len(current_motion) == 0:
                    debug_test(paragraph, "first line")
                    current_motion.add(paragraph)
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
                    current_motion.add(paragraph)
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

    return collection
