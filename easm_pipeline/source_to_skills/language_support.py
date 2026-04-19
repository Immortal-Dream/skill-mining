"""Language and runtime hints for source-language skill packaging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LanguageRuntime:
    """Runtime metadata for a packaged source-language script."""

    language_id: str
    display_name: str
    suffixes: tuple[str, ...]
    runtime_hint: str
    example_command_template: str
    supports_help: bool = False
    compiled: bool = False

    def example_command(self, *, script_path: str, entry_symbol: str | None = None) -> str:
        entry_name = entry_symbol or "main"
        filename = Path(script_path).name
        stem = Path(filename).stem
        return self.example_command_template.format(
            script_path=script_path,
            filename=filename,
            stem=stem,
            entry_symbol=entry_name,
        )


LANGUAGE_RUNTIMES: tuple[LanguageRuntime, ...] = (
    LanguageRuntime(
        language_id="python",
        display_name="Python",
        suffixes=(".py",),
        runtime_hint="python",
        example_command_template="python {script_path} --help",
        supports_help=True,
    ),
    LanguageRuntime(
        language_id="java",
        display_name="Java",
        suffixes=(".java",),
        runtime_hint="java",
        example_command_template="javac {script_path} && java -cp scripts {stem}",
        compiled=True,
    ),
    LanguageRuntime(
        language_id="javascript",
        display_name="JavaScript",
        suffixes=(".js", ".mjs", ".cjs", ".jsx"),
        runtime_hint="node",
        example_command_template="node {script_path}",
    ),
    LanguageRuntime(
        language_id="typescript",
        display_name="TypeScript",
        suffixes=(".ts", ".tsx", ".mts", ".cts"),
        runtime_hint="ts-node",
        example_command_template="ts-node {script_path}",
    ),
    LanguageRuntime(
        language_id="shell",
        display_name="Shell",
        suffixes=(".sh", ".bash", ".zsh", ".ksh"),
        runtime_hint="bash",
        example_command_template="bash {script_path}",
    ),
    LanguageRuntime(
        language_id="powershell",
        display_name="PowerShell",
        suffixes=(".ps1", ".psm1"),
        runtime_hint="pwsh",
        example_command_template="pwsh -File {script_path}",
    ),
    LanguageRuntime(
        language_id="ruby",
        display_name="Ruby",
        suffixes=(".rb",),
        runtime_hint="ruby",
        example_command_template="ruby {script_path}",
    ),
    LanguageRuntime(
        language_id="php",
        display_name="PHP",
        suffixes=(".php",),
        runtime_hint="php",
        example_command_template="php {script_path}",
    ),
    LanguageRuntime(
        language_id="perl",
        display_name="Perl",
        suffixes=(".pl", ".pm"),
        runtime_hint="perl",
        example_command_template="perl {script_path}",
    ),
    LanguageRuntime(
        language_id="r",
        display_name="R",
        suffixes=(".r", ".R"),
        runtime_hint="Rscript",
        example_command_template="Rscript {script_path}",
    ),
    LanguageRuntime(
        language_id="julia",
        display_name="Julia",
        suffixes=(".jl",),
        runtime_hint="julia",
        example_command_template="julia {script_path}",
    ),
    LanguageRuntime(
        language_id="lua",
        display_name="Lua",
        suffixes=(".lua",),
        runtime_hint="lua",
        example_command_template="lua {script_path}",
    ),
    LanguageRuntime(
        language_id="go",
        display_name="Go",
        suffixes=(".go",),
        runtime_hint="go",
        example_command_template="go run {script_path}",
    ),
    LanguageRuntime(
        language_id="rust",
        display_name="Rust",
        suffixes=(".rs",),
        runtime_hint="rust-script",
        example_command_template="rust-script {script_path}",
        compiled=True,
    ),
    LanguageRuntime(
        language_id="swift",
        display_name="Swift",
        suffixes=(".swift",),
        runtime_hint="swift",
        example_command_template="swift {script_path}",
    ),
    LanguageRuntime(
        language_id="kotlin",
        display_name="Kotlin",
        suffixes=(".kt", ".kts"),
        runtime_hint="kotlinc",
        example_command_template="kotlinc -script {script_path}",
        compiled=True,
    ),
    LanguageRuntime(
        language_id="scala",
        display_name="Scala",
        suffixes=(".scala",),
        runtime_hint="scala",
        example_command_template="scala {script_path}",
    ),
    LanguageRuntime(
        language_id="groovy",
        display_name="Groovy",
        suffixes=(".groovy", ".gvy"),
        runtime_hint="groovy",
        example_command_template="groovy {script_path}",
    ),
    LanguageRuntime(
        language_id="dart",
        display_name="Dart",
        suffixes=(".dart",),
        runtime_hint="dart",
        example_command_template="dart {script_path}",
    ),
    LanguageRuntime(
        language_id="csharp",
        display_name="C#",
        suffixes=(".cs", ".csx"),
        runtime_hint="dotnet-script",
        example_command_template="dotnet script {script_path}",
        compiled=True,
    ),
    LanguageRuntime(
        language_id="fsharp",
        display_name="F#",
        suffixes=(".fs", ".fsx"),
        runtime_hint="dotnet-fsi",
        example_command_template="dotnet fsi {script_path}",
    ),
    LanguageRuntime(
        language_id="elixir",
        display_name="Elixir",
        suffixes=(".ex", ".exs"),
        runtime_hint="elixir",
        example_command_template="elixir {script_path}",
    ),
    LanguageRuntime(
        language_id="clojure",
        display_name="Clojure",
        suffixes=(".clj", ".cljs", ".cljc"),
        runtime_hint="clojure",
        example_command_template="clojure {script_path}",
    ),
    LanguageRuntime(
        language_id="haskell",
        display_name="Haskell",
        suffixes=(".hs",),
        runtime_hint="runghc",
        example_command_template="runghc {script_path}",
    ),
    LanguageRuntime(
        language_id="c",
        display_name="C",
        suffixes=(".c", ".h"),
        runtime_hint="cc",
        example_command_template="cc {script_path} -o skill-bin && ./skill-bin",
        compiled=True,
    ),
    LanguageRuntime(
        language_id="cpp",
        display_name="C++",
        suffixes=(".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"),
        runtime_hint="c++",
        example_command_template="c++ {script_path} -o skill-bin && ./skill-bin",
        compiled=True,
    ),
)

GENERIC_TEXT_RUNTIME = LanguageRuntime(
    language_id="generic",
    display_name="Generic Source",
    suffixes=(),
    runtime_hint="sandbox",
    example_command_template="sandbox-run --language generic --script {script_path} --entry {entry_symbol}",
)


_RUNTIMES_BY_SUFFIX = {
    suffix.lower(): runtime
    for runtime in LANGUAGE_RUNTIMES
    for suffix in runtime.suffixes
}

KNOWN_SOURCE_SUFFIXES = frozenset(_RUNTIMES_BY_SUFFIX)

_SHEBANG_MARKERS = {
    "python": "python",
    "python3": "python",
    "node": "javascript",
    "deno": "typescript",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "pwsh": "powershell",
    "powershell": "powershell",
    "ruby": "ruby",
    "perl": "perl",
    "php": "php",
    "Rscript": "r",
    "julia": "julia",
    "lua": "lua",
}

_RUNTIMES_BY_ID = {runtime.language_id: runtime for runtime in LANGUAGE_RUNTIMES}


def detect_runtime_for_path(path: Path, *, first_line: str | None = None) -> LanguageRuntime:
    """Detect the best-effort runtime descriptor for a source file."""

    suffix = path.suffix.lower()
    if suffix in _RUNTIMES_BY_SUFFIX:
        return _RUNTIMES_BY_SUFFIX[suffix]
    if first_line and first_line.startswith("#!"):
        parts = first_line[2:].strip().split()
        marker = parts[-1].split("/")[-1] if parts[:1] == ["/usr/bin/env"] and len(parts) > 1 else parts[0].split("/")[-1]
        language_id = _SHEBANG_MARKERS.get(marker)
        if language_id and language_id in _RUNTIMES_BY_ID:
            return _RUNTIMES_BY_ID[language_id]
    return GENERIC_TEXT_RUNTIME


def runtime_for_language(language_id: str) -> LanguageRuntime:
    """Return the runtime descriptor for a language id."""

    return _RUNTIMES_BY_ID.get(language_id, GENERIC_TEXT_RUNTIME)
