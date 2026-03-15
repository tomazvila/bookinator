{
  description = "BookStuff — E-Book Scanner, Classifier & Uploader";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;
        pythonPkgs = python.pkgs;

        bookstuff = pythonPkgs.buildPythonApplication {
          pname = "bookstuff";
          version = "0.1.0";
          src = ./.;
          format = "pyproject";

          nativeBuildInputs = [ pythonPkgs.setuptools ];

          propagatedBuildInputs = [
            pythonPkgs.click
            pythonPkgs.anthropic
            pythonPkgs.ebooklib
            pythonPkgs.pymupdf
            pythonPkgs.flask
          ];

          checkInputs = [
            pythonPkgs.pytest
          ];

          checkPhase = ''
            python -m pytest tests/ -v -m 'not integration'
          '';
        };

        devShell = pkgs.mkShell {
          packages = [
            (python.withPackages (ps: [
              ps.click
              ps.anthropic
              ps.ebooklib
              ps.pymupdf
              ps.flask
              ps.pytest
            ]))
            pkgs.rsync
          ];
          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
          '';
        };
        dockerImage = pkgs.dockerTools.buildLayeredImage {
          name = "books-web";
          tag = "latest";
          contents = [ bookstuff pkgs.cacert ];
          config = {
            Cmd = [ "bookstuff-web" ];
            Env = [
              "BOOKS_DIR=/books"
              "PORT=5001"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            ];
            ExposedPorts = { "5001/tcp" = {}; };
          };
        };
      in {
        packages.default = bookstuff;
        packages.docker = dockerImage;
        devShells.default = devShell;
      }
    );
}
