# Encode Repository

Systematically populate the Forgetful knowledge base using your shell tools (grep/ripgrep/find) for accurate, comprehensive codebase understanding.

## Objective

**Encode this repository into Forgetful so thoroughly that a future agent — with NO access to the source code — can answer detailed, specific technical questions about it accurately, using only what you store in Forgetful.**

This is the bar every memory, entity, document, and artifact is measured against. As you encode, keep asking: *"If the code were deleted right now, could an agent answer a precise question about this from Forgetful alone?"* If not, the encoding is incomplete.

Concretely, the stored knowledge must be enough to answer questions like:
- "Where is [behaviour] implemented, and how does it work?" — file paths, function/class names, and the mechanism
- "What is the call flow for [feature], end to end?" — entry point through the components involved
- "What does [class/function] do, what does it depend on, and what depends on it?"
- "What patterns/conventions does this codebase use, and where?"
- "What are the dependencies and how are they used?"

Capture concrete specifics — exact symbol names, file paths, signatures, relationships, and representative code — not vague summaries. Generic prose that could describe any project is a failure; an agent cannot answer a precise question from "this project has a service layer."

## Purpose

Transform an undocumented or lightly-documented codebase into a rich, searchable knowledge repository. Use this when:
- Starting to use Forgetful for an existing project
- Onboarding a new project into the memory system
- Preparing a project for AI agent collaboration
- Creating institutional knowledge for team members
- You want **accurate architecture mapping** grounded in real declarations and usages

## Approach

Build understanding with systematic code exploration:
- **Structure discovery** via `find` / `git ls-files`
- **Symbol extraction** via `grep`/`ripgrep` for declarations (classes, functions, methods)
- **Relationship discovery** via `ripgrep` for usages and callers across files
- **Reading** files directly with your Read tool

If you have LSP-backed symbol tools available, **prefer them** for language-aware accuracy (exact symbol locations and reference counts). Otherwise, `ripgrep` scoped to code files is the reliable fallback — be aware its counts are approximate (text matches, not resolved references).

## Prerequisites Check (EXECUTE FIRST)

Verify Forgetful MCP is connected by testing:
```
execute_forgetful_tool("list_projects", {})
```

If Forgetful errors, stop — the knowledge base is unavailable and encoding cannot proceed.

## Arguments

$ARGUMENTS

Parse for:
- **Project path**: Directory to encode (default: current working directory)
- **Project name**: Override auto-detected name (optional)
- **Phases**: Specific phases to run (optional, default: all)

---

## Memory Targets by Project Profile

| Profile | Phase 1 | Phase 1B | Phase 2 | Phase 2B | Phase 3 | Phase 4 | Phase 5 | Phase 6 | Phase 6B | Phase 7B | Total |
|---------|---------|----------|---------|----------|---------|---------|---------|---------|----------|----------|-------|
| Small Simple | 3-5 | 1-2 | 3-5 | 3-5 entities | 3-5 | 2-4 | 0-2 | 3-5 artifacts | 1 doc + 1 mem | 1 doc + 1 mem | 17-31 memories + 2 docs + 3-5 artifacts + entities |
| Small Complex | 5-7 | 1-2 | 5-8 | 5-10 entities | 5-8 | 4-6 | 0-3 | 5-8 artifacts | 1 doc + 1 mem | 1 doc + 1 mem | 28-46 memories + 2 docs + 5-8 artifacts + entities |
| Medium Standard | 5-10 | 1-2 | 10-15 | 10-20 entities | 8-12 | 5-10 | 0-5 | 5-10 artifacts | 1-2 docs + 1-2 mems | 1 doc + 1 mem | 38-66 memories + 2-3 docs + 5-10 artifacts + entities |
| Large | 8-12 | 2-3 | 15-20 | 20-40 entities | 12-18 | 10-15 | 0-8 | 8-15 artifacts | 2-4 docs + 2-4 mems | 1-2 docs + 1-2 mems | 66-112 memories + 3-6 docs + 8-15 artifacts + entities |

**Notes**:
- Phase 1 now includes project.notes update (instant context primer)
- Phase 1B creates 1-3 dependency memories per project
- **Phase 2B is MANDATORY** - creates entities for components and their relationships
- Phase 5 is CONDITIONAL - only if explicit documentation exists (see Phase 5 guidelines)
- **Phase 6 is MANDATORY** - minimum 3 code artifacts for any project
- Phase 6B creates Symbol Index document(s) with entry memory - split by layer for large projects
- Phase 7B creates Architecture Reference document with entry memory

---

## Phase Completion Gates

**CRITICAL**: Do not proceed to the next phase until the current phase meets its minimum targets.

