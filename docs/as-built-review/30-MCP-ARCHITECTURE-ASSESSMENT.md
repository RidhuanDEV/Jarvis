# 30 — Model Context Protocol (MCP) Architecture Assessment

> **Document Scope:** Independent architectural and security evaluation of whether adopting the **Model Context Protocol (MCP)** provides meaningful advantages for J.A.R.V.I.S. (`v0.2.1`) compared to its current stubbed Extension SDK (`extension_package` / `ecosystem_service.py`), evaluating all **16 Addendum §D requirements**, establishing the strict boundary between **fast built-in native tools** and **MCP extensibility**, and defining a hardened MCP Host/Client security design.
>
> **Companion Diagram:** [diagrams/11-mcp-proposed-architecture.mmd](./diagrams/11-mcp-proposed-architecture.mmd).

---

## 1. Strategic Verdict: Should J.A.R.V.I.S. Adopt MCP?

**Yes — selectively, strictly as a sandboxed extensibility layer, and NEVER as a replacement for native desktop tools.**

### Why MCP Adds Real Value Over the Current Extension Stub
1. **Current Extension SDK Is Non-Functional:** Contrary to SDLC expectations, no `extension_registration` table exists; the actual table is `extension_package` (`core/migrations/core/0001_initial_core.sql:355-363`). `EcosystemService` (`core/jarvis/application/ecosystem_service.py:228-381`) is a SQLite metadata stub that never verifies on-disk package hashes, never loads or executes plugins, has dead authorization code (`authorize_extension_capability` has 0 runtime callers), and exposes zero process isolation.
2. **Ecosystem Leverage Without Bespoke Adapters:** Rather than maintaining fragile custom integrations for GitHub, Notion, Google Calendar/Gmail, Jira, Slack, PostgreSQL, Obsidian, Home Assistant, or Linear, a standards-compliant MCP Client allows J.A.R.V.I.S. to connect to audited local/remote MCP servers over versioned JSON-RPC 2.0 contracts.
3. **Structured Discovery & Separation of Concerns:** MCP separates **Tools** (invocable actions), **Resources** (read-only structured context URIs), and **Prompts** (reusable workflows), aligning cleanly with J.A.R.V.I.S.'s Policy Engine and RAG/context pipelines.

### Non-Negotiable Boundary: Native Core vs. MCP Extensibility

| Capability Category | Execution Layer | Architectural Rationale |
| --- | :---: | --- |
| Installed app discovery & launch; authorized filesystem metadata/search/open; volume & media control; system CPU/RAM/GPU/battery telemetry; screen capture/OCR; clock/reminders; Memory Vault; local RAG | **Native Built-In Tools** *(Fast Python/Rust in-process or Tauri broker)* | Sub-50ms latency, zero subprocess IPC overhead, deterministic Windows API integration, 100% offline reliability, direct enforcement of Tier-1/2/3 boundaries. **Core computer functions MUST NEVER depend on external MCP servers.** |
| Developer tools (GitHub, GitLab, Jira, Linear, local DB inspection), productivity SaaS (Calendar, Email, Notion, Obsidian), smart home (Home Assistant), specialized domain APIs, owner-built custom utilities | **MCP Extensibility Layer** *(Opt-in, isolated, policy-mediated)* | Cleanly isolated third-party/optional capabilities with per-server credentials, per-tool permissions, independent updates, and zero blast radius on Core stability if a server crashes. |

---

## 2. Forensic Audit of Current Extensibility Code vs. All 16 Addendum §D Topics

### Finding MCP-01: Current Extension SDK Is a Metadata-Only SQLite Stub
- **Source Evidence:**
  - `core/migrations/core/0001_initial_core.sql:355-363` — `extension_package` table stores `id`, `name`, `version`, `sha256`, `manifest_json`, `status`.
  - `core/jarvis/application/ecosystem_service.py:228-381` — `register_extension` trusts caller-supplied `sha256` without reading or hashing any artifact on disk; `authorize_extension_capability` is defined but has **0 callers** across `core/`; zero subprocess manager, plugin loader, JSON-RPC transport, or IPC sandbox exists.
  - `apps/desktop/src/components/ProductivityPanels.tsx` — Extensions UI panel displays static/unbacked registry state with zero MCP Server Manager.
