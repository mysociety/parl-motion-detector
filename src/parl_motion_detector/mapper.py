from __future__ import annotations

import json
import re
from itertools import groupby
from pathlib import Path
from typing import TypeVar

import rich
from mysoc_validator import Transcript

from parl_motion_detector.detector import PhraseDetector

from .agreements import (
    Agreement,
    DivisionHolder,
    get_agreements,
    get_divisions,
)
from .motions import Flag, Motion, get_motions

T = TypeVar("T")

amendment_check = re.compile(r"Amendment \([A-Za-z0-9]+\)", re.IGNORECASE)

lords_amendment_check = re.compile(r"Lords Amendment [A-Za-z0-9]+", re.IGNORECASE)


main_question_put = PhraseDetector(
    criteria=["question put and agreed to", "That the amendment be made."]
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
        re.compile(r"amendment \(\w+\) to Lords amendment \d+ be made", re.IGNORECASE),
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


class MotionMapper:
    def __init__(self, transcript: Transcript, debate_date: str):
        self.transcript = transcript
        self.speech_id_map = {
            x.id: n  # type: ignore
            for n, x in enumerate(transcript.items)
            if hasattr(x, "id")
        }
        self.debate_date = debate_date
        self.found_motions = get_motions(transcript, debate_date)
        self.found_agreements = get_agreements(transcript, debate_date)
        self.found_divisions = get_divisions(transcript, debate_date)
        self.division_assignments: dict[str, Motion] = {}
        self.agreement_assignments: dict[str, Motion] = {}

    def speech_distance(self, id_a: str, id_b: str) -> int:
        return abs(self.speech_id_map[id_a] - self.speech_id_map[id_b])

    def dump_test_data(self, tests_data_path: Path):
        with (tests_data_path / f"{self.debate_date}.json").open("w") as f:
            json.dump(self.snapshot(), f, indent=2)

    def snapshot(self):
        # dictionary to use as a snapshot
        return {
            "division_motions": {
                k: v.speech_id for k, v in self.division_assignments.items()
            },
            "agreement_motions": {
                k: v.speech_id for k, v in self.agreement_assignments.items()
            },
        }

    def export(self):
        return {
            "division_motions": self.division_assignments,
            "agreement_motions": self.agreement_assignments,
        }

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
        # print(f"Assigning {motion.speech_id} to {decision.speech_id} - {assignment_reason}")
        match decision:
            case DivisionHolder():
                self.division_assignments[decision.gid] = motion
            case Agreement():
                self.agreement_assignments[decision.gid] = motion

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
    ):
        possible_motions = condense_motions(possible_motions)
        previous_loop = len(decisions) + 1

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
                    possible_motions = [
                        x for x in possible_motions if x != after_decision_motions[0]
                    ]
                    continue

            # if len(as_amended_decisions) > 1:
            #    rich.print(as_amended_decisions)
            #    raise ValueError("Too many 'as amended' decisions")

            # try and match up decisions on amendment with the original motions
            # find the relevant amendment string and see if it's in the motion

            for decision in decisions:
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
                        rich.print(decision)
                        rich.print(possible_amendment_motions)
                        raise ValueError("Too many amendment motions found")

                ## are there any motions that almost exactly match the preceeding text of the question
                # e.g.That the Bill be now read the Third time.
                rel_text = (
                    decision.relevant_text.lower()
                    .replace("question put, ", "")
                    .replace(" now ", " ")
                    .replace("question agreed to", "")
                    .strip()
                )
                preceeding_text = decision.preceeding.lower().strip()
                for rt in [rel_text, preceeding_text]:
                    text_match_motions = []
                    if len(rt) > 5:
                        for motion in possible_motions:
                            if rt in str(motion).lower():
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

                for motion in possible_motions:
                    motion_pos = self.motion_position(motion)
                    if motion_pos > decision_pos and not motion.has_flag(
                        Flag.AFTER_DECISION
                    ):
                        continue
                    elif motion_pos == decision_pos:
                        exact_matches.append(motion)
                    elif abs(motion_pos - decision_pos) <= 2:
                        nearby_matches.append(motion)

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
                    self.assign_motion_decision(
                        relevant_motions[0], decision, reason_str
                    )
                    decisions = [x for x in decisions if x != decision]
                    possible_motions = [
                        x for x in possible_motions if x != relevant_motions[0]
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
            raise ValueError("Unassigned decisions remain")

    def assign(self):
        # first step is see if we've for unique division and motions within a major heading

        previous_motions: list[Motion] = []

        for major_heading_id, items in groupby(
            self.all_items(), lambda x: x.major_heading_id
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

            if len(decisions) > 2:
                self.multiple_decision_assignment(possible_motions, decisions)
                continue

            if len(decisions) == 1 and len(possible_motions) > 1:
                # seperating out if needed to make clear which branch we're in
                self.multiple_decision_assignment(possible_motions, decisions)
                continue