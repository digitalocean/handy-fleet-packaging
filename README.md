# handy-fleet-packaging

Builds internal-fleet-ready packages from [cjpais/Handy](https://github.com/cjpais/Handy)'s public releases: a real `.pkg` (via `pkgbuild` on `macos-latest`) and a real `.intunewin` (via Microsoft's Win32 Content Prep Tool on `windows-latest`).

**This repo is public and holds no credentials — that's intentional.** It only ever reads public data and publishes public build artifacts. All Jamf/Intune/Vault credentials and the actual fleet-distribution logic live in a separate internal repo, which pulls the artifacts built here.

## Flow

1. Daily cron (+ manual `workflow_dispatch`) checks `cjpais/Handy`'s latest release.
2. If it's already been built here, or is younger than 7 days, stop.
3. Download the macOS `.app.tar.gz` and Windows `-setup.exe` assets, verify each against Handy's minisign signature. **A failed signature stops everything here** — nothing gets packaged or published.
4. Build a `.pkg` per macOS arch, a `.intunewin` per Windows arch.
5. Publish all of it as a GitHub Release on this repo, tagged to match Handy's version, alongside a `manifest.json` with checksums and verification results.

## Why this exists

Building `.pkg`/`.intunewin` needs macOS- and Windows-native tooling our internal GHE only has Linux runners for. Splitting this into a public repo gets free hosted `macos-latest`/`windows-latest` runners and lets the internal side pull already-built, already-verified artifacts without needing any credential to do so.
