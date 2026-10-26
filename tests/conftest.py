from __future__ import annotations

import gzip
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    Opt into public-daemon tests explicitly rather than depending on local caches.
    """
    parser.addoption(
        "--live-rsync",
        action="store_true",
        default=False,
        help="Run live rsync checks with fresh temporary transcript destinations",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """
    Keep public network access out of the default test run.
    """
    if config.getoption("--live-rsync"):
        return
    skip = pytest.mark.skip(reason="Use --live-rsync to enable public-daemon checks")
    for item in items:
        if item.get_closest_marker("live_rsync"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def cached_transcripts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """
    Expand pinned XML fixtures without consulting the downloader or local cache.
    """
    destination = tmp_path_factory.mktemp("pinned-transcripts")
    for fixture in (Path(__file__).parent / "fixtures/transcripts").glob("*.xml.gz"):
        (destination / fixture.stem).write_bytes(gzip.decompress(fixture.read_bytes()))
    return destination
