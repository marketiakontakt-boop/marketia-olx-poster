"""Data layer: shared SQLite DB + XML product loader + price calculator."""

from .shared_db import (
    DB_PATH,
    get_connection,
    run_migrations,
    save_listing,
    get_pending_jobs,
    mark_job_status,
    get_or_create_account_meta,
    variant_cache_get,
    variant_cache_save,
    load_from_shared_db,
)
from .product_loader import Product, load_from_xml
from .price_calculator import calculate_price

__all__ = [
    "DB_PATH",
    "get_connection",
    "run_migrations",
    "save_listing",
    "get_pending_jobs",
    "mark_job_status",
    "get_or_create_account_meta",
    "variant_cache_get",
    "variant_cache_save",
    "load_from_shared_db",
    "Product",
    "load_from_xml",
    "calculate_price",
]
