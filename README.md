# Ladybird Flatpak (work in progress)

Flatpak packaging for [Ladybird](https://github.com/LadybirdBrowser/ladybird), modeled
structurally on Flathub's `org.kde.kget` manifest. **This does not build yet, but it's
close:** a real `task build` run now gets all the way through fetching sources (all 173
Rust crates + all 66 vcpkg port archives, offline-vendored), SDK/toolchain resolution,
CMake configure, vcpkg's own tool bootstrap, and starts actually compiling C++ vcpkg
packages one by one (got to package 7 of 69 before the last stop). See "What's
unresolved" below for exactly where it stops now and why.

## Facts this manifest relies on (verified 2026-09-29)

- App ID `org.ladybird.Ladybird` is upstream's own, not invented here: Ladybird already
  ships a desktop file, AppStream metainfo, D-Bus service file and scalable icon under
  `Meta/CMake/freedesktop/`, installed via CMake's `-DENABLE_INSTALL_FREEDESKTOP_FILES=ON`
  (see `UI/cmake/InstallRules.cmake`). We don't need to author any of those ourselves.
- Ladybird has **no tagged releases** — it's rolling `master` only. The manifest pins the
  `git` source to the commit that was `master` HEAD on 2026-09-29:
  `618693e7173413d0a6e23d6449164170b1c7dae8`. Re-pin periodically (Flathub requires a
  pinned commit, not a tracked branch).
- Build system: CMake ≥ 3.30 + Ninja, via the `Distribution` CMake preset
  (`LADYBIRD_VCPKG_TYPE=distribution`, static libs, Release build type) — see
  `Meta/CMake/presets/CMakeBasePresets.json`.
- Dependencies come from **vcpkg** (`vcpkg.json` / `vcpkg-configuration.json`), pinned to
  `builtin-baseline` commit `7f3781e19cc7d4e4882a4caec01668c6f7b5c163` in the vcpkg repo.
  That's ~40 C++ libraries (Skia, ICU, FFmpeg, curl, libwebp, libavif, harfbuzz, freetype,
  sqlite3, simdjson, and notably **Qt 6.10.0 itself**, built from source via vcpkg rather
  than taken from the runtime).
- Rust toolchain: `rust-toolchain.toml` pins stable channel **1.98.0** (not nightly) with
  `rustfmt`/`clippy`. Rust deps are locked in `Cargo.lock` at the repo root.
- Runtime: `org.freedesktop.Platform`/`org.freedesktop.Sdk` **26.08**, not KDE's runtime
  despite this being a Qt app and KGet (the template) being a KDE one. Two reasons,
  confirmed empirically, not just in theory:
  - Ladybird builds its own Qt 6.10.0 from source via vcpkg regardless of what the
    runtime provides (see `vcpkg.json` overrides above) — the runtime's Qt was never
    going to be used.
  - `sdk-extensions` are *always* branched to match the app's own `runtime-version`, with
    no per-extension override. `org.freedesktop.Sdk.Extension.rust-stable` is only
    published under freedesktop-sdk's own branch numbers (19.08...26.08), never under
    KDE's version numbers (6.10 etc), so `org.kde.Platform//6.10` + that extension can
    never resolve — confirmed by trying it (`error: Requested extension
    org.freedesktop.Sdk.Extension.rust-stable/x86_64/6.10 not installed`). freedesktop-sdk
    branch `26.08` ships rust-stable **1.98.0**, an exact match for
    `rust-toolchain.toml`'s pin, which is also why that branch and not another.

## How the manifest is built

`org.ladybird.Ladybird.json` is a **generated file** — don't hand-edit it. Edit
`manifest-template.json` (config-opts, finish-args, etc.) and the fragments under
`sources/`, then run:

```
task generate-manifest
```

which splices each `"@@SENTINEL@@"` string in the template's module `sources` arrays
with the matching `sources/<name>.json` array (see `tools/generate-manifest.py`). A
sentinel with no fragment file yet is dropped with a warning — that's how you can tell
from a fresh assemble which vendoring steps are still outstanding.

## What's unresolved (the actual hard part)

Flathub's build sandbox has **no network access** during `flatpak-builder` runs (except
in a `simple`-buildsystem module explicitly wrapping known lockfile-based generators).
Ladybird's build wants network access twice:

