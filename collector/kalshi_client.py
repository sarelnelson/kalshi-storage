"""Minimal Kalshi REST client for market-data collection.

Supports anonymous reads and authenticated reads via Kalshi's API-key + RSA-PSS
request signing. Auth is optional for market data but raises rate limits.
"""
from __future__ import annotations

import base64
import time
from typing import Any, Optional

import requests

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

BASE_URL = "https://api.elections.kalshi.com"
API_PREFIX = "/trade-api/v2"


class KalshiClient:
    def __init__(self, api_key_id=None, private_key_path=None,
                 base_url=BASE_URL, timeout=10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key_id = api_key_id
        self._private_key = None
        if api_key_id and private_key_path:
            if not _HAS_CRYPTO:
                raise RuntimeError("pip install cryptography for auth mode")
            with open(private_key_path, "rb") as fh:
                self._private_key = serialization.load_pem_private_key(
                    fh.read(), password=None)
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    @property
    def authenticated(self) -> bool:
        return self._private_key is not None

    def _sign_headers(self, method, path):
        if not self.authenticated:
            return {}
        ts_ms = str(int(time.time() * 1000))
        message = f"{ts_ms}{method.upper()}{path}".encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }

    def _get(self, path, params=None):
        full_path = f"{API_PREFIX}{path}"
        url = f"{self.base_url}{full_path}"
        headers = self._sign_headers("GET", full_path)
        resp = self._session.get(url, params=params, headers=headers,
                                 timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_markets(self, series_ticker=None, status=None, limit=100, cursor=None):
        params = {"limit": limit}
        if series_ticker: params["series_ticker"] = series_ticker
        if status: params["status"] = status
        if cursor: params["cursor"] = cursor
        return self._get("/markets", params)

    def get_market(self, ticker): return self._get(f"/markets/{ticker}")

    def get_orderbook(self, ticker, depth=100):
        return self._get(f"/markets/{ticker}/orderbook", {"depth": depth})

    def get_trades(self, ticker, limit=100, cursor=None):
        params = {"ticker": ticker, "limit": limit}
        if cursor: params["cursor"] = cursor
        return self._get("/markets/trades", params)

    def get_exchange_status(self): return self._get("/exchange/status")