After each phase, report:
```
Phase [N] Complete:
- Created: [X] memories, [Y] entities, [Z] artifacts
- Minimum required: [targets from table above]
- Status: ✅ Met / ❌ Not met (explain gaps)
```

**Mandatory phases** (cannot skip):
- Phase 0: Discovery
- Phase 1: Foundation
- Phase 2: Architecture
- **Phase 2B: Entity Graph** (minimum 3 entities for any project)
- Phase 3: Patterns (minimum 3 pattern memories)
- Phase 6: Code Artifacts (minimum 3 artifacts)
- Phase 6B: Symbol Index
- Phase 7B: Architecture Document

**Conditional phases** (skip only if criteria not met):
- Phase 1B: Dependencies (skip if single-file script with no deps)
- Phase 4: Features (skip if <3 distinct features)
- Phase 5: Decisions (skip if NO explicit documentation found - see guidelines)
- Phase 7: Additional Documents (skip if no long-form content needed)

---

## Phase 0: Discovery & Assessment (ALWAYS START HERE)

### Step 1: Explore Project Structure

List the project's files (respecting version control / ignore rules):
```bash
git ls-files | head -200
# or, if not a git repo:
find . -type f -not -path './.git/*' | head -200
```

### Step 2: Check Existing Forgetful Coverage

```
execute_forgetful_tool("list_projects", {})
```

If project exists, query existing memories:
```
execute_forgetful_tool("query_memory", {
  "query": "<project-name> architecture",
  "query_context": "Assessing KB coverage before bootstrap",
  "k": 10,
  "project_ids": [<project_id>]
})
```

### Step 3: Analyze Entry Points

Read key files to understand the project (use your Read tool, or `cat`):
```bash
cat README.md
cat pyproject.toml   # or package.json, Cargo.toml, go.mod, etc.
```

### Step 4: Gap Analysis

Compare:
- What's in Forgetful KB?
- What exists in codebase?
- What's missing?

Report findings before proceeding.

---

## Phase 1: Project Foundation (5-10 memories)

### Create/Update Project in Forgetful

If project doesn't exist:
```
execute_forgetful_tool("create_project", {
  "name": "owner/repo-name",
  "description": "<problem solved, features, tech stack>",
  "project_type": "development",
  "repo_name": "owner/repo"
})
```

### Update Project Notes

After project creation (or if notes are empty), populate with high-level overview:
```
execute_forgetful_tool("update_project", {
  "project_id": <id>,
  "notes": "Entry: python3 -m ProjectName.main <mode>
Tech: Python 3.12, ClickHouse, XGBoost, FastAPI, Streamlit
Architecture: 6-layer (Data→Domain→Processing→ML→Strategy→Presentation)
Key patterns: Repository, Async generators, Batch writes, Factory
Core components: ConnectionPool, Fetchers, Writers, ML Pipeline"
})
```

**Notes format guidance** (500-1000 chars max):
- Entry point command
- Tech stack summary (language, major frameworks, database)
- Architecture pattern (layer count, pattern name)
- Key patterns used
- Core components (top 5 by importance)

This provides instant context without querying memories.

### Create Foundation Memories

1. **Project Overview** (Importance: 10)
2. **Technology Stack** (Importance: 9)
3. **Architecture Pattern** (Importance: 10)
4. **Development Setup** (Importance: 8)
5. **Testing Strategy** (Importance: 8)

---

## Phase 1B: Dependency Analysis

**Purpose**: Extract and document project dependencies systematically from the project's own manifests.

### Step 1: Detect Manifest Files

Look for dependency manifests:
```bash
find . -maxdepth 2 -name package.json -not -path './node_modules/*'
# or list all candidates at once:
rg --files -g '{package.json,pyproject.toml,requirements.txt,Pipfile,Cargo.toml,go.mod,Gemfile,pom.xml,build.gradle}'
```

Common manifests to check:
- `package.json` (Node.js)
- `pyproject.toml`, `requirements.txt`, `Pipfile` (Python)
- `Cargo.toml` (Rust)
- `go.mod` (Go)
- `Gemfile` (Ruby)
- `pom.xml`, `build.gradle` (Java)

### Step 2: Parse Dependencies

Read manifest and extract:
- Direct dependencies (name, version)
- Dev dependencies
- Categorize by role: framework, library, database, tool

### Step 3: Create Dependency Memory

```
execute_forgetful_tool("create_memory", {
  "title": "[Project] - Dependencies and External Libraries",
  "content": "Language: [lang] [version]. Core frameworks: [list with roles].
              Data/storage: [databases]. HTTP/API: [frameworks].
              Dev tools: [testing, linting, build].
              Rationale: [why chosen, if documented].",
  "context": "Understanding technology choices and integration patterns",
  "keywords": ["tech-stack", "dependencies", "frameworks", "libraries"],
  "tags": ["technology", "foundation", "dependencies"],
  "importance": 9,
  "project_ids": [<project_id>]
})
```

