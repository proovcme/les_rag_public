"""RTF structural validation and native literal-reader boundary; no model calls."""
import json
import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def _api():
    from backend import rtf_parser
    return rtf_parser


def test_structural_validation_ignores_escaped_braces_hex_and_binary_payload():
    raw = br"{\rtf1\ansi escaped \{ \} \\ \'7b {\pict\bin5 {}\\} }tail}"
    info = _api().validate_rtf(raw)
    assert info.structurally_valid is True
    assert dict(info.control_word_counts)["pict"] == 1
    assert dict(info.control_word_counts)["bin"] == 1
    assert info.binary_bytes == 5


@pytest.mark.parametrize("raw,code", [
    (b"plain text", "RTF_INVALID_HEADER"),
    (br"{\rtf1 text", "RTF_UNCLOSED_GROUP"),
    (br"{\rtf1 text}}", "RTF_TRAILING_DATA"),
    (br"{\rtf1 text} trailing", "RTF_TRAILING_DATA"),
    (br"{\rtf1 \'xz}", "RTF_INVALID_HEX_ESCAPE"),
    (br"{\rtf1 \'a}", "RTF_INVALID_HEX_ESCAPE"),
    (b"{\\rtf1 dangling\\", "RTF_DANGLING_ESCAPE"),
    (br"{\rtf1\bin-1 x}", "RTF_INVALID_BINARY_LENGTH"),
    (br"{\rtf1\bin x}", "RTF_INVALID_BINARY_LENGTH"),
    (br"{\rtf1\bin10 x}", "RTF_TRUNCATED_BINARY"),
])
def test_malformed_rtf_fails_before_native_reader(raw, code):
    with pytest.raises(_api().RtfParserError) as error:
        _api().validate_rtf(raw)
    assert error.value.code == code


def _native(monkeypatch, module, *, text="Монтаж\tм²\t7,25\t\n", **extra):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        source = Path(args[args.index("-SourcePath") + 1])
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        assert args[args.index("-ExpectedSourceSha256") + 1] == source_sha
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "ok", "text": text,
            "source_sha256": source_sha, "native_reader": "windows-richtext", **extra}, ensure_ascii=False).encode("utf-8"), stderr=b"")
    monkeypatch.setattr(module, "_native_platform", lambda: "win32")
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "_windows_powershell", lambda: Path(__file__))
    return calls


def _source(tmp_path):
    path = tmp_path / "Исходник «клиент» с пробелом и 'кавычкой'.rtf"
    path.write_bytes(br"{\rtf1\ansi\trowd\cellx1000\cellx2000\cellx3000\intbl title\cell unit\cell 7,25\cell\row}")
    return path


