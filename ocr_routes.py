from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse
from ocr_service import process_certificate
import uuid, os

router = APIRouter(prefix="/ocr", tags=["OCR"])

@router.post("/verify")
async def verify_certificate(file: UploadFile = File(...)):
    # Unique filename
    filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = f"static/{filename}"

    # Save uploaded file temporarily
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Run OCR + Heatmap
    extracted_data, heatmap_path = process_certificate(file_path)

    return {
        "status": "success",
        "extracted_data": extracted_data,
        "heatmap_url": f"/ocr/heatmap/{os.path.basename(heatmap_path)}"
    }

@router.get("/heatmap/{filename}")
async def get_heatmap(filename: str):
    return FileResponse(f"static/heatmaps/{filename}")
