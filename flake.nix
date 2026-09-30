{
  description = "Dev shell for packaging Ladybird as a Flatpak";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            flatpak
            flatpak-builder
            appstream
            desktop-file-utils
            ostree
            uv
            python3
            go-task
            git
            jq
            # Everything below is here because a real `vcpkg install` for Ladybird's
            # ~69 ports needed it when tried in a minimal Fedora distrobox -- see
            # README.md's vcpkg section for exactly which port needed what. freedesktop
            # SDK (used inside the actual flatpak sandbox) already ships equivalents of
            # most of these; this list is for driving flatpak-builder itself from this
            # shell (e.g. in CI), not for the flatpak build's own internal toolchain.
            gcc
            gnumake
            perl
            nasm
            autoconf
            automake
            libtool
            autoconf-archive
            bison
            flex
            gettext
            texinfo
            ncurses
            pkg-config
            unzip
            which
            patch
            diffutils
          ];

          shellHook = ''
            echo "flathub-ladybird dev shell (flatpak-builder $(flatpak-builder --version 2>/dev/null))"
          '';
        };
      });
}
