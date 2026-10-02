"""Indexer tests with a fake Typesense: user data merged from SQLite, hidden respected,
a rewritten document never loses its note, prune still works, resync fixes drift."""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp())
os.environ.update(TYPESENSE_KEY="k", CLIPSTAGE_DB=str(TMP / "i.db"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import indexer
import store


class FakeDocs:
    def __init__(self):
        self.saved = {}

    def import_(self, batch, opts):
        for d in batch:
            if opts.get("action") == "update":
                self.saved.setdefault(d["id"], {}).update(d)
            else:
                self.saved[d["id"]] = dict(d)
        return [{"success": True}] * len(batch)

    def export(self):
        import json
        return "\n".join(json.dumps(d) for d in self.saved.values())

    def delete(self, *_a, **_k):
        pass


class FakeColl:
    def __init__(self):
        self.documents = FakeDocs()


class FakeClient:
    def __init__(self):
        self.c = FakeColl()
        self.collections = {indexer.COLLECTION: self.c}


_SAVED = {}


def teardown_module(_):
    """Put back what setup_module changed so other test files see the real configuration."""
    for k, v in _SAVED.items():
        setattr(indexer, k, v)


def setup_module(_):
    for k in ("VOLUMES_ROOT", "SCAN_VOLUMES", "DIRCACHE_FILE", "STATUS_FILE", "FFPROBE"):
        _SAVED[k] = getattr(indexer, k)
    (TMP / "vol" / "EDIT" / "NEWS").mkdir(parents=True)
    indexer.VOLUMES_ROOT = TMP / "vol"
    indexer.SCAN_VOLUMES = ["EDIT"]
    indexer.DIRCACHE_FILE = TMP / "dc.json"
    indexer.STATUS_FILE = TMP / "st.json"
    indexer.FFPROBE = None


def uid_for(p):
    return hashlib.md5(str(p).encode()).hexdigest()[:16]


def test_schema_has_separators_and_hidden():
    assert "_" in indexer.SCHEMA["token_separators"]
    assert {"hidden", "notes", "use_count"} <= {f["name"] for f in indexer.SCHEMA["fields"]}
    assert "tags" not in {f["name"] for f in indexer.SCHEMA["fields"]}


def test_merges_sqlite_user_data_and_keeps_note_on_rewrite(monkeypatch):
    f = TMP / "vol" / "EDIT" / "NEWS" / "Launch_First.mxf"
    f.write_bytes(b"x" * 2048)
    uid = uid_for(f)
    store.init()
    store.set_notes(uid, "from sqlite", str(f))
    store.bump_use_count(uid, str(f))
    store.set_hidden(uid, True, str(f))
    fc = FakeClient()
    monkeypatch.setattr(indexer, "client", fc)
    indexer.index_archive({}, full=True)
    d = fc.c.documents.saved[uid]
    assert d["notes"] == "from sqlite" and d["use_count"] == 1 and d["hidden"] is True
    assert "tags" not in d and d["volume"] == "EDIT" and d["folder"] == "NEWS"

    # File changed on disk; the OLD document (no SQLite row) held a note -> must survive the rewrite
    g = TMP / "vol" / "EDIT" / "NEWS" / "Other.mxf"
    g.write_bytes(b"y" * 4096)
    gid = uid_for(g)
    prev = {"id": gid, "path": str(g), "size_mb": 0.0, "date": "2000-01-01", "volume": "EDIT",
            "folder": "NEWS", "notes": "legacy note", "use_count": 3, "hidden": False}
    indexer.index_archive({gid: prev}, full=True)
    assert fc.c.documents.saved[gid]["notes"] == "legacy note"
    assert fc.c.documents.saved[gid]["use_count"] == 3


def test_resync_repairs_drift(monkeypatch):
    fc = FakeClient()
    monkeypatch.setattr(indexer, "client", fc)
    store.init()
    store.set_notes("drift0000000001", "newer", "/p")
    fc.c.documents.saved["drift0000000001"] = {"id": "drift0000000001", "notes": "stale"}
    indexer.resync_user_data(dict(fc.c.documents.saved))
    assert fc.c.documents.saved["drift0000000001"]["notes"] == "newer"


# -- multi-volume runs (--only A,B) --------------------------------------------

def test_parse_only_accepts_lists_repeats_and_any_case(monkeypatch):
    import indexer
    monkeypatch.setattr(indexer, "SCAN_VOLUMES", ["EDIT", "EDIT2", "PLAYOUT"])
    assert indexer.parse_only(["--prune"]) == []
    assert indexer.parse_only(["--only", "playout"]) == ["PLAYOUT"]
    assert indexer.parse_only(["--only", "PLAYOUT,edit"]) == ["EDIT", "PLAYOUT"]      # canonical order
    assert indexer.parse_only(["--only", "EDIT", "--only", "PLAYOUT", "--only", "edit"]) == ["EDIT", "PLAYOUT"]


def test_parse_only_rejects_typos_instead_of_running_everything(monkeypatch):
    import indexer
    monkeypatch.setattr(indexer, "SCAN_VOLUMES", ["EDIT", "PLAYOUT"])
    with pytest.raises(ValueError, match="PLAYOT"):
        indexer.parse_only(["--only", "EDIT,PLAYOT"])
