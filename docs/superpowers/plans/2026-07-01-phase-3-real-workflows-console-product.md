# Phase 3 Real Workflows & Console Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the platform run real workflows through the console and CLI using one durable executor path, with settings, graph inspection, Docker selection, embedded SPA serving, and console ergonomics.

**Architecture:** Keep `DurableRunExecutor` as the only run launcher for console, CLI, and future automation. Add startup schema initialization, a platform LLM backend factory, credential/settings persistence, and product UI layers around the existing Phase 1/2 contracts instead of introducing a second runner. The first vertical slice is fresh DB -> platform server -> console launch -> real codergen backend -> durable events -> approval -> artifacts -> write-back.

**Tech Stack:** Python 3.12, Starlette/FastAPI-compatible platform app, SQLAlchemy 2 async, SQLite `create_all` startup, Alembic for Postgres, existing `attractor_llm` adapters, existing `AgentLoopBackend`/`DirectLLMBackend`, React/Vite/TypeScript, client-side Graphviz rendering.

---

## Scope Boundary

Phase 3 builds the "Real Workflows & Console Product" layer. It does not implement GitHub PRs, review/repair loops, mid-turn steering, MCP clients, scheduled automations, robust restart-safe queue workers, Slack/tracker integrations, cloud sandboxes, ACP, SSO, or governance.

The hard constraint is one run path: console launches, `attractor run <workflow>` launches, and future automations must all create runs through `DurableRunExecutor`, persist the same durable events, use the same worktree isolation/checkpoint/artifact/write-back path, and show up in the same console history.

No test in the automated suite may require a live provider key. Every automated test that touches the codergen path must use an injected fake or stub `CodergenBackend`. Live Anthropic/OpenAI/Gemini adapter validation is limited to the manual acceptance smoke in Task 10 Step 5, run by an operator with keys in their own environment; it is never part of CI and no live key is committed.

## Key Decisions

- **Credential and secret storage:** store local single-user secrets in a new `platform_secrets` table encrypted with a Fernet key stored in `~/.attractor/platform-secret.key` with `0600` permissions. The GUI is write-only: it can set, replace, delete, and show presence/last-updated metadata, but never return secret values. Reject plaintext DB/env-only storage because console-managed credentials need at-rest protection; reject OS keychain as the first mechanism because the server must run consistently on macOS, Linux, and CI.
- **CLI run path:** `attractor run <workflow>` uses HTTP against a running platform server by default (`ATTRACTOR_PLATFORM_URL` or `--server-url`). Reject in-process shared-DB launch for Phase 3 because it creates a second executor lifecycle, splits active-task/capacity state, and makes approvals/SSE less predictable.
- **Schema management:** SQLite platform startup runs `Base.metadata.create_all` inside the server lifespan before serving requests; Postgres remains Alembic-managed and startup verifies connectivity without mutating schema. Reject always-running `create_all` on Postgres because it bypasses migration review and can hide drift.
- **Graph rendering:** render DOT in the browser with `@hpcc-js/wasm`, then apply highlight classes from durable events. Reject server-side DOT-to-SVG for Phase 3 because it adds server binary/runtime coupling and makes live highlight state harder to reconcile with React.
- **Environment selection:** `requested_environment` is a launch parameter resolved by existing `RunSpec` logic against `workflow.toml` and `project.toml`; the console exposes allowed options from workflow/project config and the CLI passes `--environment`. Reject hard-coding Docker/defaults in the UI because it bypasses the config contracts already shipped in Phase 1/2.

## File Structure

- Modify `src/attractor_platform/storage/db.py`
  Add SQLite schema initialization and Postgres schema verification helpers.
- Modify `src/attractor_server/__main__.py`
  Pass the async engine into the platform app and build the platform LLM backend from env/settings.
- Modify `src/attractor_server/platform_app.py`
  Add lifespan setup with schema initialization first, settings APIs, secret APIs, directory browsing, graph metadata, richer launch inputs, and static SPA serving.