def test_native_unicode_tables_keep_literal_cells_paths_hashes_and_no_geometry_claim(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    before = source.read_bytes()
    calls = _native(monkeypatch, module)
    result = module.extract_rtf(source)
    assert result.text == "Монтаж\tм²\t7,25\t\n"
    assert result.rows[0].cells == ("Монтаж", "м²", "7,25")
    assert result.rows[0].source_text_start == 0
    assert result.rows[0].source_text_end == len(result.text)
    assert result.table_boundaries_verified is True
    assert result.structurally_valid is True and result.geometry_verified is False
    assert result.extraction_complete is False
    assert source.read_bytes() == before
    args, options = calls[0]
    assert isinstance(args, list) and str(source.resolve()) in args
    assert "-STA" in args and "-NonInteractive" in args
    assert "-ExecutionPolicy" not in args
    assert options["timeout"] == 30
    assert not options.get("shell", False)
    assert options.get("creationflags", 0) != 0


def test_native_wrong_row_cardinality_never_fabricates_cells(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    _native(monkeypatch, module, text="Монтаж\tм²\t7,25\t\nДругой абзац\n")
    result = module.extract_rtf(source)
    assert result.text.endswith("Другой абзац\n")
    assert not result.rows and not result.table_boundaries_verified
    assert "RTF_TABLE_BOUNDARIES_UNVERIFIED" in result.warnings


def test_native_cell_count_mismatch_and_literal_tab_are_audited(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    _native(monkeypatch, module, text="Монтаж\tм²\n")
    result = module.extract_rtf(source)
    assert not result.rows and "RTF_TABLE_BOUNDARIES_UNVERIFIED" in result.warnings
    source.write_bytes(br"{\rtf1\trowd\intbl title\tab literal\cell\row}")
    result = module.extract_rtf(source)
    assert not result.rows and "RTF_TEXT_TABS_AMBIGUOUS_WITH_CELLS" in result.warnings


def test_truncated_input_rejected_before_os_and_ole_never_activated(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    calls = _native(monkeypatch, module)
    source.write_bytes(br"{\rtf1 truncated")
    with pytest.raises(module.RtfParserError, match="RTF_UNCLOSED_GROUP"):
        module.extract_rtf(source)
    assert not calls
    source.write_bytes(br"{\rtf1{\object{\objdata abc}}visible}")
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(source)
    assert error.value.code == "RTF_EMBEDDED_OBJECTS_UNSUPPORTED"
    assert not calls


def test_images_fields_and_nested_tables_are_explicit_partial_source_warnings(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    source.write_bytes(br"{\rtf1{\pict abc}{\field{\fldinst PAGE}{\fldrslt 1}}\nestcell\nestrow\clvmgf\clvmrg\line}")
    _native(monkeypatch, module, text="1\n")
    result = module.extract_rtf(source)
    assert not result.extraction_complete and not result.rows
    assert "RTF_IMAGES_NOT_TRANSCRIBED" in result.warnings
    assert "RTF_FIELDS_NOT_EVALUATED" in result.warnings
    assert "RTF_NESTED_TABLES_UNVERIFIED" in result.warnings
    assert "RTF_MERGED_TABLE_GEOMETRY_UNVERIFIED" in result.warnings
    assert "RTF_IN_CELL_BREAKS_UNVERIFIED" in result.warnings


@pytest.mark.parametrize("kind,code", [("timeout", "RTF_NATIVE_TIMEOUT"), ("bad_utf8", "RTF_NATIVE_INVALID_UTF8"), ("bad_json", "RTF_NATIVE_INVALID_RESPONSE"), ("bad_shape", "RTF_NATIVE_INVALID_RESPONSE"), ("error", "RTF_NATIVE_FAILED")])
def test_native_failures_are_visible_and_never_empty_success(tmp_path, monkeypatch, kind, code):
    module = _api()
    source = _source(tmp_path)
    monkeypatch.setattr(module, "_native_platform", lambda: "win32")
    monkeypatch.setattr(module, "_windows_powershell", lambda: Path(__file__))
    def run(*_args, **_kwargs):
        if kind == "timeout":
            raise subprocess.TimeoutExpired("powershell", 30)
        raw = {"bad_utf8": b"\xff", "bad_json": b"{broken", "bad_shape": b"[]", "error": b'{"status":"error","message":"invalid RTF"}'}[kind]
        return SimpleNamespace(returncode=0, stdout=raw, stderr=b"")
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(source)
    assert error.value.code == code


def test_source_changes_and_native_replacement_characters_are_not_green(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    _native(monkeypatch, module, source_sha256="f" * 64)
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(source)
    assert error.value.code == "RTF_SOURCE_CHANGED"
    _native(monkeypatch, module, text="literal �\n")
    result = module.extract_rtf(source)
    assert "RTF_REPLACEMENT_CHARACTER_PRESENT" in result.warnings
    assert not result.extraction_complete


def test_transient_native_path_change_is_rejected_before_loading_even_if_original_restored(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    original = source.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    changed = br"{\rtf1{\object{\objdata never load this}}changed}"
    loaded = []
    seen = []
    monkeypatch.setattr(module, "_native_platform", lambda: "win32")
    monkeypatch.setattr(module, "_windows_powershell", lambda: Path(__file__))
    def run(args, **kwargs):
        path = Path(args[args.index("-SourcePath") + 1])
        expected = args[args.index("-ExpectedSourceSha256") + 1] if "-ExpectedSourceSha256" in args else None
        seen.append((str(path), expected))
        # The child opens a changed snapshot after Python validated the original.
        path.write_bytes(changed)
        snapshot = path.read_bytes()
        rendered_sha = hashlib.sha256(snapshot).hexdigest()
        path.write_bytes(original)
        if expected is not None and expected != rendered_sha:
            payload = {"status": "error", "error_code": "RTF_SOURCE_CHANGED"}
        else:
            loaded.append(snapshot)
            # Old path-based helper hashed the restored file after LoadFile.
            payload = {"status": "ok", "text": "changed native text", "source_sha256": original_sha}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode("utf-8"), stderr=b"")
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(module.RtfParserError, match="RTF_SOURCE_CHANGED"):
        module.extract_rtf(source)
    assert seen == [(str(source.resolve()), original_sha)]
    assert loaded == [], "the mismatching bytes must not reach native LoadFile"
    assert source.read_bytes() == original


def test_checked_windows_cli_hashes_single_snapshot_before_rendering_that_same_buffer():
    body = (Path(__file__).resolve().parents[1] / "tools/windows_rtf_extract.ps1").read_text(encoding="utf-8")
    assert "$ExpectedSourceSha256" in body
    assert body.count("ReadAllBytes(") == 1
    assert "Get-FileHash" not in body
    assert "$box.LoadFile($resolved" not in body
    assert "$box.LoadFile($stream" in body
    assert "MemoryStream" in body and "$sourceBytes" in body
    assert body.index("ComputeHash($sourceBytes)") < body.index("$ExpectedSourceSha256", body.index("try {")) < body.index("$box.LoadFile(")
    assert "source_sha256=$sourceSha" in body


def test_mac_reader_without_proven_atomic_input_contract_does_not_render_live_path(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    monkeypatch.setattr(module, "_native_platform", lambda: "darwin")
    monkeypatch.setattr(module.shutil, "which", lambda _tool: "/usr/bin/textutil")
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k: pytest.fail("unbound live path must not be rendered"))
    with pytest.raises(module.RtfParserError, match="RTF_NATIVE_ATOMIC_INPUT_UNSUPPORTED"):
        module.extract_rtf(source)


def test_unsupported_platform_is_visible_and_mac_uses_existing_textutil_only(tmp_path, monkeypatch):
    module = _api()
    source = _source(tmp_path)
    monkeypatch.setattr(module, "_native_platform", lambda: "linux")
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(source)
    assert error.value.code == "RTF_NATIVE_READER_UNAVAILABLE"
    monkeypatch.setattr(module, "_native_platform", lambda: "darwin")
    monkeypatch.setattr(module.shutil, "which", lambda _tool: None)
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(source)
    assert error.value.code == "RTF_NATIVE_READER_UNAVAILABLE"


def test_checked_windows_cli_is_hidden_unicode_and_readonly():
    script = Path(__file__).resolve().parents[1] / "tools/windows_rtf_extract.ps1"
    body = script.read_text(encoding="utf-8")
    assert "$box.Visible = $false" in body
    assert "LoadFile" in body and "RichTextBoxStreamType]::RichText" in body
    assert "UTF8Encoding" in body and "$box.Dispose()" in body
    assert "ShowDialog" not in body and "Start-Process" not in body


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, float("nan"), "30"])
def test_unbounded_or_invalid_native_deadlines_fail_before_os(tmp_path, monkeypatch, timeout):
    module = _api()
    calls = _native(monkeypatch, module)
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(_source(tmp_path), timeout_seconds=timeout)
    assert error.value.code == "RTF_INVALID_TIMEOUT" and not calls


@pytest.mark.parametrize("payload", [
    {"status": "ok", "text": "no hash"},
    {"status": "ok", "text": 12, "source_sha256": "a" * 64},
    {"status": "ok", "text": "wrong hash shape", "source_sha256": {}},
])
def test_unbound_native_response_metadata_is_rejected(tmp_path, monkeypatch, payload):
    module = _api()
    monkeypatch.setattr(module, "_native_platform", lambda: "win32")
    monkeypatch.setattr(module, "_windows_powershell", lambda: Path(__file__))
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps(payload).encode("utf-8"), stderr=b""))
    with pytest.raises(module.RtfParserError) as error:
        module.extract_rtf(_source(tmp_path))
    assert error.value.code == "RTF_NATIVE_INVALID_RESPONSE"


def test_binary_data_does_not_create_fake_object_or_table_markers():
    body = br"\object\cell\row{}"
    raw = br"{\rtf1\bin" + str(len(body)).encode("ascii") + b" " + body + b"}"
    result = _api().validate_rtf(raw)
    assert dict(result.control_word_counts) == {"bin": 1, "rtf": 1}
    assert result.binary_bytes == len(body) and result.row_cell_counts == ()


def test_plain_text_source_is_usable_without_claiming_geometry_or_all_content(tmp_path, monkeypatch):
    module = _api()
    source = tmp_path / "Текст.rtf"
    source.write_bytes(br"{\rtf1\ansi hello\par}")
    _native(monkeypatch, module, text="hello\n")
    result = module.extract_rtf(source)
    assert result.text == "hello\n" and not result.rows
    assert not result.extraction_complete and not result.geometry_verified
    assert result.warnings == ("RTF_NATIVE_RENDERING_NOT_FULL_SOURCE_OR_GEOMETRY_PROOF",)
