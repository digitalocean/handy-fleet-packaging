# handy-fleet-packaging

Builds fleet-ready packages from [cjpais/Handy](https://github.com/cjpais/Handy) releases: `.pkg` (macOS, both architectures) and `.intunewin` (Windows, x64). Also passes through upstream Linux assets (`.deb`, `.rpm`, `.AppImage`).

**This repo is public and holds no credentials.** All MDM credentials and fleet-distribution logic live in a separate internal repo that consumes the artifacts built here.

## Pipeline

```
cron (daily) / workflow_dispatch
        │
        ▼
      check ── 7-day age gate + minisign signature verification
        │
        ├──► build-pkg (macOS, aarch64 + x64)
        └──► build-intunewin (Windows, x64)
        │
        ▼
      publish ── GitHub Release with manifest.json
        │
        ▼
      dispatch ── repository_dispatch to internal pipeline (manifest SHA256)
```

## Why this exists

Building `.pkg` and `.intunewin` requires macOS and Windows tooling. Internal GHE only has Linux runners. This public repo gets free hosted `macos-latest` / `windows-latest` runners and lets the internal side pull pre-built, pre-verified artifacts without credentials.

## Release assets

Each release includes: `.pkg` (per arch), `.intunewin` (x64), `.deb`, `.rpm`, `.AppImage`, and `manifest.json` with SHA256 checksums and verification status.

## Setup

| Secret | Purpose |
|--------|---------|
| `INTERNAL_DISPATCH_TOKEN` | PAT for `repository_dispatch` to internal GHE |
| `INTERNAL_API_URL` | Internal GHE API base URL |
| `INTERNAL_REPO` | Internal repo (`org/handy-release`) |
