# 29 — Application Discovery & Dynamic Launching Assessment

> **Document Scope:** Forensic analysis of why opening ordinary installed applications currently fails in J.A.R.V.I.S. (documenting all four stacked implementation defects), evaluation of Windows application discovery mechanisms (Registry, Start Menu, AppX/MSIX, `PATH`), alias & fuzzy matching design, and security hardening against LOLBin / shell / elevation abuse under the owner's revised 3-tier authorization policy.

---

## 1. Root-Cause Stack: Why Opening Ordinary Installed Apps Fails Today

Tracing a spoken or typed request such as `"Buka Chrome"` or `"Buka kalkulator."` reveals **four independent, stacked failure layers**—meaning fixing any single layer alone still leaves application launching broken:

| Layer | Exact Source Location | Actual Code Behavior | Failure Outcome | Status |
| :---: | --- | --- | --- | :---: |
| **1. Router Punctuation & 3-App Alias Map** | `core/jarvis/domain/router.py:37, 80-87, 99-101, 401` | `normalize_utterance()` preserves Whisper trailing `.`. `_APP_LAUNCH_RE` (`[a-z0-9 _.-]{2,40}`) captures `"kalkulator."` instead of `"kalkulator"`. `_APP_ALIASES` only contains 6 keys mapped to `calculator`, `notepad`, `paint`. | `"Buka kalkulator."` misses `_APP_ALIASES`; `"Buka Chrome"` misses alias & falls through to LLM prose or rejected target. | `BROKEN` |
| **2. R1 Grant Gate + Onboarding Omission** | `core/jarvis/domain/policy.py:274-282`; `app.py:143`; `OnboardingWizard.tsx:99-104`; `brokerClient.ts:273-278` | `os.app.launch` requires an explicit R1 `permission_grant` DB row. `"1-Click Recommended Setup"` skips Step 9 (`allowAppGrant` stays `false`), and startup auto-grants only `screen.read`. | Fresh install rejects **every** `os.app.launch` request with `403 DENIED`. | `BROKEN` |
| **3. Hardcoded 3-Binary System32 Allowlist** | `core/jarvis/platform/windows/desktop_automation.py:13-17, 27-37` | `_ALLOWLISTED_WINDOWS_APPS = {"calculator": "calc.exe", "notepad": "notepad.exe", "paint": "mspaint.exe"}` resolved strictly under `SYSTEMROOT\System32`. Any other app raises `PermissionError`. | Chrome, Edge, VS Code, Spotify, Word, Excel, Discord, Telegram, Explorer, etc. are **all hard-rejected**. | `BROKEN` |
| **4. Production `allow_live_launch=False` Toggle** | `core/jarvis/transport/app.py:620`; `desktop_automation.py:38-39` | Production Core instantiates `WindowsDesktopAutomationAdapter(allow_live_launch=False)`. When `False`, `launch_app()` **skips `subprocess.Popen`** and returns `{"launched": True, "verified": True, "dry_run": ...}`! | Even if layers 1–3 are bypassed for `calculator`, **no Windows process ever starts**, while JARVIS falsely claims success. | `BROKEN` |

---

## 2. Current vs. Target Windows Application Discovery Sources

Repository-wide search confirms **zero** installed-application discovery code exists today (`winreg` is only used in `core/jarvis/platform/windows/audio.py:106` for audio registry fallback). On Windows 10/11, no single registry key lists every installed app; a production-grade non-elevated **Windows Installed Application Catalog** must merge and deduplicate **four canonical Windows discovery sources**:

