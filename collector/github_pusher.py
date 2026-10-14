"""GitHub batch pusher: commits completed window files to a local git clone."""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

LOG = logging.getLogger("pusher")


class GitHubPusher:
    def __init__(self, repo_dir, dest_subdir="data", min_push_interval=60.0,
                 git_user_name="kalshi-collector",
                 git_user_email="kalshi-collector@example.com"):
        self.repo_dir = Path(repo_dir)
        self.dest_dir = self.repo_dir / dest_subdir
        self.min_push_interval = min_push_interval
        self.git_user_name = git_user_name
        self.git_user_email = git_user_email
        self._lock = threading.Lock()
        self._last_push = 0.0
        self._pending = False
        if not (self.repo_dir / ".git").exists():
            raise RuntimeError(f"{self.repo_dir} is not a git repository")
        self.dest_dir.mkdir(parents=True, exist_ok=True)

    def _git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo_dir), *args],
                              capture_output=True, text=True, check=False)

    def stage_window(self, window_path):
        with self._lock:
            try:
                shutil.copy2(window_path, self.dest_dir / Path(window_path).name)
                self._pending = True
                LOG.info("staged %s", Path(window_path).name)
            except Exception:
                LOG.exception("failed to stage %s", window_path)
                return
            self._maybe_push_locked()

    def _maybe_push_locked(self):
        now = time.monotonic()
        if not self._pending:
            return
        if now - self._last_push < self.min_push_interval:
            LOG.debug("push throttled; will retry on next window")
            return
        self._push_locked()

    def _push_locked(self):
        self._git("config", "user.name", self.git_user_name)
        self._git("config", "user.email", self.git_user_email)
        if self._git("add", "-A").returncode != 0:
            LOG.error("git add failed")
            return
        status = self._git("status", "--porcelain")
        if not status.stdout.strip():
            self._pending = False
            return
        msg = f"data: kalshi btc15 update {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
        if self._git("commit", "-m", msg).returncode != 0:
            LOG.error("git commit failed")
            return
        push = self._git("push")
        if push.returncode != 0:
            LOG.error("git push failed: %s", push.stderr.strip())
            return
        LOG.info("pushed to GitHub: %s", msg)
        self._last_push = time.monotonic()
        self._pending = False
