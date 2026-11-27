"""Pure-domain Application Catalog models, Tier-3 LOLBin denylist & bilingual entity resolver (B09, DEC-032, NFR-16).

Strictly OS-independent (zero Win32/ctypes/winreg imports) so domain logic remains 100% portable and testable.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

AppActivationKind = Literal["exe", "aumid"]
AppTrustClass = Literal["tier1_ordinary", "tier2_custom", "tier3_prohibited"]

# Hard Tier-3 prohibited binaries: shells, interpreters, LOLBins, registry/disk/privilege tools (DEC-012)
TIER3_PROHIBITED_BINARIES: frozenset[str] = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "powershell_ise.exe",
        "wscript.exe",
        "cscript.exe",
        "mshta.exe",
        "regedit.exe",
        "reg.exe",
        "diskpart.exe",
        "format.com",
        "bcdedit.exe",
        "vssadmin.exe",
        "wbadmin.exe",
        "cipher.exe",
        "rundll32.exe",
        "regsvr32.exe",
        "certutil.exe",
        "bitsadmin.exe",
        "msiexec.exe",
        "schtasks.exe",
        "sc.exe",
        "net.exe",
        "net1.exe",
        "netsh.exe",
        "takeown.exe",
        "icacls.exe",
        "attrib.exe",
        "taskkill.exe",
        "shutdown.exe",
        "runas.exe",
        "wsl.exe",
        "bash.exe",
        "wt.exe",
        "psexec.exe",
        "psexec64.exe",
        "mmc.exe",
        "robocopy.exe",
        "del.exe",
        "erase.exe",
        "rd.exe",
        "rmdir.exe",
        "sdelete.exe",
        "sdelete64.exe",
    }
)

_TIER3_PROHIBITED_QUERY_TOKENS: frozenset[str] = frozenset(
    {
        "cmd",
        "cmd.exe",
        "command prompt",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "windows powershell",
        "windows terminal",
        "terminal",
        "bash",
        "wsl",
        "regedit",
        "registry editor",
        "diskpart",
        "format",
        "mshta",
        "wscript",
        "cscript",
        "rundll32",
        "regsvr32",
        "certutil",
        "bitsadmin",
        "schtasks",
        "taskkill",
        "runas",
        "psexec",
        "shutdown",
        "vssadmin",
        "bcdedit",
        "icacls",
        "takeown",
    }
)

_UNINSTALLER_NAME_RE = re.compile(r"(?:^unins\d*\.exe$|uninstall|uninst|remove_)", re.I)

_DANGEROUS_SHORTCUT_ARG_RE = re.compile(
    r"(?:^|\s)(?:/c|/k|-c|-enc|-encodedcommand|-command|-executionpolicy|bypass)\b"
    r"|\b(?:powershell|pwsh|cmd\.exe|mshta|wscript|cscript|rundll32|regsvr32|certutil|bitsadmin|invoke-expression|\biex\b)\b",
    re.I,
)

_LEADING_FILLER_RE = re.compile(
    r"^(?:aplikasi|program|app|software|perangkat\s+lunak)\s+",
    re.I,
)
_TRAILING_FILLER_RE = re.compile(
    r"\s+(?:dong|ya|please|pls|sekarang|now|saja|aja)$",
    re.I,
)

BILINGUAL_APP_SYNONYMS: dict[str, tuple[str, ...]] = {
    "kalkulator": ("calculator", "calc"),
    "calculator": ("calculator", "calc"),
    "calc": ("calculator", "calc"),
    "catatan": ("notepad",),
    "notepad": ("notepad",),
    "paint": ("paint", "mspaint"),
    "gambar": ("paint", "mspaint"),
    "peramban": ("google chrome", "microsoft edge", "firefox", "brave", "chrome", "edge"),
    "browser": ("google chrome", "microsoft edge", "firefox", "brave", "chrome", "edge"),
    "chrome": ("google chrome", "chrome"),
    "krom": ("google chrome", "chrome"),
    "google chrome": ("google chrome", "chrome"),
    "edge": ("microsoft edge", "edge"),
    "microsoft edge": ("microsoft edge", "edge"),
    "firefox": ("mozilla firefox", "firefox"),
    "brave": ("brave", "brave browser"),
    "vscode": ("visual studio code", "code"),
    "vs code": ("visual studio code", "code"),
    "koding": ("visual studio code", "code"),
    "penjelajah file": ("file explorer", "windows explorer", "explorer"),
    "file explorer": ("file explorer", "windows explorer", "explorer"),
    "explorer": ("file explorer", "windows explorer", "explorer"),
    "pengaturan": ("settings", "windows settings"),
    "settings": ("settings", "windows settings"),
    "word": ("microsoft word", "word"),
    "excel": ("microsoft excel", "excel"),
    "powerpoint": ("microsoft powerpoint", "powerpoint"),
    "ppt": ("microsoft powerpoint", "powerpoint"),
    "wa": ("whatsapp",),
    "whatsapp": ("whatsapp",),
    "spotify": ("spotify",),
    "musik": ("spotify", "media player"),
    "discord": ("discord",),
    "telegram": ("telegram", "telegram desktop"),
    "slack": ("slack",),
    "notion": ("notion",),
    "obsidian": ("obsidian",),
    "snipping": ("snipping tool",),
    "screenshot": ("snipping tool",),
}


@dataclass(frozen=True)
class ApplicationCatalogEntry:
    app_id: str
    display_name: str
    activation_kind: AppActivationKind
    target: str
    aliases: tuple[str, ...] = ()
    source: str = "catalog"
    trust_class: AppTrustClass = "tier1_ordinary"
    publisher: str = ""
    arguments: str = ""


@dataclass(frozen=True)
class AppLaunchReceipt:
    accepted: bool
    app_id: str
    display_name: str
    activation_kind: AppActivationKind
    pid: int | None
    verification_kind: Literal["os_activation_ack", "disabled", "prohibited", "not_found", "failed"]
    detail: str


@dataclass(frozen=True)
class AppResolutionResult:
    status: Literal["matched", "ambiguous", "not_found", "prohibited"]
    query: str
    matched_entry: ApplicationCatalogEntry | None = None
    candidates: tuple[ApplicationCatalogEntry, ...] = ()
    confidence: float = 0.0
    reason: str = ""


def _extract_basename(raw_target: str) -> str:
    cleaned = raw_target.strip().strip('"').strip("'").replace("\\", "/")
    if not cleaned:
        return ""
    return cleaned.rsplit("/", 1)[-1].casefold()


def is_prohibited_binary_target(target_path: str, arguments: str = "") -> bool:
    """Return True if target executable or shortcut arguments match Tier-3 hard bans (DEC-012)."""
    base = _extract_basename(target_path)
    if not base:
        return True
    if base in TIER3_PROHIBITED_BINARIES:
        return True
    if _UNINSTALLER_NAME_RE.search(base):
        return True
    # Reject script/batch/command file targets directly
    if base.endswith((".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".hta", ".msi", ".reg", ".scr")):
        return True
    return bool(arguments and _DANGEROUS_SHORTCUT_ARG_RE.search(arguments))


def normalize_app_query(raw: str) -> str:
    """Normalize multilingual spoken/typed app names (Unicode NFKC, casefold, boundary punctuation strip)."""
    text = unicodedata.normalize("NFKC", raw).strip().casefold()
    text = re.sub(r"^[\s.,!?;:\"'`()\[\]{}]+", "", text)
    text = re.sub(r"[\s.,!?;:\"'`()\[\]{}]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    text = _LEADING_FILLER_RE.sub("", text).strip()
    text = _TRAILING_FILLER_RE.sub("", text).strip()
    return text


def is_prohibited_app_query(raw_query: str) -> bool:
    """Return True if user query directly names a Tier-3 prohibited shell/LOLBin/uninstaller."""
    norm = normalize_app_query(raw_query)
    if not norm:
        return False
    if norm in _TIER3_PROHIBITED_QUERY_TOKENS or norm in TIER3_PROHIBITED_BINARIES:
        return True
    base = _extract_basename(norm)
    if base in TIER3_PROHIBITED_BINARIES or _UNINSTALLER_NAME_RE.search(norm):
        return True
    tokens = set(re.findall(r"[a-z0-9_.+-]+", norm))
    for banned in ("powershell", "pwsh", "cmd.exe", "regedit", "diskpart", "mshta", "wscript", "cscript", "taskkill", "runas", "psexec"):
        if banned in tokens:
            return True
    return False


class AppEntityResolver:
    """Deterministic bilingual entity resolver with ambiguity disambiguation and Tier-3 guardrails."""

    AMBIGUITY_DELTA: float = 0.12
    MIN_MATCH_SCORE: float = 0.72

    def resolve(
        self,
        raw_query: str,
        catalog: tuple[ApplicationCatalogEntry, ...],
        *,
        user_aliases: dict[str, str] | None = None,
    ) -> AppResolutionResult:
        query = normalize_app_query(raw_query)
        if not query:
            return AppResolutionResult(
                status="not_found",
                query=query,
                reason="Nama aplikasi tidak boleh kosong.",
            )

        if is_prohibited_app_query(query):
            return AppResolutionResult(
                status="prohibited",
                query=query,
                reason=f"Aplikasi '{query}' termasuk kategori Tier-3 yang dilarang keras oleh kebijakan keamanan.",
            )

        # User-defined explicit alias override (cannot bypass Tier-3)
        if user_aliases:
            aliased = user_aliases.get(query)
            if aliased:
                norm_alias = normalize_app_query(aliased)
                if is_prohibited_app_query(norm_alias):
                    return AppResolutionResult(
                        status="prohibited",
                        query=query,
                        reason=f"Alias '{query}' merujuk target Tier-3 terlarang.",
                    )
                query = norm_alias

        expanded_queries: list[str] = [query]
        for syn in BILINGUAL_APP_SYNONYMS.get(query, ()):
            if syn not in expanded_queries:
                expanded_queries.append(syn)

        scored: list[tuple[float, bool, ApplicationCatalogEntry]] = []
        prohibited_hit = False

        for entry in catalog:
            if entry.trust_class == "tier3_prohibited" or (
                entry.activation_kind == "exe"
                and is_prohibited_binary_target(entry.target, entry.arguments)
            ):
                if self._score_entry(expanded_queries, entry)[0] >= 0.90:
                    prohibited_hit = True
                continue
            score, is_exact = self._score_entry(expanded_queries, entry)
            if score >= self.MIN_MATCH_SCORE:
                scored.append((score, is_exact, entry))

        if prohibited_hit and not scored:
            return AppResolutionResult(
                status="prohibited",
                query=query,
                reason=f"Target aplikasi '{query}' dilarang keras (Tier-3).",
            )

        if not scored:
            return AppResolutionResult(
                status="not_found",
                query=query,
                reason=f"Aplikasi '{raw_query.strip()}' tidak ditemukan pada katalog aplikasi terinstal.",
            )

        # Deduplicate by app_id keeping highest score
        best_by_id: dict[str, tuple[float, bool, ApplicationCatalogEntry]] = {}
        for score, is_exact, entry in scored:
            prev = best_by_id.get(entry.app_id)
            if prev is None or (score, is_exact) > (prev[0], prev[1]):
                best_by_id[entry.app_id] = (score, is_exact, entry)

        ranked = sorted(
            best_by_id.values(),
            key=lambda item: (item[0], item[1], -len(item[2].display_name)),
            reverse=True,
        )

        top_score, top_exact, top_entry = ranked[0]
        if len(ranked) >= 2:
            second_score, second_exact, _second_entry = ranked[1]
            # Exact unique full match wins cleanly over fuzzy siblings
            if (
                not (top_exact and not second_exact and top_score >= 0.99)
                and (top_score - second_score) < self.AMBIGUITY_DELTA
            ):
                top_candidates = tuple(item[2] for item in ranked[:3])
                names = ", ".join(c.display_name for c in top_candidates)
                return AppResolutionResult(
                    status="ambiguous",
                    query=query,
                    matched_entry=None,
                    candidates=top_candidates,
                    confidence=round(top_score, 3),
                    reason=f"Permintaan '{raw_query.strip()}' cocok dengan beberapa aplikasi: {names}. Aplikasi mana yang ingin Anda buka?",
                )

        return AppResolutionResult(
            status="matched",
            query=query,
            matched_entry=top_entry,
            candidates=tuple(item[2] for item in ranked[:3]),
            confidence=round(top_score, 3),
            reason=f"Cocok dengan '{top_entry.display_name}'.",
        )

    @staticmethod
    def _score_entry(
        expanded_queries: list[str], entry: ApplicationCatalogEntry
    ) -> tuple[float, bool]:
        labels = [
            normalize_app_query(entry.app_id),
            normalize_app_query(entry.display_name),
            *(normalize_app_query(a) for a in entry.aliases),
        ]
        labels = [lbl for lbl in labels if lbl]
        best = 0.0
        exact_hit = False

        for q_idx, q in enumerate(expanded_queries):
            synonym_penalty = 0.0 if q_idx == 0 else 0.04
            q_tokens = set(re.findall(r"[a-z0-9]+", q))
            for lbl in labels:
                if q == lbl:
                    score = 1.0 - synonym_penalty
                    if score > best:
                        best = score
                        exact_hit = q_idx == 0
                    continue
                # Prefix word boundary match (e.g. "visual studio" -> "visual studio code" & "visual studio 2022")
                if lbl.startswith(f"{q} ") or lbl.endswith(f" {q}"):
                    score = 0.88 - synonym_penalty
                    if score > best:
                        best = score
                elif q in lbl and len(q) >= 4:
                    score = 0.82 - synonym_penalty
                    if score > best:
                        best = score
                else:
                    lbl_tokens = set(re.findall(r"[a-z0-9]+", lbl))
                    if q_tokens and lbl_tokens:
                        overlap = len(q_tokens & lbl_tokens) / max(len(q_tokens), len(lbl_tokens))
                        seq = difflib.SequenceMatcher(None, q, lbl).ratio()
                        score = max(seq, (overlap * 0.65) + (seq * 0.35)) - synonym_penalty
                        if score > best:
                            best = score
        return (best, exact_hit)
