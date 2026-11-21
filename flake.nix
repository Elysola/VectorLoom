{
  description = "Vectorloom reproducible SVG asset pipeline";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        vectorloom = pkgs.python3Packages.buildPythonApplication {
          pname = "vectorloom";
          version = "0.1.0";
          pyproject = true;
          src = self;
          build-system = [ pkgs.python3Packages.hatchling ];
          nativeCheckInputs = [ pkgs.ruff pkgs.black ];
        };
      in {
        packages.default = vectorloom;
        apps.default = flake-utils.lib.mkApp { drv = vectorloom; };
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.python3Packages.hatchling
            pkgs.ruff
            pkgs.black
            pkgs.librsvg
            pkgs.fontconfig
            vectorloom
          ];
        };
      });
}
