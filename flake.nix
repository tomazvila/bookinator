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

        pipPkgs = ps: pkgs.runCommand "pip-packages" {
          buildInputs = [ (python.withPackages (p: [ p.pip ])) ];
        } ''
          mkdir -p $out/${python.sitePackages}
          ${python}/bin/python -m pip install --target=$out/${python.sitePackages} \
            voyageai sqlite-vec --quiet 2>/dev/null
        '';

        allNixPkgs = ps: [
          ps.click
          ps.anthropic
          ps.ebooklib
          ps.pymupdf
          ps.flask
          ps.argon2-cffi
        ];

        bookstuff = pythonPkgs.buildPythonApplication {
          pname = "bookstuff";
          version = "0.1.0";
          src = ./.;
          format = "pyproject";

          nativeBuildInputs = [ pythonPkgs.setuptools ];

          propagatedBuildInputs = (allNixPkgs pythonPkgs);

          checkInputs = [
            pythonPkgs.pytest
          ];

          # Skip check phase — voyageai/sqlite-vec not available at build time in nix
          doCheck = false;
        };

        devShell = pkgs.mkShell {
          packages = [
            (python.withPackages (ps: (allNixPkgs ps) ++ [ ps.pytest ps.pip ]))
            pkgs.rsync
          ];
          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
            # Install PyPI-only packages to a local directory
            export PIP_TARGET="$PWD/.pip-packages"
            export PYTHONPATH="$PIP_TARGET:$PYTHONPATH"
            if [ ! -d "$PIP_TARGET/voyageai" ]; then
              echo "Installing voyageai and sqlite-vec..."
              pip install --target="$PIP_TARGET" voyageai sqlite-vec -q
            fi
          '';
        };
        dockerImage = pkgs.dockerTools.buildLayeredImage {
          name = "books-web";
          tag = "latest";
          contents = [ bookstuff pkgs.cacert pkgs.python3Packages.pip ];
          config = {
            Cmd = [
              "${pkgs.bash}/bin/bash" "-c"
              "pip install --target=/pip-pkgs voyageai sqlite-vec -q && PYTHONPATH=/pip-pkgs:$PYTHONPATH exec bookstuff-web"
            ];
            Env = [
              "BOOKS_DIR=/books"
              "PORT=5001"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            ];
            ExposedPorts = { "5001/tcp" = {}; };
          };
        };
        devServer = pkgs.writeShellScriptBin "bookstuff-dev" ''
          export PYTHONPATH="${self}/src:$PYTHONPATH"
          export BOOKS_DIR="''${BOOKS_DIR:-/tmp/books-local}"
          export PORT="''${PORT:-5001}"
          echo "Starting dev server on http://localhost:$PORT (BOOKS_DIR=$BOOKS_DIR)"
          exec ${python.withPackages (ps: (allNixPkgs ps))}/bin/python -m bookstuff.web.app
        '';
      in {
        packages.default = bookstuff;
        packages.docker = dockerImage;
        packages.dev = devServer;
        apps.dev = {
          type = "app";
          program = "${devServer}/bin/bookstuff-dev";
        };
        devShells.default = devShell;
      }
    );
}
