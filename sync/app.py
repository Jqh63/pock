"""
Pock sync — per-app JSON blob store, deployed alongside the WoL relay
on a small always-on VM, behind the existing Caddy (path /pock/*).

One blob per app (a few KB of JSON). The PWA keeps localStorage as the
UI/offline source and syncs asynchronously: pull on load, debounced push
on change, last-write-wins per app (client-side timestamps).

Security model (the endpoint is public, the PWA too):
- Bearer token required on EVERY operation, GET included — no anonymous
  read, no listing endpoint (blob names are not enumerable without the
  token). Absent and invalid tokens get the same 401 (no oracle).
- Constant-time token comparison (hmac.compare_digest)
- Sliding-window rate limit per source IP, applied before the token
  check (anti brute-force; X-Real-IP is Caddy-set, unforgeable)
- Size cap per blob + strict JSON-object validation — the endpoint
  cannot be used as an arbitrary file drop
- Atomic writes (tmp + rename), data dir owned by a dedicated user
- Runs as a non-privileged systemd user, ProtectSystem=strict

Cf. sync/README.md for the deploy / hardening procedure.
"""
import hmac
import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request, Response

SHARED_TOKEN = os.environ["POCK_SYNC_TOKEN"]

# Optional scoped tokens for sharing a subset of apps with another person
# (e.g. shared vehicle tracking, private book list). Format, space-separated:
#   POCK_SYNC_SCOPED_TOKENS="<token>:app1,app2 <token2>:app3"
# A scoped token reads/writes ONLY its listed apps (same blobs as the full
# token — that's the sharing); other apps answer 403. The full token keeps
# access to everything. Conflicts stay last-write-wins per app: acceptable
# because concurrent writes are rare in this usage (documented trade-off).
SCOPED_TOKENS: dict[str, frozenset[str]] = {}
for _entry in os.environ.get("POCK_SYNC_SCOPED_TOKENS", "").split():
    _tok, _, _apps = _entry.partition(":")
    if _tok and _apps:
        SCOPED_TOKENS[_tok] = frozenset(a for a in _apps.split(",") if a)

DATA_DIR = os.environ.get("POCK_SYNC_DATA_DIR", "/var/lib/pock-sync")
MAX_BLOB_BYTES = int(os.environ.get("POCK_SYNC_MAX_BLOB_BYTES", str(256 * 1024)))

# App names are short slugs (km, covoit, biblio, …). The whitelist regex
# doubles as path-traversal protection: the name is used as a filename.
APP_NAME_RE = re.compile(r"^[a-z0-9-]{1,32}$")

# Same in-memory sliding-window pattern as the WoL relay (single uvicorn
# worker, see pock-sync.service). Sized for a sync client (pull = 3 GETs
# per app load), generous for legit use, tight for token brute-force.
RATE_LIMIT_WINDOW_S = 60
RATE_LIMIT_MAX_REQ = 60
MAX_TRACKED_IPS = 4096
_rate_lock = threading.Lock()
_rate_state: dict[str, deque] = defaultdict(deque)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pock-sync")

# CORS is handled at the Caddy layer (same rationale as the WoL relay:
# headers must be present on Caddy-generated errors too).
app = FastAPI(title="Pock Sync", docs_url=None, redoc_url=None, openapi_url=None)


def client_ip(request: Request) -> str:
    # Caddy strips inbound X-Forwarded-For and sets X-Real-IP from its own
    # view of the connecting peer — the only value a client cannot forge.
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def rate_limited(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_S
    with _rate_lock:
        dq = _rate_state[ip]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if not dq:
            _rate_state.pop(ip, None)
            dq = _rate_state[ip]
        if len(dq) >= RATE_LIMIT_MAX_REQ:
            return True
        dq.append(now)
        if len(_rate_state) > MAX_TRACKED_IPS:
            stale = [k for k, d in _rate_state.items() if not d or d[-1] < cutoff]
            for k in stale:
                _rate_state.pop(k, None)
    return False


def token_eq(given: str, expected: str) -> bool:
    # Comparer des OCTETS : hmac.compare_digest(str, str) lève TypeError sur un
    # caractère non-ASCII — un Authorization forgé rendait un 500 + traceback
    # (même classe que le finding F7 du relais WoL, claude-security 2026-09-27).
    return hmac.compare_digest(given.encode("utf-8", "surrogateescape"),
                               expected.encode("utf-8", "surrogateescape"))


def check_access(request: Request, authorization: str | None, app_name: str) -> str:
    """Rate limit, then token, then name validation — in that order, so an
    unauthenticated caller learns nothing (not even which names are valid)."""
    ip = client_ip(request)
    if rate_limited(ip):
        logger.warning("sync ip=%s status=429 reason=rate_limit", ip)
        raise HTTPException(status_code=429, detail="rate limited")
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
    # Identical response for absent and invalid token (no oracle), and
    # constant-time comparison (no timing-based brute-force). Scoped tokens
    # are checked the same way; iteration order leaks nothing useful (the
    # set is tiny and every comparison is constant-time).
    allowed_apps = None  # None = full access
    if not token_eq(token, SHARED_TOKEN):
        for scoped, apps in SCOPED_TOKENS.items():
            if token_eq(token, scoped):
                allowed_apps = apps
                break
        else:
            logger.warning("sync ip=%s status=401 reason=bad_token", ip)
            raise HTTPException(status_code=401, detail="unauthorized")
    if not APP_NAME_RE.match(app_name):
        logger.warning("sync ip=%s status=400 reason=bad_app_name", ip)
        raise HTTPException(status_code=400, detail="invalid app name")
    # 403 (and not 401) is fine here: the caller has already proven a valid
    # token, and the app name comes from its own URL — no oracle opened.
    if allowed_apps is not None and app_name not in allowed_apps:
        logger.warning("sync ip=%s app=%s status=403 reason=out_of_scope", ip, app_name)
        raise HTTPException(status_code=403, detail="app not allowed for this token")
    return ip


def blob_path(app_name: str) -> str:
    return os.path.join(DATA_DIR, f"{app_name}.json")


@app.get("/pock/health")
def health():
    # Liveness only — never reveals blob names, sizes or token state.
    return {"status": "ok"}


@app.get("/pock/{app_name}")
def get_blob(app_name: str, request: Request, authorization: str | None = Header(None)):
    ip = check_access(request, authorization, app_name)
    path = blob_path(app_name)
    try:
        with open(path, "rb") as f:
            content = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="no blob")
    logger.info("sync ip=%s app=%s op=get status=200 bytes=%d", ip, app_name, len(content))
    return Response(content=content, media_type="application/json")


@app.put("/pock/{app_name}")
async def put_blob(app_name: str, request: Request, authorization: str | None = Header(None)):
    ip = check_access(request, authorization, app_name)
    body = await request.body()
    if len(body) > MAX_BLOB_BYTES:
        logger.warning("sync ip=%s app=%s op=put status=413 bytes=%d", ip, app_name, len(body))
        raise HTTPException(status_code=413, detail="blob too large")
    try:
        parsed = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="blob must be a JSON object")
    # Atomic write: a crash mid-write never leaves a truncated blob.
    tmp = blob_path(app_name) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, blob_path(app_name))
    logger.info("sync ip=%s app=%s op=put status=200 bytes=%d", ip, app_name, len(body))
    return {"stored": True, "bytes": len(body)}
