import sqlite3

import pytest

from src.accounts import DevelopmentStore, InvalidSession, ServiceError, SupabaseStore
from src.workspace_state import restore, snapshot


def test_registration_sessions_and_account_deletion(tmp_path):
    path = tmp_path / "dev.sqlite3"
    store = DevelopmentStore(path)
    store.register("a@example.test", "example-strong-password")
    with sqlite3.connect(path) as db:
        salt, digest = db.execute("select salt, hash from accounts").fetchone()
        assert len(salt) == len(digest) == 32
        assert b"example-strong-password" not in path.read_bytes()
    with pytest.raises(ServiceError):
        store.login("a@example.test", "wrong")
    token = store.login("A@example.test", "example-strong-password")
    assert store.profile(token)["email"] == "a@example.test"
    store.logout(token)
    with pytest.raises(InvalidSession):
        store.profile(token)
    token = store.login("a@example.test", "example-strong-password")
    store.save(token, None, ("Project", "", "", "FASTA"), snapshot({"fasta_source": ("x.fa", b">x\nACTG", "upload")}))
    store.delete_account(token)
    with sqlite3.connect(path) as db:
        assert db.execute("select count(*) from projects").fetchone() == (0,)


def test_independent_client_restore_and_owner_isolation(tmp_path):
    path = tmp_path / "dev.sqlite3"
    first_client, second_client = DevelopmentStore(path), DevelopmentStore(path)
    first_client.register("a@example.test", "example-strong-password")
    first_client.register("b@example.test", "other-strong-password")
    first = first_client.login("a@example.test", "example-strong-password")
    same_owner = second_client.login("a@example.test", "example-strong-password")
    other = second_client.login("b@example.test", "other-strong-password")
    saved = {"fasta_source": ("sample.fa", b">a\nACGT", "upload"), "identity": 80.0}
    project = first_client.save(first, None, ("Study", "Plant", "Gene", "FASTA"), snapshot(saved))
    assert restore(second_client.load(same_owner, project)["payload"]) == saved
    assert second_client.list_projects(other) == []
    with pytest.raises(ServiceError):
        second_client.save(other, project, ("Other", "", "", ""), "{}")
    with pytest.raises(ServiceError):
        second_client.load(other, project)
    second_client.delete(other, project)
    second_client.rename(same_owner, project, "Renamed")
    assert first_client.list_projects(first)[0]["name"] == "Renamed"
    second_client.delete(same_owner, project)
    assert first_client.list_projects(first) == []


def test_supabase_refuses_privileged_client_key():
    with pytest.raises(ServiceError):
        SupabaseStore("https://example.invalid", "sb_secret_example")
