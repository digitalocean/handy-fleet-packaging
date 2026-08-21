#!/usr/bin/env python3
"""Verify Handy upstream release: 7-day age gate + minisign signature check."""

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
MINISIGN_PUBKEY_FILE_B64 = (
    "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEJBQjcyMDk1MjA2NjAxRjkK"
    "UldUNUFXWWdsU0MzdXRRZi8zYzhqV2FaNUVDbDd2Rk5VM1IvWWowVXdmRFNKQ1BrMXF5RFFsLy8K"
)

WANTED_EXTENSIONS = (
    ".app.tar.gz", "-setup.exe", ".dmg", ".msi",
    ".deb", ".rpm", ".AppImage",
)


def gh_get(url):
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


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
    """Decode base64-wrapped minisign sigs (Tauri updater quirk) in place."""
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
        capture_output=True, text=True,
    )
    return result.returncode == 0


def set_output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")


def is_wanted(name):
    return any(name.endswith(ext) for ext in WANTED_EXTENSIONS)


def main():
    release = gh_get(f"{GITHUB_API_URL}/repos/{REPO}/releases/latest")
    tag = release["tag_name"]
    published_at = release["published_at"]

    if already_built(tag):
        print(f"{tag} already built.")
        set_output("ready", "false")
        set_output("tag", tag)
        return 0

    age_days = release_age_days(published_at)
    if age_days < AGE_GATE_DAYS:
        print(f"{tag} is {age_days}d old (need {AGE_GATE_DAYS}). Waiting.")
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
        if not is_wanted(name):
            continue

        dest = os.path.join(DOWNLOAD_DIR, name)
        download(url, dest)
        checksum = sha256sum(dest)
        verified = None
        sig_name = f"{name}.sig"
        if sig_name in sig_names:
            sig_dest = os.path.join(DOWNLOAD_DIR, sig_name)
            download(assets[sig_name], sig_dest)
            verified = verify_minisign(dest, sig_dest, pubkey_file)
            if not verified:
                failed.append(name)
        manifest.append({"name": name, "sha256": checksum, "signature_verified": verified})

    with open(os.path.join(DOWNLOAD_DIR, "manifest.json"), "w") as f:
        json.dump({"version": tag, "published_at": published_at, "artifacts": manifest}, f, indent=2)

    if failed:
        print(f"SIGNATURE FAILED: {', '.join(failed)}")
        set_output("ready", "false")
        set_output("tag", tag)
        return 1

    print(f"{tag} verified — {len(manifest)} artifacts ready.")
    set_output("ready", "true")
    set_output("tag", tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