1. **Rust deps via Cargo — DONE.** `rust-toolchain.toml` pins stable channel **1.98.0**
   (not nightly), deps locked in `Cargo.lock` at the repo root. Vendored using
   [`flatpak-cargo-generator.py`](https://github.com/flatpak/flatpak-builder-tools/tree/master/cargo)
   (vendored copy at `tools/flatpak-cargo-generator.py`, MIT-licensed, from
   `flatpak/flatpak-builder-tools`), run against the pinned commit's `Cargo.lock` via
   `task generate-cargo-sources`. Output lives at `sources/cargo-sources.json` (347
   sources: 173 crate archives + 174 inline `.cargo-checksum.json`/vendor-config writes)
   and is already spliced into the manifest. `CARGO_HOME` is set to
   `/run/build/Ladybird/cargo` in `build-options.env` to match where those sources land
   inside the `Ladybird` module's build directory and the `cargo/vendor` layout the
   generator assumes. Not yet verified against an actual build (no `flatpak-builder`
   run has happened), but the source-generation half is solid, known-good tooling.

2. **vcpkg fetching sources — DONE for all 69 ports.** There is no existing
   `flatpak-node-generator`/`flatpak-cargo-generator`-equivalent for vcpkg (checked
   `flatpak/flatpak-builder-tools` — nothing there as of this writing), so this needed a
   purpose-built generator: `tools/generate-vcpkg-sources.py`. Three real, non-obvious
   fixes were needed to get here, all now verified against a real `task build` run:

   - **The bootstrap binary itself needs vendoring first**, confirmed by reading
     `/run/build/Ladybird/vcpkg-bootstrap.log` from an early failed build:
     `curl: (6) Could not resolve host: github.com` trying to fetch `vcpkg-glibc`. The
     *very first* network hit isn't a port — it's `vcpkg/bootstrap-vcpkg.sh` (invoked by
     `vcpkg.cmake` only if `$VCPKG_ROOT/vcpkg` doesn't already exist) downloading vcpkg's
     own prebuilt tool binary from a GitHub release. Fixed by adding two `"type": "file"`
     sources (x86_64/aarch64, gated by `only-arches`) for the exact `vcpkg-glibc`/
     `vcpkg-glibc-arm64` release asset named in `vcpkg/scripts/vcpkg-tool-metadata.txt`
     (`VCPKG_TOOL_RELEASE_TAG`/`VCPKG_GLIBC_SHA`), pre-placed at `vcpkg/vcpkg`, plus a
     `"type": "shell"` source to `chmod +x` it (flatpak `file` sources don't preserve the
     executable bit). `vcpkg.cmake` then skips `bootstrap-vcpkg.sh` entirely.
   - **Don't set `-DCMAKE_TOOLCHAIN_FILE` directly.** `Meta/CMake/environment.cmake`
     unconditionally does `set(CMAKE_TOOLCHAIN_FILE
     "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" CACHE STRING "" FORCE)` whenever
     `LADYBIRD_VCPKG_TYPE` is set (which we need set, to `distribution`) — `FORCE` means
     any value passed via `-D` on the command line is silently discarded. Set the
     `VCPKG_ROOT` **environment variable** instead (`build-options.env.VCPKG_ROOT`, set to
     `/run/build/Ladybird/vcpkg`, matching the vcpkg git source's `dest`) and let Ladybird
     compute the toolchain-file path itself.
   - **`flatpak-builder` needs `--disable-rofiles-fuse` inside a distrobox** — the
     rofiles-fuse overlay it normally uses needs a FUSE mount, which isn't available
     inside the container (`fusermount3: ... Permission denied`). Baked into `task build`.

   With the bootstrap binary vendored, `vcpkg install --only-downloads` (a real flag,
   fetches every port's sources without building them — much faster than a full build for
   this purpose) was run once, by hand, with network, from inside the distrobox against
   the exact same pinned commit/triplet/overlay-ports/overlay-triplets the real build
   uses. That populated `$VCPKG_ROOT/downloads/` with all 66 files needed (some ports
   share ABI-cache-only entries with no download). `tools/generate-vcpkg-sources.py` turns
   that directory + the full install log into `sources/vcpkg-sources.json`:
   - Most files: matched from `"Downloading <url> -> <filename>"` / `"Downloading
     <filename>, trying <url>"` lines in the log, hashed locally (sha256, computed from
     the file vcpkg already cached — valid since it's byte-identical to re-fetching that
     same URL).
   - vcpkg's own build tools (cmake, ninja): looked up directly from
     `vcpkg/scripts/vcpkg-tools.json` (authoritative, version-pinned) rather than the log,
     since vcpkg doesn't reliably re-log these on every run. One (`ninja`) needed a
     manual filename-override entry, since vcpkg caches it locally under a different name
     than its own download URL's basename.
   - **Two ports (skia's bundled `libyuv` and `piex` externals) needed a completely
     different mechanism**, not a `"file"` source at all: vcpkg fetches them via a raw git
     clone, packaged into a tarball itself. Their host, googlesource's Gitiles
     `+archive/<commit>.tar.gz` endpoint, **is not byte-reproducible across requests** —
     confirmed by fetching the identical commit twice and getting two different sha256
     hashes. flatpak's hash-pinned `"file"` source type fundamentally can't work against
     an endpoint like that. Fixed with a hash-pinned `"type": "git"` source (by commit,
     not download bytes) plus a `"type": "shell"` source that `tar`s the checkout into the
     exact filename vcpkg expects in `downloads/`, entirely offline. (A third such
     external, `wuffs-mirror-release-c`, is GitHub-hosted, and GitHub's archive-by-commit
     endpoint *is* stable, so it stays a normal vendored `"file"` source.)

   Regenerate via `python3 tools/generate-vcpkg-sources.py <vcpkg-checkout>
   <full-install-log> -o sources/vcpkg-sources.json`, using a *complete, untruncated* log
   (vcpkg only prints
   `Downloading` lines on an actual fetch, not a cache hit, so the log must come from a
   run against an *empty* downloads dir — see git history for the exact commands used).
   This isn't wired into the Taskfile yet since it needs a real Ladybird checkout with
   network, not just the pinned `Cargo.lock` `generate-cargo-sources` downloads.

   **Still open:**
   - `Meta/CMake/environment.cmake` also points `X_VCPKG_ASSET_SOURCES` at
     `https://vcpkg-cache.app.ladybird.org/...` — Ladybird runs its own vcpkg asset
     mirror, tried before each port's authoritative upstream URL. Irrelevant to the
     offline-vendoring approach above (vendored sources are found before any network
     fetch is attempted either way).
   - The resolved dependency set (69 packages, logged by a real `task build` run) does
     **not include Qt** anywhere, despite `vcpkg.json` pinning Qt 6.10.0 and
     `-DENABLE_QT=ON` being set. Either that CMake option isn't what actually gates the
     Qt feature/manifest-feature selection, or something else is wrong — needs
     investigation before the UI can actually build. See "Also not yet done" below.
   - The `libyuv`/`piex` git+tar fix is unverified against a full (non-`--only-downloads`)
     vcpkg build — inferred safe from log behavior (no hash-check line for these two),
     not yet confirmed by successfully building skia end to end.

3. **A new, different category of problem: `pip install` at build time.** A real
   `task build` run with all of the above in place gets through source fetching
   entirely and starts compiling real packages — reaching package 7 of 69 (`angle`,
   Google's GL/Vulkan translation layer that Skia uses) before failing:
   ```
   Command failed: .../angle/x64-linux-venv/bin/python -I -m pip install ply
   ```
   `angle`'s portfile sets up a Python venv and does `pip install ply` (Python Lex-Yacc)
   *during the build*, not during source-fetch — a different network dependency than
   anything above, needing a different fix (vendoring a pip package for offline install,
   e.g. the approach `flatpak-pip-generator` in `flatpak/flatpak-builder-tools` uses).
   Not started yet. Other ports later in the dependency order may have similar
   surprises — this is very unlikely to be the last one.

`org.ladybird.Ladybird.json` still carries an `x-comment` on the `Ladybird` module
documenting the overall gap (ignored by flatpak-builder, same convention as KGet's
`x-checker-data`), so it's visible in the manifest itself, not just here.

## Also not yet done

- `-DENABLE_QT=ON` does not appear to be pulling Qt into the resolved vcpkg dependency
  set (confirmed: a real `task build` run's package list has no `qt`/`qtbase` entry
  anywhere in the 69 packages it resolved) — needs investigation against
  `UI/CMakeLists.txt` and `vcpkg.json`'s `VCPKG_MANIFEST_FEATURES` handling. Without Qt,
  there's no UI to link against.
- `finish-args` includes `--share=network` because Ladybird is a *browser* and legitimately
  needs runtime network access (unrelated to the build-time network problem above) — this
  is normal for other browsers on Flathub, not a placeholder.

## Working on this (Taskfile)

**Local dev tooling is a Fedora [distrobox](https://distrobox.it/), not Nix.**
`flatpak-builder` has no Homebrew formula (it's too tied to system ostree/bubblewrap/
polkit integration) and its own Docker/OCI images aren't a good fit for a Nix devShell
either, so `task install-tools` creates a `flatpak-builder` distrobox (Fedora, has the
package) and installs it there. The distrobox shares this user's home directory, so
`~/.local/share/flatpak` is the same install the host `flatpak` command reads — builds
done inside the box are runnable directly from outside it (`task run` doesn't need the
box at all). This also avoids a real trap: `flatpak install org.flatpak.Builder` installs
a Flatpak *app*, not a `flatpak-builder` CLI binary on `$PATH` — it doesn't actually give
you a working `flatpak-builder` command, which is why an earlier version of this workflow
broke with `"flatpak-builder": executable file not found in $PATH`.

`uv` (used to run `tools/flatpak-cargo-generator.py`) and `go-task` itself come from
Homebrew directly — no container needed for those.

`flake.nix` and `.dagger/` (see below) are a **separate, not-yet-working path** meant for
CI, not today's local workflow — don't reach for `nix develop` here.

Requires [`go-task`](https://taskfile.dev) and [`distrobox`](https://distrobox.it/). All
tasks: `task --list`.

- `task install-tools` — creates the `flatpak-builder` distrobox, installs
  `flatpak-builder`/`flatpak`/`git` in it via `dnf`, and installs the Flatpak runtimes
  this manifest needs (freedesktop-sdk 26.08 platform/SDK, rust-stable SDK extension) via
  the host `flatpak`.
- `task generate-cargo-sources` — downloads `Cargo.lock` from the pinned Ladybird commit
  and regenerates `sources/cargo-sources.json`.
- `task generate-manifest` — reassembles `org.ladybird.Ladybird.json` from
  `manifest-template.json` + `sources/*.json`.
- `task update-sources` — the above two, in order.
- `task build` — runs `flatpak-builder --disable-rofiles-fuse` inside the distrobox.
  Currently fails partway through compiling vcpkg ports, on the first one needing a
  network `pip install` at build time (see above).
- `task run` — `flatpak run org.ladybird.Ladybird` (host, no distrobox involved).
- `task clean` — removes local build artifacts.

## Dagger + Nix (for CI, not yet working)

`dagger.json` and `.dagger/main.go` are a hand-written, **unrun** Dagger Go module — the
local Dagger engine (a podman container on this dev machine) got stuck in an unkillable
kernel `D`-state and no working engine was available to run `dagger init`/`dagger develop`
against, which is what normally generates `go.mod`/`go.sum`/the `internal/dagger` SDK
bindings this file imports. It won't compile as-is. The plan is to finish wiring it up in
GitHub Actions (or once Dagger Cloud's hosted "Cloud Engines" are set up — `dagger login`
plus `dagger --cloud` — as a way to sidestep needing any local container engine at all),
rather than chase the local engine issue further right now.

`main.go`'s `nixContainer()` helper is intended to run `flake.nix`'s devShell (which does
include `flatpak-builder`, unlike the distrobox-vs-Nix split above — inside a fresh
container, Nix's own sandboxing/build-user setup isn't fighting an immutable host OS the
way it would locally) inside a Dagger pipeline, so `flake.nix` stays relevant once this is
running in CI even though it's unused for local dev today.

## Next steps, in order

1. Fix the `pip install ply` failure in `angle` — likely vendoring `ply` (and its
   transitive deps, if any) as a flatpak source and installing via `pip install
   --no-index --find-links=...`, the way `flatpak-pip-generator` in
   `flatpak/flatpak-builder-tools` does it. Check whether other ports later in the
   dependency order (69 total, only got to #7) have the same `x_vcpkg_get_python_packages`
   pattern, and handle them together rather than one at a time.
2. Re-run `task build`; expect more failed iterations in the remaining ~62 packages
   (network hits `generate-vcpkg-sources.py` didn't need to know about because they only
   happen mid-build, not during source-fetch — `pip install` was the first example, keep
   an eye out for similar patterns like `go install`, `npm install`, or `git submodule`).
3. Once vcpkg fully installs, investigate the missing-Qt issue above before the actual
   Ladybird C++/Rust compile even starts — no point letting a multi-hour build run
   without a UI it can link.
4. Once it builds and runs, tighten `finish-args`/`cleanup`, add screenshots to the
   AppStream metainfo if upstream's is missing them, and go through Flathub's submission
   checklist.
