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
          ];

          shellHook = ''
            echo "flathub-ladybird dev shell (flatpak-builder $(flatpak-builder --version 2>/dev/null))"
          '';
        };
      });
}