- **Current Behavior:** Registering an extension inserts a passive SQLite row and does nothing at runtime; JARVIS cannot discover, start, supervise, isolate, or invoke external tools or resources.
- **Expected Behavior:** Either retire the dead custom Extension SDK in favor of a hardened **MCP Host + Client** inside Core (with versioned provider contracts) OR unify extension packaging around signed MCP server manifests with full lifecycle, isolation, and Policy Engine mediation.
- **Probable Root Cause:** Confirmed horizontal scaffolding built to tick SDLC checklist items without implementing an actual execution runtime or isolation boundary.
- **Verification Status:** `MOCK` / `NOT IMPLEMENTED` (`extension_package` CRUD is `IMPLEMENTED`, runtime plugin execution is `NOT IMPLEMENTED`).
- **Proposed Improvements:** Replace custom plugin-execution aspirations with a hardened `McpHostService` implementing MCP JSON-RPC 2.0 (stdio + optional Streamable HTTP/SSE) mediated unconditionally by `AuthorizedActionGateway` (see Section 3).
- **Security Implications:** Leaving an unverified, unsandboxed plugin table in place risks future developers bolting dynamic `importlib` execution onto it without isolation or hash verification.
- **Acceptance Criteria:** Zero dynamic in-process third-party Python code loading; all external tool extensibility flows strictly through the isolated MCP Host with verified artifact hashes and Policy mediation.

---

## 3. Comprehensive 16-Dimension MCP Architecture & Security Evaluation (Addendum §D)

