# Risk, Governance & Change Control Plan

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. RAID register
Likelihood (L) and impact (I) 1–5; score L×I, ≥15 high, 8–14 medium, ≤7 low. Scores preliminary, reviewed each sprint. Owner roles may be same individual but approval evidence required.

| ID | Risk | L/I | Score | Mitigation / contingency | Owner |
|---|---|---|---|---|---|
| RK01 | 4 GB VRAM insufficient or poor latency | 4/4 | 16 | R0 benchmark, short context, CPU offload, smaller model/direct route | Architect |
| RK02 | Indonesian STT/wake quality poor | 4/3 | 12 | corpus eval, PTT/text fallback, phrase tuning | AI engineer |
| RK03 | Model/tool prompt injection | 4/5 | 20 | typed tools, policy, untrusted data isolation, security gate | Security |
| RK04 | Unauthorized effects by guests/remote | 3/5 | 15 | local approval, scope, lock, no dangerous actions | Security |
| RK05 | Data loss or stale deletion after restore | 3/5 | 15 | transactional storage, encrypted backup, ledger replay, restore drill | Operator |
| RK06 | Host sleep makes assistant unavailable | 4/3 | 12 | missed reminder policy, clear availability, no always-on claim | Product |
| RK07 | Dependency/model/voice license incompatible | 3/4 | 12 | upstream model cards, NOTICE/SBOM, review before distribution | Architect |
| RK08 | Free web provider unavailable or quota limited | 4/3 | 12 | provider adapter, manual browser fallback, no scraping assumption | Product |
| RK09 | OS capture/automation unsupported | 3/3 | 9 | UIA first, app allowlist, manual fallback | Engineer |
| RK10 | Private data leak via logs or web | 3/5 | 15 | redaction, network opt-in, no raw data persist | Security |
| RK11 | Scope creep into coding agent or SaaS | 4/3 | 12 | hard non-goals, change control | Product |
| RK12 | Integration credentials overprivileged | 3/5 | 15 | scoped proxy/account, verify permissions and revocation | Security |
| RK13 | Branding/IP risk for public distribution | 3/3 | 9 | internal working title, clearance before public release | Product |
| RK14 | Unmeasured energy/disk costs | 3/3 | 9 | lazy model lifecycle, metrics, headroom checks | Operator |

Assumptions A01 Windows-first; A02 reference GPU/RAM based on prior user context; A03 single owner; A04 ID primary; A05 local personal use; A06 user accepts staged release. Issues I01 CPU/OS/mic unknown; I02 model/wake/TTS exact versions and licenses unverified; I03 search provider unresolved; I04 HA and remote devices unknown. Dependencies D01 official tool/model releases; D02 GPU driver; D03 test corpus; D04 user permission for real hardware/integration testing; D05 signing and distribution setup. Track status, owner, due date and evidence in implementation RAID log; none marked resolved without evidence.

## 2. Change control
CR template: ID, requester, problem, proposed change, alternatives, requirement IDs, affected ADR/data/API/tests, privacy/security/resource impact, cost/effort, migration/rollback, decision owner/date, approval, release target. Classify minor (docs/no behavior), standard (feature/contract), major (scope, permission, external data, architecture, thresholds). Major changes require explicit owner and security review. Baseline constraints no coding agent and no paid LLM API cannot be changed silently. Update PRD/SRS/SDD/RTM together; version and changelog. Any discovered gap becomes defect or CR, not an undocumented behavior.

## 3. Quality gates and evidence
G0 scope/assumptions accepted; G1 R0 benchmark/license/ADR; G2 design and threat review; G3 implementation review and test results; G4 release security/restore/UAT; G5 handover and maintenance ownership. R1/R2/R3 each repeat G2–G4. Mandatory controls no unauthorized effect, local-only inference, stop/mute, revocation, restore safety. Noncritical waivers require owner, rationale, expiry and remediation issue; no waiver for critical security or core privacy violation. Report weekly if project active: completed deliverables, planned next, blocked issues, test counts, risks, CR decisions. Do not manufacture progress or dates.

## 4. Responsible AI and compliance posture
Map risks to NIST AI RMF governance/map/measure/manage and OWASP LLM threats (18). Model limitations disclosed, no autonomous irreversible decisions, no covert monitoring, no cloud fallback. For distribution, review local privacy law and software/model licenses with qualified reviewer; no claim of regulatory compliance or ISO certification from this documentation alone. Security incidents: stop effects, revoke grants/network, preserve redacted evidence, assess affected data, remediate and regression test before resume.

## Additional risk register v0.2.0
| Risk | Mitigation / gate |
|---|---|
| Adapter incompatibility / unsupported schema | Capability contracts, conformance tests, deterministic fallback |
| Model switching OOM / incompatible indexes | One heavy lease, atomic activation, rollback, generation-scoped embeddings |
| Private LAN disclosure | Explicit scope, TLS identity, revocation, no automatic trust crossing |
| Cinematic UI steals AI resources | Governor, SVG-first, quality tiers and measured NFR-13, no compulsory WebGL |
| Motion sickness / spoofed status / approval | Reduced Motion, text state, trusted dialogs and stale-event checks |
| Movie asset/IP reuse | Original design assets and voice; commercial clearance before public distribution |
New requirements are proposed baseline pending owner approval and R0 validation.
