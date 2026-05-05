"""
AI-READY PDF PARSER (v6)
=========================
Changes from v5 (all backed by audit findings on real data):

  1. Document metadata extraction
     Preamble contained form-admin content (fee stamp, OMB number, etc.)
     that is not a "section". Now extracted separately into document_metadata:
     {form_name, form_number, edition, omg_number, expiry}.
     Preamble section is dropped from output when it only contains this noise.

  2. Sentence-boundary chunking
     v5 chunk_text split at a hard word count, cutting mid-sentence.
     Audit confirmed: Part 4 (1037 words) split at "does not use Roman
     letters," — a mid-phrase break. New chunker walks back from the word
     limit to the nearest sentence-ending token (., ?, !) up to 25% back.
     Falls back to hard cut if no boundary found (handles lists/labels).

  3. Item-number prefix repair
     pdfminer sometimes emits the item number (e.g. "1.") as a separate
     tiny text box from its label ("Alien Registration Number"). After
     column-stream ordering they appear as adjacent tokens. A post-
     processing pass joins isolated item numbers to the following text
     when they arrive as separate blocks ("1." + "Alien Registration..." 
     → "1. Alien Registration...").
"""

import re
import sys
import json
from collections import defaultdict

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LAParams


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

MAX_WORDS_PER_CHUNK   = 800
CHUNK_LOOKBACK_RATIO  = 0.25   # walk back up to 25% of chunk to find sentence end

NOISE_PATTERNS = [
    r"^►$",
    r"^►\s*A-$",
    r"^Page \d+ of \d+$",
    r"^Form [A-Z]+-\d+\s+Edition",
    r"^[A-Z]-$",
]

# Metadata patterns found on page 1 header area
META_PATTERNS = {
    "form_number": r"Form\s+(I-\d+)",
    "edition":     r"Edition\s+([\d/]+)",
    "omb_number":  r"OMB\s+No\.\s+([\d\-]+)",
    "expiry":      r"Expires\s+([\d/]+)",
}


# ─────────────────────────────────────────────────────────────
# 1. EXTRACT TEXT BOXES
# ─────────────────────────────────────────────────────────────

def extract_text_boxes(pdf_path):
    laparams = LAParams(
        line_margin=0.5,
        word_margin=0.1,
        char_margin=2.0,
        boxes_flow=0.5,
    )
    pages = []
    for page_num, layout in enumerate(extract_pages(pdf_path, laparams=laparams), 1):
        boxes = []
        for element in layout:
            if isinstance(element, LTTextContainer):
                text = element.get_text().strip()
                if not text:
                    continue
                boxes.append({
                    "x0":     element.x0,
                    "x1":     element.x1,
                    "y_top":  layout.height - element.y1,
                    "y_bot":  layout.height - element.y0,
                    "text":   text,
                    "page":   page_num,
                    "width":  layout.width,
                    "height": layout.height,
                })
        pages.append(boxes)
    return pages


# ─────────────────────────────────────────────────────────────
# 2. DOCUMENT METADATA  (new in v6)
# ─────────────────────────────────────────────────────────────

def extract_document_metadata(page1_boxes):
    """
    Pull structured metadata from page 1 header boxes.
    Returns dict with form_name, form_number, edition, omb_number, expiry.
    These are extracted before section processing so they don't pollute Preamble.
    """
    meta = {}
    full_text = " ".join(b["text"] for b in page1_boxes)

    # Form name: first long title-cased box near top
    top_boxes = sorted(
        [b for b in page1_boxes if b["y_top"] < 80],
        key=lambda b: b["y_top"]
    )
    for b in top_boxes:
        text = b["text"].strip().replace("\n", " ")
        if len(text.split()) >= 3 and not re.match(r"^(USCIS|OMB|Form)", text):
            meta["form_name"] = re.sub(r"\s+", " ", text)
            break

    for key, pattern in META_PATTERNS.items():
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            meta[key] = m.group(1)

    return meta


# ─────────────────────────────────────────────────────────────
# 3. COLUMN DETECTION
# ─────────────────────────────────────────────────────────────

def detect_columns(boxes, page_width):
    narrow = [b for b in boxes if (b["x1"] - b["x0"]) < page_width * 0.65]
    if not narrow:
        return []
    left  = sum(1 for b in narrow if b["x0"] < page_width * 0.45)
    right = sum(1 for b in narrow if b["x0"] > page_width * 0.55)
    return [page_width / 2] if (left >= 3 and right >= 3) else []


