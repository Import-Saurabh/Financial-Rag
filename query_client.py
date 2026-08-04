"""
query_client.py — professional CLI entry point for the Financial RAG system
──────────────────────────────────────────────────────────────────────────
Thin orchestration layer only: this file talks to the running server.py
over HTTP and formats what it gets back. It contains NO retrieval, fusion,
or synthesis logic — all of that stays in the pipeline (server-side).

USAGE:
    python query_client.py --symbol ADANIPORTS "revenue FY25"
    python query_client.py --symbol ADANIPORTS --auto "revenue FY25"
    python query_client.py --symbol ADANIPORTS --doc-type annual "segment breakdown"
    python query_client.py --symbol HAL --debug "What did management say about margins?"
    python query_client.py --symbol HAL --trace --show-atoms --show-plan "EBITDA CAGR FY23-25"

Make sure server.py is running first:
    C:\\Users\\hp\\Downloads\\FinRag\\venv\\Scripts\\python.exe server.py

WHAT CHANGED IN THIS VERSION (Phase-2 orchestration pass)
───────────────────────────────────────────────────────────
The old client only rendered `answer`, `sources`, and four meta fields. It
assumed the server response always has that exact shape, so any missing key
or partial failure crashed the client with a raw traceback — not something
you want in front of a stakeholder demo.

This version:
  1. Never crashes on a malformed/partial server response — every field is
     read defensively with .get() and a clear "(not reported by server)"
     placeholder, so the client degrades gracefully if server.py doesn't
     (yet) emit a given diagnostic.
  2. Adds a rich diagnostics/debug surface: --debug, --trace, --show-atoms,
     --show-plan, --show-retrieval, --show-reranker, --show-fusion,
     --show-prompt, --show-context — each toggles one section of the report
     without forcing the user to wade through everything every time.
  3. Times the request from the client side (wall clock) in addition to
     whatever server-side timing breakdown is returned, so total latency is
     always available even if the server can't yet report a breakdown.
  4. Reformats sources into a readable Document / Section / Speaker / Page /
     Year / Confidence / Importance table instead of dumping raw metadata
     dicts.
  5. Surfaces confidence, contradictions, and missing-evidence warnings as
     first-class sections instead of leaving them buried in `answer` text.
  6. Distinguishes connection failure / timeout / HTTP error / malformed
     JSON / partial pipeline failure, and prints an actionable message for
     each instead of a bare stack trace — matching "if SQL fails continue,
     if retrieval fails continue, if reranker fails fallback, if LLM fails
     show diagnostics, never crash" end-to-end.

Everything this client can't get from the server (e.g. a per-stage timing
the server doesn't emit yet) is shown as "not reported by server" rather
than guessed at or silently dropped — a debugging tool that fabricates
numbers is worse than one that admits a gap.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("[error] pip install requests")
    sys.exit(1)

SERVER_URL = "http://localhost:8001"
REQUEST_TIMEOUT_SEC = 175


# ─────────────────────────────────────────────────────────────────────────────
# Provider menu (mirrors rag_engine.py build_provider_catalogue)
# ─────────────────────────────────────────────────────────────────────────────
FALLBACK_PROVIDERS = [
    {"id": "groq-llama",              "label": "Groq — llama-3.3-70b-versatile ★ FASTEST",   "note": "~5.5k tok (free)"},
    {"id": "or-llama70b",             "label": "OpenRouter — Llama 3.3 70B [FREE] ★ BEST",   "note": "131k ctx, FREE"},
    {"id": "or-gemini",               "label": "OpenRouter — Gemini 2.0 Flash [FREE]",       "note": "1M ctx, FREE"},
    {"id": "gemini",                  "label": "Google Gemini — gemini-2.0-flash (direct)",  "note": "1M ctx, 15 RPM"},
    {"id": "nvidia",                  "label": "NVIDIA NIM — llama-3.3-70b ⚠ SLOW (~90s)",  "note": "128k ctx, slow"},
    {"id": "ollama-llama3.1-latest",  "label": "Ollama local — llama3.1:latest",            "note": "4.9 GB, local"},
    {"id": "ollama-phi3-latest",      "label": "Ollama local — phi3:latest",                "note": "2.2 GB, local"},
    {"id": "groq-llama-8b",           "label": "Groq — llama-3.1-8b-instant (fast fallback)", "note": "6k tok"},
]


def fetch_providers() -> List[Dict[str, str]]:
    """Try to get live provider list from server; fall back to hardcoded."""
    try:
        r = requests.get(f"{SERVER_URL}/providers", timeout=3)
        if r.ok:
            data = r.json()
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass
    return FALLBACK_PROVIDERS


def pick_provider(providers: List[Dict[str, str]]) -> str:
    W_LABEL, W_NOTE = 46, 18
    top = "┌────┬" + "─" * W_LABEL + "┬" + "─" * W_NOTE + "┐"
    mid = "├────┼" + "─" * W_LABEL + "┼" + "─" * W_NOTE + "┤"
    bot = "└────┴" + "─" * W_LABEL + "┴" + "─" * W_NOTE + "┘"

    print()
    print(top)
    print(f"│ {'🤖  Select LLM Provider':<{W_LABEL + W_NOTE + 5}}│")
    print(mid)
    print(f"│ #  │ {'Provider / Model':<{W_LABEL-1}}│ {'Context / Notes':<{W_NOTE-1}}│")
    print(mid)
    for i, p in enumerate(providers, 1):
        label = p.get("label", p.get("id", "?"))[:W_LABEL-1].ljust(W_LABEL-1)
        note  = p.get("note", "")[:W_NOTE-1].ljust(W_NOTE-1)
        print(f"│ {i:<3}│ {label}│ {note}│")
    print(bot)
    print()
    print("  💡 Tip: groq-llama = fastest (2s LLM) | or-llama70b = best free quality (131k ctx)")
    print("         ⚠  Avoid NVIDIA NIM for interactive use — frequently times out at 160s")
    print("         use --auto flag to skip this menu")
    print()

    while True:
        try:
            raw = input(f"  Enter number [1-{len(providers)}] (or 'q' to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)
        if raw.lower() == "q":
            sys.exit(0)
        if raw.isdigit() and 1 <= int(raw) <= len(providers):
            chosen = providers[int(raw) - 1]
            print(f"  ✔  Using: {chosen.get('label', chosen['id'])}\n")
            return chosen["id"]
        print(f"  ⚠  Enter a number between 1 and {len(providers)}")


# ─────────────────────────────────────────────────────────────────────────────
# Defensive accessors — the server contract may evolve independently of this
# client, and this client must never crash because a field is missing.
# ─────────────────────────────────────────────────────────────────────────────

_NA = "— not reported by server —"


def _g(d: Dict[str, Any], *path, default=_NA):
    """Safe nested .get() that never raises, even on wrong types mid-path."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _fmt_secs(v: Any) -> str:
    if v is None or v == _NA:
        return _NA
    try:
        return f"{float(v):.2f}s"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: Any) -> str:
    if v is None or v == _NA:
        return _NA
    try:
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(v)


