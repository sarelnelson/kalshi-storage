"""Entrypoint: wires config -> client -> collector -> GitHub pusher."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from collector import Collector
from kalshi_client import KalshiClient


def _setup_logging():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout)


def main():
    _setup_logging()
    log = logging.getLogger("run")
    api_key_id = os.environ.get("KALSHI_API_KEY_ID") or None
    private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH") or None
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    poll_interval = float(os.environ.get("POLL_INTERVAL", "1.0"))
    data_dir.mkdir(parents=True, exist_ok=True)
    client = KalshiClient(api_key_id=api_key_id, private_key_path=private_key_path)
    on_window_complete = None
    repo_dir = os.environ.get("GITHUB_REPO_DIR") or None
    if repo_dir:
        from github_pusher import GitHubPusher
        pusher = GitHubPusher(
            repo_dir=Path(repo_dir),
            dest_subdir=os.environ.get("GITHUB_DEST_SUBDIR", "data"),
            min_push_interval=float(os.environ.get("GIT_MIN_PUSH_INTERVAL", "60")),
            git_user_name=os.environ.get("GIT_USER_NAME", "kalshi-collector"),
            git_user_email=os.environ.get("GIT_USER_EMAIL",
                                          "kalshi-collector@example.com"))
        on_window_complete = pusher.stage_window
        log.info("GitHub push enabled -> %s", repo_dir)
    else:
        log.warning("GITHUB_REPO_DIR unset; running local-only (no push)")
    collector = Collector(client=client, data_dir=data_dir,
                          poll_interval=poll_interval,
                          on_window_complete=on_window_complete)
    collector.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
