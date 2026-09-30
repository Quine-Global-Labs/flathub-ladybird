#!/usr/bin/env python3
"""Turn a populated vcpkg downloads/ directory + the vcpkg install log that
populated it into flatpak-builder "file" sources, so flatpak-builder can
fetch (and flatpak-builder's own sandbox network rules verify) every vcpkg
port's source archive itself, rather than vcpkg trying to at build time.

Usage:
    generate-vcpkg-sources.py <path-to-vcpkg-checkout> <path-to-full-install-log> \
        -o sources/vcpkg-sources.json

The log must be a FULL, untruncated capture of a `vcpkg install --only-downloads`
(or plain install) run against a downloads/ directory that did NOT already have
the files cached -- vcpkg only prints "Downloading ..." lines on an actual
network fetch, not on a cache hit. See README.md for the exact command used to
produce both inputs.

Three kinds of entries are handled:
  1. "Downloading <url> -> <filename>" / "Downloading <filename>, trying <url>"
     -- the vcpkg_download_distfile / vcpkg_from_github style, which covers
     the overwhelming majority of ports. Hash is computed from the local file
     vcpkg already cached, since it's byte-identical to what re-fetching that
     same URL will produce.
  2. vcpkg's own build tools (cmake, ninja) -- looked up directly from
     vcpkg/scripts/vcpkg-tools.json instead of the log, since that file is the
     authoritative, version-pinned source and vcpkg doesn't reliably re-log
     these on every run.
  3. A short, hardcoded list of ports that vcpkg fetches via a raw git clone
     and packages into a tarball itself (skia's bundled piex/libyuv/wuffs
     externals, as of the pinned vcpkg commit) -- there's no stable URL vcpkg
     itself used, so these are re-fetched from an equivalent archive endpoint
     (GitHub/googlesource "archive by commit") and hashed from THAT download,
     not from vcpkg's own cached copy. This is unverified against an actual
     full (non-download-only) vcpkg build -- the archive layout (e.g. an
     extra wrapping directory) may not exactly match what vcpkg's own
     git-archive produced. Flag for follow-up if the real build trips on it.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

EXCLUDE_DIR_NAMES = {"tools", "git-tmp", "temp"}

# Kind 3a: ports vcpkg fetches via git clone + packages into downloads/<file> itself,
# where the origin also serves a stable/reproducible archive-by-commit endpoint (GitHub
# does). filename (as it lands in downloads/) -> (re-fetch url, sha256 of that url's
# content). Hand-verified against the pinned vcpkg commit in manifest-template.json;
# re-derive if that pin ever moves and this script reports these filenames as unmatched.
GIT_DERIVED = {
    "skia-e3f919ccfe3ef542cfc983a82146070258fb57f8.tar.gz": (
        "https://github.com/google/wuffs-mirror-release-c/archive/e3f919ccfe3ef542cfc983a82146070258fb57f8.tar.gz",
        "e849dab1f372f16b782ba7528e7f70281e35425bd2d644c92a36fb95909f98db",
    ),
}

# Kind 3b: same as above, but the origin (googlesource/Gitiles) serves a DIFFERENT set
# of bytes for its "+archive" endpoint on every single request (confirmed: two fetches
# of the identical commit produced two different sha256 hashes), so it can never satisfy
# a hash-pinned flatpak "file" source. These are handled directly in
# manifest-template.json instead, as a hash-pinned "git" source (commit, not download
# bytes, is the integrity guarantee) plus a "shell" source that `tar`s the checkout into
# the exact filename vcpkg expects in downloads/ -- skipped here, not reported as
# unmatched.
GIT_SOURCE_HANDLED_ELSEWHERE = {
    "libyuv-d98915a654d3564e4802a0004add46221c4e4348.tar.gz",
    "skia-bb217acdca1cc0c16b704669dd6f91a1b509c406.tar.gz",
}

DOWNLOADING_ARROW_RE = re.compile(r"^Downloading (\S+) -> (\S+)$")
DOWNLOADING_TRYING_RE = re.compile(r"^Downloading (\S+), trying (\S+)$")

# vcpkg-tools.json gives a URL, but vcpkg sometimes caches the download under a
# locally-renamed filename (to disambiguate versions) rather than the URL's own
# basename. Filenames observed to differ, mapped by hand.
TOOL_FILENAME_OVERRIDES = {
    "ninja-linux-1.13.2.zip": "https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-linux.zip",
}


def load_tool_urls(vcpkg_root: Path) -> dict:
    tools_json = json.loads((vcpkg_root / "scripts" / "vcpkg-tools.json").read_text())
    by_filename = {}
    for tool in tools_json["tools"]:
        if tool.get("os") != "linux" or not tool.get("url"):
            continue
        url = tool["url"]
        filename = url.rsplit("/", 1)[-1]
        by_filename[filename] = url
    return by_filename


def parse_log_urls(log_path: Path) -> dict:
    by_filename = {}
    for line in log_path.read_text(errors="replace").splitlines():
        m = DOWNLOADING_ARROW_RE.match(line)
        if m:
            url, filename = m.group(1), m.group(2)
            by_filename[filename] = url
            continue
        m = DOWNLOADING_TRYING_RE.match(line)
        if m:
            filename, url = m.group(1), m.group(2)
            by_filename.setdefault(filename, url)
    return by_filename


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("vcpkg_root", type=Path, help="Path to the vcpkg checkout (contains scripts/, downloads/)")
    parser.add_argument("log", type=Path, help="Full, untruncated log from the vcpkg install run that populated downloads/")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    downloads_dir = args.vcpkg_root / "downloads"
    tool_urls = load_tool_urls(args.vcpkg_root)
    log_urls = parse_log_urls(args.log)

    sources = []
    unmatched = []

    for entry in sorted(downloads_dir.iterdir()):
        if entry.is_dir():
            if entry.name not in EXCLUDE_DIR_NAMES:
                unmatched.append(f"{entry.name}/ (unexpected directory, not vendored)")
            continue
        if entry.name.endswith(".part"):
            continue
        if entry.name in GIT_SOURCE_HANDLED_ELSEWHERE:
            continue

        if entry.name in GIT_DERIVED:
            url, sha256 = GIT_DERIVED[entry.name]
        else:
            url = TOOL_FILENAME_OVERRIDES.get(entry.name) or tool_urls.get(entry.name) or log_urls.get(entry.name)
            if url is None:
                unmatched.append(entry.name)
                continue
            sha256 = sha256_of(entry)

        sources.append({
            "type": "file",
            "url": url,
            "sha256": sha256,
            "dest": "vcpkg/downloads",
            "dest-filename": entry.name,
        })

    args.output.write_text(json.dumps(sources, indent=4) + "\n")
    print(f"Wrote {len(sources)} sources to {args.output}")

    if unmatched:
        print(f"\n{len(unmatched)} file(s) in downloads/ had no known URL and were NOT vendored:", file=sys.stderr)
        for name in unmatched:
            print(f"  {name}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