- Modify `src/attractor_platform/executor.py`
  Accept a codergen backend at construction, preserve server human interviewer registration, include requested environment in launch, and keep all run creation inside the durable executor.
- Create `src/attractor_platform/llm_backend.py`
  Shared platform LLM backend factory using env vars first, then secret vault entries.
- Create `src/attractor_platform/secrets.py`
  Fernet key management, encrypted secret CRUD helpers, write-only response models.
- Modify `src/attractor_platform/storage/models.py`
  Add settings and secret metadata tables if settings are not stored as JSON rows.
- Create `src/attractor_cli/platform.py`
  HTTP client for platform-backed `attractor run`.
- Modify `src/attractor_pipeline/cli.py`
  Route repo-local workflow runs through the platform server and retain legacy DOT-file behavior behind `--legacy-local`.
- Modify `web/package.json`
  Add graph-rendering dependency.
- Modify `web/src/api.ts`
  Add typed calls for settings, secrets, directory browsing, graph, launch options, cancel, re-run, and write-back diff.
- Modify `web/src/App.tsx`, `web/src/routes/*`, `web/src/components/*`, `web/src/styles.css`
  Add settings pages, typed launch forms, live run lists, graph view, diff view, folder browser, and complete loading/error/empty states.
- Create focused tests:
  `tests/test_phase3_schema_init.py`, `tests/test_phase3_llm_backend.py`, `tests/test_phase3_real_agent_execution.py`, `tests/test_phase3_secrets.py`, `tests/test_phase3_settings_api.py`, `tests/test_phase3_cli_platform_run.py`, `tests/test_phase3_graph_api.py`, `tests/test_phase3_docker_e2e.py`, `tests/test_phase3_embedded_spa.py`, `tests/test_phase3_console_api_contracts.py`.

---

### Task 1: Fresh SQLite Schema Initialization

**Files:**
- Modify: `src/attractor_platform/storage/db.py`
- Modify: `src/attractor_server/platform_app.py`
- Modify: `src/attractor_server/__main__.py`
- Test: `tests/test_phase3_schema_init.py`

- [ ] **Step 1: Write failing startup-schema tests**

Create tests that build a fresh SQLite engine, assert `registered_repos` does not exist, call the new initializer, then query the table successfully. Add a second test that starts the platform app through its lifespan against a fresh SQLite DB with no manual `Base.metadata.create_all`, then makes a real request:

```python
async def test_initialize_sqlite_schema_creates_platform_tables(tmp_path: Path) -> None:
    engine = create_platform_engine(DatabaseSettings(url=default_test_database_url(tmp_path / "fresh.sqlite3")))
    with pytest.raises(OperationalError, match="registered_repos"):
        async with engine.begin() as conn:
            await conn.execute(text("select count(*) from registered_repos"))

    await initialize_platform_schema(engine)

    async with engine.begin() as conn:
        result = await conn.execute(text("select count(*) from registered_repos"))
    assert result.scalar_one() == 0


def test_platform_app_lifespan_initializes_fresh_sqlite_schema(tmp_path: Path) -> None:
    engine = create_platform_engine(DatabaseSettings(url=default_test_database_url(tmp_path / "app.sqlite3")))
    session_factory = create_session_factory(engine)
    executor = DurableRunExecutor.for_tests(
        session_factory=session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    app = create_platform_app(
        session_factory=session_factory,
        executor=executor,
        engine=engine,
    )

    with TestClient(app) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Run the failing test**

Run: `uv run python -m pytest tests/test_phase3_schema_init.py -v`

Expected: FAIL with `ImportError` for `initialize_platform_schema` and `TypeError` for the missing `engine` argument on `create_platform_app`.

- [ ] **Step 3: Implement SQLite-only initialization**

Add `initialize_platform_schema(engine: AsyncEngine) -> None` in `storage/db.py`. It must inspect `engine.url.get_backend_name()`, run `Base.metadata.create_all` only for SQLite/aiosqlite, and no-op for Postgres with a clear docstring that Alembic remains authoritative.

- [ ] **Step 4: Wire startup before serving**

Change `create_platform_app` to accept `engine: AsyncEngine | None = None` or a startup hook. Register a Starlette/FastAPI lifespan that awaits `initialize_platform_schema(engine)` as the first startup action when an engine is provided. In `src/attractor_server/__main__.py`, remove any `asyncio.run(initialize_platform_schema(...))` startup call and pass the existing async engine into `create_platform_app`. The initializer must run on uvicorn's serving loop before requests are served, not on a throwaway pre-uvicorn event loop.

- [ ] **Step 5: Verify**

Run: `uv run python -m pytest tests/test_phase3_schema_init.py tests/test_phase2_api.py -v`

Expected: PASS. The app-lifespan test must prove a fresh SQLite DB can serve `GET /api/system/health` without any manual `create_all` fixture setup.

### Task 2: Real Codergen Backend Factory

**Files:**
- Create: `src/attractor_platform/llm_backend.py`
- Modify: `src/attractor_platform/executor.py`
- Modify: `src/attractor_server/__main__.py`
- Test: `tests/test_phase3_llm_backend.py`

- [ ] **Step 1: Write backend factory tests**

Cover env-var detection for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY`, default provider/model selection, and no-key dry-run fallback:

