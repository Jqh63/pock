# Écriture conditionnelle : un PUT qui porte `base` (updatedAt de la version
# serveur sur laquelle le client a travaillé) est refusé en 409 si le blob a
# bougé entre-temps — sinon un appareil en retard écrase la saisie d'un autre
# (perte constatée en audit, 2026-10-11). Sans `base` (client d'avant le
# correctif, encore en cache SW) : accepté, comportement historique.
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

H = {"Authorization": "Bearer test-token"}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    getattr(sync, "_rate_state", {}).clear()
    for f in os.listdir(sync.DATA_DIR):
        os.remove(os.path.join(sync.DATA_DIR, f))
    return TestClient(sync.app, raise_server_exceptions=False)


def put(client, **blob):
    return client.put("/pock/conflict", headers=H, json={"data": {}, **blob})


def test_put_on_current_base_is_accepted(client):
    assert put(client, base=None, updatedAt=1).status_code == 200
    assert put(client, base=1, updatedAt=2).status_code == 200
    assert client.get("/pock/conflict", headers=H).json()["updatedAt"] == 2


def test_put_on_stale_base_is_refused(client):
    assert put(client, base=None, updatedAt=1).status_code == 200
    assert put(client, base=1, updatedAt=2).status_code == 200
    # Un 2ᵉ appareil a travaillé sur la version 1 : il ne doit pas écraser 2.
    assert put(client, base=1, updatedAt=3).status_code == 409
    assert client.get("/pock/conflict", headers=H).json()["updatedAt"] == 2


def test_first_push_refused_when_blob_already_exists(client):
    # base=None = « je crois qu'il n'y a pas encore de blob ».
    assert put(client, base=None, updatedAt=1).status_code == 200
    assert put(client, base=None, updatedAt=5).status_code == 409


def test_legacy_put_without_base_still_accepted(client):
    assert put(client, updatedAt=1).status_code == 200
    assert put(client, updatedAt=0).status_code == 200
