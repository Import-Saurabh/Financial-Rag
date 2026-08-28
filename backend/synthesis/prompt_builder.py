from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── graceful imports (same pattern as fusion_layer) ──────────────────────────
try:
    from fusion.fusion_layer import FusionResult, InsightType
except ModuleNotFoundError:
    FusionResult  = None   # type: ignore[assignment,misc]
    InsightType   = None   # type: ignore[assignment,misc]

# FIX: _dedup_chunks lives in fusion_layer and IS applied to
# fusion_result.annual_chunks/concall_chunks — but this file never reads
# those fields. It renders the raw `chunks` argument passed in by the
# caller instead, which never goes through dedup. That's why the same
# "Disaggregated Revenue" standalone-vs-consolidated pair showed up 5-6x
# in a single prompt's context. Import the same dedup fn and apply it here.
try:
    from fusion.fusion_layer import _dedup_chunks
except ModuleNotFoundError:
    def _dedup_chunks(chunks):              # type: ignore[no-redef]
        return chunks

try:
    from rag.retriever_openkb import RetrievedChunk
except ModuleNotFoundError:
    from dataclasses import dataclass as _dc, field as _f
    @_dc
    class RetrievedChunk:                     # type: ignore[no-redef]
        chunk_id: str = ""; text: str = ""; score: float = 0.0
        vector_score: float = 0.0; bm25_score: float = 0.0
        metadata: Dict[str, Any] = _f(default_factory=dict)

try:
    from utils.logger import get_logger
    log = get_logger(__name__)
except ModuleNotFoundError:
    import logging
    log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
_CHARS_PER_TOKEN   = 3.5          # conservative for dense financial text
_DEFAULT_MAX_CHARS = 80_000       # ~22k tokens — safe for Qwen3-30B free tier
_GROQ_MAX_CHARS    = 18_000       # ~5.1k tokens — Groq free hard cap
_SQL_TABLE_HDR     = "── STRUCTURED FINANCIAL DATA (from SQLite) ──"
_VECTOR_HDR        = "── DOCUMENT EXCERPTS (annual reports / concalls) ──"
_INSIGHTS_HDR      = "── CROSS-CHANNEL INSIGHTS (auto-detected) ──"


# ─────────────────────────────────────────────────────────────────────────────
# Output dataclass
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class BuiltPrompt:
    system_prompt:   str
    user_prompt:     str
    sql_rows_used:   int           # how many SQL metric rows were included
    chunks_used:     int           # how many vector chunks were included
    insights_used:   int           # how many fusion insights were included
    total_chars:     int           # estimated total prompt size
    was_trimmed:     bool          # True if chunks were dropped for budget
    # FIX: fusion_layer computes this (evidence-bundle trustworthiness,
    # 0-1) but it was being silently dropped — never read out of
    # ctx.get("overall_confidence"), never surfaced to the caller, so
    # query_client.py had nothing to print except "not reported by
    # server". Now threaded through so it can reach the CLI/API output.
    overall_confidence: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# System prompts
# ─────────────────────────────────────────────────────────────────────────────

# Shared financial rules injected into every system prompt
_FINANCIAL_RULES = """\
FINANCIAL ANALYSIS RULES (follow strictly):
A. EXACT METRIC MATCHING: If the user asks for EBIT but only EBITDA is available,
   flag it: "Note: EBIT not found; showing EBITDA (includes D&A of ₹X cr)."
   Never silently substitute one metric for another.
B. SHOW YOUR MATH — [SQL-N] DATA ONLY: For any growth/YoY/CAGR calculation
   using [SQL-N] rows (these are already unit-normalized), write the formula
   and numbers inline. Example: Revenue growth FY24→FY25 = (31,079 − 26,711)
   / 26,711 × 100 = +16.3%
B2. NEVER CONVERT UNITS YOURSELF: Figures inside [SRC-N] document excerpts
   are NOT pre-converted — the same report may state one figure in Lakh and
   another in Crore. Do not multiply, divide, or otherwise convert a [SRC-N]
   number to compare it against a [SQL-N] number or another [SRC-N] number.
   If two figures you need are in different units, do NOT compute a
   combined or converted result — state each figure exactly as written with
   its own unit, and say a directly comparable figure isn't available in
   the provided context. Manual unit conversion is the single most common
   source of serious errors in this system — treat it as forbidden, not
   optional.
C. CITE EVERY NUMBER: After each figure write [SQL-N] if it came from the
   structured data table, or [SRC-N] if it came from a document excerpt.
D. CURRENCY: State amounts exactly as in source (₹ Crore / Lakh / Million).
   Never convert unless the user asks — and even then, only using [SQL-N]
   figures (see rule B2).
E. NO HALLUCINATION: If a number is not in the provided context, write
   "Not available in provided documents." Never guess or back-calculate.
F. RECENCY FIRST: Lead with the most recent fiscal year available.
G. DON'T PAD LISTS: If asked for a specific count of items (e.g. "top 5
   drivers"), and you only find 3, only list 3. Do not pad the list with
   filler.
H. HUMAN-LIKE TONE: Ensure your response is highly conversational, natural, and human-like in tone. Do not sound robotic."""