---

## Phase 2: Symbol-Level Architecture (10-15 memories)

**Map the codebase's symbols and how they connect.**

### Step 1: Get Symbol Overview for Key Files

For each major source file, list its top-level symbols (classes, functions, methods):
```bash
grep -nE '^(class |def |async def |    def )' src/main.py
# Prefer your LSP/symbol tools here if available for language-aware accuracy.
```

This surfaces classes, functions, and methods with their line locations.

### Step 2: Analyze Key Classes/Modules

For important symbols discovered, locate the definition:
```bash
rg -n 'class ClassName|def ClassName' -g '*.py'
```

### Step 3: Discover Relationships

For core classes/functions, find usages and callers across the repo:
```bash
rg -n 'ClassName' -g '*.py'        # where is it used?
rg -c 'method_name' -g '*.py'      # approximate usage count per file
```

This reveals:
- Who calls this method?
- Where is this class used?
- What depends on what?

(If you have LSP tools, prefer exact reference lookups over text matches.)

### Step 4: Create Architecture Memories

For each architectural layer discovered:
```
{
  "title": "[Project] - [Layer] Architecture",
  "content": "Key symbols: [list]. Relationships: [discovered references]. Pattern: [identified pattern].",
  "context": "Discovered via code/symbol analysis",
  "importance": 8,
  "tags": ["architecture"]
}
```

---

## Phase 2B: Entity Graph Creation (MANDATORY)

**Purpose**: Build a knowledge graph of project components and their relationships in Forgetful.

**THIS PHASE IS MANDATORY** - Minimum 3 entities for any project.

### Why Entities Matter

Entities enable:
- Cross-project discovery ("What projects use FastAPI?")
- Relationship mapping ("What depends on this component?")
- Knowledge graph navigation beyond text search
- Grounding abstract concepts in concrete components

Without entities, the encoding is incomplete. An agent querying "what components exist" will get nothing.

### Minimum Entity Requirements

| Project Size | Component Entities | Library/Framework Entities | Total Minimum |
|--------------|-------------------|---------------------------|---------------|
| Small | 2-3 core classes | 1-2 key deps | 3-5 |
| Medium | 5-10 services/modules | 3-5 frameworks | 10-20 |
| Large | 10-20 major components | 5-10 key deps | 20-40 |

### Entity Deduplication (ALWAYS CHECK FIRST)

Before creating any entity, check if it already exists:
```
execute_forgetful_tool("search_entities", {
  "query": "<entity-name>",
  "limit": 5
})
```

The search checks both `name` and `aka` (aliases) fields.

- **If found**: Use existing entity ID, optionally update notes/tags
- **If not found**: Create with comprehensive `aka` list for future matching

### Standard Entity Types

Use `entity_type: "other"` with these `custom_type` values (allow flexibility for non-standard cases):
- `Library` - external packages/dependencies (npm, pip, cargo packages)
- `Service` - backend services, APIs, microservices
- `Component` - major code components, modules
- `Tool` - build tools, CLI tools, parsers
- `Framework` - core frameworks (or use `entity_type: "organization"`)

### Entity Creation Criteria

Only create entities for **major components**:
- High usage count from grep/LSP analysis (agent judges "high" based on project size)
- Core architectural components (services, modules with many dependents)
- External dependencies central to the project
- Services/modules that other components depend on

### Tagging Strategy

- Use `project_ids` for scoping (no discovery-method tags)
- Tag by role: `library`, `service`, `component`, `database`, `framework`, `tool`
- Tag by domain if relevant: `auth`, `api`, `storage`, `ui`, `config`

### Step 1: Create Entities for Major Components

For each major component discovered:
```
execute_forgetful_tool("create_entity", {
  "name": "AuthenticationService",
  "entity_type": "other",
  "custom_type": "Service",
  "notes": "Centralized auth service. Location: src/services/auth.py.
            Handles token validation, user context injection.",
  "tags": ["service", "auth"],
  "aka": ["AuthService", "auth", "auth_service"],
  "project_ids": [<project_id>]
})
```

### Step 2: Create Entities for Key Dependencies

For external libraries central to the project:
```
execute_forgetful_tool("create_entity", {
  "name": "FastAPI",
  "entity_type": "other",
  "custom_type": "Framework",
  "notes": "Python async web framework. Used for REST API and WebSocket endpoints.",
  "tags": ["framework", "api"],
  "aka": ["fastapi", "fast-api", "fast_api"],
  "project_ids": [<project_id>]
})
```

