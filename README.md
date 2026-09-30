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

Not yet run to completion on this machine as of this commit — `task build` is the actual
test. Upstream's CI runs this manifest inside
`ghcr.io/flathub-infra/flatpak-github-actions:kde-6.10` with `--privileged` (needed for
flatpak-builder's per-step bubblewrap sandbox to create a Linux user namespace, the same
issue the `vcpkg-approach` branch's Dagger module hit and fixed with
`InsecureRootCapabilities`); the distrobox here should have equivalent privileges, but
that's an assumption to verify, not a settled fact.

## Flathub submission

Not yet submitted anywhere findable (checked `flathub/flathub` and the `flathub` org for
an existing `org.ladybird.Ladybird` as of 2026-09-30). Since upstream owns and actively
maintains this manifest, they're the natural ones to submit it — worth raising with the
LadybirdBrowser maintainers (e.g. as a repo issue) rather than a third party submitting on
their behalf, unless they've already indicated otherwise somewhere this hasn't turned up.
