// Package main is the Dagger module for building the org.ladybird.Ladybird
// Flatpak.
//
// NOT YET RUN LOCALLY. `dagger init`/`dagger develop` was hand-written here
// instead of generated, because the local Dagger engine (a podman container)
// got stuck in an unkillable D-state on this dev machine and no working
// engine was available. `dagger develop` still needs to run once against a
// healthy engine to generate go.mod/go.sum/internal/dagger -- CI is that
// healthy engine (a fresh one every run), so GitHub Actions is this module's
// first real test, not a local one. See README.md for the manifest-side
// research (vcpkg vendoring, the freedesktop-vs-KDE runtime call, etc.) this
// Build function's actual flatpak-builder run is built on.
package main

import (
	"context"

	"dagger/flathub-ladybird/internal/dagger"
)

const appID = "org.ladybird.Ladybird"

type FlathubLadybird struct{}

// Build runs flatpak-builder against org.ladybird.Ladybird.json inside a
// Nix-provisioned container (this repo's flake.nix -- flatpak-builder plus
// the native toolchain vcpkg's ~69 ports needed when this was worked out by
// hand in a distrobox: gcc, perl, nasm, autotools, ncurses, etc), producing
// an ostree repo, then bundles that into a single distributable .flatpak
// file via `flatpak build-bundle`.
//
// --disable-rofiles-fuse is always passed because the FUSE mount
// flatpak-builder's rofiles overlay normally wants isn't guaranteed
// available inside a container (confirmed necessary in the distrobox this
// was developed against; harmless where FUSE does work, since it just
// switches to a hardlink/copy strategy instead).
//
// vcpkg's own binary cache and ccache are both mounted as Dagger cache
// volumes so a second run of this function doesn't recompile the ~69 vcpkg
// ports (or Ladybird itself) from scratch -- only the first run per cache
// generation pays the full (likely multi-hour) cost.
func (m *FlathubLadybird) Build(ctx context.Context,
	// +defaultPath="."
	src *dagger.Directory,
) *dagger.File {
	bundleName := appID + ".flatpak"

	return nixContainer(src).
		WithMountedCache("/repo/Build/caches/vcpkg-binary-cache", dag.CacheVolume("flathub-ladybird-vcpkg-binary-cache")).
		WithMountedCache("/root/.cache/ccache", dag.CacheVolume("flathub-ladybird-ccache")).
		WithExec([]string{
			"nix", "develop", "--command",
			"flatpak-builder", "--disable-rofiles-fuse", "--force-clean", "--ccache",
			"--repo=repo", "build", appID + ".json",
		}).
		WithExec([]string{
			"nix", "develop", "--command",
			"flatpak", "build-bundle", "repo", bundleName, appID,
		}).
		File(bundleName)
}

// GenerateCargoSources regenerates sources/cargo-sources.json from the
// pinned Ladybird commit's Cargo.lock and reassembles
// org.ladybird.Ladybird.json (`task update-sources`), returning the updated
// repo tree so the caller can diff and commit the result.
func (m *FlathubLadybird) GenerateCargoSources(ctx context.Context,
	// +defaultPath="."
	src *dagger.Directory,
) *dagger.Directory {
	return nixContainer(src).
		WithExec([]string{"nix", "develop", "--command", "task", "update-sources"}).
		Directory("/repo")
}

// nixContainer provisions flatpak-builder, uv, go-task, and the rest of
// flake.nix's devShell inside a Nix-enabled container, with the repo mounted
// at /repo. Nix store state is cached across runs via a Dagger cache volume.
func nixContainer(src *dagger.Directory) *dagger.Container {
	return dag.Container().
		From("nixos/nix:2.32.3").
		WithEnvVariable("NIX_CONFIG", "experimental-features = nix-command flakes").
		WithDirectory("/repo", src).
		WithWorkdir("/repo").
		WithExec([]string{"nix", "develop", "--command", "true"})
}

// Cache volumes deliberately NOT mounted at /nix/var/nix/db or /nix/store: a
// Dagger cache volume starts empty and is mounted AT that exact path,
// replacing (not merging with) whatever the base image already has there --
// which for nixos/nix is the nix binary itself and its entire dependency
// closure. First real run of this module (in CI, the local Dagger engine
// being unusable) hit exactly this: "nix: executable file not found in
// $PATH" despite the image nominally shipping it. Losing package-download
// caching across Dagger runs as a result is an acceptable tradeoff for
// correctness -- flatpak-builder etc. come from cache.nixos.org quickly
// regardless, dwarfed by the actual multi-hour Ladybird/vcpkg build time.
