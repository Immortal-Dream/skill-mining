"""Deterministic Python source extraction.

No LLM calls are made in this module. The miner prefers tree-sitter when the
runtime dependency is installed and falls back to Python's built-in AST parser
for deterministic local extraction.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from loguru import logger

from easm_pipeline.core.llm_infra.schemas import ExtractedNode

from .common import (
    byte_offset_for_line_col,
    deterministic_node_id,
    safe_relative_path,
)
from .tree_sitter_support import build_parser, load_query_source


class PythonMiner:
    """Extract Python functions, signatures, docstrings, scope, and byte spans."""

    def __init__(self, *, prefer_tree_sitter: bool = True, allow_ast_fallback: bool = True) -> None:
        self.prefer_tree_sitter = prefer_tree_sitter
        self.allow_ast_fallback = allow_ast_fallback

    def mine_file(self, path: Path, *, project_root: Path | None = None) -> list[ExtractedNode]:
        source = path.read_text(encoding="utf-8")
        relative_path = safe_relative_path(path, project_root)
        nodes = self.mine_source(source, file_path=relative_path)
        logger.debug("Python extraction complete: file={} nodes={}", relative_path, len(nodes))
        return nodes

    def mine_source(self, source: str, *, file_path: str = "<memory>") -> list[ExtractedNode]:
        """Extract nodes from a Python source string."""

        if self.prefer_tree_sitter:
            try:
                return self._mine_with_tree_sitter(source, file_path=file_path)
            except Exception as exc:
                if not self.allow_ast_fallback:
                    raise
                logger.warning(
                    "tree-sitter Python extraction failed; falling back to ast: file={} error={}",
                    file_path,
                    exc.__class__.__name__,
                )
        return self._mine_with_ast(source, file_path=file_path)

    def _mine_with_tree_sitter(self, source: str, *, file_path: str) -> list[ExtractedNode]:
        """Use tree-sitter to parse before constructing extraction records.

        The bundled query is loaded here so query assets are validated whenever
        tree-sitter is available. Node construction still uses stable byte spans
        and tree-sitter syntax nodes rather than any probabilistic step.
        """

        load_query_source("python")
        parser = build_parser("python")
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
        imports = _top_level_imports_from_source(source)
        nodes: list[ExtractedNode] = []

        def walk(node: object, scope: tuple[str, ...]) -> None:
            node_type = getattr(node, "type", "")
            next_scope = scope
            if node_type == "class_definition":
                class_name = _field_text(node, "name", source_bytes) or "<anonymous-class>"
                next_scope = (*scope, class_name)
            if node_type == "function_definition":
                nodes.append(_node_from_ts_function(node, source, source_bytes, file_path, scope, imports))
                function_name = _field_text(node, "name", source_bytes) or "<anonymous-function>"
                next_scope = (*scope, function_name)
            for child in getattr(node, "children", ()):
                walk(child, next_scope)

        walk(tree.root_node, ())
        return nodes

    def _mine_with_ast(self, source: str, *, file_path: str) -> list[ExtractedNode]:
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        visitor = _PythonAstVisitor(
            source=source,
            lines=lines,
            file_path=file_path,
            imports=_top_level_imports_from_ast(source, tree),
        )
        visitor.visit(tree)
        return visitor.nodes


class _PythonAstVisitor(ast.NodeVisitor):
    def __init__(self, *, source: str, lines: list[str], file_path: str, imports: tuple[str, ...]) -> None:
        self.source = source
        self.lines = lines
        self.file_path = file_path
        self.imports = imports
        self.scope: list[str] = []
        self.nodes: list[ExtractedNode] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node, is_async=False)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node, is_async=True)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> None:
        if node.end_lineno is None:
            return
        first_line = _decorated_start_line(node)
        start_col = 0 if first_line < node.lineno else node.col_offset
        end_col = node.end_col_offset or len(self.lines[node.end_lineno - 1])
        start_byte = byte_offset_for_line_col(self.source, first_line, start_col)
        end_byte = byte_offset_for_line_col(self.source, node.end_lineno, end_col)
        raw_code = self.source.encode("utf-8")[start_byte:end_byte].decode("utf-8")
        signature = _signature_from_ast(node, is_async=is_async)
        decorators = tuple(_decorator_text(self.source, decorator) for decorator in node.decorator_list)
        node_type = "function"
        metadata = {"parser": "python-ast-fallback"}

        self.nodes.append(
            ExtractedNode(
                node_id=deterministic_node_id(self.file_path, start_byte, end_byte, node.name),
                language="python",
                node_type=node_type,
                name=node.name,
                signature=signature,
                raw_code=raw_code,
                docstring=ast.get_docstring(node),
                file_path=self.file_path,
                start_byte=start_byte,
                end_byte=end_byte,
                start_line=first_line,
                end_line=node.end_lineno,
                scope_path=tuple(self.scope),
                annotations=decorators,
                imports=self.imports,
                metadata=metadata,
            )
        )


def _decorated_start_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    if not node.decorator_list:
        return node.lineno
    return min(decorator.lineno for decorator in node.decorator_list)


def _decorator_text(source: str, node: ast.AST) -> str:
    text = ast.get_source_segment(source, node) or ast.dump(node)
    return f"@{text.strip().lstrip('@')}"


def _top_level_imports_from_source(source: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    return _top_level_imports_from_ast(source, tree)


def _top_level_imports_from_ast(source: str, tree: ast.Module) -> tuple[str, ...]:
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            text = ast.get_source_segment(source, node)
            if text:
                imports.append(text.strip())
    return tuple(imports)


def _signature_from_ast(node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> str:
    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({_arguments_to_source(node.args)})"
    if node.returns is not None:
        signature += f" -> {ast.unparse(node.returns)}"
    return signature


def _arguments_to_source(args: ast.arguments) -> str:
    pieces: list[str] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    posonly_cutoff = len(args.posonlyargs)
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        pieces.append(_arg_to_source(arg, default))
        if index + 1 == posonly_cutoff:
            pieces.append("/")
    if args.vararg:
        pieces.append("*" + _arg_to_source(args.vararg, None))
    elif args.kwonlyargs:
        pieces.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        pieces.append(_arg_to_source(arg, default))
    if args.kwarg:
        pieces.append("**" + _arg_to_source(args.kwarg, None))
    return ", ".join(pieces)


def _arg_to_source(arg: ast.arg, default: ast.expr | None) -> str:
    text = arg.arg
    if arg.annotation is not None:
        text += f": {ast.unparse(arg.annotation)}"
    if default is not None:
        text += f" = {ast.unparse(default)}"
    return text


def _field_text(node: object, field_name: str, source_bytes: bytes) -> str | None:
    child = getattr(node, "child_by_field_name", lambda _name: None)(field_name)
    if child is None:
        return None
    return source_bytes[child.start_byte : child.end_byte].decode("utf-8")


def _node_from_ts_function(
    node: object,
    source: str,
    source_bytes: bytes,
    file_path: str,
    scope: tuple[str, ...],
    imports: tuple[str, ...],
) -> ExtractedNode:
    name = _field_text(node, "name", source_bytes) or "<anonymous-function>"
    start_byte = getattr(node, "start_byte")
    end_byte = getattr(node, "end_byte")
    raw_code = source_bytes[start_byte:end_byte].decode("utf-8")
    start_line = getattr(node, "start_point")[0] + 1
    end_line = getattr(node, "end_point")[0] + 1
    parameters = _field_text(node, "parameters", source_bytes) or "()"
    return_type = _field_text(node, "return_type", source_bytes)
    prefix = "async def" if _has_async_child(node) else "def"
    signature = f"{prefix} {name}{parameters}"
    if return_type:
        signature += f" {return_type}"
    return ExtractedNode(
        node_id=deterministic_node_id(file_path, start_byte, end_byte, name),
        language="python",
        node_type="function",
        name=name,
        signature=signature,
        raw_code=raw_code,
        docstring=_python_docstring_from_raw(raw_code),
        file_path=file_path,
        start_byte=start_byte,
        end_byte=end_byte,
        start_line=start_line,
        end_line=end_line,
        scope_path=scope,
        annotations=_decorators_from_preceding_source(source, start_line),
        imports=imports,
        metadata={"parser": "tree-sitter-python"},
    )


def _has_async_child(node: object) -> bool:
    return any(getattr(child, "type", "") == "async" for child in getattr(node, "children", ()))


def _python_docstring_from_raw(raw_code: str) -> str | None:
    try:
        module = ast.parse(raw_code)
    except SyntaxError:
        return None
    for child in module.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ast.get_docstring(child)
    return None


def _decorators_from_preceding_source(source: str, start_line: int) -> tuple[str, ...]:
    lines = source.splitlines()
    decorators: list[str] = []
    index = start_line - 2
    while index >= 0 and lines[index].lstrip().startswith("@"):
        decorators.append(lines[index].strip())
        index -= 1
    return tuple(reversed(decorators))


