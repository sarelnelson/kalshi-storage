"""Kalshi BTC 15-minute market data collector."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from kalshi_client import KalshiClient

LOG = logging.getLogger("collector")
SERIES_TICKER = "KXBTC15M"


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


class WindowWriter:
    def __init__(self, data_dir, ticker):
        self.ticker = ticker
        self.path = data_dir / f"{ticker}.ndjson"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self._seen_trade_ids = set()

    def write(self, record):
        self._fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def mark_trades_seen(self, trade_ids):
        self._seen_trade_ids.update(trade_ids)

    def already_seen(self, trade_id):
        return trade_id in self._seen_trade_ids

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


class Collector:
    def __init__(self, client, data_dir, poll_interval=1.0, on_window_complete=None):
        self.client = client
        self.data_dir = data_dir
        self.poll_interval = poll_interval
        self.on_window_complete = on_window_complete
        self._writers = {}

    def _get_open_markets(self):
        resp = self.client.get_markets(series_ticker=SERIES_TICKER,
                                       status="open", limit=100)
        return resp.get("markets", [])

    def _writer_for(self, ticker):
        w = self._writers.get(ticker)
        if w is None:
            LOG.info("opening new window file for %s", ticker)
            w = WindowWriter(self.data_dir, ticker)
            self._writers[ticker] = w
        return w

    def _retire_closed_windows(self, open_tickers):
        for ticker in list(self._writers.keys()):
            if ticker not in open_tickers:
                LOG.info("window %s closed; finalizing", ticker)
                writer = self._writers.pop(ticker)
                writer.close()
                if self.on_window_complete:
                    try:
                        self.on_window_complete(writer.path)
                    except Exception:
                        LOG.exception("on_window_complete failed for %s", ticker)

    def _capture_once(self):
        captured_at = _utcnow_iso()
        markets = self._get_open_markets()
        open_tickers = {m["ticker"] for m in markets}
        for market in markets:
            ticker = market["ticker"]
            writer = self._writer_for(ticker)
            writer.write({"_type": "market", "_captured_at": captured_at,
                          "ticker": ticker, "data": market})
            try:
                ob = self.client.get_orderbook(ticker, depth=100)
                writer.write({"_type": "orderbook", "_captured_at": captured_at,
                              "ticker": ticker, "data": ob.get("orderbook_fp", ob)})
            except Exception:
                LOG.exception("orderbook fetch failed for %s", ticker)
            try:
                trades_resp = self.client.get_trades(ticker, limit=100)
                new_trades = []
                for t in trades_resp.get("trades", []):
                    tid = t.get("trade_id")
                    if tid and not writer.already_seen(tid):
                        new_trades.append(t)
                if new_trades:
                    writer.write({"_type": "trades", "_captured_at": captured_at,
                                  "ticker": ticker, "data": new_trades})
                    writer.mark_trades_seen(
                        [t["trade_id"] for t in new_trades if t.get("trade_id")])
            except Exception:
                LOG.exception("trades fetch failed for %s", ticker)
        self._retire_closed_windows(open_tickers)

    def run_forever(self):
        LOG.info("collector starting (series=%s, interval=%.2fs, auth=%s)",
                 SERIES_TICKER, self.poll_interval, self.client.authenticated)
        while True:
            start = time.monotonic()
            try:
                self._capture_once()
            except Exception:
                LOG.exception("capture cycle failed; continuing")
            elapsed = time.monotonic() - start
            time.sleep(max(0.0, self.poll_interval - elapsed))