```python
def test_backend_factory_returns_none_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert build_platform_codergen_backend(default_provider=None, default_model=None) is None

def test_executor_registers_real_codergen_backend(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    fake_backend: CodergenBackend,
) -> None:
    executor = DurableRunExecutor.for_tests(
        session_factory=session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
        codergen_backend=fake_backend,
    )
    handler = executor._handlers.get("codergen")
    assert isinstance(handler, CodergenHandler)
    assert handler._backend is fake_backend
```

- [ ] **Step 2: Run failing tests**

Run: `uv run python -m pytest tests/test_phase3_llm_backend.py -v`

Expected: FAIL because `llm_backend.py` and `codergen_backend` constructor injection do not exist.

- [ ] **Step 3: Add `build_platform_codergen_backend`**

Create a helper that mirrors the legacy server path: register all available adapters on `Client`, choose provider/model from args or first available env key, and return `AgentLoopBackend(client, default_provider=provider, default_model=model)`. Return `None` when no credentials are configured so dry-run mode remains explicit.

- [ ] **Step 4: Thread backend into the executor**

Add `codergen_backend: CodergenBackend | None = None` to `DurableRunExecutor.__init__` and `for_tests`, and call `register_default_handlers(self._handlers, codergen_backend=codergen_backend)`. Keep the subsequent `wait.human` override intact.

- [ ] **Step 5: Wire platform startup**

In `__main__.py`, call `build_platform_codergen_backend(default_provider=args.provider, default_model=args.model)` for `--platform` and pass the result to `DurableRunExecutor`.

- [ ] **Step 6: Verify**

Run: `uv run python -m pytest tests/test_phase3_llm_backend.py tests/test_phase2_executor.py -v`

Expected: PASS, with existing Phase 2 executor tests still passing in dry-run mode.

### Task 3: Real-Agent Console Vertical Slice

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `src/attractor_platform/executor.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/WorkflowDetailRoute.tsx`
- Test: `tests/test_phase3_console_api_contracts.py`
- Test: `tests/test_phase3_real_agent_execution.py`

- [ ] **Step 1: Write API contract tests**

Test `POST /api/runs` accepts `repo_path`, `workflow_name`, `actor_label`, `inputs`, and `requested_environment`, then asserts the created `RunRecord.run_spec` preserves those values and the durable event stream includes `run.queued`.

Also add an automated key-free real-agent regression test:

