import csv
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import selectinload

from app.celery.worker import celery_app
from app.database.database import SessionLocal
from app.models.background_job import BackgroundJob
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.utils.invoice import create_invoice_pdf

logger = logging.getLogger(__name__)
PRIVATE_FILES = Path(__file__).resolve().parents[2] / "private_files"
PAYMENT_METHOD_LABELS = {
    "card": "Card",
    "upi": "UPI",
    "cash_on_delivery": "Cash on delivery",
}


def _save_job(job_id: str, **values: Any) -> None:
    db = SessionLocal()
    try:
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if job is None:
            raise RuntimeError(f"Background job {job_id} no longer exists")
        for key, value in values.items():
            setattr(job, key, value)
        db.commit()
    finally:
        db.close()


@celery_app.task(name="send_order_email")
def send_order_email(email: str, order_id: int):
    logger.info("Order confirmation email queued for %s (order %s)", email, order_id)
    return "Email queued"


@celery_app.task(name="periodic_system_heartbeat")
def periodic_system_heartbeat():
    logger.info("Celery Beat heartbeat: background scheduler is active.")
    return "Heartbeat OK"


@celery_app.task(bind=True, name="generate_product_content")
def generate_product_content_task(self, job_id: str, owner_id: int, values: dict[str, Any]):
    _save_job(job_id, status="running", progress=10, error=None)
    self.update_state(state="PROGRESS", meta={"progress": 10})
    try:
        from app.services.ai_features_service import generate_product_content

        result = generate_product_content(
            values["name"],
            values["price"],
            brand=values.get("brand"),
            category=values.get("category"),
            feature_details=values.get("features"),
            stock=values.get("stock"),
            existing_description=values.get("existing_description"),
            cache_scope=f"user:{owner_id}",
        )
        _save_job(job_id, status="completed", progress=100, result=result, error=None)
        return result
    except Exception as error:
        _save_job(job_id, status="failed", error=str(error))
        logger.exception("AI product content generation failed for job %s", job_id)
        raise


@celery_app.task(bind=True, name="generate_invoice")
def generate_invoice(self, job_id: str, order_id: int):
    _save_job(job_id, status="running", progress=10, error=None)
    self.update_state(state="PROGRESS", meta={"progress": 10})
    db = SessionLocal()
    try:
        order = (
            db.query(Order)
            .options(selectinload(Order.items).joinedload(OrderItem.product))
            .filter(Order.id == order_id)
            .first()
        )
        if order is None:
            raise ValueError("Order not found")

        lines = [
            "COMMON GOODS",
            f"INVOICE #{order.id:05d}",
            f"Date: {order.created_at:%Y-%m-%d}",
            f"Customer: {(order.shipping_address or {}).get('full_name', 'Customer')}",
            "",
            "ITEMS",
        ]
        for item in order.items:
            name = item.product.name if item.product else f"Product #{item.product_id}"
            lines.append(f"{item.quantity} x {name}  -  {item.price * item.quantity:.2f}")
        payment_method = PAYMENT_METHOD_LABELS.get(order.payment_method, "Not specified")
        lines.extend([
            "",
            f"TOTAL: {order.total_amount:.2f}",
            "",
            "PAYMENT DETAILS",
            f"Method: {payment_method}",
            "Status: Demo only; no payment was processed",
        ])
        PRIVATE_FILES.mkdir(parents=True, exist_ok=True)
        path = PRIVATE_FILES / f"invoice-{order.id}.pdf"
        path.write_bytes(create_invoice_pdf(lines))
        result = {
            "order_id": order.id,
            "total_amount": order.total_amount,
            "download_url": f"/jobs/invoices/{order.id}/download",
        }
        _save_job(job_id, status="completed", progress=100, result=result, error=None)
        return result
    except Exception as error:
        db.rollback()
        _save_job(job_id, status="failed", error=str(error))
        logger.exception("Invoice generation failed for order %s", order_id)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="import_products_csv")
def import_products_csv(self, job_id: str, owner_id: int, file_path: str):
    source = Path(file_path)
    errors: list[str] = []
    error_count = 0
    imported = 0
    processed = 0
    _save_job(job_id, status="running", progress=0, error=None)
    db = SessionLocal()
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as csv_file:
            count_reader = csv.DictReader(csv_file)
            required = {"name", "price", "stock"}
            headers = {header.strip().lower() for header in (count_reader.fieldnames or [])}
            if not required.issubset(headers):
                raise ValueError("CSV must include name, price, and stock columns.")
            total_rows = sum(1 for _ in count_reader)
        with source.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row_number, raw_row in enumerate(reader, start=2):
                processed += 1
                row = {(key or "").strip().lower(): (value or "").strip() for key, value in raw_row.items()}
                try:
                    name = row.get("name", "")
                    price = float(row.get("price", ""))
                    stock = int(row.get("stock", ""))
                    if not name or len(name) > 100 or price < 0 or stock < 0:
                        raise ValueError("name, non-negative price, and non-negative stock are required")
                    image_url = row.get("image_url") or None
                    if image_url:
                        parsed_image_url = urlparse(image_url)
                        if parsed_image_url.scheme not in {"http", "https"} or not parsed_image_url.netloc:
                            raise ValueError("image_url must be an absolute http or https URL")
                    db.add(Product(
                        name=name,
                        description=row.get("description") or None,
                        price=price,
                        stock=stock,
                        image_url=image_url,
                        owner_id=owner_id,
                    ))
                    imported += 1
                    if imported % 25 == 0:
                        db.commit()
                except (ValueError, TypeError) as error:
                    error_count += 1
                    if len(errors) < 100:
                        errors.append(f"Row {row_number}: {error}")
                progress = min(95, int(processed / max(total_rows, 1) * 95))
                update_interval = max(1, total_rows // 100)
                if processed % update_interval == 0 or processed == total_rows:
                    _save_job(job_id, progress=progress)
                    self.update_state(state="PROGRESS", meta={"progress": progress, "processed": processed})
        db.commit()
        result = {
            "imported": imported,
            "processed": processed,
            "error_count": error_count,
            "errors": errors,
        }
        _save_job(job_id, status="completed", progress=100, result=result, error=None)
        return result
    except Exception as error:
        db.rollback()
        _save_job(job_id, status="failed", error=str(error))
        logger.exception("CSV import failed for job %s", job_id)
        raise
    finally:
        db.close()
        source.unlink(missing_ok=True)
