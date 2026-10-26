from __future__ import annotations

import hashlib
import os
import shutil
import socket
import stat
import struct
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from parl_motion_detector.rsync import (
    RemoteEntry,
    RsyncConnection,
    RsyncDaemonClient,
    RsyncError,
    RsyncStream,
)


@pytest.mark.parametrize(
    "failure",
    ["", "checksum", "size", "truncated", "basis", "completion", "statistics"],
)
def test_transfer_verification_and_atomic_save(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    """
    Verify real transfer framing and preserve cached files on failed transfers.
    """
    content = b"<publicwhip>transcript</publicwhip>"
    digest = hashlib.md5(content).digest()
    token = -1 if failure == "basis" else len(content)
    payload = (
        b"\x01"
        + struct.pack("<Hiiii", 1 << 15, 0, 0, 0, 0)
        + struct.pack("<i", token)
        + content
        + struct.pack("<i", 0)
        + (bytes(16) if failure == "checksum" else digest)
        + b"\x00\x00"
        + (b"\x01" if failure == "completion" else b"\x00")
        + b"\x00\xff\xff" * 5
        + b"\x00"
    )
    if failure == "statistics":
        payload = payload[:-1]
    if failure == "truncated":
        payload = payload[:25]
    receiver, sender = socket.socketpair()
    sender.sendall(struct.pack("<I", (7 << 24) | len(payload)) + payload)
    sender.shutdown(socket.SHUT_WR)
    stream = RsyncStream(receiver, multiplex=True)
    client = RsyncDaemonClient("unused", "parldata")
    entry = RemoteEntry(
        "transcript.xml", len(content) + (failure == "size"), 1234, stat.S_IFREG
    )
    monkeypatch.setattr(client, "connect", lambda args: RsyncConnection(stream, 0))
    monkeypatch.setattr(client, "recv_flist", lambda stream: [entry])
    destination = tmp_path / "transcript.xml"
    destination.write_bytes(b"cached")
    try:
        if failure:
            with pytest.raises((RsyncError, EOFError)):
                client.fetch("transcript.xml", destination)
            assert destination.read_bytes() == b"cached"
        else:
            assert client.fetch("transcript.xml", destination) == entry
            assert destination.read_bytes() == content
            assert destination.stat().st_mtime == 1234
        assert not list(tmp_path.glob("*.part"))
        assert receiver.fileno() == -1
    finally:
        sender.close()


def test_handshake_failure_closes_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Release sockets even when the daemon greeting cannot be parsed.
    """
    receiver, sender = socket.socketpair()
    sender.sendall(b"invalid greeting\n")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: receiver)
    try:
        with pytest.raises(RsyncError, match="greeting"):
            RsyncDaemonClient("unused", "parldata").connect([])
        assert receiver.fileno() == -1
    finally:
        sender.close()


@dataclass
class Daemon:
    """
    A local interoperability server and its fixture directory.
    """

    root: Path
    client: RsyncDaemonClient
    port: int


@pytest.fixture(params=[0, 60], ids=["no-timeout", "server-timeout"])
def daemon(tmp_path: Path, request: pytest.FixtureRequest) -> Iterator[Daemon]:
    """
    Run the installed rsync binary as a black-box, read-only local daemon.
    """
    executable = shutil.which("rsync")
    if executable is None:
        pytest.skip("rsync executable required for interoperability tests")
    root = tmp_path / "module"
    root.mkdir()
    (root / "empty-directory").mkdir()
    (root / "nested").mkdir()
    fixtures = [
        ("empty", b""),
        ("one.txt", b"one"),
        ("nested/binary", bytes(range(256))),
        ("large", bytes(range(256)) * 36865),
        ("a space.txt", b"space"),
        ("caf\u00e9.txt", b"unicode"),
        ("x" * 255, b"long"),
        ("nested/" + "n" * 100 + "/" + "y" * 220, b"long path"),
    ]
    for name, content in fixtures:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        os.utime(file, (1_700_000_000, 1_700_000_000))
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    config = tmp_path / "rsyncd.conf"
    config.write_text(
        f"use chroot = no\nuid = {os.getuid()}\ngid = {os.getgid()}\n"
        f"timeout = {request.param}\n"
        f"[fixture]\npath = {root}\nread only = yes\n"
        f"[private]\npath = {root}\nauth users = tester\n"
    )

    process = subprocess.Popen(
        [
            executable,
            "--daemon",
            "--no-detach",
            f"--config={config}",
            "--address=127.0.0.1",
            f"--port={port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail(f"Daemon failed: {process.communicate()[1]}")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.01)
        else:
            pytest.fail("Daemon failed to start")
        yield Daemon(
            root, RsyncDaemonClient("127.0.0.1", "fixture", port=port, timeout=5), port
        )
    finally:
        process.terminate()
        process.communicate(timeout=5)


def test_daemon_recursive_listing_and_fetch(daemon: Daemon, tmp_path: Path) -> None:
    """
    Compare complete bytes and metadata across all supported fixture types.
    """
    entries = daemon.client.list()
    files = [entry for entry in entries if entry.is_file]
    assert {entry.path for entry in files} == {
        str(path.relative_to(daemon.root))
        for path in daemon.root.rglob("*")
        if path.is_file()
    }
    assert any(entry.path == "empty-directory" and entry.is_dir for entry in entries)
    for entry in files:
        assert entry.size == (daemon.root / entry.path).stat().st_size
        assert entry.mtime == 1_700_000_000
        destination = tmp_path / "download" / entry.name
        fetched = daemon.client.fetch(entry.path, destination)
        assert fetched == RemoteEntry(entry.name, entry.size, entry.mtime, entry.mode)
        assert destination.read_bytes() == (daemon.root / entry.path).read_bytes()
    assert daemon.client.list("empty-directory/")[0].is_dir
    assert [entry.name for entry in daemon.client.list("*.txt")] == [
        "a space.txt",
        "caf\u00e9.txt",
        "one.txt",
    ]


def test_daemon_errors(daemon: Daemon, tmp_path: Path) -> None:
    """
    Fail explicitly for unavailable modules, paths, authentication and directories.
    """
    with pytest.raises(RsyncError, match="No such file") as missing:
        daemon.client.fetch("missing", tmp_path / "missing")
    assert isinstance(missing.value, FileNotFoundError)
    with pytest.raises(RsyncError, match="Unknown module"):
        RsyncDaemonClient("127.0.0.1", "missing", port=daemon.port).list()
    with pytest.raises(RsyncError, match="authentication"):
        RsyncDaemonClient("127.0.0.1", "private", port=daemon.port).list()
    with pytest.raises(RsyncError, match="exactly one"):
        daemon.client.fetch("empty-directory", tmp_path / "directory")
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "one\n--option", "a/../b", "a\x00b"]
)
def test_invalid_paths(path: str) -> None:
    """
    Reject path traversal and daemon argument injection before networking.
    """
    with pytest.raises(ValueError):
        RsyncDaemonClient("unused", "fixture").list(path)


@pytest.mark.parametrize("address", ["unused::fixture", "rsync://unused:18730/fixture"])
def test_daemon_addresses(address: str) -> None:
    """
    Accept daemon address conventions without an executable dependency.
    """
    client = RsyncDaemonClient(address)
    assert client.host == "unused"
    assert client.module == "fixture"
    assert client.port == (18730 if address.startswith("rsync://") else 873)


def test_truncated_multiplex_frame() -> None:
    """
    Never hide EOF in the middle of a multiplex payload.
    """
    receiver, sender = socket.socketpair()
    sender.sendall(struct.pack("<I", (7 << 24) | 10) + b"abc")
    sender.shutdown(socket.SHUT_WR)
    try:
        with pytest.raises(EOFError):
            RsyncStream(receiver, multiplex=True).read(10)
    finally:
        receiver.close()
        sender.close()


def test_timeout_announcement_between_data_frames() -> None:
    """
    Consume daemon timeout metadata without adding it to the protocol data.
    """
    receiver, sender = socket.socketpair()
    receiver.settimeout(2)
    sender.sendall(
        struct.pack("<I", (7 << 24) | 2)
        + b"ab"
        + struct.pack("<II", (40 << 24) | 4, 60)
        + struct.pack("<I", (7 << 24) | 2)
        + b"cd"
    )
    try:
        assert RsyncStream(receiver, multiplex=True).read(4) == b"abcd"
        assert receiver.gettimeout() == 2
    finally:
        receiver.close()
        sender.close()


@pytest.mark.parametrize("payload", [b"", b"x", bytes(5)])
def test_invalid_timeout_announcement(payload: bytes) -> None:
    """
    Reject timeout control frames whose length is not four bytes.
    """
    receiver, sender = socket.socketpair()
    sender.sendall(struct.pack("<I", (40 << 24) | len(payload)) + payload)
    sender.shutdown(socket.SHUT_WR)
    try:
        with pytest.raises(RsyncError, match="I/O-timeout message length"):
            RsyncStream(receiver, multiplex=True).read(1)
    finally:
        receiver.close()
        sender.close()


def test_truncated_timeout_announcement() -> None:
    """
    Treat a truncated timeout payload as a failed connection.
    """
    receiver, sender = socket.socketpair()
    sender.sendall(struct.pack("<I", (40 << 24) | 4) + bytes(2))
    sender.shutdown(socket.SHUT_WR)
    try:
        with pytest.raises(EOFError):
            RsyncStream(receiver, multiplex=True).read(1)
    finally:
        receiver.close()
        sender.close()


def test_unknown_multiplex_message() -> None:
    """
    Continue rejecting unknown control messages rather than silently ignoring them.
    """
    receiver, sender = socket.socketpair()
    sender.sendall(struct.pack("<I", 255 << 24))
    sender.shutdown(socket.SHUT_WR)
    try:
        with pytest.raises(RsyncError, match="Unsupported multiplex message 255"):
            RsyncStream(receiver, multiplex=True).read(1)
    finally:
        receiver.close()
        sender.close()


@pytest.mark.parametrize("separate_frames", [False, True])
def test_completion_statistics_alignment(separate_frames: bool) -> None:
    """
    Read all three phase markers before decoding statistics, across frame layouts.

    Counts with high low-order bytes expose the previous one-byte misalignment;
    assert the entire response is consumed rather than leaving the final marker.
    """
    receiver, sender = socket.socketpair()
    receiver.settimeout(1)
    sender.settimeout(1)
    statistics = b"".join(
        bytes([value >> 16]) + (value & 0xFFFF).to_bytes(2, "little")
        for value in [24, 110, 65535, 1, 0]
    )
    parts = [b"\0", b"\0", b"\0", statistics + b"\0"]
    if not separate_frames:
        parts = [b"".join(parts)]
    sender.sendall(
        b"".join(struct.pack("<I", (7 << 24) | len(part)) + part for part in parts)
    )
    sender.shutdown(socket.SHUT_WR)
    stream = RsyncStream(receiver, multiplex=True)
    try:
        RsyncDaemonClient("unused", "fixture").finish_transfer(stream)
        assert stream.remaining == 0
        assert receiver.recv(1) == b""
        expected = b"".join(
            struct.pack("<I", (7 << 24) | len(part)) + part
            for part in [b"\0", b"\0\0", b"\0"]
        )
        assert sender.recv(len(expected)) == expected
    finally:
        receiver.close()
        sender.close()


class FragmentedSocket(socket.socket):
    """
    Force short reads even when the operating system has buffered a full frame.
    """

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        """
        Expose at most three bytes of a daemon response per socket read.
        """
        return super().recv(min(bufsize, 3), flags)


def test_fragmented_daemon_session(
    daemon: Daemon, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Exercise greeting, listing, literals, checksum and completion with short reads.
    """
    create_connection = socket.create_connection

    def fragmented_connection(*args: Any, **kwargs: Any) -> FragmentedSocket:
        """
        Retain the configured timeout while wrapping the real connected socket.
        """
        connected = create_connection(*args, **kwargs)
        timeout = connected.gettimeout()
        fragmented = FragmentedSocket(fileno=connected.detach())
        fragmented.settimeout(timeout)
        return fragmented

    monkeypatch.setattr(socket, "create_connection", fragmented_connection)
    assert daemon.client.list("one.txt")[0].size == 3
    destination = tmp_path / "fragmented.txt"
    daemon.client.fetch("one.txt", destination)
    assert destination.read_bytes() == b"one"


class TransferPart(NamedTuple):
    """
    Name a captured transfer boundary for interruption checks.
    """

    name: str
    data: bytes


@pytest.mark.parametrize(
    "stage",
    [
        "frame header",
        "file index",
        "transfer flags",
        "basis header",
        "literal token",
        "literal data",
        "end token",
        "checksum",
        "first completion marker",
        "second completion marker",
        "statistics phase marker",
        "transfer statistics",
        "daemon completion",
    ],
)
def test_interruption_at_transfer_stage(
    stage: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Preserve cached bytes and report context for EOF at each transfer boundary.
    """
    content = b"one"
    parts = [
        TransferPart("file index", b"\x01"),
        TransferPart("transfer flags", struct.pack("<H", 0x8000)),
        TransferPart("basis header", bytes(16)),
        TransferPart("literal token", struct.pack("<i", len(content))),
        TransferPart("literal data", content),
        TransferPart("end token", bytes(4)),
        TransferPart("checksum", hashlib.md5(content).digest()),
        TransferPart("first completion marker", b"\0"),
        TransferPart("second completion marker", b"\0"),
        TransferPart("statistics phase marker", b"\0"),
        TransferPart("transfer statistics", b"\0\xff\xff" * 5),
        TransferPart("daemon completion", b"\0"),
    ]
    header = struct.pack("<I", (7 << 24) | sum(len(part.data) for part in parts))
    truncated = bytearray(header)
    if stage == "frame header":
        truncated = truncated[:2]
    else:
        for part in parts:
            if part.name == stage:
                truncated.extend(part.data[:-1])
                break
            truncated.extend(part.data)
    receiver, sender = socket.socketpair()
    receiver.settimeout(1)
    sender.sendall(truncated)
    sender.shutdown(socket.SHUT_WR)
    stream = RsyncStream(receiver, multiplex=True)
    client = RsyncDaemonClient("unused", "fixture")
    monkeypatch.setattr(client, "connect", lambda args: RsyncConnection(stream, 0))
    monkeypatch.setattr(
        client,
        "recv_flist",
        lambda stream: [RemoteEntry("one.txt", 3, 0, stat.S_IFREG)],
    )
    destination = tmp_path / "one.txt"
    destination.write_bytes(b"cached")
    try:
        with pytest.raises(EOFError, match="fetch unused::fixture/one.txt") as failure:
            client.fetch("one.txt", destination)
        if stage in {
            "checksum",
            "first completion marker",
            "second completion marker",
            "statistics phase marker",
            "transfer statistics",
            "daemon completion",
        }:
            assert stage in str(failure.value)
        assert failure.value.__cause__ is not None
        assert destination.read_bytes() == b"cached"
        assert not list(tmp_path.glob("*.part"))
        assert receiver.fileno() == -1
    finally:
        sender.close()


@pytest.mark.parametrize("stage", ["greeting", "module", "capabilities", "file list"])
def test_interrupted_session_negotiation(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Include connection or listing context for incomplete negotiation and metadata.
    """
    payload = b"@RSYNCD: 31.0\n@RSYNCD: OK\n\x3e" + struct.pack("<I", 1)
    if stage == "greeting":
        payload = b"@RSYNCD:"
    elif stage == "module":
        payload = b"@RSYNCD: 31.0\n"
    elif stage == "capabilities":
        payload = payload[:-2]
    receiver, sender = socket.socketpair()
    receiver.settimeout(1)
    sender.sendall(payload)
    sender.shutdown(socket.SHUT_WR)
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: receiver)
    try:
        with pytest.raises(EOFError, match=stage) as failure:
            RsyncDaemonClient("unused", "fixture").list("one.txt")
        assert "unused::fixture" in str(failure.value)
        assert receiver.fileno() == -1
    finally:
        sender.close()


def test_timeout_reports_operation_and_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Identify a stalled greeting without changing the timeout exception type.
    """
    receiver, sender = socket.socketpair()
    receiver.settimeout(0.01)
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: receiver)
    try:
        with pytest.raises(
            TimeoutError, match="connect unused::fixture.*daemon greeting"
        ) as failure:
            RsyncDaemonClient("unused", "fixture").list("one.txt")
        assert isinstance(failure.value.__cause__, TimeoutError)
        assert receiver.fileno() == -1
    finally:
        sender.close()
