"""
Smart Recursive Chunking Module for ArkhamMirror.

Provides intelligent text chunking strategies that preserve semantic boundaries
and protect important patterns from being split.

Features:
- Smart recursive chunking (paragraph -> sentence -> character boundaries)
- Pattern protection (page markers, tables, phone numbers, etc.)
- Agentic chunking using LLM for semantic break detection
- Overlap management for retrieval context
"""

import re
import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.arkham.services.llm_service import chat_with_llm

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ChunkConfig:
    """Configuration for text chunking behavior."""
    max_chunk_size: int = 512
    min_chunk_size: int = 100
    overlap: int = 50
    protect_patterns: bool = True


# Regex patterns that should never be split across chunks
PROTECTED_PATTERNS = [
    # Page markers: === PAGE 1 START ===, === PAGE 1 END ===
    r'=== PAGE \d+ (?:START|END) ===',

    # Table blocks: === TABLE 1 === ... === END TABLE 1 ===
    r'=== TABLE \d+ ===.*?=== END TABLE \d+ ===',

    # Phone numbers - US format
    r'(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',

    # Phone numbers - Ukrainian format (+380 XX XXX XX XX)
    r'\+380\s?\d{2}\s?\d{3}\s?\d{2}\s?\d{2}',

    # Phone numbers - International format
    r'\+\d{1,4}[\s.-]?\d{1,5}[\s.-]?\d{1,5}[\s.-]?\d{1,9}',
]


def _protect_patterns(text: str) -> Tuple[str, dict]:
    """
    Replace protected patterns with placeholders to prevent splitting.

    Args:
        text: Original text

    Returns:
        Tuple of (protected_text, replacements_dict)
    """
    replacements = {}
    protected_text = text
    placeholder_counter = 0

    for pattern in PROTECTED_PATTERNS:
        for match in re.finditer(pattern, protected_text, re.DOTALL):
            matched_text = match.group()
            placeholder = f"__PROTECTED_{placeholder_counter}__"
            replacements[placeholder] = matched_text
            protected_text = protected_text.replace(matched_text, placeholder, 1)
            placeholder_counter += 1

    return protected_text, replacements


def _restore_patterns(text: str, replacements: dict) -> str:
    """
    Restore protected patterns from placeholders.

    Args:
        text: Text with placeholders
        replacements: Dictionary mapping placeholders to original text

    Returns:
        Text with restored patterns
    """
    restored_text = text
    for placeholder, original in replacements.items():
        restored_text = restored_text.replace(placeholder, original)
    return restored_text


def _split_by_paragraphs(text: str) -> List[str]:
    """Split text on paragraph boundaries (double newline)."""
    paragraphs = re.split(r'\n\n+', text)
    return [p.strip() for p in paragraphs if p.strip()]


def _split_by_sentences(text: str) -> List[str]:
    """
    Split text on sentence boundaries.

    Looks for period, exclamation, or question mark followed by space and capital letter.
    """
    # Pattern: sentence ending (. ! ?) followed by space and capital letter
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z])'
    sentences = re.split(sentence_pattern, text)
    return [s.strip() for s in sentences if s.strip()]


def _split_by_characters(text: str, max_size: int) -> List[str]:
    """
    Split text at character boundaries (last resort).

    Args:
        text: Text to split
        max_size: Maximum chunk size

    Returns:
        List of character-level chunks
    """
    chunks = []
    for i in range(0, len(text), max_size):
        chunks.append(text[i:i + max_size])
    return chunks


def _merge_small_chunks(chunks: List[str], min_size: int) -> List[str]:
    """
    Merge chunks smaller than min_size with neighbors.

    Args:
        chunks: List of text chunks
        min_size: Minimum chunk size

    Returns:
        List of merged chunks
    """
    if not chunks:
        return []

    merged = []
    current_chunk = chunks[0]

    for next_chunk in chunks[1:]:
        if len(current_chunk) < min_size:
            # Merge with next chunk
            current_chunk = current_chunk + "\n\n" + next_chunk
        else:
            # Current chunk is large enough, save it
            merged.append(current_chunk)
            current_chunk = next_chunk

    # Don't forget the last chunk
    if current_chunk:
        # If last chunk is too small and we have previous chunks, merge with last
        if len(current_chunk) < min_size and merged:
            merged[-1] = merged[-1] + "\n\n" + current_chunk
        else:
            merged.append(current_chunk)

    return merged


