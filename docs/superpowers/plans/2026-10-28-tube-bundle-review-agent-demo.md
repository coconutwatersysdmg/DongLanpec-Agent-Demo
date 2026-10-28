# Tube Bundle Review Agent Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the old drawing-centric sibling demo with a single-window, four-stage tube-bundle review agent that extracts file evidence, supports easy human edits, validates linked parameters, and saves approved results only to an isolated SQLite database.

**Architecture:** A PyQt5 shell drives a deterministic local agent pipeline. The pipeline scans documents, loads mock upstream/default/history data, optionally asks DeepSeek for schema-bound document facts, merges only reviewable proposals, validates each stage, and commits human-approved snapshots through an atomic SQLite repository. Production DongLanpec remains read-only reference code and is never imported for side-effecting loads or writes.

**Tech Stack:** Python 3.12, PyQt5, sqlite3, PyMuPDF (`fitz`), openpyxl, urllib, Windows DPAPI, unittest.

**Spec:** `docs/2026-10-28-管束AI单窗口审核Demo设计.md`

## Global Constraints

- Change only `管束AI方案/DongLanpec-Agent-Demo`; do not add AI code to `DongLanpec`.
- Save reviewed results only to `%LOCALAPPDATA%/DongLanpecAgentDemo/tube_agent_demo.sqlite3` or an explicit test override.
- Never log or persist a plaintext API key; optional persistence uses Windows DPAPI.
- The model may propose facts but may not approve, validate, execute SQL, or commit.
- Questions, conflicts, unchecked alternatives, and unsupported legacy DOC content may not silently override a base value.
- A user edit invalidates the current approval; an upstream edit invalidates dependent downstream approvals.
- Validation failures must identify the exact field, render it red in the UI, explain the error, and provide an optional recommended value. Applying a recommendation is a user action and always requires re-validation.
- Passing deterministic validation never advances or saves automatically; a separate user confirmation is required to save the stage and move on.
- Use only the current `E:/Homework/AALB/ACode/DongLanpec` checkout as the production-code baseline; legacy copies are non-authoritative.
- Support the common fields for AEU, BEU, AKU, BKU, AES, BES, AEM, BEM, NEN, and NEN(H); report unported type-specific rules as uncovered.
- Reopened history is read-only; continuing creates a copied new version, never overwrites the old version.
- Persist evidence excerpts and file hashes, not full source documents.
- Target the current Windows + Anaconda environment; producing a portable EXE is out of scope.

## Review Focus

- A ZIP containing multiple equipment records must require one equipment selection and avoid cross-equipment evidence leakage; Task 2 tests this.
- “U-tube count” and “tube-hole count” must remain distinct parameters; Task 2 tests this.
- A question or unresolved review comment must become a conflict, not a fact; Task 3 tests this.
- Editing a previously accepted upstream value must invalidate downstream stage reviews; Task 4 tests this.
- A database failure during final save must roll back all finalization changes and keep the design retryable; Task 1 tests this.
- Missing API credentials must leave an honest offline review flow rather than block launch or claim a real model result; Task 3 tests this.
- A recommendation may be applied with one click but must not preserve the previous validation pass; Task 4 tests this.
- A stage that passed validation but has not received explicit user confirmation must remain unsaved and must not advance; Tasks 1, 4, and 5 test this.

---

### Task 1: Isolated SQLite repository and seeded engineering context

**Files:**
- Create: `demo_db.py`
- Create: `models.py`
- Test: `tests/test_demo_db.py`

**Interfaces:**
- Produces: `DemoRepository(path)`, `load_base_context(product_type, dn) -> dict`, `lookup_history(product_type, dn) -> list[dict]`, `save_stage(design_id, stage, payload, expected_version) -> int`, and `finalize_design(design_id, expected_version) -> int`.

- [ ] **Step 1: Write failing repository tests** for schema creation, source labels, nearest same-type/DN history, optimistic version checks, and transaction rollback on injected finalization failure.
- [ ] **Step 2: Run `python -m unittest tests.test_demo_db -v`** and verify missing repository failures.
- [ ] **Step 3: Implement focused dataclasses and the SQLite repository** with schema migrations, deterministic seed data, JSON serialization, transactions, and test path override.
- [ ] **Step 4: Run `python -m unittest tests.test_demo_db -v`** and verify all Task 1 tests pass.

### Task 2: Safe document inventory, equipment selection, and evidence retrieval

**Files:**
- Create: `document_reader.py`
- Test: `tests/test_document_reader.py`

**Interfaces:**
- Consumes: ordinary file paths selected by the user.
- Produces: `scan_inputs(paths) -> DocumentBundle`, `identify_equipment(bundle) -> list[str]`, and `retrieve(bundle, equipment_id, keywords, limit) -> list[Evidence]`.

- [ ] **Step 1: Write failing tests** using generated PDF/XLSX/ZIP fixtures for multi-equipment isolation, sheet/page source references, unsupported `.doc`, irrelevant-file ranking, and distinct tube/tube-hole terminology.
- [ ] **Step 2: Run `python -m unittest tests.test_document_reader -v`** and verify scanner failures.
- [ ] **Step 3: Implement bounded in-memory ZIP scanning** with PyMuPDF/openpyxl readers, file-size/page/character limits, normalized equipment candidates, keyword retrieval, and explicit unsupported statuses.
- [ ] **Step 4: Run `python -m unittest tests.test_document_reader -v`** and verify all Task 2 tests pass.

