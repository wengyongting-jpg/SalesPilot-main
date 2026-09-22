# -*- coding: utf-8 -*-
"""Interactive model setup: paste a key, get a working `.env`.

Run it with `py -3 -m backend --configure`. It does four things in order, and stops
at the first one that fails with an explanation of what to try next:

    1. takes the key without echoing it or leaving it in shell history
    2. finds which endpoint that key actually belongs to
    3. reads the real model list from that endpoint, rather than guessing a name
    4. sends one real chat completion to prove the whole path, then writes `.env`

Step 3 is the reason this exists rather than a README paragraph. `GET /models` turns
"which model name does this provider expect" from a guessing game into a list, and a
wrong model name is the single most common way this configuration fails - it arrives
as a 404 that looks exactly like a wrong base URL.

**On sending the key to more than one endpoint.** Discovery means offering the
credential to a candidate to see whether it is accepted, so it is opt-in and named as
such. Every endpoint in `KNOWN_ENDPOINTS` is a vendor's own first-party API or a
service on this machine - there is no relay or proxy in the list, because a key
belonging to one provider should never be handed to a third party that merely
forwards to it.

Standard library only, deliberately. This is the command somebody runs when nothing
works yet, so it must not depend on the agent framework being installed.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path
from typing import Optional

from . import config
from .providers import ProviderSpec, probe, resolve
from .providers.probe import models as list_models

WIDTH = 78
RULE = "-" * WIDTH

# Vendor-operated endpoints and local servers only. OpenAI first, because that is the
# protocol everything here speaks and the most likely answer.
KNOWN_ENDPOINTS: list[tuple[str, str]] = [
    ("OpenAI", "https://api.openai.com/v1"),
    ("DeepSeek", "https://api.deepseek.com/v1"),
    ("Moonshot / Kimi", "https://api.moonshot.cn/v1"),
    ("Zhipu / GLM", "https://open.bigmodel.cn/api/paas/v4"),
    ("Alibaba DashScope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("SiliconFlow", "https://api.siliconflow.cn/v1"),
    ("Groq", "https://api.groq.com/openai/v1"),
    ("Together", "https://api.together.xyz/v1"),
    ("OpenRouter", "https://openrouter.ai/api/v1"),
    ("Ollama (this machine)", "http://127.0.0.1:11434/v1"),
    ("LM Studio (this machine)", "http://127.0.0.1:1234/v1"),
]

# Preferred when an endpoint offers hundreds of models and we need a sensible default
# to put at the top of the list. Substring match, cheapest-capable first.
PREFERRED = (
    "gpt-4o-mini", "gpt-4.1-mini", "gpt-4o", "gpt-4.1",
    "deepseek-chat", "moonshot-v1-8k", "glm-4-flash", "qwen-plus",
    "llama-3.3-70b", "llama3",
)

# Model families that cannot serve a chat completion. Pushed to the bottom rather than
# hidden: the filter is a guess, and hiding a name the user was looking for is worse
# than listing one they will not pick. OpenAI alone returns dozens of these.
NOT_CHAT = (
    "embedding", "whisper", "tts", "dall-e", "moderation", "rerank",
    "audio", "image", "transcribe", "realtime", "search", "codex",
)

MANAGED_KEYS = (
    "SALESPILOT_LLM",
    "SALESPILOT_LLM_API_KEY",
    "SALESPILOT_LLM_MODEL",
    "SALESPILOT_LLM_BASE_URL",
)


def run(argv: Optional[list[str]] = None) -> int:
    try:
        return _run()
    except _Cancelled:
        print("\n  Cancelled. .env was not changed.")
        return 1


def _run() -> int:
    print(RULE)
    print("  SalesPilot - model setup")
    print(RULE)
    print("  Nothing here is required. With no model the backend still runs its")
    print("  offline path end to end. This only turns the model path on.")
    print()

    key = _ask_for_key()
    if key is None:
        return _write_offline()

    candidates = _ask_which_endpoints()
    if not candidates:
        print("\n  Nothing to try. Stopping without changing .env.")
        return 1

    found = _discover(key, candidates)
    if found is None:
        print()
        print("  No endpoint accepted that key.")
        print("  Things worth checking, in the order they usually go wrong:")
        print("    - the key belongs to a provider that is not in the list above;")
        print("      re-run and choose the custom option to type its base URL")
        print("    - the base URL needs, or must not have, a /v1 suffix")
        print("    - the key is expired, or the account is out of quota")
        print("    - a proxy or firewall is intercepting HTTPS")
        print("\n  .env was left alone. The offline path still works:")
        print("      py -3 -m backend --demo")
        return 1

    base_url, available, label = found
    model_name = _ask_which_model(available)
    if not model_name:
        print("\n  No model chosen. Stopping without changing .env.")
        return 1

    spec = resolve(
        provider="gateway", api_key=key, base_url=base_url, model_name=model_name
    )
    print(f"\n  Verifying {model_name} at {base_url} ...")
    result = probe(spec, timeout=30.0)
    print(f"  {result.summary}")
    if not result.reachable:
        print("\n  The endpoint answered the model list but refused a completion.")
        print("  That usually means this model is not enabled for the account.")
        if not _ask_yes_no("  Write .env anyway?", default=False):
            print("  .env left alone.")
            return 1
    else:
        print(f"  The model replied: {result.model_reply!r}")

    _write_env(
        {
            "SALESPILOT_LLM": "gateway",
            "SALESPILOT_LLM_API_KEY": key,
            "SALESPILOT_LLM_MODEL": model_name,
            "SALESPILOT_LLM_BASE_URL": base_url,
        }
    )
    print(f"\n  Written to {config.ENV_FILE}")
    print(f"    provider   gateway ({label})")
    print(f"    base URL   {base_url}")
    print(f"    model      {model_name}")
    print(f"    key        {config.redact(key)}")
    print("\n  .env is git-ignored, so the key is not committed.")
    print("\n  Next:")
    print("      py -3 -m backend --probe          confirm it still answers")
    print("      py -3 -m backend --demo           the whole pipeline, narrated")
    print("      py -3 -m backend --serve --seed   the API on port 8000")
    return 0


# ---- Input ---------------------------------------------------------------


def _ask_for_key() -> Optional[str]:
    """Read the key without echoing it.

    `getpass` rather than `input` so the key does not end up on screen during a
    screen share, and typing it here rather than on a command line so it does not end
    up in shell history either.
    """
    existing = config.LLM_API_KEY
    if existing:
        print(f"  .env already holds a key: {config.redact(existing)}")
        if _ask_yes_no("  Keep it?", default=True):
            return existing

    print("\n  Paste the API key. It is not echoed. Leave blank to stay offline.")
    try:
        key = getpass.getpass("  key: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise _Cancelled from None
    if not key:
        return None

    # Caught here rather than as a 401 three steps later, where the cause is much
    # less obvious.
    if key != key.strip() or " " in key:
        print("  Note: that key contains a space. A truncated paste looks like this.")
    print(f"  Read {config.redact(key)}")
    return key


def _ask_which_endpoints() -> list[tuple[str, str]]:
    print(f"\n{RULE}")
    print("  Which endpoint does the key belong to?")
    print(RULE)
    for index, (label, url) in enumerate(KNOWN_ENDPOINTS, start=1):
        print(f"   {index:>2}. {label:<26}{url}")
    print("    c. something else - type the base URL")
    print("    a. try all of the above, stopping at the first that accepts the key")
    print()

    choice = _ask("  choice [1]: ", default="1").strip().lower()

    if choice == "c":
        url = _ask("  base URL (include /v1 if the provider expects it): ").strip()
        return [("custom", url.rstrip("/"))] if url else []

    if choice == "a":
        print()
        print("  This offers the key to each endpoint in turn until one accepts it.")
        print("  Every one of them is a vendor's own API or a server on this machine,")
        print("  but it does mean the key is sent to more than one place.")
        if not _ask_yes_no("  Go ahead?", default=False):
            return []
        return list(KNOWN_ENDPOINTS)

    if choice.isdigit() and 1 <= int(choice) <= len(KNOWN_ENDPOINTS):
        return [KNOWN_ENDPOINTS[int(choice) - 1]]

    print("  Not a choice on the list.")
    return []


def _ask_which_model(available: list[str]) -> str:
    if not available:
        print("\n  The endpoint does not publish a model list, so the name has to be")
        print("  typed. Check the provider's documentation for the exact spelling.")
        return _ask(f"  model [{config.LLM_MODEL}]: ", default=config.LLM_MODEL).strip()

    ordered = _order_models(available)
    shown = ordered[:20]
    print(f"\n{RULE}")
    print(f"  {len(available)} models available. Pick one:")
    print(RULE)
    for index, name in enumerate(shown, start=1):
        marker = "  <- suggested" if index == 1 else ""
        print(f"   {index:>2}. {name}{marker}")
    if len(ordered) > len(shown):
        print(f"       ... and {len(ordered) - len(shown)} more")
        print("    l. list every one")
    print("    t. type a name instead")
    print()

    choice = _ask("  choice [1]: ", default="1").strip().lower()
    if choice == "l":
        for name in ordered:
            print(f"      {name}")
        choice = _ask("  choice [1]: ", default="1").strip().lower()
    if choice == "t":
        return _ask("  model: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(shown):
        return shown[int(choice) - 1]
    # A name typed at the numeric prompt is an obvious intent; honour it rather than
    # making them start again.
    return choice if choice in available else (shown[0] if shown else "")


def _order_models(available: list[str]) -> list[str]:
    """Preferred models first, then everything else alphabetically.

    A provider can return several hundred names, most of them embeddings, moderation
    or audio models that would fail as a chat model. Surfacing a known-good chat model
    first is the difference between a two-second choice and a scroll.
    """
    ranked: list[str] = []
    for wanted in PREFERRED:
        for name in available:
            # The preference match is a substring, so `gpt-4o` also hits
            # `gpt-4o-realtime-preview`, which cannot serve an ordinary chat
            # completion. Screen the family out here as well, or the suggestion at the
            # top of the list is a model that fails on first use.
            if wanted in name and name not in ranked and not _is_not_chat(name):
                ranked.append(name)

    rest = [name for name in available if name not in ranked]
    chat = [name for name in rest if not _is_not_chat(name)]
    other = [name for name in rest if _is_not_chat(name)]
    return ranked + chat + other


def _is_not_chat(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in NOT_CHAT)


class _Cancelled(Exception):
    """Ctrl-C or end of input. Raised rather than defaulted.

    Returning the default on EOF made the script print "Cancelled." and then carry on
    with choice 1, which is the opposite of what either signal means. An interrupted
    setup must leave `.env` alone.
    """


def _ask(prompt: str, *, default: str = "") -> str:
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise _Cancelled from None
    return answer or default


def _ask_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = _ask(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


# ---- Discovery -----------------------------------------------------------


def _discover(
    key: str, candidates: list[tuple[str, str]]
) -> Optional[tuple[str, list[str], str]]:
    """Find the first endpoint that accepts the key. Returns `(url, models, label)`.

    Uses `GET /models` rather than a completion: it costs no tokens, and an endpoint
    that lists models has proved both the URL and the credential at once.
    """
    print(f"\n{RULE}")
    print("  Looking for an endpoint that accepts the key")
    print(RULE)

    fallbacks: list[tuple[str, str]] = []
    for label, url in candidates:
        print(f"  {label:<26}", end="", flush=True)
        spec = resolve(
            provider="gateway", api_key=key, base_url=url, model_name="probe"
        )
        available, detail = list_models(spec, timeout=12.0)
        if available:
            print(f"OK - {detail}")
            return url, available, label
        # No list is not the same as no endpoint. Remember it and fall back to a real
        # completion attempt if nothing better turns up.
        if "not with a model list" in detail:
            print("reachable, but publishes no model list")
            fallbacks.append((label, url))
        else:
            print(_short(detail))

    for label, url in fallbacks:
        print(f"\n  Retrying {label} with a real completion ...")
        spec = resolve(
            provider="gateway", api_key=key, base_url=url,
            model_name=config.LLM_MODEL,
        )
        result = probe(spec, timeout=20.0)
        if result.reachable:
            print(f"  {result.summary}")
            return url, [], label
        print(f"  {_short(result.detail)}")

    return None


def _short(detail: str) -> str:
    """One line. A probe detail carries a body excerpt that is useful in a report and
    noise in a progress list."""
    text = detail.split("[")[0].strip() or detail
    return text[:60]


# ---- Writing -------------------------------------------------------------


def _write_offline() -> int:
    print("\n  No key given, so the offline path stays selected.")
    _write_env({"SALESPILOT_LLM": "offline", "SALESPILOT_LLM_API_KEY": ""})
    print(f"  {config.ENV_FILE} updated: SALESPILOT_LLM=offline")
    print("\n  Everything still works:")
    print("      py -3 -m backend --demo")
    return 0


def _write_env(settings: dict[str, str]) -> None:
    """Update the managed keys in `.env`, leaving every other line as it was.

    Rewritten in place rather than regenerated from the template, because the file is
    the user's: comments, ordering and any setting this script does not manage have to
    survive. Only the four keys in `MANAGED_KEYS` are ever touched.
    """
    path: Path = config.ENV_FILE
    lines = (
        path.read_text(encoding="utf-8").splitlines()
        if path.exists()
        else _template_lines()
    )

    remaining = dict(settings)
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name in remaining:
                updated.append(f"{name}={remaining.pop(name)}")
                continue
        updated.append(line)

    for name, value in remaining.items():
        updated.append(f"{name}={value}")

    # Written with an explicit UTF-8 encoding and a trailing newline, because a file
    # the loader reads must not depend on the console code page.
    path.write_text("\n".join(updated).rstrip("\n") + "\n", encoding="utf-8")


def _template_lines() -> list[str]:
    example = config.REPO_ROOT / ".env.example"
    if example.exists():
        return example.read_text(encoding="utf-8").splitlines()
    return ["# SalesPilot backend - local configuration."]


if __name__ == "__main__":
    sys.exit(run())
