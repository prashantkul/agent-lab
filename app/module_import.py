"""Module import service using AI to extract module info from images/PDFs."""
import base64
import io
import json
from typing import Optional

import anthropic
import fitz  # PyMuPDF

from app.config import settings


EXTRACTION_PROMPT = """Analyze this course syllabus/curriculum image and extract ALL modules/weeks present.

Return a JSON array with each module as an object:

{
    "modules": [
        {
            "name": "Module title/name",
            "week_number": 1,
            "short_description": "Brief theme or description (1-2 sentences)",
            "detailed_description": "Longer description of what the module covers",
            "learning_objectives": ["List of learning objectives/topics covered"],
            "prerequisites": ["Any prerequisites mentioned"],
            "expected_outcomes": "What students will be able to do after completing this module",
            "estimated_time_minutes": 180
        }
    ]
}

Rules:
- Extract ALL modules/weeks visible in the image, not just the first one
- Each week or module section should be a separate entry in the array
- Week number should be extracted from "Week One", "Week 1", "Module 1", etc.
- Learning objectives should include ALL bullet points from lesson topics for each module
- Keep descriptions concise but informative
- If a field is not present, use null
- For estimated_time_minutes, estimate based on content volume (typically 120-240 for a full module)

Return ONLY valid JSON, no markdown formatting or explanation."""


def extract_module_from_image(image_data: bytes, media_type: str) -> dict:
    """Extract module information from an image using Claude Vision."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    image_base64 = base64.standard_b64encode(image_data).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    )

    response_text = message.content[0].text

    # Clean up response if it has markdown code blocks
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])

    return json.loads(response_text)


def extract_modules_from_images(images: list) -> dict:
    """Extract module information from multiple images using Claude Vision."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build content with all images
    content = []
    for img_data in images:
        image_base64 = base64.standard_b64encode(img_data).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_base64,
            },
        })

    content.append({
        "type": "text",
        "text": EXTRACTION_PROMPT,
    })

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=8000,
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
    )

    response_text = message.content[0].text

    # Clean up response if it has markdown code blocks
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1])

    return json.loads(response_text)


def extract_module_from_pdf(pdf_data: bytes) -> dict:
    """Extract module information from a PDF by converting pages to images."""
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    # Open PDF and convert pages to images
    doc = fitz.open(stream=pdf_data, filetype="pdf")

    images = []
    # Process up to 20 pages to capture all module info
    for page_num in range(min(20, len(doc))):
        page = doc[page_num]
        # Render at 2x resolution for better OCR
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        images.append(img_data)

    doc.close()

    if not images:
        raise ValueError("Could not extract images from PDF")

    # Send all pages to Claude for comprehensive extraction
    return extract_modules_from_images(images)


def extract_module_from_file(file_data: bytes, filename: str, content_type: str) -> dict:
    """Extract module information from an uploaded file."""
    filename_lower = filename.lower()

    if content_type == "application/pdf" or filename_lower.endswith(".pdf"):
        return extract_module_from_pdf(file_data)
    elif content_type.startswith("image/") or any(
        filename_lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]
    ):
        # Determine media type
        if filename_lower.endswith(".png"):
            media_type = "image/png"
        elif filename_lower.endswith(".gif"):
            media_type = "image/gif"
        elif filename_lower.endswith(".webp"):
            media_type = "image/webp"
        else:
            media_type = "image/jpeg"

        return extract_module_from_image(file_data, media_type)
    else:
        raise ValueError(f"Unsupported file type: {content_type}")
