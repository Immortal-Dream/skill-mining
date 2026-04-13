"""Deterministic Java source extraction and localized dependency resolution."""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from easm_pipeline.core.llm_infra.schemas import ExtractedNode

from .common import deterministic_node_id, line_for_byte, normalize_signature, safe_relative_path
from .tree_sitter_support import build_parser, load_query_source


IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?(?P<name>[\w.*]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"\b(?:class|interface|enum|record)\s+(?P<name>[A-Z]\w*)\b")
ANNOTATION_RE = re.compile(r"@\w+(?:\s*\([^)]*\))?")
JAVADOC_RE = re.compile(r"/\*\*.*?\*/", re.DOTALL)
TYPE_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")
METHOD_RE = re.compile(
    r"^[ \t]*(?P<prefix>(?:/\*\*.*?\*/\s*|@\w+(?:\s*\([^)]*\))?\s*)*)"
    r"(?P<signature>[ \t]*(?:(?:public|protected|private|static|final|abstract|synchronized|native|"
    r"strictfp|default)\s+)*"
    r"(?:<[^>{};]+>\s*)?"
    r"(?:(?:[\w.$]+(?:<[^>{};]+>)?(?:\[\])?)\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\([^;{}]*\)"
    r"(?:\s*throws\s+[^{;]+)?\s*)"
    r"(?P<body_start>[{;])",
    re.DOTALL | re.MULTILINE,
)


class JavaMiner:
    """Extract Java methods and context without executing source code."""

    def __init__(self, *, prefer_tree_sitter: bool = True, allow_regex_fallback: bool = True) -> None:
        self.prefer_tree_sitter = prefer_tree_sitter
        self.allow_regex_fallback = allow_regex_fallback

    def mine_file(self, path: Path, *, project_root: Path | None = None) -> list[ExtractedNode]:
        source = path.read_text(encoding="utf-8")
        relative_path = safe_relative_path(path, project_root)
        nodes = self.mine_source(source, file_path=relative_path)
        logger.debug("Java extraction complete: file={} nodes={}", relative_path, len(nodes))
        return nodes

    def mine_source(self, source: str, *, file_path: str = "<memory>") -> list[ExtractedNode]:
        if self.prefer_tree_sitter:
            try:
                return self._mine_with_tree_sitter(source, file_path=file_path)
            except Exception as exc:
                if not self.allow_regex_fallback:
                    raise
                logger.warning(
                    "tree-sitter Java extraction failed; falling back to regex: file={} error={}",
                    file_path,
                    exc.__class__.__name__,
                )
        return self._mine_with_regex(source, file_path=file_path)

    def _mine_with_tree_sitter(self, source: str, *, file_path: str) -> list[ExtractedNode]:
        load_query_source("java")
        parser = build_parser("java")
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
        imports = _parse_imports(source)
        nodes: list[ExtractedNode] = []

        def walk(node: object, scope: tuple[str, ...]) -> None:
            node_type = getattr(node, "type", "")
            next_scope = scope
            if node_type in {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}:
                class_name = _field_text(node, "name", source_bytes) or "<anonymous-type>"
                next_scope = (*scope, class_name)
            if node_type in {"method_declaration", "constructor_declaration"}:
                nodes.append(_node_from_ts_method(node, source, source_bytes, file_path, next_scope, imports))
            for child in getattr(node, "children", ()):
                walk(child, next_scope)

        walk(tree.root_node, ())
        return nodes

    def _mine_with_regex(self, source: str, *, file_path: str) -> list[ExtractedNode]:
        imports = _parse_imports(source)
        nodes: list[ExtractedNode] = []
        for match in METHOD_RE.finditer(source):
            name = match.group("name")
            if name in {"if", "for", "while", "switch", "catch", "return", "new"}:
                continue
            body_start = match.group("body_start")
            end = _balanced_block_end(source, match.end("body_start") - 1) if body_start == "{" else match.end()
            start = match.start("prefix") if match.group("prefix").strip() else match.start("signature")
            raw_code = source[start:end]
            signature = normalize_signature(match.group("signature"))
            javadoc = _last_javadoc(match.group("prefix"))
            annotations = tuple(item.strip() for item in ANNOTATION_RE.findall(match.group("prefix")))
            dependencies = _resolve_local_dependencies(raw_code, imports)
            start_byte = len(source[:start].encode("utf-8"))
            end_byte = len(source[:end].encode("utf-8"))
            start_line = line_for_byte(source, start_byte)
            end_line = line_for_byte(source, end_byte)
            nodes.append(
                ExtractedNode(
                    node_id=deterministic_node_id(file_path, start_byte, end_byte, name),
                    language="java",
                    node_type="constructor" if _looks_like_constructor(name, source[:start]) else "method",
                    name=name,
                    signature=signature,
                    raw_code=raw_code,
                    docstring=javadoc,
                    file_path=file_path,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    start_line=start_line,
                    end_line=end_line,
                    scope_path=_class_scope_before(source, start),
                    annotations=annotations,
                    imports=tuple(imports),
                    dependencies=dependencies,
                    metadata={"parser": "java-regex-fallback"},
                )
            )
        return nodes


