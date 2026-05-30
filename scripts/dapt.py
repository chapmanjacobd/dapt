#!/usr/bin/env python3
"""DAPT: small helpers for packaging data products into an APT repository."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_REPO_ROOT = Path("repo")
DEFAULT_PRODUCTS_DIR = Path("products")
DEFAULT_BUILD_ROOT = Path(".dapt/build")
REPO_CONFIG_NAME = "dapt-repo.toml"
PRODUCT_MANIFEST_NAME = "product.toml"
PACKAGE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
SOURCE_TYPES = {"local", "remote"}


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"error: {message}")


def run(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        fail(f"required command not found: {command[0]}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        detail = stderr or stdout or "command failed"
        fail(f"{' '.join(command)}: {detail}")
    return completed.stdout


def ensure_package_name(name: str) -> str:
    normalized = name.strip().lower().replace("_", "-")
    if not PACKAGE_NAME_PATTERN.fullmatch(normalized):
        fail(
            "package names must match Debian conventions "
            "(lowercase letters, digits, plus, dot, and hyphen)"
        )
    return normalized


def ensure_version(version: str) -> str:
    if not version.strip():
        fail("version cannot be empty")
    return version.strip()


def ensure_source_type(source_type: str) -> str:
    normalized = source_type.strip().lower()
    if normalized not in SOURCE_TYPES:
        fail(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")
    return normalized


def toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def toml_list(values: Iterable[str]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        fail(f"missing TOML file: {path}")
    except tomllib.TOMLDecodeError as exc:
        fail(f"invalid TOML in {path}: {exc}")


def repo_config_path(repo_root: Path) -> Path:
    return repo_root / REPO_CONFIG_NAME


def product_manifest_path(products_dir: Path, product: str) -> Path:
    return products_dir / product / PRODUCT_MANIFEST_NAME


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_repo_config(path: Path, config: dict) -> None:
    content = "\n".join(
        [
            f"origin = {toml_string(config['origin'])}",
            f"label = {toml_string(config['label'])}",
            f"suite = {toml_string(config['suite'])}",
            f"codename = {toml_string(config['codename'])}",
            f"description = {toml_string(config['description'])}",
            f"components = {toml_list(config['components'])}",
            f"architectures = {toml_list(config['architectures'])}",
            f"sign_with = {toml_string(config['sign_with'])}",
            "",
        ]
    )
    write_text(path, content)


def load_repo_config(repo_root: Path) -> dict:
    config = read_toml(repo_config_path(repo_root))
    return {
        "origin": config.get("origin", "DAPT"),
        "label": config.get("label", "DAPT"),
        "suite": config.get("suite", "stable"),
        "codename": config.get("codename", "stable"),
        "description": config.get("description", "DAPT proof-of-concept repository"),
        "components": [str(value) for value in config.get("components", ["main"])],
        "architectures": [str(value) for value in config.get("architectures", ["amd64", "all"])],
        "sign_with": str(config.get("sign_with", "")),
    }


def write_product_manifest(path: Path, manifest: dict) -> None:
    description = textwrap.dedent(manifest["description"]).strip()
    content = "\n".join(
        [
            f"name = {toml_string(manifest['name'])}",
            f"package = {toml_string(manifest['package'])}",
            f"maintainer = {toml_string(manifest['maintainer'])}",
            f"summary = {toml_string(manifest['summary'])}",
            'description = """',
            description,
            '"""',
            f"section = {toml_string(manifest['section'])}",
            f"priority = {toml_string(manifest['priority'])}",
            f"architecture = {toml_string(manifest['architecture'])}",
            f"install_prefix = {toml_string(manifest['install_prefix'])}",
            f"depends = {toml_list(manifest['depends'])}",
            f"homepage = {toml_string(manifest['homepage'])}",
            f"source_type = {toml_string(manifest['source_type'])}",
            f"remote_urls = {toml_list(manifest['remote_urls'])}",
            f"remote_filename = {toml_string(manifest['remote_filename'])}",
            f"remote_sha256 = {toml_string(manifest['remote_sha256'])}",
            f"remote_torrent_url = {toml_string(manifest['remote_torrent_url'])}",
            f"remote_metalink_url = {toml_string(manifest['remote_metalink_url'])}",
            "",
        ]
    )
    write_text(path, content)


