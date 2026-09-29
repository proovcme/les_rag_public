"""One markdown-table reading contract for model answers (task § 3, B3).

The decoder that turns a model answer into decision rows
(``chat_evidence_application_service.parse_model_rag_result``) and the gate that
re-reads the same answer for closed quality fields
(``lsr_norm_quality_gate_service.parse_quality_table``) must accept the tables the
provider actually wrote.  Three renderings occur in the installed chat store and
each of them is ordinary markdown:

* a line opened with a pipe — ``| source_row | title | … |``;
* a line opened without one — ``source_row | title | …``;
* a line with the citation mark the prompt itself mandates glued in front of it —
  ``[Источник 1] | source_row | title | … |``.

Only presentation is handled here.  Cell text comes back verbatim, no word of an
answer is interpreted as a professional decision, and no ``re`` is used, so the
decoder stays inside the architecture gate that forbids regex in it.  A mark that
is not a citation — an evidence handle such as ``[Q4.H1]`` or a bracketed value a
model wrote inside a cell — is left exactly where the model wrote it.

usage:
    from proxy.services.model_answer_table_service import table_cells

    cells = table_cells("[Источник 3] | АР!R49 | ГЭСН15-04-007-08 |")
"""

from __future__ import annotations

#: The citation head the prompt mandates («Ссылки оформляй номерами из заголовков
#: [Источник N]», and the packet header label is built from the same word).  Matched
#: by prefix so the Russian declensions of one word do not become a growing list.
CITATION_MARK_HEADS = ("источник", "source")
#: How many glued marks one line may carry before it stops being presentation.
MAX_CITATION_MARKS_PER_LINE = 3
_CITATION_MARK_MAX_CHARS = 48


def citation_mark_length(text: str) -> int:
    """Length of a leading ``[Источник N]`` / ``[7]`` mark, or 0 when there is none."""

    if not text.startswith("["):
        return 0
    end = text.find("]")
    if end <= 0 or "|" in text[: end + 1]:
        return 0
    inner = " ".join(text[1:end].split()).casefold()
    if not inner or len(inner) > _CITATION_MARK_MAX_CHARS:
        return 0
    if inner.isdigit():
        return end + 1
    head, _, tail = inner.partition(" ")
    if not tail or not any(head.startswith(word) for word in CITATION_MARK_HEADS):
        return 0
    # A citation names numbers, nothing else: «[Источник 1]», «[Источники 2, 3]».
    return end + 1 if all(character in "0123456789, -" for character in tail) else 0


def table_line(line: str) -> str:
    """The table payload of one answer line, or ``""`` when it carries no table."""

    text = str(line or "").strip()
    for _ in range(MAX_CITATION_MARKS_PER_LINE):
        taken = citation_mark_length(text)
        if not taken:
            break
        text = text[taken:].lstrip(" \t")
    return text if "|" in text else ""


def table_cells(line: str) -> list[str]:
    """Split one table line into cells, whatever presentation opened it."""

    payload = table_line(line)
    if not payload:
        return []
    if payload.startswith("|"):
        payload = payload[1:]
    if payload.endswith("|"):
        payload = payload[:-1]
    return [item.strip() for item in payload.split("|")]


def opens_as_table(line: str) -> bool:
    """Whether the model opened this line the way a table row is opened."""

    return table_line(line).startswith("|")


def is_divider_cell(value: str) -> bool:
    """One alignment cell: dashes with at most an alignment colon on either side.

    ``|---|``, ``|:--|``, ``|:-:|`` and ``|--|`` are all the same markdown marker;
    requiring three dashes dropped a whole 38-row decision table (chat row 53,
    ``ВОР!R4…ВОР!R41``) that opened its alignment row with ``:--``.
    """

    candidate = str(value or "").strip()
    if not candidate:
        return False
    body = candidate.strip(":")
    return bool(body) and set(body) <= {"-"} and ":" not in body
