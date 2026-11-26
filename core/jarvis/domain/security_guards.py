"""Pure Security Guards: Anti-SSRF IP/URL Validator, Private-Query Detector & Screen Secret Redactor (B12, B13, T05, FR-SCR-04)."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

_CGNAT_NET = ipaddress.IPv4Network("100.64.0.0/10")

_FORBIDDEN_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.azure.internal",
        "instance-data",
    }
)

_BLOCKED_SCREEN_PROCESSES: frozenset[str] = frozenset(
    {
        "keepass.exe",
        "keepassxc.exe",
        "1password.exe",
        "bitwarden.exe",
        "lastpass.exe",
        "consent.exe",
        "logonui.exe",
        "credentialuibroker.exe",
    }
)

_BLOCKED_WINDOW_TITLE_RE = re.compile(
    r"\b(?:keepass|1password|bitwarden|lastpass|password\s+manager|credential\s+manager|user\s+account\s+control)\b",
    re.IGNORECASE,
)

# High-precision / high-recall secret redaction rules for screen UIA/OCR (FR-SCR-04)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "pem_private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._\-~+/]{10,}=*", re.IGNORECASE)),
    ("openai_or_api_key", re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b")),
    (
        "env_secret_assignment",
        re.compile(
            r"(?im)^(\s*(?:[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY|TOKEN|PRIVATE_?KEY|AUTH_?TOKEN|DATABASE_URL))\s*[:=]\s*)([^\s'\"#]+|'[^']*'|\"[^\"]*\")"
        ),
    ),
)

_PRIVATE_QUERY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("nik_or_national_id", re.compile(r"\b\d{16}\b")),
    ("api_token", re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{12,}|ghp_[A-Za-z0-9]{16,}|Bearer\s+\S{10,})\b", re.I)),
    ("local_file_path", re.compile(r"(?:[A-Za-z]:\\[^\s]+|/(?:Users|home)/[^\s]+)")),
)


def _try_parse_obfuscated_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Detect decimal (2130706433), hex (0x7f000001), octal (0177.0.0.1), and short IPv4 forms."""
    if not host:
        return None
    # Pure single integer (decimal or hex)
    if re.fullmatch(r"(?:0x[0-9a-f]+|\d+)", host, re.IGNORECASE):
        try:
            val = int(host, 0)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            return None
    # Dotted numeric forms with octal/hex/shortened octets (e.g. 0177.0.0.1 or 127.1)
    parts = host.split(".")
    if 2 <= len(parts) <= 4 and all(re.fullmatch(r"(?:0x[0-9a-f]+|0[0-7]+|\d+)", p, re.I) for p in parts):
        nums: list[int] = []
        for p in parts:
            try:
                if p.lower().startswith("0x"):
                    nums.append(int(p, 16))
                elif len(p) > 1 and p.startswith("0"):
                    nums.append(int(p, 8))
                else:
                    nums.append(int(p, 10))
            except ValueError:
                return None
        if len(nums) == 4 and all(0 <= n <= 255 for n in nums):
            return ipaddress.IPv4Address((nums[0] << 24) | (nums[1] << 16) | (nums[2] << 8) | nums[3])
        if len(nums) == 3 and nums[0] <= 255 and nums[1] <= 255 and nums[2] <= 0xFFFF:
            return ipaddress.IPv4Address((nums[0] << 24) | (nums[1] << 16) | nums[2])
        if len(nums) == 2 and nums[0] <= 255 and nums[1] <= 0xFFFFFF:
            return ipaddress.IPv4Address((nums[0] << 24) | nums[1])
    return None


def is_forbidden_ip(ip_str: str) -> bool:
    """Return True for any loopback, RFC1918, CGNAT, link-local/IMDS, multicast, or IPv4-mapped private IP."""
    cleaned = ip_str.strip().strip("[]").split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        obf = _try_parse_obfuscated_ipv4(cleaned)
        if obf is None:
            return True
        addr = obf

    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped

    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return True
    return isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT_NET


def validate_outbound_url_syntax(
    raw_url: str, *, require_https: bool = False
) -> tuple[str, str, int]:
    """Validate URL scheme, disallow userinfo & obfuscated/metadata hostnames before DNS lookup (T05)."""
    parsed = urlparse(raw_url.strip())
    scheme = parsed.scheme.lower()
    allowed_schemes = ("https",) if require_https else ("https", "http")
    if scheme not in allowed_schemes:
        raise ValueError(f"SSRF_BLOCKED_PROTOCOL: scheme '{scheme}' is prohibited.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("SSRF_BLOCKED_USERINFO: embedded URL credentials are prohibited.")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("SSRF_INVALID_HOST: empty hostname.")
    if host in _FORBIDDEN_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError(f"SSRF_FORBIDDEN_HOST: '{host}' is blocked.")

    # Direct IP or obfuscated IP literal check
    obf = _try_parse_obfuscated_ipv4(host)
    if obf is not None and is_forbidden_ip(str(obf)):
        raise ValueError(f"SSRF_FORBIDDEN_DESTINATION_IP: obfuscated IP '{host}' resolved to {obf}.")
    try:
        ipaddress.ip_address(host.strip("[]"))
        if is_forbidden_ip(host):
            raise ValueError(f"SSRF_FORBIDDEN_DESTINATION_IP: '{host}' is non-global.")
    except ValueError as exc:
        if "SSRF_FORBIDDEN" in str(exc):
            raise

    port = parsed.port or (443 if scheme == "https" else 80)
    if port not in (80, 443):
        raise ValueError(f"SSRF_BLOCKED_PORT: port {port} is not an allowed standard web port.")
    return (scheme, host, port)


def detect_private_indicators_in_query(query: str) -> tuple[str, ...]:
    """Identify potential private/PII/secret indicators in outbound web search queries (FR-WEB-01)."""
    found: list[str] = []
    for label, pattern in _PRIVATE_QUERY_PATTERNS:
        if pattern.search(query):
            found.append(label)
    return tuple(found)


def redact_screen_secrets(raw_text: str) -> tuple[str, int]:
    """Redact credentials, API tokens, JWTs, private keys, and .env secrets before LLM context (FR-SCR-04)."""
    text = raw_text
    total_redactions = 0
    for name, pattern in _SECRET_PATTERNS:
        if name == "env_secret_assignment":
            text, count = pattern.subn(r"\1[REDACTED]", text)
        else:
            text, count = pattern.subn("[REDACTED]", text)
        total_redactions += count
    return (text, total_redactions)


def is_blocked_screen_window(
    *,
    window_title: str,
    process_name: str,
    is_elevated_uac: bool = False,
    has_focused_password_field: bool = False,
) -> tuple[bool, str]:
    """Refuse screen capture/UIA on password managers, UAC admin windows, and password inputs (FR-SCR-02)."""
    if is_elevated_uac:
        return (True, "Elevated UAC/administrator windows are blocked from screen capture.")
    if has_focused_password_field:
        return (True, "Focused password input field detected; screen context capture refused.")
    if process_name.strip().lower() in _BLOCKED_SCREEN_PROCESSES:
        return (True, f"Protected process '{process_name}' is blocked from screen capture.")
    if _BLOCKED_WINDOW_TITLE_RE.search(window_title):
        return (True, f"Protected window '{window_title}' is blocked from screen capture.")
    return (False, "ok")
