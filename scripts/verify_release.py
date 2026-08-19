#!/usr/bin/env python3
"""
handy-fleet-packaging — verify Handy's latest upstream release before
packaging it for internal fleet deployment.

This repo is PUBLIC and holds no Jamf/Intune/Vault credentials. This check
(the same ~7-day age gate and minisign signature verification used by the
internal watcher, AENG-496) is the only thing standing between "upstream
published something" and "we built and published an installer publicly."
A failed signature must never proceed to packaging.
"""

import base64
import binascii
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

REPO = "cjpais/Handy"
THIS_REPO = os.environ.get("GITHUB_REPOSITORY", "digitalocean/handy-fleet-packaging")
GITHUB_API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
AGE_GATE_DAYS = 7
DOWNLOAD_DIR = "verified"
# Base64 of the full minisign pubkey file (comment line + key line), as
# published by cjpais/Handy for its Tauri updater signing key.
MINISIGN_PUBKEY_FILE_B64 = (
    "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEJBQjcyMDk1MjA2NjAxRjkKUldUNUFXWWdsU0MzdXRRZi8zYzhqV2FaNUVDbDd2Rk5VM1IvWWowVXdmRFNKQ1BrMXF5RFFsLy8K"
)


def gh_get(url):
    # GITHUB_TOKEN (the repo's own free, automatic Actions token) is valid
    # for authenticated reads against the public github.com API too — this
    # avoids the 60/hour unauthenticated rate limit without needing any
    # extra secret. (Different from the internal GHE repo's problem: that
    # instance's GITHUB_TOKEN only works against its own GHE host.)
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_latest_handy_release():
    return gh_get(f"{GITHUB_API_URL}/repos/{REPO}/releases/latest")


def already_built(tag):
    try:
        gh_get(f"{GITHUB_API_URL}/repos/{THIS_REPO}/releases/tags/{tag}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def release_age_days(published_at_iso):
    published = datetime.fromisoformat(published_at_iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - published).days


def download(url, dest):
    urllib.request.urlretrieve(url, dest)


def sha256sum(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_sig_file(sig_path):
    """Handy's .sig assets are base64-encoded minisign signature text (a
    Tauri updater-action quirk), not raw minisign format. Decode in place
    when detected; leave already-raw files alone."""
    with open(sig_path, "rb") as f:
        raw = f.read()
    if raw.lstrip().startswith(b"untrusted comment:"):
        return
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return
    if decoded.startswith(b"untrusted comment:"):
        with open(sig_path, "wb") as f:
            f.write(decoded)


def write_minisign_pubkey_file():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    path = os.path.join(DOWNLOAD_DIR, "handy_minisign.pub")
    with open(path, "wb") as f:
        f.write(base64.b64decode(MINISIGN_PUBKEY_FILE_B64))
    return path


def verify_minisign(artifact_path, sig_path, pubkey_file):
    normalize_sig_file(sig_path)
    result = subprocess.run(
        ["minisign", "-Vm", artifact_path, "-x", sig_path, "-p", pubkey_file],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def set_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")


def main():
    release = fetch_latest_handy_release()
    tag = release["tag_name"]
    published_at = release["published_at"]

    if already_built(tag):
        print(f"{tag} already has a fleet-packaging release. Nothing to do.")
        set_output("ready", "false")
        set_output("tag", tag)
        return 0

    age_days = release_age_days(published_at)
    if age_days < AGE_GATE_DAYS:
        print(f"{tag} is only {age_days} day(s) old (need {AGE_GATE_DAYS}). Waiting.")
        set_output("ready", "false")
        set_output("tag", tag)
        return 0

    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    pubkey_file = write_minisign_pubkey_file()
    sig_names = {n for n in assets if n.endswith(".sig")}

    manifest = []
    failed = []
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    for name, url in assets.items():
        if name.endswith(".sig") or name == "latest.json":
            continue
        # .app.tar.gz + -setup.exe are needed to build .pkg/.intunewin;
        # .dmg/.msi are published as-is alongside them for anyone who wants
        # the original installer. Skip the ~500MB of Linux .rpm/.deb/
        # .AppImage assets this repo never touches.
        if not (
            name.endswith(".app.tar.gz")
            or name.endswith("-setup.exe")
            or name.endswith(".dmg")
            or name.endswith(".msi")
        ):
            continue
        dest = os.path.join(DOWNLOAD_DIR, name)
        download(url, dest)
        checksum = sha256sum(dest)
        verified = None
        sig_name = f"{name}.sig"
        if sig_name in sig_names:
            sig_dest = os.path.join(DOWNLOAD_DIR, sig_name)
            download(assets[sig_name], sig_dest)
            verified, _ = verify_minisign(dest, sig_dest, pubkey_file)
            if verified is False:
                failed.append(name)
        manifest.append({"name": name, "sha256": checksum, "signature_verified": verified})

    with open(os.path.join(DOWNLOAD_DIR, "manifest.json"), "w") as f:
        json.dump({"version": tag, "published_at": published_at, "artifacts": manifest}, f, indent=2)

    if failed:
        print(f"SIGNATURE VERIFICATION FAILED for: {', '.join(failed)} — refusing to package.")
        set_output("ready", "false")
        set_output("tag", tag)
        return 1

    print(f"{tag} verified clean — {len(manifest)} artifacts ready for packaging.")
    set_output("ready", "true")
    set_output("tag", tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
