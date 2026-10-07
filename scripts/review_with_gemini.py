"""External review of the last commit by Gemini. Prints concerns only — it never edits or commits anything;
every concern is verified with evidence and tests before any change (see docs/personal_ledger_design.md workflow).

Setup (Ahmed, once): create a key at https://aistudio.google.com, add GEMINI_API_KEY=... to C:\\Projects\\EGX\\.env.
Model: GEMINI_MODEL in .env, no default in code (models get retired: on 2026-10-07 gemini-2.5-pro/flash were closed
to new users and the free tier gave 0 requests on 3.1-pro; gemini-3.1-flash-lite worked).
Run:   python scripts/review_with_gemini.py [--commit REF] [--dry-run]
Privacy: the diff is filtered so .env, databases, market data, logs, Telegram sessions and the personal ledger's
private files are never sent. Free-tier prompts may be used by Google to improve its products.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_DIFF_CHARS = 200_000
MAX_CONTEXT_CHARS = 40_000
# Never sent: secrets, databases, data, logs, sessions, personal ledger files, binary/report outputs.
EXCLUDE = [":(exclude).env*", ":(exclude)*.db", ":(exclude)*.db-*", ":(exclude)data", ":(exclude)data_*",
           ":(exclude)logs", ":(exclude)reports", ":(exclude)*.session*", ":(exclude)personal_journal/prices",
           ":(exclude)personal_journal/statements", ":(exclude)*.xlsx", ":(exclude)*.pdf", ":(exclude)*.png"]

PROMPT = """You are a strict, sceptical code reviewer for an Egyptian stock-market (EGX) trading/backtest system.
Your job is to find problems, not to approve. Do not summarise the change and do not praise it.

Look especially for: look-ahead bias (using data not known at decision time), fills at prices a bar never traded,
fee/tax/slippage mistakes, double counting of dividends or corporate actions, silent data loss, tests that cannot
fail or do not test what they claim, behaviour that contradicts the known issues below, secrets or personal data.

Output ONLY a numbered list. Each item: [HIGH|MEDIUM|LOW] file:line — the problem — concrete evidence from the diff —
a minimal way to reproduce or check it. If you are not sure, say UNSURE and why. If you find nothing, output exactly
"NO CONCERNS" — but only after checking every point above.

=== KNOWN_ISSUES.md (project context, may be truncated) ===
{context}

=== DIFF of {ref} ===
{diff}
"""


def commit_diff(ref: str) -> str:
    parent = f"{ref}^1"  # first parent: for a merge commit this is everything the merge brought in
    out = subprocess.run(["git", "diff", "--no-color", parent, ref, "--", ".", *EXCLUDE], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    if len(out) > MAX_DIFF_CHARS:
        out = out[:MAX_DIFF_CHARS] + f"\n[... diff truncated at {MAX_DIFF_CHARS} characters ...]"
    return out


def build_prompt(ref: str) -> str:
    context = (ROOT / "KNOWN_ISSUES.md").read_text(encoding="utf-8")[:MAX_CONTEXT_CHARS]
    return PROMPT.format(context=context, ref=ref, diff=commit_diff(ref))


def review(prompt: str, key: str, model: str) -> str:
    r = requests.post(URL.format(model=model), headers={"x-goog-api-key": key},
                      json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=300)
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--dry-run", action="store_true", help="show what would be sent; no API call, no key needed")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    model = os.getenv("GEMINI_MODEL", "").strip()
    if not model:
        print("GEMINI_MODEL is not set: add e.g. GEMINI_MODEL=gemini-3.1-flash-lite to .env.", file=sys.stderr)
        return 2
    prompt = build_prompt(args.commit)
    if args.dry_run:
        print(f"model={model} ref={args.commit} prompt_chars={len(prompt)}\nexcluded: {', '.join(EXCLUDE)}")
        return 0
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY is not set: add it to .env (create it at https://aistudio.google.com).", file=sys.stderr)
        return 2
    print(review(prompt, key, model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
