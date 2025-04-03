from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motions import Motion

from mysoc_validator.models.transcripts import Chamber

from parl_motion_detector.detector import PhraseDetector

# Compile the regex pattern in advance
disagreement_pattern = re.compile(
    r"This house disagrees with Lords amendment (\d+[A-Z]?)", re.IGNORECASE
)

reasons_patterns = [
    re.compile(r"Amendment\s(\d+[A-Z])", re.IGNORECASE),
    re.compile(r"Amendments\s*(\d+[A-Z]\s+and\s+\d+[A-Z])", re.IGNORECASE),
]


reasons_committee = PhraseDetector(
    criteria=[
        "Committee be appointed to draw up Reasons",
        "Committee be appointed to draw up a Reason",
    ]
)

adjournment_debate = PhraseDetector(criteria=["this House do now adjourn"])

be_approved = PhraseDetector(criteria=["be approved"])

leave_for_bill = PhraseDetector(
    criteria=["leave be given to bring in a Bill", "leave to bring in a Bill"]
)

legislation_patterns = [
    re.compile(r"([A-Z][a-z]+(?: [A-Z][a-z]+)* \([A-Za-z ,\.\-]+\) Regulations \d{4})"),
    re.compile(r"the\s(\b[A-Z][A-Za-z\s\(\)]*?Regulations \d{4})"),
    re.compile(r"draft\s+(.*?\d{4}\s+\(.*?\)\s+Order\s+\d{4})"),
]
move_amendment = PhraseDetector(
    criteria=[
        "beg to move an amendment",
        "beg to move amendment",
        "Amendment proposed",
        re.compile(
            r"The question is, (?:that|the) amendment \d+ be agreed to\. Are we agreed\?",
            re.IGNORECASE,
        ),
    ]
)

second_reading = PhraseDetector(criteria=["read a Second time", "read the Second time"])
first_reading = PhraseDetector(criteria=["read a First time", "read the First time"])
third_reading = PhraseDetector(criteria=["read a Third time", "read the Third time"])

private_sitting = PhraseDetector(criteria=["the House sit in private"])

in_text_clause = re.compile(r"^New clause (\d+)", re.IGNORECASE)

in_text_amendment_patterns = [
    re.compile(r"^Amendment (\d+),", re.IGNORECASE),
]

in_text_amendment_scotland_patterns = [
    re.compile(r"Amendments? (\d+ and \d+)", re.IGNORECASE),
    re.compile(r"Amendment (\d+)", re.IGNORECASE),
]

new_order = PhraseDetector(criteria=["and makes provision as set out in this Order"])

suspend_standing_order = re.compile(
    r"Standing Order No\. (\d+[A-Z]?) *\(*.*?\)* shall not apply to the Motion",
    re.IGNORECASE,
)


def first_search(text: str, patterns: list[re.Pattern]) -> re.Match | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


def extract_disagreement(text: str):
    # Use the pre-compiled regex pattern
    match = disagreement_pattern.search(text)

    if match:
        # Extract the amendment number from the matched string
        amendment = match.group(1)
        return f"Disagree: Lords amendment {amendment}"

    # Return None if no match is found
    return None


def extract_legislation_name(text: str):
    match = first_search(text, legislation_patterns)
    if match:
        return match.group(1)
    return None


def extract_motion_title(motion: Motion) -> str:
    content = str(motion).replace("\n", " ")
    # Extract the motion title from the motion object

    # if a scottish motion
    from .motions import extract_sp_motions, get_sp_manager

    if motion.chamber == Chamber.SCOTLAND:
        possible_motions = extract_sp_motions(content)

        if len(possible_motions) == 1:
            try:
                motion_data = get_sp_manager().get_motion(possible_motions[0])
                return motion_data.nice_title()
            except KeyError:
                pass

    # Check if the motion title contains a disagreement with a Lords amendment
    if d := extract_disagreement(content):
        return d

    if reasons_committee(content):
        match = first_search(content, reasons_patterns)
        if match:
            amendments_text = match.group(1)
            return f"Appoint Reasons Committee: {amendments_text}"
        else:
            return "Appoint Reasons Committee"

    if adjournment_debate(content):
        return f"Adjournment Debate: {motion.major_heading_title}"

    if be_approved(content):
        legislation_name = extract_legislation_name(content)
        if legislation_name:
            return f"Approve: {legislation_name}"

    if match := suspend_standing_order.search(content):
        return f"Disapply Standing Order {match.group(1)}"

    if private_sitting(content):
        return f"{motion.major_heading_title}: Sit in Private"

    prefix = ""
    if move_amendment(content):
        prefix = "Amendment: "

    if new_order(content):
        return f"New Order: {motion.major_heading_title}"

    if second_reading(content):
        return f"Second Reading: {motion.major_heading_title}"

    if first_reading(content):
        return f"First Reading: {motion.major_heading_title}"

    if third_reading(content):
        return f"Third Reading: {motion.major_heading_title}"

    if leave_for_bill(content):
        return f"Leave for Bill: {motion.major_heading_title}"

    if motion.chamber == Chamber.SCOTLAND:
        for pattern in in_text_amendment_scotland_patterns:
            if match := pattern.search(content):
                return f"Amendment {match.group(1)}: {motion.major_heading_title}"
    else:
        for pattern in in_text_amendment_patterns:
            if match := pattern.search(content):
                return f"Amendment {match.group(1)}: {motion.major_heading_title}"

    if "clause" in motion.minor_heading_title.lower():
        if match := in_text_clause.search(content):
            return f"New Clause {match.group(1)}: {motion.major_heading_title}"
        return motion.minor_heading_title

    if motion.minor_heading_id:
        return f"{prefix}{motion.major_heading_title}: {motion.minor_heading_title}"

    # Return the major title if no disagreement is found
    return f"{prefix}{motion.major_heading_title}"
