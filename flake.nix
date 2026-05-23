{
  description = "rssx - self-hosted RSS reader";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        pyprojectContent = builtins.readFile ./pyproject.toml;
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python312
            uv
            sqlite
            just
          ];

          shellHook = ''
            export UV_PYTHON=${pkgs.python312}/bin/python3.12
            : "${builtins.hashString "sha256" pyprojectContent}"
            uv sync --quiet
            echo "rssx dev shell ready. Run: uv run rssx"
          '';
        };
      });
}