def render_description(summary: str, long_description: str) -> str:
    lines = [f"Description: {summary.strip()}"]
    detail_lines = textwrap.dedent(long_description).strip().splitlines()
    if not detail_lines:
        return "\n".join(lines)
    for line in detail_lines:
        lines.append(" ." if not line.strip() else f" {line.rstrip()}")
    return "\n".join(lines)


def init_repo(args: argparse.Namespace) -> int:
    repo_root = args.repo_root.resolve()
    config = {
        "origin": args.origin,
        "label": args.label,
        "suite": args.suite,
        "codename": args.codename,
        "description": args.description,
        "components": args.components,
        "architectures": args.architectures,
        "sign_with": args.sign_with or "",
    }
    (repo_root / "pool" / "main").mkdir(parents=True, exist_ok=True)
    for architecture in sorted(set(args.architectures)):
        (repo_root / "dists" / args.codename / "main" / f"binary-{architecture}").mkdir(
            parents=True, exist_ok=True
        )
    write_repo_config(repo_config_path(repo_root), config)
    refresh_repo(repo_root, args.sign_with or "")
    print(repo_root)
    return 0


def new_product(args: argparse.Namespace) -> int:
    product = ensure_package_name(args.name)
    product_dir = args.products_dir / product
    if product_dir.exists():
        fail(f"product already exists: {product_dir}")
    source_type = ensure_source_type(args.source_type)
    manifest = {
        "name": product,
        "package": ensure_package_name(args.package or f"dapt-{product}"),
        "maintainer": args.maintainer,
        "summary": args.summary,
        "description": args.description,
        "section": args.section,
        "priority": args.priority,
        "architecture": args.architecture,
        "install_prefix": args.install_prefix,
        "depends": args.depends,
        "homepage": args.homepage,
        "source_type": source_type,
        "remote_urls": args.remote_url,
        "remote_filename": args.remote_filename,
        "remote_sha256": args.remote_sha256,
        "remote_torrent_url": args.remote_torrent_url,
        "remote_metalink_url": args.remote_metalink_url,
    }
    payload_dir = product_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    write_product_manifest(product_dir / PRODUCT_MANIFEST_NAME, manifest)
    if source_type == "remote":
        readme_text = textwrap.dedent(
            f"""\
            This product uses remote sources.

            Optional supplemental files placed here will still be bundled into the package,
            but the primary payload is downloaded by aria2c into:
            {args.install_prefix.rstrip('/')}/{product}/
            """
        )
    else:
        readme_text = textwrap.dedent(
            f"""\
            Drop the versioned payload for {product} into this directory.

            Whatever is placed here will be copied into:
            {args.install_prefix.rstrip('/')}/{product}/
            """
        )
    write_text(payload_dir / "README.txt", readme_text)
    print(product_dir)
    return 0