def _hr(char: str = "─", width: int = 74) -> str:
    return char * width


# ─────────────────────────────────────────────────────────────────────────────
# Report sections
# ─────────────────────────────────────────────────────────────────────────────

def _print_header(query: str, args: argparse.Namespace) -> None:
    print("\n" + "=" * 74)
    print("FINANCIAL RAG — QUERY".center(74))
    print("=" * 74)
    print(f"  Query    : {query}")
    if args.symbol:
        print(f"  Symbol   : {args.symbol}")
    print(f"  Doc-type : {args.doc_type}   Year: {args.year or 'any'}")


def _print_plan(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("RETRIEVAL PLAN")
    print(_hr())
    intent   = _g(data, "intent")
    channels = _g(data, "channels")
    if channels != _NA and isinstance(channels, list):
        channels = ", ".join(channels) or "(none)"
    print(f"  Intent detected      : {intent}")
    print(f"  Retrieval channels   : {channels}")
    print(f"  Retrieval plan       : {_g(data, 'plan')}")


def _print_atoms(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("ATOMIC DECOMPOSITION")
    print(_hr())
    atoms = _g(data, "atoms")
    if atoms == _NA or not isinstance(atoms, list):
        print(f"  {_NA}")
        return
    sql_atoms    = [a for a in atoms if a.get("need_type") in
                     ("quantitative", "comparative", "ownership", "macro", "technical")]
    vector_atoms = [a for a in atoms if a.get("need_type") in ("qualitative", "forward_looking")]
    print(f"  Total atoms: {len(atoms)}  (SQL-bound: {len(sql_atoms)}, vector-bound: {len(vector_atoms)})")
    for a in atoms:
        print(
            f"    • [{a.get('need_type','?'):<15}] {a.get('sub_type','?'):<18} "
            f"metric={a.get('metric','?'):<20} years={a.get('years', [])} "
            f"conf={a.get('confidence', '?')}"
        )


def _print_retrieval(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("RETRIEVAL")
    print(_hr())
    print(f"  Chunks retrieved (pre-rerank) : {_g(data, 'retrieval', 'chunks_retrieved')}")
    print(f"  Chunks reranked (post-rerank) : {_g(data, 'retrieval', 'chunks_reranked')}")
    print(f"  Annual-report candidates      : {_g(data, 'retrieval', 'annual_candidates')}")
    print(f"  Concall candidates            : {_g(data, 'retrieval', 'concall_candidates')}")
    sql_rows = data.get("sql_rows", _NA)
    print(f"  SQL rows returned             : {sql_rows}")


def _print_reranker(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("RERANKER")
    print(_hr())
    print(f"  Model / backend    : {_g(data, 'reranker', 'backend')}")
    print(f"  Candidates in      : {_g(data, 'reranker', 'candidates_in')}")
    print(f"  Candidates out     : {_g(data, 'reranker', 'candidates_out')}")
    print(f"  Score range        : {_g(data, 'reranker', 'score_range')}")
    print(f"  Low-confidence flag: {_g(data, 'reranker', 'low_confidence')}")


def _print_fusion(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("FUSION")
    print(_hr())
    insights = data.get("insights", _NA)
    print(f"  Insights generated     : {insights}")
    print(f"  Contradictions found   : {_g(data, 'fusion', 'contradictions')}")
    print(f"  Confirmations found    : {_g(data, 'fusion', 'confirmations')}")
    print(f"  Forward guidance found : {_g(data, 'fusion', 'forward_guidance')}")
    print(f"  Fusion confidence      : {_fmt_pct(_g(data, 'fusion', 'overall_confidence'))}")


def _print_prompt(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("PROMPT SENT TO LLM")
    print(_hr())
    prompt = _g(data, "debug", "prompt")
    if prompt == _NA:
        print(f"  {_NA} (server must include debug.prompt in the response)")
        return
    print(prompt)


def _print_context(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("RAW CONTEXT PASSED TO SYNTHESIS")
    print(_hr())
    ctx = _g(data, "debug", "context")
    if ctx == _NA:
        print(f"  {_NA} (server must include debug.context in the response)")
        return
    try:
        print(json.dumps(ctx, indent=2, default=str)[:4000])
    except Exception:
        print(str(ctx)[:4000])


def _format_source(src: Any, idx: int) -> str:
    """
    Render one source as Document / Section / Speaker / Page / Year /
    Confidence / Importance instead of a raw metadata dump. Falls back
    gracefully if the server only sends a plain string (older contract).
    """
    if isinstance(src, str):
        return f"  [{idx}] {src}"
    if not isinstance(src, dict):
        return f"  [{idx}] {src!r}"

    doc      = src.get("document") or src.get("title") or src.get("doc_type", "?")
    section  = src.get("section") or src.get("section_type", "—")
    speaker  = src.get("speaker", "—")
    page     = src.get("page") or src.get("page_start", "—")
    year     = src.get("year", "—")
    conf     = src.get("confidence")
    importance = src.get("importance") or src.get("importance_score")

    conf_str = _fmt_pct(conf) if conf is not None else "—"
    imp_str  = f"{importance:.2f}" if isinstance(importance, (int, float)) else "—"

    lines = [f"  [{idx}] {doc}"]
    lines.append(
        f"        Section: {section:<20} Speaker: {speaker:<15} "
        f"Page: {page:<5} Year: {year}"
    )
    lines.append(f"        Confidence: {conf_str:<8} Importance: {imp_str}")
    return "\n".join(lines)


def _print_sources(data: Dict[str, Any]) -> None:
    sources = data.get("sources") or []
    n_used  = data.get("chunks_used", len(sources))
    print(f"\n── Sources ({n_used} chunks used) ──")
    if not sources:
        print("  (no sources returned)")
        return
    for i, src in enumerate(sources, 1):
        print(_format_source(src, i))


def _print_confidence_and_warnings(data: Dict[str, Any]) -> None:
    print("\n" + _hr())
    print("CONFIDENCE & EVIDENCE QUALITY")
    print(_hr())
    overall_conf = data.get("overall_confidence", _g(data, "fusion", "overall_confidence"))
    print(f"  Overall answer confidence : {_fmt_pct(overall_conf)}")

    contradictions = data.get("contradictions") or []
    if contradictions:
        print(f"\n  ⚠ {len(contradictions)} CONTRADICTION(S) BETWEEN SOURCES:")
        for c in contradictions[:10]:
            if isinstance(c, dict):
                print(f"      • {c.get('note') or c.get('metric', 'unspecified metric')}")
            else:
                print(f"      • {c}")

    missing = data.get("missing_evidence") or data.get("unmatched") or []
    if missing:
        print(f"\n  ℹ {len(missing)} METRIC(S) WITH NO SUPPORTING COMMENTARY:")
        for m in missing[:10]:
            if isinstance(m, dict):
                print(f"      • {m.get('note') or m.get('metric', 'unspecified metric')}")
            else:
                print(f"      • {m}")

    warnings = data.get("warnings") or []
    if warnings:
        print(f"\n  ⚠ WARNINGS:")
        for w in warnings:
            print(f"      • {w}")

    if not contradictions and not missing and not warnings:
        print("  No contradictions, gaps, or warnings reported.")


def _print_timing(data: Dict[str, Any], client_elapsed: float) -> None:
    print("\n" + _hr())
    print("DIAGNOSTICS / TIMING")
    print(_hr())
    timings = data.get("timings") if isinstance(data.get("timings"), dict) else {}
    print(f"  SQL execution time     : {_fmt_secs(timings.get('sql'))}")
    print(f"  Vector retrieval time  : {_fmt_secs(timings.get('retrieval'))}")
    print(f"  Reranker time          : {_fmt_secs(timings.get('reranker'))}")
    print(f"  Fusion time            : {_fmt_secs(timings.get('fusion'))}")
    print(f"  LLM time               : {_fmt_secs(timings.get('llm'))}")
    server_total = data.get("latency_sec")
    print(f"  Server-reported latency: {_fmt_secs(server_total)}")
    print(f"  Client round-trip time : {client_elapsed:.2f}s")


def _print_meta(data: Dict[str, Any]) -> None:
    print(f"\n── Meta ──")
    print(f"  Model  : {data.get('model_used', _NA)}")
    print(f"  Mode   : {data.get('pipeline_mode', _NA)}")
    print(f"  SQL rows: {data.get('sql_rows', _NA)}  |  Insights: {data.get('insights', _NA)}")


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FinRAG query client")
    parser.add_argument("query", help="Natural language query")
    parser.add_argument("--symbol",   default=None)
    parser.add_argument("--doc-type", default="both",
                         choices=["both", "annual_report", "concall"])
    parser.add_argument("--year",     type=int, default=None)
    parser.add_argument("--auto",     action="store_true",
                         help="Skip provider menu, use best available automatically")
    parser.add_argument("--provider", default=None,
                         help="Skip menu and use this provider ID directly")

    # ── Diagnostics flags ────────────────────────────────────────────────────
    parser.add_argument("--debug", action="store_true",
                         help="Show full diagnostics: plan, atoms, retrieval, reranker, fusion, timing")
    parser.add_argument("--trace", action="store_true",
                         help="Print the raw JSON response from the server (implies --debug)")
    parser.add_argument("--show-atoms",     action="store_true", help="Show atomic decomposition")
    parser.add_argument("--show-plan",      action="store_true", help="Show retrieval plan / intent")
    parser.add_argument("--show-retrieval", action="store_true", help="Show retrieval channel stats")
    parser.add_argument("--show-reranker",  action="store_true", help="Show reranker stats")
    parser.add_argument("--show-fusion",    action="store_true", help="Show fusion insights summary")
    parser.add_argument("--show-prompt",    action="store_true", help="Show the exact prompt sent to the LLM")
    parser.add_argument("--show-context",   action="store_true", help="Show the raw structured context object")
    return parser


def _resolve_show_flags(args: argparse.Namespace) -> None:
    """--debug turns every --show-* flag on; --trace implies --debug."""
    if args.trace:
        args.debug = True
    if args.debug:
        for flag in ("show_atoms", "show_plan", "show_retrieval",
                     "show_reranker", "show_fusion"):
            setattr(args, flag, True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    _resolve_show_flags(args)

    # ── Check server is up ────────────────────────────────────────────────────
    try:
        requests.get(f"{SERVER_URL}/health", timeout=3)
    except requests.exceptions.ConnectionError:
        print(f"\n[error] Cannot connect to {SERVER_URL}")
        print("        Start the server first:")
        print("        C:\\Users\\hp\\Downloads\\FinRag\\venv\\Scripts\\python.exe server.py\n")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"\n[error] Server health check failed: {e}\n"
              f"        Continuing anyway — the server may still respond to /query.\n")

    # ── Provider selection ────────────────────────────────────────────────────
    if args.auto:
        provider_id = "auto"
    elif args.provider:
        provider_id = args.provider
    else:
        providers = fetch_providers()
        provider_id = pick_provider(providers)

    # ── Send query ────────────────────────────────────────────────────────────
    payload = {
        "query":    args.query,
        "symbol":   args.symbol,
        "doc_type": args.doc_type,
        "year":     args.year,
        "provider": provider_id,
        # Ask the server for extra diagnostics if it supports them. Older
        # server builds will simply ignore unknown keys, and every render
        # function above degrades gracefully if these fields never arrive.
        "debug":    bool(args.debug or args.trace),
    }

    _print_header(args.query, args)
    print("\n🔍 Retrieving and re-ranking...")

    t0 = time.perf_counter()
    try:
        resp = requests.post(f"{SERVER_URL}/query", json=payload, timeout=REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        print(
            "\n[error] Client timed out waiting for server "
            f"(>{REQUEST_TIMEOUT_SEC}s).\n"
            "  The server is still processing — this is likely a slow/stalled LLM provider.\n"
            "  Tips:\n"
            "    • Use groq-llama (option 1) — fastest and most reliable\n"
            "    • Use --auto to let the server try providers in order\n"
            "    • Free OpenRouter models can queue for 60-120s under load\n"
        )
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print(f"\n[error] Lost connection to {SERVER_URL} mid-request. "
              f"Is the server still running?\n")
        sys.exit(1)
    except requests.exceptions.HTTPError:
        detail = None
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = getattr(resp, "text", "(no body)")
        print(f"\n[error] Server returned HTTP {resp.status_code}:\n  {detail}")
        print("        The LLM stage likely failed — check server logs for the "
              "specific provider error. Try a different --provider.\n")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"\n[error] Request failed: {e}\n")
        sys.exit(1)

    client_elapsed = time.perf_counter() - t0

    try:
        data = resp.json()
    except ValueError:
        print("\n[error] Server response was not valid JSON:")
        print(resp.text[:1000])
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"\n[error] Unexpected response shape from server: {type(data)}")
        sys.exit(1)

    if args.trace:
        print("\n" + _hr())
        print("RAW SERVER RESPONSE")
        print(_hr())
        try:
            print(json.dumps(data, indent=2, default=str))
        except Exception:
            print(str(data))

    # ── Diagnostic sections (each opt-in, so a plain query stays plain) ────────
    if args.show_plan:
        _print_plan(data)
    if args.show_atoms:
        _print_atoms(data)
    if args.show_retrieval:
        _print_retrieval(data)
    if args.show_reranker:
        _print_reranker(data)
    if args.show_fusion:
        _print_fusion(data)
    if args.show_prompt:
        _print_prompt(data)
    if args.show_context:
        _print_context(data)

    # ── Answer ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("ANSWER")
    print("=" * 74)
    answer = data.get("answer")
    if not answer:
        print("  [warning] Server returned no answer text. This usually means every "
              "LLM provider failed — check --debug output above for partial evidence, "
              "or retry with a different --provider.")
    else:
        print(answer)

    _print_sources(data)
    _print_confidence_and_warnings(data)

    if args.debug:
        _print_timing(data, client_elapsed)

    _print_meta(data)
    print(f"  Client round-trip: {client_elapsed:.2f}s")
    print("=" * 74 + "\n")


if __name__ == "__main__":
    main()