| # | Addendum §D Evaluation Dimension | Current Status | Proposed Hardened J.A.R.V.I.S. Design | Critical Security / Engineering Constraints |
| :---: | --- | :---: | --- | --- |
| 1 | **MCP Host & Client Architecture** | `NOT IMPLEMENTED` | Dedicated `McpHostService` inside Core managing 1 isolated `McpClientSession` per enabled server; exposes discovered tools to `ToolRegistry` under strict namespace `mcp.<server_id>.<tool_name>` so MCP tools can **never shadow native tools** (`os.*`, `fs.*`, `memory.*`). | Native tools always win resolution; LLM never connects directly to MCP servers—all calls pass through `AuthorizedActionGateway`. |
| 2 | **Tool & Resource Discovery** | `NOT IMPLEMENTED` | On server handshake (`initialize` -> `tools/list`, `resources/list`), Core hashes the canonical JSON Schema of every tool name, description, and input schema (`tool_manifest_hash`) and compares it against the owner-approved pinned snapshot. | **Anti-Rug-Pull Control:** If a server silently alters a tool's description or input schema after installation (a known MCP prompt-injection / rug-pull attack), Core immediately **quarantines** the server and requires fresh GUI re-approval before invocation. |
| 3 | **Versioned Provider Contracts** | `NOT IMPLEMENTED` | Pin supported MCP protocol version (`2025-03-26` / negotiated capability set), manifest schema version (`jarvis.mcp.manifest/v1`), and per-server semantic version + artifact SHA-256 digest. | Reject servers requesting unsupported experimental capabilities (e.g., unsolicited `sampling/createMessage` or unrestricted `roots/list`) unless explicitly enabled. |
| 4 | **Trusted MCP Server Installation** | `NOT IMPLEMENTED` | Curated built-in catalog of audited first-party/verified servers + owner opt-in custom local install via explicit Tier-2 GUI review showing exact command, args, binary/package SHA-256, requested scopes, and network endpoints. | **NEVER auto-run `npx -y <unpinned-pkg>` or `uvx <latest>`** from unpinned registries (supply-chain & typosquatting hazard). Require exact version + hash pinning or signed local executable. |
| 5 | **MCP Manager UI** | `NOT IMPLEMENTED` | Dedicated MCP Manager tab in Desktop Settings showing per-server health (`RUNNING`, `STOPPED`, `QUARANTINED`, `CRASHED`), transport type, discovered tools with Tier badges, pinned hashes, active scopes, resource usage, logs, and instant Kill Switch / Pause / Revoke controls. | One-click global MCP Kill Switch immediately terminates all MCP Job Objects and revokes active sessions. |
| 6 | **Server Lifecycle Management** | `NOT IMPLEMENTED` | Supervised lazy-start or startup-configured stdio child processes with health-check pings, exponential restart backoff (max 3 restarts/5 min -> `QUARANTINED`), graceful `SIGTERM`/stdin-close shutdown + hard kill after 3s, and clean orphan termination on Core crash via Windows `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. | Prevents zombie `node.exe` / `python.exe` MCP servers leaking RAM/handles after JARVIS exits or crashes. |
| 7 | **Tool Capability Classification** | `NOT IMPLEMENTED` | Classify every MCP tool into J.A.R.V.I.S.'s 3-Tier Policy (`Tier 1: Read-Only`, `Tier 2: State-Changing / External Send`, `Tier 3: Prohibited`). MCP `readOnlyHint` / `destructiveHint` annotations are treated as **advisory hints only**, NEVER trusted blindly! | **Fail-Closed Default:** Unknown or newly discovered MCP tools default to **Tier 2 (Explicit GUI Approval)**. Tools declaring or matching shell execution, arbitrary filesystem deletion, or credential extraction are **hard-blocked (Tier 3)**. |
| 8 | **Per-Server & Per-Tool Permissions** | `NOT IMPLEMENTED` | Fine-grained SQLite grant matrix `(server_id, tool_name, tier_override, allowed_fs_roots, allowed_domains, enabled)` evaluated by `PolicyEngine` on every single invocation. | Disabling a single tool (`mcp.github.delete_branch`) keeps read tools (`mcp.github.list_issues`) functional without all-or-nothing risk. |
| 9 | **Approval Integration** | `NOT IMPLEMENTED` | Any Tier-2 MCP tool call creates a standard `ApprovalService` GUI request displaying: server name, tool name, verified arguments JSON, affected resource/recipient, impact summary, single-use nonce, and TTL countdown. | Voice confirmation alone can **never** authorize Tier-2 MCP writes/sends (`TRUSTED_UI` + `LOCAL` + unlocked OS strictly enforced). |
| 10 | **Process Isolation** | `NOT IMPLEMENTED` | Every local stdio MCP server spawns with: (a) dedicated **Windows Job Object** (memory cap, CPU rate limit, active process count limit, `KILL_ON_JOB_CLOSE`); (b) **stripped environment variables** (zero inherited OS/JARVIS tokens, zero `%APPDATA%` secrets—only explicitly scoped per-server credentials); (c) restricted working directory; (d) optional Windows AppContainer / Low-Integrity token for high-risk untrusted servers. | Prevents a compromised MCP subprocess from reading `jarvis_core.db`, harvesting the Core loopback Bearer token, or spawning fork bombs. |
| 11 | **Filesystem & Network Access Controls** | `NOT IMPLEMENTED` | For MCP `roots`, pass strictly canonical owner-authorized subdirectories (never `C:\` or `%USERPROFILE%`, never excluded credential paths). For Streamable HTTP/SSE remote MCP servers: enforce `offline_mode` hard block, HTTPS-only + TLS verification, DNS-pinned anti-SSRF (blocking RFC1918/loopback/link-local unless explicitly configured local), and explicit domain allowlist. | Enforces `BR-01` (offline-first / zero unsolicited network egress) and prevents SSRF into internal LAN/cloud metadata services. |
| 12 | **Credential Management** | `NOT IMPLEMENTED` | Store per-server API keys / OAuth tokens strictly in **Windows Credential Manager / DPAPI** (`keyring` / Win32 CredWrite), injected at process launch ONLY to the owning MCP server's isolated environment or authenticated HTTP header; **never** stored in plaintext SQLite or exposed to the LLM prompt or logs. | Even if the LLM is prompt-injected, it can never read or exfiltrate MCP server API keys. |
| 13 | **Prompt Injection Defense** | `NOT IMPLEMENTED` | Apply **strict `BR-15` tainting**: every MCP tool response and MCP resource payload is wrapped in structural untrusted-data delimiters, scrubbed of instruction-injection patterns before presentation, AND sets `SessionContext.untrusted_origin = True`—blocking automatic follow-on state-changing native or MCP tool calls without explicit GUI review. | Closes the #1 real-world MCP attack vector (indirect prompt injection via GitHub issue / email / webpage body triggering local file/tool actions). |
| 14 | **Tool Output Validation** | `NOT IMPLEMENTED` | Validate every MCP JSON-RPC response against maximum payload byte ceiling (e.g., `64 KiB` to LLM context; larger blobs spilled to bounded temp buffer), valid UTF-8, schema conformance, and redaction of accidental secret/bearer-token patterns before logging or passing to LLM. | Prevents context-window DoS, JSON parser crashes, and accidental credential leakage into chat history or logs. |
| 15 | **Audit Logging** | `NOT IMPLEMENTED` | Every MCP lifecycle event (`install`, `start`, `hash_mismatch`, `quarantine`, `stop`) and every tool call (`server_id`, `tool_name`, `arg_hash`, `policy_tier`, `approval_id`, `duration_ms`, `status`, `error_code`) writes to the hash-chained `audit_event` table with PII/secret redaction. | Full forensic traceability across native and external tool boundaries. |
| 16 | **Timeout, Cancellation & Failure Recovery** | `NOT IMPLEMENTED` | Bounded per-call timeout (default `15s`, max `60s`), propagation of MCP `notifications/cancelled` on user barge-in or UI cancel, circuit breaker (`3` consecutive timeouts/errors -> `OPEN` state), and graceful natural-language degradation (*"Server MCP kalender sedang tidak merespons; fungsi desktop lokal tetap berjalan normal."*). | Ensures a hung third-party MCP server can never freeze `TurnOrchestrator` or `LiveVoiceEngine`. |

---

## 4. Detailed Findings & Acceptance Criteria

### Finding MCP-02: Risk of Unrestricted Shell/Filesystem Exposure via Third-Party MCP Servers
- **Source Evidence:** `core/jarvis/application/ecosystem_service.py:228-381` (zero capability classification or sandbox); `core/jarvis/domain/models.py:412` (`untrusted_origin` dead flag).
- **Current Behavior:** No MCP layer exists yet, and the existing `PolicyEngine` + `untrusted_origin` taint system is not hardened enough to safely host untrusted third-party tool servers.
- **Expected Behavior:** MCP Host ships **only after** Phase 1 authorization hardening ([27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md](./27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md)) is complete, enforcing non-shadowable tool namespacing, tool-schema hash pinning, Job Object isolation, Tier-3 hard bans (never allowing a `filesystem-delete` or `bash/powershell` MCP server to bypass Tier 3), and `untrusted_origin` taint propagation.
- **Probable Root Cause:** Architectural gap between nascent extension stub and production MCP threat model.
- **Verification Status:** `NOT IMPLEMENTED` (prerequisite Policy/tainting layers currently `BROKEN`).
- **Proposed Improvements:** Implement `McpHostService` in Phase 3 following the 16 controls in Section 3, starting with 2–3 high-value read-first audited servers (e.g., Calendar/Notes/GitHub read) before allowing arbitrary custom local MCP servers.
- **Security Implications:** Installing an unhardened MCP client (e.g., exposing generic filesystem or shell MCP servers directly to a local 4B LLM) would completely nullify J.A.R.V.I.S.'s Tier-3 non-deletion guarantee and expose the machine to trivial indirect prompt injection.
- **Acceptance Criteria:**
  - Native desktop commands (app launch, file search, volume, clock) continue working with `0` MCP servers installed or when all MCP servers crash.
  - Mutating a running MCP server's `tools/list` description triggers automatic `QUARANTINED` state and blocks execution (`100%` rug-pull detection).
  - Killing Core crashes/exits cleanly terminates all child MCP processes via Windows Job Object (`0` orphaned processes).
  - Prompt injection embedded inside an MCP tool response sets `untrusted_origin=True` and achieves `0%` unauthorized chained execution against native or MCP write tools.
