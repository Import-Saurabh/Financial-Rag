import os
import re
import math
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Set, Any
import numpy as np

try:
    from sentence_transformers import SentenceTransformer, CrossEncoder
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    SentenceTransformer = None
    CrossEncoder = None

log = logging.getLogger(__name__)

@dataclass
class RetrievedChunk:
    text: str
    section: str = "Unknown"
    symbol: str = "Unknown"
    year: int = 0
    doc_type: str = "Unknown"
    page_start: int = 0
    section_type: str = "Unknown"
    importance_score: float = 0.0
    chunk_id: str = ""

    @property
    def score(self) -> float:
        return self.importance_score
        
    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "doc_type": self.doc_type,
            "symbol": self.symbol,
            "year": self.year,
            "section": self.section,
            "page_start": self.page_start
        }


def _parse_chunk_metadata(chunk_text: str, filename: str):
    sym = "Unknown"
    if "APOLLO" in filename or "apollo" in filename.lower(): sym = "APOLLO"
    elif "HAL" in filename or "hal" in filename.lower(): sym = "HAL"
    
    m_sym = re.search(r'\[SYMBOL:\s*([A-Za-z0-9_-]+)\]', chunk_text)
    if m_sym: sym = m_sym.group(1).upper()
    
    yr = 0
    m_yr = re.search(r'(?i)FY\s*(20\d{2}(?:-\d{2})?)', chunk_text)
    if m_yr: 
        try: yr = int(m_yr.group(1)[:4])
        except: pass
    elif "2024" in filename: yr = 2024
    elif "2025" in filename: yr = 2025
    elif "2026" in filename: yr = 2026
    
    dt = "annual_report"
    if "concall" in filename.lower() or "transcript" in chunk_text.lower():
        dt = "concall"
    
    return sym, yr, dt

def classify_section(chunk_text: str, filename: str) -> str:
    text = (filename + " " + chunk_text).lower()
    if "auditor" in text or "independent auditor" in text:
        return "auditor"
    if "management discussion" in text or "md&a" in text:
        return "mda"
    if "risk" in text:
        return "risk"
    if "financial" in text or "statement" in text or "balance sheet" in text or "profit and loss" in text:
        return "financials"
    if "corporate overview" in text or "about us" in text or "message" in text or "director" in text:
        return "overview"
    return "general"

_SYNONYMS = {
    "customer":     ["client", "buyer", "end-user", "counterparty", "purchaser", "user", "consumer"],
    "missile":      ["weapon", "munition", "armament", "projectile", "rocket"],
    "produce":      ["manufacture", "make", "build", "develop", "fabricate", "supply", "deliver"],
    "product":      ["system", "platform", "equipment", "solution", "offering", "device"],
    "revenue":      ["income", "turnover", "sales", "top-line", "topline"],
    "profit":       ["earnings", "pat", "net income", "bottom-line", "bottomline"],
    "supplier":     ["vendor", "partner", "subcontractor", "provider"],
    "defence":      ["defense", "military", "armed forces", "strategic"],
    "defense":      ["defence", "military", "armed forces", "strategic"],
    "order":        ["contract", "deal", "procurement", "tender", "award"],
    "growth":       ["increase", "expansion", "improvement", "surge", "uptick"],
    "subsidiary":   ["unit", "arm", "division", "group company"],
    "acquisition":  ["purchase", "takeover", "buyout", "merger"],
    "export":       ["overseas", "international", "global", "foreign"],
    "partner":      ["collaborator", "ally", "associate", "joint venture"],
    "strategy":     ["plan", "roadmap", "vision", "direction", "initiative"],
    "torpedo":      ["underwater weapon", "homing system", "naval weapon"],
    "mine":         ["naval mine", "ground mine", "undersea mine", "limpet"],
    "drone":        ["uav", "unmanned", "remotely piloted", "counter-drone"],
    "shareholder":  ["investor", "promoter", "stakeholder", "shareholding"],
}

def _expand_query_keywords(keywords: List[str]) -> List[str]:
    expanded = list(keywords)
    for kw in keywords:
        if kw in _SYNONYMS:
            expanded.extend(_SYNONYMS[kw])
    return expanded

