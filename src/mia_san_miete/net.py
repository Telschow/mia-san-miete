"""TLS helpers. Python from python.org on macOS ships no root certificates, so HTTPS and IMAP
fail with CERTIFICATE_VERIFY_FAILED. When `certifi` is installed its bundle is used."""

from __future__ import annotations

import ssl
import urllib.request
from typing import Any
from urllib.parse import urljoin

SSL_HINT = (
    "TLS certificates could not be verified. On macOS with Python from python.org run "
    "'pip install certifi' (it is then used automatically) or the 'Install Certificates.command' "
    "of your Python."
)


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def urlopen(req: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


def explain(exc: BaseException) -> str:
    """The error text, with a hint appended when it is a certificate problem."""
    text = f"{type(exc).__name__}: {exc}"
    return f"{text}\n{SSL_HINT}" if "CERTIFICATE_VERIFY_FAILED" in text else text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class RedirectProbe:
    """Callable: the Location header of the first redirect of a URL, without following it,
    sending cookies or reading the page. None when there is none; `last_status` then says why
    (the HTTP status, or the error name)."""

    def __init__(self, timeout: float = 10, user_agent: str = "mia-san-miete") -> None:
        self.timeout, self.user_agent = timeout, user_agent
        self.last_status: str = ""

    def __call__(self, url: str) -> str | None:
        import urllib.error

        opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=ssl_context()))
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                self.last_status = f"http {resp.status} without redirect"
                return None
        except urllib.error.HTTPError as exc:
            self.last_status = f"http {exc.code}"
            if 300 <= exc.code < 400 and exc.headers.get("Location"):
                return urljoin(url, exc.headers["Location"])     # Location may be relative
            return None


def redirect_location(url: str, timeout: float = 10, user_agent: str = "mia-san-miete") -> str | None:
    return RedirectProbe(timeout, user_agent)(url)
