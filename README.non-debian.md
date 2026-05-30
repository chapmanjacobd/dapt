# Developing dapt on Fedora or another non-Debian host

This repo is designed so you can **build and publish APT-compatible data repositories from a non-Debian machine**. You do not need `apt-ftparchive` or `dpkg-scanpackages`; `scripts/dapt.py` generates the repository metadata itself.

What you do need is:

- Python 3.11+
- `dpkg-deb` to build `.deb` packages
- `gpg` if you want signed repositories
- `aria2c` for the offline/LAN transport demo
- `mkmetalink` as the preferred sidecar generator for Metalink plus BitTorrent

## Fedora setup

```bash
sudo dnf install python3 dpkg gnupg2 aria2 git
```

Install `mkmetalink`:

```bash
go install github.com/chapmanjacobd/mkmetalink@latest
```

Make sure `$GOPATH/bin` or `$HOME/go/bin` is on your `PATH`.

Fallback tools if you do not want `mkmetalink`:

```bash
sudo dnf install transmission-cli
```

## What works on Fedora

- `./scripts/dapt.py init-repo`
- `./scripts/dapt.py new-product`
- `./scripts/dapt.py release`
- `./scripts/generate-sidecars.sh`
- remote-backed packages that fetch very large files with `aria2c`

In other words, Fedora is a good **authoring and publishing environment** for the proof of concept.

## What still needs a Debian-family client

APT consumption itself still happens on Debian or Ubuntu systems:

- `apt update`
- `apt install dapt-<product>`
- testing `/etc/apt/sources.list.d/*.list`
- validating a future custom APT transport

If you want a clean consumer-side validation loop from Fedora, use a Debian container or VM:

```bash
podman run --rm -it -v "$PWD/repo:/repo:Z" docker.io/library/debian:stable
```

Inside that container you can point APT at `file:/repo`.

## Suggested workflow

1. Author products and release packages from Fedora.
2. Serve or copy the generated `repo/` tree.
3. Validate installation from a Debian/Ubuntu VM, container, or physical client.
4. Use `aria2-sync.sh` to demo HTTP/LAN/offline mirroring without changing the repo format.

Remote-backed products are especially useful from a Fedora dev host: you can publish a small Debian package that points at a large upstream file, plus LAN-local `.torrent` or `.metalink` alternates, without needing to stage the full dataset inside the repo itself.
