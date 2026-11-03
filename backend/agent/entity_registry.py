import os
import re
import json
import time
import logging
import difflib
import threading
import urllib.request
from typing import Optional, Tuple, Dict, Set, List

log = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "of", "in", "for", "and", "or", "is", "at", "to", "by", "on", 
    "with", "from", "as", "about", "what", "which", "how", "who", "when", "where", "why",
    "tell", "me", "show", "give", "concept", "concepts", "summary", "summaries", "entity",
    "entities", "note", "notes", "part", "report", "annual", "quarterly", "limited", "ltd",
    "private", "pvt", "company", "corporation", "corp", "inc", "revenue", "profit", "ebitda",
    "margin", "margins", "debt", "balance", "sheet", "cash", "flow", "ratio", "ratios",
    "growth", "eps", "pat", "pbt", "sales", "concall", "transcript", "guidance"
}

# Pre-seeded common tickers and companies to ensure instantaneous, offline-ready resolution
KNOWN_STOCKS = {
    "APOLLO": "Apollo Micro Systems Limited",
    "HAL": "Hindustan Aeronautics Limited",
    "MTARTECH": "MTAR Technologies Limited",
    "RELIANCE": "Reliance Industries Limited",
    "BEL": "Bharat Electronics Limited",
    "BDL": "Bharat Dynamics Limited",
    "PARAS": "Paras Defence and Space Technologies",
    "COCHINSHIP": "Cochin Shipyard Limited",
    "MAZDOCK": "Mazagon Dock Shipbuilders Limited",
    "TCS": "Tata Consultancy Services Limited",
    "INFY": "Infosys Limited",
    "HDFCBANK": "HDFC Bank Limited",
    "ICICIBANK": "ICICI Bank Limited",
    "SBIN": "State Bank of India",
    "LT": "Larsen & Toubro Limited",
    "TITAN": "Titan Company Limited",
    "TATASTEEL": "Tata Steel Limited",
    "TATAMOTORS": "Tata Motors Limited",
    "ITC": "ITC Limited",
    "ASTRAL": "Astral Limited",
    "ZEN": "Zen Technologies Limited",
    "BEML": "BEML Limited",
    "PREMIER": "Premier Explosives Limited",
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
        self.aliases: Dict[str, Tuple[str, str]] = {}
        self.tickers_to_names: Dict[str, str] = {}
        self.last_update = 0
        self.ttl = 30 * 60  # 30 minutes
        self.wiki_entities_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "openkb_wiki", "wiki", "entities"
        )
        try:
            from config.settings import FINRAG_API_BASE
        except ImportError:
            FINRAG_API_BASE = "https://zhwbvtkibdyhjy42gubo3qbsxq0pifuv.lambda-url.ap-south-1.on.aws"

        self.api_url = f"{FINRAG_API_BASE.rstrip('/')}/api/v1/stocks"
        self._update_lock = threading.Lock()

        # 1. Immediately seed known stocks
        for ticker, name in KNOWN_STOCKS.items():
            self._add_entity(ticker, name)

        # 2. Add high-frequency manual aliases
        self.aliases["ams"] = ("APOLLO", "Apollo Micro Systems Limited")
        self.aliases["apollo micro"] = ("APOLLO", "Apollo Micro Systems Limited")
        self.aliases["apollo micro systems"] = ("APOLLO", "Apollo Micro Systems Limited")
        self.aliases["mtar"] = ("MTARTECH", "MTAR Technologies Limited")
        self.aliases["mtar tech"] = ("MTARTECH", "MTAR Technologies Limited")
        self.aliases["ril"] = ("RELIANCE", "Reliance Industries Limited")

        # 3. Synchronously scan local wiki entities (takes <20ms)
        self._scan_wiki_entities()
        self.last_update = time.time()

        # 4. Asynchronously fetch from remote API in background thread so caller never blocks
        threading.Thread(target=self._fetch_api, daemon=True).start()

    def _clean_text(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        return ' '.join(text.split())

    def _clean_name(self, name: str) -> str:
        name = self._clean_text(name)
        suffixes = [" limited", " ltd", " inc", " corp", " corporation"]
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
        return name.strip()

    def _add_entity(self, ticker: str, name: str):
        ticker = ticker.upper()
        self.tickers_to_names[ticker] = name
        
        # Add aliases mapping back to (ticker, name)
        aliases_to_add = set()
        aliases_to_add.add(ticker.lower())
        
        clean_n = self._clean_name(name)
        if clean_n and clean_n not in STOPWORDS:
            aliases_to_add.add(clean_n)
        
        # Split into words/phrases
        words = [w for w in clean_n.split() if w not in STOPWORDS and len(w) >= 3]
        if words:
            # Single distinctive first word (e.g. "apollo", "reliance", "paras")
            aliases_to_add.add(words[0])
            if len(words) > 1:
                aliases_to_add.add(f"{words[0]} {words[1]}")
            
        for alias in aliases_to_add:
            if alias not in STOPWORDS:
                # Do not overwrite high-priority exact ticker mappings with generic aliases
                if alias not in self.aliases:
                    self.aliases[alias] = (ticker, name)

    def _fetch_api(self):
        try:
            req = urllib.request.Request(self.api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=2.0) as response:
                payload = json.loads(response.read().decode())
                
                # Remote API returns {'data': [...], 'meta': ...} or a direct list
                items = payload.get('data', []) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    for item in items:
                        symbol = item.get('symbol')
                        name = item.get('name')
                        if not name and symbol:
                            name = KNOWN_STOCKS.get(symbol.upper(), symbol)
                        if symbol and name:
                            self._add_entity(symbol, name)
            log.info(f"EntityRegistry updated from API. Total entities: {len(self.tickers_to_names)}")
        except Exception as e:
            log.warning(f"Failed to fetch stocks from API (using cached/local entities): {e}")

    def _scan_wiki_entities(self):
        if not os.path.exists(self.wiki_entities_path):
            return
            
        for file in os.listdir(self.wiki_entities_path):
            if file.endswith(".md"):
                path = os.path.join(self.wiki_entities_path, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        symbol_match = re.search(r'(?:NSE Symbol:\s*|Symbol:\s*)([A-Z0-9]+)', content)
                        symbol = symbol_match.group(1).strip() if symbol_match else None
                        
                        name_match = re.search(r'^#\s*(.+)', content, re.MULTILINE)
                        name = name_match.group(1).strip() if name_match else None
                        
                        # Only register if explicitly identified as stock or organization
                        if symbol and name and not name.startswith("#"):
                            self._add_entity(symbol, name)
                except Exception as e:
                    log.debug(f"Error reading wiki entity file {path}: {e}")

    def refresh(self, force=False):
        now = time.time()
        if force or (now - self.last_update) > self.ttl:
            # Refresh in background so queries are never blocked
            self.last_update = now
            threading.Thread(target=self._fetch_api, daemon=True).start()

    def resolve(self, query: str) -> Optional[Tuple[str, str]]:
        self.refresh()
        query_clean = self._clean_text(query)
        if not query_clean:
            return None
            
        # 1. Exact match on clean query
        if query_clean in self.aliases:
            return self.aliases[query_clean]

        # 2. Match whole-word token boundary with longest alias first
        sorted_aliases = sorted(self.aliases.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if re.search(r'\b' + re.escape(alias) + r'\b', query_clean):
                return self.aliases[alias]
                
        # 3. Fallback: Fuzzy match against candidate aliases
        words = [w for w in query_clean.split() if w not in STOPWORDS and len(w) >= 3]
        candidates = list(self.aliases.keys())
        for word in words:
            matches = difflib.get_close_matches(word, candidates, n=1, cutoff=0.82)
            if matches:
                return self.aliases[matches[0]]
                    
        return None

# Singleton instance
_registry = EntityRegistry()

def resolve_entity(query: str) -> Optional[Tuple[str, str]]:
    """Returns (ticker, company_name) or None."""
    return _registry.resolve(query)
