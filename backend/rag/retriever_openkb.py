import subprocess
import json
import logging
import os
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)

@dataclass
class RetrievedChunk:
    text: str
    chunk_type: str = "openkb_text"
    section: str = "Unknown"
    section_type: str = "Unknown"
    symbol: str = "Unknown"
    year: int = 0
    doc_type: str = "Unknown"
    page_start: int = 0
    page_end: int = 0
    word_count: int = 0
    importance_score: float = 0.0
    retrieval_tags: List[str] = None
    
    # Optional v2 fields
    chapter: str = ""

    @property
    def metadata(self) -> dict:
        return {"symbol": self.symbol, "year": self.year, "section": self.section, "doc_type": self.doc_type, "page_start": self.page_start, "page_end": self.page_end}

    subsection: str = ""

    @property

    def get(self, key, default=None):
        if key == "metadata":
            return self.metadata
        if key == "score":
            return self.score
        return getattr(self, key, default)

    def __getitem__(self, key):
        return self.get(key)
        
    def __contains__(self, key):
        return hasattr(self, key)

    @property
    def score(self) -> float:
        return self.importance_score


    hierarchy_path: str = ""
    
    financial_metrics: List[str] = None
    products_mentioned: List[str] = None
    business_segments: List[str] = None
    geography_mentioned: List[str] = None
    entities_mentioned: List[str] = None
    currencies_mentioned: List[str] = None
    fiscal_period: str = ""
    quarter: str = ""
    
    forward_looking: bool = False
    historical: bool = False
    management_opinion: bool = False
    quantitative_guidance: bool = False
    contains_guidance: bool = False
    contains_commitment: bool = False
    contains_strategic: bool = False
    contains_contract: bool = False
    is_duplicate: bool = False
    is_low_information: bool = False
    
    table_type: str = ""
    table_summary: str = ""
    
    speaker: str = ""
    speaker_role: str = ""
    
    chunk_id: str = ""


def _parse_chunk_metadata(text: str, section: str) -> tuple:
    import re
    combined = f"{section} {text[:400]}".lower()
    # Symbol
    if "apollo" in combined:
        sym = "APOLLO"
    elif "hal" in combined or "hindustan aero" in combined:
        sym = "HAL"
    elif "bel" in combined or "bharat elec" in combined:
        sym = "BEL"
    elif "reliance" in combined or "ril" in combined:
        sym = "RELIANCE"
    elif "tcs" in combined or "tata consul" in combined:
        sym = "TCS"
    else:
        sym = "Unknown"

    # Year
    year = 0
    m_yr = re.search(r'\b(202[0-9])\b|fy\s*(\d{2,4})', combined)
    if m_yr:
        if m_yr.group(1):
            year = int(m_yr.group(1))
        elif m_yr.group(2):
            y_val = int(m_yr.group(2))
            year = (2000 + y_val) if y_val < 100 else y_val

    # Doc type
    if any(k in combined for k in ["concall", "transcript", "earnings call", "call"]):
        doc_type = "concall"
    else:
        doc_type = "annual_report"

    return sym, year, doc_type


