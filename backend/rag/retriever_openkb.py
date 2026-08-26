import subprocess
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any
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


class OpenKBRetriever:
    def __init__(self, wiki_dir: str = "backend/data/openkb_wiki"):
        self.wiki_dir = Path(wiki_dir).absolute()
        
    def retrieve(self, question: str, top_k: int = 5) -> List[RetrievedChunk]:
        """
        Retrieves relevant pages using OpenKB tree index.
        """
        evidence = []
        try:
            openkb_cmd = r"C:\Users\hp\AppData\Roaming\Python\Python310\Scripts\openkb.exe"
            result = subprocess.run(
                [openkb_cmd, "query", question, "--json", f"--top-k={top_k}"],
                cwd=self.wiki_dir,
                capture_output=True,
                text=True,
                timeout=10,
                shell=(os.name == "nt")
            )
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    # OpenKB typically outputs a list of results in JSON format
                    for item in data.get("results", []):
                        evidence.append(RetrievedChunk(
                            text=item.get("summary", "") or item.get("text", ""),
                            section=item.get("section_title", "Unknown Section"),
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
            
        # Fallback Logic: if empty or failed
        if not evidence:
            evidence = self._fallback_keyword_search(question, top_k)
            
        return evidence[:top_k]
        
    def _fallback_keyword_search(self, question: str, top_k: int = 5) -> List[RetrievedChunk]:
        """
        Simple keyword search across text files in the wiki directory.
        """
        import re
        keywords = [w.lower() for w in question.split() if len(w) > 3]
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
                            
                            # Naive scoring
                            score = sum(chunk_lower.count(k) for k in keywords)
                            if score > 0:
                                results.append(RetrievedChunk(
                                    text=chunk.strip(),
                                    section=filepath.stem,
                                    page_start=-1,
                                    importance_score=float(score)
                                ))
                    except Exception:
                        pass
                        
        # Sort by score descending and take top_k
        results.sort(key=lambda x: x.importance_score, reverse=True)
        return results[:top_k]