def _recursive_chunk(text: str, max_size: int, min_size: int) -> List[str]:
    """
    Recursively chunk text using paragraph -> sentence -> character boundaries.

    Args:
        text: Text to chunk
        max_size: Maximum chunk size
        min_size: Minimum chunk size

    Returns:
        List of chunks
    """
    chunks = []

    # Try splitting by paragraphs first
    paragraphs = _split_by_paragraphs(text)

    for para in paragraphs:
        if len(para) <= max_size:
            # Paragraph fits, keep it
            chunks.append(para)
        else:
            # Paragraph too large, try sentences
            sentences = _split_by_sentences(para)

            current_chunk = ""
            for sentence in sentences:
                if len(sentence) > max_size:
                    # Single sentence too large, character split
                    if current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = ""

                    char_chunks = _split_by_characters(sentence, max_size)
                    chunks.extend(char_chunks)
                elif len(current_chunk) + len(sentence) + 1 <= max_size:
                    # Add sentence to current chunk
                    if current_chunk:
                        current_chunk += " " + sentence
                    else:
                        current_chunk = sentence
                else:
                    # Current chunk full, start new one
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = sentence

            # Save remaining chunk
            if current_chunk:
                chunks.append(current_chunk)

    # Merge small chunks
    chunks = _merge_small_chunks(chunks, min_size)

    return chunks


def smart_chunk(text: str, config: Optional[ChunkConfig] = None) -> List[str]:
    """
    Intelligently chunk text using recursive splitting strategy.

    Strategy:
    1. Protect patterns (if enabled)
    2. Split on paragraph boundaries first
    3. If chunks too large, split on sentence boundaries
    4. Character-level split as last resort
    5. Merge chunks smaller than min_size
    6. Restore protected patterns

    Args:
        text: Text to chunk
        config: Chunking configuration (uses defaults if None)

    Returns:
        List of text chunks

    Example:
        >>> config = ChunkConfig(max_chunk_size=512, min_chunk_size=100)
        >>> chunks = smart_chunk(long_document, config)
        >>> print(f"Created {len(chunks)} chunks")
    """
    if config is None:
        config = ChunkConfig()

    if not text or not text.strip():
        return []

    # Step 1: Protect patterns
    replacements = {}
    if config.protect_patterns:
        text, replacements = _protect_patterns(text)
        logger.debug(f"Protected {len(replacements)} patterns")

    # Step 2-5: Recursive chunking
    chunks = _recursive_chunk(text, config.max_chunk_size, config.min_chunk_size)

    # Step 6: Restore protected patterns
    if config.protect_patterns and replacements:
        chunks = [_restore_patterns(chunk, replacements) for chunk in chunks]

    logger.info(f"Smart chunking created {len(chunks)} chunks from {len(text)} characters")
    return chunks


def agentic_chunk(text: str, config: Optional[ChunkConfig] = None) -> List[str]:
    """
    Use LLM to identify semantic break points for intelligent chunking.

    This function asks the LLM to analyze the text and suggest optimal
    break points based on semantic meaning, topics, and narrative flow.
    Falls back to smart_chunk if LLM is unavailable or fails.

    Args:
        text: Text to chunk
        config: Chunking configuration (uses defaults if None)

    Returns:
        List of text chunks

    Example:
        >>> config = ChunkConfig(max_chunk_size=512)
        >>> chunks = agentic_chunk(document, config)
    """
    if config is None:
        config = ChunkConfig()

    if not text or not text.strip():
        return []

    # Prepare prompt for LLM
    prompt = f"""Analyze the following text and identify optimal semantic break points for chunking.

The goal is to split this text into chunks of approximately {config.max_chunk_size} characters each,
while preserving semantic meaning and avoiding breaks in the middle of important concepts.

Return a JSON array of character positions where breaks should occur.
Only include positions that make semantic sense (topic changes, section boundaries, etc.).

Example response format:
{{
    "break_points": [0, 450, 920, 1400],
    "reasoning": "Brief explanation of why these break points were chosen"
}}

Text to analyze:
{text[:2000]}{"... (truncated)" if len(text) > 2000 else ""}

Total text length: {len(text)} characters

Respond with ONLY valid JSON, no additional commentary."""

    try:
        # Call LLM with JSON mode
        response = chat_with_llm(
            messages=prompt,
            temperature=0.2,  # Lower temperature for more consistent output
            max_tokens=1000,
            json_mode=True,
            use_cache=False  # Don't cache chunking decisions
        )

        # Parse JSON response
        if not response or "[LM Studio" in response or "Error:" in response:
            logger.warning("LLM not available for agentic chunking, falling back to smart_chunk")
            return smart_chunk(text, config)

        # Clean up markdown code blocks if present
        cleaned = response.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0]
        elif "```" in cleaned:
            parts = cleaned.split("```")
            if len(parts) > 1:
                cleaned = parts[1]

        data = json.loads(cleaned.strip())
        break_points = data.get("break_points", [])
        reasoning = data.get("reasoning", "")

        if reasoning:
            logger.info(f"LLM chunking reasoning: {reasoning}")

        # Validate break points
        if not break_points or not isinstance(break_points, list):
            logger.warning("Invalid break points from LLM, falling back to smart_chunk")
            return smart_chunk(text, config)

        # Ensure break points are sorted and valid
        break_points = sorted([bp for bp in break_points if 0 <= bp <= len(text)])

        # Create chunks from break points
        chunks = []
        for i in range(len(break_points)):
            start = break_points[i]
            end = break_points[i + 1] if i + 1 < len(break_points) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

        # Validate chunks aren't too large or too small
        valid_chunks = []
        for chunk in chunks:
            if len(chunk) > config.max_chunk_size:
                # Chunk too large, split it further
                logger.debug(f"LLM chunk too large ({len(chunk)} chars), splitting with smart_chunk")
                valid_chunks.extend(smart_chunk(chunk, config))
            elif len(chunk) < config.min_chunk_size and valid_chunks:
                # Chunk too small, merge with previous
                logger.debug(f"LLM chunk too small ({len(chunk)} chars), merging with previous")
                valid_chunks[-1] = valid_chunks[-1] + "\n\n" + chunk
            else:
                valid_chunks.append(chunk)

        logger.info(f"Agentic chunking created {len(valid_chunks)} chunks from {len(text)} characters")
        return valid_chunks

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        logger.debug(f"Raw response: {response[:500]}")
        return smart_chunk(text, config)
    except Exception as e:
        logger.error(f"Agentic chunking failed: {e}")
        return smart_chunk(text, config)