### Step 3: Create Relationships

Map how components connect using usage counts from your grep/LSP analysis:
```
execute_forgetful_tool("create_entity_relationship", {
  "source_entity_id": <project_or_component_id>,
  "target_entity_id": <library_id>,
  "relationship_type": "uses",
  "strength": 1.0,
  "metadata": {
    "version": "0.104.1",
    "role": "HTTP framework and routing"
  }
})
```

**Relationship types**:
- `uses` - project/component uses library
- `depends_on` - component depends on another
- `calls` - service calls another service
- `extends` - class extends base class
- `implements` - class implements interface
- `connects_to` - system connects to database/service

**Strength calculation**:
- Based on usage count (grep matches, or exact LSP references if available)
- Normalize to 0.0-1.0 scale within project
- Higher usage count = higher strength

### Step 4: Link Entities to Memories

Connect entities to their architecture memories:
```
execute_forgetful_tool("link_entity_to_memory", {
  "entity_id": <component_entity_id>,
  "memory_id": <architecture_memory_id>
})
```

This enables bidirectional discovery:
- Find entity → get related memories
- Query memories → discover linked entities

### Phase 2B Completion Checkpoint

```
Phase 2B Complete:
- Component entities created: [count] (minimum 2-3)
- Library/framework entities created: [count] (minimum 1-2)
- Relationships created: [count]
- Entities linked to memories: [count]
- Status: ✅ Met minimum / ❌ Not met (create more before proceeding)
```

**DO NOT proceed to Phase 3 until minimum entity count is met.**

---

## Phase 3: Pattern Discovery (8-12 memories, minimum 3)

**Purpose**: Document recurring implementation patterns that define how the codebase works.

### Pattern Categories to Search

**1. Concurrency/Async Patterns**
```bash
rg -nE 'async def|await|asyncio|yield' -g '*.py' -A 5
```

**2. Error Handling Patterns**
```bash
rg -nE 'except.*:|catch\s*\(|raise|throw' -g '*.{py,js,ts}'
```

**3. Dependency Injection / IoC**
```bash
rg -nE 'Depends\(|@inject|Container|def __init__\(self,.*:' -g '*.py'
```

**4. Decorator/Middleware Patterns**
```bash
rg -nE '@app\.|@router\.|@middleware|@(before|after)' -g '*.py'
```

**5. Database/Transaction Patterns**
```bash
rg -nE 'session|transaction|commit|rollback|with.*connection' -g '*.py'
```

**6. Factory/Builder Patterns**
```bash
rg -nE 'Factory|Builder|create_|build_|make_' -g '*.py'
```

**7. Repository/Data Access Patterns**
```bash
rg -nE 'Repository|DAO|DataAccess|load_|save_|find_' -g '*.py'
```

**8. Event/Observer Patterns**
```bash
rg -nE 'emit|on_|subscribe|publish|EventHandler|Observer' -g '*.py'
```

### Analyze Pattern Usage

For each pattern found with >3 occurrences, locate the implementation and read its body:
```bash
rg -n 'pattern_name' -g '*.py'
# then read the surrounding code with your Read tool
```

Use a repo-wide search to understand how a pattern is used (callers/usages):
```bash
rg -n 'PatternClass' -g '*.py'
```

### Create Pattern Memories

For each significant pattern (used 3+ times):
```
execute_forgetful_tool("create_memory", {
  "title": "[Project] - [Pattern Name] Pattern",
  "content": "Pattern: [name]. Used for: [purpose].
              Locations: [list files/classes using it].
              Implementation: [brief description of how it works].
              Usage count: [X] occurrences across codebase.",
  "context": "Recurring implementation pattern for [purpose]",
  "keywords": ["pattern", "<pattern-name>", "<domain>"],
  "tags": ["pattern", "implementation"],
  "importance": 7,
  "project_ids": [<project_id>]
})
```

### Phase 3 Completion Checkpoint

```
Phase 3 Complete:
- Patterns searched: [list categories checked]
- Patterns documented: [count] (minimum 3)
- Pattern memories created: [list titles]
- Status: ✅ Met minimum / ❌ Not met (continue searching)
```

**Minimum 3 pattern memories required.** If fewer than 3 patterns found, document whatever exists (even basic ones like "error handling approach").

---

## Phase 4: Critical Features (1-2 per feature, minimum 3 features)

**Purpose**: Document major user-facing features and their implementation flows.

### Identify Features via Code Search

**1. API Endpoints (REST/GraphQL)**
```bash
rg -nE '@(app|router)\.(get|post|put|delete|patch)|@(Query|Mutation)' -g '*.py'
```

**2. CLI Commands**
```bash
rg -nE '@click\.|@command|argparse|subparser' -g '*.py'
```

