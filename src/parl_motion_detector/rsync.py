"""
Implement a minimal read-only rsync daemon client for protocol 31.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import stat
import struct
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from urllib.parse import urlsplit


class RsyncError(OSError):
    """
    The daemon rejected a request or sent an unsupported/invalid response.
    """


class RsyncMissingPathError(RsyncError, FileNotFoundError):
    """
    The daemon reports a missing source path or an unmatched wildcard.

    Also a FileNotFoundError so date-processing callers can skip non-sitting days
    without treating permission, transport or protocol failures as missing data.
    """


@dataclass(frozen=True)
class RemoteEntry:
    """
    Metadata from a protocol-31 file list; paths are relative to the request.
    """

    path: str
    size: int
    mtime: int
    mode: int

    @property
    def name(self) -> str:
        """
        Return the final component of the request-relative remote path.
        """
        return PurePosixPath(self.path).name

    @property
    def is_file(self) -> bool:
        """
        Indicate whether the remote mode identifies a regular file.
        """
        return stat.S_ISREG(self.mode)

    @property
    def is_dir(self) -> bool:
        """
        Indicate whether the remote mode identifies a directory.
        """
        return stat.S_ISDIR(self.mode)


class RsyncStream:
    """
    Bounded socket reads and rsync multiplex frames, independent of sessions.
    """

    def __init__(self, sock: socket.socket, *, multiplex: bool = False) -> None:
        """
        Wrap a socket, optionally enabling rsync multiplex framing immediately.

        Daemon negotiation starts with raw bytes and enables framing afterward.
        The caller must close the stream when its session ends.
        """
        self.sock = sock
        self.multiplex = multiplex
        self.remaining = 0
        self.stage = "receiving protocol data"

    @contextmanager
    def operation(self, description: str) -> Iterator[None]:
        """
        Attach the remote operation and current protocol stage to failures.

        Preserve exception types so callers can still distinguish daemon errors,
        incomplete connections and timeouts. Keep the original error as the cause.
        """
        try:
            yield
        except (RsyncError, EOFError, TimeoutError) as exc:
            raise type(exc)(f"{description} ({self.stage}): {exc}") from exc

    def close(self) -> None:
        """
        Close the underlying socket and release the daemon connection.
        """
        self.sock.close()

    def read_raw(self, length: int) -> bytes:
        """
        Read exactly length socket bytes without interpreting multiplex headers.

        Reads are limited to 1 MiB. Raise EOFError if the connection ends early,
        or RsyncError if the requested length exceeds the transport limit.
        """
        if not 0 <= length <= 1024 * 1024:
            raise RsyncError("Read exceeds transport limit")
        result = bytearray()
        while len(result) < length:
            data = self.sock.recv(length - len(result))
            if not data:
                raise EOFError("Truncated rsync connection")
            result.extend(data)
        return bytes(result)

    def readline(self) -> bytes:
        """
        Read a raw daemon greeting or response, including its trailing newline.

        Reject lines longer than 8 KiB and propagate EOF for incomplete lines.
        """
        result = bytearray()
        for _ in range(8192):
            result.extend(self.read_raw(1))
            if result[-1] == 10:
                return bytes(result)
        raise RsyncError("Daemon line exceeds limit")

    def read(self, length: int) -> bytes:
        """
        Read exactly length protocol bytes across multiplex data frames.

        In multiplex mode, consume informational messages and server timeout
        announcements, retaining the socket timeout chosen by the caller. Raise RsyncError
        for daemon errors, unsupported tags or excessive framing. Before framing
        is enabled, read directly from the socket. Incomplete reads raise EOFError.
        """
        if not self.multiplex:
            return self.read_raw(length)
        if not 0 <= length <= 1024 * 1024:
            raise RsyncError("Read exceeds transport limit")
        result = bytearray()
        frames = 0
        while len(result) < length:
            if not self.remaining:
                frames += 1
                if frames > 10000:
                    raise RsyncError("Too many empty/control frames")
                header = int.from_bytes(self.read_raw(4), "little")
                size, tag = header & 0xFFFFFF, header >> 24
                if size > 1024 * 1024:
                    raise RsyncError("Multiplex frame exceeds limit")
                if tag != 7:
                    message = self.read_raw(size)
                    if tag == 40:
                        # A daemon with timeout configured announces four-byte seconds.
                        if size != 4:
                            raise RsyncError(
                                "Invalid daemon I/O-timeout message length"
                            )
                        continue
                    if tag in (8, 10, 11, 12, 13):
                        text = message.decode("utf-8", "replace").strip()
                        if (
                            tag == 8
                            and text.endswith("No such file or directory (2)")
                            and ("link_stat " in text or "change_dir " in text)
                        ):
                            raise RsyncMissingPathError(text)
                        raise RsyncError(text)
                    if tag != 9:
                        raise RsyncError(f"Unsupported multiplex message {tag}")
                    continue
                self.remaining = size
                if not size:
                    continue
            count = min(length - len(result), self.remaining)
            result.extend(self.read_raw(count))
            self.remaining -= count
        return bytes(result)

    def write(self, data: bytes) -> None:
        """
        Send all bytes, adding a data-frame header when multiplexing is enabled.

        Multiplex payloads are limited to 1 MiB. Socket failures propagate.
        """
        if self.multiplex:
            if len(data) > 1024 * 1024:
                raise RsyncError("Write exceeds transport limit")
            data = struct.pack("<I", (7 << 24) | len(data)) + data
        self.sock.sendall(data)

    def integer(self) -> int:
        """
        Read a signed, four-byte little-endian protocol integer.
        """
        return struct.unpack("<i", self.read(4))[0]

    def unsigned_short(self) -> int:
        """
        Read an unsigned, two-byte little-endian value, such as transfer flags.
        """
        return int.from_bytes(self.read(2), "little")

    def variable_integer(self, minimum: int = 1) -> int:
        """
        Decode a prefix length followed by little-endian low-order bytes.

        The minimum includes the prefix byte: use 1 for ordinary variable
        integers, 3 for file sizes/statistics, and 4 for modification seconds.
        Reject malformed encodings and values above the signed 64-bit range.
        Derived from controlled captures with known sizes and timestamps.
        """
        prefix = self.read(1)[0]
        extra = 0
        marker = 0x80
        while prefix & marker:
            extra += 1
            marker >>= 1
        length = minimum - 1 + extra
        if length > 8 or not marker:
            raise RsyncError("Invalid variable integer")
        high = prefix & (marker - 1)
        value = int.from_bytes(self.read(length), "little") | (high << (length * 8))
        if value > 0x7FFFFFFFFFFFFFFF:
            raise RsyncError("Integer exceeds supported range")
        return value


class RsyncConnection(NamedTuple):
    """
    Carry a negotiated stream and the daemon's unsigned checksum seed.

    The selected whole-file MD5 digest is unseeded; retain the seed as session
    metadata rather than applying it to the downloaded contents.
    """

    stream: RsyncStream
    seed: int


class RsyncDaemonClient:
    """
    Anonymous, read-only protocol-31 daemon client using fresh TCP sessions.

    Only regular files/directories, recursive lists and whole-file MD5 transfers
    are supported. See docs/rsync.md for interoperability evidence and limits.
    """

    def __init__(
        self,
        host: str,
        module: str | None = None,
        *,
        port: int = 873,
        timeout: float = 30,
        max_entries: int = 1_000_000,
        max_file_size: int = 1024**4,
    ) -> None:
        """
        Configure a daemon address and resource limits without opening a socket.

        Supply host and module separately, or omit module and use host::module
        or rsync://host:port/module. Paths belong in list/fetch requests. Timeout
        applies to individual socket operations; max_file_size is measured in
        bytes and max_entries bounds the number of decoded file-list entries.
        Invalid addresses or resource limits raise ValueError.
        """
        if module is None:
            if host.startswith("rsync://"):
                parsed = urlsplit(host)
                if (
                    parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError("Only anonymous daemon URLs are supported")
                module = parsed.path.strip("/")
                port = parsed.port or port
                host = parsed.hostname or ""
            elif "::" in host:
                host, module = host.split("::", 1)
            else:
                raise ValueError(
                    "Specify a module or host::module / rsync://host/module"
                )
        if not host or not re.fullmatch(r"[A-Za-z0-9_.-]+", module):
            raise ValueError("Invalid daemon host/module")
        if timeout <= 0 or max_entries <= 0 or max_file_size < 0:
            raise ValueError("Invalid timeout or resource limits")
        self.host = host
        self.module = module
        self.port = port
        self.timeout = timeout
        self.max_entries = max_entries
        self.max_file_size = max_file_size

    def validate_path(self, path: str, *, exact: bool = False) -> str:
        """
        Return a safe module-relative path unchanged, or raise ValueError.

        Reject absolute paths, parent traversal, control characters and paths
        exceeding 4,096 encoded bytes. Exact fetch requests also reject empty
        paths and wildcard metacharacters; listing requests permit both.
        """
        if (
            len(os.fsencode(path)) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or path.startswith("/")
            or ".." in path.split("/")
            or (exact and (not path or any(char in path for char in "*?[]")))
        ):
            raise ValueError("Expected a safe module-relative path")
        return path

    def connect(self, args: list[str]) -> RsyncConnection:
        """
        Negotiate a fresh protocol-31 session and send operation arguments.

        Arguments extend the fixed read-only sender options. Select the module,
        require the tested capabilities, enable multiplexing and send an empty
        filter list. The caller owns the returned stream. Any negotiation failure
        closes the socket; authentication and unsupported responses raise RsyncError.
        """
        stream = RsyncStream(
            socket.create_connection((self.host, self.port), timeout=self.timeout)
        )
        try:
            with stream.operation(f"connect {self.host}::{self.module}"):
                stream.stage = "reading daemon greeting"
                greeting = stream.readline()
                match = re.match(rb"@RSYNCD: ([0-9]+)\.[0-9]+(?: |\n)", greeting)
                if match is None:
                    raise RsyncError("Invalid daemon greeting")
                if int(match[1]) < 31:
                    raise RsyncError("Daemon must support protocol 31")
                stream.stage = "selecting daemon module"
                stream.write(b"@RSYNCD: 31.0\n" + self.module.encode() + b"\n")
                for _ in range(100):
                    line = stream.readline()
                    if line == b"@RSYNCD: OK\n":
                        break
                    if line.startswith(b"@RSYNCD: AUTHREQD"):
                        raise RsyncError("Daemon authentication is unsupported")
                    if line.startswith((b"@ERROR", b"@RSYNCD:")):
                        raise RsyncError(line.decode("utf-8", "replace").strip())
                else:
                    raise RsyncError("Daemon did not accept module")
                options = [
                    "--server",
                    "--sender",
                    "-rte.LsfxC",
                    "--no-inc-recursive",
                    "--whole-file",
                    "--checksum-choice=md5",
                    "--checksum-seed=1",
                    *args,
                ]
                stream.write(os.fsencode("\0".join(options) + "\0\0"))
                stream.stage = "negotiating capabilities"
                capabilities = stream.read_raw(1)[0]
                if capabilities != 0x3E:
                    raise RsyncError(
                        f"Unsupported daemon capabilities: {capabilities:#x}"
                    )
                seed = struct.unpack("<I", stream.read_raw(4))[0]
                stream.multiplex = True
                # Empty filter list, observed in daemon captures.
                stream.write(bytes(4))
                return RsyncConnection(stream, seed)
        except BaseException:
            stream.close()
            raise

    def recv_flist(self, stream: RsyncStream) -> list[RemoteEntry]:
        """
        Decode the nonincremental file list without owner/group/link metadata.

        Expand shared filename prefixes and cached mode/time values, validate
        paths and resource limits, and return entries sorted by encoded path.
        Modification times retain whole seconds; nanoseconds are validated and
        discarded. Unsupported file types or fields raise RsyncError.
        """
        stream.stage = "receiving file list"
        entries: list[RemoteEntry] = []
        previous = b""
        mtime = mode = 0
        while flags := stream.read(1)[0]:
            if flags & 4:
                flags |= stream.read(1)[0] << 8
            if flags & ~0x20FF:
                raise RsyncError(f"Unsupported file-list flags: {flags:#x}")
            prefix = stream.read(1)[0] if flags & 32 else 0
            suffix = stream.variable_integer() if flags & 64 else stream.read(1)[0]
            if prefix > len(previous) or prefix + suffix > 4096:
                raise RsyncError("Invalid file-list name length")
            name = previous[:prefix] + stream.read(suffix)
            path = os.fsdecode(name)
            try:
                self.validate_path(path)
            except ValueError as exc:
                raise RsyncError("Unsafe remote file-list path") from exc
            if not name or b"\0" in name:
                raise RsyncError("Invalid remote filename")
            size = stream.variable_integer(3)
            if size > self.max_file_size:
                raise RsyncError("Remote entry exceeds file-size limit")
            if not flags & 128:
                mtime = stream.variable_integer(4)
            if flags & 8192:
                if stream.variable_integer() >= 1_000_000_000:
                    raise RsyncError("Invalid modification nanoseconds")
            if not flags & 2:
                mode = int.from_bytes(stream.read(4), "little")
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise RsyncError("Unsupported remote file type")
            entries.append(RemoteEntry(path, size, mtime, mode))
            if len(entries) > self.max_entries:
                raise RsyncError("File list exceeds entry limit")
            previous = name
        return sorted(entries, key=lambda entry: os.fsencode(entry.path))

    def list(self, path: str = "") -> list[RemoteEntry]:
        """
        Recursively list a module-relative path or daemon wildcard pattern.

        An empty path lists the module root. Entry paths are relative to the
        requested source. Complete and close the fresh session before returning;
        daemon failures, including missing-path errors, propagate as RsyncError.
        """
        path = self.validate_path(path)
        connection = self.connect(["--list-only", ".", f"{self.module}/{path}"])
        stream = connection.stream
        try:
            with stream.operation(f"list {self.host}::{self.module}/{path}"):
                entries = self.recv_flist(connection.stream)
                connection.stream.write(b"\0")
                self.finish_transfer(connection.stream)
                return entries
        finally:
            connection.stream.close()

    def fetch(self, path: str, destination: Path | str) -> RemoteEntry:
        """
        Verify full contents before atomically replacing the chosen destination.

        Require one exact regular file and return its request-relative metadata.
        Create destination parents and stream literals to a temporary sibling,
        checking the advertised byte count and unseeded MD5 digest. Complete the
        session and apply the modification time before replacing the destination.
        Failures close the connection, remove the temporary file and preserve any
        existing destination. Basis-file references and malformed transfers raise
        RsyncError; truncated connections raise EOFError.
        """
        path = self.validate_path(path, exact=True)
        destination = Path(destination)
        connection = self.connect([".", f"{self.module}/{path}"])
        stream = connection.stream
        temporary: Path | None = None
        try:
            with stream.operation(f"fetch {self.host}::{self.module}/{path}"):
                entries = self.recv_flist(stream)
                if not entries:
                    raise FileNotFoundError(path)
                if len(entries) != 1 or not entries[0].is_file:
                    raise RsyncError("Fetch requires exactly one regular file")
                entry = entries[0]
                if entry.name != PurePosixPath(path).name:
                    raise RsyncError("Daemon returned a different file")
                stream.stage = "requesting file contents"
                # Index zero is delta-encoded as 1; transfer flag and empty basis header.
                stream.write(
                    b"\x01" + struct.pack("<Hiiii", 0x8000, 0, 0, 0, 0) + b"\0"
                )
                if stream.read(1) != b"\x01":
                    raise RsyncError("Unexpected transfer index")
                flags = stream.unsigned_short()
                if not flags & 0x8000 or flags & ~0xA000:
                    raise RsyncError("Unexpected transfer flags")
                if stream.read(16) != bytes(16):
                    raise RsyncError("Unexpected basis-file checksum header")
                stream.stage = "receiving file contents"
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.md5()
                size = 0
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent,
                    prefix=".rsync-",
                    suffix=".part",
                    delete=False,
                ) as output:
                    temporary = Path(output.name)
                    while token := stream.integer():
                        if token < 0:
                            raise RsyncError("Unexpected basis-file reference")
                        if size + token > entry.size:
                            raise RsyncError("Transfer exceeds advertised size")
                        size += token
                        while token:
                            block = stream.read(min(token, 65536))
                            output.write(block)
                            digest.update(block)
                            token -= len(block)
                    stream.stage = "verifying file checksum"
                    checksum = stream.read(16)
                    if size != entry.size or checksum != digest.digest():
                        raise RsyncError("Transfer size/checksum verification failed")
                    output.flush()
                    os.fsync(output.fileno())
                self.finish_transfer(stream)
                os.utime(temporary, (entry.mtime, entry.mtime))
                os.replace(temporary, destination)
                temporary = None
                return entry
        finally:
            stream.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def finish_transfer(self, stream: RsyncStream) -> None:
        """
        Complete all nonincremental phases and consume daemon statistics.

        Require three phase-completion markers and, for multiplex sessions,
        consume five statistics integers before acknowledging daemon completion.
        Late daemon errors and truncated responses propagate to the caller before
        a downloaded temporary file can replace its destination.
        """
        stream.stage = "reading first completion marker"
        if stream.read(1) != b"\0":
            raise RsyncError("Unexpected transfer phase")
        stream.write(b"\0")
        stream.stage = "reading second completion marker"
        if stream.read(1) != b"\0":
            raise RsyncError("Unexpected final transfer phase")
        if stream.multiplex:
            stream.write(b"\0\0")
            stream.stage = "reading statistics phase marker"
            if stream.read(1) != b"\0":
                raise RsyncError("Unexpected statistics phase")
            stream.stage = "reading transfer statistics"
            for _ in range(5):
                stream.variable_integer(3)
            stream.stage = "reading daemon completion"
            if stream.read(1) != b"\0":
                raise RsyncError("Unexpected daemon completion")
            stream.write(b"\0")