def chunk_with_overlap(chunks: List[str], overlap: int) -> List[str]:
    """
    Add overlap from neighboring chunks for better retrieval context.

    This helps with retrieval by ensuring that queries near chunk boundaries
    can still match relevant content.

    Strategy:
    - First chunk: add prefix from second chunk
    - Last chunk: add suffix from previous chunk
    - Middle chunks: add overlap from both sides

    Args:
        chunks: List of text chunks
        overlap: Number of characters to overlap

    Returns:
        List of chunks with overlap added

    Example:
        >>> chunks = ["First chunk text", "Second chunk text", "Third chunk text"]
        >>> overlapped = chunk_with_overlap(chunks, overlap=20)
        >>> # First chunk now includes start of second chunk
        >>> # Second chunk includes end of first and start of third
        >>> # Third chunk includes end of second chunk
    """
    if not chunks or overlap <= 0:
        return chunks

    overlapped_chunks = []

    for i, chunk in enumerate(chunks):
        enhanced_chunk = chunk

        # Add suffix from previous chunk
        if i > 0:
            prev_chunk = chunks[i - 1]
            suffix = prev_chunk[-overlap:] if len(prev_chunk) >= overlap else prev_chunk
            enhanced_chunk = suffix + " ... " + enhanced_chunk

        # Add prefix from next chunk
        if i < len(chunks) - 1:
            next_chunk = chunks[i + 1]
            prefix = next_chunk[:overlap] if len(next_chunk) >= overlap else next_chunk
            enhanced_chunk = enhanced_chunk + " ... " + prefix

        overlapped_chunks.append(enhanced_chunk)

    logger.info(f"Added {overlap}-character overlap to {len(chunks)} chunks")
    return overlapped_chunks


# Convenience function for quick chunking
def chunk_text(
    text: str,
    max_chunk_size: int = 512,
    min_chunk_size: int = 100,
    overlap: int = 50,
    use_agentic: bool = False,
    protect_patterns: bool = True
) -> List[str]:
    """
    Convenience function for quick text chunking.

    Args:
        text: Text to chunk
        max_chunk_size: Maximum chunk size in characters
        min_chunk_size: Minimum chunk size in characters
        overlap: Overlap size for retrieval context
        use_agentic: Whether to use LLM for semantic chunking
        protect_patterns: Whether to protect special patterns from splitting

    Returns:
        List of text chunks with overlap

    Example:
        >>> chunks = chunk_text(document, max_chunk_size=512, use_agentic=True)
    """
    config = ChunkConfig(
        max_chunk_size=max_chunk_size,
        min_chunk_size=min_chunk_size,
        overlap=overlap,
        protect_patterns=protect_patterns
    )

    # Choose chunking strategy
    if use_agentic:
        chunks = agentic_chunk(text, config)
    else:
        chunks = smart_chunk(text, config)

    # Add overlap if requested
    if overlap > 0:
        chunks = chunk_with_overlap(chunks, overlap)

    return chunks