_SYSTEM_PROMPT_FUSION = """\
You are an expert equity research analyst with a natural, human-like conversational tone.
You specialise in Indian listed companies (BSE/NSE).

You receive three types of pre-processed context:
  [SQL]      Hard numbers directly from a structured financial database.
             These are ground truth.
  [EXCERPTS] Ranked passages from annual reports and concall transcripts.
             Use these for qualitative colour and management commentary.
  [INSIGHTS] Pre-detected contradictions, confirmations, and guidance flags.

ANSWER FORMAT:
1. Make your answer sound natural, insightful, and easy to read. Avoid robotic structuring unless data clearly warrants a table.
2. If comparing metrics across years, feel free to use a Markdown table or clear bullet points.
3. If summarising management commentary, use bullet points with speaker names.
4. If a contradiction insight is present, start your answer with a callout.
5. Always end with a 'Sources used:' line. For documents, cite the source and the page number clearly (e.g., [SRC-1, Page 45]).

""" + _FINANCIAL_RULES

_SYSTEM_PROMPT_VECTOR_ONLY = """\
You are a senior equity research analyst specialising in Indian listed companies \
(BSE/NSE).

BEFORE WRITING YOUR ANSWER reason step-by-step internally:
  Step 1 — What EXACTLY is being asked? One sentence.
  Step 2 — Which chunks directly answer Step 1? List them.
  Step 3 — Exclude chunks that are only tangentially related.
  Step 4 — Build your answer ONLY from Step 2 chunks.
  Step 5 — For missing data write "Not available in provided documents."

ANSWER FORMAT:
- Multi-year comparisons → Markdown table.
- Single-year or qualitative → bullet points or short paragraphs.
- Cite every number with [SRC-N].

""" + _FINANCIAL_RULES


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_value(value: Optional[float], unit: str) -> str:
    """Format a metric value with its unit for display."""
    if value is None:
        return "N/A"
    if unit in ("%",):
        return f"{value:.2f}%"
    if unit in ("x",):
        return f"{value:.2f}x"
    if unit in ("days",):
        return f"{value:.1f} days"
    if unit in ("rs",):
        return f"₹{value:,.2f}"
    if unit in ("crore",):
        return f"₹{value:,.1f} cr"
    return f"{value:,.2f} {unit}".strip()


def _render_sql_table(metric_rows: List[Dict]) -> str:
    """
    Render the list of MetricRow dicts as a compact ASCII table.

    Groups rows by (symbol, sub_type) so multi-year series appears as
    one logical block.  Annotates each row with [SQL-N].

    Returns empty string if metric_rows is empty.
    """
    if not metric_rows:
        return ""

    lines = [_SQL_TABLE_HDR]
    lines.append(f"{'#':<6} {'Symbol':<14} {'Metric':<22} {'FY':<6} {'Period':<12} {'Value'}")
    lines.append("─" * 80)

    for i, row in enumerate(metric_rows, 1):
        sym    = str(row.get("symbol", ""))[:13]
        metric = str(row.get("metric", row.get("sub_type", "")))[:21]
        fy     = str(row.get("year", ""))[:5]
        period = str(row.get("period", ""))[:11]
        value  = _fmt_value(row.get("value"), row.get("unit", ""))
        lines.append(f"[SQL-{i}] {sym:<14} {metric:<22} {fy:<6} {period:<12} {value}")

    lines.append("─" * 80)
    return "\n".join(lines)