**3. Background Jobs/Tasks**
```bash
rg -nE '@task|@job|celery|schedule|cron' -g '*.py'
```

**4. UI Pages/Components (for frontend)**
```bash
rg -nE 'export.*function.*Page|def.*page|class.*View' -g '*.{py,js,ts,tsx}'
```

**5. Main Workflows**
```bash
rg -nE 'def main|def run|def process|def execute' -g '*.py'
```

### Trace Feature Flow

For each feature:
1. Find the entry point symbol
2. Search the repo for usages to trace downstream callers
3. Identify all components involved
4. Document the complete flow

```bash
rg -n 'endpoint_function' -g '*.py'
```

### Create Feature Memories

For each major feature:
```
execute_forgetful_tool("create_memory", {
  "title": "[Project] - [Feature Name] Implementation",
  "content": "Feature: [user-facing description].
              Entry point: [file:function].
              Flow: [step-by-step through components].
              Key components: [list classes/functions involved].
              Configuration: [relevant settings if any].",
  "context": "Implementation details for [feature purpose]",
  "keywords": ["feature", "<feature-name>", "implementation"],
  "tags": ["feature", "implementation"],
  "importance": 8,
  "project_ids": [<project_id>]
})
```

### Phase 4 Completion Checkpoint

```
Phase 4 Complete:
- Features identified: [count]
- Feature memories created: [count] (minimum 3 for projects with 3+ features)
- Feature flows traced: [list]
- Status: ✅ Met / ⚠️ Fewer than 3 features exist (acceptable)
```

**Skip only if** project has fewer than 3 distinct features (e.g., single-purpose library).

---

## Phase 5: Design Decisions (DOCUMENTATION-ONLY)

**CRITICAL: This phase is CONDITIONAL. Only capture decisions that are EXPLICITLY documented.**

### What Counts as "Documented"

✅ **DO create decision memories for**:
- ADRs (Architecture Decision Records) in `docs/adr/` or similar
- README sections titled "Why X", "Rationale", "Design Decisions"
- Code comments explicitly stating "We chose X because Y"
- CONTRIBUTING.md or DESIGN.md files explaining choices
- Commit messages or PR descriptions linked from docs

❌ **DO NOT create decision memories for**:
- Inferred decisions (e.g., "They use PostgreSQL so they must value ACID")
- Technology choices without documented rationale
- Patterns you observe but aren't explained
- Your assumptions about why something was built a certain way
- Standard framework conventions (e.g., "FastAPI uses Pydantic")

### Search for Decision Documentation

```bash
rg -nE 'Decision:|Rationale:|## Why|ADR-|chose.*because|decided.*to|trade-?off' -g '*.md'
```

Also check:
```bash
rg -nE '# Why|## Rationale|Design Decision' -g '*.md'
```

And code comments:
```bash
rg -nE '# NOTE:.*chose|# DECISION:|# WHY:' -g '*.py'
```

### Phase 5 Outcomes

**If documentation found**:
Create 1 memory per documented decision:
```
execute_forgetful_tool("create_memory", {
  "title": "[Project] - Decision: [Topic]",
  "content": "Decision: [what was decided].
              Alternatives considered: [if documented].
              Rationale: [QUOTE from documentation].
              Source: [file path and line number].",
  "context": "Documented design decision from [source file]",
  "keywords": ["decision", "architecture", "rationale", "<topic>"],
  "tags": ["decision", "documented"],
  "importance": 8,
  "project_ids": [<project_id>]
})
```

**If NO documentation found**:
```
Phase 5 Complete:
- Searched: [X] markdown files, [Y] code files
- Documented decisions found: 0
- Status: ✅ SKIPPED (no explicit documentation)
```

**DO NOT** create decision memories based on inference. This pollutes the knowledge base with assumptions.

---

## Phase 6: Code Artifacts (MANDATORY, minimum 3)

**Purpose**: Store reusable code patterns that enable an agent to understand HOW the codebase works, not just WHAT exists.

**THIS PHASE IS MANDATORY** - Minimum 3 artifacts for any project.

### Why Code Artifacts Matter

Without artifacts, an agent knows components exist but cannot:
- Write code that integrates with existing patterns
- Understand implementation details
- See actual syntax and conventions used
- Learn project-specific idioms

### Artifact Selection Criteria

Create artifacts for:
1. **Core patterns** - Most-used patterns from Phase 3 (async generators, factories, etc.)
2. **Interface contracts** - Base classes/interfaces that define extensibility points
3. **Entry point examples** - Main handlers, API endpoints, CLI commands
4. **Utility functions** - Frequently-used helpers
5. **Configuration patterns** - How config is loaded/used

