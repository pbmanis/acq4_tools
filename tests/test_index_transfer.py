import stat
from pathlib import Path
from types import SimpleNamespace

import paramiko
import pytest

from acq4_tools.tools import index_transfer as IT


class FakeSFTP:
    """An in-memory remote file system."""

    def __init__(self, existing=(), denied=(), unwritable=()):
        self.files = set(existing)
        self.denied = set(denied)
        self.unwritable = set(unwritable)
        self.puts = []

    def stat(self, remote):
        if remote in self.denied:
            raise PermissionError(remote)
        if remote not in self.files:
            raise FileNotFoundError(remote)
        return SimpleNamespace(st_mode=stat.S_IFREG)

    def put(self, local, remote):
        if remote in self.unwritable:
            raise FileNotFoundError(remote)
        self.puts.append((local, remote))
        self.files.add(remote)


def test_discover_days_from_parent_or_from_a_day(day_tree):
    (day_tree.parent / "not_a_day").mkdir()
    assert IT.discover_days(day_tree.parent) == [day_tree]
    assert IT.discover_days(day_tree) == [day_tree]


def test_finds_all_index_files_and_skips_appledouble(day_tree):
    (day_tree / "._.index").write_bytes(b"x")
    found = IT.find_index_files(day_tree)
    assert len(found) == 5
    assert all(p.name == ".index" for p in found)


def test_remote_path_keeps_day_layout_in_posix_form(day_tree):
    local = day_tree / "slice_000" / ".index"
    assert IT.remote_path_for(local, day_tree, "/remote/data") == (
        "/remote/data/2024.03.05_000/slice_000/.index"
    )


def make_items(*remotes):
    return [IT.TransferItem(Path(f"/local/{i}/.index"), r) for i, r in enumerate(remotes)]


def test_check_items_statuses():
    items = make_items("/r/present", "/r/absent", "/r/denied")
    IT.check_items(FakeSFTP(existing={"/r/present"}, denied={"/r/denied"}), items)
    assert items[0].status == IT.PRESENT
    assert items[1].status == IT.MISSING
    assert items[2].status.startswith("error:")


def test_upload_sends_only_missing_files():
    items = make_items("/r/present", "/r/absent")
    sftp = FakeSFTP(existing={"/r/present"})
    IT.check_items(sftp, items)
    assert IT.upload_missing(sftp, items) == 1
    assert [remote for _, remote in sftp.puts] == ["/r/absent"]
    assert items[1].status == "uploaded"


def test_upload_never_overwrites_a_file_that_appeared_after_the_check():
    items = make_items("/r/new")
    sftp = FakeSFTP()
    IT.check_items(sftp, items)
    sftp.files.add("/r/new")
    assert IT.upload_missing(sftp, items) == 0
    assert sftp.puts == []
    assert items[0].status == IT.PRESENT


def test_upload_failure_is_recorded_and_others_continue():
    items = make_items("/r/nodir/a", "/r/b")
    sftp = FakeSFTP(unwritable={"/r/nodir/a"})
    IT.check_items(sftp, items)
    assert IT.upload_missing(sftp, items) == 1
    assert items[0].status.startswith("failed:")
    assert items[1].status == "uploaded"


def test_connect_rejects_unknown_hosts_with_guidance(monkeypatch):
    calls = {}

    class FakeClient:
        def load_system_host_keys(self):
            calls["loaded"] = True

        def set_missing_host_key_policy(self, policy):
            calls["policy"] = policy

        def connect(self, **kwargs):
            raise paramiko.SSHException("Server 'h' not found in known_hosts")

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(IT.paramiko, "SSHClient", FakeClient)
    with pytest.raises(ConnectionError, match="ssh me@h"):
        IT.connect_sftp("h", 22, "me", "pw")
    assert calls["loaded"] and calls["closed"]
    assert isinstance(calls["policy"], paramiko.RejectPolicy)


def test_password_is_not_stored(qtbot, isolated_config, monkeypatch):
    window = IT.IndexTransferWindow()
    qtbot.addWidget(window)
    window.host.setText("server")
    window.username.setText("someone")
    window.remote_root.setText("/remote")
    window.password.setText("do-not-store")
    assert window._connection_settings()["password"] == "do-not-store"
    stored = (isolated_config / "history.json").read_text(encoding="utf-8")
    assert "server" in stored
    assert "do-not-store" not in stored
    window.close()
