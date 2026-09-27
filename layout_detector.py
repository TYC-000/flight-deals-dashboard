"""Layout preference: user-toggled only (no JS detection).

Streamlit's plain html() can\'t receive postMessage, so we skip viewport detection.
Detect is provided by User-Agent hint via window.navigator at page-load time,
but Streamlit can\'t see that server-side.

UX flow:
  1. Default = "spacious" (works for desktop)
  2. Sidebar toggle lets user pick Compact / Spacious
  3. Choice persists in session_state (per browser session)
  4. We also pre-populate a one-time hint suggesting Compact for mobile
     based on Common User-Agent heuristics.
"""

LAYOUT_VALUES = ("compact", "spacious")

LAYOUT_LABELS = {
    "en": {
        "compact": "Compact (mobile / tablet)",
        "spacious": "Spacious (desktop)",
    },
    "zh": {
        "compact": "精簡 (手機 / 平板)",
        "spacious": "寬鬆 (桌機)",
    },
}

# Mobile UA hints — best-effort only
MOBILE_UA_TOKENS = (
    "iphone", "ipad", "android", "mobile", "ipod",
    "phone", "blackberry", "opera mini", "iemobile",
)


def is_likely_mobile(user_agent: str | None) -> bool:
    """Best-effort UA-based mobile detection (not authoritative)."""
    if not user_agent:
        return False
    ua = user_agent.lower()
    # Tablets: ipad is mobile-like (not desktop)
    return any(token in ua for token in MOBILE_UA_TOKENS)


def layout_options(lang: str = "zh") -> list[str]:
    return [LAYOUT_LABELS[lang][v] for v in LAYOUT_VALUES]
