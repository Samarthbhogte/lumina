"""First-line screen for prompt-injection attempts in user questions.

This is a cheap heuristic, not the main defence: the system prompt also tells the
model to treat document text and questions as data. The patterns are deliberately
narrow so ordinary compliance questions ("Can a manager override consent?") pass.
"""

import re

_PATTERNS = [
    (
        r"\b(ignore|disregard|forget|override)\b.{0,30}"
        r"\b(previous|prior|above|earlier|all|your|the system)\b.{0,20}"
        r"\b(instructions?|prompts?|rules|directions|guidelines)\b"
    ),
    r"\byou are (now|no longer)\b",
    r"\bfrom now on,? you\b",
    (
        r"\b(act|behave|pretend|roleplay) (as|like|to be)\b.{0,25}"
        r"\b(unfiltered|unrestricted|uncensored|evil|jailbroken|dan|developer mode)\b"
    ),
    r"\bjail ?break",
    r"\b(dan|developer) mode\b",
    r"\b(reveal|print|show|repeat|output|leak)\b.{0,20}\b(system prompt|your (instructions|prompt|rules))\b",
    r"<\s*/?\s*(system|assistant)\s*>",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE | re.DOTALL)


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))
