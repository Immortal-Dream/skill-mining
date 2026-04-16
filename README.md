# skill-mining

`skill-mining` is an experimental pipeline for turning either:

1. **source code** into packaged reusable skills, or
2. **execution traces / provenance DAGs** into packaged reusable skills.

The repository currently contains two closely related mining tracks under `skill-mining/easm_pipeline/`:

- **source-to-skills**: mine Python / Java source into standalone CLI-style skill packages
- **DAG-based skill mining**: mine provenance reports into composed workflow skills that replay repeated tool graphs

The project is aimed at converting low-level capabilities into a portable skill format with:

- a generated `SKILL.md`
- one or more runnable scripts under `scripts/`
- optional references under `references/`
- a registry entry in `skills_registry.json`

---

## Why this project exists

Many useful capabilities appear in one of two forms:

- **static code**: a reusable function or method already exists in a codebase
- **dynamic behavior**: an agent repeatedly performs the same multi-tool workflow, but that workflow only becomes obvious from traces

These are different discovery problems, but they share a lot of downstream packaging concerns:

- deciding whether something is reusable enough to become a skill
- exposing a clean invocation boundary
- validating generated scripts
- writing usable skill documentation
- packaging the result in a consistent on-disk format

This repository is the workbench for that end-to-end flow.

---

## Project layout

```text
skill-mining/
├── README.md
├── data/
│   ├── sample_python_source/
│   └── output_skills/
├── easm_pipeline/
│   ├── core/
│   │   └── llm_infra/
│   ├── source_to_skills/
│   │   ├── extraction/
│   │   ├── mining/
│   │   ├── script_mining/
│   │   ├── packaging/
│   │   └── synthesis/
│   ├── dag_to_skills/
│   ├── skill_mining.py
│   ├── provenance_trace.py
│   └── registered_skill_writer.py
└── test/
```

### Important modules

#### Source mining

- `easm_pipeline/source_to_skills/main_pipeline.py`
  - main orchestration for source mining
- `easm_pipeline/source_to_skills/extraction/`
  - Python / Java extraction
- `easm_pipeline/source_to_skills/mining/candidate_evaluator.py`
  - decides whether a capability should become a skill
- `easm_pipeline/source_to_skills/script_mining/script_generator.py`
  - generates standalone scripts from extracted source
- `easm_pipeline/source_to_skills/synthesis/skill_doc_generator.py`
  - generates `SKILL.md`
- `easm_pipeline/source_to_skills/packaging/`
  - filesystem output and registry management

#### DAG-based mining

- `easm_pipeline/skill_mining.py`
  - current DAG/provenance mining entrypoint
- `easm_pipeline/dag_to_skills/library_learning.py`
  - representative pattern mining and parallel planning
- `easm_pipeline/dag_to_skills/meta_tool_codegen.py`
  - code generation for replayable DAG/meta-tool wrappers
- `easm_pipeline/provenance_trace.py`
  - optional trace capture bridge using an AppWorld-style provenance proxy runtime

#### Shared workflow pieces

- `easm_pipeline/registered_skill_writer.py`
  - shared package writing + registry updating
- `easm_pipeline/core/llm_infra/`
  - optional structured-LLM support and CLI config helpers

---

## What a generated skill looks like

A generated skill is written as a self-contained directory:

```text
output_skills/<skill-id>/
├── SKILL.md
├── scripts/
│   └── <generated-script>.py
└── references/
    └── <optional-reference-files>
```

A registry file is also updated at:

```text
output_skills/skills_registry.json
```

This layout is shared by both mining tracks.

---

## Source-to-skills pipeline

### What it does

The source mining path:

1. walks a source directory
2. extracts callable capabilities from Python / Java
3. evaluates whether each capability is worth extracting as a skill
4. generates a reusable standalone script
5. validates the script
6. generates `SKILL.md`
7. packages the result into the registered skill layout

### Current behavior

