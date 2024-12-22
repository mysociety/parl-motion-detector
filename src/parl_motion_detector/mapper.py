from __future__ import annotations

import json
import re
from functools import lru_cache
from itertools import chain, groupby
from pathlib import Path
from typing import TypeVar

import pandas as pd
import rich
from mysoc_validator import Transcript
from mysoc_validator.models.transcripts import Chamber
from pydantic import BaseModel, Field, TypeAdapter

from parl_motion_detector.detector import PhraseDetector

from .agreements import (
    Agreement,
    DivisionHolder,
    get_agreements,
    get_divisions,
)
from .motions import Flag, Motion, get_motions
from .sp_motions import SPMotionManager

T = TypeVar("T")

DEBUG: bool = False

sp_motion_pattern = re.compile(r"\b[A-Z0-9]{3}-[0-9]{5}\.?[0-9]?\b")


def extract_sp_motions(text: str) -> list[str]:
    matches = sp_motion_pattern.findall(text)
    return [x for x in matches if not any(y in x for y in matches if x != y)]


@lru_cache
def get_sp_manager() -> SPMotionManager:
    return SPMotionManager()


class ManualLink(BaseModel):
    decision_gid: str
    motion_gid: str


class ManualText(BaseModel):
    decision_gid: str
    motion: Motion


ManualInfo = ManualLink | ManualText


@lru_cache
def get_manual_connections(data_dir: Path) -> dict[str, str]:
    data = Path(data_dir, "raw", "manual_motion_linking.json").read_text()
    items = TypeAdapter(list[ManualLink | ManualText]).validate_json(data)
    return {x.motion_gid: x.decision_gid for x in items if isinstance(x, ManualLink)}


@lru_cache
def get_manual_text(data_dir: Path) -> dict[str, Motion]:
    data = Path(data_dir, "raw", "manual_motion_linking.json").read_text()
    items = TypeAdapter(list[ManualLink | ManualText]).validate_json(data)
    return {x.decision_gid: x.motion for x in items if isinstance(x, ManualText)}


amendment_be_made = PhraseDetector(criteria=["That the amendment be made."])

amendment_check = re.compile(r"Amendment \([A-Za-z0-9]+\)", re.IGNORECASE)

lords_amendment_check = re.compile(r"Lords Amendment [A-Za-z0-9]+", re.IGNORECASE)


main_question_put = PhraseDetector(
    criteria=["question put and agreed to", "That the amendment be made."]
)

lords_amendment_agreement = PhraseDetector(
    criteria=[
        re.compile(r"lords amendment \d+ agreed to", re.IGNORECASE),
        re.compile(r"amendment \(a\) in lieu of Lords", re.IGNORECASE),
    ]
)

# These are phrases that indicate in the worst case - we can just extract a motion from
# information the decision itself has
can_be_self_motion = PhraseDetector(
    criteria=[
        "Question put, That the clause stand part of the Bill.",
        "Question put (single Question on successive provisions of the Bill)",
        "Bill accordingly read a Second time",
        "That the clause be read a Second time",
        "Question put, That the Bill be now read the Third time",
        "accordingly read the Third time and passed",
        "this House agrees with Lords amendment",
        "this House disagrees with Lords amendment",
        re.compile(r"clause \d+ accordingly read a Second time", re.IGNORECASE),
        re.compile(r"^That the draft .+ be approved", re.IGNORECASE),
        re.compile(r"^That the .+ be approved.$", re.IGNORECASE),
        re.compile(r"amendment \(\w+\) to Lords amendment \d+ be made", re.IGNORECASE),
        re.compile(r"^Amendment.*?agreed to", re.IGNORECASE),
        re.compile(
            r"Amendments? \d+( and \d+)* moved—\[.*?\]—and agreed to\.", re.IGNORECASE
        ),
    ]
)


preamble = ["Motion made, and Question put,", "Resolved,"]

similar_phrases = {"additional amendment": "amendment"}