def _extract_related_symbols(text: str, filename: str) -> Set[str]:
    symbols = set()
    text_lower = text.lower()
    company_patterns = {
        "APOLLO": ["apollo micro systems", "apollo defence", "apollo strategic", "apollo food",
                    "apollo employees", "apollo group", "apollo's", "nse symbol: apollo",
                    "nse: apollo", "apollo micro"],
        "HAL":    ["hindustan aeronautics", "hal "],
        "BEL":    ["bharat electronics", "bel "],
        "RELIANCE": ["reliance industries"],
        "TCS":    ["tata consultancy"],
    }
    for sym, patterns in company_patterns.items():
        if any(p in text_lower for p in patterns):
            symbols.add(sym)
    return symbols

_GLOBAL_INDEX_CACHE = {}
_GLOBAL_EMBEDDINGS_CACHE = {}
_MODEL_CACHE = {}

class FinancialRetriever:
    def __init__(self, wiki_dir: str = "backend/data/openkb_wiki"):
        self.wiki_dir = Path(wiki_dir).absolute()
        cache_key = str(self.wiki_dir)
        
        if 'encoder' not in _MODEL_CACHE and SentenceTransformer is not None:
            log.info("Loading SentenceTransformer model for dense retrieval...")
            _MODEL_CACHE['encoder'] = SentenceTransformer('all-MiniLM-L6-v2')
            
        if 'reranker' not in _MODEL_CACHE and CrossEncoder is not None:
            log.info("Loading CrossEncoder for reranking...")
            _MODEL_CACHE['reranker'] = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            
        self.encoder = _MODEL_CACHE.get('encoder')
        self.reranker = _MODEL_CACHE.get('reranker')
        
        if cache_key in _GLOBAL_INDEX_CACHE:
            self.index = _GLOBAL_INDEX_CACHE[cache_key]
            self.embeddings = _GLOBAL_EMBEDDINGS_CACHE.get(cache_key)
            self._idf_table = _GLOBAL_INDEX_CACHE.get(cache_key + "_idf", {})
        else:
            self.index = []
            self.embeddings = None
            self._idf_table = {}
            self._build_index()
            _GLOBAL_INDEX_CACHE[cache_key] = self.index
            _GLOBAL_EMBEDDINGS_CACHE[cache_key] = self.embeddings
            _GLOBAL_INDEX_CACHE[cache_key + "_idf"] = getattr(self, '_idf_table', {})
            
    def _build_index(self):
        wiki_base = self.wiki_dir / "wiki"
        if not wiki_base.exists(): return
            
        for root, _, files in os.walk(wiki_base):
            for file in files:
                if file.endswith(".md"):
                    filepath = Path(root) / file
                    if "images" in str(filepath): continue
                    try:
                        content = filepath.read_text(encoding="utf-8")
                        rel_path = filepath.relative_to(wiki_base)
                        wiki_subdir = str(rel_path.parts[0]) if len(rel_path.parts) > 1 else ""
                        if wiki_subdir in ("entities", "concepts"):
                            self._index_entity_or_concept(content, filepath, wiki_subdir)
                        else:
                            self._index_chunked(content, filepath)
                    except Exception as e:
                        log.error(f"Error indexing {file}: {e}")
        
        self._build_idf()
        self._build_embeddings()
        log.info(f"[OpenKB] Indexed {len(self.index)} chunks. Embeddings shape: {self.embeddings.shape if self.embeddings is not None else 'None'}")

    def _index_entity_or_concept(self, content: str, filepath: Path, wiki_subdir: str):
        sym, yr, dt = _parse_chunk_metadata(content, filepath.stem)
        related_syms = _extract_related_symbols(content, filepath.stem)
        if related_syms and sym == "Unknown":
            sym = next(iter(related_syms))
        
        sec_type = "entity" if wiki_subdir == "entities" else "concept"
        dt = sec_type
        
        sections = re.split(r'\n(?=## )', content)
        title_match = re.match(r'^(?:---.*?---\s*)?#\s+(.*)', content, re.DOTALL)
        title = ""
        if title_match:
            h1_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if h1_match: title = h1_match.group(1).strip()
        
        for section in sections:
            section = section.strip()
            if not section or len(section) < 50: continue
            h2_match = re.match(r'^##\s+(.*)', section)
            heading = h2_match.group(1).strip() if h2_match else title
            text_to_store = f"{title}\n{section}" if title and title not in section else section
            
            self.index.append({
                'text': text_to_store,
                'section': filepath.stem,
                'symbol': sym,
                'related_symbols': related_syms,
                'year': yr,
                'doc_type': dt,
                'page_start': -1,
                'section_type': sec_type,
                'heading': heading,
                'wiki_subdir': wiki_subdir,
                'word_count': len(section.split()),
            })

    def _index_chunked(self, content: str, filepath: Path):
        raw_chunks = re.split(r'\n(?=#)|\n\n+', content)
        current_heading = ""
        for chunk in raw_chunks:
            chunk = chunk.strip()
            if not chunk: continue
            m_head = re.match(r'^(#+)\s+(.*)', chunk)
            if m_head: current_heading = m_head.group(2)
            page_start = -1
            page_match = re.search(r'(?i)page\s*(\d+)', chunk)
            if not page_match: page_match = re.search(r'(?m)^\s*(\d+)\s*$', chunk)
            if page_match: page_start = int(page_match.group(1))
            sym, yr, dt = _parse_chunk_metadata(chunk, filepath.stem)
            sec_type = classify_section(chunk, filepath.stem)
            text_to_store = f"{current_heading}\n{chunk}" if current_heading and current_heading not in chunk else chunk
            
            self.index.append({
                'text': text_to_store,
                'section': filepath.stem,
                'symbol': sym,
                'related_symbols': set(),
                'year': yr,
                'doc_type': dt,
                'page_start': page_start,
                'section_type': sec_type,
                'heading': current_heading,
                'wiki_subdir': 'summaries',
                'word_count': len(chunk.split()),
            })

    def _build_idf(self):
        self._idf_table = {}
        N = len(self.index)
        if N == 0: return
        df = {}
        for item in self.index:
            words = set(item['text'].lower().split())
            for w in words: df[w] = df.get(w, 0) + 1
        for term, freq in df.items():
            self._idf_table[term] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)
            
    def _build_embeddings(self):
        if not self.index or self.encoder is None:
            self.embeddings = None
            return
        log.info("Computing dense embeddings for all chunks...")
        texts = [item['text'] for item in self.index]
        self.embeddings = self.encoder.encode(texts, show_progress_bar=False)

    def _is_relationship_query(self, query: str) -> bool:
        relationship_keywords = {
            "customer", "client", "buyer", "who", "partner", "supplier", "vendor",
            "subsidiary", "group", "acquisition", "product", "system", "missile", 
            "torpedo", "mine", "weapon", "drone", "radar", "navigation", "avionics",
            "manufacture", "produce", "make", "build", "develop", "export", "import", 
            "deal", "contract", "order", "technology", "capability", "platform",
        }
        words = set(query.lower().split())
        return bool(words & relationship_keywords)

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        symbol_filter: Optional[List[str]] = None,
        section_filter: Optional[List[str]] = None,
    ) -> List[RetrievedChunk]:
        stopwords = {"what", "is", "the", "for", "and", "how", "has", "are", "was", "been",
                      "from", "with", "this", "that", "its", "will", "can", "does", "did",
                      "about", "over", "which", "their", "they", "have", "were", "our", "any",
                      "show", "me", "tell", "give", "list", "please", "could", "would",
                      "do", "you", "know", "of", "in", "on", "at", "to", "a", "an", "by"}
        
        raw_keywords = [w.lower() for w in question.split() if w.lower() not in stopwords and len(w) >= 2]
        if not raw_keywords: return []

        keywords = _expand_query_keywords(raw_keywords)
        is_relational = self._is_relationship_query(question)
        
        # Sparse BM25 setup
        k1 = 1.5; b = 0.75
        total_words = sum(item.get('word_count', len(item['text'].split())) for item in self.index)
        avg_dl = total_words / max(len(self.index), 1)
        
        # Dense Semantic Search setup
        dense_scores = None
        if self.embeddings is not None and self.encoder is not None:
            q_emb = self.encoder.encode([question])
            dense_scores = cosine_similarity(q_emb, self.embeddings)[0]

        results = []
        for i, item in enumerate(self.index):
            if symbol_filter:
                allowed_syms = {s.upper() for s in symbol_filter}
                item_sym = item['symbol'].upper()
                related_syms = {s.upper() for s in item.get('related_symbols', set())}
                wiki_subdir = item.get('wiki_subdir', '')
                if wiki_subdir in ('entities', 'concepts'):
                    if item_sym not in allowed_syms and not (related_syms & allowed_syms):
                        continue
                else:
                    if item_sym not in allowed_syms:
                        continue
                    
            text_lower = item['text'].lower()
            heading_lower = item['heading'].lower()
            doc_len = item.get('word_count', len(item['text'].split()))
            
            # Sparse Score
            bm25_score = 0.0
            matched_original_keywords = 0
            for k_idx, kw in enumerate(keywords):
                count = text_lower.count(kw)
                if count > 0:
                    tf = (count * (k1 + 1)) / (count + k1 * (1 - b + b * doc_len / max(avg_dl, 1)))
                    idf = self._idf_table.get(kw, 1.0)
                    weight = 1.0 if k_idx < len(raw_keywords) else 0.4
                    bm25_score += tf * idf * weight
                    if k_idx < len(raw_keywords): matched_original_keywords += 1
                    if kw in heading_lower: bm25_score += 0.5 * idf * weight
            
            if len(raw_keywords) > 1:
                coverage = matched_original_keywords / len(raw_keywords)
                bm25_score *= (0.5 + 0.5 * coverage)
                        
            # Dense Score
            d_score = dense_scores[i] if dense_scores is not None else 0.0
            
            # Hybrid Score
            final_score = (bm25_score * 0.3) + (max(0, d_score) * 12.0)
            
            # First-pass filter
            if final_score <= 0.5:
                continue

            if section_filter and item['section_type'] in section_filter: final_score *= 1.3
            if item['section_type'] == 'auditor': final_score *= 0.3
                
            wiki_subdir = item.get('wiki_subdir', '')
            if is_relational and wiki_subdir in ('entities', 'concepts'): final_score *= 2.0
            elif wiki_subdir in ('entities', 'concepts'): final_score *= 1.3
            
            if wiki_subdir == 'sources' and doc_len > 2000: final_score *= 0.6
                
            results.append(RetrievedChunk(
                text=item['text'],
                section=item['section'],
                section_type=item['section_type'],
                symbol=item['symbol'],
                year=item['year'],
                doc_type=item['doc_type'],
                page_start=item['page_start'],
                importance_score=float(final_score)
            ))
                
        # Stage 1: Sort by Hybrid Score and take top 15 candidates for re-ranking
        results.sort(key=lambda x: x.importance_score, reverse=True)
        candidates = results[:15]
        
        # Stage 2: Cross-Encoder Re-ranking (High Precision)
        if candidates and hasattr(self, 'reranker') and self.reranker is not None:
            pairs = [[question, chunk.text] for chunk in candidates]
            try:
                rerank_scores = self.reranker.predict(pairs)
                for chunk, r_score in zip(candidates, rerank_scores):
                    chunk.importance_score = float(r_score) + (chunk.importance_score * 0.1)
                
                candidates.sort(key=lambda x: x.importance_score, reverse=True)
            except Exception as e:
                log.error(f"CrossEncoder reranking failed: {e}")
                
        top_candidates = candidates[:top_k]
        
        # Stage 3: Evidence Expansion (fetch adjacent chunks to capture cross-page tables)
        expanded_results = []
        for candidate in top_candidates:
            expanded_results.append(candidate)
            # Find chunks from the same section/file
            same_doc_chunks = [c for c in self.index if c['section'] == candidate.section]
            if not same_doc_chunks:
                continue
                
            # Find candidate index in original doc chunks
            idx = -1
            for j, c in enumerate(same_doc_chunks):
                if c['text'] == candidate.text:
                    idx = j
                    break
                    
            if idx != -1:
                # Add previous chunk if it exists and hasn't been added
                if idx > 0:
                    prev_c = same_doc_chunks[idx - 1]
                    if not any(r.text == prev_c['text'] for r in expanded_results):
                        expanded_results.append(RetrievedChunk(
                            text=prev_c['text'], section=prev_c['section'],
                            section_type=candidate.section_type, symbol=candidate.symbol,
                            year=candidate.year, doc_type=candidate.doc_type,
                            page_start=prev_c.get('page_start', -1), importance_score=candidate.importance_score * 0.8
                        ))
                # Add next chunk if it exists and hasn't been added
                if idx < len(same_doc_chunks) - 1:
                    next_c = same_doc_chunks[idx + 1]
                    if not any(r.text == next_c['text'] for r in expanded_results):
                        expanded_results.append(RetrievedChunk(
                            text=next_c['text'], section=next_c['section'],
                            section_type=candidate.section_type, symbol=candidate.symbol,
                            year=candidate.year, doc_type=candidate.doc_type,
                            page_start=next_c.get('page_start', -1), importance_score=candidate.importance_score * 0.8
                        ))

        return expanded_results[:(top_k * 2)] # Return expanded context to LLM