def _render_insights(insights: List[Dict]) -> str:
    """
    Render fusion insights (contradictions / confirmations / forward / unmatched)
    as a labelled callout block.

    Returns empty string if no insights.
    """
    if not insights:
        return ""

    contras  = [i for i in insights if i.get("type") == "CONTRADICT"]
    confirms = [i for i in insights if i.get("type") == "CONFIRM"]
    forwards = [i for i in insights if i.get("type") == "FORWARD"]
    unmatch  = [i for i in insights if i.get("type") == "UNMATCHED"]

    lines = [_INSIGHTS_HDR]

    for ins in contras:
        lines.append(f"⚠  CONTRADICTION  [{ins.get('metric','')}]")
        lines.append(f"   {ins.get('note','')}")

    for ins in confirms:
        lines.append(f"✓  CONFIRMED  [{ins.get('metric','')}]")
        lines.append(f"   {ins.get('note','')}")

    for ins in forwards:
        lines.append(f"→  GUIDANCE  [{ins.get('metric','')} | {ins.get('symbol','')}]")
        lines.append(f"   {ins.get('note','')}")

    for ins in unmatch:
        lines.append(f"·  DATA ONLY (no mgmt commentary)  [{ins.get('metric','')}]")
        lines.append(f"   {ins.get('note','')}")

    return "\n".join(lines)


def _render_chunks(chunks: List[Any], start_index: int = 1) -> str:
    """Render OpenKB tree evidence or legacy vector chunks as labelled [SRC-N] blocks."""
    if not chunks:
        return ""
    lines = [_VECTOR_HDR]
    for i, chunk in enumerate(chunks, start_index):
        if isinstance(chunk, dict):
            # OpenKB evidence
            file = chunk.get("source_file", "")
            page = chunk.get("page_number", "?")
            section = chunk.get("section_title", "")[:50]
            score = round(chunk.get("score", 0.0), 4)
            text = chunk.get("text", "")
            header = f"[SRC-{i}] {file} | {section} | p.{page} | OpenKB-score={score}"
        else:
            # Legacy RetrievedChunk
            meta    = chunk.metadata
            symbol  = meta.get("symbol", "")
            year    = meta.get("year", "")
            dt      = "AR" if meta.get("doc_type") == "annual_report" else "CC"
            section = (meta.get("section") or meta.get("speaker", ""))[:50]
            page    = meta.get("page_start", "?")
            score   = round(chunk.score, 4)
            text    = chunk.text
            header  = f"[SRC-{i}] {symbol} FY{year} [{dt}] | {section} | p.{page} | score={score}"
            
        lines.append(header)
        lines.append(textwrap.fill(text[:1200], width=100))
        lines.append("")
    return "\n".join(lines)


def _build_gap_flag_note(
    resolved_years: Optional[List[int]],
    explicit_years: Optional[List[int]],
) -> str:
    if not explicit_years:
        return (
            "\nGAP FLAG INSTRUCTION: The user did NOT specify particular years. "
            "Do NOT emit any ⚠ 'not in retrieved excerpts' flags. "
            "Simply state what is available."
        )
    fy_str = "/".join(f"FY{y}" for y in explicit_years)
    return (
        f"\nGAP FLAG INSTRUCTION: The user explicitly asked about {fy_str}. "
        f"Emit ⚠ gap warnings ONLY for these years if data is missing. "
        f"Do NOT emit ⚠ for any other year."
    )


def _build_intent_note(query: str) -> str:
    q = query.lower()
    if any(kw in q for kw in ["outlook", "guidance", "expect", "h1", "h2",
                                "demand", "going forward", "forecast", "target"]):
        return (
            "\nINTENT: FORWARD-LOOKING query. Prioritise [SRC-N] chunks containing "
            "'we expect', 'going forward', 'H1/H2', 'guidance', 'target'. "
            "Do NOT substitute past performance for forward commentary."
        )
    if any(kw in q for kw in ["yoy", "year on year", "growth", "cagr", "trend"]):
        return (
            "\nINTENT: GROWTH / TREND query. Show a multi-year table with explicit "
            "YoY % calculations. Lead with most recent year."
        )
    return ""


