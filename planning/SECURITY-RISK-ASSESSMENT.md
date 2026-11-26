# SECURITY, PRIVACY & LICENSING RISK ASSESSMENT — J.A.R.V.I.S.

**Document ID:** `PLAN-08`  
**Version:** 0.2.1 (Aligned with `JARVIS-SDLC-v0.2.1/09-SECURITY-PRIVACY.md`, `15-RISK-GOVERNANCE.md` & `DEC-001`–`DEC-025`)  
**Standards Referenced:** STRIDE, OWASP Top 10 for LLM Applications, OWASP ASVS v5.0.0, NIST AI RMF, NIST SSDF (`SP 800-218`)  
**Date:** 26 November 2026  
**Status:** Updated with Runtime Ownership, Storage Migration, Dual-DB & Open-Source Compliance Controls

---

## 1. Security Architecture & Honest Host Boundary

JARVIS enforces **Zero-Trust Proposal & Untrusted-Input Isolation** across all local, LAN, and remote channels:
1. **Separation of Data vs. Authority**: Spoken audio, documents, web pages, screen OCR text, third-party extension outputs, and AI model generations never carry execution privileges. Every side effect passes through the deterministic **`R0`–`R3` Policy Engine** and, for `R2`, a parameter-bound, nonce-protected, `60s`-expiring native local `<dialog>` approval.
2. **Honest Same-User Boundary**: Running as an unprivileged user process (`0` admin/`SYSTEM` services) protects strongly against prompt injection, voice spoofing, path traversal/*TOCTOU*, SSRF, XSS, unauthorized LAN/remote access, and accidental secret leakage, while transparently noting that malware already executing under the same OS user SID lies outside user-mode isolation guarantees.

---

## 2. Seven-Boundary STRIDE & Lifecycle Security Controls (`T01` – `T18`)

| Trust Boundary | Threats Mitigated (`09-SECURITY-PRIVACY.md`) | Defense-in-Depth Controls & Measurable Targets | Verification |
| :--- | :--- | :--- | :--- |
| **`TB-01` Audio & Voice Input** | `T01` Guest/recorded voice spoofing, speaker TTS self-wake | Wake word grants zero identity; OS `Lock` & `Suspend` immediately close capture streams and cancel pending approvals (`FR-ADM-03`, `FR-SCH-05`); dynamic headphone vs. open-speaker echo protection (`FR-VOI-06`); voice `R2` approval hard-banned. | `TC-FR-ADM-02/03`, `TC-FR-VOI-06` |
| **`TB-02` Docs, Web & Screen** | `T02` Indirect prompt injection, `T07` Screen secret leakage | `tools=[]` during RAG synthesis; untrusted data delimiters; no-network parser worker with file/ZIP-ratio caps (`FR-KNO-05`); pre-inference credential/token/`.env` regex redaction on UIA/OCR (`FR-SCR-04`). | `TC-FR-KNO-05`, `TC-FR-SCR-04` |
| **`TB-03` Runtimes, Models & Extensions** | `T03` Excessive agency, `T08` OOM/zombie workers, `T09` Model/extension supply chain, `T16` External runtime interference | Strict `extra="forbid"` JSON schemas + `≤ 5` steps + *non-thinking* control; SHA-256 manifest checks (`no trust_remote_code`); `ProcessSupervisorPort` (`Job Object` targeting **`≤ 5s`** release of `managed_local` children on forced parent kill, while **strictly leaving `external_local` user runtimes untouched**, `NFR-15`, `FR-AIP-08`); extensions confined behind Policy Engine (`FR-SYS-06`). | `TC-FR-COR-02/03`, `TC-FR-AIP-08`, `TC-NFR-15`, `TC-FR-SYS-06` |
| **`TB-04` WebView2, IPC & Config** | `T14` XSS / spoofed approval UI, `T18` Machine-config / secret leak | Strict CSP (`connect-src 'none'` to internet from WebView), sanitized text/Markdown, explicit Tauri `capabilities/*.json`, `LocalIpcTransportPort` (Named Pipe current-SID DACL + 256-bit pipe-inherited secret), secret-free config export (`FR-SYS-02`), and CI check blocking personal paths (`NFR-16`). | `TC-NFR-04`, `TC-NFR-16`, `TC-FR-SYS-02` |
| **`TB-05` OS & Filesystem Execution** | `T04` Symlink/junction escape & *TOCTOU*, `T06` Replay, `T15` False success | Shell-free `Win32`/`AUMID` launch (`FR-OS-01`/`06`); handle-pinned path & reparse verification (`GetFinalPathNameByHandleW`) + non-overwriting rename (`FR-OS-03`/`04`/`06`); single-use `nonce_hash` + handle-bound `bound_hash`; mandatory adapter readback (`FR-OS-05`). | `TC-FR-OS-01`..`06` |
| **`TB-06` Dual SQLite, Storage Migration & Backups** | `T07` Unencrypted partition leak, `T10` Mid-migration corruption, `T13` Tombstone resurrection, `RK21` Cross-DB drift | `SecretVaultAndCryptoPort` wraps local `AES-256-GCM` `DEK` in OS Vault; `core.db` `root_id` + `deletion_ledger` filter enforced before every `knowledge.db` read + startup orphan GC (`FR-ADM-08`); SMB/UNC blocked for WAL DBs (`FR-SYS-03`); staged checksum-verified storage migration with rollback (`FR-SYS-04`); portable `Argon2id + AES-256-GCM` backups replaying `deletion_ledger` on restore (`FR-MEM-05`). | `TC-FR-ADM-08`, `TC-FR-SYS-03/04`, `TC-FR-MEM-05`, `TC-NFR-05/10` |
| **`TB-07` Web, Private LAN & Remote/IoT** | `T05` SSRF/DNS rebinding, `T11` Stolen phone, `T12` Unsafe IoT, `T17` Unapproved LAN disclosure | DNS-pinned anti-SSRF blocking all private/loopback/link-local/IPv6-mapped IPs on initial connect & redirects (`FR-WEB-02`); explicit TLS-verified LAN enrollment + per-scope consent + zero silent cross-zone fallback (`FR-AIP-06`); private-VPN/TLS remote gateway (`no R2/file/screen`, `FR-REM-01/02`); hard `R3` block on locks/alarms/heaters (`FR-IOT-03`). | `TC-FR-WEB-02`, `TC-FR-AIP-06`, `TC-FR-IOT-03`, `TC-NFR-11` |

---

## 3. Open-Source & Artifact Licensing Risk Governance (`DEC-001`, `DEC-022`, `RK07`)

Rather than enforcing a naive permissive-only ban or ignoring copyleft rules:
1. **Full Compliance Evaluation**: `GPL` (e.g., `OHF-Voice/piper1-gpl`) and `AGPL` (e.g., `PyMuPDF`) candidates are evaluated transparently alongside permissive alternatives (`sherpa-onnx`, `pypdfium2`) during `R0`.
2. **No Legal Shortcuts Assumed**: Architecture documentation explicitly warns that IPC/subprocess boundaries or optional post-install downloads do **not** automatically extinguish `GPL`/`AGPL` distribution or network-interaction obligations; compatibility with the final JARVIS open-source license (`MIT`/`Apache-2.0` vs `GPLv3`/`AGPLv3`) is verified at Gate `G5` prior to public repository release.
3. **Separate Model/Voice/Dataset Auditing**: Every voice checkpoint (such as `piper-voices` `id_ID-news_tts-medium`), wake-word model (`openWakeWord` `CC-BY-NC-SA 4.0`), weight file, font, icon, and earcon is logged in the 11-category `license_artifact` table (`FR-SYS-05`), blocking `Unknown` licenses automatically.

---

## 4. Synchronized Risk Register Summary (`RK01` – `RK22`)

All **22 normalized project risks (`RK01`–`RK22`)** — spanning limited GPU memory (`RK01`), multilingual STT/wake quality (`RK02`), prompt injection (`RK03`, score `20`), guest/remote abuse (`RK04`), restore tombstones (`RK05`), host sleep (`RK06`), multi-category licensing (`RK07`), pluggable search (`RK08`), UIA limits (`RK09`), secret redaction/encryption (`RK10`), scope discipline (`RK11`), token scopes (`RK12`), trademark clearance (`RK13`), dynamic storage/unplugged drives (`RK14`), runtime schema/thinking drift (`RK15`), `managed_local` vs `external_local` process supervision (`RK16`), LAN disclosure (`RK17`), adaptive high-Hz rendering (`RK18`), stale event ordering (`RK19`), wheel/language-pack verification (`RK20`), Dual-SQLite crash consistency (`RK21`), and `.local` dev-config isolation (`RK22`) — are maintained in full parity with [15-RISK-GOVERNANCE.md](../JARVIS-SDLC-v0.2.1/15-RISK-GOVERNANCE.md).
