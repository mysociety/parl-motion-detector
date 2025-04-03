from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import httpx
from mysoc_validator.models.transcripts import Chamber
from pydantic import (
    AfterValidator,
    AliasGenerator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
)
from pydantic.alias_generators import to_pascal as base_pascal

if TYPE_CHECKING:
    from .agreements import Agreement, DivisionHolder
    from .motions import Motion


root_dir = Path(__file__).parent.parent.parent

StrippedStr = Annotated[str, AfterValidator(str.strip)]

motion_format = re.compile(r"^[A-Z0-9]{3}-[0-9]{5}(\.[0-9])?$")


def to_pascal(name: str) -> str:
    first_round = base_pascal(name)
    return first_round.replace("Id", "ID")


convert_config = ConfigDict(alias_generator=AliasGenerator(validation_alias=to_pascal))


class SPMotion(BaseModel):
    model_config = convert_config
    unique_id: int
    event_id: str
    title: str
    item_text: StrippedStr


MotionList = TypeAdapter(list[SPMotion])


@dataclass
class SPMotionManager:
    motions_dataset = (
        "https://data.parliament.scot/api/motionsquestionsanswersmotions/json"
    )
    root_dir: Path = root_dir
    download_timeout: float = 30.0
    motions: list[SPMotion] = Field(default_factory=list)
    motion_lookup: dict[str, SPMotion] = Field(default_factory=dict)

    def __post_init__(self):
        self.download_datasets()
        self.motions = MotionList.validate_json(self.motions_path.read_text())
        self.motion_lookup = {motion.event_id: motion for motion in self.motions}

    def construct_from_decision(
        self, motion_id: str, decision: Agreement | DivisionHolder
    ) -> Motion | None:
        try:
            motion_data = self.get_motion(motion_id)
        except KeyError:
            return None

        from .motions import Motion

        return Motion(
            date=decision.date,
            chamber=Chamber.SCOTLAND,
            speech_id=decision.speech_id,
            speech_start_pid=decision.paragraph_pid,
            motion_title=motion_data.title,
            motion_lines=motion_data.item_text.split("\n"),
        )

    def get_motion(self, motion_id: str):
        # manual remapping
        if motion_id == "S6M-133651.1":
            motion_id = "S6M-13365.1"
        if motion_id == "S6M-081050":
            motion_id = "S6M-08150"
        if motion_id == "S6M-011247":
            motion_id = "S6M-11247"

        if motion_id not in self.motion_lookup:
            if motion_format.match(motion_id):
                if motion_id not in self.motion_lookup:
                    raise KeyError(f"Motion ID {motion_id} not found")
            else:
                raise KeyError(f"Invalid motion ID format: {motion_id}")

        motion = self.motion_lookup[motion_id]

        if "." in motion_id:
            parent_id = motion_id.split(".")[0]
            parent_motion = self.motion_lookup[parent_id]

            text = f"{motion.item_text}\n\nOriginal motion({parent_motion.event_id}):\n{parent_motion.item_text}"
            motion.item_text = text

        return motion

    @property
    def raw_data_dir(self):
        return self.root_dir / "data" / "raw" / "sp"

    @property
    def motions_path(self):
        return self.raw_data_dir / "motions.json"

    def download_datasets(self, force: bool = False):
        if not self.raw_data_dir.exists():
            self.raw_data_dir.mkdir(parents=True)

        if not self.motions_path.exists() or force:
            with httpx.stream(
                "GET", self.motions_dataset, timeout=self.download_timeout
            ) as response:
                with open(self.motions_path, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