def load_manifest(products_dir: Path, product: str) -> tuple[Path, dict]:
    product_name = ensure_package_name(product)
    manifest_path = product_manifest_path(products_dir, product_name)
    manifest = read_toml(manifest_path)
    product_dir = manifest_path.parent
    required_fields = ["name", "package", "maintainer", "summary", "description"]
    for field in required_fields:
        if not manifest.get(field):
            fail(f"missing required field {field!r} in {manifest_path}")
    manifest["name"] = ensure_package_name(str(manifest["name"]))
    manifest["package"] = ensure_package_name(str(manifest["package"]))
    manifest["depends"] = [str(value) for value in manifest.get("depends", [])]
    manifest["install_prefix"] = str(manifest.get("install_prefix", "/usr/share/dapt/products"))
    manifest["architecture"] = str(manifest.get("architecture", "all"))
    manifest["section"] = str(manifest.get("section", "data"))
    manifest["priority"] = str(manifest.get("priority", "optional"))
    manifest["homepage"] = str(manifest.get("homepage", ""))
    manifest["source_type"] = ensure_source_type(str(manifest.get("source_type", "local")))
    manifest["remote_urls"] = [str(value) for value in manifest.get("remote_urls", [])]
    manifest["remote_filename"] = str(manifest.get("remote_filename", ""))
    manifest["remote_sha256"] = str(manifest.get("remote_sha256", ""))
    manifest["remote_torrent_url"] = str(manifest.get("remote_torrent_url", ""))
    manifest["remote_metalink_url"] = str(manifest.get("remote_metalink_url", ""))
    if manifest["source_type"] == "remote":
        if not manifest["remote_filename"]:
            fail(f"remote products require remote_filename in {manifest_path}")
        if not (
            manifest["remote_urls"]
            or manifest["remote_torrent_url"]
            or manifest["remote_metalink_url"]
        ):
            fail(
                f"remote products require at least one of remote_urls, "
                f"remote_torrent_url, or remote_metalink_url in {manifest_path}"
            )
    return product_dir, manifest


