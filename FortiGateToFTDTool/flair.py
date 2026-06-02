"""
Flair: phrase pools for action outcomes.

Returns a formatted line like:
    [OK] Yeeted into the void: net-obj-foo
    [SKIP] Already gone, sweet prince: legacy-rule
    [FAIL] Refused to die: stubborn-route - 503 Service Unavailable

The bracket tag (`[OK] | [SKIP] | [FAIL]`) is preserved verbatim because
JSON reports, exit-code logic, and grep-based log scraping depend on it.
The flavor text is the message body that follows.

Phrase pools are keyed by (action, outcome). Unknown keys fall back to a
generic pool so callers never crash on a typo.
"""

import random
from typing import Optional

# (action, outcome) -> list of phrases
_PHRASES: dict = {
    # ---- create ----
    ("create", "OK"): [
        "Welcomed to the family",
        "Born this way",
        "Brought into existence",
        "Pushed across the finish line",
        "Hatched successfully",
        "It's alive",
    ],
    ("create", "SKIP"): [
        "Already on the guest list",
        "Been there, done that",
        "Déjà vu detected",
        "Twin already exists",
    ],
    ("create", "FAIL"): [
        "Refused entry at the door",
        "Bounced",
        "Returned to sender",
        "Did not stick the landing",
    ],

    # ---- delete ----
    ("delete", "OK"): [
        "Thrown in the trash",
        "Destroyed",
        "Sent to the shadow realm",
        "Yeeted into the void",
        "Goodbye, sweet prince",
        "Erased from history",
        "Returned to dust",
    ],
    ("delete", "SKIP"): [
        "Already gone",
        "Nothing to see here",
        "Ghost - already departed",
        "Beat us to it",
    ],
    ("delete", "FAIL"): [
        "Refuses to die",
        "Clinging to life",
        "Held on for dear life",
        "Still kicking, somehow",
    ],

    # ---- convert ----
    ("convert", "OK"): [
        "Translated faithfully",
        "Successfully reincarnated",
        "Reborn in a new format",
        "Crossed the language barrier",
    ],
    ("convert", "SKIP"): [
        "Lost in translation",
        "Doesn't speak the language",
        "Untranslatable, moving on",
    ],
    ("convert", "FAIL"): [
        "Garbled in transit",
        "Babel fish malfunction",
        "Translator threw up its hands",
    ],

    # ---- update ----
    ("update", "OK"): [
        "Glow-up complete",
        "Freshly remodeled",
        "Brought up to code",
        "Patched and polished",
    ],
    ("update", "SKIP"): [
        "Already shiny",
        "No notes",
        "Looks good as-is",
    ],
    ("update", "FAIL"): [
        "Renovation denied",
        "Makeover refused",
        "Still rough around the edges",
    ],

    # ---- auth ----
    ("auth", "OK"): [
        "Secret handshake accepted",
        "You're on the list",
        "Bouncer waved you through",
    ],
    ("auth", "FAIL"): [
        "Bouncer said no",
        "Wrong password, bub",
        "Not on the list",
    ],

    # ---- validate ----
    ("validate", "OK"): [
        "All systems nominal",
        "Looking sharp",
        "Vibes check passed",
        "Green across the board",
    ],
    ("validate", "FAIL"): [
        "Vibes check failed",
        "Something smells off",
        "Red flags everywhere",
    ],

    # ---- deploy ----
    ("deploy", "OK"): [
        "Shipped it",
        "Live in production",
        "Rolling thunder",
    ],
    ("deploy", "FAIL"): [
        "Deployment ate the floor",
        "Did not ship it",
        "Rollback inbound",
    ],

    # ---- report (writing JSON reports, logs, etc.) ----
    ("report", "OK"): [
        "Report filed",
        "Receipts saved",
        "On the record",
    ],
    ("report", "FAIL"): [
        "Couldn't get it on paper",
        "Pen ran out of ink",
    ],
}

# Generic fallbacks if (action, outcome) isn't in the table
_GENERIC: dict = {
    "OK":   ["Done", "Handled", "Crushed it"],
    "SKIP": ["Skipped", "Passed on this one"],
    "FAIL": ["Faceplanted", "No dice", "Nope"],
}


def phrase(action: str, outcome: str) -> str:
    """Return a random phrase for (action, outcome). Falls back to a generic pool."""
    pool = _PHRASES.get((action, outcome))
    if not pool:
        pool = _GENERIC.get(outcome, ["Done"])
    return random.choice(pool)


def flair(action: str, outcome: str, subject: str = "", detail: Optional[str] = None) -> str:
    """
    Build a flair-tagged line.

    Examples:
        flair("delete", "OK", "net-obj-foo")
            -> "[OK] Yeeted into the void: net-obj-foo"
        flair("create", "FAIL", "rule-42", detail="422 duplicate name")
            -> "[FAIL] Bounced: rule-42 - 422 duplicate name"
        flair("auth", "OK")
            -> "[OK] Secret handshake accepted"
    """
    outcome = outcome.upper()
    tag = f"[{outcome}]"
    msg = phrase(action, outcome)
    parts = [tag, msg]
    out = " ".join(parts)
    if subject:
        out = f"{out}: {subject}"
    if detail:
        out = f"{out} - {detail}"
    return out
