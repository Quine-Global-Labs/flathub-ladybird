// Package main is the Dagger module for building the org.ladybird.Ladybird
// Flatpak.
//
// NOT YET RUN. `dagger init` was hand-written here instead of generated,
// because the local Dagger engine (a podman container) got stuck in an
// unkillable D-state on this dev machine and no working engine was available
// to run `dagger develop` against. That command still needs to be run once
// against a healthy engine (locally once the podman issue is resolved, or in
// CI) to generate go.mod/go.sum and the internal/dagger SDK bindings this
// file imports -- until then this package doesn't build. The intent is to
// finish wiring this up via GitHub Actions rather than chase the local
// engine issue further. See README.md for the manifest-side TODOs (vcpkg
// vendoring) this Build function will hit once it actually runs.
package main

import (
	"context"

	"dagger/flathub-ladybird/internal/dagger"
)

type FlathubLadybird struct{}

// Build runs flatpak-builder against org.ladybird.Ladybird.json inside a
// Nix-provisioned container (using this repo's flake.nix for
// flatpak-builder/uv/etc.) and returns the resulting flatpak-builder repo
// directory.
//
// Expected to fail once vcpkg tries to fetch ports mid-build until that's
// vendored (see README.md) -- kept here so CI exercises the real pipeline as
// soon as it's resolved, instead of being wired up after the fact.
func (m *FlathubLadybird) Build(ctx context.Context,
	// +defaultPath="."
	src *dagger.Directory,
) *dagger.Directory {
	return nixContainer(src).
		WithExec([]string{
			"nix", "develop", "--command",
			"flatpak-builder", "--force-clean", "--ccache",
			"--repo=repo", "build", "org.ladybird.Ladybird.json",
		}).
		Directory("/repo/repo")
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
		WithMountedCache("/nix/var/nix/db", dag.CacheVolume("flathub-ladybird-nix-db")).
		WithMountedCache("/nix/store", dag.CacheVolume("flathub-ladybird-nix-store")).
		WithDirectory("/repo", src).
		WithWorkdir("/repo").
		WithExec([]string{"nix", "develop", "--command", "true"})
}