class OpenKBRetriever:
    def __init__(self, wiki_dir: str = "backend/data/openkb_wiki"):
        self.wiki_dir = Path(wiki_dir).absolute()
        
    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        symbol_filter: Optional[List[str]] = None,
    ) -> List[RetrievedChunk]:
        """
        Retrieves relevant pages using OpenKB tree index.

        Args:
            question:      The user query.
            top_k:         Max chunks to return.
            symbol_filter: If provided, only chunks whose .symbol matches
                           one of these values (case-insensitive) are kept.
                           When the filter is active and no matching chunks
                           exist, an empty list is returned instead of
                           falling back to unrelated documents.
        """
        evidence = []
        try:
            openkb_cmd = r"C:\Users\hp\AppData\Roaming\Python\Python310\Scripts\openkb.exe"
            result = subprocess.run(
                [openkb_cmd, "query", question, "--json", f"--top-k={top_k * 3}"],
                cwd=self.wiki_dir,
                capture_output=True,
                text=True,
                timeout=10,
                shell=(os.name == "nt")
            )
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    for item in data.get("results", []):
                        raw_text = item.get("summary", "") or item.get("text", "")
                        sec_title = item.get("section_title", "Unknown Section")
                        sym, yr, dt = _parse_chunk_metadata(raw_text, sec_title)
                        evidence.append(RetrievedChunk(
                            text=raw_text,
                            section=sec_title,
                            symbol=sym,
                            year=yr,
                            doc_type=dt,
                            page_start=item.get("page_number", -1),
                            importance_score=item.get("score", 0.0)
                        ))
                except json.JSONDecodeError:
                    log.error(f"Failed to parse OpenKB JSON output: {result.stdout}")
            else:
                log.warning(f"OpenKB query returned non-zero or empty. Stderr: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            log.warning("OpenKB query timed out (>10s). Falling back to keyword search.")
        except Exception as e:
            log.error(f"Error calling OpenKB: {e}")
            
        # Fallback: if OpenKB returned nothing, try keyword search
        if not evidence:
            evidence = self._fallback_keyword_search(question, top_k * 3)

        # ── Symbol filtering ─────────────────────────────────────────────────
        # This is the critical fix: when the agent has identified specific
        # symbols, we MUST filter out chunks belonging to other companies.
        # Without this, a query for "HAL profit" would return Apollo chunks
        # simply because Apollo docs mention "profit" more often.
        if symbol_filter:
            allowed = {s.upper() for s in symbol_filter}
            filtered = [c for c in evidence if c.symbol.upper() in allowed]
            if filtered:
                evidence = filtered
                log.info(
                    f"[retriever] Symbol filter {allowed}: "
                    f"kept {len(filtered)}/{len(evidence)} chunks"
                )
            else:
                # No docs for the requested symbol — return empty.
                # The agent will handle this gracefully by relying on
                # structured SQL data or informing the user.
                log.warning(
                    f"[retriever] Symbol filter {allowed}: "
                    f"0 chunks matched — returning empty (no cross-polluted docs)"
                )
                return []

        return evidence[:top_k]
        
    def _fallback_keyword_search(self, question: str, top_k: int = 5) -> List[RetrievedChunk]:
        """
        Keyword search across wiki markdown files.
        Improved: includes short words (like 'HAL') instead of
        the old broken `len(w) > 3` filter that silently dropped them.
        """
        import re
        # Keep all meaningful words — no longer drops 3-letter tickers like HAL/BEL/TCS
        stopwords = {"what", "is", "the", "for", "and", "how", "has", "are", "was", "been",
                      "from", "with", "this", "that", "its", "will", "can", "does", "did",
                      "about", "over", "which", "their", "they", "have", "were", "our", "any"}
        keywords = [w.lower() for w in question.split() if w.lower() not in stopwords and len(w) >= 2]
        if not keywords:
            return []
            
        results = []
        wiki_base = self.wiki_dir / "wiki"
        if not wiki_base.exists():
            return results
            
        for root, _, files in os.walk(wiki_base):
            for file in files:
                if file.endswith(".md"):
                    filepath = Path(root) / file
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        
                        # Break content into paragraphs or sections
                        chunks = re.split(r"\\n\\n|\\n# ", content)
                        for chunk in chunks:
                            if not chunk.strip():
                                continue
                            chunk_lower = chunk.lower()
                            
                            score = sum(chunk_lower.count(k) for k in keywords)
                            if score > 0:
                                sym, yr, dt = _parse_chunk_metadata(chunk, filepath.stem)
                                results.append(RetrievedChunk(
                                    text=chunk.strip(),
                                    section=filepath.stem,
                                    symbol=sym,
                                    year=yr,
                                    doc_type=dt,
                                    page_start=-1,
                                    importance_score=float(score)
                                ))
                    except Exception:
                        pass
                        
        results.sort(key=lambda x: x.importance_score, reverse=True)
        return results[:top_k]
