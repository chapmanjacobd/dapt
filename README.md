# dapt

`dapt` is a proof-of-concept data versioning and distribution tool built on top of APT. It packages datasets as Debian packages, publishes a normal APT repository, and adds optional Metalink, BitTorrent, and aria2c-backed transport paths without replacing APT itself.

For Fedora and other non-Debian development hosts, use [README.non-debian.md](README.non-debian.md).

## Why piggyback on APT?

Because APT already solves the hard parts:

- dependency resolution
- upgrade semantics
- package integrity and repository signing
- standard install and removal workflows

So the distribution problem becomes: how do we move the same repo files more flexibly? This repo answers that in three layers:

1. build normal `.deb` data packages
2. publish a normal APT repository
3. optionally fetch package files through `aria2c`, Metalink, or BitTorrent

`apt-metalink` is useful precedent here, but it is an APT wrapper, not an `/usr/lib/apt/methods` plugin. `dapt` includes a small native APT method for the transport-shaped part.

## Repository layout

```text
.
├── README.md
├── README.non-debian.md
├── products/
│   └── <product>/
│       ├── payload/
│       └── product.toml
└── scripts/
    ├── aria2-sync.sh
    ├── dapt-apt-method.py
    ├── dapt.py
    ├── generate-sidecars.sh
    └── install-apt-transport.sh
```

## What the repo gives you

- `scripts/dapt.py` initializes a repo, scaffolds products, and releases versions.
- `scripts/generate-sidecars.sh` creates Metalink and torrent sidecars, preferably with `mkmetalink`.
- `scripts/aria2-sync.sh` builds an offline/LAN mirror that APT can consume with `file:`.
- `scripts/dapt-apt-method.py` is a minimal APT acquire method for `dapt+http://` and `dapt+https://`.
- `scripts/install-apt-transport.sh` installs that method into `/usr/lib/apt/methods/`.

## Quickstart

### 1. Initialize an APT repo

```bash
./scripts/dapt.py init-repo \
  --repo-root repo \
  --origin "DAPT Demo" \
  --label "DAPT Demo" \
  --suite stable \
  --codename stable \
  --components main staging \
  --architectures amd64 all
```

That creates:

- `repo/pool/<component>/` for `.deb` files in each configured component
- `repo/dists/stable/<component>/binary-amd64/Packages.gz`
- `repo/dists/stable/<component>/binary-all/Packages.gz`
- `repo/dists/stable/Release`

If you pass `--sign-with <gpg-key-id>`, `dapt.py` also writes `InRelease` and `Release.gpg`.

### 2. Create a new data product

```bash
./scripts/dapt.py new-product \
  climate-hourly \
  --component staging \
  --maintainer "Data Team <data@example.com>" \
  --summary "Climate snapshots" \
  --description "Hourly climate snapshots packaged as a versioned APT data product."
```

That scaffolds:

```text
products/climate-hourly/
├── payload/
│   └── README.txt
└── product.toml
```

Put your data files under `products/climate-hourly/payload/`.

### 3. Release a new version

```bash
./scripts/dapt.py release climate-hourly 2026.05.30 \
  --products-dir products \
  --repo-root repo
```

That:

1. reads `product.toml`
2. builds a data-only Debian package with `dpkg-deb`
3. copies it into `repo/pool/<product-component>/`
4. regenerates `Packages`, `Packages.gz`, and `Release` for every configured component

By default, payload files install under:

```text
/usr/share/dapt/products/<product>/
```

### 4. Serve or copy the repo

For a quick demo:

```bash
python3 -m http.server --directory repo 8000
```

### 5. Install from a Debian/Ubuntu client

For an unsigned local repo:

```bash
echo "deb [trusted=yes] file:/ABSOLUTE/PATH/TO/repo stable main" | \
  sudo tee /etc/apt/sources.list.d/dapt-demo.list

sudo apt update
sudo apt install dapt-climate-hourly
```

For a signed repo, import the signing key and use `signed-by=` instead of `trusted=yes`.

## Custom APT transport

This repo now includes a minimal APT acquire method for `dapt+http` and `dapt+https`.

### Install it

On a Debian or Ubuntu client:

```bash
sudo apt install aria2
sudo ./scripts/install-apt-transport.sh
```

That installs:

- `/usr/lib/apt/methods/dapt+http`
- `/usr/lib/apt/methods/dapt+https`

### Use it

Point APT at the same repository with the custom scheme:

```bash
echo "deb [trusted=yes] dapt+http://MIRROR_HOST:8000 stable main" | \
  sudo tee /etc/apt/sources.list.d/dapt-transport.list

sudo apt update
sudo apt install dapt-climate-hourly
```

For signed repos, use your normal `signed-by=` configuration instead of `trusted=yes`.

### What the transport does

The transport intentionally stays small:

1. metadata files (`Release`, `InRelease`, `Packages*`) are fetched directly
2. package files (`.deb`) prefer `.meta4`, then `.metalink`, then `.torrent`, then direct HTTP(S)
3. direct package downloads forward APT's expected checksums into `aria2c`

Metadata stays on the direct path because APT stores index files under temp names that do not match the filenames encoded in torrent or Metalink sidecars.

## Product manifest

`product.toml` stays intentionally small:

```toml
name = "climate-hourly"
package = "dapt-climate-hourly"
component = "staging"
maintainer = "Data Team <data@example.com>"
summary = "Climate snapshots"
description = """
Hourly climate snapshots packaged as a versioned APT data product.
"""
section = "data"
priority = "optional"
architecture = "all"
install_prefix = "/usr/share/dapt/products"
depends = []
homepage = ""
source_type = "local"
remote_urls = []
remote_filename = ""
remote_sha256 = ""
remote_torrent_url = ""
remote_metalink_url = ""
```

`component` is part of the product definition. Products without an explicit component are treated as `main`. `dapt` does not currently prevent the same package version from being published to multiple components.

## Remote-backed products

Some datasets are too large or too externally hosted to bundle into the repo. For those, `dapt` also supports `source_type = "remote"`: APT still installs a normal package, but the package's maintainer script uses `aria2c` to fetch the real payload from upstream or LAN-local alternates.

Example for a Kiwix/Wikimedia-style source:

```bash
./scripts/dapt.py new-product \
  wikipedia-zim \
  --source-type remote \
  --maintainer "Data Team <data@example.com>" \
  --summary "Wikipedia ZIM snapshot" \
  --description "Installs a pinned Wikipedia ZIM snapshot via aria2c." \
  --remote-url https://dumps.wikimedia.org/kiwix/zim/wikipedia/wikipedia_en_all_nopic_2026-05.zim \
  --remote-filename wikipedia_en_all_nopic_2026-05.zim \
  --remote-sha256 <sha256>
```

If you also have a LAN-local torrent or Metalink for the same file, add it to `products/wikipedia-zim/product.toml`:

```toml
source_type = "remote"
remote_torrent_url = "http://mirror.example.internal:8000/zim/wikipedia_en_all_nopic_2026-05.zim.torrent"
remote_metalink_url = "http://mirror.example.internal:8000/zim/wikipedia_en_all_nopic_2026-05.zim.meta4"
```

On install, the package prefers:

1. metalink
2. torrent
3. direct URLs

So the same product definition can use the internet when available and LAN-local alternates when it is not.

## aria2c, Metalink, and BitTorrent


### Generate sidecars

The preferred generator is [`mkmetalink`](https://github.com/chapmanjacobd/mkmetalink), because it emits both Metalink v4 (`.meta4`) and BitTorrent (`.torrent`) sidecars from the same file set.

```bash
./scripts/generate-sidecars.sh \
  repo \
  http://mirror.example.internal:8000 \
  http://mirror2.example.internal:8000 \
  --tracker udp://tracker.example.internal:6969/announce
```

That writes sidecars next to repo artifacts:

- `*.meta4` and `*.torrent` when `mkmetalink` is installed
- fallback `*.metalink` plus optional `*.torrent` when `mkmetalink` is unavailable

### Use the custom transport or use a mirrored cache?

Use the custom APT transport when:

- Debian/Ubuntu clients can reach the repo over HTTP(S)
- you want `apt update` / `apt install` to fetch package files through `aria2c` automatically
- you want APT to remain the entry point

Use the offline mirror path when:

- you want to pre-stage files before running APT
- clients will consume the repo via `file:`
- you want the simplest fallback with no `/usr/lib/apt/methods/` installation

### Sync a local mirror with aria2c

```bash
./scripts/aria2-sync.sh \
  http://mirror.example.internal:8000 \
  /srv/dapt-mirror \
  stable \
  main \
  amd64
```

The sync helper:

1. fetches `Release` and `Packages.gz`
2. extracts package filenames from `Packages`
3. prefers `.meta4`
4. falls back to `.metalink`
5. falls back to `.torrent`
6. falls back again to direct HTTP/file downloads

Once the files exist locally, clients can use normal APT against the mirrored directory:

```bash
echo "deb [trusted=yes] file:/srv/dapt-mirror stable main" | \
  sudo tee /etc/apt/sources.list.d/dapt-offline.list
```

The key design choice is: `aria2c` moves bytes; APT still owns package semantics.

## Commands

| Command | Purpose |
| --- | --- |
| `dapt.py init-repo` | Create repository layout and metadata config |
| `dapt.py new-product` | Scaffold `products/<name>/product.toml` and `payload/` |
| `dapt.py release <product> <version>` | Build a `.deb` and publish it into the repo |
| `dapt.py refresh-repo` | Rebuild `Packages`, `Packages.gz`, and `Release` |

Run `./scripts/dapt.py --help` to see flags.