| Discovery Source | Windows Location / API | What It Finds | Requires Admin? | Normalization & Validation Notes |
| --- | --- | --- | :---: | --- |
| **1. Start Menu Shortcuts (Primary GUI Apps)** | `%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\*.lnk` and `%APPDATA%\Microsoft\Windows\Start Menu\Programs\*.lnk` | Almost every user-facing Win32 GUI application (Chrome, VS Code, Office, Spotify, Figma, Zoom, Adobe, etc.) with human display names and icons | **No** | Parse `.lnk` via `IShellLinkW` / COM (never execute blindly); inspect resolved `TargetPath` AND `Arguments`; reject shortcuts targeting denylisted shells/LOLBins or uninstallers (`unins*.exe`, `Uninstall*`). |
| **2. Windows Registry (`App Paths` & `Uninstall`)** | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\*`, `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\*`, plus `Uninstall` (`HKLM`, `HKCU`, `WOW6432Node`) | Registered executables (`chrome.exe`, `code.exe`, `winword.exe`, `excel.exe`, `msedge.exe`), `DisplayName`, `Publisher`, `DisplayVersion`, `InstallLocation` | **No** (Read-only) | Filter out `SystemComponent=1`, `ParentKeyName` updates, runtime redistributables (`VC++ Redist`, `.NET`), and `UninstallString`-only entries lacking a valid GUI executable. |
| **3. Packaged UWP / MSIX / Microsoft Store Apps** | Windows `shell:AppsFolder` (`IKnownFolder` / `FOLDERID_AppsFolder` via COM `IShellItem2` `PKEY_AppUserModel_ID`) or read-only WinRT `PackageManager` | Modern Store/Inbox apps (`Calculator`, `Windows Terminal`, `WhatsApp`, `Spotify Store`, `Photos`, `Clock`, `Mail`, `Paint`, `Notepad` Win11 MSIX) | **No** | Launches cleanly via canonical `AUMID` (`IApplicationActivationManager::ActivateApplication` or `explorer.exe shell:AppsFolder\<AUMID>`), **never** requiring brittle `System32` paths that break on Win11 MSIX redirection! |
| **4. Curated User-Pinned / Portable Apps (Opt-In)** | User-configured entries in SQLite `app_catalog_custom` (explicitly approved by owner via GUI picker) | Portable apps (`.exe` in `D:\Tools\...`) not registered in Start Menu or Registry | **No** | Requires explicit owner GUI registration + SHA-256 / path validation; subject to identical Tier-3 LOLBin denylist. |

> **Why `PATH` Scanning Alone Is Dangerous:** Blindly exposing every binary on `%PATH%` would expose hundreds of CLI/system binaries (`cmd.exe`, `powershell.exe`, `curl.exe`, `git.exe`, `python.exe`, `reg.exe`, `schtasks.exe`, `format.com`, `taskkill.exe`), turning an ordinary app launcher into an arbitrary command execution engine. `%PATH%` MUST NOT be auto-exposed as launchable GUI apps.

---

## 3. Detailed Forensic Findings & Target Architecture

### Finding APP-01: Hardcoded 3-App Stub & Disabled Live Launch in Production
- **Source Evidence:** `core/jarvis/platform/windows/desktop_automation.py:13-45`; `core/jarvis/transport/app.py:620`.
- **Current Behavior:** Only `calc.exe`, `notepad.exe`, `mspaint.exe` are recognized, and `allow_live_launch=False` silently fakes launches in production.
- **Expected Behavior:** Real non-elevated Windows process activation (`CreateProcessW` with `CREATE_NEW_PROCESS_GROUP`, zero `shell=True`, zero `runas` elevation, or `IApplicationActivationManager` for MSIX AUMIDs) backed by a live cached `InstalledAppCatalog` refreshed at startup and on Start Menu / Registry changes.
- **Probable Root Cause:** Confirmed test-mode stub left enabled in production `app.py` composition root.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Build `WindowsAppDiscoveryService` (Start Menu + Registry + `AppsFolder` AUMID) storing canonical catalog entries in SQLite (`installed_app` table with `app_id`, `display_name`, `publisher`, `launch_kind` (`EXE` | `AUMID`), `canonical_target`, `trust_tier`, `last_verified_at`), and enable real non-elevated launch in production (`allow_live_launch=True` outside test fixtures).
- **Security Implications:** Must verify `canonical_target` exists, is not a reparse point into a forbidden binary, and does not request UAC elevation (`requireAdministrator` manifest inspection or non-elevated token enforcement).
- **Acceptance Criteria:** Discovery finds standard Win32 + MSIX apps in `< 1.5s` on cold start; launching Chrome, VS Code, Notepad, and Calculator spawns real Windows processes with verified PID/activation result (`dry_run=False`).

### Finding APP-02: Missing Fuzzy Name Resolution, Indonesian/English Aliases & Disambiguation
- **Source Evidence:** `core/jarvis/domain/router.py:37, 80-87` (6 static aliases, trailing-dot capture bug).
- **Current Behavior:** Users must say an exact English/Indonesian word matching 1 of 3 apps without punctuation. Common everyday phrases (*"buka chrome"*, *"buka vs code"*, *"buka browser"*, *"buka excel"*, *"buka spotify"*, *"buka pengaturan"*) fail completely.
- **Expected Behavior:** Multi-signal app entity resolver:
  1. **User-Defined Aliases (`app_alias` table, highest priority):** e.g., `"koding"` -> `Visual Studio Code`, `"browser"` -> `Google Chrome`, `"musik"` -> `Spotify`.
  2. **Built-in Bilingual Synonym Layer:** e.g., `"kalkulator"` -> Calculator, `"catatan"` -> Notepad, `"peramban"` -> Default Browser, `"penjelajah file"` -> File Explorer, `"pengaturan"` -> Windows Settings.
  3. **Normalized Fuzzy Match (Token Set + Trigram/Jaro-Winkler):** matches `"vs code"` / `"visual studio"` -> `Visual Studio Code`, `"word"` -> `Microsoft Word`, `"wa"` -> `WhatsApp`.
  4. **Deterministic Ambiguity Handling:** If top-2 candidates score within delta `< 0.12` (e.g., `"Visual Studio 2022"` vs `"Visual Studio Code"`), JARVIS asks a short clarifying question (*"Maksud Anda Visual Studio Code atau Visual Studio 2022?"*) rather than launching the wrong app.
- **Probable Root Cause:** Confirmed static 6-entry dictionary and missing entity-resolution service.
- **Verification Status:** `BROKEN` / `NOT IMPLEMENTED`.
- **Proposed Improvements:** Implement `AppEntityResolver` combining user aliases, bilingual synonyms, and scored fuzzy matching over `InstalledAppCatalog`, plus Settings UI + voice/GUI alias creation (*"kalau saya bilang koding, maksudnya VS Code"* -> saved as preference/alias).
- **Security Implications:** Fuzzy matching must never relax the Tier-3 denylist—even if a user creates an alias `"terminal"` -> `powershell.exe`, the Policy Engine MUST reject registering or launching any Tier-3 prohibited binary.
- **Acceptance Criteria:** `>= 95%` Top-1 resolution accuracy across 50 bilingual app-launch utterances (including Whisper phonetic typos); ambiguous pairs always trigger clarification rather than silent wrong launch.

### Finding APP-03: Tier-1 Auto-Allow vs. Tier-3 LOLBin / Shell / Elevation Security Boundary
- **Source Evidence:** `core/jarvis/domain/policy.py:274-282`; `core/jarvis/platform/windows/desktop_automation.py:13-37`.
- **Current Behavior:** Policy treats all app launches uniformly as R1 requiring manual DB grant, with no distinction between benign GUI applications (Spotify, Word, Calculator) and dangerous system/shell/LOLBin executables.
- **Expected Behavior:** Split application classification strictly into three trusted policy tiers enforced in Python/Rust:
  - **Tier 1 (Auto-Allowed, Zero Confirmation):** Verified non-elevated GUI applications discovered in trusted install roots (`Program Files`, `Program Files (x86)`, `%LOCALAPPDATA%\Programs`, `WindowsApps`/MSIX, safe Inbox GUI tools like `calc`, `notepad`, `mspaint`, `explorer.exe`) NOT matching the Tier-3 denylist.
  - **Tier 2 (Explicit GUI Approval):** Launching newly registered custom/portable user binaries outside standard install roots, or launching an installer/updater, or passing external file/URL arguments outside authorized scopes.
  - **Tier 3 (Strictly Prohibited — Hard Denylist, Non-Overridable):**
    - Shells & script hosts: `cmd.exe`, `powershell.exe`, `pwsh.exe`, `wscript.exe`, `cscript.exe`, `mshta.exe`, `wsl.exe`, `bash.exe`, `wt.exe` (unless explicitly audited non-command profile—default banned under arbitrary-shell prohibition).
    - System/disk/registry destruction & LOLBins: `regedit.exe`, `reg.exe`, `diskpart.exe`, `format.com`, `bcdedit.exe`, `vssadmin.exe`, `wbadmin.exe`, `cipher.exe`, `sdelete*.exe`, `rundll32.exe`, `regsvr32.exe`, `certutil.exe`, `bitsadmin.exe`, `msiexec.exe`, `schtasks.exe`, `sc.exe`, `net.exe`, `netsh.exe`, `takeown.exe`, `icacls.exe`, `attrib.exe`, `taskkill.exe`, `shutdown.exe`, `runas.exe`, `psexec*.exe`, `unins*.exe`.
    - **Shortcut Argument Guard:** Any `.lnk` whose resolved target is on the denylist OR whose target arguments invoke shell flags (`-enc`, `/c`, `/k`, `-Command`) is excluded during catalog ingestion and rejected at launch time.
    - **Zero Elevation:** Process launch MUST NEVER pass `runas` verb or trigger UAC elevation; if an executable manifest requires elevation (`ERROR_ELEVATION_REQUIRED` / WinError 740), fail safely and report that elevated apps cannot be auto-launched.
- **Probable Root Cause:** Confirmed absence of binary trust classification and LOLBin denylist.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Implement `AppTrustClassifier` enforced both at catalog ingestion time and again at launch time (`defense-in-depth`), passing **empty/strictly validated argument vectors** (`CreateProcessW` with `shell=False`) and logging every launch and denial to the immutable audit trail.
- **Security Implications:** Essential control preventing Addendum §B Tier-3 bypass via voice/LLM social engineering or indirect prompt injection (*"open PowerShell and delete..."* or crafting a malicious Start Menu shortcut).
- **Acceptance Criteria:**
  - Opening Chrome, Calculator, Notepad, VS Code, Spotify, Word, or Excel executes immediately under Tier 1 (`0` confirmation dialogs).
  - Attempting to launch any binary in the Tier-3 denylist (directly, by alias, by fuzzy name, or via `.lnk` redirection) returns `403 PROHIBITED_TIER3` with `0%` bypass across automated adversarial tests.
  - Launching any UAC-elevated binary fails cleanly without spawning a UAC prompt.