def _build_confidence_note(overall_confidence: Optional[float]) -> str:
    """
    FIX: overall_confidence was computed by fusion_layer and available via
    ctx["overall_confidence"] but never read by this file, so it never
    reached the model or the CLI output — every query in production logs
    showed "confidence: not reported by server". This surfaces it as a
    calibration instruction so the model hedges appropriately, and the
    caller can also read it back off BuiltPrompt.overall_confidence for
    display/logging without needing to re-derive it.
    """
    if overall_confidence is None:
        return ""
    if overall_confidence >= 0.8:
        tone = "Evidence bundle is strong — answer with normal confidence."
    elif overall_confidence >= 0.5:
        tone = ("Evidence bundle is moderate — hedge claims that rely on a "
                "single unconfirmed source and note where corroboration is thin.")
    else:
        tone = ("Evidence bundle is weak (low source agreement / many gaps) — "
                "be explicit about uncertainty and avoid definitive claims "
                "not directly backed by [SQL-N] or a clear [SRC-N] statement.")
    return f"\nEVIDENCE CONFIDENCE: {overall_confidence:.2f}/1.0. {tone}"

"""
synthesis/prompt_builder.py  — EBITDA proxy patch

Bug fixed
──────────
[BUG-EBITDA-CALC]
  When the user asks for "EBITDA CAGR FY23-25", the bridge now fetches
  ebitda_proxy rows (operating_profit + depreciation from annual_results).
  But the prompt_builder didn't know to tell the LLM to compute
  EBITDA = operating_profit + depreciation and then compute the CAGR.

  Without this instruction, the LLM just sees the raw numbers and either
  guesses incorrectly or says "EBITDA not available".

  FIX: In _build_metric_note() (called from both fusion and vector-only paths),
  detect when the query mentions "ebitda" + multi-year indicators and inject
  an explicit calculation instruction into the prompt.

HOW TO APPLY:
In your synthesis/prompt_builder.py, find the function _build_metric_note()
(around line 350-380).  Add the EBITDA block shown below to its return value.

Also update _render_sql_table() to show a "CALCULATION NOTE" row when
ebitda_proxy sub_type is present in the rows.
"""

# ─────────────────────────────────────────────────────────────────────────────
# PATCH: Replace _build_metric_note() in prompt_builder.py with this version
# ─────────────────────────────────────────────────────────────────────────────
def _build_metric_note(query: str) -> str:
    """
    Return model-specific calculation instructions based on detected metrics.
    Injected at the bottom of the user prompt.
    """
    notes = []
    q = query.lower()

    # EBITDA multi-year / CAGR note  [BUG-EBITDA-CALC]
    import re
    if re.search(r'\bebitda\b', q) and re.search(
        r'\b(cagr|yoy|year[\s\-]on[\s\-]year|trend|growth|fy2[0-9]\d?\s*[-–to])', q
    ):
        notes.append(
            "EBITDA CALCULATION NOTE: If [SQL] rows show 'operating_profit' and "
            "'depreciation' columns (ebitda_proxy), compute:\n"
            "  EBITDA = operating_profit + depreciation  (for each year)\n"
            "Then compute CAGR:\n"
            "  CAGR = (EBITDA_end / EBITDA_start)^(1/n_years) - 1\n"
            "Show this calculation step explicitly before presenting the result."
        )

    # FCF calculation note
    if re.search(r'\bfcf\b|\bfree\s+cash\s+flow\b', q):
        notes.append(
            "FCF NOTE: Free Cash Flow = Operating Cash Flow (CFO) − Capex. "
            "If only OCF and Capex are provided, compute FCF explicitly."
        )

    # CAGR general note
    if re.search(r'\bcagr\b', q):
        notes.append(
            "CAGR FORMULA: CAGR = (End_Value / Start_Value)^(1 / N_years) − 1. "
            "Write formula + numbers inline before stating the result."
        )

    # YoY note
    if re.search(r'\byoy\b|\byear[\s\-]on[\s\-]year\b|\bgrowth\b', q):
        notes.append(
            "YoY GROWTH: (Current_Year − Prior_Year) / Prior_Year × 100. "
            "Show formula + numbers for every year."
        )

    return ("\n\n" + "\n".join(notes)) if notes else ""