- Python extraction works with tree-sitter when available and falls back to `ast`
- Java extraction works with tree-sitter when available and falls back to regex-based parsing
- candidate evaluation can be deterministic or LLM-backed
- script generation can be deterministic or LLM-backed
- `SKILL.md` generation can be deterministic or LLM-backed
- invalid LLM output is repaired or falls back to deterministic generation
- scripts are statically validated before packaging

### Typical entrypoint

```bash
python -m easm_pipeline.source_to_skills <source_dir> --output-dir output_skills
```

Optional LLM flags are supported, for example:

```bash
python -m easm_pipeline.source_to_skills <source_dir> \
  --output-dir output_skills \
  --use-llm \
  --model gpt-5.2
```

---

## DAG-based skill mining

### What it is

The DAG-based pipeline starts from **provenance reports** rather than source code.

A provenance report describes:

- tool calls
- produced values
- dependencies between produced values and later tool arguments
- unresolved / literal boundaries

From those reports, the pipeline mines repeated subgraphs and turns them into replayable workflow skills.

### Current progress

The DAG-based mining path is no longer just a standalone prototype. It now reuses much of the same workflow shape as source mining:

- representative pattern mining
- generated wrapper script creation
- script validation
- `SKILL.md` generation through the shared doc generator
- shared packaging / registry output
- shared optional LLM CLI configuration

It also now supports an **optional trace-capture workflow** so a report does not always have to be prepared manually first.

### What it can do today

#### 1. Mine repeated workflow patterns from provenance reports

Input:

- one or more `provenance_report.json` files

Output:

- one or more skill folders representing mined workflows

The pipeline identifies representative call subgraphs and computes:

- support
- compression gain
- sequential vs parallel latency
- external boundary inputs

#### 2. Generate composed workflow scripts

The generated DAG skill scripts can:

- replay a mined multi-tool workflow
- preserve inter-call composition through produced values
- expose external dependencies as CLI flags
- call independent read stages in parallel when safe

This is one of the main differences from source mining: the DAG path is fundamentally about **composition**, not just extraction of a single function.

#### 3. Preserve parallelism from the mined workflow

The DAG path includes an effect-aware scheduling pass that:

- groups independent read calls into parallel stages
- keeps dependent or risky calls sequential
- records the plan in the packaged references

So the mined skill is not only a wrapper around a sequence of calls; it is an execution plan derived from the graph.

#### 4. Generate skill documentation after mining

After a DAG tool/workflow is mined, the pipeline now generates `SKILL.md` as part of the normal packaging flow.

This is important because a mined workflow skill should be consumable the same way a source-mined skill is consumable.

#### 5. Capture traces through a proxy-style runtime

There is now an optional bridge in `easm_pipeline/provenance_trace.py` that can:

- load an `apis` factory
- proxy the returned APIs through an AppWorld-style provenance recorder
- run a workflow callable
- write a `provenance_report.json`
- immediately feed that report into DAG mining

This mirrors the original AppWorld provenance/proxy idea, but is surfaced through the skill-mining CLI.

### DAG CLI entrypoint

Mine from existing reports:

```bash
python -m easm_pipeline.skill_mining report_a.json report_b.json \
  --output-dir output_skills
```

Capture a trace and mine directly from it:

```bash
python -m easm_pipeline.skill_mining \
  --trace-apis-factory my_module:create_apis \
  --trace-workflow my_module:run_workflow \
  --trace-workflow-input-json '{"query": "alex"}' \
  --output-dir output_skills
```

Optional LLM flags are also available on this path.

### What the DAG path currently assumes

- a provenance report schema compatible with the graph loader
- tool namespaces that can be replayed through an `apis` object
- workflow boundaries expressible as CLI arguments

### What DAG mining is good at

DAG mining is currently best for workflows like:

- repeated login + fetch + follow-up action patterns
- repeated fan-out read patterns that can be parallelized
- multi-step workflows where composition matters more than any individual function body

It is much less about “extract this exact implementation from source” and much more about “package this recurring tool-use behavior”.

---

## Relationship between source mining and DAG mining

These two tracks are related but not identical.