def copy_payload(payload_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    for entry in payload_dir.iterdir():
        target = destination_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def write_control_file(path: Path, manifest: dict, version: str) -> None:
    depends = list(manifest["depends"])
    if manifest["source_type"] == "remote" and "aria2" not in depends:
        depends.append("aria2")
    lines = [
        f"Package: {manifest['package']}",
        f"Version: {version}",
        f"Section: {manifest['section']}",
        f"Priority: {manifest['priority']}",
        f"Architecture: {manifest['architecture']}",
        f"Maintainer: {manifest['maintainer']}",
    ]
    if depends:
        lines.append(f"Depends: {', '.join(depends)}")
    if manifest["homepage"]:
        lines.append(f"Homepage: {manifest['homepage']}")
    lines.append(render_description(manifest["summary"], manifest["description"]))
    write_text(path, "\n".join(lines) + "\n")


def build_deb(build_tree: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        preferred = subprocess.run(
            ["dpkg-deb", "--build", "--root-owner-group", str(build_tree), str(output_path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        fail("required command not found: dpkg-deb")
    if preferred.returncode == 0:
        return
    if "--root-owner-group" not in (preferred.stderr or ""):
        detail = preferred.stderr.strip() or preferred.stdout.strip() or "dpkg-deb failed"
        fail(detail)
    run(["dpkg-deb", "--build", str(build_tree), str(output_path)])


def write_executable(path: Path, content: str) -> None:
    write_text(path, content)
    path.chmod(0o755)


def render_remote_source_manifest(manifest: dict) -> str:
    lines = [
        f"remote_filename = {toml_string(manifest['remote_filename'])}",
        f"remote_sha256 = {toml_string(manifest['remote_sha256'])}",
        f"remote_urls = {toml_list(manifest['remote_urls'])}",
        f"remote_torrent_url = {toml_string(manifest['remote_torrent_url'])}",
        f"remote_metalink_url = {toml_string(manifest['remote_metalink_url'])}",
        "",
    ]
    return "\n".join(lines)


def create_remote_maintainer_scripts(package_root: Path, manifest: dict, install_dir: Path) -> None:
    remote_file = install_dir / manifest["remote_filename"]
    url_setter = "\n".join(
        f"set -- \"$@\" {shlex.quote(url)}" for url in manifest["remote_urls"]
    )
    postinst = "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            f'install_dir={shlex.quote(install_dir.as_posix())}',
            f'target_file={shlex.quote(remote_file.as_posix())}',
            f'torrent_url={shlex.quote(manifest["remote_torrent_url"])}',
            f'metalink_url={shlex.quote(manifest["remote_metalink_url"])}',
            f'expected_sha256={shlex.quote(manifest["remote_sha256"])}',
            "",
            'if ! command -v aria2c >/dev/null 2>&1; then',
            '  echo "dapt remote packages require aria2c (package: aria2)" >&2',
            "  exit 1",
            "fi",
            "",
            'mkdir -p "$install_dir"',
            "downloaded=0",
            'if [ -n "$torrent_url" ]; then',
            '  if aria2c --allow-overwrite=true --auto-file-renaming=false --bt-enable-lpd=true --check-integrity=true --dir "$install_dir" --follow-torrent=mem --out "$(basename "$target_file")" "$torrent_url"; then',
            "    downloaded=1",
            "  fi",
            "fi",
            "",
            'if [ "$downloaded" -eq 0 ] && [ -n "$metalink_url" ]; then',
            '  if aria2c --allow-overwrite=true --auto-file-renaming=false --check-integrity=true --dir "$install_dir" --follow-metalink=mem --out "$(basename "$target_file")" "$metalink_url"; then',
            "    downloaded=1",
            "  fi",
            "fi",
            "",
            "set --",
            url_setter,
            'if [ "$downloaded" -eq 0 ] && [ "$#" -gt 0 ]; then',
            '  if aria2c --allow-overwrite=true --auto-file-renaming=false --continue=true --check-integrity=true --dir "$install_dir" --out "$(basename "$target_file")" "$@"; then',
            "    downloaded=1",
            "  fi",
            "fi",
            "",
            'if [ "$downloaded" -ne 1 ]; then',
            '  echo "failed to download remote payload for dapt package" >&2',
            "  exit 1",
            "fi",
            "",
            'if [ -n "$expected_sha256" ]; then',
            '  printf "%s  %s\\n" "$expected_sha256" "$target_file" | sha256sum -c -',
            "fi",
            "",
            "exit 0",
            "",
        ]
    )
    postrm = "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            'case "${1:-}" in',
            "  remove|purge)",
            f"    rm -f {shlex.quote(remote_file.as_posix())}",
            "    ;;",
            "esac",
            "exit 0",
            "",
        ]
    )
    write_executable(package_root / "DEBIAN" / "postinst", postinst)
    write_executable(package_root / "DEBIAN" / "postrm", postrm)


def release_product(args: argparse.Namespace) -> int:
    version = ensure_version(args.version)
    repo_root = args.repo_root.resolve()
    product_dir, manifest = load_manifest(args.products_dir.resolve(), args.product)
    payload_dir = product_dir / "payload"
    if not payload_dir.exists():
        fail(f"payload directory does not exist: {payload_dir}")

    build_root = args.build_root.resolve() / f"{manifest['package']}_{version}"
    if build_root.exists():
        shutil.rmtree(build_root)

    package_root = build_root / manifest["package"]
    data_root = package_root / manifest["install_prefix"].lstrip("/") / manifest["name"]
    debian_dir = package_root / "DEBIAN"
    copy_payload(payload_dir, data_root)
    debian_dir.mkdir(parents=True, exist_ok=True)
    write_control_file(debian_dir / "control", manifest, version)
    if manifest["source_type"] == "remote":
        write_text(data_root / "remote-source.toml", render_remote_source_manifest(manifest))
        create_remote_maintainer_scripts(package_root, manifest, data_root)
    write_text(
        data_root / ".dapt-release.txt",
        "\n".join(
            [
                f"product={manifest['name']}",
                f"package={manifest['package']}",
                f"version={version}",
                f"source_type={manifest['source_type']}",
                f"released_at={datetime.now(timezone.utc).isoformat()}",
                "",
            ]
        ),
    )

    package_filename = f"{manifest['package']}_{version}_{manifest['architecture']}.deb"
    output_path = build_root / package_filename
    build_deb(package_root, output_path)

    pool_path = repo_root / "pool" / "main" / package_filename
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, pool_path)
    refresh_repo(repo_root, args.sign_with or "")
    print(pool_path)
    return 0


