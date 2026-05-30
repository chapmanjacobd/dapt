#!/usr/bin/env python3
"""Minimal APT acquire method for dapt+http and dapt+https."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CAPABILITIES = """100 Capabilities
Version: 1.0
Single-Instance: true

"""

HASH_FIELDS = [
    ("Expected-SHA512", "sha-512", "sha512", "SHA512-Hash"),
    ("Expected-SHA256", "sha-256", "sha256", "SHA256-Hash"),
    ("Expected-SHA1", "sha-1", "sha1", "SHA1-Hash"),
    ("Expected-MD5Sum", "md5", "md5", "MD5Sum-Hash"),
]


class TransportError(RuntimeError):
    """Raised when the transport cannot satisfy a fetch."""

    def __init__(self, message: str, *, transient: bool = False, reason: str = "") -> None:
        super().__init__(message)
        self.transient = transient
        self.reason = reason


class AptMethod:
    def __init__(self) -> None:
        sys.stdout.write(CAPABILITIES)
        sys.stdout.flush()

    def emit(self, header: str, fields: dict[str, str | None]) -> None:
        sys.stdout.write(header + "\n")
        for key, value in fields.items():
            if value is None or value == "":
                continue
            sys.stdout.write(f"{key}: {value}\n")
        sys.stdout.write("\n")
        sys.stdout.flush()

    def status(self, **kwargs: str | None) -> None:
        self.emit("102 Status", kwargs)

    def uri_start(self, fields: dict[str, str | None]) -> None:
        self.emit("200 URI Start", fields)

    def uri_done(self, fields: dict[str, str | None]) -> None:
        self.emit("201 URI Done", fields)

    def uri_failure(self, fields: dict[str, str | None]) -> None:
        self.emit("400 URI Failure", fields)

    def read_message(self) -> dict[str, str] | None:
        while True:
            line = sys.stdin.readline()
            if line == "":
                return None
            if line != "\n":
                break

        number, text = line.split(" ", 1)
        message = {"_number": int(number), "_text": text.strip()}
        while True:
            line = sys.stdin.readline()
            if line == "":
                return message
            if line == "\n":
                return message
            key, value = line.split(":", 1)
            message[key] = value.strip()

    def run(self) -> int:
        while True:
            message = self.read_message()
            if message is None:
                return 0
            if message["_number"] == 600:
                self.fetch(message)

    def fetch(self, message: dict[str, str]) -> None:
        raise NotImplementedError


class DaptAcquireMethod(AptMethod):
    sidecar_suffixes = [".meta4", ".metalink", ".torrent"]

    def fetch(self, message: dict[str, str]) -> None:
        dapt_uri = message.get("URI", "")
        destination = message.get("Filename", "")
        if not dapt_uri or not destination:
            self.uri_failure(
                {
                    "URI": dapt_uri,
                    "Message": "APT did not provide URI and Filename",
                    "FailReason": "GeneralFailure",
                }
            )
            return

        try:
            self.fetch_one(message)
        except TransportError as exc:
            fields = {"URI": dapt_uri, "Message": str(exc)}
            if exc.reason:
                fields["FailReason"] = exc.reason
            if exc.transient:
                fields["Transient-Failure"] = "true"
            self.uri_failure(fields)

    def fetch_one(self, message: dict[str, str]) -> None:
        dapt_uri = message["URI"]
        destination = Path(message["Filename"])
        real_uri = to_real_uri(dapt_uri)
        destination.parent.mkdir(parents=True, exist_ok=True)

        size_hint = message.get("Expected-Checksum-FileSize") or message.get("Size")
        self.uri_start({"URI": dapt_uri, "Size": size_hint})

        with tempfile.TemporaryDirectory(prefix="dapt-apt-method-") as tmpdir:
            tempdir = Path(tmpdir)
            checksum = expected_checksum(message)

            self.status(URI=dapt_uri, Message="Selecting download strategy")
            if is_package_uri(real_uri):
                mode = self.download_package(dapt_uri, real_uri, tempdir, checksum)
            else:
                self.status(URI=dapt_uri, Message="Fetching metadata directly")
                download_with_aria2(real_uri, real_uri, tempdir, checksum, "direct")
                mode = "direct"

            downloaded = tempdir / target_name(real_uri)
            if not downloaded.exists():
                raise TransportError(
                    f"aria2c completed but did not leave {downloaded.name}",
                    reason="GeneralFailure",
                )
            verify_expected_checksum(downloaded, checksum)
            shutil.move(str(downloaded), str(destination))

        hashes = digest_file(destination)
        self.uri_done(
            {
                "URI": dapt_uri,
                "Filename": str(destination),
                "Size": str(destination.stat().st_size),
                "MD5-Hash": hashes["md5"],
                "MD5Sum-Hash": hashes["md5"],
                "SHA256-Hash": hashes["sha256"],
                "Alt-URI": real_uri if mode != "direct" else None,
            }
        )

    def candidate_uris(self, real_uri: str) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        for suffix in self.sidecar_suffixes:
            sidecar_uri = real_uri + suffix
            if sidecar_exists(sidecar_uri):
                candidates.append((sidecar_uri, suffix.lstrip(".")))
        candidates.append((real_uri, "direct"))
        return candidates

    def download_package(
        self,
        dapt_uri: str,
        real_uri: str,
        tempdir: Path,
        checksum: tuple[str, str, str] | None,
    ) -> str:
        last_error: TransportError | None = None
        for request_uri, mode in self.candidate_uris(real_uri):
            self.status(URI=dapt_uri, Message=f"Fetching package via {mode}")
            try:
                download_with_aria2(request_uri, real_uri, tempdir, checksum, mode)
                return mode
            except TransportError as exc:
                last_error = exc
                if mode == "direct":
                    break
                self.status(URI=dapt_uri, Message=f"Fetch via {mode} failed; trying next source")
        assert last_error is not None
        raise last_error


def to_real_uri(dapt_uri: str) -> str:
    if dapt_uri.startswith("dapt+http://"):
        return "http://" + dapt_uri[len("dapt+http://") :]
    if dapt_uri.startswith("dapt+https://"):
        return "https://" + dapt_uri[len("dapt+https://") :]
    raise TransportError(
        f"unsupported dapt URI scheme in {dapt_uri}",
        reason="UnsupportedURI",
    )


def is_package_uri(real_uri: str) -> bool:
    return urlsplit(real_uri).path.endswith(".deb")


def target_name(real_uri: str) -> str:
    path = Path(urlsplit(real_uri).path)
    name = path.name
    if not name:
        raise TransportError(f"cannot infer filename from URI {real_uri}", reason="MalformedURI")
    return name


def expected_checksum(message: dict[str, str]) -> tuple[str, str, str] | None:
    for field, aria_name, hashlib_name, _done_field in HASH_FIELDS:
        value = message.get(field)
        if value:
            return aria_name, hashlib_name, value
    return None


def sidecar_exists(sidecar_uri: str) -> bool:
    try:
        with urlopen(Request(sidecar_uri, method="HEAD"), timeout=5):
            return True
    except HTTPError as exc:
        if exc.code == 404:
            return False
        if exc.code in {405, 501}:
            try:
                with urlopen(Request(sidecar_uri), timeout=5):
                    return True
            except HTTPError as get_exc:
                if get_exc.code == 404:
                    return False
                return False
            except URLError as get_exc:
                raise TransportError(
                    f"sidecar probe failed for {sidecar_uri}: {get_exc.reason}",
                    transient=True,
                    reason="ConnectionRefused",
                ) from get_exc
        return False
    except URLError as exc:
        raise TransportError(
            f"sidecar probe failed for {sidecar_uri}: {exc.reason}",
            transient=True,
            reason="ConnectionRefused",
        ) from exc


def download_with_aria2(
    request_uri: str,
    real_uri: str,
    tempdir: Path,
    checksum: tuple[str, str, str] | None,
    mode: str,
) -> None:
    command = [
        "aria2c",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--connect-timeout=5",
        "--continue=true",
        "--dir",
        str(tempdir),
        "--file-allocation=none",
        "--max-tries=1",
        "--max-connection-per-server=4",
        "--min-split-size=1M",
        "--no-conf=true",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--remote-time=true",
        "--timeout=20",
        request_uri,
    ]

    if checksum is not None and mode == "direct":
        algorithm, _hashlib_name, value = checksum
        command.extend(["--check-integrity=true", f"--checksum={algorithm}={value}"])
    if mode == "torrent":
        command.extend(
            [
                "--follow-torrent=mem",
                "--bt-enable-lpd=true",
                "--bt-stop-timeout=10",
                "--seed-time=0",
            ]
        )
    elif mode in {"meta4", "metalink"}:
        command.extend(["--follow-metalink=mem"])
        preferred_protocol = preferred_http_protocol(real_uri)
        if preferred_protocol:
            command.append(f"--metalink-preferred-protocol={preferred_protocol}")
    elif mode == "direct":
        command.extend(["--out", target_name(real_uri)])
    else:
        raise TransportError(f"unsupported download mode {mode}", reason="GeneralFailure")

    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode == 0:
        return

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    detail = stderr or stdout or "aria2c failed"
    raise TransportError(
        detail,
        transient=completed.returncode in {2, 5, 6, 7},
        reason="GeneralFailure",
    )


def verify_expected_checksum(path: Path, checksum: tuple[str, str, str] | None) -> None:
    if checksum is None:
        return
    _aria_name, hashlib_name, expected_value = checksum
    hasher = hashlib.new(hashlib_name)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != expected_value:
        raise TransportError(
            f"downloaded file checksum mismatch for {path.name}",
            reason="HashSumMismatch",
        )


def preferred_http_protocol(uri: str) -> str | None:
    scheme = urlsplit(uri).scheme
    if scheme in {"http", "https"}:
        return scheme
    return None


def digest_file(path: Path) -> dict[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            md5.update(chunk)
            sha256.update(chunk)
    return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}


if __name__ == "__main__":
    try:
        sys.exit(DaptAcquireMethod().run())
    except KeyboardInterrupt:
        sys.exit(130)
