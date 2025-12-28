{
  description = "Vizzy the NixOs derivations data visualiser";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells = {
          default = pkgs.mkShell {
            name = "vizzy";
            packages = with pkgs; [
              python313
              python313Packages.pip
              graphviz
            ];

            shellHook = ''
              echo "Vizzy - NixOS Derivation Graph Explorer"
              echo ""
              echo "Setup:"
              echo "  pip install -e '.[dev]'"
              echo "  createdb vizzy"
              echo "  psql vizzy < scripts/init_db.sql"
              echo ""
              echo "Run:"
              echo "  uvicorn vizzy.main:app --reload"
            '';
          };

        };
      }
    );
}
