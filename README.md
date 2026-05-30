# dapt

`dapt` is a proof-of-concept data versioning and distribution tool built on top of APT. It treats each data product as a data-only Debian package, publishes standard APT repository metadata, and keeps the package-manager work where it belongs: dependency resolution, signatures, upgrades, and installation.

The repo is intentionally simple:

- `scripts/dapt.py` initializes a repository, scaffolds a new data product, and releases new versions.
- `scripts/generate-sidecars.sh` creates `.metalink` files and optional `.torrent` files for repo artifacts.
- `scripts/aria2-sync.sh` uses `aria2c` to sync an offline/LAN mirror that APT can consume with a normal `file:` source.
- remote-backed products can ship a tiny `.deb` that fetches a large upstream artifact with `aria2c` at install time.

For Fedora and other non-Debian development hosts, use the separate guide in [README.non-debian.md](README.non-debian.md).

## Why piggyback on APT instead of building something new?

Because APT already solves the hard parts:

- dependency resolution
- package upgrade semantics
- package integrity and optional repository signing
- standard install and removal workflows

That makes the P2P/offline problem a distribution-layer problem, not a package-manager rewrite. The cleanest next step beyond this POC is a custom APT transport under `/usr/lib/apt/methods/`; until then, this repo keeps APT authoritative and uses `aria2c` to pre-position the same repository files over HTTP, Metalink, or BitTorrent.

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
    ├── dapt.py
    └── generate-sidecars.sh
```

## Quickstart

### 1. Initialize an APT repo

```bash
./scripts/dapt.py init-repo \
  --repo-root repo \
  --origin "DAPT Demo" \
  --label "DAPT Demo" \
  --suite stable \
  --codename stable \
  --architectures amd64 all
```

That creates a standard repo root:

- `repo/pool/main/` for `.deb` files
- `repo/dists/stable/main/binary-amd64/Packages.gz`
- `repo/dists/stable/main/binary-all/Packages.gz`
- `repo/dists/stable/Release`

If you pass `--sign-with <gpg-key-id>`, `dapt.py` also writes `InRelease` and `Release.gpg`.

### 2. Create a new data product

```bash
./scripts/dapt.py new-product \
  climate-hourly \
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

Put your actual data files under `products/climate-hourly/payload/`.

### 3. Release a new version

```bash
./scripts/dapt.py release climate-hourly 2026.05.30 \
  --products-dir products \
  --repo-root repo
```

The release command:

1. reads `product.toml`
2. builds a data-only Debian package with `dpkg-deb`
3. copies the package into `repo/pool/main/`
4. regenerates `Packages`, `Packages.gz`, and `Release`

By default, payload files are installed under:

```text
/usr/share/dapt/products/<product>/
```

APT keeps the version history in the repository; installed systems upgrade the package normally with `apt install` or `apt upgrade`.

### 4. Serve or copy the repo

For a quick demo:

```bash
python3 -m http.server --directory repo 8000
```

Or point clients at a local mirror directly with `file:`.

### 5. Install from a Debian/Ubuntu client

For an unsigned local POC:

```bash
echo "deb [trusted=yes] file:/ABSOLUTE/PATH/TO/repo stable main" | \
  sudo tee /etc/apt/sources.list.d/dapt-demo.list

sudo apt update
sudo apt install dapt-climate-hourly
```

For a signed repo, import the signing key and use `signed-by=` instead of `trusted=yes`.

## Product manifest

`product.toml` is intentionally small and readable:

```toml
name = "climate-hourly"
package = "dapt-climate-hourly"
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

## Commands

| Command | Purpose |
| --- | --- |
| `dapt.py init-repo` | Create repository layout and metadata config |
| `dapt.py new-product` | Scaffold `products/<name>/product.toml` and `payload/` |
| `dapt.py release <product> <version>` | Build a `.deb` and publish it into the repo |
| `dapt.py refresh-repo` | Rebuild `Packages`, `Packages.gz`, and `Release` |

Run `./scripts/dapt.py --help` to see all flags.

## Remote-backed products

Some datasets are too large or too externally hosted to bundle into the repository itself. For those, `dapt` also supports a remote source type: APT still installs a normal package, but the package's maintainer script uses `aria2c` to fetch the real payload from upstream or LAN-local alternates.

That is the practical stand-in for a "virtual repo entry" in this POC: you still get an installable package, but the package points at remote content instead of embedding it.

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

If you also have a LAN-local torrent or metalink for the same file, add it to `products/wikipedia-zim/product.toml`:

```toml
source_type = "remote"
remote_torrent_url = "http://mirror.example.internal:8000/zim/wikipedia_en_all_nopic_2026-05.zim.torrent"
remote_metalink_url = "http://mirror.example.internal:8000/zim/wikipedia_en_all_nopic_2026-05.zim.metalink"
```

On install, the package prefers:

1. torrent
2. metalink
3. direct URLs

So the same product definition can use the internet when available and LAN-local alternates when it is not.

## aria2c, Metalink, and BitTorrent

The POC keeps the APT repo format unchanged and adds alternate distribution paths around it.

### Generate alternate download descriptors

```bash
./scripts/generate-sidecars.sh \
  repo \
  http://mirror.example.internal:8000 \
  udp://tracker.example.internal:6969/announce
```

That writes sidecars next to repo artifacts:

- `*.metalink` for `aria2c`
- `*.torrent` when `mktorrent` or `transmission-create` is installed

The important point is that the sidecars describe the same `Packages.gz`, `Release`, and `.deb` files APT already understands.

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
3. prefers `.torrent` sidecars when present
4. falls back to `.metalink`
5. falls back again to direct HTTP/file downloads

Once the files exist locally, clients can use normal APT against the mirrored directory:

```bash
echo "deb [trusted=yes] file:/srv/dapt-mirror stable main" | \
  sudo tee /etc/apt/sources.list.d/dapt-offline.list
```

This is the key design choice for offline/LAN use: `aria2c` moves bytes; APT still owns package semantics.

## Notes on prior art

- `apt-metalink` is the closest conceptual fit for the future direction here: keep APT, but hand file acquisition to a metalink-aware helper such as `aria2c`.
- `nala` is useful inspiration for APT UX and concurrent fetching, but it is more of an APT frontend than a transport-layer answer to offline or BitTorrent-backed distribution.

## What this POC deliberately does not do yet

- install a real custom APT method under `/usr/lib/apt/methods/`
- manage multi-component repos beyond `main`
- replace mature repo managers like `reprepro` or `aptly`
- create torrents without an external torrent creation tool

Those are the natural next steps once the workflow and UX are proven.
