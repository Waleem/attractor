# Console Product v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing minimal React operations console into a polished, live-updating product surface with deep operator settings, richer run views, and a verified current model catalog.

**Architecture:** Extend the current Starlette platform app, durable storage repository, SSE stream, and Vite React app. Preserve `DurableRunExecutor` as the one run path; this work adds catalog/settings API surface and console presentation without changing execution semantics.

**Tech Stack:** Python 3.12, Starlette, SQLAlchemy async, existing Attractor platform contracts, existing `attractor_llm` client/adapters, React 19, Vite, TypeScript, `@hpcc-js/wasm` Graphviz.

---

## Baseline and Branch

- Verified `git fetch origin` succeeded.
- Verified `main` was even with `origin/main` before branching.
- Created and switched to `codex/console-product-v2`.
- Existing untracked `.attractor-worktrees/` is unrelated and must remain untouched.
- Existing console files are in `web/src/` and must be extended, not rewritten.

## Provider Model Verification

Current model IDs were checked against official provider documentation before writing this plan:

- Anthropic Claude Platform docs list current Claude API IDs and aliases: `claude-fable-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5-20251001` with alias `claude-haiku-4-5`. Source: https://platform.claude.com/docs/en/about-claude/models/overview
- OpenAI API docs list GPT-5.5 as the flagship model and smaller variants including `gpt-5.4-mini` and `gpt-5.4-nano`. Source: https://developers.openai.com/api/docs/models
- Google Gemini API docs list `gemini-3.5-flash`, with 1,048,576 input tokens and 65,536 output tokens. Source: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash

## Key Decisions

- **Graph rendering:** keep `web/src/components/GraphViewer.tsx` and `@hpcc-js/wasm`; move graph colors and sizing to CSS variables, extend `web/src/graphHighlight.ts` to produce lifecycle-aware classes (`queued`, `running`, `waiting`, `completed`, `failed`, `checkpointed`), and keep DOM class application in `web/src/graphViewerController.ts`.
- **Live SSE wiring:** introduce a shared run-stream hook in `web/src/hooks/useRunEvents.ts`; run detail continues to use `/api/runs/{id}/events/stream`, and run list opens streams only for visible active runs. No new polling; remove the manual Refresh button from `web/src/routes/RunsRoute.tsx`.
- **Catalog testing:** add a backend `POST /api/settings/models/test` endpoint. It builds provider clients from configured env/vault keys, sends a minimal text request per catalog entry, and returns per-model status. Automated tests inject a fake model tester; no test uses live provider keys.
- **Theming:** define semantic design tokens in `web/src/styles.css` under `:root` and `@media (prefers-color-scheme: dark)`. Components consume CSS classes and custom properties rather than inline colors. Status is always conveyed with icon/text plus color.
- **Settings taxonomy:** backend settings rows carry one of `editable`, `restart-required`, `read-only`, or `reserved`; the UI renders that tag beside every value.
- **Execution boundary:** no changes to `DurableRunExecutor` run semantics. API additions may read run state, diff contents, settings, and catalog models, but launching/canceling/approving/write-back continue through existing endpoints.

## File Structure

- Modify `src/attractor_llm/catalog.py`
  Update catalog entries, defaults, aliases, context/output sizes, costs where known, and stale count assumptions.
- Modify `src/attractor_agent/profiles/anthropic.py`, `src/attractor_agent/profiles/openai.py`, `src/attractor_agent/profiles/gemini.py`
  Align profile defaults with catalog defaults so settings and codergen fallback agree.
- Modify `src/attractor_pipeline/backends.py`
  Replace stale constructor defaults with catalog-backed provider defaults.
- Modify `src/attractor_server/__main__.py`
  Replace legacy hardcoded fallback models in the non-platform server path.
- Modify `src/attractor_server/platform_app.py`
  Add catalog/settings model endpoints, deep settings overview fields, diff content, artifact download/view response, server/runtime metadata, and model-test dependency injection.
- Modify `src/attractor_platform/storage/repositories.py`
  Add any small read helpers needed by settings and diff-content endpoints; do not alter executor writes.
- Modify `web/src/api.ts`
  Add typed settings model catalog, model-test, deep settings, diff hunks, artifact link, and run stream helpers.
- Modify `web/src/components/ui.tsx`
  Add shared primitives: `StatusPill`, `StatusDot`, `IconStatus`, `CopyButton`, `TruncatedValue`, `SettingsRow`, `SectionCard`, `SegmentedControl`, `RelativeTime`, and `DiffViewer`.
