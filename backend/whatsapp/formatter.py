import re
from typing import List


def format_for_whatsapp(text: str) -> str:
    """
    Convert Markdown to WhatsApp-compatible text formatting.
    - Standard markdown bold **text** -> *text*
    - Headers # / ## / ### -> *Header*
    - [Title](URL) -> Title (URL)
    - Clean up excessive blank lines
    """
    if not text:
        return ""

    formatted = text.strip()

    # 1. Convert headers (# Header -> *Header*)
    formatted = re.sub(r'^(?:#{1,6})\s+(.+)$', r'*\1*', formatted, flags=re.MULTILINE)

    # 2. Convert standard markdown bold **word** -> *word*
    formatted = re.sub(r'\*\*(.+?)\*\*', r'*\1*', formatted)

    # 3. Convert markdown links [Text](URL) -> Text: URL
    formatted = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\1: \2', formatted)

    # 4. Remove unsupported HTML tags
    formatted = re.sub(r'<[^>]+>', '', formatted)

    # 5. Clean up code blocks if they are chart JSON
    formatted = re.sub(r'```json:financial-charts[\s\S]*?```', '', formatted)

    # 6. Normalize multiple consecutive newlines (max 2)
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)

    return formatted.strip()


def _chunk_by_words(text: str, max_length: int) -> List[str]:
    """Helper to break a line with no newlines into chunks by word boundaries."""
    words = text.split(" ")
    chunks = []
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > max_length:
            if current:
                chunks.append(current.strip())
            current = w + " "
        else:
            current += w + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


def split_message(text: str, max_length: int = 3800) -> List[str]:
    """
    Split a long message into WhatsApp-friendly chunks within max_length,
    preserving paragraph and sentence boundaries.
    Adds (Part X/Y) if split into multiple messages.
    """
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        if len(para) > max_length:
            # Check if there are newline breaks
            lines = para.split("\n") if "\n" in para else _chunk_by_words(para, max_length)
            for line in lines:
                if len(line) > max_length:
                    sub_chunks = _chunk_by_words(line, max_length)
                    for sc in sub_chunks:
                        if len(current_chunk) + len(sc) + 1 > max_length:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sc + " "
                        else:
                            current_chunk += sc + " "
                else:
                    if len(current_chunk) + len(line) + 2 > max_length:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = line + "\n"
                    else:
                        current_chunk += line + "\n"
        else:
            if len(current_chunk) + len(para) + 2 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    total = len(chunks)
    if total <= 1:
        return chunks

    # Add (Part i/total) headers
    tagged_chunks = []
    for i, chunk in enumerate(chunks, 1):
        header = f"📄 *[Part {i}/{total}]*\n\n"
        tagged_chunks.append(header + chunk)

    return tagged_chunks