### Task 3: DeepSeek adapter and controlled agent pipeline

**Files:**
- Replace: `ai_support/api_client.py`
- Create: `pipeline.py`
- Modify: `settings.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_settings_launcher.py`

**Interfaces:**
- Consumes: `DocumentBundle`, selected equipment, `DemoRepository`, and optional `DeepSeekClient`.
- Produces: `TubeBundleAgent.prepare_design(...) -> ReviewSession`, `prepare_stage(stage) -> StageDraft`, and a user-readable `trace` of tool calls.

- [ ] **Step 1: Write failing tests** for the DeepSeek host/model defaults, JSON-schema parsing, prompt-injection-as-data handling, question/conflict filtering, offline non-pretence, provenance priority, and key redaction.
- [ ] **Step 2: Run `python -m unittest tests.test_pipeline tests.test_settings_launcher -v`** and verify failures.
- [ ] **Step 3: Implement the DeepSeek-compatible client** at `https://api.deepseek.com/chat/completions`, fixed schema parsing, bounded evidence prompts, actionable HTTP errors, and no automatic retry.
- [ ] **Step 4: Implement the local agent tool loop** for scan, context load, retrieval, optional extraction, history lookup, validation request, and review preparation; expose every step in plain Chinese trace records.
- [ ] **Step 5: Update DPAPI settings** for DeepSeek labels, environment variables, and advanced endpoint/model fields without plaintext storage.
- [ ] **Step 6: Run Task 3 tests** and verify all pass.

### Task 4: Four-stage linkage, validation, and review state machine

**Files:**
- Create: `rules.py`
- Create: `review_session.py`
- Test: `tests/test_rules.py`
- Test: `tests/test_review_session.py`

**Interfaces:**
- Consumes: base parameters, extracted proposals, component proposals, and human edits.
- Produces: `validate_stage(stage, parameters, components) -> ValidationResult`, `apply_edit(...)`, `apply_recommendation(issue_id)`, `run_review()`, `confirm_and_advance()`, and `current_stage_draft()`.

- [ ] **Step 1: Write failing tests** for DL recomputation, tube diameter/wall/pitch, pass/form combinations, weld length versus tube-sheet thickness, axial protrusion range, component row checks, field-targeted issues with recommended values, recommendation re-validation, explicit confirmation, edit invalidation, and downstream invalidation.
- [ ] **Step 2: Run `python -m unittest tests.test_rules tests.test_review_session -v`** and verify failures.
- [ ] **Step 3: Implement pure derived-value and validation functions** using canonical parameter names and row-targeted Chinese messages.
- [ ] **Step 4: Implement the four-stage review state machine** with `waiting/running/review_required/needs_changes/approved/saving/saved/error` transitions and repository version checks.
- [ ] **Step 5: Run Task 4 tests** and verify all pass.

### Task 5: Single-window designer UI and reliable launcher

**Files:**
- Replace: `window.py`
- Replace: `main.py`
- Modify: `bootstrap.py`
- Modify: `启动管束设计助手.cmd`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `TubeBundleAgent` and `ReviewSession`.
- Produces: a single PyQt window supporting file upload, equipment choice, chat/trace, editable stage tables, validation, accept-and-next, history reopen, settings, and final save.

- [ ] **Step 1: Write failing offscreen UI tests** for no drawing canvas/tabs, example ZIP selection, equipment confirmation, four stages, inline edits, red failed cells, visible error reasons, one-click recommendation fill, mandatory re-review, separate confirm-and-next, final SQLite persistence, and readable error handling.
- [ ] **Step 2: Run `python -m unittest tests.test_window -v`** and verify old-window mismatches.
- [ ] **Step 3: Implement the Codex-like single-window layout** with high-contrast source badges, simple Chinese labels, keyboard-friendly editing, and status text that avoids computer jargon.
- [ ] **Step 4: Implement background analysis and safe UI updates** so large packages do not freeze the window and Stop never corrupts a review session.
- [ ] **Step 5: Make bootstrap locate the moved production sibling robustly** while keeping the new demo independent, and keep the launcher open on startup error.
- [ ] **Step 6: Run Task 5 tests and an offscreen screenshot smoke test**; verify stage navigation and saved database content.

### Task 6: Editable pipeline artifact, documentation, and full verification

**Files:**
- Create: `docs/管束AI审核流-Pipeline.drawio`
- Create: `docs/管束AI审核流-Pipeline预览.svg`
- Replace: `docs/操作手册.md`
- Replace: `README.md`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: the completed application behavior.
- Produces: editable draw.io pages for main pipeline/four-stage dependencies/state machine and a novice-facing operating guide.

- [ ] **Step 1: Create the draw.io source** with separate editable cards/connectors and three pages: main pipeline, four-stage data flow, and state transitions; create a matching SVG preview.
- [ ] **Step 2: Rewrite the operating guide** for first launch, DeepSeek key setup, file/equipment selection, evidence review, editing, validation, accept-and-next, history reopen, database location, and common errors.
- [ ] **Step 3: Run the complete test suite** with `python -m unittest discover -s tests -v` and require zero failures.
- [ ] **Step 4: Run launcher and screenshot smoke tests** with the actual `D:\ProgramData\anaconda3\python.exe` and verify no secret or production DB access appears in logs.
- [ ] **Step 5: Verify both Git worktrees**: the demo contains only intended changes and the production `DongLanpec` repository has no new AI changes.
