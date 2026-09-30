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
        self.wiki_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "openkb_wiki", "wiki"
        )
        self.api_url = "https://zhwbvtkibdyhjy42gubo3qbsxq0pifuv.lambda-url.ap-south-1.on.aws/api/v1/stocks"
        self._update_lock = threading.Lock()

    def _clean_name(self, name: str) -> str:
        name = name.lower()
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
        aliases_to_add.add(clean_n)
        
        # Split into words/phrases
        words = clean_n.split()
        if len(words) > 1:
            aliases_to_add.add(words[0])
            
        for alias in aliases_to_add:
            if alias not in self.aliases: # simple conflict resolution
                self.aliases[alias] = (ticker, name)

    def _fetch_api(self):
        try:
            req = urllib.request.Request(self.api_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                # assume data is list of dicts with 'symbol' and 'name'
                if isinstance(data, list):
                    for item in data:
                        symbol = item.get('symbol')
                        name = item.get('name')
                        if symbol and name:
                            self._add_entity(symbol, name)
        except Exception as e:
            log.warning(f"Failed to fetch stocks from API: {e}")

    def _scan_wiki(self):
        if not os.path.exists(self.wiki_path):
            return
            
        for root, dirs, files in os.walk(self.wiki_path):
            for file in files:
                if file.endswith(".md"):
                    path = os.path.join(root, file)
                    # Use filename as potential hint
                    filename_base = os.path.splitext(file)[0].upper()
                    
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                            # Simple heuristics to find symbol/name
                            symbol_match = re.search(r'(?:BSE:\s*(\d+)|Symbol:\s*([A-Z0-9]+))', content)
                            symbol = None
                            if symbol_match:
                                symbol = symbol_match.group(1) or symbol_match.group(2)
                            
                            if not symbol:
                                symbol = filename_base
                                
                            name_match = re.search(r'^#\s*(.+)', content, re.MULTILINE)
                            name = name_match.group(1).strip() if name_match else filename_base
                            
                            if symbol and name:
                                self._add_entity(symbol, name)
                    except Exception as e:
                        log.debug(f"Error reading wiki file {path}: {e}")

    def refresh(self, force=False):
        now = time.time()
        if force or (now - self.last_update) > self.ttl:
            with self._update_lock:
                if force or (now - self.last_update) > self.ttl:
                    log.info("Refreshing entity registry index...")
                    self.aliases.clear()
                    self.tickers_to_names.clear()
                    self._fetch_api()
                    self._scan_wiki()
                    self.last_update = time.time()
                    log.info(f"Entity registry refreshed. {len(self.tickers_to_names)} entities loaded.")

    def resolve(self, query: str) -> Optional[Tuple[str, str]]:
        self.refresh()
        query_clean = self._clean_name(query)
        words = query_clean.split()
        
        # Check exact matches first
        if query_clean in self.aliases:
            return self.aliases[query_clean]
            
        for word in words:
            if word in self.aliases:
                return self.aliases[word]
                
        # Try fuzzy match on the query against keys in self.aliases
        candidates = list(self.aliases.keys())
        matches = difflib.get_close_matches(query_clean, candidates, n=1, cutoff=0.7)
        if matches:
            return self.aliases[matches[0]]
            
        # Try fuzzy match for individual words
        for word in words:
            if len(word) > 3:
                matches = difflib.get_close_matches(word, candidates, n=1, cutoff=0.8)
                if matches:
                    return self.aliases[matches[0]]
                    
        return None

# Singleton instance
_registry = EntityRegistry()

def resolve_entity(query: str) -> Optional[Tuple[str, str]]:
    """Returns (ticker, company_name) or None."""
    return _registry.resolve(query)
