"""Read literal XLSX print metadata and classic comments without interpretation."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_P = "http://schemas.openxmlformats.org/package/2006/relationships"
_PRINT_PARTS = frozenset({"oddHeader", "evenHeader", "firstHeader", "oddFooter", "evenFooter", "firstFooter"})
_PRINT_ATTRIBUTES = frozenset({"differentOddEven", "differentFirst", "scaleWithDoc", "alignWithMargins"})
_RICH_TEXT_TAGS = frozenset({"text", "r", "rPr", "t", "rFont", "charset", "family", "b", "i", "strike",
    "outline", "shadow", "condense", "extend", "color", "sz", "u", "vertAlign", "scheme"})


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml(node: ET.Element) -> str:
    return ET.tostring(node, encoding="unicode")


def _target(base: str, target: str) -> str:
    value = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                              else posixpath.join(posixpath.dirname(base), target))
    if value.startswith("../") or value in {".", ".."}:
        raise ValueError("XLSX_METADATA_RELATIONSHIP_OUTSIDE_PACKAGE")
    return value


def _relationships(archive: ZipFile, part: str) -> list[dict[str, str]]:
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if path not in archive.namelist():
        return []
    return [dict(node.attrib) for node in ET.fromstring(archive.read(path)).findall(f"{{{_P}}}Relationship")]


def _has_picture(text: str) -> bool:
    index = 0
    while index < len(text) - 1:
        if text[index] != "&":
            index += 1
        elif text[index + 1] == "&":
            index += 2
        elif text[index + 1] == "G":
            return True
        else:
            index += 2
    return False


def read_xlsx_source_metadata(path: str | Path) -> dict[str, dict]:
    """Expose full literal bodies; unsupported metadata remains an unread warning.

    Excel print fields/formatting are not evaluated or stripped. Classic comment
    rich text is concatenated from its literal text runs and its XML is retained.
    Nothing here classifies a construction operation, unit, quantity or price.
    """
    result: dict[str, dict] = {}
    with ZipFile(path) as archive:
        workbook_part = "xl/workbook.xml"
        workbook = ET.fromstring(archive.read(workbook_part))
        relations = {item.get("Id"): item for item in _relationships(archive, workbook_part)}
        for sheet in workbook.findall(f"{{{_S}}}sheets/{{{_S}}}sheet"):
            name = sheet.attrib.get("name", "")
            record = {"rows": [], "print_parts": [], "comment_coordinates": [], "warnings": []}
            result[name] = record
            relation = relations.get(sheet.attrib.get(f"{{{_R}}}id"), {})
            try:
                if relation.get("TargetMode") == "External" or not relation.get("Target"):
                    raise ValueError("XLSX_METADATA_WORKSHEET_RELATIONSHIP_UNSUPPORTED")
                part = _target(workbook_part, relation["Target"])
                document = ET.fromstring(archive.read(part))
                if document.find(f"{{{_S}}}legacyDrawingHF") is not None:
                    record["warnings"].append(f"xlsx_unread_content:{name}:header_footer_pictures")
                for number, container in enumerate(document.findall(f"{{{_S}}}headerFooter"), 1):
                    unsupported = (len(document.findall(f"{{{_S}}}headerFooter")) != 1
                        or bool(set(container.attrib) - _PRINT_ATTRIBUTES)
                        or bool((container.text or "").strip())
                        or any((child.tail or "").strip() for child in container))
                    children = list(container)
                    meaningful = bool(unsupported or any("".join(child.itertext()) for child in children))
                    for child in children:
                        kind, text = _name(child.tag), "".join(child.itertext())
                        supported = child.tag == f"{{{_S}}}{kind}" and kind in _PRINT_PARTS and not list(child) and not child.attrib
                        unsupported = unsupported or not supported
                        if supported:
                            record["print_parts"].append(kind)
                        if _has_picture(text):
                            record["warnings"].append(f"xlsx_unread_content:{name}:{kind}:picture")
                    if meaningful or unsupported:
                        record["rows"].append({"suffix": f"headerFooter:{number}", "body": {
                            "kind": "xlsx_header_footer", "source_part": part,
                            "attributes": dict(container.attrib), "literal_xml": _xml(container),
                            "parts": [{"kind": _name(child.tag), "literal": "".join(child.itertext())} for child in children],
                        }})
                    if unsupported:
                        record["warnings"].append(f"xlsx_unread_content:{name}:headerFooter_unsupported")

                for item in _relationships(archive, part):
                    kind = item.get("Type", "").rsplit("/", 1)[-1]
                    if "threadedcomment" in kind.casefold():
                        record["warnings"].append(f"xlsx_unread_content:{name}:threaded_comments")
                    if kind != "comments":
                        continue
                    if item.get("TargetMode") == "External" or not item.get("Target"):
                        record["warnings"].append(f"xlsx_unread_content:{name}:cell_comments")
                        continue
                    comment_part = _target(part, item["Target"])
                    comments = ET.fromstring(archive.read(comment_part))
                    authors = [node.text or "" for node in comments.findall(f"{{{_S}}}authors/{{{_S}}}author")]
                    unsupported = (comments.tag != f"{{{_S}}}comments" or bool(comments.attrib)
                        or any(node.tag != f"{{{_S}}}{_name(node.tag)}" or _name(node.tag) not in (
                            _RICH_TEXT_TAGS | {"comments", "authors", "author", "commentList", "comment"})
                            for node in comments.iter())
                        or any((node.text or "").strip() and node.tag not in {f"{{{_S}}}author", f"{{{_S}}}t"}
                               or (node.tail or "").strip() for node in comments.iter())
                        or any(node.attrib for node in comments.findall(f"{{{_S}}}authors/{{{_S}}}author")))
                    seen = defaultdict(int)
                    for index, comment in enumerate(comments.findall(f"{{{_S}}}commentList/{{{_S}}}comment"), 1):
                        coordinate = comment.attrib.get("ref", "")
                        seen[coordinate] += 1
                        author_id = comment.attrib.get("authorId", "")
                        author = authors[int(author_id)] if author_id.isdigit() and int(author_id) < len(authors) else None
                        text = comment.find(f"{{{_S}}}text")
                        unsupported = (unsupported or not coordinate or author is None or seen[coordinate] > 1
                            or bool(set(comment.attrib) - {"ref", "authorId", "shapeId"})
                            or any(child.tag != f"{{{_S}}}text" for child in comment)
                            or text is None
                            or any(node.tag != f"{{{_S}}}{_name(node.tag)}" or _name(node.tag) not in _RICH_TEXT_TAGS for node in text.iter()))
                        literal = "" if text is None else "".join(node.text or "" for node in text.iter(f"{{{_S}}}t"))
                        record["rows"].append({"suffix": f"comment:{index}:{coordinate}", "body": {
                            "kind": "xlsx_cell_comment", "source_part": comment_part, "coordinate": coordinate,
                            "author": author, "author_id": author_id, "text": literal, "literal_xml": _xml(comment),
                        }})
                        if coordinate:
                            record["comment_coordinates"].append(coordinate)
                    if unsupported:
                        record["warnings"].append(f"xlsx_unread_content:{name}:cell_comments_unsupported")
                        record["rows"].append({"suffix": "comments:unsupported", "body": {
                            "kind": "xlsx_comments_unsupported", "source_part": comment_part,
                            "literal_xml": _xml(comments),
                        }})
            except (KeyError, ET.ParseError, ValueError):
                # A visible warning is retained; partial metadata bodies already
                # read stay available. No malformed part is treated as complete.
                record["warnings"].append(f"xlsx_unread_content:{name}:metadata_parse_error")
    return result