def _parse_imports(source: str) -> list[str]:
    return [match.group("name") for match in IMPORT_RE.finditer(source)]


def _balanced_block_end(source: str, opening_brace_index: int) -> int:
    depth = 0
    in_string: str | None = None
    escape = False
    index = opening_brace_index
    while index < len(source):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
        else:
            if char in {'"', "'"}:
                in_string = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
        index += 1
    return len(source)


def _last_javadoc(prefix: str) -> str | None:
    matches = JAVADOC_RE.findall(prefix)
    if not matches:
        return None
    text = matches[-1]
    text = re.sub(r"^/\*\*|\*/$", "", text.strip())
    lines = [re.sub(r"^\s*\*\s?", "", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip() or None


def _resolve_local_dependencies(raw_code: str, imports: list[str]) -> tuple[str, ...]:
    simple_to_import = {item.rsplit(".", 1)[-1]: item for item in imports if not item.endswith(".*")}
    used_types = set(TYPE_TOKEN_RE.findall(raw_code))
    dependencies = sorted(full_name for simple, full_name in simple_to_import.items() if simple in used_types)
    return tuple(dependencies)


def _class_scope_before(source: str, byte_start: int) -> tuple[str, ...]:
    prefix = source[:byte_start]
    return tuple(match.group("name") for match in CLASS_RE.finditer(prefix))


def _looks_like_constructor(name: str, prefix: str) -> bool:
    scope = _class_scope_before(prefix, len(prefix))
    return bool(scope and scope[-1] == name)


def _field_text(node: object, field_name: str, source_bytes: bytes) -> str | None:
    child = getattr(node, "child_by_field_name", lambda _name: None)(field_name)
    if child is None:
        return None
    return source_bytes[child.start_byte : child.end_byte].decode("utf-8")


def _node_from_ts_method(
    node: object,
    source: str,
    source_bytes: bytes,
    file_path: str,
    scope: tuple[str, ...],
    imports: list[str],
) -> ExtractedNode:
    name = _field_text(node, "name", source_bytes) or "<anonymous-method>"
    start_byte = getattr(node, "start_byte")
    end_byte = getattr(node, "end_byte")
    raw_code = source_bytes[start_byte:end_byte].decode("utf-8")
    signature = normalize_signature(raw_code.split("{", 1)[0].rstrip(";"))
    annotations = tuple(ANNOTATION_RE.findall(raw_code.split(signature, 1)[0]))
    return ExtractedNode(
        node_id=deterministic_node_id(file_path, start_byte, end_byte, name),
        language="java",
        node_type="constructor" if getattr(node, "type", "") == "constructor_declaration" else "method",
        name=name,
        signature=signature,
        raw_code=raw_code,
        docstring=_nearest_javadoc_before(source, start_byte),
        file_path=file_path,
        start_byte=start_byte,
        end_byte=end_byte,
        start_line=getattr(node, "start_point")[0] + 1,
        end_line=getattr(node, "end_point")[0] + 1,
        scope_path=scope,
        annotations=annotations,
        imports=tuple(imports),
        dependencies=_resolve_local_dependencies(raw_code, imports),
        metadata={"parser": "tree-sitter-java"},
    )


def _nearest_javadoc_before(source: str, start_byte: int) -> str | None:
    prefix = source[:start_byte]
    matches = list(JAVADOC_RE.finditer(prefix))
    if not matches:
        return None
    last = matches[-1]
    between = prefix[last.end() :].strip()
    if between and not all(line.strip().startswith("@") for line in between.splitlines() if line.strip()):
        return None
    return _last_javadoc(last.group(0))
