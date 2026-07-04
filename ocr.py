import io
import os
import re

import requests
from PIL import Image, ImageFilter, ImageOps

try:
    import pytesseract
except ImportError:
    pytesseract = None

OCRSPACE_API_KEY = os.getenv("OCRSPACE_API_KEY", "helloworld").strip() or "helloworld"
OCRSPACE_URL = "https://api.ocr.space/parse/image"
OCRSPACE_MAX_BYTES = 1_000_000


class OCRError(Exception):
    pass


def _preprocess_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.SHARPEN)
    return image


def extract_text_from_image(image_path: str) -> str:
    if pytesseract is None:
        raise OCRError(
            "pytesseract is not installed. Run `pip install -r requirements.txt`."
        )
    try:
        with Image.open(image_path) as img:
            processed = _preprocess_image(img)
            text = pytesseract.image_to_string(processed)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRError(
            "Tesseract OCR engine was not found on this system. "
            "Install it with `brew install tesseract` (macOS) or see the README."
        ) from exc
    except Exception as exc:
        raise OCRError(f"Failed to process image: {exc}") from exc

    return text.strip()


def _shrink_for_upload(image_path: str, max_bytes: int = OCRSPACE_MAX_BYTES) -> bytes:
    with Image.open(image_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")

        quality = 90
        max_dimension = 1800
        while True:
            resized = img.copy()
            resized.thumbnail((max_dimension, max_dimension))
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=quality)
            data = buffer.getvalue()
            if len(data) <= max_bytes or (quality <= 30 and max_dimension <= 500):
                return data
            if quality > 30:
                quality -= 15
            else:
                max_dimension = int(max_dimension * 0.7)


def extract_text_via_ocrspace(image_path: str) -> str:
    try:
        image_bytes = _shrink_for_upload(image_path)
    except Exception as exc:
        raise OCRError(f"Failed to prepare image for OCR: {exc}") from exc

    try:
        response = requests.post(
            OCRSPACE_URL,
            data={
                "apikey": OCRSPACE_API_KEY,
                "language": "eng",
                "OCREngine": 2,
                "scale": "true",
                "isTable": "false",
            },
            files={"file": ("label.jpg", image_bytes, "image/jpeg")},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise OCRError(f"Could not reach the OCR service: {exc}") from exc

    if response.status_code != 200:
        raise OCRError(f"OCR service returned status {response.status_code}.")

    try:
        data = response.json()
    except ValueError as exc:
        raise OCRError("OCR service returned an unreadable response.") from exc

    if data.get("IsErroredOnProcessing"):
        message = data.get("ErrorMessage") or "Unknown OCR service error."
        if isinstance(message, list):
            message = "; ".join(message)
        raise OCRError(f"OCR service error: {message}")

    results = data.get("ParsedResults") or []
    if not results:
        raise OCRError("OCR service did not return any parsed text.")

    text = (results[0].get("ParsedText") or "").strip()
    if not text:
        raise OCRError("OCR service could not read any text from this image.")
    return text


def parse_ingredients(raw_text: str) -> str:
    if not raw_text:
        return ""

    text = raw_text.replace("\n", " ").strip()

    match = re.search(r"ingredients?\s*[:\-]\s*(.+)", text, re.IGNORECASE)
    ingredients_section = match.group(1) if match else text

    stop_markers = [
        "allergen", "contains", "nutrition", "may contain",
        "storage", "best before", "manufactured", "distributed",
    ]
    lowered = ingredients_section.lower()
    cut_index = len(ingredients_section)
    for marker in stop_markers:
        idx = lowered.find(marker)
        if idx != -1:
            cut_index = min(cut_index, idx)
    ingredients_section = ingredients_section[:cut_index]

    items = []
    depth = 0
    current = ""
    for char in ingredients_section:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            items.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        items.append(current.strip())

    cleaned = [re.sub(r"[.;]+$", "", item).strip() for item in items]
    cleaned = [item for item in cleaned if item]

    return ", ".join(cleaned) if cleaned else text.strip()
