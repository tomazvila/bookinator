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

        # sqlite-vec: fetch platform-specific wheel from PyPI
        sqliteVecWheel = {
          x86_64-linux = {
            url = "https://files.pythonhosted.org/packages/59/56/6ff304d917ee79da769708dad0aed5fd34c72cbd0ae5e38bcc56cdc652a4/sqlite_vec-0.1.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.manylinux1_x86_64.whl";
            sha256 = "ad654283cb9c059852ce2d82018c757b06a705ada568f8b126022a131189818e";
          };
          aarch64-linux = {
            url = "https://files.pythonhosted.org/packages/59/56/6ff304d917ee79da769708dad0aed5fd34c72cbd0ae5e38bcc56cdc652a4/sqlite_vec-0.1.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.manylinux1_x86_64.whl";
            sha256 = "ad654283cb9c059852ce2d82018c757b06a705ada568f8b126022a131189818e";
          };
          aarch64-darwin = {
            url = "https://files.pythonhosted.org/packages/e6/c9/1cd2f59b539096cd2ce6b540247b2dfe3c47ba04d9368b5e8e3dc86498d4/sqlite_vec-0.1.7-py3-none-macosx_11_0_arm64.whl";
            sha256 = "6d272593d1b45ec7ea289b160ee6e5fafbaa6e1f5ba15f1305c012b0bda43653";
          };
          x86_64-darwin = {
            url = "https://files.pythonhosted.org/packages/e6/c9/1cd2f59b539096cd2ce6b540247b2dfe3c47ba04d9368b5e8e3dc86498d4/sqlite_vec-0.1.7-py3-none-macosx_11_0_arm64.whl";
            sha256 = "6d272593d1b45ec7ea289b160ee6e5fafbaa6e1f5ba15f1305c012b0bda43653";
          };
        }.${system};

        sqlite-vec = pythonPkgs.buildPythonPackage {
          pname = "sqlite-vec";
          version = "0.1.7";
          format = "wheel";
          src = pkgs.fetchurl {
            inherit (sqliteVecWheel) url sha256;
          };
          doCheck = false;
        };

        # Fetch all-MiniLM-L6-v2 ONNX model files from HuggingFace
        embeddingModel = pkgs.stdenvNoCC.mkDerivation {
          pname = "all-MiniLM-L6-v2-onnx";
          version = "1.0.2";

          srcs = [
            (pkgs.fetchurl {
              url = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx";
              sha256 = "0lk40hb4cll24q8q504gwdybnadmvd16805wisgii7sqwhpxgmbg";
              name = "model.onnx";
            })
            (pkgs.fetchurl {
              url = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json";
              sha256 = "0dr0aw8z8c5awl2spvi778d5dchi8vvv25vz79gbpx9bixic6l5y";
              name = "tokenizer.json";
            })
          ];

          dontUnpack = true;
          installPhase = ''
            mkdir -p $out
            for src in $srcs; do
              name=$(stripHash "$src")
              cp "$src" "$out/$name"
            done
          '';
        };

        allNixPkgs = ps: [
          ps.click
          ps.anthropic
          ps.ebooklib
          ps.pymupdf
          ps.flask
          ps.argon2-cffi
          ps.requests
          ps.numpy
          ps.onnxruntime
          ps.tokenizers
        ];

        bookstuff = pythonPkgs.buildPythonApplication {
          pname = "bookstuff";
          version = "0.1.0";
          src = ./.;
          format = "pyproject";

          nativeBuildInputs = [ pythonPkgs.setuptools ];

          propagatedBuildInputs = (allNixPkgs pythonPkgs) ++ [ sqlite-vec ];

          checkInputs = [ pythonPkgs.pytest ];

          doCheck = false;
        };

        devShell = pkgs.mkShell {
          packages = [
            (python.withPackages (ps: (allNixPkgs ps) ++ [ ps.pytest sqlite-vec ]))
            pkgs.rsync
          ];
          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
          '';
        };

        dockerImage = pkgs.dockerTools.buildLayeredImage {
          name = "books-web";
          tag = "latest";
          contents = [ bookstuff embeddingModel pkgs.cacert ];
          config = {
            Cmd = [ "bookstuff-web" ];
            Env = [
              "BOOKS_DIR=/books"
              "PORT=5001"
              "EMBEDDING_MODEL_DIR=/model"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            ];
            ExposedPorts = { "5001/tcp" = {}; };
          };
          # Place model files at /model in the image
          extraCommands = ''
            mkdir -p model
            cp ${embeddingModel}/model.onnx model/
            cp ${embeddingModel}/tokenizer.json model/
          '';
        };

        devServer = pkgs.writeShellScriptBin "bookstuff-dev" ''
          export PYTHONPATH="${self}/src:$PYTHONPATH"
          export BOOKS_DIR="''${BOOKS_DIR:-/tmp/books-local}"
          export PORT="''${PORT:-5001}"
          echo "Starting dev server on http://localhost:$PORT (BOOKS_DIR=$BOOKS_DIR)"
          exec ${python.withPackages (ps: (allNixPkgs ps) ++ [ sqlite-vec ])}/bin/python -m bookstuff.web.app
        '';
      in {
        packages.default = bookstuff;
        packages.docker = dockerImage;
        packages.dev = devServer;
        packages.embeddingModel = embeddingModel;
        apps.dev = {
          type = "app";
          program = "${devServer}/bin/bookstuff-dev";
        };
        devShells.default = devShell;
      }
    );
}
