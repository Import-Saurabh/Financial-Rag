"""Structured query metrics for performance tracking and debugging."""
import time
import logging
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List
from pathlib import Path

logger = logging.getLogger("rag_metrics")
logger.setLevel(logging.INFO)

# Setup file handler
log_file = Path(__file__).parent.parent / "logs" / "query_metrics.jsonl"
log_file.parent.mkdir(parents=True, exist_ok=True)

handler = logging.FileHandler(log_file)
handler.setFormatter(logging.Formatter('%(message)s'))
if not logger.handlers:
    logger.addHandler(handler)

@dataclass
class QueryMetrics:
    query: str
    entity: str = ""
    model: str = ""
    total_ms: int = 0
    bridge_ms: int = 0
    retrieval_ms: int = 0
    synthesis_ms: int = 0
    chunks_retrieved: int = 0
    chunks_used: int = 0
    sql_rows: int = 0
    citations: int = 0
    confidence: float = 0.0
    pipeline_mode: str = ""
    sections_searched: List[str] = field(default_factory=list)
    error: str = ""
    
    def log(self):
        """Log metrics as structured JSON for easy parsing."""
        logger.info(json.dumps(asdict(self), default=str))
    
    def to_dict(self) -> dict:
        return asdict(self)

class Timer:
    """Context manager for timing code blocks."""
    def __init__(self):
        self.elapsed_ms = 0
        self._start = 0.0
    
    def __enter__(self):
        self._start = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
