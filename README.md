# Ladybird Flatpak (work in progress)

Flatpak packaging for [Ladybird](https://github.com/LadybirdBrowser/ladybird), modeled
structurally on Flathub's `org.kde.kget` manifest. **This does not build yet.** A real
`task build` run gets all the way through fetching sources (including all 173 vendored
Rust crates), SDK/toolchain resolution, and CMake configure, and fails cleanly exactly
where expected: vcpkg has no network access in the build sandbox. See "What's unresolved"
below.

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

2. **vcpkg fetching things — IN PROGRESS, now precisely located.** There is no existing
   `flatpak-node-generator`/`flatpak-cargo-generator`-equivalent for vcpkg (checked
   `flatpak/flatpak-builder-tools` — nothing there as of this writing).

   A real `task build` run (freedesktop runtime, see above) gets through source
   fetching, SDK/extension resolution, and CMake configure, and fails here, confirmed by
   reading `/run/build/Ladybird/vcpkg-bootstrap.log` from the failed build dir:
   ```
   Downloading vcpkg-glibc...
   curl: (6) Could not resolve host: github.com
   ```
   So the *very first* network hit isn't even a port — it's vcpkg's own bootstrap script
   (`vcpkg/bootstrap-vcpkg.sh`, invoked automatically by `vcpkg.cmake` the first time
   `find_package`/`vcpkg_install` runs) trying to download vcpkg's own prebuilt tool
   binary from a GitHub release. That needs vendoring the same way a port does, and comes
   *before* any of the ~40 port downloads in the dependency-download order.

   Getting to this point required two fixes, both non-obvious and worth keeping straight:
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
     inside the container (`fusermount3: ... Permission denied`). This is now baked into
     `task build`.

   Next concrete step: vendor the vcpkg bootstrap binary the same way as a normal port
   (pre-place it wherever `bootstrap-vcpkg.sh` looks before it curls, as a flatpak `file`
   source), confirm the build gets past bootstrap, then handle actual port downloads:
   - vcpkg caches every port's downloaded archive under `$VCPKG_ROOT/downloads/` (or
     `VCPKG_DOWNLOADS` if set) with predictable filenames, and vcpkg only re-downloads a
     file if it's missing — it doesn't require network if the file is already there.
   - Write a generator script (`tools/generate-vcpkg-sources.py`, doesn't exist yet) that
     walks that downloads directory, and for each file emits a flatpak `"type": "file"`
     source with `dest: vcpkg/downloads` and its sha512 (vcpkg's own hash, reusable
     directly), writing `sources/vcpkg-sources.json` — same shape as the cargo fragment,
     so it'll be picked up by the existing `@@VCPKG_SOURCES@@` sentinel in
     `manifest-template.json` automatically once it exists.
   - Note `Meta/CMake/environment.cmake` also points `X_VCPKG_ASSET_SOURCES` at
     `https://vcpkg-cache.app.ladybird.org/...` — Ladybird runs its own vcpkg asset
     mirror. Doesn't remove the offline-vendoring need (it's still a network fetch), but
     may be a friendlier/more stable single source than each port's original upstream URL
     if the generator ends up needing to re-fetch anything by hand.
   - Open question: whether to let vcpkg build its own Qt 6.10.0 from source (correctness,
     but a very large extra build — Qt from source is itself a multi-GB, multi-hour
     build) or add an overlay port that redirects Qt to the runtime's Qt6 instead. Needs
     a decision before vendoring the full port set, since it changes the download set
     significantly. (`org.freedesktop.Platform` doesn't ship Qt at all, unlike KDE's
     runtime, so "redirect to the runtime's Qt" is no longer on the table now that we're
     off the KDE runtime — vcpkg building its own Qt is the only remaining option.)

`org.ladybird.Ladybird.json` still carries an `x-comment` on the `Ladybird` module
documenting this gap (ignored by flatpak-builder, same convention as KGet's
`x-checker-data`), so it's visible in the manifest itself, not just here.

## Also not yet done

- Haven't confirmed whether `-DENABLE_QT=ON` is the correct/only CMake variable gating the
  Qt UI (vs. a headless/Android build) — verify against `UI/CMakeLists.txt` and
  `vcpkg.json`'s `VCPKG_MANIFEST_FEATURES` handling once the build gets far enough to
  actually reach that code path (it doesn't yet — see vcpkg bootstrap blocker above).
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
  Currently fails once vcpkg's bootstrap script tries to download its own tool binary
  (see above).
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

1. Vendor vcpkg's own bootstrap tool binary (`vcpkg-glibc`) so `bootstrap-vcpkg.sh` finds
   it locally instead of curling GitHub — figure out exactly where it looks (probably
   `$VCPKG_ROOT/downloads/`, matching where port downloads land) and add it as a flatpak
   `file` source.
2. Re-run `task build`; confirm it gets past bootstrap and starts actually resolving
   ports.
3. Do one network-enabled local vcpkg fetch (now that bootstrap works), write
   `tools/generate-vcpkg-sources.py` against `$VCPKG_ROOT/downloads/`, produce
   `sources/vcpkg-sources.json`.
4. Re-run `task build` again; expect further failed iterations (Rust vendor-dir
   mismatches, missing headers, the actual multi-hour Qt-from-source build, etc.) before
   it produces a working `ladybird` binary.
5. Once it builds and runs, tighten `finish-args`/`cleanup`, add screenshots to the
   AppStream metainfo if upstream's is missing them, and go through Flathub's submission
   checklist.
