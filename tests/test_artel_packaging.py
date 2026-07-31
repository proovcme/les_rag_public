from pathlib import Path
import json
import subprocess

from tools import check_atlas_bundle_budget


ROOT = Path(__file__).resolve().parents[1]


def test_artel_is_pinned_standalone_submodule():
    gitmodules = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    assert "path = products/artel" in gitmodules
    assert "url = git@github.com:proovcme/Agnostis.git" in gitmodules

    entry = subprocess.run(
        ["git", "ls-files", "--stage", "products/artel"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert entry.startswith("160000 ")

    artel = ROOT / "products" / "artel"
    for required in (
        "README.md",
        "version.json",
        "app/index.html",
        "backend/Agnostis.Api/Program.cs",
        "openapi/artel-runtime.yaml",
        "skills/revit-api-operator/SKILL.md",
    ):
        assert (artel / required).is_file(), f"ARTEL submodule is not initialized: {required}"


def test_artel_submodule_tracks_no_build_outputs():
    tracked = subprocess.run(
        ["git", "-C", ROOT / "products" / "artel", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    forbidden_dirs = {"Dist", "bin", "obj", "publish", "artifacts"}
    assert not [path for path in tracked if forbidden_dirs.intersection(Path(path).parts)]
    assert not [path for path in tracked if Path(path).suffix.lower() in {".dll", ".pdb", ".exe"}]


def test_atlas_bundle_budget_current_standalone():
    failures = check_atlas_bundle_budget.check_budget(ROOT / "standalone" / "cad_bim_viewer")

    assert failures == []


def test_artel_standalone_installer_contract():
    artel = ROOT / "products" / "artel"
    project = (artel / "ARTEL.Revit.FamilyFactory" / "ARTEL.Revit.FamilyFactory.csproj").read_text(encoding="utf-8")
    installer = (artel / "installer" / "ARTEL.iss").read_text(encoding="utf-8")
    launcher = (artel / "installer" / "start-artel.ps1").read_text(encoding="utf-8")
    build_script = (artel / "build-family-factory-revit.ps1").read_text(encoding="utf-8")

    assert "net48;net8.0-windows" in project
    assert "Revit 2024" in project and "Revit 2025" in project
    assert "knowledge\\ARTEL" in installer
    assert 'Source: "..\\skills\\*"' in installer
    assert "sync-artel-knowledge.ps1" in installer
    assert "start-les-artel-index-proxy.ps1" in installer
    assert 'start-les-artel-index-proxy.ps1"" -Register' in installer
    assert 'sync-artel-knowledge.ps1"""' in installer
    assert '#define MyPayloadVersion "0.25.9-420"' in installer
    assert '#define MyAppVersion "0.25.9"' in installer
    assert 'Name: "lesintegration"' in installer and 'Flags: unchecked' in installer
    assert "ARTEL.FamilyFactory\\{#MyPayloadVersion}" in installer
    assert "qwen3.5:9b" in launcher
    assert {"not_installed", "service_unavailable", "model_missing", "ready"} <= set(launcher.split('"'))
    assert 'Register-ScheduledTask -TaskName $taskName' in launcher
    assert 'Start-ScheduledTask -TaskName $taskName' in launcher
    assert "24.0.0.0 API contract" in build_script
    assert "2024.3" not in project and "2024.3" not in installer

    proxy_launcher = (artel / "installer" / "start-les-artel-index-proxy.ps1").read_text(encoding="utf-8")
    assert '$env:LES_EMBED_PROFILE = "legacy"' in proxy_launcher
    assert '$env:RAG_CHUNK_SIZE = "900"' in proxy_launcher
    assert '$env:EMBED_BACKEND = "ollama"' in proxy_launcher
    assert "les_meta.db.les_rag.index-contract.json" in proxy_launcher
    assert "& $uv run uvicorn proxy_server:app" in proxy_launcher


def test_artel_workflow_is_real_and_confirmation_gated():
    artel = ROOT / "products" / "artel"
    workflow = (artel / "backend" / "Agnostis.Api" / "ArtelWorkflow.cs").read_text(encoding="utf-8")
    pane = (artel / "ARTEL.Revit.FamilyFactory" / "ArtelDockPane.cs").read_text(encoding="utf-8")
    bridge = (artel / "ARTEL.Revit.FamilyFactory" / "ArtelExternalEvent.cs").read_text(encoding="utf-8")

    for endpoint in ('/api/generator/draft', '/api/operator/plan'):
        assert endpoint in workflow
    for source_kind in ('ExtractDocx', 'ExtractXlsx', 'IngestPdfAndRetrieveAsync', 'images'):
        assert source_kind in workflow
    assert 'artel.family_spec.v1' in workflow
    assert 'artel.family_action_plan.v1' in workflow
    assert 'artel.revit_operator_plan.v1' in workflow
    assert 'confirmationHash' in workflow and 'EnsureConfirmed' in bridge
    assert 'catch (JsonException)' in workflow and '"upstream_error"' in workflow
    assert 'LooksLikeFamilySpecification' in workflow and 'NormalizeFamilySpecification' in workflow
    assert 'EvidenceForPrompt' in workflow and 'Не добавляй отсутствующие факты' in workflow
    assert '["think"] = false' in workflow and '["num_predict"] = 2400' in workflow
    assert 'AdaptFamilySpecification' not in workflow
    assert 'Сохрани профессиональные решения модели без изменений' in workflow
    assert 'LoadGeneratorSkill' in workflow and 'revit-family-generator' in workflow
    assert 'preserveUnparsed: true' in workflow and 'JSON-нормализатор собственного черновика Revit-плана' in workflow
    assert 'OperatorPlanFormat' in workflow and 'model_inventory — единственный источник целей' in workflow
    assert 'StringValue(parameter["shared_guid"])' in workflow and 'hasBlockingQuestions' in workflow
    assert 'Regex.Replace(candidate' in workflow and 'trailing comma' in workflow
    assert 'ExternalEvent.Create' in bridge and 'new Transaction' in bridge
    assert 'model_quantities' in bridge and 'system_quantities' in bridge and 'model_inventory' in bridge
    assert 'SystemQuantitySummary' in bridge and 'BuiltInParameter.RBS_SYSTEM_NAME_PARAM' in bridge
    assert 'UnitTypeId.CubicMeters' in bridge and 'select_elements' in bridge
    assert 'ViewSchedule.CreateSchedule' in bridge and 'GetSchedulableFields' in bridge
    assert 'document.Settings.Categories' in bridge and 'ViewSchedule.IsValidCategoryForSchedule' in bridge
    assert 'ScheduleFilter' in bridge and 'AddFilter' in bridge
    assert 'BuildScheduleFilter' in bridge and 'StorageType.ElementId' in bridge and 'AsElementId()' in bridge
    assert 'parameter_catalog' in bridge and 'type_parameters' in bridge
    assert 'parameter_scope' in bridge and 'UniqueViewName' in bridge
    assert 'ReadParameters(element, 80)' in bridge
    assert {'set_parameter', 'select_elements', 'select_category'} <= set(workflow.split('"'))
    assert 'Шаг {_wizardStep} из 6' in pane
    assert 'ModeButton("Действия в Revit"' not in pane
    assert 'ModeButton("Оператор"' not in pane
    assert '+ Прикрепить файл' in pane and 'DataFormats.FileDrop' in pane
    assert 'FlowDocumentScrollViewer' in pane and 'IsMarkdownTable' in pane
    assert 'Вопрос по открытой модели Revit' in pane
    assert 'Название BIM-пакета' in pane and 'include_quantities' in pane and 'include_selection' in pane
    assert 'PrepareChatActionAsync' not in pane and 'Предлагаемое действие в Revit' not in pane
    assert '/api/integrations/les/export' in pane
    assert 'TryGetProperty("action"' in pane and 'RunAsync("operator", _pendingPlan, _pendingHash, bypassSafety:' in pane
    assert 'RunAsync("operator_preview"' in pane and 'Предохранитель действий Revit' in pane
    assert 'safety_enabled' in pane and 'ОТКЛЮЧЁН: агент выполняет' in pane
    assert 'BackendUrl + "/api/assistant/live"' in pane
    assert 'RunAsync("agent_query"' in pane
    ask_method = pane[pane.index('private async Task AskAsync()'):pane.index('private void ShowConfirmation')]
    assert 'RunAsync("context")' not in ask_method
    assert 'ResolveTargets' in bridge and 'parameter_filters' in bridge
    assert 'QueryRevitLive' in bridge and 'artel.revit_live_query.v1' in bridge
    assert '["total"] = total' in bridge and '["has_more"] = offset + returned < total' in bridge
    assert 'ScheduleSortGroupField' in bridge and 'IsItemized' in bridge
    assert {'model', 'active_view', 'selection'} <= set(bridge.split('"'))
    assert {'family', 'type', 'system'} <= set(bridge.split('"'))
    assert 'target_fingerprint' in bridge and 'safety_bypassed' in bridge


def test_artel_knowledge_is_module_owned_and_git_bundled():
    artel = ROOT / "products" / "artel"
    manifest = json.loads((artel / "knowledge" / "ARTEL_DATASET.json").read_text(encoding="utf-8"))
    corpus = artel / "knowledge" / "ARTEL"

    assert manifest["dataset_name"] == "ARTEL_Index"
    assert manifest["dataset_scope"] == "system"
    assert manifest["module_id"] == "artel"
    assert len([path for path in corpus.rglob("*") if path.is_file()]) >= 60
    revit_2024 = list((corpus / "revit_api_sdk_docs").glob("revit_api_2024.1.10.25_*_xml_shard_*.md"))
    assert len(revit_2024) == 68
    sample_2024 = revit_2024[0].read_text(encoding="utf-8")
    assert "Revit API version: 2024.1.10.25" in sample_2024
    assert "Package SHA-256: 72e2be30d84f438e6d9d9eeb92ff99a7674dfbcbe906c2dcaf9229b75c5cff43" in sample_2024
    assert (artel / "skills" / "revit-api-operator" / "SKILL.md").is_file()
    generator_skill = (artel / "skills" / "revit-family-generator" / "SKILL.md").read_text(encoding="utf-8")
    assert "The model owns every professional choice" in generator_skill
    assert "must not infer missing dimensions" in generator_skill
    assert (artel / "skills" / "revit-family-generator" / "references" / "family-spec-contract.md").is_file()


def test_artel_bim_export_does_not_mutate_service_knowledge():
    program = (ROOT / "products" / "artel" / "backend" / "Agnostis.Api" / "Program.cs").read_text(encoding="utf-8")
    pane = (ROOT / "products" / "artel" / "ARTEL.Revit.FamilyFactory" / "ArtelDockPane.cs").read_text(encoding="utf-8")

    assert 'const string exportDataset = "ARTEL_BIM_Index";' in program
    assert '"/api/rag/upload/ARTEL"' not in program
    assert '"/api/assistant/live"' in program and 'query_revit' in program
    assert 'search_artel_index' in program and 'prepare_revit_action' in program
    assert {'select_elements', 'create_schedule', 'set_parameter'} <= set(program.split('"'))
    assert 'requires_confirmation' in program and 'parameter_scope' in program
    assert '["parameter_filters"]' in program
    assert 'artel.revit_operator_plan.v3' in program
    assert {'model', 'active_view', 'selection'} <= set(program.split('"'))
    assert 'LiveAssistantTools()' in program and 'PrepareLiveRevitAction' in program
    assert 'finish_revit_response' in program
    assert 'Не завершай агентный ход обещанием' in program
    assert 'finish_revit_response для окончательного read-only ответа' in program
    assert 'Исправь аргументы prepare_revit_action по сообщению инструмента' in program
    live_endpoint = program[program.index('app.MapPost("/api/assistant/live"'):program.index('app.MapPost("/api/assistant"')]
    assert 'status = "action_invalid"' not in live_endpoint
    assert 'У тебя нет заранее подготовленного снимка модели' in program
    assert 'всегда проверяй total, returned и has_more' in program
    assert 'Snapshot BIM chat is disabled' in program and 'Status410Gone' in program
    assert 'static string NodeText' in program and 'SearchAssistantEvidenceAsync' in program
    assert 'JavaScriptEncoder.UnsafeRelaxedJsonEscaping' in program
    assert 'PrepareChatActionAsync' not in pane
    assert 'Посчитать объёмы' not in pane and 'Что выбрано' not in pane
    assert 'TextAlignment = TextAlignment.Left' in pane
    assert 'RuntimeLabel(status)' in pane and '{message}' not in pane
