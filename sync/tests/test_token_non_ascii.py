# Même classe que le finding F7 du relais WoL (claude-security, 2026-09-27) :
# hmac.compare_digest(str, str) lève TypeError sur un caractère non-ASCII, donc
# un Authorization forgé rendait un 500 + traceback au lieu d'un 401.
# Lancement : cd sync && python3 -m pytest -q tests/
import os
import sys
import tempfile

import pytest

os.environ.setdefault("POCK_SYNC_TOKEN", "test-token")
os.environ.setdefault("POCK_SYNC_SCOPED_TOKENS", "scoped-token:demo")
os.environ.setdefault("POCK_SYNC_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as sync  # noqa: E402


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    getattr(sync, "_rate_state", {}).clear()
    return TestClient(sync.app, raise_server_exceptions=False)


def test_non_ascii_token_is_rejected_not_crashed(client):
    h = {"Authorization": "Bearer t\xe9st".encode("latin-1")}
    assert client.get("/pock/demo", headers=h).status_code == 401


@pytest.mark.parametrize("token", ["test-token", "scoped-token"])
def test_valid_tokens_still_accepted(client, token):
    # Contrôle positif : le correctif ne doit refuser ni le token global
    # ni un token restreint à son app.
    r = client.get("/pock/demo", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code not in (401, 500), r.status_code
