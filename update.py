#!/usr/bin/env python3
"""
MAVERIC GSS Updater — Textual UI for checking and applying updates.

Works with both git clones and standalone source downloads.
- Git repo: uses git pull
- No git: downloads latest release ZIP from GitHub and replaces files

Usage:
    python3 update.py
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

import yaml

try:
    import urllib.request
    import json
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widget import Widget

# -- Styles (matching main TUI design spec) -----------------------------------

S_LABEL   = Style(color="#00bfff", bold=True)
S_VALUE   = Style(color="#ffffff", bold=True)
S_SUCCESS = Style(color="#00ff87", bold=True)
S_WARNING = Style(color="#ffd700", bold=True)
S_ERROR   = Style(color="#ff4444", bold=True)
S_DIM     = Style(color="#888888")
S_SEP     = Style(color="#707070")

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(REPO_DIR, "maveric_gss.yml")
GITHUB_REPO = "totesirfan/MAVERIC_GSS"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"

BAR_WIDTH = 40
BAR_FILL = "█"
BAR_EMPTY = "░"

# Files to preserve during ZIP update (operator-specific config)
PRESERVE_FILES = {"maveric_gss.yml", ".pending_queue.jsonl"}
# Directories to skip during ZIP update
SKIP_DIRS = {"logs", "generated_commands", "__pycache__", ".git"}

# -- Helpers -------------------------------------------------------------------

def _git_run(cmd):
    r = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def is_git_repo():
    rc, _, _ = _git_run(["git", "rev-parse", "--git-dir"])
    return rc == 0

def get_local_version():
    try:
        with open(CONFIG_FILE) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("general", {}).get("version", "unknown")
    except Exception as e:
        print(f"WARNING: could not read version: {e}", file=sys.stderr)
        return "unknown"

def parse_version(v):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)

# -- Git update path -----------------------------------------------------------

def git_get_remote_url():
    rc, out, _ = _git_run(["git", "remote", "get-url", "origin"])
    return out if rc == 0 and out else None

def git_get_latest_tag():
    _git_run(["git", "fetch", "--tags", "--quiet"])
    _, out, _ = _git_run(["git", "tag", "--sort=-v:refname"])
    for tag in out.splitlines():
        tag = tag.strip()
        if tag.startswith("v") and tag.count(".") >= 2:
            return tag
    return None

def git_has_local_changes():
    _, out, _ = _git_run(["git", "status", "--porcelain"])
    return bool(out), out

def git_get_changelog(local_ver):
    _, out, _ = _git_run(["git", "log", f"v{local_ver}..origin/main", "--oneline"])
    return out

def git_do_update(on_progress):
    """Git pull with stash. on_progress(pct, label) callback."""
    changes, _ = git_has_local_changes()
    stashed = False

    on_progress(0.2, "Stashing local changes..." if changes else "Preparing...")
    if changes:
        rc, _, err = _git_run(["git", "stash", "--include-untracked"])
        if rc != 0:
            return False, f"Stash failed: {err}"
        stashed = True

    on_progress(0.4, "Pulling from GitHub...")
    rc, out, err = _git_run(["git", "pull", "--rebase", "origin", "main"])
    if rc != 0:
        if stashed:
            _git_run(["git", "stash", "pop"])
        return False, f"Pull failed: {err or out}"

    on_progress(0.7, "Applying update...")
    time.sleep(0.3)

    if stashed:
        on_progress(0.8, "Restoring local changes...")
        rc, _, err = _git_run(["git", "stash", "pop"])
        if rc != 0:
            return True, "Updated but conflict restoring local changes. Run: git stash pop"

    on_progress(0.9, "Verifying...")
    return True, f"Updated to {get_local_version()}"

# -- ZIP download update path --------------------------------------------------

def api_get_latest_tag():
    """Fetch latest tag from GitHub API."""
    if not HAS_URLLIB:
        return None, "urllib not available"
    try:
        req = urllib.request.Request(f"{GITHUB_API}/tags",
                                     headers={"Accept": "application/vnd.github.v3+json",
                                              "User-Agent": "MAVERIC-GSS-Updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tags = json.loads(resp.read())
        for tag in tags:
            name = tag.get("name", "")
            if name.startswith("v") and name.count(".") >= 2:
                return name, None
        return None, "No release tags found"
    except Exception as e:
        return None, str(e)

def api_get_changelog(local_ver, remote_tag):
    """Fetch commit messages between versions from GitHub API."""
    try:
        url = f"{GITHUB_API}/compare/v{local_ver}...{remote_tag}"
        req = urllib.request.Request(url,
                                     headers={"Accept": "application/vnd.github.v3+json",
                                              "User-Agent": "MAVERIC-GSS-Updater"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        commits = data.get("commits", [])
        return "\n".join(c["commit"]["message"].split("\n")[0] for c in commits)
    except Exception as e:
        print(f"WARNING: could not fetch changelog: {e}", file=sys.stderr)
        return ""

def zip_do_update(remote_tag, on_progress):
    """Download ZIP from GitHub and replace source files. Preserves config."""
    zip_url = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{remote_tag}.zip"

    on_progress(0.2, "Downloading ZIP from GitHub...")
    try:
        req = urllib.request.Request(zip_url, headers={"User-Agent": "MAVERIC-GSS-Updater"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            data = bytearray()
            downloaded = 0
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                data.extend(chunk)
                downloaded += len(chunk)
                if total > 0:
                    dl_pct = 0.2 + 0.4 * (downloaded / total)
                    on_progress(dl_pct, f"Downloading... {downloaded // 1024}KB / {total // 1024}KB")
    except Exception as e:
        return False, f"Download failed: {e}"

    on_progress(0.6, "Extracting...")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        return False, f"Invalid ZIP: {e}"

    # Find the root directory inside the ZIP (e.g., MAVERIC_GSS-4.1.0/)
    zip_root = None
    for name in zf.namelist():
        parts = name.split("/")
        if len(parts) > 1 and parts[0]:
            zip_root = parts[0]
            break
    if not zip_root:
        return False, "ZIP has unexpected structure"

    on_progress(0.7, "Backing up config...")

    # Backup preserved files
    backups = {}
    for fname in PRESERVE_FILES:
        fpath = os.path.join(REPO_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath, "rb") as f:
                backups[fname] = f.read()

    on_progress(0.8, "Installing files...")

    # Extract new files, skipping preserved and skip dirs
    for info in zf.infolist():
        if info.is_dir():
            continue
        # Strip ZIP root prefix to get relative path
        rel = info.filename[len(zip_root) + 1:]
        if not rel:
            continue
        # Skip directories we don't want to overwrite
        top_dir = rel.split("/")[0] if "/" in rel else ""
        if top_dir in SKIP_DIRS:
            continue
        # Skip preserved files
        if rel in PRESERVE_FILES:
            continue

        dest = os.path.join(REPO_DIR, rel)
        dest_dir = os.path.dirname(dest)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as dst:
            dst.write(src.read())

    # Restore preserved files
    for fname, content in backups.items():
        with open(os.path.join(REPO_DIR, fname), "wb") as f:
            f.write(content)

    on_progress(0.95, "Verifying...")
    new_ver = get_local_version()
    on_progress(1.0, "Complete")
    return True, f"Updated to {new_ver}"

# -- Widget --------------------------------------------------------------------

class UpdatePanel(Widget):
    DEFAULT_CSS = "UpdatePanel { width: 100%; height: 100%; }"

    def __init__(self):
        super().__init__()
        self.info_lines = []
        self.state = "checking"
        self.local_ver = ""
        self.remote_ver = ""
        self.remote_tag = ""
        self.update_method = ""  # "git" or "zip"
        self.remote_url = ""
        self.changed_files = ""
        self.has_changes = False
        self.changelog = ""
        self.result_msg = ""
        self.progress = 0.0
        self.progress_label = ""

    def set_progress(self, pct, label=""):
        self.progress = max(0.0, min(1.0, pct))
        self.progress_label = label
        self.refresh()

    def add_info(self, label, value, style=S_VALUE):
        self.info_lines.append((label, value, style))
        self.refresh()

    def render(self):
        w = self.content_size.width or 80
        t = Text()

        # Title bar
        title = Text()
        title.append(" MAVERIC GSS UPDATER ", style="reverse bold #ffffff")
        t.append_text(title)
        t.append("\n")
        t.append("─" * w, style=S_SEP)

        # Info lines
        for label, value, style in self.info_lines:
            t.append("\n")
            t.append(f"  {label:<18}", style="#00bfff")
            t.append(str(value), style=style)

        # State content
        if self.state == "checking":
            t.append("\n\n")
            t.append_text(self._bar(w))

        elif self.state == "up_to_date":
            t.append("\n\n")
            t.append_text(self._bar(w))
            t.append("\n\n")
            t.append("  ✓ Already up to date", style=S_SUCCESS)
            t.append("\n\n")
            t.append("  Press any key to exit", style=S_DIM)

        elif self.state == "update_available":
            t.append("\n\n")
            t.append("  Update available: ", style=S_WARNING)
            t.append(self.local_ver, style=S_DIM)
            t.append(" → ", style=S_SEP)
            t.append(self.remote_ver, style=S_SUCCESS)

            if self.changelog:
                t.append("\n\n")
                t.append("  Changes:", style=S_LABEL)
                for line in self.changelog.splitlines()[:8]:
                    t.append(f"\n    {line.strip()}", style=S_DIM)
                total = len(self.changelog.splitlines())
                if total > 8:
                    t.append(f"\n    ... and {total - 8} more", style=S_DIM)

            if self.has_changes and self.update_method == "git":
                t.append("\n\n")
                t.append("  ⚠ Uncommitted local changes (will stash and restore):", style=S_WARNING)
                for line in self.changed_files.splitlines()[:5]:
                    t.append(f"\n    {line.strip()}", style=S_DIM)

            t.append("\n\n")
            method_label = "git pull" if self.update_method == "git" else "ZIP download"
            t.append(f"  Method: {method_label}", style=S_DIM)
            t.append("\n\n")
            t.append("  Enter", style=S_VALUE)
            t.append(": Update   ", style=S_DIM)
            t.append("Esc", style=S_VALUE)
            t.append(": Cancel", style=S_DIM)

        elif self.state == "updating":
            t.append("\n\n")
            t.append_text(self._bar(w))

        elif self.state == "done":
            t.append("\n\n")
            t.append_text(self._bar(w))
            t.append("\n\n")
            t.append(f"  ✓ {self.result_msg}", style=S_SUCCESS)
            t.append("\n\n")
            t.append("  Restart MAV_RX / MAV_TX to use the new version.", style=S_DIM)
            t.append("\n\n")
            t.append("  Press any key to exit", style=S_DIM)

        elif self.state == "error":
            t.append("\n\n")
            t.append_text(self._bar(w))
            t.append("\n\n")
            t.append(f"  ✖ {self.result_msg}", style=S_ERROR)
            t.append("\n\n")
            t.append("  Press any key to exit", style=S_DIM)

        return t

    def _bar(self, w):
        t = Text()
        bar_w = min(BAR_WIDTH, w - 20)
        filled = int(self.progress * bar_w)
        empty = bar_w - filled
        pct = int(self.progress * 100)
        t.append("  ")
        t.append(BAR_FILL * filled, style=S_SUCCESS)
        t.append(BAR_EMPTY * empty, style=S_SEP)
        t.append(f"  {pct:3d}%", style=S_VALUE if self.progress >= 1.0 else S_DIM)
        if self.progress_label:
            t.append(f"  {self.progress_label}", style=S_DIM)
        return t

# -- App -----------------------------------------------------------------------

TERMINAL_STATES = ("up_to_date", "done", "error")

class UpdateApp(App):
    CSS = "Screen { background: black; }"
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("enter", "confirm", "Confirm"),
    ]

    def compose(self) -> ComposeResult:
        yield UpdatePanel()

    def on_mount(self):
        self.panel = self.query_one(UpdatePanel)
        self.set_interval(1/30, self._tick)
        threading.Thread(target=self._check, daemon=True).start()

    def _tick(self):
        if self.panel.state in ("checking", "updating"):
            self.panel.refresh()

    def _check(self):
        p = self.panel
        p.set_progress(0.1, "Reading local version...")

        p.local_ver = get_local_version()
        p.add_info("Local version:", p.local_ver)

        use_git = is_git_repo()
        p.update_method = "git" if use_git else "zip"
        p.add_info("Method:", "git pull" if use_git else "ZIP download", S_DIM)

        if use_git:
            p.set_progress(0.3, "Checking remote...")
            p.remote_url = git_get_remote_url()
            if p.remote_url:
                p.add_info("Remote:", p.remote_url, S_DIM)

            p.set_progress(0.5, "Fetching tags from GitHub...")
            tag = git_get_latest_tag()
            if not tag:
                p.result_msg = "Could not fetch remote tags"
                p.state = "error"
                p.refresh()
                return
            p.remote_tag = tag
        else:
            p.set_progress(0.5, "Checking GitHub API...")
            tag, err = api_get_latest_tag()
            if not tag:
                p.result_msg = f"Could not reach GitHub: {err}"
                p.state = "error"
                p.refresh()
                return
            p.remote_tag = tag

        p.remote_ver = p.remote_tag.lstrip("v")
        up_to_date = parse_version(p.remote_tag) <= parse_version(p.local_ver)
        p.add_info("Remote version:", p.remote_ver, S_DIM if up_to_date else S_SUCCESS)

        p.set_progress(0.8, "Comparing...")

        if up_to_date:
            p.set_progress(1.0, "Done")
            p.state = "up_to_date"
            p.refresh()
            return

        p.set_progress(0.9, "Fetching changelog...")
        if use_git:
            p.changelog = git_get_changelog(p.local_ver)
            p.has_changes, p.changed_files = git_has_local_changes()
        else:
            p.changelog = api_get_changelog(p.local_ver, p.remote_tag)

        p.set_progress(1.0, "Ready")
        p.state = "update_available"
        p.refresh()

    def _do_update(self):
        p = self.panel
        p.set_progress(0.0, "Starting...")

        if p.update_method == "git":
            ok, msg = git_do_update(p.set_progress)
        else:
            ok, msg = zip_do_update(p.remote_tag, p.set_progress)

        p.result_msg = msg
        if ok:
            p.info_lines = []
            p.add_info("Previous version:", p.local_ver, S_DIM)
            p.add_info("Updated to:", get_local_version(), S_SUCCESS)
            p.set_progress(1.0, "Complete")
            p.state = "done"
        else:
            p.state = "error"
        p.refresh()

    def action_confirm(self):
        p = self.panel
        if p.state == "update_available":
            p.state = "updating"
            p.set_progress(0.0, "Starting...")
            threading.Thread(target=self._do_update, daemon=True).start()
        elif p.state in TERMINAL_STATES:
            self.exit()

    def action_cancel(self):
        self.exit()

    def on_key(self, event):
        if self.panel.state in TERMINAL_STATES:
            self.exit()


def main():
    UpdateApp().run()


if __name__ == "__main__":
    main()