def parse_control_fields(raw_control: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    for line in raw_control.splitlines():
        if not line:
            continue
        if line[0].isspace() and current_key:
            fields[current_key] += "\n" + line
            continue
        key, value = line.split(":", 1)
        current_key = key
        fields[key] = value.lstrip()
    return fields


def digest_file(path: Path) -> dict[str, str]:
    hashes = {
        "md5": hashlib.md5(),
        "sha1": hashlib.sha1(),
        "sha256": hashlib.sha256(),
    }
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            for hasher in hashes.values():
                hasher.update(chunk)
    return {name: hasher.hexdigest() for name, hasher in hashes.items()}


def read_deb_fields(path: Path) -> dict[str, str]:
    return parse_control_fields(run(["dpkg-deb", "-f", str(path)]))


def render_packages_record(fields: dict[str, str], repo_relative_path: str, size: int, hashes: dict[str, str]) -> str:
    lines = []
    ordered_keys = [
        "Package",
        "Version",
        "Architecture",
        "Maintainer",
        "Depends",
        "Homepage",
        "Section",
        "Priority",
        "Description",
    ]
    for key in ordered_keys:
        value = fields.get(key)
        if value:
            lines.append(f"{key}: {value}")
    lines.extend(
        [
            f"Filename: {repo_relative_path}",
            f"Size: {size}",
            f"MD5sum: {hashes['md5']}",
            f"SHA1: {hashes['sha1']}",
            f"SHA256: {hashes['sha256']}",
        ]
    )
    return "\n".join(lines)


def write_packages_index(path: Path, records: list[str]) -> None:
    content = "\n\n".join(records) + ("\n" if records else "")
    write_text(path, content)
    gz_path = path.with_name(path.name + ".gz")
    gz_path.parent.mkdir(parents=True, exist_ok=True)
    with gz_path.open("wb") as handle:
        handle.write(gzip.compress(content.encode("utf-8"), mtime=0))


def release_checksums(repo_dist_dir: Path) -> tuple[list[str], list[str]]:
    md5_lines: list[str] = []
    sha256_lines: list[str] = []
    for path in sorted(repo_dist_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"Release", "InRelease", "Release.gpg"}:
            continue
        relative = path.relative_to(repo_dist_dir).as_posix()
        size = path.stat().st_size
        hashes = digest_file(path)
        md5_lines.append(f" {hashes['md5']} {size:16d} {relative}")
        sha256_lines.append(f" {hashes['sha256']} {size:16d} {relative}")
    return md5_lines, sha256_lines


def maybe_sign_release(repo_dist_dir: Path, signing_key: str) -> None:
    release_path = repo_dist_dir / "Release"
    inrelease_path = repo_dist_dir / "InRelease"
    release_gpg_path = repo_dist_dir / "Release.gpg"
    if not signing_key:
        for signature_path in (inrelease_path, release_gpg_path):
            if signature_path.exists():
                signature_path.unlink()
        return
    run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--armor",
            "--detach-sign",
            "--local-user",
            signing_key,
            "--output",
            str(release_gpg_path),
            str(release_path),
        ]
    )
    run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--clearsign",
            "--local-user",
            signing_key,
            "--output",
            str(inrelease_path),
            str(release_path),
        ]
    )


