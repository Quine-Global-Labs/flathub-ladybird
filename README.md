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
task build            # clones LadybirdBrowser/ladybird into ./ladybird if needed (applying
                      # patches/ -- see "Running it" below), then builds
                      # Meta/CMake/flatpak/org.ladybird.Ladybird.json
task run              # flatpak run org.ladybird.Ladybird
```

`task update` pulls the latest `ladybird/` checkout and reapplies `patches/` (`git
reset --hard` wipes them, same as a fresh clone would). `task clean` removes local build
artifacts (not the checkout itself).

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

## Running it: three sandbox bugs found, fixed, and verified

At today's pinned master commit (`124f0c9871`), the app **would not run at all** with
Linux sandboxing enabled — found three separate bugs doing so, all in Ladybird's own C++
sandbox code, not in packaging. All three are now fixed by `patches/sandbox-fixes.patch`
(applied automatically by `task clone`/`task update`/`task apply-patches` — **not**
committed to Ladybird's own repo, since none of this is upstreamed yet) and **confirmed
working**: a real `flatpak run org.ladybird.Ladybird` (no `--disable-sandbox`, no other
flags) starts `RequestServer`, `Compositor`, and two `WebContent` processes, all stay up,
and pages load with no crash loop.

1. **Fontconfig loads after the sandbox restricts filesystem access, so it fails** —
   tracked upstream as
   [#11775](https://github.com/LadybirdBrowser/ladybird/issues/11775) (open, filed
   2026-09-15, reported against NixOS but is a general Linux-sandbox issue, not
   Nix-specific — Flatpak's own filesystem restriction triggers the identical failure).
   The issue includes an unmerged, untested-by-its-author patch (force fontconfig to load
   its config before the Landlock/seccomp restrictions go up, then hand Skia that already-
   loaded `FcConfig*` instead of letting it load a fresh one from inside the sandbox).
   Adapted into the patch here (`Services/Compositor/SandboxLinux.cpp`,
   `Services/RendererSandboxLinux.cpp`, `Libraries/LibGfx/Font/TypefaceSkia.cpp`) to this
   checkout's current `Gfx::GlobalFontConfig` singleton (a `get()` accessor that didn't
   exist when the issue's patch was written). Confirmed fixed in isolation: the
   `Fontconfig error: Cannot load default config file` line disappeared from a rebuild with
   just this change, before the other two below were found.

2. **A second, separate, not-yet-reported bug**: even with the fontconfig fix, `WebContent`
   crash-looped immediately with `Runtime error: Landlock must be applied before the
   process starts a second thread` — a check that, per `git log`, didn't exist before
   commit `3fea952607` (2026-09-19, 11 days before our pin), added as a safety net while
   fixing an *analogous* bug in `Compositor` (GPU driver threads starting before Landlock
   was applied). That fix reordered `Compositor`'s startup; `WebContent` apparently has the
   same ordering problem and was never updated to match, so it now hits the newly-strict
   check instead of silently running with the same gap `Compositor` had. Root-caused by
   adding temporary `/proc/self/task` diagnostics: the second thread is OpenSSL's thread
   pool (`OSSL_set_max_threads`, for its thread-pool provider) *and* SDL's gamepad hotplug
   thread (`SDL_Init(SDL_INIT_GAMEPAD)`), both called before the sandbox in
   `Services/WebContent/main.cpp`. Fixed the same way the precedent did: moved both to
   after `RendererSandbox::apply_sandbox()`.

3. **Moving SDL's init that late surfaced a third, related issue**: its HIDAPI/libusb
   backend starts its own event thread, which then hits a seccomp violation
   (`disallowed syscall unknown (294)` — `sendmmsg`, used on the netlink socket libusb
   opens for device hotplug) that `WebContent`'s seccomp policy doesn't grant. Tried
   `SDL_HINT_HIDAPI_LIBUSB=0` (meant to make HIDAPI prefer the udev/hidraw backend instead
   of libusb) — did **not** avoid it in testing (`hid_init()` still calls `libusb_init()`
   regardless; not fully root-caused why). Rather than widen the seccomp policy for a
   feature most pages never use (and risk over-granting — `LibSandbox`'s existing
   `allow_network()` that provides `sendmmsg` is a much broader grant than this narrow case
   needs), **the patch just skips gamepad initialization entirely while sandboxed**
   (`--disable-sandbox` still gets it). A real, known tradeoff, not a hidden one: the
   Gamepad Web API won't work in the sandboxed build until someone scopes a properly
   narrow seccomp allowance for whatever libusb's event thread actually needs, or finds why
   the HIDAPI hint didn't take.

If a leftover session from a crashed run leaves the browser refusing to start at all with
`Runtime error: connect: Connection refused (errno=111)`, a stale single-instance
lock/socket is why (hit repeatedly while testing, mostly from `timeout`-killing a test
run non-gracefully) — `task clean-runtime` removes it.

## Flathub submission

Not yet submitted anywhere findable (checked `flathub/flathub` and the `flathub` org for
an existing `org.ladybird.Ladybird` as of 2026-09-30). Since upstream owns and actively
maintains this manifest, they're the natural ones to submit it — worth raising with the
LadybirdBrowser maintainers (e.g. as a repo issue) rather than a third party submitting on
their behalf, unless they've already indicated otherwise somewhere this hasn't turned up.
