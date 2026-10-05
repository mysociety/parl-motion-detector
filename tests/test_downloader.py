from __future__ import annotations

import datetime
from pathlib import Path

import httpx
import pytest

from parl_motion_detector.downloader import (
    USER_AGENT,
    TranscriptXMl,
    check_urls_exist,
)


def test_transcript_checks_identify_client_and_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Follow redirects and treat only missing transcripts as absent.
    """
    original_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "/found"})
        return httpx.Response(404 if request.url.path == "/missing" else 200)

    def create_client(**kwargs: object) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    assert check_urls_exist(
        ["https://example.com/redirect", "https://example.com/missing"]
    ) == ["https://example.com/redirect"]


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_transcript_checks_surface_http_failures(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """
    Preserve server errors rather than reporting missing files.
    """
    original_client = httpx.AsyncClient

    def create_client(**kwargs: object) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status)),
            **kwargs,
        )

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    with pytest.raises(httpx.HTTPStatusError) as error:
        check_urls_exist(["https://example.com/transcript.xml"])
    assert error.value.response.status_code == status


def test_failed_download_does_not_cache_error_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Never save an HTTP error response as a transcript.
    """
    url = "https://example.com/debates2023-06-27a.xml"
    monkeypatch.setattr(
        "parl_motion_detector.downloader.check_urls_exist", lambda urls: [url]
    )

    def download(request_url: str, **kwargs: object) -> httpx.Response:
        assert kwargs["headers"] == {"User-Agent": USER_AGENT}
        assert kwargs["follow_redirects"] is True
        return httpx.Response(403, request=httpx.Request("GET", request_url))

    monkeypatch.setattr(httpx, "get", download)
    with pytest.raises(httpx.HTTPStatusError):
        TranscriptXMl.UK_COMMONS_DEBATES.download_for_date(
            datetime.date(2023, 6, 27), download_path=tmp_path
        )
    assert not list(tmp_path.rglob("*.xml"))


@pytest.mark.parametrize("available", [True, False])
def test_transcript_discovery_continues_after_candidate_503(
    monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    """
    Select a lettered version despite a 503, preserving errors if none exist.
    """
    original_client = httpx.AsyncClient
    base_url = "https://example.com/debates2024-04-22"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("22.xml"):
            return httpx.Response(503)
        if available and request.url.path.endswith("22a.xml"):
            return httpx.Response(200)
        return httpx.Response(404)

    def create_client(**kwargs: object) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    urls = [f"{base_url}{letter}.xml" for letter in ("", "a", "b")]
    if available:
        assert check_urls_exist(urls) == [f"{base_url}a.xml"]
    else:
        with pytest.raises(httpx.HTTPStatusError) as error:
            check_urls_exist(urls)
        assert error.value.response.status_code == 503
