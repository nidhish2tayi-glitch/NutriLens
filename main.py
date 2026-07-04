import logging
import os
import traceback
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import ai
import database
import ocr
from models import (
    AnalyzeRequest,
    ScanDetail,
    ScanSummary,
    UploadResponse,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nutrilens")

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "../uploads")
if not os.path.isabs(UPLOAD_DIR):
    UPLOAD_DIR = os.path.join(BACKEND_DIR, UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)

ALLOWED_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
origins = ["*"] if CORS_ORIGINS.strip() == "*" else [
    o.strip() for o in CORS_ORIGINS.split(",") if o.strip()
]

app = FastAPI(title="NutriLens AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    database.init_db()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error on %s %s:\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "Something went wrong on our end processing that request. "
                "Please try again, or use the 'Type Ingredients' tab as a "
                "fallback. (See the server terminal/log for details.)"
            )
        },
    )


@app.post("/upload", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)) -> UploadResponse:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a PNG, JPG, JPEG, or WEBP image.",
        )

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum allowed size is {MAX_UPLOAD_MB} MB.",
        )

    extension = ALLOWED_CONTENT_TYPES[file.content_type]
    safe_filename = f"{uuid.uuid4().hex}{extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    with open(file_path, "wb") as f:
        f.write(contents)

    raw_text = ""
    last_error: Optional[str] = None

    try:
        raw_text = ocr.extract_text_from_image(file_path)
    except ocr.OCRError as exc:
        last_error = str(exc)

    if not raw_text.strip() and ai.vision_ocr_available():
        try:
            raw_text = ai.vision_ocr(file_path)
        except ai.AIAnalysisError as exc:
            last_error = str(exc)

    if not raw_text.strip():
        try:
            raw_text = ocr.extract_text_via_ocrspace(file_path)
        except ocr.OCRError as exc:
            last_error = str(exc)

    if not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                last_error
                or "Could not extract any text from this image. Try a clearer "
                "photo, or use the 'Type Ingredients' tab to enter them manually."
            ),
        )

    ingredients_text = ocr.parse_ingredients(raw_text)
    if not ingredients_text:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract any ingredients from this image. Try a "
                "clearer photo, or use the 'Type Ingredients' tab to enter "
                "them manually."
            ),
        )

    return UploadResponse(
        image_url=f"/uploads/{safe_filename}",
        extracted_text=raw_text,
        ingredients_text=ingredients_text,
    )


@app.post("/analyze", response_model=ScanDetail)
async def analyze(payload: AnalyzeRequest) -> ScanDetail:
    ingredients_text = (payload.ingredients_text or "").strip()
    if not ingredients_text:
        raise HTTPException(status_code=400, detail="ingredients_text is required.")

    NO_NAME_PLACEHOLDERS = {"", "unknown product", "uploaded food product"}
    raw_name = (payload.product_name or "").strip()
    needs_auto_title = raw_name.lower() in NO_NAME_PLACEHOLDERS

    try:
        analysis = ai.analyze_ingredients(
            ingredients_text, None if needs_auto_title else raw_name
        )
    except ai.AIAnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if needs_auto_title:
        product_name = (
            analysis.get("product_title", "").strip()
            or ai.derive_title_from_ingredients(ingredients_text)
        )
    else:
        product_name = raw_name

    scan_id = database.save_scan(
        product_name=product_name,
        source=payload.source,
        ingredients_text=ingredients_text,
        analysis=analysis,
        image_url=payload.image_url,
        barcode=payload.barcode,
    )

    record = database.get_scan(scan_id)
    return ScanDetail(
        id=record["id"],
        product_name=record["product_name"],
        source=record["source"],
        created_at=record["created_at"],
        overall_score=record["overall_score"],
        ingredients_text=record["ingredients_text"],
        image_url=record["image_url"],
        barcode=record["barcode"],
        analysis=record["analysis"],
    )


@app.get("/history", response_model=list[ScanSummary])
async def get_history() -> list:
    return database.list_scans()


@app.get("/history/{scan_id}", response_model=ScanDetail)
async def get_history_item(scan_id: int) -> ScanDetail:
    record = database.get_scan(scan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return ScanDetail(
        id=record["id"],
        product_name=record["product_name"],
        source=record["source"],
        created_at=record["created_at"],
        overall_score=record["overall_score"],
        ingredients_text=record["ingredients_text"],
        image_url=record["image_url"],
        barcode=record["barcode"],
        analysis=record["analysis"],
    )


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