### Minimum Artifact Requirements

| Project Size | Minimum Artifacts | Recommended |
|--------------|-------------------|-------------|
| Small | 3 | 3-5 |
| Medium | 5 | 5-10 |
| Large | 8 | 8-15 |

### Extract Code

Locate the symbol, then read its full body with your Read tool:
```bash
rg -n 'def key_method|class PatternClass' -g '*.py'
# then read the lines spanning the implementation
```

### Create Artifacts

For each key pattern/utility:
```
execute_forgetful_tool("create_code_artifact", {
  "title": "[Project] - [Pattern Name] ([Language])",
  "description": "What: [brief description of what it does].
                  When: [when to use this pattern].
                  Where: [file location in codebase].
                  Usage: [how other code uses this].",
  "code": "<full implementation read from the file>",
  "language": "python",
  "tags": ["pattern", "<domain-tag>"],
  "project_id": <project_id>
})
```

### Recommended Artifacts by Project Type

**Web API**:
1. Request handler pattern (endpoint example)
2. Middleware/interceptor pattern
3. Repository/data access pattern
4. Error handling pattern
5. Authentication pattern

**CLI Tool**:
1. Command handler pattern
2. Argument parsing pattern
3. Output formatting pattern

**Data Pipeline**:
1. Async generator/streaming pattern
2. Batch processing pattern
3. Transformation/mapping pattern
4. Error recovery pattern

**Library/SDK**:
1. Public API entry point
2. Factory/builder pattern
3. Configuration pattern
4. Extension point example

### Phase 6 Completion Checkpoint

```
Phase 6 Complete:
- Code artifacts created: [count] (minimum 3)
- Artifacts by category: [patterns: X, interfaces: Y, utilities: Z]
- Artifact titles: [list]
- Status: ✅ Met minimum / ❌ Not met (create more before proceeding)
```

**DO NOT proceed to Phase 6B until minimum artifact count is met.**

---

## Phase 6B: Symbol Index Document

**Purpose**: Compile your symbol analysis into a permanent, searchable Forgetful document.

This captures symbol locations, relationships, and approximate usage counts as a durable reference.

### Step 1: Aggregate Symbol Data

Collect from all the symbol exploration you did during Phase 2:
- Classes with file locations and line numbers
- Interfaces with their implementations
- Key functions with callers (from your usage searches)
- Usage counts for each symbol

### Step 2: Create Symbol Index Document

```
execute_forgetful_tool("create_document", {
  "title": "[Project] - Symbol Index",
  "description": "Symbol listing with locations, relationships, and usage counts. Generated via code analysis.",
  "content": "<structured markdown table - see format below>",
  "document_type": "markdown",
  "project_id": <id>,
  "tags": ["symbol-index", "reference", "navigation"]
})
```

**Document Format:**
```markdown
# [Project] - Symbol Index

Generated: [date]
Total: X classes, Y interfaces, Z functions

## Classes

| Symbol | Location | Description | Refs |
|--------|----------|-------------|------|
| ClassName | path/file.py:line | Brief description | count |
| ... | ... | ... | ... |

## Interfaces

| Symbol | Location | Implementations |
|--------|----------|-----------------|
| InterfaceName | path/file.py:line | Impl1, Impl2 |
| ... | ... | ... |

## Key Functions

| Symbol | Location | Called By |
|--------|----------|-----------|
| func_name | path/file.py:line | Caller1, Caller2 |
| ... | ... | ... |
```

### Step 3: Create Entry Memory

Create an atomic memory that summarizes the index and links to the document:
```
execute_forgetful_tool("create_memory", {
  "title": "[Project] - Symbol Index Reference",
  "content": "Symbol index contains X classes, Y interfaces, Z functions.
              Top referenced: [list top 5 by usage count].
              Key interfaces: [list with implementation counts].
              Full index in linked document.",
  "context": "Entry point for symbol navigation - links to full index document",
  "keywords": ["symbols", "classes", "functions", "navigation", "index"],
  "tags": ["reference", "navigation", "symbol-index"],
  "importance": 8,
  "project_ids": [<id>],
  "document_ids": [<symbol_index_doc_id>]
})
```

### Size Guidelines

| Project Size | Est. Symbols | Doc Size | Split? |
|--------------|--------------|----------|--------|
| Small | <50 | <2000 words | No |
| Medium | 50-150 | 2000-5000 words | No |
| Large | 150+ | >5000 words | Yes, by layer |

**If splitting** (large projects):
- Create separate docs per architectural layer: `[Project] - Symbol Index: Data Layer`
- Each doc gets its own entry memory
- Entry memories link to their respective documents

---

## Phase 7: Documents (as needed)