# ─────────────────────────────────────────────────────────────────────────────
# INSTRUCTION: In your existing prompt_builder.py, find the current
# _build_metric_note() function and replace its entire body with the
# function above (keep the same function signature).
#
# If the function doesn't exist yet in your file, add it and call it
# from both _build_fusion_prompt() and _build_vector_only_prompt() like:
#
#   notes = (
#       _build_gap_flag_note(resolved_years, explicit_years)
#       + _build_intent_note(query)
#       + _build_metric_note(query)   ← add this line
#   )
# ─────────────────────────────────────────────────────────────────────────────

PATCH_DESCRIPTION = {
    "file":     "synthesis/prompt_builder.py",
    "function": "_build_metric_note",
    "reason":   "Adds EBITDA = operating_profit + depreciation calculation instruction "
                "when ebitda_proxy SQL rows are fetched, so LLM can compute CAGR/YoY "
                "from annual_results instead of failing on the fundamentals snapshot.",
}

# ─────────────────────────────────────────────────────────────────────────────
# PromptBuilder
# ─────────────────────────────────────────────────────────────────────────────

class PromptBuilder:
    """
    Assembles (system_prompt, user_prompt) from FusionResult + raw chunks.

    Usage:
        builder = PromptBuilder()
        built   = builder.build(query, fusion_result, chunks, ...)
        result  = _call_with_retry(built.system_prompt, built.user_prompt, entry)
    """

    def __init__(self, max_context_chars: int = _DEFAULT_MAX_CHARS):
        self.max_context_chars = max_context_chars

    # ── Main entry point ──────────────────────────────────────────────────────

    def build(
        self,
        query:          str,
        chunks:         List["RetrievedChunk"],
        fusion_result:  Optional[Any] = None,   # FusionResult | None
        doc_type:       str = "both",
        resolved_years: Optional[List[int]] = None,
        explicit_years: Optional[List[int]] = None,
    ) -> BuiltPrompt:
        """
        Build the full (system, user) prompt pair.

        Parameters
        ──────────
        query           Raw user question.
        chunks          Reranked RetrievedChunk list (vector channel output).
        fusion_result   FusionResult from the fusion layer — may be None for
                        pure-vector queries (legacy path).
        doc_type        "annual_report" | "concall" | "both"
        resolved_years  All years used for retrieval filtering.
        explicit_years  Only years the user explicitly named — controls gap flags.
        """
        has_fusion = (
            fusion_result is not None
            and FusionResult is not None
            and isinstance(fusion_result, FusionResult)
        )

        if has_fusion:
            return self._build_fusion_prompt(
                query, chunks, fusion_result,
                doc_type, resolved_years, explicit_years,
            )
        else:
            return self._build_vector_only_prompt(
                query, chunks, doc_type, resolved_years, explicit_years,
            )

    # ── Fusion path (SQL + vector + insights) ─────────────────────────────────

    def _build_fusion_prompt(
        self,
        query:          str,
        chunks:         List["RetrievedChunk"],
        fusion_result:  Any,
        doc_type:       str,
        resolved_years: Optional[List[int]],
        explicit_years: Optional[List[int]],
    ) -> BuiltPrompt:

        ctx = fusion_result.to_context_dict()

        # FIX: dedup the chunks actually being rendered. fusion_result's own
        # .annual_chunks/.concall_chunks are deduped, but this function
        # renders the raw `chunks` argument the caller passed in — which
        # bypassed dedup entirely. This is why the same "Disaggregated
        # Revenue" disclosure (standalone vs consolidated, same page range)
        # was showing up 5-6 times in one prompt, crowding out everything
        # else the model could have cited.
        chunks = _dedup_chunks(chunks)

        # ── 1. SQL table (always kept whole) ──────────────────────────────────
        sql_block     = _render_sql_table(ctx.get("metric_table", []))
        sql_rows_used = len(ctx.get("metric_table", []))

        # ── 2. Insights block ─────────────────────────────────────────────────
        all_insights = (
            ctx.get("contradictions",  []) +
            ctx.get("confirmations",   []) +
            ctx.get("forward_guidance",[]) +
            ctx.get("unmatched",       [])
        )
        insights_block  = _render_insights(all_insights)
        insights_used   = len(all_insights)

        # ── 3. Budget: how much space left for vector chunks? ─────────────────
        overall_confidence = ctx.get("overall_confidence")   # FIX: was dropped
        system_prompt  = _SYSTEM_PROMPT_FUSION
        notes          = (
            _build_gap_flag_note(resolved_years, explicit_years)
            + _build_intent_note(query)
            + _build_metric_note(query)
            + _build_confidence_note(overall_confidence)
        )
        fixed_chars    = (
            len(system_prompt)
            + len(sql_block)
            + len(insights_block)
            + len(query)
            + len(notes)
            + 600          # overhead: headers, separators, question line
        )
        chunk_budget   = max(0, self.max_context_chars - fixed_chars)

        # ── 4. Trim chunks to budget ──────────────────────────────────────────
        safe_chunks, was_trimmed = _trim_chunks(chunks, chunk_budget)

        # ── 5. Chunk block ────────────────────────────────────────────────────
        chunk_block = _render_chunks(safe_chunks, start_index=1)

        # ── 6. Assemble user prompt ───────────────────────────────────────────
        year_note = ""
        if resolved_years:
            year_note = (
                f"\nDATA SEARCHED: Retrieval covered "
                f"FY{'/'.join(str(y) for y in resolved_years)} documents."
            )

        sections = []
        if sql_block:
            sections.append(sql_block)
        if insights_block:
            sections.append(insights_block)
        if chunk_block:
            sections.append(chunk_block)
        if ctx.get("errors"):
            sections.append("── PIPELINE ERRORS ──\n" + "\n".join(ctx["errors"]))

        context_block = "\n\n".join(sections)

        user_prompt = (
            f"CONTEXT:\n{'=' * 70}\n"
            f"{context_block}\n"
            f"{'=' * 70}"
            f"{year_note}{notes}\n\n"
            f"QUESTION: {query}\n\n"
            f"INSTRUCTIONS:\n"
            f"- Use [SQL-N] data as ground truth; cite it after every number.\n"
            f"- Use [SRC-N] excerpts for qualitative context and management commentary.\n"
            f"- Be conversational and analytical. Avoid sounding like a rigid bot.\n"
            f"- End with a concise 'Sources used: [SQL-1], [SRC-2, Page 45], ...' line.\n"
        )

        total_chars = len(system_prompt) + len(user_prompt)
        log.info(
            f"[prompt_builder] fusion path | sql_rows={sql_rows_used} "
            f"chunks={len(safe_chunks)}/{len(chunks)} insights={insights_used} "
            f"confidence={overall_confidence} chars={total_chars:,} trimmed={was_trimmed}"
        )

        return BuiltPrompt(
            system_prompt       = system_prompt,
            user_prompt         = user_prompt,
            sql_rows_used       = sql_rows_used,
            chunks_used         = len(safe_chunks),
            insights_used       = insights_used,
            total_chars         = total_chars,
            was_trimmed         = was_trimmed,
            overall_confidence  = overall_confidence,
        )

    # ── Vector-only path (legacy / no SQL data) ───────────────────────────────

    def _build_vector_only_prompt(
        self,
        query:          str,
        chunks:         List["RetrievedChunk"],
        doc_type:       str,
        resolved_years: Optional[List[int]],
        explicit_years: Optional[List[int]],
    ) -> BuiltPrompt:

        system_prompt = _SYSTEM_PROMPT_VECTOR_ONLY
        notes         = (
            _build_gap_flag_note(resolved_years, explicit_years)
            + _build_intent_note(query)
            + _build_metric_note(query)
        )

        # FIX: same dedup gap as the fusion path — apply here too.
        chunks = _dedup_chunks(chunks)

        fixed_chars  = len(system_prompt) + len(query) + len(notes) + 400
        chunk_budget = max(0, self.max_context_chars - fixed_chars)

        safe_chunks, was_trimmed = _trim_chunks(chunks, chunk_budget)
        chunk_block  = _render_chunks(safe_chunks, start_index=1)

        year_note = ""
        if resolved_years:
            year_note = (
                f"\nDATA SEARCHED: Retrieval covered "
                f"FY{'/'.join(str(y) for y in resolved_years)} documents."
            )

        user_prompt = (
            f"CONTEXT FROM FINANCIAL DOCUMENTS (most relevant first):\n"
            f"{'=' * 70}\n"
            f"{chunk_block}\n"
            f"{'=' * 70}"
            f"{year_note}{notes}\n\n"
            f"QUESTION: {query}\n\n"
            f"INSTRUCTIONS:\n"
            f"- Answer using ONLY the context above.\n"
            f"- Cite every number with [SRC-N].\n"
            f"- Show explicit calculations only when both figures share the same unit "
            f"as written in the excerpt — never convert Lakh/Crore/Million yourself "
            f"(see rule B2).\n"
            f"- Use a Markdown table for multi-year comparisons.\n"
            f"- Flag only explicitly-requested missing years (see GAP FLAG above).\n"
        )

        total_chars = len(system_prompt) + len(user_prompt)
        log.info(
            f"[prompt_builder] vector-only path | "
            f"chunks={len(safe_chunks)}/{len(chunks)} "
            f"chars={total_chars:,} trimmed={was_trimmed}"
        )

        return BuiltPrompt(
            system_prompt  = system_prompt,
            user_prompt    = user_prompt,
            sql_rows_used  = 0,
            chunks_used    = len(safe_chunks),
            insights_used  = 0,
            total_chars    = total_chars,
            was_trimmed    = was_trimmed,
        )

    # ── Convenience: adjust budget for a specific provider ────────────────────

    def for_provider(self, model: str) -> "PromptBuilder":
        """
        Return a new PromptBuilder sized for a specific model.

        Usage:
            built = PromptBuilder().for_provider("llama-3.3-70b-versatile").build(...)
        """
        _MODEL_CHARS = {
            # Groq free tier
            "llama-3.3-70b-versatile":          _GROQ_MAX_CHARS,
            "gemma2-9b-it":                     12_000,
            # OpenRouter Qwen free
            "qwen/qwen3-30b-a3b:free":          _DEFAULT_MAX_CHARS,
            "qwen/qwen3-8b:free":               _DEFAULT_MAX_CHARS,
            "qwen/qwen2.5-72b-instruct:free":   _DEFAULT_MAX_CHARS,
            # Gemini
            "google/gemini-2.0-flash-001":      600_000,
            "gemini-2.0-flash":                 600_000,
            # NVIDIA NIM
            "meta/llama-3.3-70b-instruct":      150_000,
        }
        chars = _MODEL_CHARS.get(model, _DEFAULT_MAX_CHARS)
        return PromptBuilder(max_context_chars=chars)


# ─────────────────────────────────────────────────────────────────────────────
# Internal: chunk trimmer
# ─────────────────────────────────────────────────────────────────────────────

def _trim_chunks(
    chunks: List[Any],
    char_budget: int,
) -> tuple:  # (List[Any], bool was_trimmed)
    """
    Keep top-ranked chunks until char_budget is consumed.
    Returns (kept_chunks, was_trimmed).
    SQL data is never touched here — budget calculation excludes it.
    """
    if char_budget <= 0:
        return [], True

    kept  = []
    used  = 0
    # ~250 chars per chunk for header + separators
    for chunk in chunks:
        if isinstance(chunk, dict):
            cost = len(chunk.get("text", "")) + 250
        else:
            cost = len(chunk.text) + 250
            
        if used + cost > char_budget:
            break
        kept.append(chunk)
        used += cost

    was_trimmed = len(kept) < len(chunks)
    if was_trimmed:
        log.info(
            f"[prompt_builder] trimmed {len(chunks)} → {len(kept)} chunks "
            f"({used:,}/{char_budget:,} chars used)"
        )
    return kept or (chunks[:1] if chunks else []), was_trimmed