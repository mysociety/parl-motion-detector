from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from parl_motion_detector.process import save_package_resource


@pytest.mark.parametrize("resource", ["agreements", "division-links", "motions"])
def test_resource_identifiers_and_chambers(resource: str) -> None:
    """
    Validate identifiers and chamber values in built or stored package resources.
    """
    package = (
        Path(__file__).resolve().parents[1] / "data/packages/parliamentary_motions"
    )
    path = package / f"{resource}.parquet"
    if not path.exists():
        path = package / "versions/0.1.0" / f"{resource}.parquet"
    frame = pd.read_parquet(path)
    identifier = "division_gid" if resource == "division-links" else "gid"

    assert not frame.empty
    assert frame[identifier].notna().all()
    assert frame[identifier].is_unique
    assert frame[identifier].str.startswith("uk.org.publicwhip/").all()
    assert frame["chamber"].isin(["house-of-commons", "scottish-parliament"]).all()
    if "date" in frame:
        assert (
            pd.to_datetime(frame["date"], format="%Y-%m-%d", errors="raise")
            .notna()
            .all()
        )


@pytest.mark.parametrize("changed", [False, True])
def test_resource_rebuild_preserves_only_identical_data(
    tmp_path: Path, changed: bool
) -> None:
    """
    Retain snapshot bytes for identical tables and write actual data changes.
    """
    stored = tmp_path / "stored.parquet"
    output = tmp_path / "output.parquet"
    original = pd.DataFrame({"gid": ["one", "two"], "value": [1, 2]})
    original.to_parquet(stored, compression="gzip")
    rebuilt = original.copy()
    if changed:
        rebuilt.loc[0, "value"] = 3

    save_package_resource(rebuilt, output, stored)

    pd.testing.assert_frame_equal(pd.read_parquet(output), rebuilt)
    assert (output.read_bytes() == stored.read_bytes()) is (not changed)