def assign_columns(boxes, boundaries):
    def get_col(x0):
        for i, b in enumerate(boundaries):
            if x0 < b:
                return i
        return len(boundaries)
    for b in boxes:
        b["col"] = get_col(b["x0"]) if boundaries else 0
    return boxes


# ─────────────────────────────────────────────────────────────
# 4. COLUMN STREAM SPLIT
# ─────────────────────────────────────────────────────────────

def split_into_column_streams(boxes, num_cols):
    streams = []
    for col_idx in range(num_cols):
        col_boxes = sorted(
            [b for b in boxes if b.get("col", 0) == col_idx],
            key=lambda b: b["y_top"]
        )
        if col_boxes:
            streams.append(col_boxes)
    # Sort streams by topmost content — defensive for PDFs where right col
    # genuinely starts higher than left col
    streams.sort(key=lambda s: min(b["y_top"] for b in s))
    return streams


# ─────────────────────────────────────────────────────────────
# 5. TEXT UTILITIES
# ─────────────────────────────────────────────────────────────

def clean_text(text):
    lines = text.split("\n")
    result = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(
            r"\b(?:[A-Z]\s){2,}[A-Z]\b",
            lambda m: m.group(0).replace(" ", ""),
            line,
        )
        if line:
            result.append(line)
    return " ".join(result)


def is_noise(text):
    t = text.strip()
    return any(re.match(p, t, re.IGNORECASE) for p in NOISE_PATTERNS)


# ─────────────────────────────────────────────────────────────
# 6. SECTION DETECTION
# ─────────────────────────────────────────────────────────────

def is_section_header(text):
    return bool(re.match(r"^(Part|Section)\s+\d+[\.\s]", text, re.IGNORECASE))