For content >400 words (detailed guides, comprehensive analysis):
```
execute_forgetful_tool("create_document", {
  "title": "Document name",
  "description": "Overview and purpose",
  "content": "<full documentation>",
  "document_type": "markdown",
  "project_id": <project_id>
})
```

Create 3-5 atomic memories as entry points, linked via `document_ids`.

---

## Phase 7B: Architecture Document

**Purpose**: Consolidate the architecture analysis into a comprehensive reference document.

This creates the definitive architecture reference for the project.

### Step 1: Synthesize Architecture Content

Combine insights from:
- Phase 2 architecture memories (symbol-level analysis)
- Phase 2B entity relationships (component graph)
- Phase 3 pattern discoveries
- The usage/relationship data from your code searches

### Step 2: Create Architecture Document

```
execute_forgetful_tool("create_document", {
  "title": "[Project] - Architecture Reference",
  "description": "Comprehensive architecture documentation with layer details, component relationships, and design patterns. Generated via code analysis.",
  "content": "<structured architecture doc - see format below>",
  "document_type": "markdown",
  "project_id": <id>,
  "tags": ["architecture", "reference", "design"]
})
```

**Document Format:**
```markdown
# [Project] - Architecture Reference

Generated: [date]

## Overview

[2-3 paragraph summary of what the system does and how it's structured]

## Architecture Diagram

┌─────────────────────────────────────────────────────────────┐
│         Presentation Layer                                   │
│  (Streamlit Dashboard + FastAPI Prediction Server)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
[Continue with layer diagram...]

## Layer Details

### [Layer Name]

**Purpose**: [what this layer does]

**Key Components**:
- ComponentName (location: path/file.py): [brief description]
  - Key methods: method1(), method2()
  - Used by: [list consumers from your usage searches]

**Patterns Used**: [patterns in this layer]

### [Next Layer...]

## Cross-Cutting Concerns

### Error Handling
[how errors flow through the system]

### Configuration
[how config is managed]

### Testing
[testing approach and locations]

## Key Design Decisions

[Only if documented in repo - from Phase 5]
```

### Step 3: Create Entry Memory

Create an atomic memory that summarizes and links to the document:
```
execute_forgetful_tool("create_memory", {
  "title": "[Project] - Architecture Reference",
  "content": "[Layer count]-layer architecture: [list layers].
              Key patterns: [top 4-5 patterns].
              Core components: [top 5 by usage count].
              Full reference in linked document.",
  "context": "Entry point for architecture deep-dives - links to comprehensive document",
  "keywords": ["architecture", "layers", "patterns", "design", "structure"],
  "tags": ["architecture", "reference", "foundation"],
  "importance": 9,
  "project_ids": [<id>],
  "document_ids": [<arch_doc_id>]
})
```

### Size Guidelines

- **Target**: 3000-8000 words
- **If exceeding 8000 words**, consider splitting by:
  - Layer (Data Architecture, ML Architecture, API Architecture)
  - Concern (Core Architecture, Integration Points, Deployment)
- Each split doc gets its own entry memory

---

## Execution Guidelines

### Phase Execution Order

Execute in order: 0 → 1 → 1B → 2 → **2B** → 3 → 4 → 5 → **6** → 6B → 7 → 7B

### Mandatory Phases (CANNOT SKIP)

| Phase | Minimum Output | Gate |
|-------|---------------|------|
| 0: Discovery | Gap analysis report | Report before proceeding |
| 1: Foundation | 5 memories + project notes | All 5 core memories |
| 2: Architecture | Layer memories | 1 per architectural layer |
| **2B: Entities** | **3+ entities** | **Entity count met** |
| 3: Patterns | **3+ pattern memories** | Pattern count met |
| **6: Artifacts** | **3+ code artifacts** | **Artifact count met** |
| 6B: Symbol Index | 1 document + entry memory | Document created |
| 7B: Architecture Doc | 1 document + entry memory | Document created |

### Conditional Phases

| Phase | Skip Condition |
|-------|----------------|
| 1B: Dependencies | Single-file script with no deps |
| 4: Features | <3 distinct features |
| 5: Decisions | NO explicit documentation found |
| 7: Documents | No long-form content needed |

### Execution Rules

1. **Report after each phase** - Use the completion checkpoint format
2. **Meet minimums before proceeding** - DO NOT skip mandatory phases
3. **Prefer symbol-level understanding** - declarations and references over shallow text matches (use LSP if available, else ripgrep)
4. **Track relationships** - grep for usages/callers across files (or LSP references)
5. **Aggregate symbol data** - Collect during Phase 2 for Phase 6B
6. **Deduplicate entities** - Always search before creating
7. **Update outdated memories** as discovered
8. **Link entities to memories** - Enable bidirectional discovery
9. **Create entry memories** - Link documents via document_ids
10. **Mark obsolete** - Memories that reference removed code
11. **Phase 5 is documentation-only** - Never infer decisions from code