- Create `web/src/hooks/useRunEvents.ts`
  Shared SSE hook for durable run events.
- Modify `web/src/components/GraphViewer.tsx`, `web/src/graphHighlight.ts`, `web/src/graphViewerController.ts`, `web/src/graphHighlight.test.ts`
  Tokenize graph styling and support lifecycle colors.
- Modify `web/src/routes/RunsRoute.tsx`
  Replace polling table with List/Board views, live indicator, search, chips, empty state, row/card actions, and Launch primary action.
- Modify `web/src/routes/RunDetailRoute.tsx`
  Replace raw-id title and raw JSON timeline with product header, contextual actions, diff content, readable event timeline, artifact links, and copy/truncation controls.
- Modify `web/src/routes/SettingsRoute.tsx`
  Replace tabs with grouped left sub-nav and one page template across Models, Integrations, Sandboxes, Environments, Variables, Secrets, Run defaults, Server, Security, Storage, Monitoring, and Live events.
- Modify `web/src/styles.css`
  Add design tokens, light/dark themes, focus rings, responsive layout, status classes, run list/board/detail/settings styles.
- Create focused tests:
  `tests/test_console_product_v2_catalog.py`, `tests/test_console_product_v2_model_testing.py`, `tests/test_console_product_v2_settings_api.py`, `tests/test_console_product_v2_run_diff.py`, plus web TypeScript tests under `web/src/`.

---

### Task 1: Catalog and Defaults Fix

**Files:**
- Modify: `src/attractor_llm/catalog.py`
- Modify: `src/attractor_agent/profiles/anthropic.py`
- Modify: `src/attractor_agent/profiles/openai.py`
- Modify: `src/attractor_agent/profiles/gemini.py`
- Modify: `src/attractor_pipeline/backends.py`
- Modify: `src/attractor_server/__main__.py`
- Test: `tests/test_console_product_v2_catalog.py`
- Test: existing `tests/test_llm_catalog_streaming.py`, `tests/test_wave11_catalog_enrichment.py`, `tests/test_profiles.py`

- [ ] **Step 1: Write failing catalog tests**

Create `tests/test_console_product_v2_catalog.py`:

```python
from __future__ import annotations

from attractor_agent.profiles import get_profile
from attractor_llm.catalog import get_default_model, get_latest_model, get_model_info, list_models
from attractor_pipeline.backends import AgentLoopBackend, DirectLLMBackend
from attractor_llm.client import Client


def test_catalog_contains_verified_current_model_ids() -> None:
    expected = {
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.4-codex",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite",
    }
    ids = {model.id for model in list_models()}
    assert expected <= ids


def test_catalog_removed_stale_defaults() -> None:
    ids = {model.id for model in list_models()}
    assert "claude-sonnet-4-5" not in ids
    assert "gpt-4.1-mini" not in ids
    assert "gemini-3-flash-preview" not in ids


def test_default_models_resolve_to_verified_ids() -> None:
    assert get_default_model("anthropic").id == "claude-sonnet-5"
    assert get_default_model("openai").id == "gpt-5.5"
    assert get_default_model("gemini").id == "gemini-3.5-flash"


def test_provider_profiles_match_catalog_defaults() -> None:
    for provider in ("anthropic", "openai", "gemini"):
        assert get_profile(provider).default_model == get_default_model(provider).id


def test_aliases_keep_operator_shortcuts_current() -> None:
    assert get_model_info("sonnet").id == "claude-sonnet-5"
    assert get_model_info("haiku").id == "claude-haiku-4-5-20251001"
    assert get_model_info("flash").id == "gemini-3.5-flash"
    assert get_latest_model("openai").id == "gpt-5.5"


def test_backend_constructor_defaults_are_catalog_current() -> None:
    client = Client()
    assert AgentLoopBackend(client)._default_model == "claude-sonnet-5"
    assert DirectLLMBackend(client)._default_model == "claude-sonnet-5"
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_catalog.py tests/test_llm_catalog_streaming.py tests/test_wave11_catalog_enrichment.py tests/test_profiles.py -v
```

Expected: FAIL on current missing IDs and stale default assertions.

- [ ] **Step 3: Update `MODEL_CATALOG`**

In `src/attractor_llm/catalog.py`, replace stale entries with the verified set. Preserve `ModelInfo` shape and catalog order as ranking:

