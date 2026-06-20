{
  description = "Development shell for brobizz-usage";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    {
      nixpkgs,
      ...
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          runtimeLibraries = pkgs.lib.makeLibraryPath [
            pkgs.stdenv.cc.cc.lib
          ];
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python314
              pkgs.uv
              pkgs.playwright-test
              pkgs.playwright-driver.browsers-chromium
            ];

            shellHook = ''
              export UV_PYTHON="${pkgs.python314}"
              export UV_PROJECT_ENVIRONMENT=".venv"
              export UV_LINK_MODE=copy
              export LD_LIBRARY_PATH="${runtimeLibraries}:''${LD_LIBRARY_PATH:-}"
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=true
            '';
          };
        }
      );
    };
}
