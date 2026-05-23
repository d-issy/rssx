{
  description = "rssx - self-hosted RSS reader";

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
        pyprojectContent = builtins.readFile ./pyproject.toml;
        packageJsonContent = builtins.readFile ./package.json;
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python314
            uv
            sqlite
            just
            nodejs_24
            pnpm
            treefmt
            nixfmt
          ];

          shellHook = ''
            export UV_PYTHON=${pkgs.python314}/bin/python3.14
            : "${builtins.hashString "sha256" pyprojectContent}"
            uv sync --quiet
            : "${builtins.hashString "sha256" packageJsonContent}"
            pnpm install --silent
            echo "rssx dev shell ready. Run: just dev"
          '';
        };
      }
    );
}
