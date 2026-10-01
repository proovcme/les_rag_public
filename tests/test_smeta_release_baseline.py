from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from tools import smeta_release_baseline as baseline


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_root(root: Path, *, norms: int = 2, fsem_rows: int = 2) -> Path:
    source = root / "data/gesn_base/gesn2022_unified.parquet"
    base = root / "data/smeta_base/les_smeta_base.sqlite"
    fsem = root / "data/smeta_base/fsem_2022.sqlite"
    pricebook = root / "data/price_base/sankt-peterburg_2kv2026.parquet"
    source.parent.mkdir(parents=True)
    base.parent.mkdir(parents=True)
    pricebook.parent.mkdir(parents=True)
    source.write_bytes(b"typed-parquet-fixture")
    with closing(sqlite3.connect(base)) as conn, conn:
        conn.executescript("CREATE TABLE norms(norm_key TEXT); CREATE TABLE resources(norm_key TEXT);")
        conn.executemany("INSERT INTO norms VALUES(?)", [(f"ГЭСН:{i}",) for i in range(norms)])
        conn.executemany("INSERT INTO resources VALUES(?)", [(f"ГЭСН:{i}",) for i in range(norms * 2)])
    with closing(sqlite3.connect(fsem)) as conn, conn:
        conn.execute("CREATE TABLE machines(machine_code TEXT)")
        conn.executemany("INSERT INTO machines VALUES(?)", [(str(i),) for i in range(fsem_rows)])
    pq.write_table(
        pa.table(
            {
                "code": ["1-100-10", "4-100-040"],
                "name": ["Рабочие", "Машинисты"],
                "unit": ["чел.-ч", "чел.-ч"],
                "price_current_eff": [500.0, 600.0],
                "region": ["Санкт-Петербург", "Санкт-Петербург"],
                "quarter": ["2 квартал 2026 г.", "2 квартал 2026 г."],
            }
        ),
        pricebook,
    )
    manifest = {
        "schema": "les_smeta_base_v2",
        "source": {"sha256": _sha(source)},
        "output": {"norms": norms, "resources": norms * 2},
    }
    integrity = {
        "schema": "les_smeta_base_integrity_v1",
        "verdict": "passed",
        "source_sha256": _sha(source),
        "base_sha256": _sha(base),
        "checks": {name: {"failures": 0} for name in baseline.REQUIRED_ZERO_CHECKS},
    }
    fsem_manifest = {
        "schema": "fsem_2022_catalog_manifest_v1",
        "verdict": "passed",
        "output": {"rows": fsem_rows, "sha256": _sha(fsem)},
    }
    (base.parent / "les_smeta_base_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base.parent / "les_smeta_base_integrity.json").write_text(json.dumps(integrity), encoding="utf-8")
    (base.parent / "fsem_2022_manifest.json").write_text(json.dumps(fsem_manifest), encoding="utf-8")
    return root


def test_release_baseline_roundtrip_provisions_clean_state(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"

    created = baseline.create_archive(
        source_root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    verified = baseline.verify_archive(archive)
    installed = baseline.provision_archive(archive, tmp_path / "state")

    assert created["norm_count"] == 2
    assert verified["schema"] == "les.smeta.release-baseline.v1"
    assert installed["action"] == "installed"
    assert installed["norm_count"] == 2
    assert installed["pricebook_rows"] == 2
    assert (tmp_path / "state/data/price_base/sankt-peterburg_2kv2026.parquet").is_file()
    packaged_integrity = json.loads(
        (tmp_path / "state/data/smeta_base/les_smeta_base_integrity.json").read_text(encoding="utf-8")
    )
    assert packaged_integrity["checks"]["minimum_norms"]["minimum"] == 2
    packaged_manifest = json.loads(
        (tmp_path / "state/data/smeta_base/les_smeta_base_manifest.json").read_text(encoding="utf-8")
    )
    assert packaged_manifest["minimum_norms"] == 2


def test_sqlite_count_releases_file_handle(monkeypatch, tmp_path: Path):
    class _Cursor:
        @staticmethod
        def fetchone():
            return (7,)

    class _Connection:
        closed = False

        @staticmethod
        def execute(_query: str):
            return _Cursor()

        def close(self):
            self.closed = True

    connection = _Connection()
    monkeypatch.setattr(baseline.sqlite3, "connect", lambda *_args, **_kwargs: connection)

    assert baseline._sqlite_count(tmp_path / "locked-on-windows.sqlite", "machines") == 7
    assert connection.closed is True


def test_release_baseline_keeps_complete_existing_state(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(
        source_root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    state = tmp_path / "state"
    baseline.provision_archive(archive, state)

    assert baseline.provision_archive(archive, state)["action"] == "kept_existing"


def test_release_baseline_refuses_partial_existing_state(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(
        source_root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    state = tmp_path / "state"
    partial = state / "data/smeta_base/les_smeta_base.sqlite"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"user-state")

    with pytest.raises(baseline.BaselineError, match="refusing to overwrite"):
        baseline.provision_archive(archive, state)
    assert partial.read_bytes() == b"user-state"


def test_release_baseline_repair_backs_up_partial_state_and_restores_complete_set(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(
        source_root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    state = tmp_path / "state"
    partial = state / "data/smeta_base/les_smeta_base.sqlite"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"broken-user-state")

    repaired = baseline.repair_archive(archive, state)

    assert repaired["action"] == "repaired"
    assert repaired["norm_count"] == 2
    backup = Path(repaired["backup"]) / "data/smeta_base/les_smeta_base.sqlite"
    assert backup.read_bytes() == b"broken-user-state"
    assert baseline.validate_root(
        state, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )["ok"] is True


def test_release_baseline_repair_upgrades_valid_but_older_state(tmp_path: Path):
    old_root = _fixture_root(tmp_path / "old", norms=2)
    release_root = _fixture_root(tmp_path / "release", norms=3)
    old_archive = tmp_path / "old.zip"
    release_archive = tmp_path / "release.zip"
    baseline.create_archive(
        old_root, old_archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    baseline.create_archive(
        release_root, release_archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    state = tmp_path / "state"
    baseline.provision_archive(old_archive, state)

    repaired = baseline.repair_archive(release_archive, state)

    assert repaired["action"] == "repaired"
    assert repaired["norm_count"] == 3
    assert "norms=2<3" in repaired["reason"]
    assert Path(repaired["backup"]).is_dir()


def test_release_baseline_rejects_norm_count_regression(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source", norms=1)

    with pytest.raises(baseline.BaselineError, match="1 < 2 norms"):
        baseline.create_archive(
            source_root,
            tmp_path / "baseline.zip",
            minimum_norms=2,
            minimum_fsem_rows=2,
            minimum_price_rows=2,
        )


def test_release_baseline_rejects_corrupt_archive(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(
        source_root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    raw = bytearray(archive.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    archive.write_bytes(raw)

    with pytest.raises(baseline.BaselineError):
        baseline.verify_archive(archive)


def test_release_baseline_rejects_self_consistent_manifest_with_false_counts(tmp_path: Path):
    source_root = _fixture_root(tmp_path / "source")
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(
        source_root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2
    )
    rewritten = tmp_path / "rewritten.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(rewritten, "w") as target:
        for info in source.infolist():
            raw = source.read(info.filename)
            if info.filename == baseline.ARCHIVE_MANIFEST:
                manifest = json.loads(raw)
                manifest["norm_count"] = 3
                raw = json.dumps(manifest).encode("utf-8")
            target.writestr(info, raw)

    with pytest.raises(baseline.BaselineError, match="counts do not match payload"):
        baseline.verify_archive(rewritten)


def _extra_book(root: Path, name: str = "region_a_3kv2026", **changes) -> str:
    relative = f"data/price_base/{name}.parquet"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "code": ["01.1.03.01-0001", "1-100-10", "4-100-040"],
        "name": ["Fixture resource", "Fixture labor", "Fixture crew"],
        "unit": ["м", None, "чел.-ч"],
        "price_current": [123.45, None, 600.0],
        "region": ["Регион А"] * 3,
        "quarter": ["3 квартал 2026"] * 3,
    }
    values.update(changes)
    pq.write_table(pa.table(values), path)
    return relative


def _extended_archive(tmp_path: Path, *, norms: int = 2) -> tuple[Path, Path, tuple[str, ...]]:
    root = _fixture_root(tmp_path / "source", norms=norms)
    first = _extra_book(root)
    second = _extra_book(root, "another_region_1kv2027",
                         region=["Другой регион"] * 3, quarter=["1 квартал 2027"] * 3)
    archive = tmp_path / "baseline.zip"
    baseline.create_archive(root, archive, minimum_norms=2, minimum_fsem_rows=2,
                            minimum_price_rows=2, extra_pricebooks=(first, second))
    return root, archive, (first, second)


def _rewrite_archive(source: Path, target: Path, update_manifest, *, added_member=None) -> None:
    with zipfile.ZipFile(source) as previous, zipfile.ZipFile(target, "w") as result:
        for info in previous.infolist():
            raw = previous.read(info.filename)
            if info.filename == baseline.ARCHIVE_MANIFEST:
                manifest = json.loads(raw)
                update_manifest(manifest)
                raw = json.dumps(manifest).encode("utf-8")
            result.writestr(info, raw)
        if added_member:
            result.writestr(added_member, b"never package private state")


def test_v2_roundtrip_installs_declared_regions_and_periods_losslessly(tmp_path):
    source, archive, books = _extended_archive(tmp_path)

    verified = baseline.verify_archive(archive)
    installed = baseline.provision_archive(archive, tmp_path / "state")

    assert verified["schema"] == baseline.BASELINE_V2
    assert len(verified["files"]) == 9
    assert {item["region"] for item in verified["pricebooks"]} == {"Регион А", "Другой регион"}
    assert {item["quarter"] for item in verified["pricebooks"]} == {"3 квартал 2026", "1 квартал 2027"}
    for item in verified["pricebooks"]:
        assert item["rows"] == 3
        assert item["rows_with_price_values"] == 2
        assert item["missing_price_rows"] == 1
        assert item["missing_unit_rows"] == 1
        assert item["sha256"] == _sha(source / item["path"])
    for relative in books:
        assert (tmp_path / "state" / relative).read_bytes() == (source / relative).read_bytes()
    assert installed["installed_pricebooks"] == list(books)
    assert installed["kept_pricebooks"] == []


def test_v1_file_set_and_schema_remain_compatible_when_extras_are_absent(tmp_path):
    root = _fixture_root(tmp_path / "source")
    _extra_book(root)  # Mere presence never admits an undeclared file.
    archive = tmp_path / "old-format.zip"
    baseline.create_archive(root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2)

    verified = baseline.verify_archive(archive)

    assert verified["schema"] == baseline.BASELINE_V1
    assert "pricebooks" not in verified
    assert {item["path"] for item in verified["files"]} == {path.as_posix() for path in baseline.REQUIRED_FILES}


@pytest.mark.parametrize("relative", [
    "../data/price_base/other.parquet", "data/price_base/../secret.parquet",
    "data/les_meta.db", "data/price_base/private.sqlite", "RAG_Content/private.parquet",
    "C:/private.parquet", "data/price_base/nested/private.parquet",
    "data/price_base/sankt-peterburg_2kv2026.parquet",
])
def test_v2_creator_rejects_paths_outside_explicit_pricebook_whitelist(tmp_path, relative):
    root = _fixture_root(tmp_path / "source")

    with pytest.raises(baseline.BaselineError, match="invalid extra pricebook path"):
        baseline.create_archive(root, tmp_path / "out.zip", minimum_norms=2,
                                minimum_fsem_rows=2, minimum_price_rows=2, extra_pricebooks=(relative,))


def test_v2_creator_rejects_duplicate_explicit_book_paths(tmp_path):
    root = _fixture_root(tmp_path / "source")
    relative = _extra_book(root)

    with pytest.raises(baseline.BaselineError, match="invalid extra pricebook path"):
        baseline.create_archive(root, tmp_path / "out.zip", minimum_norms=2,
                                minimum_fsem_rows=2, minimum_price_rows=2, extra_pricebooks=(relative, relative))


@pytest.mark.parametrize("changes,reason", [
    ({"region": ["А", "Б", "А"]}, "mixed region/period"),
    ({"quarter": ["3 квартал 2026", "2 квартал 2026", "3 квартал 2026"]}, "mixed region/period"),
    ({"region": ["", "", ""]}, "blank code/metadata"),
    ({"code": ["", "1-100-10", "4-100-040"]}, "blank code/metadata"),
    ({"price_current": [123.45, float("inf"), None]}, "invalid numeric price"),
    ({"price_current": [123.45, -1, None]}, "invalid numeric price"),
    ({"price_current": ["123.45", "garbage", None]}, "invalid numeric price"),
    ({"unit": [1, 2, 3]}, "invalid unit type"),
    ({"private_customer": ["secret"] * 3}, "unsupported columns"),
])
def test_v2_creator_rejects_structurally_invalid_typed_books(tmp_path, changes, reason):
    root = _fixture_root(tmp_path / "source")
    relative = _extra_book(root, **changes)

    with pytest.raises(baseline.BaselineError, match=reason):
        baseline.create_archive(root, tmp_path / "out.zip", minimum_norms=2,
                                minimum_fsem_rows=2, minimum_price_rows=2, extra_pricebooks=(relative,))


def test_v2_book_missing_values_and_duplicate_codes_are_preserved_as_counts(tmp_path):
    root = _fixture_root(tmp_path / "source")
    relative = _extra_book(root, price_current=[123.45, float("nan"), None],
                           unit=["м", "", None], code=["01.1.03.01-0001"] * 3)
    original = (root / relative).read_bytes()
    archive = tmp_path / "out.zip"
    baseline.create_archive(root, archive, minimum_norms=2, minimum_fsem_rows=2,
                            minimum_price_rows=2, extra_pricebooks=(relative,))

    record = baseline.verify_archive(archive)["pricebooks"][0]
    baseline.provision_archive(archive, tmp_path / "state")

    assert record["rows"] == 3 and record["missing_price_rows"] == 2
    assert record["missing_unit_rows"] == 2 and record["duplicate_code_rows"] == 2
    assert (tmp_path / "state" / relative).read_bytes() == original


@pytest.mark.parametrize("field,bad_value", [("rows", 4), ("region", "Wrong region"), ("missing_unit_rows", 0)])
def test_v2_verifier_rejects_self_consistent_file_hash_with_false_book_metadata(tmp_path, field, bad_value):
    _root, archive, _books = _extended_archive(tmp_path)
    rewritten = tmp_path / "tampered.zip"
    _rewrite_archive(archive, rewritten, lambda manifest: manifest["pricebooks"][0].update({field: bad_value}))

    with pytest.raises(baseline.BaselineError, match="metadata does not match payload"):
        baseline.verify_archive(rewritten)


def test_v2_verifier_rejects_undeclared_private_zip_member(tmp_path):
    _root, archive, _books = _extended_archive(tmp_path)
    rewritten = tmp_path / "tampered.zip"
    _rewrite_archive(archive, rewritten, lambda _manifest: None, added_member="payload/data/les_meta.db")

    with pytest.raises(baseline.BaselineError, match="undeclared/duplicate"):
        baseline.verify_archive(rewritten)


@pytest.mark.parametrize("operation", [baseline.provision_archive, baseline.repair_archive])
def test_v2_missing_books_added_without_overwriting_valid_operator_books(tmp_path, operation):
    _root, archive, books = _extended_archive(tmp_path)
    state = _fixture_root(tmp_path / "state")
    _extra_book(state, price_current=[999.0, 888.0, 777.0])
    operator_bytes = (state / books[0]).read_bytes()
    core_sha = _sha(state / "data/smeta_base/les_smeta_base.sqlite")

    result = operation(archive, state)

    assert (state / books[0]).read_bytes() == operator_bytes
    assert _sha(state / "data/smeta_base/les_smeta_base.sqlite") == core_sha
    assert result["kept_pricebooks"] == [books[0]]
    assert result["installed_pricebooks"] == [books[1]]
    assert (state / books[1]).is_file()


def test_v2_core_repair_adds_extra_books_but_preserves_existing_operator_book(tmp_path):
    _root, archive, books = _extended_archive(tmp_path, norms=3)
    state = _fixture_root(tmp_path / "state", norms=2)
    _extra_book(state, price_current=[999.0, 888.0, 777.0])
    operator_bytes = (state / books[0]).read_bytes()

    result = baseline.repair_archive(archive, state)

    assert result["action"] == "repaired" and result["norm_count"] == 3
    assert (state / books[0]).read_bytes() == operator_bytes
    assert (state / books[1]).is_file()
    assert books[0] not in result["backed_up"]


@pytest.mark.parametrize("operation", [baseline.provision_archive, baseline.repair_archive])
def test_v2_invalid_existing_book_does_not_trigger_core_replacement(tmp_path, operation):
    _root, archive, books = _extended_archive(tmp_path)
    state = _fixture_root(tmp_path / "state")
    invalid = state / books[0]
    invalid.write_bytes(b"invalid operator file")
    before = {path: (state / path).read_bytes() for path in baseline.REQUIRED_FILES}

    with pytest.raises(baseline.BaselineError):
        operation(archive, state)

    assert invalid.read_bytes() == b"invalid operator file"
    assert not (state / books[1]).exists()
    assert all((state / path).read_bytes() == raw for path, raw in before.items())


def test_known_producer_manifests_public_projection_removes_absolute_paths(tmp_path):
    root = _fixture_root(tmp_path / "source")
    for relative in (baseline.REQUIRED_FILES[2], baseline.REQUIRED_FILES[3], baseline.REQUIRED_FILES[5]):
        path = root / str(relative)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["private_owner"] = "never include this"
        for field in ("source", "output", "integrity"):
            payload.setdefault(field, {})["path"] = "C:/Users/PrivateOwner/customer files/private.xlsx"
            payload[field]["private_path"] = "C:/secret"
        path.write_text(json.dumps(payload), encoding="utf-8")
    archive = tmp_path / "public.zip"

    baseline.create_archive(root, archive, minimum_norms=2, minimum_fsem_rows=2, minimum_price_rows=2)
    baseline.verify_archive(archive)

    with zipfile.ZipFile(archive) as bundle:
        for relative in (baseline.REQUIRED_FILES[2], baseline.REQUIRED_FILES[3], baseline.REQUIRED_FILES[5]):
            raw = bundle.read(f"payload/{relative}").decode("utf-8")
            assert "PrivateOwner" not in raw and "never include" not in raw and "C:/secret" not in raw
    assert "PrivateOwner" in (root / str(baseline.REQUIRED_FILES[2])).read_text(encoding="utf-8")


def test_v2_provision_rolls_back_new_core_and_books_on_move_failure(tmp_path, monkeypatch):
    _root, archive, books = _extended_archive(tmp_path)
    state = tmp_path / "state"
    real_replace = baseline.os.replace

    def fail_second_book(source, target):
        if Path(target) == state / books[1]:
            raise OSError("injected move failure")
        return real_replace(source, target)

    monkeypatch.setattr(baseline.os, "replace", fail_second_book)

    with pytest.raises(OSError, match="injected move failure"):
        baseline.provision_archive(archive, state)

    assert not any((state / path).exists() for path in (*baseline.REQUIRED_FILES, *books))


def test_v2_create_cli_accepts_repeated_explicit_book_arguments(tmp_path, capsys):
    root = _fixture_root(tmp_path / "source", fsem_rows=1500)
    first = _extra_book(root)
    second = _extra_book(root, "other_region_4kv2027", region=["Другой регион"] * 3,
                         quarter=["4 квартал 2027"] * 3)
    archive = tmp_path / "output.zip"

    assert baseline.main([
        "create", "--source-root", str(root), "--archive", str(archive),
        "--minimum-norms", "2", "--minimum-price-rows", "2",
        "--pricebook", first, "--pricebook", second,
    ]) == 0
    receipt = json.loads(capsys.readouterr().out)

    assert receipt["archive_sha256"] == _sha(archive)
    assert {item["path"] for item in receipt["pricebooks"]} == {first, second}
    assert baseline.verify_archive(archive)["schema"] == baseline.BASELINE_V2


def test_actual_cli_preserves_cyrillic_json_in_non_utf8_parent_environment(tmp_path):
    _source, archive, _books = _extended_archive(tmp_path)
    environment = {**os.environ, "PYTHONIOENCODING": "cp1251", "PYTHONUTF8": "0"}

    result = subprocess.run(
        [sys.executable, "-m", "tools.smeta_release_baseline", "verify", "--archive", str(archive)],
        cwd=baseline.ROOT, env=environment, capture_output=True, check=True,
    )
    receipt = json.loads(result.stdout.decode("utf-8"))

    assert {book["region"] for book in receipt["pricebooks"]} == {"Регион А", "Другой регион"}
    assert {book["quarter"] for book in receipt["pricebooks"]} == {"3 квартал 2026", "1 квартал 2027"}
    assert receipt == baseline.verify_archive(archive)


def test_provisioned_book_unit_gap_cannot_become_confirmed_money(tmp_path):
    from proxy.services.fgis_price_service import PriceBook
    from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows

    root = _fixture_root(tmp_path / "source")
    relative = _extra_book(root, code=["01.1.03.01-0001", "01.1.03.01-0002", "4-100-040"],
                           price_current=[123.45, 300.0, 600.0])
    archive = tmp_path / "output.zip"
    baseline.create_archive(root, archive, minimum_norms=2, minimum_fsem_rows=2,
                            minimum_price_rows=2, extra_pricebooks=(relative,))
    state = tmp_path / "state"
    baseline.provision_archive(archive, state)
    book = PriceBook.from_parquet(state / relative)
    row = {"source_row": "S!R2", "row_role": "material", "title": "Literal unitless resource",
           "resource_code": "01.1.03.01-0002", "unit": "м", "quantity": 1,
           "evidence_refs": ["Q1.H1"]}

    trace = build_lsr_trace_from_visible_rows([row], pricebook=book)

    assert trace["summary"]["confirmed_amount"] == 0
    assert trace["summary"]["preliminary_amount"] == 300
    assert row["resource_code"] == "01.1.03.01-0002" and row["unit"] == "м"
    position = trace["sections"][0]["positions"][0]
    assert any("book_price_unit_unknown" in reason for reason in position["summary"]["completeness_reasons"])


def test_v2_creator_rejects_book_changed_after_official_snapshot_and_keeps_previous_archive(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path / "source")
    relative = _extra_book(root)
    archive = tmp_path / "output.zip"
    archive.write_bytes(b"previous candidate remains untouched")
    validate = baseline._validate_extra_pricebook

    def changed_after_validation(source_root, source_relative):
        receipt = validate(source_root, source_relative)
        _extra_book(source_root, price_current=[777.0, None, 600.0])
        return receipt

    monkeypatch.setattr(baseline, "_validate_extra_pricebook", changed_after_validation)

    with pytest.raises(baseline.BaselineError, match="changed during packaging"):
        baseline.create_archive(root, archive, minimum_norms=2, minimum_fsem_rows=2,
                                minimum_price_rows=2, extra_pricebooks=(relative,))

    assert archive.read_bytes() == b"previous candidate remains untouched"
