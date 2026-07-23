"""Typed scoped evidence packet builder for LES turns.

This is a composition helper: it arranges already available context into typed
sections. It does not run semantic search and does not turn snippets/examples
into evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from proxy.services.active_state_service import ActiveState, render_active_state
from proxy.services.skill_snippet_registry import SkillSnippet, render_snippets


@dataclass
class EvidenceSection:
    section_type: str
    items: list[Any] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.section_type, "items": self.items, "note": self.note}


@dataclass
class EvidencePacket:
    module_id: str
    turn_type: str
    sections: list[EvidenceSection]

    def section(self, section_type: str) -> EvidenceSection | None:
        for sec in self.sections:
            if sec.section_type == section_type:
                return sec
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "les.scoped_evidence_packet.v1",
            "module_id": self.module_id,
            "turn_type": self.turn_type,
            "sections": [sec.to_dict() for sec in self.sections],
        }

    def render_for_model(self) -> str:
        labels = {
            "active_state": "ACTIVE_STATE",
            "user_input": "USER_INPUT",
            "source_facts": "SOURCE_FACTS",
            "table_rows": "TABLE_ROWS",
            "calculation_trace": "CALCULATION_TRACE",
            "domain_objects": "DOMAIN_OBJECTS",
            "tool_results": "TOOL_RESULTS",
            "skill_snippets": "SKILL_SNIPPET",
            "example_patterns": "EXAMPLE_PATTERNS",
            "gaps": "GAPS",
            "lookup_records": "LOOKUP_RECORDS",
        }
        chunks: list[str] = []
        for sec in self.sections:
            label = labels.get(sec.section_type, sec.section_type.upper())
            chunks.append(f"[{label}]")
            if sec.note:
                chunks.append(sec.note)
            if sec.items:
                for item in sec.items:
                    chunks.append(str(item))
            else:
                chunks.append("—")
        return "\n".join(chunks)


def build_scoped_evidence_packet(
    *,
    module_id: str,
    turn_type: str,
    user_input: str,
    active_state: ActiveState | dict[str, Any] | None = None,
    source_facts: list[Any] | None = None,
    table_rows: list[Any] | None = None,
    calculation_trace: list[Any] | None = None,
    domain_objects: list[Any] | None = None,
    tool_results: list[Any] | None = None,
    skill_snippets: list[SkillSnippet] | None = None,
    example_patterns: list[Any] | None = None,
    lookup_records: list[Any] | None = None,
    gaps: list[Any] | None = None,
) -> EvidencePacket:
    sections: list[EvidenceSection] = []
    rendered_state = render_active_state(active_state)
    if rendered_state:
        sections.append(EvidenceSection("active_state", [rendered_state], "working memory, not proof"))
    sections.append(EvidenceSection("user_input", [user_input]))

    def _add(section_type: str, items: list[Any] | None, note: str = "") -> None:
        if items:
            sections.append(EvidenceSection(section_type, list(items), note))

    _add("source_facts", source_facts, "facts from current sources")
    _add("table_rows", table_rows, "source table rows")
    _add("calculation_trace", calculation_trace, "deterministic calculations")
    _add("domain_objects", domain_objects, "module objects/candidates")
    _add("lookup_records", lookup_records, "structured exact lookup records")
    _add("tool_results", tool_results, "tool outputs with trace")
    if skill_snippets:
        sections.append(EvidenceSection("skill_snippets", [render_snippets(skill_snippets)], "rules, not evidence"))
    _add("example_patterns", example_patterns, "patterns only; not facts for current object")
    _add("gaps", gaps, "missing inputs or unresolved conflicts")
    return EvidencePacket(module_id=module_id, turn_type=turn_type, sections=sections)
