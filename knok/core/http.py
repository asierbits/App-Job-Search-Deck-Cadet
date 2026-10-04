"""Acceso HTTP común. Todo el motor usa esta interfaz, así los tests la sustituyen por FakeHttp (sin red).

- User-Agent propio de knok: nunca se hace pasar por un navegador.
- Límite de tamaño por respuesta y timeouts cortos.
- Para leer webs públicas pequeñas con la cadena de certificados incompleta, se puede reintentar sin
  verificar el certificado (solo lectura de páginas públicas; NUNCA para APIs con credenciales).
"""
import json
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from knok.settings import get_settings


class HttpError(Exception):
    def __init__(self, status: int, url: str, message: str = ""):
        super().__init__(message or f"HTTP {status} en {url}")
        self.status = status
        self.url = url


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def content_type(self) -> str:
        return (self.headers.get("content-type") or "").split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        m = re.search(r"charset=([\w-]+)", self.headers.get("content-type") or "", re.I)
        try:
            return self.content.decode(m.group(1) if m else "utf-8", errors="ignore")
        except LookupError:
            return self.content.decode("utf-8", errors="ignore")

    def json(self):
        return json.loads(self.content.decode("utf-8", errors="replace"))

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Http(Protocol):
    def request(self, method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                data: dict | bytes | None = None, json_body=None, timeout: float = 20,
                max_bytes: int = 5_000_000, insecure_fallback: bool = False) -> Response: ...


class RealHttp:
    def __init__(self, user_agent: str | None = None):
        self.user_agent = user_agent or get_settings().crawler_user_agent

    def request(self, method, url, *, params=None, headers=None, data=None, json_body=None, timeout=20,
                max_bytes=5_000_000, insecure_fallback=False):
        try:
            return self._do(method, url, params, headers, data, json_body, timeout, max_bytes, True)
        except httpx.ConnectError as ex:
            if insecure_fallback and "CERTIFICATE_VERIFY_FAILED" in str(ex):
                return self._do(method, url, params, headers, data, json_body, timeout, max_bytes, False)
            raise

    def _do(self, method, url, params, headers, data, json_body, timeout, max_bytes, verify):
        h = {"User-Agent": self.user_agent, "Accept-Language": "es,en;q=0.8,de;q=0.6,fr;q=0.5"}
        h.update(headers or {})
        with httpx.Client(follow_redirects=True, timeout=timeout, verify=verify) as c:
            with c.stream(method, url, params=params, headers=h, data=data if isinstance(data, dict) else None,
                          content=data if isinstance(data, bytes) else None, json=json_body) as r:
                cuerpo = bytearray()
                for trozo in r.iter_bytes():
                    cuerpo += trozo
                    if len(cuerpo) >= max_bytes:
                        break
                return Response(url=str(r.url), status=r.status_code, content=bytes(cuerpo[:max_bytes]),
                                headers={k.lower(): v for k, v in r.headers.items()})


def get(http: Http, url: str, **kw) -> Response:
    """GET que lanza HttpError si la respuesta no es 2xx."""
    r = http.request("GET", url, **kw)
    if not r.ok:
        raise HttpError(r.status, url)
    return r


def get_json(http: Http, url: str, **kw):
    kw.setdefault("headers", {})
    kw["headers"] = {"Accept": "application/json", **kw["headers"]}
    return get(http, url, **kw).json()


class FakeHttp:
    """Doble para tests: rutas por prefijo de URL → (estado, cuerpo, content-type). Registra las llamadas."""

    def __init__(self, routes: dict | None = None):
        self.routes: dict[str, tuple[int, bytes | str, str]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        for k, v in (routes or {}).items():
            self.add(k, *v) if isinstance(v, tuple) else self.add(k, 200, v)

    def add(self, url_prefix: str, status: int = 200, body=b"", content_type: str = ""):
        if isinstance(body, (dict, list)):
            body, content_type = json.dumps(body), content_type or "application/json"
        self.routes[url_prefix] = (status, body, content_type or "text/html; charset=utf-8")
        return self

    def request(self, method, url, *, params=None, headers=None, data=None, json_body=None, timeout=20,
                max_bytes=5_000_000, insecure_fallback=False):
        full = url + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
        self.calls.append((method, full, json_body if json_body is not None else data))
        # El prefijo más largo que encaje gana
        for prefix in sorted(self.routes, key=len, reverse=True):
            if full.startswith(prefix) or url.startswith(prefix):
                status, body, ctype = self.routes[prefix]
                body = body.encode() if isinstance(body, str) else body
                return Response(url=url, status=status, content=body[:max_bytes], headers={"content-type": ctype})
        return Response(url=url, status=404, content=b"", headers={"content-type": "text/plain"})


_default: Http | None = None


def default_http() -> Http:
    return _default or RealHttp()


def set_default_http(h: Http | None) -> None:
    """Los tests y la Simulación sin red cambian el cliente por defecto."""
    global _default
    _default = h
