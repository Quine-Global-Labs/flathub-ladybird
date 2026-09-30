# Ladybird Flatpak — local build helper

This repo does **not** maintain its own Flatpak manifest for
[Ladybird](https://github.com/LadybirdBrowser/ladybird). It builds
**upstream's own manifest** instead:
[`Meta/CMake/flatpak/org.ladybird.Ladybird.json`](https://github.com/LadybirdBrowser/ladybird/blob/master/Meta/CMake/flatpak/org.ladybird.Ladybird.json),
maintained by the LadybirdBrowser team and built + tested on every single commit and PR
via their own
[`.github/workflows/flatpak.yml`](https://github.com/LadybirdBrowser/ladybird/blob/master/.github/workflows/flatpak.yml)
(both x86_64 and aarch64, currently green).

## Why not our own manifest

An earlier version of this repo (see the `vcpkg-approach` branch) built an independent
manifest from scratch, driving Ladybird's normal vcpkg-based build inside Flatpak's
network-less sandbox. That got genuinely close — a real CI run compiled 68 of 69 vcpkg
ports successfully, including Skia — after solving a long chain of non-obvious problems
(vcpkg's own bootstrap binary, googlesource's non-reproducible archive endpoint, a Dagger
cache-volume bug, bubblewrap needing privileged nesting, and more; see that branch's
README for the full account). Partway through fixing the very last vendoring gap, it
turned out upstream had already solved the entire problem, more simply, by not using
vcpkg for the Flatpak build at all — every dependency is its own plain Flatpak module
with a git-tag source — and had it running green in CI on every commit already. Building
and maintaining a second, independent manifest against a fast-moving browser codebase,
when a first-party one already exists and stays in lockstep with the code by
construction, isn't a good use of ongoing effort. This repo pivoted to just building that
one instead.

## Local build

Requires [`go-task`](https://taskfile.dev) and [`distrobox`](https://distrobox.it/) (same
reasoning as before: `flatpak-builder` has no Homebrew formula and needs deep
ostree/bubblewrap/polkit integration that doesn't suit an immutable host directly).

```
task install-tools   # once: creates the distrobox, installs flatpak-builder,
                      # installs the org.kde.Platform/Sdk 6.10 runtime this manifest uses
task build            # clones LadybirdBrowser/ladybird into ./ladybird if needed, then
                      # builds Meta/CMake/flatpak/org.ladybird.Ladybird.json
task run              # flatpak run org.ladybird.Ladybird
```

`task update` pulls the latest `ladybird/` checkout before a rebuild. `task clean`
removes local build artifacts (not the checkout itself).

**Build confirmed working end to end on 2026-09-30**: `task build` compiles every
dependency module (angle, skia, openssl, ffmpeg, etc.) and the main `Ladybird` module
itself, and installs cleanly. Two build-time things worth knowing if you hit them:

- `flatpak-builder` needs `--install-deps-from=flathub` (already in `task build`). Without
  it, it fails immediately with `Requested extension
  org.freedesktop.Sdk.Extension.llvm20/x86_64/6.10 not installed` — `llvm20`/`rust-stable`
  are never published under a branch numbered "6.10" on Flathub (confirmed directly against
  the remote), so a naive pre-install of the runtime doesn't satisfy the SDK's declared
  extension points. `--install-deps-from` makes flatpak-builder resolve and install them
  correctly itself; upstream's CI gets this for free because its container image
  (`ghcr.io/flathub-infra/flatpak-github-actions:kde-6.10`) already has them deployed.
- `--disable-rofiles-fuse` (already in `task build`) is needed inside the distrobox, same
  as discovered on the `vcpkg-approach` branch — no FUSE mount available in the container.
  Unlike that branch's Dagger module, this distrobox did *not* need any extra privilege
  grant for bubblewrap's per-step sandbox (it just worked), so `InsecureRootCapabilities`
  wasn't needed here — evidently distrobox containers already have sufficient namespace
  permissions by default on this host.

## Running it: two live, unfixed upstream sandbox bugs

The built app installs fine but currently **will not run with Linux sandboxing enabled**
at today's pinned master commit (`124f0c9871`) — both bugs are in Ladybird's own C++
sandbox code, not in packaging:

1. **Fontconfig loads after the sandbox restricts filesystem access, so it fails** —
   tracked upstream as
   [#11775](https://github.com/LadybirdBrowser/ladybird/issues/11775) (open, filed
   2026-09-15, reported against NixOS but is a general Linux-sandbox issue, not
   Nix-specific — Flatpak's own filesystem restriction triggers the identical failure).
   The issue includes an unmerged, untested-by-its-author patch (force fontconfig to load
   its config before the Landlock/seccomp restrictions go up, then hand Skia that already-
   loaded `FcConfig*` instead of letting it load a fresh one from inside the sandbox).
   **Applied locally** (uncommitted, working-tree-only changes in `ladybird/` — the
   manifest's `Ladybird` module sources directly from the working directory, so a rebuild
   picks it up automatically) to `Services/Compositor/SandboxLinux.cpp`,
   `Services/RendererSandboxLinux.cpp`, and `Libraries/LibGfx/Font/TypefaceSkia.cpp`,
   adapted to this checkout's current `Gfx::GlobalFontConfig` singleton (a `get()` accessor
   that didn't exist when the issue's patch was written) rather than applied as a literal
   patch file. **Confirmed fixed**: the `Fontconfig error: Cannot load default config file`
   line is gone from a rebuild with this change, verified against the exact same manifest
   that reproduced it.

2. **A second, separate, not-yet-reported bug**: even with the fontconfig fix applied,
   `WebContent` crash-loops immediately on startup with `Runtime error: Landlock must be
   applied before the process starts a second thread` — repeating every ~100ms, "Last page
   loaded: about:newtab" each time. This was present from the very first run, *before* the
   fontconfig patch, so it isn't caused by that fix; searched the issue tracker
   exhaustively and found no existing report. **Confirmed isolated**: running with
   `flatpak run org.ladybird.Ladybird --disable-sandbox` (propagates to every helper
   process — `Services/WebContent/main.cpp`'s `--disable-sandbox` flag, plumbed through
   `LibWebView/HelperProcess.cpp`) eliminates the crash loop entirely — `RequestServer`,
   `Compositor`, and two `WebContent` processes all start and stay up. This isolates the
   bug cleanly to Ladybird's own Landlock-application code path (a thread getting created
   somewhere between `Sandbox::install_no_new_privileges()`/`configure_runtime()` and the
   actual Landlock restrict syscall, for reasons not yet root-caused), not to Flatpak, not
   to this repo's build, and not to the fontconfig fix. Worth filing upstream.

`task run` currently needs `--disable-sandbox` appended to actually work:

```
flatpak run org.ladybird.Ladybird --disable-sandbox
```

This is a real reduction in the security boundary Ladybird's own sandbox is meant to
provide (it's still inside the outer Flatpak sandbox, which is unaffected) — fine for
local testing, not something to treat as a permanent fix. If a leftover session from a
crashed run leaves the browser refusing to start at all with
`Runtime error: connect: Connection refused (errno=111)`, a stale single-instance
lock/socket is why — clear it and relaunch:

```
rm -f /run/user/$(id -u)/.flatpak/org.ladybird.Ladybird/xdg-run/Ladybird/Profiles/default/{*.pid,*.socket,*.lock}
```

## Flathub submission

Not yet submitted anywhere findable (checked `flathub/flathub` and the `flathub` org for
an existing `org.ladybird.Ladybird` as of 2026-09-30). Since upstream owns and actively
maintains this manifest, they're the natural ones to submit it — worth raising with the
LadybirdBrowser maintainers (e.g. as a repo issue) rather than a third party submitting on
their behalf, unless they've already indicated otherwise somewhere this hasn't turned up.
