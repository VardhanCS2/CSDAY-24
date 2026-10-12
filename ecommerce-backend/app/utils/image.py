import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException

UPLOAD_DIR = Path(__file__).resolve().parents[1] / "uploads" / "products"
MAX_FILE_SIZE = 5 * 1024 * 1024
IMAGE_SIGNATURES = {
    "image/jpeg": lambda content: content.startswith(b"\xff\xd8\xff"),
    "image/png": lambda content: content.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda content: (
        len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    ),
}


def save_image(file: UploadFile) -> str:
    content_type = file.content_type or ""
    is_valid_image = IMAGE_SIGNATURES.get(content_type)
    if is_valid_image is None:
        raise HTTPException(status_code=400, detail="Only JPG, PNG and WEBP images are allowed.")

    content = file.file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Image files must be 5 MB or smaller.")
    if not is_valid_image(content):
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid image.")

    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
    filename = f"{uuid.uuid4()}.{extension}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / filename).write_bytes(content)
    return f"/uploads/products/{filename}"