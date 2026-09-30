# Ladybird Flatpak (work in progress)

Flatpak packaging for [Ladybird](https://github.com/LadybirdBrowser/ladybird), modeled
structurally on Flathub's `org.kde.kget` manifest. **This does not build yet** — see
"What's unresolved" below before attempting a real `flatpak-builder` run.

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
- Runtime chosen: `org.kde.Platform`/`org.kde.Sdk` `6.10`, matching KGet's manifest and
  giving us a compatible C++23 toolchain and X11/Wayland/DRI dev headers. Whether vcpkg's
  self-built Qt or the runtime's Qt ends up mattering is still open (see below).

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

2. **vcpkg fetching each port's source archive — NOT STARTED.** There is no existing
   `flatpak-node-generator`/`flatpak-cargo-generator`-equivalent for vcpkg (checked
   `flatpak/flatpak-builder-tools` — nothing there as of this writing). The plan:
   - Run `./Meta/ladybird.py vcpkg` once, with network, using the `Distribution` preset,
     against the pinned commit above.
   - vcpkg caches every port's downloaded archive under `$VCPKG_ROOT/downloads/` (or
     `VCPKG_DOWNLOADS` if set) with predictable filenames, and vcpkg only re-downloads a
     file if it's missing — it doesn't require network if the file is already there.
   - Write a generator script (`tools/generate-vcpkg-sources.py`, doesn't exist yet) that
     walks that downloads directory, and for each file emits a flatpak `"type": "file"`
     source with `dest: vcpkg/downloads` and its sha512 (vcpkg's own hash, reusable
     directly), writing `sources/vcpkg-sources.json` — same shape as the cargo fragment,
     so it'll be picked up by the existing `@@VCPKG_SOURCES@@` sentinel in
     `manifest-template.json` automatically once it exists.
   - Open question: whether to let vcpkg build its own Qt 6.10.0 from source (correctness,
     but a very large extra build — Qt from source is itself a multi-GB, multi-hour
     build) or add an overlay port that redirects Qt to the runtime's Qt6 instead. Needs
     a decision before the first real build attempt, since it changes the vcpkg download
     set significantly.

`org.ladybird.Ladybird.json` still carries an `x-comment` on the `Ladybird` module
documenting this gap (ignored by flatpak-builder, same convention as KGet's
`x-checker-data`), so it's visible in the manifest itself, not just here.

## Also not yet done

- `flatpak-builder` itself still isn't installed in this environment (only the `flatpak`
  client) — `task install-tools` will fetch it as `org.flatpak.Builder` plus the KDE
  6.10 runtime/SDK and the rust-stable SDK extension, but hasn't been run yet.
- Haven't confirmed whether `-DENABLE_QT=ON` is the correct/only CMake variable gating the
  Qt UI (vs. a headless/Android build) — verify against `UI/CMakeLists.txt` and
  `vcpkg.json`'s `VCPKG_MANIFEST_FEATURES` handling once a build is actually attempted.
- Haven't confirmed the exact install location vcpkg expects `VCPKG_ROOT` to be — the
  `dest: vcpkg` git source assumes it lands at `$builddir/vcpkg`, matching the
  `-DCMAKE_TOOLCHAIN_FILE=vcpkg/scripts/buildsystems/vcpkg.cmake` config-opt, but this is
  unverified against an actual `Meta/ladybird.py`-orchestrated configure.
- `finish-args` includes `--share=network` because Ladybird is a *browser* and legitimately
  needs runtime network access (unrelated to the build-time network problem above) — this
  is normal for other browsers on Flathub, not a placeholder.

## Working on this (Taskfile)

Requires [`go-task`](https://taskfile.dev). All tasks: `task --list`.

- `task install-tools` — installs `uv`, `flatpak-builder` (as `org.flatpak.Builder`), the
  KDE 6.10 platform/SDK, and the rust-stable SDK extension.
- `task generate-cargo-sources` — downloads `Cargo.lock` from the pinned Ladybird commit
  and regenerates `sources/cargo-sources.json`.
- `task generate-manifest` — reassembles `org.ladybird.Ladybird.json` from
  `manifest-template.json` + `sources/*.json`.
- `task update-sources` — the above two, in order.
- `task build` — runs `flatpak-builder`. Currently fails once vcpkg tries to fetch ports
  (see above).
- `task run` — `flatpak run org.ladybird.Ladybird`.
- `task clean` — removes local build artifacts.

## Next steps, in order

1. Run `task install-tools`, then `task build` to see exactly where it currently breaks
   (expected: the first vcpkg port fetch).
2. Do one network-enabled local vcpkg fetch, write `tools/generate-vcpkg-sources.py`,
   produce `sources/vcpkg-sources.json`.
3. Decide the vcpkg-Qt-vs-runtime-Qt question.
4. Re-run `task build`; expect several more failed iterations (missing headers from the
   KDE runtime, wrong `VCPKG_ROOT` layout, Rust vendor-dir mismatches, etc.) before it
   produces a working `ladybird` binary.
5. Once it builds and runs, tighten `finish-args`/`cleanup`, add screenshots to the
   AppStream metainfo if upstream's is missing them, and go through Flathub's submission
   checklist.