```python
MODEL_CATALOG: list[ModelInfo] = [
    ModelInfo(
        id="claude-fable-5",
        provider="anthropic",
        display_name="Claude Fable 5",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=10.0,
        output_cost_per_million=50.0,
        aliases=("fable", "claude-fable", "fable-5"),
        knowledge_cutoff="2026-01",
    ),
    ModelInfo(
        id="claude-opus-4-8",
        provider="anthropic",
        display_name="Claude Opus 4.8",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=5.0,
        output_cost_per_million=25.0,
        aliases=("opus", "claude-opus", "opus-4-8"),
        knowledge_cutoff="2026-01",
    ),
    ModelInfo(
        id="claude-sonnet-5",
        provider="anthropic",
        display_name="Claude Sonnet 5",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=3.0,
        output_cost_per_million=15.0,
        aliases=("sonnet", "claude-sonnet", "sonnet-5"),
        knowledge_cutoff="2026-01",
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        provider="anthropic",
        display_name="Claude Haiku 4.5",
        context_window=200_000,
        max_output=64_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=1.0,
        output_cost_per_million=5.0,
        aliases=("haiku", "claude-haiku", "claude-haiku-4-5", "haiku-4-5"),
        knowledge_cutoff="2025-02",
    ),
    ModelInfo(
        id="gpt-5.5",
        provider="openai",
        display_name="GPT-5.5",
        context_window=1_047_576,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gpt-5", "5.5"),
    ),
    ModelInfo(
        id="gpt-5.4",
        provider="openai",
        display_name="GPT-5.4",
        context_window=1_047_576,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("5.4",),
    ),
    ModelInfo(
        id="gpt-5.4-mini",
        provider="openai",
        display_name="GPT-5.4 Mini",
        context_window=1_047_576,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gpt-mini", "5.4-mini"),
    ),
    ModelInfo(
        id="gpt-5.4-nano",
        provider="openai",
        display_name="GPT-5.4 Nano",
        context_window=1_047_576,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gpt-nano", "5.4-nano"),
    ),
    ModelInfo(
        id="gpt-5.4-codex",
        provider="openai",
        display_name="GPT-5.4 Codex",
        context_window=1_047_576,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gpt-codex", "5.4-codex"),
    ),
    ModelInfo(
        id="gemini-3.5-flash",
        provider="gemini",
        display_name="Gemini 3.5 Flash",
        context_window=1_048_576,
        max_output=65_536,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gemini-flash", "3.5-flash", "flash"),
        knowledge_cutoff="2025-01",
    ),
    ModelInfo(
        id="gemini-3.1-pro-preview",
        provider="gemini",
        display_name="Gemini 3.1 Pro Preview",
        context_window=1_048_576,
        max_output=65_536,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gemini-pro", "3.1-pro"),
    ),
    ModelInfo(
        id="gemini-3.1-flash-lite",
        provider="gemini",
        display_name="Gemini 3.1 Flash-Lite",
        context_window=1_048_576,
        max_output=65_536,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("flash-lite", "3.1-flash-lite"),
    ),
]
```

Set:

```python
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5.5",
    "gemini": "gemini-3.5-flash",
}
```

- [ ] **Step 4: Align profile and backend defaults**

Change:

```python
return "claude-sonnet-4-5"
return "gpt-5.2"
return "gemini-3-flash-preview"
```

to:

```python
return "claude-sonnet-5"
return "gpt-5.5"
return "gemini-3.5-flash"
```

in the provider profile files. Replace constructor defaults in `src/attractor_pipeline/backends.py` with `"claude-sonnet-5"`.

- [ ] **Step 5: Fix hardcoded server defaults**

In `src/attractor_server/__main__.py`, replace non-platform fallbacks:

```python
model = model or "claude-sonnet-5"
model = model or "gpt-5.5"
default_model=model or "claude-sonnet-5"
```

Also register Gemini in the legacy non-platform path when `GOOGLE_API_KEY` exists, using `gemini-3.5-flash` as its fallback.

- [ ] **Step 6: Verify**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_catalog.py tests/test_llm_catalog_streaming.py tests/test_wave11_catalog_enrichment.py tests/test_profiles.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/attractor_llm/catalog.py src/attractor_agent/profiles src/attractor_pipeline/backends.py src/attractor_server/__main__.py tests/test_console_product_v2_catalog.py tests/test_llm_catalog_streaming.py tests/test_wave11_catalog_enrichment.py tests/test_profiles.py
git commit -m "fix: refresh model catalog defaults"
```

### Task 2: Test Models Backend Endpoint

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/src/api.ts`
- Test: `tests/test_console_product_v2_model_testing.py`

- [ ] **Step 1: Write fake-client endpoint tests**

Create `tests/test_console_product_v2_model_testing.py` with a fake tester object:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from attractor_llm.catalog import ModelInfo
from attractor_server.platform_app import create_platform_app