```python
class RecordingCodergenBackend(CodergenBackend):
    def __init__(self) -> None:
        self.invocations: list[str] = []

    async def run(
        self,
        node: Node,
        prompt: str,
        context: dict[str, Any],
        abort_signal: AbortSignal | None = None,
    ) -> str:
        del prompt, context, abort_signal
        self.invocations.append(node.id)
        cwd = Path(await get_environment().working_directory())
        (cwd / "agent-output.txt").write_text("written by fake codergen\n", encoding="utf-8")
        return "fake codergen completed"


def _init_repo_with_workflow(tmp_path: Path, workflow_name: str, workflow_dot: str) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)
    workflow_dir = repo_path / ".attractor" / "workflows" / workflow_name
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(workflow_dot, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


def _git_show(repo_path: Path, ref_name: str, file_path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref_name}:{file_path}"],
        cwd=repo_path,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


async def test_fake_codergen_executes_through_durable_executor_and_changes_branch(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repo = _init_repo_with_workflow(
        tmp_path,
        "real-agent",
        workflow_dot="""
        digraph RealAgent {
            graph [goal="Exercise codergen"]
            start [shape=Mdiamond]
            generate [shape=box, prompt="write a file"]
            done [shape=Msquare]
            start -> generate
            generate -> done
        }
        """,
    )
    backend = RecordingCodergenBackend()
    executor = DurableRunExecutor.for_tests(
        session_factory=session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
        codergen_backend=backend,
    )

    run_id = await executor.register_and_launch(
        repo_path=repo,
        workflow_name="real-agent",
        actor_label="test",
        inputs={},
    )
    result = await executor.wait(run_id)

    events = await executor.repository.list_events(run_id, after_sequence=0, limit=100)
    run = await executor.repository.get_run(run_id)
    assert result.status == PipelineStatus.COMPLETED
    assert backend.invocations == ["generate"]
    assert any("fake codergen completed" in str(event.payload) for event in events)
    assert run is not None and run.managed_branch
    assert _git_show(repo, run.managed_branch, "agent-output.txt") == "written by fake codergen\n"
```

- [ ] **Step 2: Run failing contract tests**

Run: `uv run python -m pytest tests/test_phase3_console_api_contracts.py tests/test_phase3_real_agent_execution.py -v`

Expected: `tests/test_phase3_console_api_contracts.py` FAILS on missing `requested_environment` propagation and typed launch metadata. `tests/test_phase3_real_agent_execution.py` should PASS after Task 2; if it fails, treat that as a blocker in the backend injection from Task 2 before continuing.

- [ ] **Step 3: Preserve launch environment and typed inputs**

Add `requested_environment: str = ""` to `DurableRunExecutor.register_and_launch` and pass it into `build_run_spec`. Keep `inputs` JSON-object validation strict: keys are strings; values are strings for Phase 3 because `RunSpec.inputs` is currently `dict[str, str]`.

- [ ] **Step 4: Update console launch UI**

Render inputs from `workflow.toml [inputs]`, expose an environment select from project/workflow config, disable launch while submitting, and display validation diagnostics before the launch button.

- [ ] **Step 5: Verify**

Run: `uv run python -m pytest tests/test_phase3_console_api_contracts.py tests/test_phase2_e2e.py -v`

Run: `uv run python -m pytest tests/test_phase3_real_agent_execution.py -v`

Expected: PASS. The real-agent regression must run without live provider keys and must prove the fake codergen backend is invoked through `DurableRunExecutor`, writes into the run worktree, emits durable output evidence, and leaves a file change on the managed branch.

### Task 4: Settings Pages and Write-Only Secret Vault

