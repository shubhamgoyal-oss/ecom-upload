"""Core logic for the PDF -> HTML conversion tool.

Design notes (why this looks the way it does):

- PDF pages are rendered to images *client-side* (pdf.js, in the browser) and
  sent here one page at a time. The server never parses the PDF itself and
  never holds any job state between requests — each request is fully
  self-contained. This matters on Vercel: serverless functions are stateless
  and ephemeral, so a background-thread/job-queue design (like the app's old,
  now-unreachable FB-media-uploader code) would not survive across requests.
  One page per request also keeps each call well within serverless execution
  time limits, since it does exactly one vision API call.
- Image regions on a page (illustrations/photos, as opposed to body text) are
  identified by the vision model as a bounding box; the *browser* crops the
  pixels for that region out of the page canvas it already rendered, so the
  server never needs to re-derive or store image bytes either.
- Because this handles arbitrary PDFs (unknown language/script), the raw
  text layer is never trusted even when present — every page is read visually,
  the same approach used for the one-off narayan-kwach.pdf conversion, just
  generalized and automated.
- Final HTML assembly (blocks -> a standalone document) happens client-side in
  templates/pdf_to_html.html, not here. A server round-trip carrying every
  accumulated block plus every cropped image for the whole document — then
  returning the fully assembled HTML with those images re-embedded — would
  need to fit Vercel Functions' ~4.5MB request/response body limit in one
  shot, which any real multi-page, multi-image document blows past. The
  browser already holds all of that in memory, so it builds the final file
  itself and never sends it anywhere.
"""
from __future__ import annotations

import os

import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip()

# Guardrails: this is a demo-scale tool (one Anthropic API call per page,
# driven synchronously by the browser), not a bulk pipeline.
MAX_PAGES = 60
# Decoded size of a single page image. Kept well under Vercel Functions'
# ~4.5MB request body cap: base64 inflates this by ~4/3, plus JSON overhead,
# so 3MB decoded lands around ~4.1MB on the wire.
MAX_IMAGE_BYTES = 3 * 1024 * 1024

_client = None


def is_configured() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it as an environment variable "
                "(in Vercel: Project Settings -> Environment Variables) to enable "
                "PDF conversion."
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


BLOCK_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "heading",
                            "subheading",
                            "paragraph",
                            "quote",
                            "list_item",
                            "caption",
                            "image",
                        ],
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "The exact text of this block, transcribed by reading it, "
                            "in its original language and script, with correct Unicode "
                            "characters. Omit for type=image."
                        ),
                    },
                    "bold": {"type": "boolean"},
                    "align": {"type": "string", "enum": ["left", "center", "right"]},
                    "color": {
                        "type": "string",
                        "description": (
                            "Only set this when the text is printed in a distinctly "
                            "different, deliberate color (e.g. red ink for emphasis), "
                            "not for normal black/dark body text. One word, e.g. 'red'."
                        ),
                    },
                    "image_bbox": {
                        "type": "object",
                        "description": (
                            "Only for type=image: the bounding box of a photo, "
                            "illustration, or figure on the page (not a text block), "
                            "as fractions of the full page width/height, 0-1, "
                            "origin at the top-left corner."
                        ),
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                        "required": ["x", "y", "width", "height"],
                    },
                },
                "required": ["type"],
            },
        }
    },
    "required": ["blocks"],
}

PROMPT = """This image is one page of a PDF document. Read it carefully and transcribe \
its content into structured blocks, in top-to-bottom reading order.

Rules:
- Transcribe text exactly as written, in its original language/script. Do not \
translate, summarize, or correct spelling. Read the actual glyphs on the page \
rather than guessing from context — many PDFs have unreliable embedded text \
layers, so treat this purely as a visual reading task.
- Classify each block's type: "heading" for a page/section title, "subheading" \
for a lesser heading, "paragraph" for body text, "quote" for a block quotation \
or callout, "list_item" for one item of a bulleted/numbered list (one block per \
item), "caption" for a small label under a figure/table.
- Use "image" only for genuine photos, illustrations, diagrams, or figures — \
not for text, even decorative or stylized text. Give its bounding box as \
fractions of the page (0-1), tight around the actual artwork.
- Mark bold=true only for text that is visibly bolder than the surrounding body \
text. Mark color only when text is deliberately printed in a distinct color \
(e.g. red for emphasis) — not for normal body text or scan/JPEG artifacts.
- Skip running headers/footers/page numbers that are pure pagination chrome, \
but keep everything else, including section numbers, footnotes, and table \
content (render a table's rows as consecutive paragraph blocks if you cannot \
represent it as a true table).
- If the page is blank or has no meaningful content, return an empty blocks list.

Call the record_blocks tool with the result."""


def transcribe_page(image_base64: str, media_type: str) -> list[dict]:
    """Send one page image to the vision model and return its content blocks."""
    decoded_len = len(image_base64) * 3 // 4
    if decoded_len > MAX_IMAGE_BYTES:
        raise ValueError(f"Page image is too large ({decoded_len} bytes, max {MAX_IMAGE_BYTES}).")
    if media_type not in ("image/png", "image/jpeg", "image/webp"):
        raise ValueError(f"Unsupported image media type: {media_type}")

    client = _get_client()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8192,
        tools=[
            {
                "name": "record_blocks",
                "description": "Record the transcribed content blocks for this page.",
                "input_schema": BLOCK_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "record_blocks"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_base64},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "This page has too much content to transcribe in one pass "
            "(the model's response was cut off). Try a lower-resolution render "
            "or a simpler page."
        )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_blocks":
            return block.input.get("blocks", [])
    raise RuntimeError("Model did not return a record_blocks tool call.")
