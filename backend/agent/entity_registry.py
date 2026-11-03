import os
import json
import time
import logging
import threading
import urllib.request
from difflib import SequenceMatcher
from typing import Optional, Tuple, Dict, Set, List, Any

log = logging.getLogger(__name__)

# Common financial stop words to avoid false positive token matches
COMMON_FINANCIAL_TOKENS = {
    "ltd", "limited", "inc", "corp", "corporation", "company", "technologies",
    "systems", "enterprises", "industries", "holdings", "group", "india",
    "what", "when", "where", "which", "who", "whom", "this", "that", "these",
    "those", "with", "from", "into", "during", "including", "until", "against",
    "among", "throughout", "despite", "towards", "upon", "concerning", "about",
    "tell", "show", "give", "please", "annual", "quarterly", "report", "transcript",
    "concall", "guidance", "revenue", "profit", "ebitda", "margin", "margins",
    "debt", "balance", "sheet", "cash", "flow", "ratio", "ratios", "growth",
    "capex", "sales", "earnings", "price", "stock", "share", "value", "trend"
}

class EntityRegistry:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EntityRegistry, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.entities: Dict[str, Dict[str, Any]] = {}
        self.last_update = 0
        self.ttl = 30 * 60  # 30 minutes
        self._update_lock = threading.Lock()
        
        self.wiki_entities_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "openkb_wiki", "wiki", "entities"
        )
        try:
            from config.settings import FINRAG_API_BASE, GROQ_API_KEY
        except ImportError:
            FINRAG_API_BASE = "https://zhwbvtkibdyhjy42gubo3qbsxq0pifuv.lambda-url.ap-south-1.on.aws"
            GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

        self.api_url = f"{FINRAG_API_BASE.rstrip('/')}/api/v1/stocks"
        self.groq_api_key = GROQ_API_KEY

        # High-frequency acronyms mapping to canonical tickers
        self.acronyms: Dict[str, str] = {
            "ams": "APOLLO",
            "ril": "RELIANCE",
            "mtar": "MTARTECH",
            "tcs": "TCS",
            "infy": "INFY",
            "sbi": "SBIN",
            "lt": "LT",
        }

        # 1. Synchronously scan OpenKB entity wiki docs (<15ms)
        self._scan_wiki_entities()

        # 2. Asynchronously fetch latest universe from remote API in background thread
        threading.Thread(target=self._fetch_api, daemon=True).start()

    def _normalize_text(self, text: str) -> str:
        """Normalizes text without regex: replaces punctuation with spaces."""
        return "".join(c if c.isalnum() else " " for c in text.lower())

    def _tokenize(self, text: str) -> List[str]:
        return [w for w in self._normalize_text(text).split() if len(w) >= 2]

    def _add_entity(self, ticker: str, name: str, description: str = ""):
        ticker = ticker.upper()
        norm_name = self._normalize_text(name)
        tokens = set(self._tokenize(name)) - COMMON_FINANCIAL_TOKENS

        self.entities[ticker] = {
            "symbol": ticker,
            "name": name,
            "norm_name": norm_name,
            "tokens": tokens,
            "description": description.strip()
        }

    def _fetch_api(self):
        try:
            req = urllib.request.Request(self.api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2.0) as response:
                payload = json.loads(response.read().decode())
                items = payload.get('data', []) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    for item in items:
                        symbol = item.get('symbol')
                        name = item.get('name') or symbol
                        if symbol:
                            self._add_entity(symbol, name)
            log.info(f"[EntityRegistry] Synced {len(self.entities)} entities from remote API.")
        except Exception as e:
            log.debug(f"[EntityRegistry] Background API sync note: {e}")

    def _scan_wiki_entities(self):
        if not os.path.exists(self.wiki_entities_path):
            return
            
        for file in os.listdir(self.wiki_entities_path):
            if file.endswith(".md"):
                path = os.path.join(self.wiki_entities_path, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        # Extract symbol, title, and description from frontmatter/markdown
                        symbol = None
                        name = None
                        description = ""

                        for line in content.splitlines():
                            line_strip = line.strip()
                            if line_strip.startswith("description:"):
                                description = line_strip.split("description:", 1)[1].strip(" \"'")
                            elif "NSE Symbol:" in line:
                                symbol = line.split("NSE Symbol:", 1)[1].split(";")[0].split()[0].strip()
                            elif line_strip.startswith("# ") and not name:
                                name = line_strip[2:].strip()

                        if not symbol and file == "apollo_micro_systems_limited.md":
                            symbol = "APOLLO"
                            name = name or "Apollo Micro Systems Limited"

                        if symbol and name and not name.startswith("#"):
                            self._add_entity(symbol, name, description)
                except Exception as e:
                    log.debug(f"[EntityRegistry] Error reading wiki entity {file}: {e}")

    def _fuzzy_resolve(self, query: str) -> Optional[Tuple[str, str]]:
        q_tokens = set(self._tokenize(query))
        q_norm = self._normalize_text(query)

        # 1. Exact symbol match (e.g. "HAL", "APOLLO", "BEL")
        for sym, data in self.entities.items():
            if sym.lower() in q_tokens:
                return sym, data["name"]

        # 2. Known market acronyms (e.g. "AMS" -> APOLLO, "RIL" -> RELIANCE, "MTAR" -> MTARTECH)
        for acr, sym in self.acronyms.items():
            if acr in q_tokens and sym in self.entities:
                return sym, self.entities[sym]["name"]

        # 3. Multi-word or distinct brand name match (e.g. "Apollo Micro", "Hindustan Aeronautics")
        best_sym = None
        best_score = 0.0

        for sym, data in self.entities.items():
            # Check distinctive tokens
            distinct_tokens = data["tokens"]
            matched_tokens = distinct_tokens & q_tokens
            if matched_tokens:
                # If a significant distinctive token is present, calculate token coverage
                coverage = len(matched_tokens) / max(len(distinct_tokens), 1)
                score = 0.8 + (0.2 * coverage)
                if score > best_score:
                    best_score = score
                    best_sym = sym

            # Check sequence similarity against normalized company name
            ratio = SequenceMatcher(None, q_norm, data["norm_name"]).ratio()
            if ratio > best_score and ratio > 0.65:
                best_score = ratio
                best_sym = sym

        if best_sym and best_score >= 0.8:
            return best_sym, self.entities[best_sym]["name"]

        return None

    async def aresolve(self, query: str) -> Optional[Tuple[str, str]]:
        """
        Asynchronously resolves entity.
        Fast fuzzy token match first (0ms), then falls back to Groq LLM semantic extraction (~300ms).
        """
        # Step 1: Fast fuzzy / token match
        res = self._fuzzy_resolve(query)
        if res:
            return res

        # Step 2: Semantic LLM extraction via Groq for natural language / descriptive queries
        if self.groq_api_key:
            try:
                from groq import AsyncGroq
                client = AsyncGroq(api_key=self.groq_api_key)
                known_symbols = list(self.entities.keys())
                prompt = (
                    f"User query: '{query}'\n"
                    f"Extract the relevant Indian stock ticker symbol (NSE) and company name.\n"
                    f"Candidate symbols in universe: {', '.join(known_symbols[:20])}\n"
                    "Respond ONLY with a JSON object: {\"symbol\": \"TICKER_OR_NULL\", \"company\": \"NAME_OR_NULL\"}"
                )
                resp = await client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=[
                        {"role": "system", "content": "You are a financial entity resolver for Indian equities. Always return valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.0,
                    max_tokens=60
                )
                raw_text = resp.choices[0].message.content.strip()
                parsed = json.loads(raw_text)
                sym = parsed.get("symbol")
                company = parsed.get("company")
                if sym and sym.upper() in self.entities:
                    return sym.upper(), self.entities[sym.upper()]["name"]
                elif sym and sym.upper() != "NULL":
                    return sym.upper(), company or sym.upper()
            except Exception as e:
                log.debug(f"[EntityRegistry] LLM fallback note: {e}")

        return None

    def resolve(self, query: str) -> Optional[Tuple[str, str]]:
        """Synchronous wrapper for resolve."""
        return self._fuzzy_resolve(query)

# Singleton instance
_registry = EntityRegistry()

def resolve_entity(query: str) -> Optional[Tuple[str, str]]:
    """Returns (ticker, company_name) or None."""
    return _registry.resolve(query)

async def aresolve_entity(query: str) -> Optional[Tuple[str, str]]:
    """Asynchronously resolves (ticker, company_name) or None with LLM fallback."""
    return await _registry.aresolve(query)