def refresh_repo(repo_root: Path, signing_key: str) -> None:
    config = load_repo_config(repo_root)
    dist_dir = repo_root / "dists" / config["codename"]
    pool_dir = repo_root / "pool" / "main"
    pool_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    packages: list[dict[str, str]] = []
    repository_architectures = set(config["architectures"])
    repository_architectures.add("all")

    for deb_path in sorted(pool_dir.glob("*.deb")):
        fields = read_deb_fields(deb_path)
        architecture = fields.get("Architecture", "all")
        repository_architectures.add(architecture)
        rel_path = deb_path.relative_to(repo_root).as_posix()
        hashes = digest_file(deb_path)
        packages.append(
            {
                "architecture": architecture,
                "record": render_packages_record(
                    fields,
                    rel_path,
                    deb_path.stat().st_size,
                    hashes,
                ),
            }
        )

    for architecture in sorted(repository_architectures):
        index_dir = dist_dir / "main" / f"binary-{architecture}"
        index_dir.mkdir(parents=True, exist_ok=True)
        records = [
            package["record"]
            for package in packages
            if package["architecture"] in {architecture, "all"}
        ]
        write_packages_index(index_dir / "Packages", records)

    md5_lines, sha256_lines = release_checksums(dist_dir)
    release_content = "\n".join(
        [
            f"Origin: {config['origin']}",
            f"Label: {config['label']}",
            f"Suite: {config['suite']}",
            f"Codename: {config['codename']}",
            f"Date: {datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %Z')}",
            f"Architectures: {' '.join(sorted(repository_architectures))}",
            f"Components: {' '.join(config['components'])}",
            f"Description: {config['description']}",
            "MD5Sum:",
            *md5_lines,
            "SHA256:",
            *sha256_lines,
            "",
        ]
    )
    write_text(dist_dir / "Release", release_content)
    maybe_sign_release(dist_dir, signing_key or config["sign_with"])


def refresh_repo_command(args: argparse.Namespace) -> int:
    refresh_repo(args.repo_root.resolve(), args.sign_with or "")
    print(args.repo_root.resolve())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DAPT proof-of-concept helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-repo", help="initialize a repository root")
    init_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    init_parser.add_argument("--origin", default="DAPT")
    init_parser.add_argument("--label", default="DAPT")
    init_parser.add_argument("--suite", default="stable")
    init_parser.add_argument("--codename", default="stable")
    init_parser.add_argument(
        "--description",
        default="DAPT proof-of-concept repository",
    )
    init_parser.add_argument(
        "--components",
        nargs="+",
        default=["main"],
        help="repository components to list in Release",
    )
    init_parser.add_argument(
        "--architectures",
        nargs="+",
        default=["amd64", "all"],
        help="architectures to index; arch=all packages are included everywhere",
    )
    init_parser.add_argument("--sign-with", default="")
    init_parser.set_defaults(func=init_repo)

    new_parser = subparsers.add_parser("new-product", help="scaffold a new data product")
    new_parser.add_argument("name")
    new_parser.add_argument("--products-dir", type=Path, default=DEFAULT_PRODUCTS_DIR)
    new_parser.add_argument("--package", default="")
    new_parser.add_argument(
        "--maintainer",
        default="DAPT Maintainer <maintainer@example.com>",
    )
    new_parser.add_argument("--summary", default="Example data product")
    new_parser.add_argument(
        "--description",
        default="Replace this with a longer description of the data product.",
    )
    new_parser.add_argument("--section", default="data")
    new_parser.add_argument("--priority", default="optional")
    new_parser.add_argument("--architecture", default="all")
    new_parser.add_argument("--install-prefix", default="/usr/share/dapt/products")
    new_parser.add_argument("--depends", nargs="*", default=[])
    new_parser.add_argument("--homepage", default="")
    new_parser.add_argument("--source-type", default="local", choices=sorted(SOURCE_TYPES))
    new_parser.add_argument("--remote-url", action="append", default=[])
    new_parser.add_argument("--remote-filename", default="")
    new_parser.add_argument("--remote-sha256", default="")
    new_parser.add_argument("--remote-torrent-url", default="")
    new_parser.add_argument("--remote-metalink-url", default="")
    new_parser.set_defaults(func=new_product)

    release_parser = subparsers.add_parser("release", help="build and publish a data product version")
    release_parser.add_argument("product")
    release_parser.add_argument("version")
    release_parser.add_argument("--products-dir", type=Path, default=DEFAULT_PRODUCTS_DIR)
    release_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    release_parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    release_parser.add_argument("--sign-with", default="")
    release_parser.set_defaults(func=release_product)

    refresh_parser = subparsers.add_parser("refresh-repo", help="rebuild repository metadata")
    refresh_parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    refresh_parser.add_argument("--sign-with", default="")
    refresh_parser.set_defaults(func=refresh_repo_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
