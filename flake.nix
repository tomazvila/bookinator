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

          # voyageai/sqlite-vec are optional deps, installed via pip at runtime
          doCheck = false;
        };

        pythonWithPkgs = python.withPackages (ps: (allNixPkgs ps) ++ [ ps.pip ]);

        # Entrypoint script that installs optional PyPI deps then starts the app
        entrypoint = pkgs.writeShellScriptBin "bookstuff-entrypoint" ''
          export PATH="${pythonWithPkgs}/bin:${pkgs.coreutils}/bin:$PATH"
          PIP_DIR="/tmp/pip-packages"
          if [ ! -d "$PIP_DIR/voyageai" ]; then
            echo "Installing semantic search dependencies..."
            pip install --target="$PIP_DIR" voyageai sqlite-vec --quiet 2>/dev/null || \
              echo "Warning: Could not install semantic search deps, continuing without them"
          fi
          export PYTHONPATH="$PIP_DIR:$PYTHONPATH"
          exec bookstuff-web "$@"
        '';

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
          contents = [ bookstuff pythonWithPkgs pkgs.cacert pkgs.bash pkgs.coreutils ];
          config = {
            Cmd = [ "${entrypoint}/bin/bookstuff-entrypoint" ];
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
