{
    description = "Development shell for Tunnelvision";

    inputs = {
        nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
        flake-utils.url = "github:numtide/flake-utils";
    };

    outputs = { nixpkgs, flake-utils, ... }:
        flake-utils.lib.eachDefaultSystem (system:
            let
                pkgs = import nixpkgs { inherit system; };
            in { devShells.default = pkgs.mkShell {
                packages = with pkgs; with python311Packages; [
                    python3
                    boto
                    flask
                    pillow
                    flask-migrate
                    flask-sqlalchemy
                    psycopg2
                    werkzeug
                ];
            }; }
        );
}