**Files:**
- Create: `src/attractor_platform/secrets.py`
- Modify: `src/attractor_platform/storage/models.py`
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/src/api.ts`
- Create/modify: `web/src/routes/Settings*.tsx`
- Test: `tests/test_phase3_secrets.py`
- Test: `tests/test_phase3_settings_api.py`

- [ ] **Step 1: Write secret API tests**

Assert `PUT /api/settings/secrets/openai` stores a secret, `GET /api/settings/secrets` returns only `{name, configured, updated_at}`, and no API response includes the raw value.

- [ ] **Step 2: Add encrypted vault**

Implement Fernet key creation with `0600` permissions, encrypted secret persistence, and delete/replace semantics. Add `cryptography>=42` to `pyproject.toml`.

- [ ] **Step 3: Add settings routes**

Add routes for Models, Environments, Variables, Server, Storage, and Monitoring. Models must show provider credential status and default provider/model. Variables can be readable non-secret key/value rows; secrets remain write-only.

- [ ] **Step 4: Add settings UI**

Create tabs for Models, Environments, Variables, Server, Storage, and Monitoring. Use password inputs for secret writes, show configured/unconfigured status, and never display saved values.

- [ ] **Step 5: Verify**

Run: `uv run python -m pytest tests/test_phase3_secrets.py tests/test_phase3_settings_api.py -v`

Expected: PASS.

### Task 5: Platform CLI Run Path

**Files:**
- Create: `src/attractor_cli/platform.py`
- Modify: `src/attractor_pipeline/cli.py`
- Test: `tests/test_phase3_cli_platform_run.py`

- [ ] **Step 1: Write CLI tests**

Use `respx` to assert `attractor run release-checks --repo /repo --server-url http://platform` sends one `POST /api/runs` request and prints the returned durable run id. Add a second test that `--legacy-local path/to/workflow.dot` still uses the old local runner.

- [ ] **Step 2: Choose CLI syntax**

Support:

```bash
attractor run release-checks --repo /path/to/repo --server-url http://127.0.0.1:8080 --input target=wheel --environment docker-ci
```

Reject launching the durable executor inside the CLI process in this phase.

- [ ] **Step 3: Implement HTTP client**

`src/attractor_cli/platform.py` should build the request body, call the server with `httpx`, print run URL/status, and return non-zero on 4xx/5xx with the server error text.

- [ ] **Step 4: Verify**

Run: `uv run python -m pytest tests/test_phase3_cli_platform_run.py -v`

Expected: PASS.

### Task 6: DOT Graph Viewer With Live Highlighting

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/package.json`
- Modify: `web/src/api.ts`
- Create: `web/src/components/GraphViewer.tsx`
- Modify: `web/src/routes/RunDetailRoute.tsx`
- Test: `tests/test_phase3_graph_api.py`

- [ ] **Step 1: Write graph API tests**

Test `GET /api/workflows/{workflow_id}/graph` returns raw DOT plus parsed node ids and edge ids. Test a run detail can map durable events with payload `node_id` to graph highlight state.

- [ ] **Step 2: Add Graphviz dependency**

Run: `npm install @hpcc-js/wasm` from `web/` and commit `package.json` and `package-lock.json`.

- [ ] **Step 3: Add graph API and UI**

Return graph metadata from the server. In React, render DOT to SVG, then apply classes: `active` for latest `stage.started`, `complete` for `stage.completed`, `failed` for `stage.failed`, and `checkpointed` for `checkpoint.saved`. Edge highlighting follows the most recent completed node to next active node when both are known.

- [ ] **Step 4: Verify**

Run: `uv run python -m pytest tests/test_phase3_graph_api.py -v`

Run: `cd web && npm run build`

Expected: PASS and successful production build.

### Task 7: Docker Selection End-to-End

**Files:**
- Modify: `src/attractor_platform/run_environment.py`
- Modify: `src/attractor_platform/executor.py`
- Modify: `web/src/routes/WorkflowDetailRoute.tsx`
- Test: `tests/test_phase3_docker_e2e.py`

- [ ] **Step 1: Write Docker E2E test**

Create a workflow whose tool step writes a file in the workspace, launch with `requested_environment="docker"`, and assert the durable run completes, events persist, artifacts/checkpoints are present, and the host registered repo is not directly mutated before write-back.

- [ ] **Step 2: Fix Docker workspace semantics**

Ensure Docker runs receive the prepared worktree contents and that allowed roots map to the container workspace. Persist effective environment details into `RunSpec`.

- [ ] **Step 3: Expose Docker in launch UI**

Show Docker options only when `allowed_execution_modes` includes `docker`, and surface unavailable Docker errors as launch/run diagnostics.

- [ ] **Step 4: Verify**

Run: `uv run python -m pytest tests/test_phase3_docker_e2e.py -v`

Expected: PASS when Docker is available; SKIP with a clear reason when Docker is unavailable.

### Task 8: Embedded SPA Serving

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `src/attractor_server/__main__.py`
- Test: `tests/test_phase3_embedded_spa.py`

- [ ] **Step 1: Write embedded SPA tests**

Create a temporary `web/dist/index.html`, pass its path through a new `spa_dist` argument on `create_platform_app`, and assert `GET /` returns the file while `GET /api/system/health` still returns JSON.

- [ ] **Step 2: Add static mount**

Mount built assets after API routes. For non-API unknown paths, return `index.html` so client-side routing works.

- [ ] **Step 3: Add CLI flag**

Add `--spa-dist` and default to the installed package's bundled `web/dist` when present.

- [ ] **Step 4: Verify**

Run: `uv run python -m pytest tests/test_phase3_embedded_spa.py -v`

Run: `cd web && npm run build`

Expected: PASS and build succeeds.

### Task 9: Folder Browser and Console Ergonomics

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/ReposRoute.tsx`
- Modify: `web/src/routes/RunsRoute.tsx`
- Modify: `web/src/routes/RunDetailRoute.tsx`
- Modify: `web/src/components/*`
- Test: `tests/test_phase3_console_api_contracts.py`