def clean_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if "—(" in t:
        t = t.split("—(")[0]
    for p in preamble:
        t = t.replace(p, "")
    t = t.strip().lower()
    for k, v in similar_phrases.items():
        t = t.replace(k, v)
    return t


def extract_amendment(text: str) -> str | None:
    # Regular expression to match "Amendment (a)" where 'a' can be any letter or number
    match = amendment_check.search(text)
    result = match.group(0) if match else None
    if not result:
        return None

    if "lords amendment" in text.lower():
        rel_lords = lords_amendment_check.search(text)
        if rel_lords:
            lords_text = rel_lords.group(0)
            result = f"{result} ({lords_text})"
    return result


def get_major_minor_equiv(speech_id: str) -> int:
    dots = speech_id.split(".")
    major = int(dots[-2])
    minor = int(dots[-1])
    return major * 100 + minor


def condense_motions(motions: list[Motion]) -> list[Motion]:
    """
    This doesn't remove any motions - but tries to copy key information
    from the 'main' question to abstract motions that may be closer to the actual vote.
    """
    main_motions = [x for x in motions if x.has_flag(Flag.MAIN_QUESTION)]
    amendment_motions = [x for x in motions if x.has_flag(Flag.MOTION_AMENDMENT)]

    main_motion_text = None
    if len(main_motions) == 1:
        main_motion_text = str(main_motions[0])

    amendment_motion_text = None
    if len(amendment_motions) == 1:
        amendment_motion_text = str(amendment_motions[0])

    previous_motion = None
    for motion in motions:
        s_motion = str(motion).lower()
        if motion.has_flag(Flag.ABSTRACT_MOTION):
            if "That the original words stand part of the Question".lower() in s_motion:
                if amendment_motion_text:
                    motion.motion_lines.extend(
                        ["Amendment:"] + amendment_motion_text.split("\n")
                    )
                if main_motion_text:
                    motion.motion_lines.extend(
                        ["Original words:"] + main_motion_text.split("\n")
                    )
            if "That the proposed words be there added.".lower() in s_motion:
                if amendment_motion_text:
                    motion.motion_lines.extend(
                        ["Amendment:"] + amendment_motion_text.split("\n")
                    )
            if "That the amendment be made.".lower() in s_motion:
                # Capturing where the question action has been captured seperately from the motion that
                # ends up being voted on
                if previous_motion:
                    if previous_motion.speech_id and motion.speech_id:
                        motion.motion_lines.extend(
                            ["Amendment:"] + str(previous_motion).split("\n")
                        )

        previous_motion = motion

    return motions


def remove_redundant_agreements(
    decisions: list[DivisionHolder | Agreement],
) -> list[DivisionHolder | Agreement]:
    """
    Very edge case where a SI has been printed and agreed twice.
    """
    new_list = []

    previous_texts = []

    for decision in decisions:
        if isinstance(decision, DivisionHolder):
            new_list.append(decision)
            continue

        agreement_text = (
            (decision.preceeding_text + decision.agreed_text).lower().strip()
        )

        if agreement_text not in previous_texts:
            previous_texts.append(agreement_text)
            new_list.append(decision)
    return new_list


def remove_redundant_motions(motions: list[Motion]) -> list[Motion]:
    # remove any motions with similar or substancially similar text
    # this is ususaly when a motion is being (usefully) restated,
    # but causes us problems because we then get more than *one* relevant motion

    # for the first version of this, we're just checking overlap

    non_redundant_motions = []

    base_motion = motions[0]
    non_redundant_motions.append(base_motion)
    base_text = clean_text(str(base_motion))

    for motion in motions[1:]:
        r_motion_text = clean_text(str(motion))
        if r_motion_text != base_text:
            non_redundant_motions.append(motion)

    return non_redundant_motions