### Source mining is best when:

- the reusable capability already exists as source code
- you want a clean standalone script around that implementation
- the logic is best understood statically

### DAG mining is best when:

- the capability emerges from repeated tool-use behavior
- composition and dataflow matter more than any single function body
- parallel execution opportunities should be preserved
- traces are a better source of truth than source files

### Shared pieces today

Both tracks now share:

- structured LLM config
- skill packaging layout
- registry writing
- script validation
- `SKILL.md` generation machinery

### Intentionally different pieces

They still differ in the actual generation core:

- source mining generates scripts from extracted source functions
- DAG mining generates scripts from mined graph structure and call composition

That difference is intentional.

---

## Current DAG-based mining status

### Implemented

- provenance report loading
- representative pattern mining
- anti-unification of argument structure
- execution-plan derivation with safe read parallelism
- composed wrapper script generation
- deterministic DAG `SKILL.md` generation
- shared `SkillDocGenerator` integration for DAG skills
- shared packaging / registry writing
- CLI-based trace capture via proxy/runtime bridge
- tests for DAG mining and trace capture

### Verified in this workspace

The following have been exercised during development:

- DAG mining from synthetic provenance reports
- AppWorld benchmark bridge usage
- trace-capture -> DAG mining -> packaged skill flow
- execution of generated DAG skill scripts
- shared skill-doc generation path for DAG skills

### Known limitations

- live LLM `SKILL.md` generation for DAG skills can still fail schema validation and fall back to deterministic docs
- DAG script generation itself is still deterministic / graph-specific rather than sharing the source `ScriptGenerator`
- trace capture currently depends on an AppWorld-style provenance runtime bridge; it is not yet a fully native, framework-agnostic tracer
- trace capture from arbitrary environments still depends on having a compatible `apis` factory and workflow callable
- representative pattern ranking is still fairly lightweight; there is room for stronger scoring and pruning

---

## TODOs

### High priority

- Improve DAG `SKILL.md` prompting so live LLM docs succeed more often without fallback
- Make DAG docs more explicitly reflect:
  - composition stages
  - parallel stages
  - expected API namespaces
  - traced boundary defaults vs required inputs
- Improve pattern ranking / filtering so low-value or partial subgraphs are less likely to be emitted

### Medium priority

- Introduce a more native skill-mining trace runtime instead of relying on the AppWorld-compatible provenance bridge
- Support batch trace capture more directly from multiple workflow runs
- Add richer metadata for mined DAG skills, such as:
  - number of occurrences
  - support across sessions/tasks
  - estimated speedup from parallel stages
- Improve handling of unresolved inputs and fallback origins
- Add more end-to-end datasets for DAG mining beyond synthetic examples

### Longer-term

- Unify the conceptual “agent workflow” story across source and DAG mining
- Support mining from richer agent traces beyond current provenance report format
- Add iterative refinement loops that compare mined DAG skills against future traces
- Support promotion / deduplication of overlapping DAG-derived skills
- Make trace capture and skill packaging easier to use outside AppWorld-derived environments

---

## Tests

Examples of useful targeted tests in this repo:

```bash
python skill-mining/test/test_stage1_pipeline.py
python skill-mining/test/test_dag_skill_pipeline.py
python skill-mining/test/test_phase1_llm_infra.py
python skill-mining/test/test_skill_mining_trace_capture.py
```

---

## Sample data

- `data/sample_python_source/`
  - small source examples for source mining
- `data/output_skills/`
  - example generated skills

These are useful for quick smoke tests and for understanding the produced package structure.

---

## In short

This project is currently a two-lane skill-mining system:

- **source mining** packages reusable code capabilities
- **DAG mining** packages reusable traced workflows

The DAG path has moved beyond a rough prototype:

- it preserves composition
- it preserves safe parallelism
- it generates skill docs
- it packages into the same registered-skill format
- it can now capture traces through a proxy workflow bridge before mining

The main unfinished work is improving DAG doc quality, ranking, and native tracing ergonomics.