- [ ] **Step 1: Write API tests**

Test `GET /api/fs/browse?path=/repo` lists directories and git repos but rejects traversal and hidden system paths outside the server user's accessible filesystem policy.

- [ ] **Step 2: Add directory-listing endpoint**

Return entries `{name, path, kind, is_git_repo}` sorted directories first. Do not return file contents.

- [ ] **Step 3: Add console ergonomics**

Add live-updating run list with filters, cancel and re-run buttons, typed launch form, branch diff viewer, validation diagnostics, and explicit empty/error/loading states for each route.

- [ ] **Step 4: Verify**

Run: `uv run python -m pytest tests/test_phase3_console_api_contracts.py -v`

Run: `cd web && npm run build`

Expected: PASS and build succeeds.

### Task 10: Full Verification Gate

**Files:**
- Modify only files needed to address failures found by the commands below.

- [ ] **Step 1: Python test suite**

Run: `uv run python -m pytest tests/`

Expected: PASS on the default SQLite path with no live provider keys set. No automated test may require `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`; codergen-path tests must use injected fake/stub `CodergenBackend` instances.

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`

Expected: PASS with no lint errors.

- [ ] **Step 3: Type check**

Run: `uv run pyright`

Expected: 0 errors.

- [ ] **Step 4: Web build**

Run: `cd web && npm run build`

Expected: PASS.

- [ ] **Step 5: Manual real-agent smoke**

With a provider key set in the operator's local environment, run:

```bash
uv run python -m attractor_server --platform --port 8080
attractor run release-checks --repo /path/to/repo --server-url http://127.0.0.1:8080
```

Expected: the console can register the repo, launch the same workflow, stream live events, handle a gate, show artifacts/checkpoints, write back the managed branch, and display the CLI-created durable run in the same run list. This is the only live-provider validation step; it is manual acceptance coverage, not CI coverage, and no real key is committed or required for `pytest tests/`.

## Review Gate

This plan is final after the corrective edits above. Implementation should start with Task 1, then Task 2, then Task 3 before any settings or UI expansion, because fresh DB startup, real codergen backend wiring, and the automated key-free real-agent regression are the drivability blockers.
