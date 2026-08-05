{
  description = "rssx - terminal RSS reader";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            go_1_26
            golangci-lint
            sqlite
            just
            treefmt
            nixfmt
            actionlint
            zizmor
          ];

          shellHook = ''
            echo "rssx dev shell ready. Run: just run"
          '';
        };
      }
    );
}