pytestmark = pytest.mark.asyncio


@dataclass
class FakeModelTester:
    failures: set[str]
    seen: list[str]

    async def test_model(self, model: ModelInfo, provider_api_keys: dict[str, str]) -> dict[str, Any]:
        self.seen.append(model.id)
        if model.id in self.failures:
            return {"ok": False, "latency_ms": 12, "error": "fake failure"}
        return {"ok": model.provider in provider_api_keys, "latency_ms": 8, "error": None}


async def test_test_models_endpoint_uses_fake_tester_without_live_keys(platform_app_factory: Any) -> None:
    fake_tester = FakeModelTester(failures={"gpt-5.4-nano"}, seen=[])
    app = platform_app_factory(model_tester=fake_tester, provider_api_keys={"openai": "fake-key"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post("/api/settings/models/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["ok"] >= 1
    assert payload["summary"]["failed"] >= 1
    by_model = {row["model"]: row for row in payload["items"]}
    assert by_model["gpt-5.4-nano"]["ok"] is False
    assert "fake-key" not in str(payload)
    assert "gpt-5.5" in fake_tester.seen
```

If `platform_app_factory` does not exist, implement the test using the helper shape already used in `tests/test_phase3_settings_api.py`: fresh SQLite engine, `initialize_platform_schema`, `DurableRunExecutor.for_tests`, `create_platform_app`.

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_model_testing.py -v
```

Expected: FAIL because `model_tester` injection and `/api/settings/models/test` do not exist.

- [ ] **Step 3: Add tester boundary**

In `platform_app.py`, define:

```python
class PlatformModelTester:
    async def test_model(
        self,
        model: ModelInfo,
        provider_api_keys: dict[str, str],
    ) -> dict[str, Any]:
        api_key = provider_api_keys.get(model.provider)
        if not api_key:
            return {"ok": False, "latency_ms": None, "error": "provider key not configured"}
        client = Client()
        client.register_adapter(model.provider, _adapter_for_provider(model.provider, api_key))
        started = time.perf_counter()
        await client.complete(
            Request.simple(
                model=model.id,
                prompt="Reply with ok.",
                provider=model.provider,
                max_tokens=8,
            )
        )
        return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000), "error": None}
```

Use existing adapter imports from `attractor_platform.llm_backend` patterns. Keep this class small and injectable through `create_platform_app(..., model_tester: PlatformModelTester | None = None)`.

- [ ] **Step 4: Add endpoint**

Add `POST /api/settings/models/test` that:

- loads env/vault provider keys with `_provider_api_keys_from_vault(services)`;
- iterates `list_models()`;
- returns rows with `provider`, `model`, `display_name`, `ok`, `latency_ms`, `error`;
- returns summary `{ok, failed, skipped, tested_at}`.

Never include raw key values in responses or errors.

- [ ] **Step 5: Add frontend API types**

In `web/src/api.ts`, add:

```ts
export interface ModelCatalogRow {
  provider: string;
  model: string;
  display_name: string;
  context_window: number;
  max_output: number | null;
  supports_tools: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  is_default: boolean;
  is_small: boolean;
}

export interface ModelTestResult {
  provider: string;
  model: string;
  display_name: string;
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface ModelTestResponse {
  summary: { ok: number; failed: number; skipped: number; tested_at: string };
  items: ModelTestResult[];
}
```

Add `getModelCatalog()` for `GET /api/settings/models/catalog` and `testModels()` for `POST /api/settings/models/test`.

- [ ] **Step 6: Verify**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_model_testing.py tests/test_phase3_settings_api.py -v
```

Expected: PASS with no live provider keys.

- [ ] **Step 7: Commit**

```bash
git add src/attractor_server/platform_app.py web/src/api.ts tests/test_console_product_v2_model_testing.py
git commit -m "feat: add key-free model catalog validation endpoint"
```

### Task 3: Design Tokens Foundation

**Files:**
- Modify: `web/src/styles.css`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/components/GraphViewer.tsx`
- Test: `web/src/appBase.test.ts` if helper exports are reused
- Acceptance: `cd web && npm run build`

- [ ] **Step 1: Define tokens**

In `web/src/styles.css`, replace raw repeated colors with tokens:

```css
:root {
  color-scheme: light dark;
  --font-sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --text-page: #17202a;
  --text-secondary: #526173;
  --text-muted: #687789;
  --bg-page: #f5f7fa;
  --bg-card: #ffffff;
  --bg-card-muted: #f8fafc;
  --border-subtle: color-mix(in srgb, #98a6b5 50%, transparent);
  --focus-ring: #2563eb;
  --status-queued: #6b7280;
  --status-running: #2563eb;
  --status-waiting: #b45309;
  --status-completed: #15803d;
  --status-failed: #b91c1c;
  --space-0-5: 4px;
  --space-1: 8px;
  --space-1-5: 12px;
  --space-2: 16px;
  --space-3: 24px;
  --space-4: 32px;
  --radius-card: 12px;
  --border-card: 0.5px solid var(--border-subtle);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
}

@media (prefers-color-scheme: dark) {
  :root {
    --text-page: #eef2f7;
    --text-secondary: #b8c2cf;
    --text-muted: #8fa0b3;
    --bg-page: #101418;
    --bg-card: #171d23;
    --bg-card-muted: #1f2730;
    --border-subtle: color-mix(in srgb, #7f8fa3 45%, transparent);
  }
}
```

Keep type sizes to 12, 13, 14, 15, 18, 22px and weights `400`/`500`.

- [ ] **Step 2: Add accessible primitives**

In `web/src/components/ui.tsx`, add:

```tsx
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  return (
    <button
      type="button"
      className="icon-button secondary"
      title={label}
      aria-label={label}
      onClick={() => void navigator.clipboard.writeText(value)}
    >
      ⧉
    </button>
  );
}

export function TruncatedValue({ value }: { value: string }) {
  return <span className="truncate mono" title={value}>{value}</span>;
}
```

Use text/icon glyphs that are keyboard-focusable and labeled. Add `StatusDot` and update `StatusBadge` so status is not color-only.

- [ ] **Step 3: Remove inline graph colors**

Move `GRAPH_SVG_STYLE`, `graphCanvasStyle`, `legendStyle`, and swatch colors from `GraphViewer.tsx` into CSS classes that consume status tokens.

- [ ] **Step 4: Acceptance check**

Run:

```bash
cd web && npm run build
```

Expected: PASS, with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/styles.css web/src/components/ui.tsx web/src/components/GraphViewer.tsx
git commit -m "feat: add console design token foundation"
```

### Task 4: Models Settings Page Hero

**Files:**
- Modify: `web/src/routes/SettingsRoute.tsx`
- Modify: `web/src/api.ts`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/styles.css`
- Acceptance: models page shows providers, configured status, catalog table, search, badges, and test results without exposing secrets.

- [ ] **Step 1: Extend settings API response in TypeScript**

Add `models.catalog` to `SettingsOverview` or fetch it through `getModelCatalog()`. The UI must render columns: provider, model mono, badges `default` and `small`, context, speed, configured status, and Test.

- [ ] **Step 2: Replace `ModelsSettings` implementation**

In `SettingsRoute.tsx`, implement:

- provider cards with configured green status only when env/vault key exists;
- masked secret inputs with `type="password"`;
- search input filtering `provider`, `model`, and `display_name`;
- `Test models` button calling `testModels()`;
- summary text like `7 ok · 2 failed`;
- per-row pass/fail icon plus text.

- [ ] **Step 3: Acceptance check**

Run:

```bash
cd web && npm run build
```

Manual visual acceptance:

- `/settings` defaults to Models.
- A provider without keys reads `Not configured`.
- A provider with a saved vault key reads `Configured`.
- Secret input is masked.
- Test results never display raw key material.

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/SettingsRoute.tsx web/src/api.ts web/src/components/ui.tsx web/src/styles.css
git commit -m "feat: build models settings hero"
```

### Task 5: Run List and Board Views with Durable SSE

**Files:**
- Create: `web/src/hooks/useRunEvents.ts`
- Modify: `web/src/routes/RunsRoute.tsx`
- Modify: `web/src/api.ts`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/styles.css`
- Test: add `web/src/runViewModel.test.ts` and `web/src/runViewModel.ts`
- Acceptance: no interval polling, no Refresh button, List/Board toggle, live indicator, search, filter chips, Launch CTA, and waiting lane approve action.

- [ ] **Step 1: Extract run presentation helpers**

Create `web/src/runViewModel.ts`:

```ts
import type { RunRecord } from "./api";

export type RunLane = "queued" | "running" | "awaiting_you" | "done";

export function shortRunId(id: string): string {
  return id.length > 10 ? id.slice(0, 10) : id;
}

export function runWorkflowName(run: RunRecord): string {
  return run.run_spec?.workflow_name ?? run.run_spec?.workflow ?? run.workflow_id;
}

export function runMetaLine(run: RunRecord): string {
  if (run.error_message) return run.error_message;
  if (run.status === "waiting_for_approval") return "waiting for approval";
  if (run.status === "writeback_pending") return "ready to promote branch";
  return run.managed_branch ? `writing ${run.managed_branch}` : "durable run";
}

export function runLane(run: RunRecord): RunLane | "failed" {
  if (run.status === "queued" || run.status === "preparing") return "queued";
  if (run.status === "running") return "running";
  if (run.status === "waiting_for_approval") return "awaiting_you";
  if (run.status === "failed" || run.status === "writeback_failed") return "failed";
  return "done";
}
```

Add `web/src/runViewModel.test.ts` covering workflow-name primary label, lane mapping, and short id.

- [ ] **Step 2: Add shared SSE hook**

Create `web/src/hooks/useRunEvents.ts`:

```ts
import { useEffect, useState } from "react";
import { knownRunEventTypes, openRunEventSource, type RunEvent } from "../api";

export function useRunEvents(runId: string, enabled: boolean) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    setEvents([]);
    const source = openRunEventSource(runId);
    const handlers: Array<[string, EventListener]> = [];
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    for (const eventType of knownRunEventTypes) {
      const handler = ((message: MessageEvent<string>) => {
        const sequence = Number(message.lastEventId);
        if (!Number.isFinite(sequence)) return;
        let payload: Record<string, unknown> = {};
        try {
          const parsed = JSON.parse(message.data) as unknown;
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            payload = parsed as Record<string, unknown>;
          }
        } catch {
          payload = { message: message.data };
        }
        setEvents((current) =>
          [...current, { sequence, event_type: eventType, payload, actor_label: "", created_at: new Date().toISOString() }]
            .sort((a, b) => a.sequence - b.sequence)
        );
      }) as EventListener;
      source.addEventListener(eventType, handler);
      handlers.push([eventType, handler]);
    }
    return () => {
      for (const [eventType, handler] of handlers) source.removeEventListener(eventType, handler);
      source.close();
      setConnected(false);
    };
  }, [runId, enabled]);

  return { events, connected };
}
```

- [ ] **Step 3: Replace `RunsRoute` polling**

Remove:

```ts
useEffect(() => {
  const timer = window.setInterval(() => runsState.refresh(), 4000);
  return () => window.clearInterval(timer);
}, [runsState.refresh]);
```

Remove the Refresh button. Use SSE events from visible active runs to call `runsState.refresh()` when a durable event arrives. Keep `listRuns()` for initial load and filter changes.

- [ ] **Step 4: Build List view**

Rows render:

- colored status dot plus text;
- workflow name as primary label;
- short id mono with copy button;
- meta line from `runMetaLine()`;
- status pill;
- relative timestamp;
- diff summary from `getRunDiff()` when available;
- whole row click opens `/runs/{id}`.

- [ ] **Step 5: Build Board view**

Map lanes:

- Queued: `queued`, `preparing`;
- Running: `running`;
- Awaiting you: `waiting_for_approval`;
- Done: `completed`, `cancelled`, `writeback_pending`, `writeback_applied`.

Failed runs only appear when the failed filter chip is selected. Cards show name, short id, meta. `Awaiting you` cards include inline Approve action that uses `listApprovals()` and `answerApproval()`.

- [ ] **Step 6: Acceptance check**

Run:

```bash
cd web && npm run test:graph
cd web && npm run build
```

Manual visual acceptance:

- Refresh button is absent.
- Live indicator changes when EventSource connects.
- Empty state shows icon text and `Launch your first run`.
- Keyboard can tab through List/Board toggle, chips, Launch, rows/cards, and approve buttons.

- [ ] **Step 7: Commit**

```bash
git add web/src/hooks/useRunEvents.ts web/src/routes/RunsRoute.tsx web/src/api.ts web/src/components/ui.tsx web/src/styles.css web/src/runViewModel.ts web/src/runViewModel.test.ts web/package.json
git commit -m "feat: add live run list and board views"
```

### Task 6: Run Detail Product View

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/RunDetailRoute.tsx`
- Modify: `web/src/components/GraphViewer.tsx`
- Modify: `web/src/graphHighlight.ts`
- Modify: `web/src/graphHighlight.test.ts`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/styles.css`
- Test: `tests/test_console_product_v2_run_diff.py`
- Acceptance: no raw hash title, diff content expands, timeline is human-readable, artifacts link by filename.

- [ ] **Step 1: Add diff content API test**

Create `tests/test_console_product_v2_run_diff.py`:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_run_diff_includes_bounded_patch_content(platform_harness) -> None:
    run = await platform_harness.create_run_with_worktree(
        base_commit="base-commit",
        head_commit="head-commit",
        diff_patch="diff --git a/HELLO.md b/HELLO.md\n+hello\n",
    )
    response = await platform_harness.client.get(f"/api/runs/{run.id}/diff?include_patch=true")

    assert response.status_code == 200
    file_row = response.json()["files"][0]
    assert file_row["path"] == "HELLO.md"
    assert file_row["patch"].startswith("diff --git")
    assert len(file_row["patch"]) <= 60_000
```

Use the fake git harness style from `tests/test_phase3_console_api_contracts.py` if a reusable `platform_harness` helper is not present.

- [ ] **Step 2: Extend diff endpoint**

In `get_run_diff`, when `include_patch=true`, call:

```python
git.run(diff_cwd, "diff", "--find-renames", "--unified=80", base_commit, head_commit, "--", path)
```

Attach a bounded `patch` string to each file row and set `patch_truncated` if over 60,000 characters.

- [ ] **Step 3: Header and actions**

In `RunDetailRoute.tsx`, set `PageHeader` title to `runWorkflowName(run)`, not `run.id`. Subline includes short id copy, `source_branch -> managed_branch`, relative time, and duration. Show actions:

- `Promote branch` primary when `status === "completed" && managed_branch`;
- `Re-run` always when `run_spec` can convert;
- `Cancel` only for active statuses.

- [ ] **Step 4: Graph status**

Extend `graphHighlight.ts` to mark:

- active running node as `running`;
- approval gate as `waiting`;
- failed node as `failed`;
- completed nodes as `completed`;
- checkpointed nodes as `checkpointed`.

Update legend to use semantic tokens and include text labels.

- [ ] **Step 5: Changes section**

Replace `BranchDiff` table with expandable file rows. Each row shows path, status, `+N -M`, and a `details` expander containing `<pre className="diff-code">`.

- [ ] **Step 6: Timeline section**

Replace raw JSON table with event rows:

- icon + event label;
- formatted summary such as `Build started`, `approval requested at review`, `checkpoint saved abc123`;
- relative time;
- quiet `view raw` `<details>` containing JSON.

- [ ] **Step 7: Long values and artifacts**

Use `TruncatedValue` and `CopyButton` for worktree, refs, branches, and artifact URIs. Artifact row link text is `artifact.name`; link target is a new `GET /api/runs/{run_id}/artifacts/{artifact_id}` when an id exists, otherwise do not link unknown file URIs.

- [ ] **Step 8: Acceptance check**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_run_diff.py tests/test_phase3_console_api_contracts.py -v
cd web && npm run test:graph
cd web && npm run build
```

Manual visual acceptance:

- Header never uses a raw 32-character id as title.
- Agent output is readable without opening raw JSON.
- Long paths/refs stay one line and copy.
- Artifacts show filename links rather than URI strings.

- [ ] **Step 9: Commit**

```bash
git add src/attractor_server/platform_app.py web/src/api.ts web/src/routes/RunDetailRoute.tsx web/src/components/GraphViewer.tsx web/src/graphHighlight.ts web/src/graphHighlight.test.ts web/src/components/ui.tsx web/src/styles.css tests/test_console_product_v2_run_diff.py
git commit -m "feat: polish run detail experience"
```

### Task 7: Deep Settings Area

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `src/attractor_server/__main__.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/SettingsRoute.tsx`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/styles.css`
- Test: `tests/test_console_product_v2_settings_api.py`
- Acceptance: grouped left sub-nav, one template, editability tag on every row, all requested knobs visible.

- [ ] **Step 1: Write settings API contract test**

Create `tests/test_console_product_v2_settings_api.py`:

```python
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_deep_settings_overview_contains_operator_knobs(settings_client) -> None:
    response = await settings_client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    pages = payload["pages"]
    page_ids = {page["id"] for page in pages}
    assert {
        "models",
        "integrations",
        "sandboxes",
        "environments",
        "variables",
        "secrets",
        "run-defaults",
        "server",
        "security",
        "storage",
        "monitoring",
        "live-events",
    } <= page_ids
    for page in pages:
        assert page["title"]
        assert page["description"]
        for group in page["groups"]:
            assert group["title"]
            for row in group["rows"]:
                assert row["editability"] in {"editable", "restart-required", "read-only", "reserved"}
                assert {"label", "description", "value", "editability"} <= set(row)
```

Build `settings_client` using the helper pattern in `tests/test_phase3_settings_api.py`.

- [ ] **Step 2: Extend settings response**

In `get_settings`, keep legacy top-level keys for compatibility and add `pages`. Each page has:

```python
{
    "id": "storage",
    "title": "Storage",
    "description": "Configured from server flags and environment variables. Restart required for path changes.",
    "groups": [
        {
            "title": "Database",
            "rows": [
                {
                    "label": "Database URL",
                    "description": "Controls the platform metadata store.",
                    "value": redacted_database_url,
                    "editability": "restart-required",
                }
            ],
        }
    ],
}
```

Add all requested pages and knobs:

- Sandboxes: local and Docker `RunEnvironment` providers, enabled status.
- Environments: repo `project.toml [environments]`, provider, image, CPU/mem/disk, lifecycle.
- Run defaults: `--max-concurrent`, default environment, retry presets, timeouts, approval/write-back policy, protected branches.
- Server: `--host`, `--port`, web/API URLs, listen address, version, OS, uptime.
- Storage: DB type, redacted `--database-url`, `--worktree-root`, `--artifact-root`, retention policy, artifact capture, max size, managed/reclaimable bytes.
- Security: no-auth posture, allowed repo roots, redaction, actor labels.
- Monitoring: CPU, memory, disk, run concurrency.
- Live events: durable SSE endpoint, current active streams if available, replay behavior.

- [ ] **Step 3: Preserve secrets masking**

Keep secret editing on the Secrets page only. Inputs use `type="password"` and responses never include secret values.

- [ ] **Step 4: Replace settings UI layout**

In `SettingsRoute.tsx`, replace top tabs with grouped left sub-nav:

- General: Models, Integrations, Sandboxes
- Workflows: Environments, Variables, Secrets, Run defaults
- Administration: Server, Security, Storage, Monitoring
- Live events

Every page renders the same template: title, one-line description, grouped cards, `SettingsRow` rows.

- [ ] **Step 5: Acceptance check**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_settings_api.py tests/test_phase3_settings_api.py -v
cd web && npm run build
```

Manual visual acceptance:

- Switching settings pages does not change layout structure.
- Every row has an editability tag.
- Read-only rows are still visible and explained.
- Restart-required rows say where configured.
- No secret value can be revealed in UI or API payload.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_server/platform_app.py src/attractor_server/__main__.py web/src/api.ts web/src/routes/SettingsRoute.tsx web/src/components/ui.tsx web/src/styles.css tests/test_console_product_v2_settings_api.py
git commit -m "feat: add deep operator settings"
```

### Task 8: Final Verification Gate

**Files:**
- No source changes unless a verification failure identifies a concrete defect.

- [ ] **Step 1: Python full suite**

Run:

```bash
uv run python -m pytest tests/
```

Expected: PASS on default SQLite path with no live provider keys. Record the full count from pytest output, for example `N passed, M skipped`.

- [ ] **Step 2: Ruff**

Run:

```bash
uv run ruff check .
```

Expected: PASS with no lint errors.

- [ ] **Step 3: Pyright**

Run:

```bash
uv run pyright
```

Expected: `0 errors`.

- [ ] **Step 4: Web build**

Run:

```bash
cd web && npm run build
```

Expected: PASS.

- [ ] **Step 5: Key-free model validation coverage**

Run:

```bash
uv run python -m pytest tests/test_console_product_v2_model_testing.py -v
```

Expected: PASS using fake tester only. Do not set real `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY` for automated verification.

- [ ] **Step 6: Manual operator smoke**

With provider keys configured by an operator outside automated tests:

```bash
uv run python -m attractor_server --platform
```

Open the console, go to Settings -> Models, run `Test models`, and confirm the page shows `N ok · M failed` plus per-row statuses. Record the date, provider key sources (`environment` or `vault`), and summary counts; do not record key values.

- [ ] **Step 7: Commit verification fixes**

If verification required fixes:

```bash
git add <fixed-files>
git commit -m "fix: satisfy console product v2 verification"
```

If no fixes were required, do not create an empty commit.

## Self-Review Checklist

- Spec sequence is preserved: Models/Test Models/catalog/defaults -> design tokens -> run list/board/detail -> settings depth.
- UI tasks name existing `web/` files and include acceptance checks.
- Existing durable SSE stream remains the live-update mechanism; no polling is introduced.
- Automated tests remain key-free; live model validation is operator-run only.
- One-run-path executor constraint is preserved.
- Catalog defaults resolve to verified current IDs from official docs.
- Full verification gate requires pytest full-suite counts, ruff clean, pyright zero errors, and web build.
