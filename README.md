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

## What's unresolved (the actual hard part)

Flathub's build sandbox has **no network access** during `flatpak-builder` runs (except
in a `simple`-buildsystem module explicitly wrapping known lockfile-based generators).
Ladybird's build wants network access twice:

1. **vcpkg fetching each port's source archive.** There is no existing
   `flatpak-node-generator`/`flatpak-cargo-generator`-equivalent for vcpkg (checked
   `flatpak/flatpak-builder-tools` — nothing there as of this writing). The plan:
   - Run `./Meta/ladybird.py vcpkg` once, with network, using the `Distribution` preset,
     against the pinned commit above.
   - vcpkg caches every port's downloaded archive under `$VCPKG_ROOT/downloads/` (or
     `VCPKG_DOWNLOADS` if set) with predictable filenames, and vcpkg only re-downloads a
     file if it's missing — it doesn't require network if the file is already there.
   - Write a small generator script that walks that downloads directory, and for each
     file emits a flatpak `"type": "file"` source with `dest: vcpkg/downloads` (or
     wherever `VCPKG_DOWNLOADS` is pointed for the flatpak build) and its sha512 (vcpkg's
     own hash, reusable directly).
   - Feed the generated source list into the `Ladybird` module's `sources` array (as a
     separate generated JSON file, `flatpak-vcpkg-sources.json`, merged in the same way
     `flatpak-cargo-generator` output is normally merged).
   - Open question: whether to let vcpkg build its own Qt 6.10.0 from source (correctness,
     but a very large extra build — Qt from source is itself a multi-GB, multi-hour
     build) or add an overlay port that redirects Qt to the runtime's Qt6 instead. Needs
     a decision before the first real build attempt, since it changes the vcpkg download
     set significantly.
2. **Rust deps via Cargo.** This one *does* have a known-good tool:
   [`flatpak-cargo-generator.py`](https://github.com/flatpak/flatpak-builder-tools/tree/master/cargo)
   from `flatpak/flatpak-builder-tools`. Run it against Ladybird's `Cargo.lock` at the
   pinned commit to produce `cargo-sources.json`, then add a `rust-deps` module (or fold
   the generated sources into the `Ladybird` module) the standard way that tool documents.
   This is mechanical, not a research problem.

Neither of these has been attempted yet — the manifest currently just documents them via
`x-comment` fields (ignored by flatpak-builder, same convention as KGet's
`x-checker-data`) so the gap is visible in the manifest itself, not just here.

## Also not yet done

- No local `flatpak-builder` is installed in this environment (only the `flatpak` client).
  Install it (`sudo dnf install flatpak-builder` on Fedora, or
  `flatpak install org.flatpak.Builder` for the flatpak-native builder) before attempting
  a real build.
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

## Next steps, in order

1. Get `flatpak-builder` installed locally.
2. Run `flatpak-cargo-generator.py` against Ladybird's `Cargo.lock` → wire up Rust deps
   (mechanical, do this first since it's solved tooling).
3. Do one network-enabled local vcpkg fetch, write the downloads-directory generator
   script, produce `flatpak-vcpkg-sources.json`.
4. Decide the vcpkg-Qt-vs-runtime-Qt question.
5. First real `flatpak-builder --user --install --force-clean` attempt; expect several
   failed iterations (missing headers from the KDE runtime, wrong `VCPKG_ROOT` layout,
   etc.) before it produces a working `ladybird` binary.
6. Once it builds and runs, tighten `finish-args`/`cleanup`, add screenshots to the
   AppStream metainfo if upstream's is missing them, and go through Flathub's submission
   checklist.