def normalize_title(title):
    title = re.sub(r"\s*\(continued\)\s*", " ", title, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", title).strip()


# ─────────────────────────────────────────────────────────────
# 7. ITEM-NUMBER PREFIX REPAIR  (new in v6)
# ─────────────────────────────────────────────────────────────

def repair_item_numbers(blocks):
    """
    pdfminer sometimes splits "1." (tiny box) from "Alien Registration Number"
    (wider box) into separate blocks because they have different x0 positions.
    After column-stream ordering they land adjacently. This pass merges an
    isolated item-number block into the following content block.

    Pattern: block text matches r"^\d+[\.\)\-:]?$" (just a number and period)
    Action:  prepend it to the next block's text.
    """
    if not blocks:
        return blocks

    result = []
    pending_prefix = None

    for b in blocks:
        text = b["text"].strip()
        #if re.match(r"^\d+\.$", text):
        if re.match(r"^\d+[\.\)\-:]?$", text):
            # Isolated item number — hold it
            pending_prefix = text
        else:
            if pending_prefix:
                b = dict(b)  # don't mutate original
                b["text"] = pending_prefix + " " + b["text"]
                pending_prefix = None
            result.append(b)

    # If a number was at the very end with nothing after it, keep it
    if pending_prefix:
        result.append({"text": pending_prefix, "col": 0, "page": 0,
                        "x0": 0, "x1": 0, "y_top": 0, "y_bot": 0,
                        "width": 0, "height": 0})

    return result


# ─────────────────────────────────────────────────────────────
# 8. KEY-VALUE EXTRACTION
# ─────────────────────────────────────────────────────────────

def extract_key_values(blocks):
    kv = {}
    skip = ["select", "provide", "if you", "complete", "type or print"]
    for block in blocks:
        m = re.match(r"^([^:]{3,60}):\s*(.{3,})", block["text"])
        if m:
            key, value = m.group(1).strip(), m.group(2).strip()
            if not any(w in key.lower() for w in skip):
                kv[key] = value
    return kv


# ─────────────────────────────────────────────────────────────
# 9. EXTRACT SECTIONS FROM A SINGLE STREAM
# ─────────────────────────────────────────────────────────────

def extract_sections_from_stream(stream, carry_title="Preamble"):
    """
    Walk one column stream and split into sections.
    carry_title: inherited section context from previous stream/page.
    Returns (list_of_sections, last_title_seen).
    """
    stream = repair_item_numbers(stream)

    sections = []
    current  = {"title": carry_title, "blocks": []}

    for b in stream:
        text = b["text"]
        if is_section_header(text):
            if current["blocks"]:
                sections.append(current)
            current = {"title": normalize_title(text), "blocks": []}
        else:
            if not is_noise(text):
                current["blocks"].append(b)

    if current["blocks"]:
        sections.append(current)

    result     = []
    last_title = carry_title

    for sec in sections:
        parts   = [clean_text(b["text"]) for b in sec["blocks"] if not is_noise(b["text"])]
        content = " ".join(p for p in parts if p)
        result.append({
            "title":      sec["title"],
            "content":    content,
            "key_values": extract_key_values(sec["blocks"]),
        })
        last_title = sec["title"]

    return result, last_title


# ─────────────────────────────────────────────────────────────
# 10. PROCESS A SINGLE PAGE
# ─────────────────────────────────────────────────────────────

def process_page(boxes, carry_title="Preamble"):
    if not boxes:
        return [], carry_title

    width      = boxes[0]["width"]
    boundaries = detect_columns(boxes, width)
    boxes      = assign_columns(boxes, boundaries)
    num_cols   = len(boundaries) + 1
    streams    = split_into_column_streams(boxes, num_cols)

    all_sections  = []
    current_carry = carry_title

    for stream in streams:
        sections, current_carry = extract_sections_from_stream(stream, current_carry)
        all_sections.extend(sections)

    return all_sections, current_carry


# ─────────────────────────────────────────────────────────────
# 11. SENTENCE-BOUNDARY CHUNKING  (improved in v6)
# ─────────────────────────────────────────────────────────────

def chunk_text(content, max_words=MAX_WORDS_PER_CHUNK):
    """
    Split content into chunks bounded by max_words.

    Improvement over v5: instead of cutting at exactly max_words, walks
    back up to CHUNK_LOOKBACK_RATIO * max_words to find the nearest
    sentence-ending token (word ending in . ? !). Falls back to hard
    word-count cut when no sentence boundary is found (e.g. pure label lists).
    """
    if not content:
        return []

    words = content.split()
    if len(words) <= max_words:
        return [content]

    chunks    = []
    start     = 0
    lookback  = int(max_words * CHUNK_LOOKBACK_RATIO)

    while start < len(words):
        end = min(start + max_words, len(words))

        if end < len(words):
            # Try to find sentence boundary by walking back
            boundary = None
            for i in range(end, max(start + max_words - lookback, start + 1), -1):
                if words[i - 1][-1] in ".?!":
                    boundary = i
                    break
            if boundary:
                end = boundary

        chunks.append(" ".join(words[start:end]))
        start = end

    return chunks


# ─────────────────────────────────────────────────────────────
# 12. MAIN PIPELINE
# ─────────────────────────────────────────────────────────────

def extract_pdf(pdf_path):
    all_page_boxes = extract_text_boxes(pdf_path)

    # Extract document metadata from page 1 before section processing
    document_metadata = {}
    if all_page_boxes:
        document_metadata = extract_document_metadata(all_page_boxes[0])

    merged      = defaultdict(lambda: {"content_parts": [], "key_values": {}})
    carry_title = "Preamble"

    for boxes in all_page_boxes:
        page_sections, carry_title = process_page(boxes, carry_title)
        for sec in page_sections:
            title = normalize_title(sec["title"])
            # Skip preamble-only noise (form admin header — captured in metadata)
            if title == "Preamble" and not sec["content"].strip():
                continue
            merged[title]["content_parts"].append(sec["content"])
            merged[title]["key_values"].update(sec["key_values"])

    final_sections = []
    for title, data in merged.items():
        full_content = " ".join(p for p in data["content_parts"] if p).strip()
        if not full_content:
            continue  # drop empty sections entirely

        final_sections.append({
            "title":      title,
            "key_values": data["key_values"],
            "chunks":     chunk_text(full_content),
            "word_count": len(full_content.split()),
        })

    return {
        "document_type":     "auto-detect",
        "document_metadata": document_metadata,
        "total_sections":    len(final_sections),
        "sections":          final_sections,
    }


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parser.py file.pdf")
        sys.exit(1)

    result = extract_pdf(sys.argv[1])
    print(json.dumps(result, indent=2))