from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
	chunk_id: int
	text: str


def chunk_text(text: str, *, max_chars: int = 2000, overlap_chars: int = 200) -> list[TextChunk]:
	"""Split long text into overlapping chunks.

	This is intentionally simple (char-based) so it works without external
	tokenizers. It can be replaced later with a smarter semantic chunker.
	"""

	if max_chars <= 0:
		raise ValueError("max_chars must be > 0")
	if overlap_chars < 0:
		raise ValueError("overlap_chars must be >= 0")
	if overlap_chars >= max_chars:
		raise ValueError("overlap_chars must be < max_chars")

	normalized = (text or "").strip()
	if not normalized:
		return []

	chunks: list[TextChunk] = []
	start = 0
	chunk_id = 1
	length = len(normalized)

	while start < length:
		end = min(start + max_chars, length)

		# Try to end on a nice boundary.
		window = normalized[start:end]
		boundary = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
		if boundary > int(max_chars * 0.6):
			end = start + boundary + 1

		chunk_text_value = normalized[start:end].strip()
		if chunk_text_value:
			chunks.append(TextChunk(chunk_id=chunk_id, text=chunk_text_value))
			chunk_id += 1

		if end >= length:
			break

		start = max(0, end - overlap_chars)

	return chunks