class ResultsHolder(BaseModel):
    date: str
    chamber: Chamber
    division_motions: list[DivisionHolder] = Field(default_factory=list)
    agreement_motions: list[Agreement] = Field(default_factory=list)

    def export_motions_parquet(self, output_dir: Path):
        all_motions = [
            x.motion.flat()
            for x in self.division_motions + self.agreement_motions
            if x.motion
        ]
        df = pd.DataFrame(all_motions)
        df["chamber"] = self.chamber
        df.to_parquet(output_dir / f"{self.chamber}-{self.date}-motions.parquet")

    def export_divison_links(self, output_dir: Path):
        df = pd.DataFrame(
            [
                {
                    "division_gid": x.gid,
                    "motion_gid": x.motion_speech_id(),
                }
                for x in self.division_motions
            ]
        )
        df["chamber"] = self.chamber
        df.to_parquet(output_dir / f"{self.chamber}-{self.date}-division-links.parquet")

    def export_agreements(self, output_dir: Path):
        df = pd.DataFrame([x.flat() for x in self.agreement_motions])
        df["chamber"] = self.chamber
        df.to_parquet(output_dir / f"{self.chamber}-{self.date}-agreements.parquet")

    def export(self, output_dir: Path):
        if not output_dir.exists():
            output_dir.mkdir(parents=True)
        self.export_motions_parquet(output_dir)
        self.export_divison_links(output_dir)
        self.export_agreements(output_dir)

    def to_data_dir(self, data_dir: Path):
        if not data_dir.exists():
            data_dir.mkdir(parents=True)
        with (data_dir / f"{self.chamber}-{self.date}.json").open("w") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def from_data_dir(cls, data_dir: Path, date: str, chamber: Chamber):
        with (data_dir / f"{chamber}-{date}.json").open() as f:
            return cls.model_validate_json(f.read())

    @classmethod
    def from_data_dir_composite(cls, data_dir: Path, date: str, chamber: Chamber):
        items: list[ResultsHolder] = []
        if date == "custom":
            file_paths = []
            for year in range(2000, 2019):
                file_paths.extend(data_dir.glob(f"{chamber}-{year}*.json"))
        else:
            file_paths = data_dir.glob(f"{chamber}-{date}*.json")
        for file_path in file_paths:
            with file_path.open() as f:
                item = cls.model_validate_json(f.read())
                items.append(item)

        composite = cls(
            date=date,
            chamber=chamber,
            division_motions=list(chain(*[x.division_motions for x in items])),
            agreement_motions=list(chain(*[x.agreement_motions for x in items])),
        )
        return composite


