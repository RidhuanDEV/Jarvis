# Technical References, Standards & Verification Notes

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Requirements and governance references
| ID | Source | Application |
|---|---|---|
| REF-01 | [ISO/IEC/IEEE 29148:2018](https://www.iso.org/standard/72089.html) | Requirements structure, attributes, traceability; public abstract consulted, not full paid standard or certification |
| REF-02 | [ISO/IEC/IEEE 42010:2022](https://www.iso.org/standard/74393.html) | Stakeholders, concerns and architecture description; public abstract only |
| REF-03 | [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) | Risk governance and AI evaluation |
| REF-04 | [OWASP Top 10 for LLM Applications](https://owasp.org/projects/top-10-for-large-language-model-applications) | Prompt injection, excessive agency, sensitive information and supply chain |

## 2. Primary technical references
| ID | Source | Relevance |
|---|---|---|
| REF-05 | [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | GGUF local inference, GPU offload and constrained JSON |
| REF-06 | [Qwen3-1.7B GGUF](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF) | Candidate lightweight model; verify exact revision/license |
| REF-07 | [Qwen3-4B GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | Candidate higher quality; verify actual fit |
| REF-08 | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Local STT, CPU int8 and GPU options |
| REF-09 | [openWakeWord](https://github.com/dscripka/openWakeWord) | Wake-word candidate, English limitations and model license review |
| REF-10 | [Piper TTS](https://github.com/OHF-Voice/piper1-gpl) | Local TTS candidate, GPL project |
| REF-11 | [Piper voices](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md) | Indonesian voice availability; model cards required |
| REF-12 | [Piper licensing](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/LICENSING.md) | Separate voice licensing and distribution obligations |
| REF-13 | [SQLite FTS5](https://www.sqlite.org/fts5.html) | Local lexical retrieval |
| REF-14 | [SQLite WAL](https://www.sqlite.org/wal.html) | Local concurrency and WAL constraints |
| REF-15 | [SQLite backup API](https://sqlite.org/backup.html) | Consistent snapshots and restore |
| REF-16 | [Tauri capabilities](https://v2.tauri.app/security/capabilities/) | Native permission boundaries; explicit command allowlisting |
| REF-17 | [Windows UI Automation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview) | Semantic desktop interaction |
| REF-18 | [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt) | IoT integration option |
| REF-19 | [Home Assistant REST API docs source](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/api/rest.md) | State and service integration |
| REF-20 | [Tailscale access control](https://tailscale.com/docs/features/access-control) | Private remote access candidate; explicit policy verification |

References checked via available public search results on 25 November 2026. These establish candidate capability, not compatibility, security assurance, performance or license clearance for a particular release. Verify exact upstream versions, license texts, dependencies, model cards, hashes, OS support and pricing/terms in R0. Other candidate components (Python/FastAPI/Pydantic, VAD, embedding, OCR, parser, VPN implementation) require their own official documentation and license review at selection. No claim of using the latest model. No paid standard text reproduced.

## 3. Required R0 evidence
Hardware inventory; benchmark raw metrics and corpus; selected model manifests; dependency lock and SBOM; license and distribution assessment; proof offline/no egress; model and adapter compatibility matrix; updated ADRs and RTM. Store evidence locally and redact private data before sharing.

## v0.2.0 technical additions
- [Motion for React layout animation](https://motion.dev/docs/react-layout-animations): shared layout and component choreography.
- [Motion reduced motion](https://motion.dev/docs/react-use-reduced-motion): adaptive motion and accessibility.
- [Tauri WebView versions](https://v2.tauri.app/reference/webview-versions/): Windows WebView2 runtime behavior; validate installed version.
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md): adapter API candidate; test exact versions and capabilities, disable built-in tool execution.
- [Ollama API documentation](https://docs.ollama.com/api): second local adapter candidate; exact endpoints/version/license and conformance remain R0 verification items. No claim of benchmarking or full API compatibility.