## Quality Principles

- **Symbol-aware**: Ground claims in actual declarations/usages (LSP if available, else ripgrep), not guesses
- **Relationship-aware**: Document how things connect
- **One concept per memory** (atomic)
- **200-400 words ideal** per memory
- **Include context field** explaining relevance
- **Honest importance scoring** (most should be 7-8)
- **Quality over quantity**
- **Only document what's explicitly in the repo** (especially for decisions)

---

## Validation

After completion, verify coverage:

### Test Memories
```
execute_forgetful_tool("query_memory", {
  "query": "How do I add a new API endpoint?",
  "query_context": "Testing bootstrap coverage",
  "project_ids": [<project_id>]
})
```

### Test Dependencies
```
execute_forgetful_tool("query_memory", {
  "query": "What dependencies does this project use?",
  "query_context": "Validating dependency encoding",
  "project_ids": [<project_id>]
})
```

### Test Entities (scoped by project)
```
execute_forgetful_tool("list_entities", {
  "project_ids": [<project_id>]
})
```

### Test Entities by Role
```
execute_forgetful_tool("list_entities", {
  "project_ids": [<project_id>],
  "tags": ["library"]
})
```

### Test Relationships
```
execute_forgetful_tool("get_entity_relationships", {
  "entity_id": <component_entity_id>,
  "direction": "outgoing"
})
```

### Test Documents
```
execute_forgetful_tool("list_documents", {
  "project_id": <project_id>
})
```

Should show Symbol Index and Architecture Reference documents.

### Test Document Retrieval
```
execute_forgetful_tool("get_document", {
  "document_id": <symbol_index_doc_id>
})
```

Verify symbol table is structured and contains accurate locations.

### Test Entry Memory Links
```
execute_forgetful_tool("query_memory", {
  "query": "symbol index navigation classes",
  "query_context": "Verifying entry memories link to documents",
  "project_ids": [<project_id>]
})
```

Should return entry memory with `document_ids` populated. The entry memory provides quick context; the linked document provides full detail.

### Test Project Notes
```
execute_forgetful_tool("get_project", {
  "project_id": <project_id>
})
```

Verify `notes` field contains high-level overview (entry point, tech stack, architecture, key patterns).

Test with architecture questions - a well-encoded repo should answer accurately.

---

## Report Progress

After each phase, report using the checkpoint format:
```
Phase [N] Complete:
- Created: [X] memories, [Y] entities, [Z] artifacts
- Minimum required: [targets from table]
- Status: ✅ Met / ❌ Not met
```

**Proceed automatically** to the next phase once the checkpoint is met. Do not wait for user confirmation.

---

## Final Encoding Summary

When encoding is complete, provide a summary in this format:

```
# [Project] Encoding Complete

## Artifacts Created

| Type | Count | Minimum | Status |
|------|-------|---------|--------|
| Memories | [X] | [per profile] | ✅/❌ |
| Entities | [Y] | 3+ | ✅/❌ |
| Relationships | [Z] | - | - |
| Code Artifacts | [W] | 3+ | ✅/❌ |
| Documents | [V] | 2 | ✅/❌ |

## Phase Completion Status

| Phase | Status | Output |
|-------|--------|--------|
| 0: Discovery | ✅ | Gap analysis completed |
| 1: Foundation | ✅ | [X] memories |
| 1B: Dependencies | ✅/SKIP | [reason] |
| 2: Architecture | ✅ | [X] layer memories |
| 2B: Entities | ✅ | [X] entities, [Y] relationships |
| 3: Patterns | ✅ | [X] pattern memories |
| 4: Features | ✅/SKIP | [X] feature memories |
| 5: Decisions | ✅/SKIP | [X] decisions (or: no documentation found) |
| 6: Artifacts | ✅ | [X] code artifacts |
| 6B: Symbol Index | ✅ | Document + entry memory |
| 7B: Architecture | ✅ | Document + entry memory |

## Key Memories for Navigation

1. **Overview**: [title] (ID: X)
2. **Architecture**: [title] (ID: Y)
3. **Symbol Index**: [title] (ID: Z, links to doc)
4. **Architecture Doc**: [title] (ID: W, links to doc)

## Entity Graph Summary

Components: [list]
Frameworks: [list]
Key relationships: [list]

## Validation Queries Tested

- "How do I add a new endpoint?" → [result summary]
- "What patterns are used?" → [result summary]
- "What components exist?" → [entity count returned]
```

This summary confirms the encoding meets minimum requirements and provides quick navigation for future agents.