class MotionMapper:
    def __init__(
        self, transcript: Transcript, debate_date: str, chamber: Chamber, data_dir: Path
    ):
        self.transcript = transcript
        self.speech_id_map = {
            x.id: n  # type: ignore
            for n, x in enumerate(transcript.items)
            if hasattr(x, "id")
        }
        self.data_dir = data_dir
        self.debate_date = debate_date
        self.chamber = chamber
        self.found_motions = get_motions(self.chamber, transcript, debate_date)
        self.found_agreements = get_agreements(self.chamber, transcript, debate_date)
        self.found_divisions = get_divisions(self.chamber, transcript, debate_date)
        self.division_assignments: list[DivisionHolder] = []
        self.agreement_assignments: list[Agreement] = []

    def speech_distance(self, id_a: str, id_b: str) -> int:
        return abs(self.speech_id_map[id_a] - self.speech_id_map[id_b])

    def dump_test_data(self, tests_data_path: Path):
        with (tests_data_path / f"{self.debate_date}.json").open("w") as f:
            json.dump(self.snapshot(), f, indent=2)

    def snapshot(self):
        # dictionary to use as a snapshot
        return {
            "division_motions": {
                x.gid: x.motion_speech_id() for x in self.division_assignments
            },
            "agreement_motions": {
                x.gid: x.motion_speech_id() for x in self.agreement_assignments
            },
        }

    def export(self) -> ResultsHolder:
        return ResultsHolder(
            date=self.debate_date,
            chamber=self.chamber,
            division_motions=self.division_assignments,
            agreement_motions=self.agreement_assignments,
        )

    def all_items(self):
        def ordered_speech(gid: str) -> float:
            return float(".".join(gid.split(".")[-2:]))

        items = (
            list(self.found_motions)
            + list(self.found_agreements)
            + list(self.found_divisions)
        )
        items.sort(key=lambda x: ordered_speech(x.speech_id))
        return items

    def assign_motion_decision(
        self,
        motion: Motion,
        decision: DivisionHolder | Agreement,
        assignment_reason: str,
    ):
        if DEBUG:
            motion_start = str(motion)[:30]
            print(
                f"Assigning motion: {motion.speech_id} ({motion_start})  to {type(decision).__name__}: {decision.gid} - {assignment_reason}"
            )
        decision.motion = motion
        decision.motion_assignment_reason = assignment_reason
        match decision:
            case DivisionHolder():
                self.division_assignments.append(decision)
            case Agreement():
                self.agreement_assignments.append(decision)

    def decision_position(self, decision: DivisionHolder | Agreement) -> int:
        return self.speech_id_map.get(decision.speech_id, 0)

    def motion_position(self, motion: Motion) -> int:
        start = self.speech_id_map.get(motion.speech_id, 0)
        end = self.speech_id_map.get(motion.final_speech_id, 0)
        return max(start, end)

    def multiple_decision_assignment(
        self,
        possible_motions: list[Motion],
        decisions: list[DivisionHolder | Agreement],
        previous_motions: list[Motion] | None = None,
    ):
        if previous_motions is None:
            previous_motions = []

        possible_motions = condense_motions(possible_motions)
        previous_loop = len(decisions) + 1

        second_stage_motions = [
            x for x in possible_motions if x.has_flag(Flag.SECOND_STAGE)
        ]
        if len(second_stage_motions) > 1:
            # if we have multiple second stage motions - we want to just keep the first
            # because it might confuse reasoned amendment assignment
            possible_motions = [
                x for x in possible_motions if x not in second_stage_motions[1:]
            ]

        if any(x.has_flag(Flag.REASONED_AMENDMENT_FULL) for x in possible_motions):
            # remove any partial reasoned amendments if so
            # this is because ANNOYINGLY sometimes they don't print the reasoned amendment
            # so we need to fall back to another way of catagorising it to get the right map
            # given this is ALWAYS in the same vote as a staged vote
            possible_motions = [
                x
                for x in possible_motions
                if not x.has_flag(Flag.REASONED_AMENDMENT_PARTIAL)
            ]

        while len(decisions) < previous_loop:
            previous_loop = len(decisions)
            # print(len(decisions), previous_loop)

            # do we have any decisions on something 'as amended'?
            as_amended_decisions = [
                x for x in decisions if "as amended" in x.relevant_text
            ]

            if len(as_amended_decisions) == 1:
                # see if we have one 'after_decision' motion
                after_decision_motions = [
                    x for x in possible_motions if Flag.AFTER_DECISION in x.flags
                ]
                if len(after_decision_motions) == 1:
                    self.assign_motion_decision(
                        after_decision_motions[0],
                        as_amended_decisions[0],
                        "just one after decision motion",
                    )
                    decisions = [x for x in decisions if x != as_amended_decisions[0]]
                    old_motion_count = len(possible_motions)
                    possible_motions = [
                        x for x in possible_motions if x != after_decision_motions[0]
                    ]
                    if len(possible_motions) != old_motion_count - 1:
                        raise ValueError("After decision motion not removed")
                    continue

            # hints from flags
            # if we try and construct a motion from the text surrounding the decision
            # does it share a flag with one of the motions
            banned_overlap_flags = [Flag.MAIN_QUESTION, Flag.AFTER_DECISION]
            for decision in decisions:
                constructed_motion = decision.construct_motion(use_agreed_only=True)
                possible_flagged_motions = []
                for motion in possible_motions:
                    overlap_flags = (
                        set(motion.flags) & set(constructed_motion.flags)
                    ) - set(banned_overlap_flags)
                    if overlap_flags:
                        # print(f"overlap flags: {overlap_flags}")
                        possible_flagged_motions.append(motion)
                if len(possible_flagged_motions) == 1:
                    self.assign_motion_decision(
                        possible_flagged_motions[0],
                        decision,
                        "constructed motion flag match",
                    )
                    decisions = [x for x in decisions if x != decision]
                    possible_motions = [
                        x for x in possible_motions if x != possible_flagged_motions[0]
                    ]
                    continue

            if self.chamber == Chamber.SCOTLAND:
                # Here we have some special casing for amendments in the scottish Parliament
                # these should happen pretty good in order! But there may be a bit more spacing than usual
                # for no! and some comments

                match_allowance = 20
                for decision in decisions:
                    amendment_motions = [
                        x
                        for x in possible_motions
                        if x.has_flag(Flag.MOTION_AMENDMENT)
                        or x.has_flag(Flag.SCOTTISH_EXPANDED_MOTION)
                    ]
                    dec_pos = self.decision_position(decision)
                    possible_match = None
                    match_distance = 1000

                    for amendment in amendment_motions:
                        # we want to allow an amendment if it's it's a motion *before* the decision and
                        # the closest within match_allowance blocks
                        motion_pos = self.motion_position(amendment)
                        dec_motion_distance = abs(motion_pos - dec_pos)

                        if (
                            motion_pos < dec_pos
                            and dec_motion_distance < match_allowance
                        ):
                            if (
                                possible_match is None
                                or dec_motion_distance < match_distance
                            ):
                                if DEBUG:
                                    print(
                                        f"assigning {amendment.speech_id} to {decision.gid} based on distance {dec_motion_distance}"
                                    )
                                possible_match = amendment
                                match_distance = dec_pos - motion_pos
                    if possible_match:
                        self.assign_motion_decision(
                            possible_match, decision, "scottish amendment"
                        )
                        decisions = [x for x in decisions if x != decision]
                        possible_motions = [
                            x for x in possible_motions if x != possible_match
                        ]
                        continue

            # try and match up decisions on amendment with the original motions
            # find the relevant amendment string and see if it's in the motion

            for decision in decisions:
                # print(f"d gid: {decision.gid}")
                detected_amendment = extract_amendment(decision.relevant_text)

                if detected_amendment:
                    possible_amendment_motions = [
                        x
                        for x in possible_motions
                        if detected_amendment.lower() in str(x).lower()
                    ]

                    if len(possible_amendment_motions) > 1:
                        possible_amendment_motions = remove_redundant_motions(
                            possible_amendment_motions
                        )

                    if len(possible_amendment_motions) == 1:
                        self.assign_motion_decision(
                            possible_amendment_motions[0],
                            decision,
                            "relevant amendment",
                        )
                        decisions = [x for x in decisions if x != decision]
                        possible_motions = [
                            x
                            for x in possible_motions
                            if x != possible_amendment_motions[0]
                        ]
                        continue

                    if len(possible_amendment_motions) > 1:
                        if isinstance(decision, Agreement):
                            if lords_amendment_agreement(decision.agreed_text):
                                motion = decision.construct_motion(use_agreed_only=True)
                                if motion:
                                    self.assign_motion_decision(
                                        motion, decision, "lords amendment"
                                    )
                                    decisions = [x for x in decisions if x != decision]
                                    continue

                    if len(possible_amendment_motions) > 1:
                        rich.print(decision)
                        rich.print(possible_amendment_motions)

                        raise ValueError(
                            f"Too many amendment motions found on {self.debate_date}"
                        )

                ## are there any motions that almost exactly match the preceeding text of the question
                # e.g.That the Bill be now read the Third time.
                rel_text = (
                    decision.relevant_text.lower()
                    .replace("question, ", "")
                    .replace("question put, ", "")
                    .replace(" now ", " ")
                    .replace("question agreed to", "")
                    .strip()
                )

                # remove closing full stop
                if rel_text.endswith("."):
                    rel_text = rel_text[:-1]

                preceeding_text = decision.preceeding.lower().strip()
                text_match_motions = []

                for rt in [rel_text, preceeding_text]:
                    if len(rt) > 5:
                        for motion in possible_motions:
                            motion_str = str(motion).lower()
                            motion_str = motion_str.replace("be now read", "be read")
                            if rt in motion_str:
                                if motion not in text_match_motions:
                                    text_match_motions.append(motion)
                if len(text_match_motions) == 1:
                    self.assign_motion_decision(
                        text_match_motions[0], decision, "text match on proceeding"
                    )
                    decisions = [x for x in decisions if x != decision]
                    possible_motions = [
                        x for x in possible_motions if x != text_match_motions[0]
                    ]
                    continue

                if main_question_put(rel_text):
                    # if there's *one* relevant main question, this is our match
                    decision_pos = self.decision_position(decision)
                    main_motions = [
                        x
                        for x in possible_motions
                        if x.has_flag(Flag.MAIN_QUESTION)
                        and self.motion_position(x) < decision_pos
                    ]
                    # rich.print(main_motions)
                    if len(main_motions) == 1:
                        self.assign_motion_decision(
                            main_motions[0], decision, "one relevant main question"
                        )
                        decisions = [x for x in decisions if x != decision]
                        possible_motions = [
                            x for x in possible_motions if x != main_motions[0]
                        ]
                        continue

            # for each decisions, are there any that have only one motion that shares the same speech_id
            # or are (close)

            for index, decision in enumerate(decisions):
                decision_pos = self.decision_position(decision)

                exact_matches: list[Motion] = []
                nearby_matches: list[Motion] = []
                remainder_matches: list[Motion] = []

                for motion in possible_motions:
                    motion_pos = self.motion_position(motion)
                    if motion_pos > decision_pos and not motion.has_flag(
                        Flag.AFTER_DECISION
                    ):
                        continue
                    if motion_pos < decision_pos and motion.has_flag(
                        Flag.AFTER_DECISION
                    ):
                        # ignore after_decision motions that come *before* the motion we're concerned about.
                        continue
                    elif motion_pos == decision_pos:
                        # if this is the case, we need to check the motion comes before the decision
                        # we implicitly know this is an agreement because a devision would have a minimum distance of 1
                        exact_matches.append(motion)
                    elif abs(motion_pos - decision_pos) <= 2:
                        nearby_matches.append(motion)
                    else:
                        remainder_matches.append(motion)

                # prefer exact matches
                if exact_matches:
                    relevant_motions = exact_matches
                    reason_str = "exact id match"
                else:
                    relevant_motions = nearby_matches
                    reason_str = "nearby id match"

                if len(relevant_motions) > 1:
                    # sometimes there are multiple ones that share the speech id - we want the last one if this is so
                    if len(set([x.speech_id for x in relevant_motions])) == 1:
                        relevant_motions = [relevant_motions[-1]]

                if len(relevant_motions) == 1:
                    # print(f"motion_pos: {motion_pos} decision_pos: {decision_pos}")
                    # print(f"is_before: {motion_pos < decision_pos}")
                    self.assign_motion_decision(
                        relevant_motions[0], decision, reason_str
                    )
                    decisions = [x for x in decisions if x != decision]
                    possible_motions = [
                        x for x in possible_motions if x != relevant_motions[0]
                    ]
                    continue

                if len(relevant_motions) == 0 and len(remainder_matches) == 1:
                    # exactly one motion left after we've found no nearby motions
                    # and discarded prior after motions
                    # this helps catch instances where of the two last remaining instances
                    # one isn't *close* (e.g. at the top of the debate)
                    # but the other is an after_decision motion from an earlier decision.
                    self.assign_motion_decision(
                        remainder_matches[0], decision, "remainder match"
                    )
                    decisions = [x for x in decisions if x != decision]
                    possible_motions = [
                        x for x in possible_motions if x != remainder_matches[0]
                    ]
                    continue

            for decision in decisions:
                if amendment_be_made(decision.preceeding):
                    # if there's one motion amendment, this is our match
                    amendment_motions = [
                        x for x in possible_motions if x.has_flag(Flag.MOTION_AMENDMENT)
                    ]
                    if len(amendment_motions) == 1:
                        self.assign_motion_decision(
                            amendment_motions[0], decision, "one amendment motion"
                        )
                        decisions = [x for x in decisions if x != decision]
                        possible_motions = [
                            x for x in possible_motions if x != amendment_motions[0]
                        ]
                        continue

            # when we're down to one, we can move on
            if len(possible_motions) == 1 and len(decisions) == 1:
                self.assign_motion_decision(
                    possible_motions[0], decisions[0], "just one left"
                )
                decisions = []
                continue

            if len(possible_motions) > 1 and len(decisions) == 1:
                decision = decisions[0]

                # if down to one decision, multiple motions - let's see if there's a motion in a sensible range nearby

                for motion in possible_motions:
                    # 5 is arbitary here - allows for a few extra lines after the motion
                    if (self.speech_distance(motion.speech_id, decision.speech_id)) < 5:
                        self.assign_motion_decision(motion, decision, "close by motion")
                        decisions = []
                        break

                if len(decisions) == 0:
                    continue

                # if there is only one 'one_line_motion' we can use that.
                # This is generally the 'main question'

                one_line_motions = [
                    x
                    for x in possible_motions
                    if Flag.ONE_LINE_MOTION in x.flags
                    and Flag.INLINE_AMENDMENT not in x.flags
                ]

                if len(one_line_motions) == 1:
                    self.assign_motion_decision(
                        one_line_motions[0], decision, "prioritise one line motion"
                    )
                    decisions = []
                    continue

                # is the relevant tex for a decision within any of the motions

                for decision in decisions:
                    rel_text = decision.preceeding.lower()
                    relevant_motions = [
                        x for x in possible_motions if rel_text in str(x).lower()
                    ]
                    if len(relevant_motions) == 1:
                        self.assign_motion_decision(
                            relevant_motions[0], decision, "single relevant text match"
                        )
                        decisions = [x for x in decisions if x != decision]
                        possible_motions = [
                            x for x in possible_motions if x != relevant_motions[0]
                        ]
                        continue

            if len(decisions) > 0:
                for decision in decisions:
                    # ok, this is just giving up.
                    # For some decisions we just can't find a motion
                    # But we can construct something like it from the header
                    # so we do do that!
                    if (
                        can_be_self_motion(decision.relevant_text)
                        or can_be_self_motion(decision.preceeding)
                        or can_be_self_motion(decision.after)
                    ):
                        motion = decision.construct_motion()
                        if motion:
                            self.assign_motion_decision(
                                motion, decision, "constructed motion"
                            )
                            decisions = [x for x in decisions if x != decision]
                            continue

            if len(decisions) == 1:
                # are all motions text identical?
                if len(set([clean_text(str(x)) for x in possible_motions])) == 1:
                    self.assign_motion_decision(
                        possible_motions[0], decisions[0], "all motions identical"
                    )
                    decisions = []
                    continue

            if (
                len(decisions) > 0
                and len(possible_motions) == 0
                and len(previous_motions) > 0
            ):
                possible_motions = [
                    x for x in previous_motions if x.has_flag(Flag.MAIN_QUESTION)
                ]
                previous_motions = []
                continue

        if len(decisions) > 0:
            # if all remaining are 'agreements' I am ok just not collecting them
            # we're *mostly* interested in the divisions and agreements as a way of specifying the right
            # motion
            agreements = [x for x in decisions if isinstance(x, Agreement)]
            if len(decisions) == len(agreements):
                decisions = []
                for a in agreements:
                    rich.print(f"Agreement {a.gid} not assigned - no relevant motions.")

        if len(decisions) > 0:
            rich.print(decisions)
            rich.print(possible_motions)
            raise ValueError(f"Unassigned decisions remain on date {self.debate_date}")

    def assign_manual(self):
        manual_lookup = get_manual_connections(self.data_dir)
        decisions: list[DivisionHolder | Agreement] = list(
            self.found_agreements
        ) + list(self.found_divisions)
        for m in self.found_motions:
            if m.gid in manual_lookup:
                mdecision_gid = manual_lookup[m.gid]
                mdecision = [x for x in decisions if x.gid == mdecision_gid]
                if len(mdecision) == 1:
                    self.assign_motion_decision(m, mdecision[0], "manual lookup")
                elif len(mdecision) == 0:
                    raise ValueError(f"Manual lookup failed to find {mdecision_gid}")

        # when motions are just missing, sometimes we specify the whole thing by hand
        manual_motions = get_manual_text(self.data_dir)
        for decision in decisions:
            if decision.gid in manual_motions:
                motion = manual_motions[decision.gid]
                self.assign_motion_decision(motion, decision, "manual text")

    def assign_scotland(self):
        for d in list(self.found_divisions) + list(self.found_agreements):
            after_motions = extract_sp_motions(d.after)
            # what we need to check here is if we've got S6M-15508.1 amending S6M-15508 - we only want the long verson.
            # discard any motions that are fully contained in another

            if len(after_motions) > 1:
                raise ValueError(
                    f"Multiple scottish motions found in {d.gid} - {after_motions}"
                )
            if len(after_motions) == 1:
                if "as amended" in d.after.lower():
                    # there will be a motion text in the actual transcript that should be easily extracted
                    continue
                motion = get_sp_manager().construct_from_decision(after_motions[0], d)
                self.assign_motion_decision(motion, d, "scottish motion")

    def assigned_gids(self):
        division_gids = [x.gid for x in self.division_assignments]
        agreement_gids = [x.gid for x in self.agreement_assignments]
        divison_motion_gids = [x.motion_speech_id() for x in self.division_assignments]
        agreement_motion_gids = [
            x.motion_speech_id() for x in self.agreement_assignments
        ]
        return (
            division_gids + agreement_gids + divison_motion_gids + agreement_motion_gids
        )

    def assign(self):
        # first step is see if we've for unique division and motions within a major heading

        previous_motions: list[Motion] = []

        # assign manual ones first so these can reach across major heading divides
        self.assign_manual()

        self.assign_scotland()

        # remove inappriprate motions

        def is_inappropriate(motion: Motion) -> bool:
            # there's a thing after first reading where what's resolved is who presents the bill rather than the *content* of the bill.
            # which is ideally what we want
            if motion.has_flag(Flag.AFTER_DECISION) and str(
                motion
            ).strip().lower().endswith("present the bill."):
                return True
            return False

        self.found_motions = [x for x in self.found_motions if not is_inappropriate(x)]

        remaining_items = [
            x for x in self.all_items() if x.gid not in self.assigned_gids()
        ]

        for major_heading_id, items in groupby(
            remaining_items, lambda x: x.major_heading_id
        ):
            items = list(items)
            possible_motions = [x for x in items if isinstance(x, Motion)]
            decisions = [x for x in items if isinstance(x, DivisionHolder | Agreement)]

            decisions = remove_redundant_agreements(decisions)

            if len(possible_motions) == 0:
                possible_motions.extend(previous_motions)
                previous_motions = []

            if len(possible_motions) == 1 and len(decisions) == 1:
                self.assign_motion_decision(
                    possible_motions[0], decisions[0], "single motion and decision"
                )
                continue
            if len(decisions) == 0:
                # sometimes time runs out, and motions are not voted on
                previous_motions.extend(possible_motions)
                continue

            if len(decisions) == 1 and len(possible_motions) > 1:
                # seperating out if needed to make clear which branch we're in
                self.multiple_decision_assignment(
                    possible_motions, decisions, previous_motions
                )
                continue

            if len(decisions) > 1:
                self.multiple_decision_assignment(
                    possible_motions, decisions, previous_motions
                )
                continue

            if len(decisions) == 1 and len(possible_motions) == 0:
                # *also* send this down the multiple path because it has some self extracting features
                self.multiple_decision_assignment(
                    possible_motions, decisions, previous_motions
                )
                continue

        if len(self.found_divisions) != len(self.division_assignments):
            diff = len(self.found_divisions) - len(self.division_assignments)
            # rich.print(self.division_assignments)
            # rich.print(self.found_divisions)
            raise ValueError(
                f"Not all divisions assigned - {diff} remain for {self.debate_date}"
            )
