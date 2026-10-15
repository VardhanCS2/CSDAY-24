import logging
from pathlib import Path
from uuid import uuid4

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.celery.tasks import PRIVATE_FILES, generate_invoice, import_products_csv
from app.celery.worker import celery_app, require_celery_worker
from app.database.database import get_db
from app.models.background_job import BackgroundJob
from app.models.order import Order
from app.models.user import User
from app.utils.response import success_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["Background jobs"])
MAX_CSV_BYTES = 10 * 1024 * 1024


def _job_data(job: BackgroundJob) -> dict:
    return {
        "id": job.id,
        "task_type": job.task_type,
        "resource_id": job.resource_id,
        "status": job.status,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _require_worker() -> None:
    require_celery_worker()


def _refresh_job_state(job: BackgroundJob, db: Session) -> None:
    if job.status not in {"queued", "running"}:
        return

    task_result = AsyncResult(job.id, app=celery_app)
    changed = False
    if task_result.state == "PROGRESS":
        info = task_result.info if isinstance(task_result.info, dict) else {}
        task_progress = info.get("progress")
        if job.status != "running":
            job.status = "running"
            changed = True
        if isinstance(task_progress, int):
            progress = max(job.progress, min(100, task_progress))
            if progress != job.progress:
                job.progress = progress
                changed = True
    elif task_result.state == "STARTED" and job.status != "running":
        job.status = "running"
        changed = True
    elif task_result.state == "SUCCESS":
        job.status = "completed"
        job.progress = 100
        if job.result is None and task_result.result is not None:
            result = task_result.result
            if (
                isinstance(result, dict)
                and isinstance(result.get("progress"), int)
                and "result" in result
            ):
                result = result["result"]
            job.result = result
        job.error = None
        changed = True
    elif task_result.state == "FAILURE":
        job.status = "failed"
        job.error = str(task_result.result) or "Background task failed."
        changed = True
    elif task_result.state == "REVOKED":
        job.status = "failed"
        job.error = "Background task was revoked."
        changed = True

    if changed:
        db.commit()
        db.refresh(job)


@router.post("/invoices/{order_id}")
def request_invoice(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Order).filter(Order.id == order_id)
    if current_user.role != "admin":
        query = query.filter(Order.user_id == current_user.id)
    if query.first() is None:
        raise HTTPException(status_code=404, detail="Order not found")

    _require_worker()
    job = BackgroundJob(
        id=str(uuid4()),
        user_id=current_user.id,
        task_type="invoice",
        resource_id=order_id,
    )
    db.add(job)
    db.commit()
    try:
        generate_invoice.apply_async(args=[job.id, order_id], task_id=job.id)
    except Exception as error:
        db.delete(job)
        db.commit()
        logger.exception("Unable to queue invoice job for order %s", order_id)
        raise HTTPException(status_code=503, detail="Invoice generation is currently unavailable.") from error
    return success_response(data=_job_data(job), message="Invoice generation started")


@router.get("/invoices/{order_id}/download")
def download_invoice(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Order).filter(Order.id == order_id)
    if current_user.role != "admin":
        query = query.filter(Order.user_id == current_user.id)
    if query.first() is None:
        raise HTTPException(status_code=404, detail="Order not found")

    invoice_job = (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.task_type == "invoice",
            BackgroundJob.status == "completed",
            BackgroundJob.resource_id == order_id,
        )
        .first()
    )
    path = PRIVATE_FILES / f"invoice-{order_id}.pdf"
    if invoice_job is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Invoice has not been generated yet")
    return FileResponse(path, media_type="application/pdf", filename=f"invoice-{order_id}.pdf")


@router.post("/imports/products")
async def request_product_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="Upload a .csv file.")
    content = await file.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV files must be 10 MB or smaller.")
    if not content:
        raise HTTPException(status_code=400, detail="The CSV file is empty.")

    _require_worker()
    job_id = str(uuid4())
    PRIVATE_FILES.mkdir(parents=True, exist_ok=True)
    path = PRIVATE_FILES / f"import-{job_id}.csv"
    path.write_bytes(content)
    job = BackgroundJob(id=job_id, user_id=current_user.id, task_type="product_import")
    db.add(job)
    db.commit()
    try:
        import_products_csv.apply_async(args=[job.id, current_user.id, str(path)], task_id=job.id)
    except Exception as error:
        path.unlink(missing_ok=True)
        db.delete(job)
        db.commit()
        logger.exception("Unable to queue product import job")
        raise HTTPException(status_code=503, detail="Product import is currently unavailable.") from error
    return success_response(data=_job_data(job), message="Product import started")


@router.get("/")
def list_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(BackgroundJob)
    if current_user.role != "admin":
        query = query.filter(BackgroundJob.user_id == current_user.id)
    jobs = query.order_by(BackgroundJob.created_at.desc()).limit(100).all()
    for job in jobs:
        _refresh_job_state(job, db)
    return success_response(data=[_job_data(job) for job in jobs], message="Background jobs fetched")


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(BackgroundJob).filter(BackgroundJob.id == job_id)
    if current_user.role != "admin":
        query = query.filter(BackgroundJob.user_id == current_user.id)
    job = query.first()
    if job is None:
        raise HTTPException(status_code=404, detail="Background job not found")

    _refresh_job_state(job, db)
    return success_response(data=_job_data(job), message="Background job status fetched")
