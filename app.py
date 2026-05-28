#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from base64 import b64encode
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urljoin, urlparse

import gdown
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename


def load_local_env(env_path: Path):
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


load_local_env(Path(__file__).with_name(".env"))

app = Flask(
    __name__,
    static_folder="public/static",
    static_url_path="/static",
    template_folder="templates",
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 * 1024


def env_flag(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


IS_VERCEL = env_flag("VERCEL", "false") or bool(os.environ.get("VERCEL_ENV"))

API_VERSION = "v25.0"
DEFAULT_DRIVE_LINK = os.environ.get("DEFAULT_DRIVE_LINK", "")
DEFAULT_AD_ACCOUNT_ID = os.environ.get("DEFAULT_AD_ACCOUNT_ID", "")
DEFAULT_ACCESS_TOKEN = os.environ.get("DEFAULT_ACCESS_TOKEN", "")
DEFAULT_CAMPAIGN_REF = os.environ.get("DEFAULT_CAMPAIGN_REF", "")
DEFAULT_ADSET_REF = os.environ.get("DEFAULT_ADSET_REF", "")
DEFAULT_PAGE_ID = os.environ.get("DEFAULT_PAGE_ID", "")
DEFAULT_DESTINATION_URL = os.environ.get("DEFAULT_DESTINATION_URL", "")
DEFAULT_PRIMARY_TEXT = os.environ.get("DEFAULT_PRIMARY_TEXT", "")
DEFAULT_HEADLINE = os.environ.get("DEFAULT_HEADLINE", "")
DEFAULT_CTA_TYPE = os.environ.get("DEFAULT_CTA_TYPE", "LEARN_MORE")
APP_VERSION = (
    os.environ.get("APP_VERSION")
    or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    or os.environ.get("RAILWAY_DEPLOYMENT_ID")
    or "local-dev"
)
APP_BOOT_UTC = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

JOB_DIR = Path("/tmp/fb_media_jobs")
TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "stopped"}
ERP_DB_PATH = Path(
    os.environ.get(
        "ERP_DB_PATH",
        "/tmp/erp_orders.db" if IS_VERCEL else str(Path(__file__).with_name("erp_orders.db")),
    )
)
PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "auto").strip().lower() or "auto"
RAZORPAY_API_BASE_URL = os.environ.get("RAZORPAY_API_BASE_URL", "https://api.razorpay.com/v1").strip()
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
RAZORPAY_CALLBACK_URL = os.environ.get("RAZORPAY_CALLBACK_URL", "").strip()
PAYMENT_SUCCESS_URL = os.environ.get("PAYMENT_SUCCESS_URL", "").strip()
RAZORPAY_LINK_EXPIRY_HOURS = int(os.environ.get("RAZORPAY_LINK_EXPIRY_HOURS", "24"))
RAZORPAY_NOTIFY_SMS = env_flag("RAZORPAY_NOTIFY_SMS", "true")
RAZORPAY_NOTIFY_EMAIL = env_flag("RAZORPAY_NOTIFY_EMAIL", "true")
RAZORPAY_REMINDER_ENABLE = env_flag("RAZORPAY_REMINDER_ENABLE", "true")
XPAY_LINK_API_URL = os.environ.get("XPAY_LINK_API_URL", "").strip()
XPAY_SYNC_API_URL = os.environ.get("XPAY_SYNC_API_URL", "").strip()
XPAY_API_KEY = os.environ.get("XPAY_API_KEY", "").strip()
XPAY_PAYMENT_LINK_TEMPLATE = os.environ.get("XPAY_PAYMENT_LINK_TEMPLATE", "").strip()
XPAY_PAYMENT_LINK_BASE = os.environ.get("XPAY_PAYMENT_LINK_BASE", "https://xpay.local/pay").strip()
XPAY_API_BASE_URL = os.environ.get("XPAY_API_BASE_URL", "https://api.xpaycheckout.com").strip()
XPAY_PUBLIC_KEY = os.environ.get("XPAY_PUBLIC_KEY", "").strip()
XPAY_PRIVATE_KEY = (
    os.environ.get("XPAY_PRIVATE_KEY", "").strip()
    or os.environ.get("XPAY_SECRET_KEY", "").strip()
)
XPAY_CALLBACK_URL = os.environ.get("XPAY_CALLBACK_URL", "").strip()
XPAY_CANCEL_URL = os.environ.get("XPAY_CANCEL_URL", "").strip()
XPAY_LINK_EXPIRY_HOURS = int(os.environ.get("XPAY_LINK_EXPIRY_HOURS", "24"))
XPAY_PHONE_REQUIRED = env_flag("XPAY_PHONE_REQUIRED", "false")
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "INR").strip().upper() or "INR"
SUPPORTED_CURRENCIES = [
    c.strip().upper()
    for c in (os.environ.get("SUPPORTED_CURRENCIES", "INR,USD,EUR,GBP,AED,SGD").split(","))
    if c.strip()
]
if DEFAULT_CURRENCY not in SUPPORTED_CURRENCIES:
    SUPPORTED_CURRENCIES.insert(0, DEFAULT_CURRENCY)


class StopRequested(Exception):
    pass


def now_ts() -> int:
    return int(time.time())


def _job_path(job_id: str) -> Path:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    return JOB_DIR / f"{job_id}.json"


def save_job(job_id: str, payload: Dict):
    path = _job_path(job_id)
    tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True))
    tmp.replace(path)


def load_job(job_id: str):
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def update_job(job_id: str, **fields):
    payload = load_job(job_id) or {}
    payload.update(fields)
    payload["updated_at"] = now_ts()
    save_job(job_id, payload)


def set_job_control(job_id: str, action: str):
    payload = load_job(job_id)
    if not payload:
        return None

    if payload.get("status") in TERMINAL_STATUSES:
        return payload

    if action == "pause":
        payload["control"] = "pause"
        if payload.get("status") != "paused":
            payload["status"] = "paused"
            payload["step"] = "Paused by user"
    elif action == "resume":
        payload["control"] = "run"
        if payload.get("status") == "paused":
            payload["status"] = "running"
            payload["step"] = payload.get("last_step") or "Resumed"
    elif action == "stop":
        payload["control"] = "stop"
        payload["status"] = "stopping"
        payload["step"] = "Stopping..."
    else:
        return payload

    payload["updated_at"] = now_ts()
    save_job(job_id, payload)
    return payload


def control_checkpoint(job_id: str):
    while True:
        payload = load_job(job_id) or {}
        control = payload.get("control", "run")

        if control == "stop":
            if payload.get("status") not in TERMINAL_STATUSES:
                payload["status"] = "stopped"
                payload["ok"] = False
                payload["step"] = "Stopped by user"
                payload["eta_seconds"] = 0
                payload["updated_at"] = now_ts()
                save_job(job_id, payload)
            raise StopRequested("Stopped by user")

        if control == "pause":
            if payload.get("status") != "paused":
                payload["status"] = "paused"
                payload["step"] = "Paused by user"
                payload["updated_at"] = now_ts()
                save_job(job_id, payload)
            time.sleep(0.6)
            continue

        if payload.get("status") == "paused":
            payload["status"] = "running"
            payload["step"] = payload.get("last_step") or "Resumed"
            payload["updated_at"] = now_ts()
            save_job(job_id, payload)

        return payload


def format_job_state_for_api(payload: Dict):
    data = dict(payload)
    items = data.get("items")
    if isinstance(items, list):
        uploaded_count = sum(1 for i in items if i.get("status") == "uploaded")
        failed_count = sum(1 for i in items if i.get("status") == "failed")
        removed_count = sum(1 for i in items if i.get("status") == "removed")
        processed_count = uploaded_count + failed_count + removed_count
    else:
        uploaded_count = 0
        failed_count = 0
        removed_count = 0
        processed_count = 0

    data["uploaded_count"] = uploaded_count
    data["failed_count"] = failed_count
    data["removed_count"] = removed_count
    data["processed_count"] = processed_count
    return data


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    return datetime.now().date().isoformat()


def get_erp_conn():
    ERP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ERP_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_erp_db():
    with get_erp_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS erp_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_uid TEXT NOT NULL UNIQUE,
                order_type TEXT NOT NULL CHECK (order_type IN ('puja', 'ecommerce')),
                payment_provider TEXT NOT NULL DEFAULT 'manual',
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                payment_date TEXT NOT NULL,
                order_date TEXT NOT NULL,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                payment_link TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                payment_status TEXT NOT NULL DEFAULT 'unpaid',
                paid_at TEXT,
                payment_txn_id TEXT,
                payment_amount TEXT,
                payment_payload TEXT,
                puja_name TEXT,
                temple_name TEXT,
                puja_schedule_date TEXT,
                address_line1 TEXT,
                address_line2 TEXT,
                city TEXT,
                state TEXT,
                postal_code TEXT,
                item_name TEXT,
                quantity INTEGER,
                notes TEXT,
                xpay_reference TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                raw_payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_erp_orders_created_at ON erp_orders(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_erp_orders_type ON erp_orders(order_type)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_erp_orders_xpay_ref ON erp_orders(xpay_reference)")

        # Lightweight schema migration for existing local DBs.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(erp_orders)").fetchall()}
        migration_columns = [
            ("payment_provider", "TEXT NOT NULL DEFAULT 'manual'"),
            ("payment_status", "TEXT NOT NULL DEFAULT 'unpaid'"),
            ("paid_at", "TEXT"),
            ("payment_txn_id", "TEXT"),
            ("payment_amount", "TEXT"),
            ("payment_payload", "TEXT"),
            ("currency", f"TEXT NOT NULL DEFAULT '{DEFAULT_CURRENCY}'"),
        ]
        for name, ddl in migration_columns:
            if name not in existing_cols:
                conn.execute(f"ALTER TABLE erp_orders ADD COLUMN {name} {ddl}")


def parse_date_input(raw_value: str, fallback: str = "") -> str:
    value = str(raw_value or "").strip()
    if not value:
        return fallback

    for parser in (
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")).date(),
        lambda x: datetime.strptime(x, "%Y-%m-%d").date(),
        lambda x: datetime.strptime(x, "%d/%m/%Y").date(),
        lambda x: datetime.strptime(x, "%d-%m-%Y").date(),
        lambda x: datetime.strptime(x, "%m/%d/%Y").date(),
    ):
        try:
            return parser(value).isoformat()
        except Exception:
            continue
    return fallback


def parse_amount(raw_value: Any) -> str:
    text = str(raw_value or "").strip().replace(",", "")
    if not text:
        raise ValueError("Amount is required.")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Amount must be a valid number.")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return f"{amount}"


def parse_currency(raw_value: Any, fallback: str = DEFAULT_CURRENCY) -> str:
    value = str(raw_value or "").strip().upper()
    currency = value or fallback
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError(
            f"Currency '{currency}' is not supported. Allowed: {', '.join(SUPPORTED_CURRENCIES)}."
        )
    return currency


def amount_to_minor_units(amount: Decimal, currency: str) -> int:
    zero_decimal_currencies = {"JPY", "KRW", "VND", "CLP"}
    three_decimal_currencies = {"BHD", "KWD", "OMR"}
    if currency in zero_decimal_currencies:
        exponent = Decimal("1")
    elif currency in three_decimal_currencies:
        exponent = Decimal("1000")
    else:
        exponent = Decimal("100")
    return int((amount * exponent).to_integral_value())


def minor_units_to_amount(raw_value: Any, currency: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    try:
        minor_units = Decimal(text)
    except (InvalidOperation, ValueError):
        return ""

    zero_decimal_currencies = {"JPY", "KRW", "VND", "CLP"}
    three_decimal_currencies = {"BHD", "KWD", "OMR"}
    if currency in zero_decimal_currencies:
        divisor = Decimal("1")
        precision = Decimal("1")
    elif currency in three_decimal_currencies:
        divisor = Decimal("1000")
        precision = Decimal("0.001")
    else:
        divisor = Decimal("100")
        precision = Decimal("0.01")

    return f"{(minor_units / divisor).quantize(precision)}"


def build_basic_authorization(username: str, password: str) -> str:
    if not (username and password):
        return ""
    raw = f"{username}:{password}"
    token = b64encode(raw.encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def build_xpay_basic_authorization() -> str:
    return build_basic_authorization(XPAY_PUBLIC_KEY, XPAY_PRIVATE_KEY)


def build_razorpay_basic_authorization() -> str:
    return build_basic_authorization(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)


def normalize_contact_number(phone: str) -> str:
    value = str(phone or "").strip()
    if not value:
        return ""
    if value.startswith("+"):
        return value
    digits = re.sub(r"\D+", "", value)
    if not digits:
        return ""
    if len(digits) == 10:
        return f"+91{digits}"
    return f"+{digits}"


def build_xpay_link_payload(
    *,
    amount_decimal: Decimal,
    currency: str,
    order_type: str,
    metadata: Dict,
    order_uid: str,
) -> Dict:
    customer_name = str((metadata or {}).get("customer_name") or "").strip() or "Customer"
    customer_email = str((metadata or {}).get("email") or "").strip()
    customer_phone = normalize_contact_number(str((metadata or {}).get("phone") or "").strip())

    payload = {
        "amount": amount_to_minor_units(amount_decimal, currency),
        "currency": currency,
        "customerDetails": {
            "name": customer_name,
            "email": customer_email,
        },
        "expiryDate": int((time.time() + (XPAY_LINK_EXPIRY_HOURS * 3600)) * 1000),
        "receiptId": order_uid or uuid.uuid4().hex[:16],
        "description": str((metadata or {}).get("description") or f"{order_type} booking").strip(),
        "phoneNumberRequired": XPAY_PHONE_REQUIRED,
    }
    if customer_phone:
        payload["customerDetails"]["contactNumber"] = customer_phone
    if XPAY_CALLBACK_URL:
        payload["callbackUrl"] = XPAY_CALLBACK_URL
    if XPAY_CANCEL_URL:
        payload["cancelUrl"] = XPAY_CANCEL_URL

    return payload


def build_razorpay_link_payload(
    *,
    amount_decimal: Decimal,
    currency: str,
    order_type: str,
    metadata: Dict,
    order_uid: str,
) -> Dict:
    customer_name = str((metadata or {}).get("customer_name") or "").strip() or "Customer"
    customer_email = str((metadata or {}).get("email") or "").strip()
    customer_phone = normalize_contact_number(str((metadata or {}).get("phone") or "").strip())

    customer_payload: Dict[str, Any] = {"name": customer_name}
    if customer_phone:
        customer_payload["contact"] = customer_phone
    if customer_email:
        customer_payload["email"] = customer_email

    payload: Dict[str, Any] = {
        "amount": amount_to_minor_units(amount_decimal, currency),
        "currency": currency,
        "accept_partial": False,
        "expire_by": int(time.time()) + (RAZORPAY_LINK_EXPIRY_HOURS * 3600),
        "reference_id": (order_uid or uuid.uuid4().hex[:16])[:40],
        "description": str((metadata or {}).get("description") or f"{order_type} booking").strip(),
        "customer": customer_payload,
        "notify": {
            "sms": RAZORPAY_NOTIFY_SMS,
            "email": RAZORPAY_NOTIFY_EMAIL,
        },
        "reminder_enable": RAZORPAY_REMINDER_ENABLE,
        "notes": {
            "order_uid": order_uid or "",
            "order_type": order_type,
        },
    }
    _redirect = PAYMENT_SUCCESS_URL or RAZORPAY_CALLBACK_URL
    if _redirect:
        payload["callback_url"] = _redirect
        payload["callback_method"] = "get"
    return payload


def extract_error_message(body: Any) -> str:
    if isinstance(body, dict):
        for path in (
            ("error", "description"),
            ("error", "reason"),
            ("errorDescription",),
            ("message",),
            ("description",),
        ):
            current = body
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current.get(key)
            if current:
                return str(current).strip()
    text = str(body or "").strip()
    return text or "Unknown API error."


def get_active_payment_provider() -> str:
    preferred = PAYMENT_PROVIDER
    if preferred in {"razorpay", "xpay"}:
        return preferred
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        return "razorpay"
    if XPAY_PUBLIC_KEY and XPAY_PRIVATE_KEY:
        return "xpay"
    return "custom"


def format_payment_provider_label(provider: str) -> str:
    mapping = {
        "razorpay": "Razorpay",
        "xpay": "XPay",
        "custom": "Custom",
        "manual": "Manual",
    }
    return mapping.get(str(provider or "").strip().lower(), str(provider or "").strip().title() or "Unknown")


def get_payment_webhook_path() -> str:
    provider = get_active_payment_provider()
    if provider == "razorpay":
        return "/api/erp/razorpay/webhook"
    return "/api/erp/xpay/webhook"


def parse_unix_date(raw_value: Any, fallback: str = "") -> str:
    text = str(raw_value or "").strip()
    if not text:
        return fallback
    try:
        return datetime.fromtimestamp(int(float(text)), tz=timezone.utc).date().isoformat()
    except Exception:
        return fallback


def verify_razorpay_webhook_signature(raw_body: bytes, signature: str) -> None:
    if not RAZORPAY_WEBHOOK_SECRET:
        return
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(signature or "").strip()):
        raise ValueError("Razorpay webhook signature verification failed.")


def parse_positive_int(raw_value: Any, fallback: int = 1) -> int:
    text = str(raw_value or "").strip()
    if not text:
        return fallback
    try:
        value = int(text)
    except Exception:
        raise ValueError("Quantity must be a whole number.")
    if value <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return value


def build_order_uid() -> str:
    return f"ASB-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def extract_payment_link(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("short_url", "shortUrl", "payment_link", "paymentLink", "url", "link"):
            value = body.get(key)
            if value:
                return str(value).strip()
        data = body.get("data")
        if isinstance(data, dict):
            return extract_payment_link(data)
    return ""


def extract_gateway_reference(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("id", "reference", "payment_link_id", "paymentLinkId"):
            value = body.get(key)
            if value:
                return str(value).strip()
        data = body.get("data")
        if isinstance(data, dict):
            return extract_gateway_reference(data)
    return ""


def create_payment_link_details(
    amount: str,
    order_type: str,
    metadata: Dict = None,
    order_uid: str = "",
    currency: str = DEFAULT_CURRENCY,
) -> Dict:
    amount_decimal = Decimal(amount)
    final_currency = parse_currency(currency)
    amount_minor_units = amount_to_minor_units(amount_decimal, final_currency)
    meta = dict(metadata or {})
    if order_uid:
        meta["order_uid"] = order_uid
    payload = {
        "amount": float(amount_decimal),
        "amount_text": f"{amount_decimal}",
        "amount_in_minor_units": amount_minor_units,
        "currency": final_currency,
        "order_type": order_type,
        "merchant_order_id": order_uid or None,
        "metadata": meta,
    }

    provider = get_active_payment_provider()

    if provider == "razorpay":
        razorpay_auth = build_razorpay_basic_authorization()
        if not razorpay_auth:
            raise RuntimeError(
                "Razorpay is selected but RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are not configured."
            )

        razorpay_payload = build_razorpay_link_payload(
            amount_decimal=amount_decimal,
            currency=final_currency,
            order_type=order_type,
            metadata=meta,
            order_uid=order_uid,
        )
        razorpay_headers = {
            "Content-Type": "application/json",
            "Authorization": razorpay_auth,
        }
        razorpay_url = f"{RAZORPAY_API_BASE_URL.rstrip('/')}/payment_links"
        resp = requests.post(razorpay_url, json=razorpay_payload, headers=razorpay_headers, timeout=60)
        body = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            message = extract_error_message(body)
            raise RuntimeError(f"Razorpay payment-link creation failed with HTTP {resp.status_code}: {message}")
        link = extract_payment_link(body)
        if not link:
            raise RuntimeError("Razorpay response did not include a payment link (`short_url`).")
        return {
            "payment_provider": "razorpay",
            "payment_link": link,
            "gateway_reference": extract_gateway_reference(body),
            "raw_response": body,
        }

    # Direct xPay integration (from official xPay Payment Links API docs).
    xpay_auth = build_xpay_basic_authorization()
    if provider == "xpay" and xpay_auth:
        xpay_payload = build_xpay_link_payload(
            amount_decimal=amount_decimal,
            currency=final_currency,
            order_type=order_type,
            metadata=meta,
            order_uid=order_uid,
        )
        xpay_headers = {
            "Content-Type": "application/json",
            "Authorization": xpay_auth,
        }
        if order_uid:
            xpay_headers["Idempotency-Key"] = order_uid

        xpay_url = f"{XPAY_API_BASE_URL.rstrip('/')}/link/merchant/generate-link"
        resp = requests.post(xpay_url, json=xpay_payload, headers=xpay_headers, timeout=60)
        body = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            message = extract_error_message(body)
            if "Authentication Failed" in str(message):
                raise RuntimeError(
                    "xPay authentication failed. Verify that the server is using your xPay "
                    "Public Key and xPay Private Key from the xPay dashboard API Keys page."
                )
            raise RuntimeError(f"xPay generate-link failed with HTTP {resp.status_code}: {message}")
        link = extract_payment_link(body)
        if not link:
            raise RuntimeError("xPay response did not include a payment link (`shortUrl`).")
        return {
            "payment_provider": "xpay",
            "payment_link": link,
            "gateway_reference": extract_gateway_reference(body),
            "raw_response": body,
        }

    headers = {"Content-Type": "application/json"}
    if XPAY_API_KEY:
        headers["Authorization"] = f"Bearer {XPAY_API_KEY}"

    if XPAY_LINK_API_URL:
        resp = requests.post(XPAY_LINK_API_URL, json=payload, headers=headers, timeout=60)
        body = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            raise RuntimeError(f"XPay payment-link API failed with HTTP {resp.status_code}: {body}")
        link = extract_payment_link(body)
        if not link:
            raise RuntimeError("XPay API response did not include a payment link URL.")
        return {
            "payment_provider": "custom",
            "payment_link": link,
            "gateway_reference": extract_gateway_reference(body),
            "raw_response": body,
        }

    if XPAY_PAYMENT_LINK_TEMPLATE:
        try:
            link = XPAY_PAYMENT_LINK_TEMPLATE.format(
                amount=f"{amount_decimal}",
                amount_in_paise=amount_minor_units,
                currency=final_currency,
                order_type=order_type,
                order_uid=order_uid,
                ref=uuid.uuid4().hex[:10],
            )
        except Exception as exc:
            raise RuntimeError(f"Invalid XPAY_PAYMENT_LINK_TEMPLATE: {exc}")
        return {
            "payment_provider": "custom",
            "payment_link": link,
            "gateway_reference": "",
            "raw_response": payload,
        }

    return {
        "payment_provider": "custom",
        "payment_link": (
            f"{XPAY_PAYMENT_LINK_BASE}"
            f"?amount={amount_decimal}&amount_in_paise={amount_minor_units}&currency={final_currency}&order_type={order_type}"
            f"&order_uid={order_uid}&ref={uuid.uuid4().hex[:10]}"
        ),
        "gateway_reference": "",
        "raw_response": payload,
    }


def create_payment_link(
    amount: str,
    order_type: str,
    metadata: Dict = None,
    order_uid: str = "",
    currency: str = DEFAULT_CURRENCY,
) -> str:
    return create_payment_link_details(
        amount=amount,
        order_type=order_type,
        metadata=metadata,
        order_uid=order_uid,
        currency=currency,
    )["payment_link"]


def serialize_order_row(row: sqlite3.Row) -> Dict:
    return {
        "id": row["id"],
        "order_uid": row["order_uid"],
        "order_type": row["order_type"],
        "payment_provider": row["payment_provider"],
        "customer_name": row["customer_name"],
        "phone": row["phone"],
        "email": row["email"],
        "payment_date": row["payment_date"],
        "order_date": row["order_date"],
        "amount": row["amount"],
        "currency": row["currency"],
        "payment_link": row["payment_link"],
        "status": row["status"],
        "payment_status": row["payment_status"],
        "paid_at": row["paid_at"],
        "payment_txn_id": row["payment_txn_id"],
        "payment_amount": row["payment_amount"],
        "puja_name": row["puja_name"],
        "temple_name": row["temple_name"],
        "puja_schedule_date": row["puja_schedule_date"],
        "address_line1": row["address_line1"],
        "address_line2": row["address_line2"],
        "city": row["city"],
        "state": row["state"],
        "postal_code": row["postal_code"],
        "item_name": row["item_name"],
        "quantity": row["quantity"],
        "notes": row["notes"],
        "gateway_reference": row["xpay_reference"],
        "xpay_reference": row["xpay_reference"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_order(payload: Dict) -> Dict:
    order_type = str(payload.get("order_type") or "").strip().lower()
    if order_type not in {"puja", "ecommerce"}:
        raise ValueError("Order type must be either 'puja' or 'ecommerce'.")

    customer_name = str(payload.get("customer_name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    email = str(payload.get("email") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    payment_date = parse_date_input(payload.get("payment_date"), fallback=today_iso())
    amount = parse_amount(payload.get("amount"))
    currency = parse_currency(payload.get("currency"), fallback=DEFAULT_CURRENCY)
    order_date = payment_date

    if not customer_name:
        raise ValueError("Customer name is required.")
    if not phone:
        raise ValueError("Phone number is required.")
    if not payment_date:
        raise ValueError("Payment date is required.")

    puja_name = None
    temple_name = None
    puja_schedule_date = None
    address_line1 = None
    address_line2 = None
    city = None
    state = None
    postal_code = None
    item_name = None
    quantity = None

    if order_type == "puja":
        puja_name = str(payload.get("puja_name") or "").strip()
        temple_name = str(payload.get("temple_name") or "").strip()
        puja_schedule_date = parse_date_input(str(payload.get("puja_schedule_date") or "").strip())
        if not puja_name:
            raise ValueError("Puja name is required for Puja orders.")
        if not temple_name:
            raise ValueError("Temple name is required for Puja orders.")
        if not puja_schedule_date:
            raise ValueError("Puja schedule date is required for Puja orders.")
    else:
        address_line1 = str(payload.get("address_line1") or "").strip()
        address_line2 = str(payload.get("address_line2") or "").strip()
        city = str(payload.get("city") or "").strip()
        state = str(payload.get("state") or "").strip()
        postal_code = str(payload.get("postal_code") or "").strip()
        item_name = str(payload.get("item_name") or "").strip()
        quantity = parse_positive_int(payload.get("quantity"), fallback=1)
        if not address_line1:
            raise ValueError("Address line 1 is required for e-commerce orders.")
        if not city:
            raise ValueError("City is required for e-commerce orders.")
        if not state:
            raise ValueError("State is required for e-commerce orders.")
        if not postal_code:
            raise ValueError("Postal code is required for e-commerce orders.")
        if not item_name:
            raise ValueError("Item name is required for e-commerce orders.")

    order_uid = str(payload.get("order_uid") or "").strip() or build_order_uid()
    payment_link = str(payload.get("payment_link") or "").strip()
    payment_provider = str(payload.get("payment_provider") or get_active_payment_provider()).strip().lower() or "manual"
    gateway_reference = str(payload.get("gateway_reference") or payload.get("xpay_reference") or "").strip() or None
    if not payment_link:
        if order_type == "puja":
            _description = f"Puja – {puja_name} at {temple_name}"
        else:
            _description = item_name or "E-commerce Order"
        link_data = create_payment_link_details(
            amount=amount,
            order_type=order_type,
            metadata={
                "customer_name": customer_name,
                "phone": phone,
                "email": email,
                "description": _description,
            },
            order_uid=order_uid,
            currency=currency,
        )
        payment_link = link_data["payment_link"]
        payment_provider = str(link_data.get("payment_provider") or payment_provider or "manual").strip().lower()
        gateway_reference = str(link_data.get("gateway_reference") or gateway_reference or "").strip() or None

    now = utc_now_iso()
    status = str(payload.get("status") or "pending").strip() or "pending"
    payment_status = str(payload.get("payment_status") or "unpaid").strip() or "unpaid"
    source = str(payload.get("source") or "manual").strip() or "manual"
    raw_payload = payload.get("raw_payload")

    with get_erp_conn() as conn:
        conn.execute(
            """
            INSERT INTO erp_orders (
                order_uid, order_type, payment_provider, customer_name, phone, email,
                payment_date, order_date, amount, currency, payment_link, status,
                payment_status, paid_at, payment_txn_id, payment_amount, payment_payload,
                puja_name, temple_name, puja_schedule_date,
                address_line1, address_line2, city, state, postal_code,
                item_name, quantity, notes, xpay_reference, source,
                raw_payload, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                order_uid,
                order_type,
                payment_provider,
                customer_name,
                phone,
                email,
                payment_date,
                order_date,
                amount,
                currency,
                payment_link,
                status,
                payment_status,
                None,
                None,
                None,
                None,
                puja_name,
                temple_name,
                puja_schedule_date,
                address_line1,
                address_line2,
                city,
                state,
                postal_code,
                item_name,
                quantity,
                notes,
                gateway_reference,
                source,
                raw_payload,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM erp_orders WHERE order_uid = ?", (order_uid,)).fetchone()
    return serialize_order_row(row)


def list_orders(limit: int = 100, order_type: str = "") -> List[Dict]:
    safe_limit = max(1, min(int(limit or 100), 500))
    query = "SELECT * FROM erp_orders"
    params: List[Any] = []
    filter_type = str(order_type or "").strip().lower()
    if filter_type in {"puja", "ecommerce"}:
        query += " WHERE order_type = ?"
        params.append(filter_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(safe_limit)

    with get_erp_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [serialize_order_row(row) for row in rows]


def get_order_by_uid(order_uid: str) -> Dict:
    with get_erp_conn() as conn:
        row = conn.execute("SELECT * FROM erp_orders WHERE order_uid = ? LIMIT 1", (order_uid,)).fetchone()
    if not row:
        return {}
    return serialize_order_row(row)


def parse_json_text(raw_text: str):
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def get_backend_overview() -> Dict:
    with get_erp_conn() as conn:
        counts = conn.execute(
            """
            SELECT
                COUNT(*) AS total_orders,
                SUM(CASE WHEN payment_status = 'paid' THEN 1 ELSE 0 END) AS paid_orders,
                SUM(CASE WHEN payment_status = 'unpaid' THEN 1 ELSE 0 END) AS unpaid_orders,
                SUM(CASE WHEN payment_status = 'pending' THEN 1 ELSE 0 END) AS pending_orders
            FROM erp_orders
            """
        ).fetchone()
        latest = conn.execute(
            "SELECT order_uid, updated_at FROM erp_orders ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "db_path": str(ERP_DB_PATH),
        "db_exists": ERP_DB_PATH.exists(),
        "total_orders": int((counts["total_orders"] if counts else 0) or 0),
        "paid_orders": int((counts["paid_orders"] if counts else 0) or 0),
        "unpaid_orders": int((counts["unpaid_orders"] if counts else 0) or 0),
        "pending_orders": int((counts["pending_orders"] if counts else 0) or 0),
        "latest_order_uid": str(latest["order_uid"]) if latest else "",
        "latest_order_updated_at": str(latest["updated_at"]) if latest else "",
        "payment_provider": get_active_payment_provider(),
        "payment_provider_label": format_payment_provider_label(get_active_payment_provider()),
        "webhook_url_path": get_payment_webhook_path(),
        "razorpay_api_configured": bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET),
        "razorpay_webhook_secret_configured": bool(RAZORPAY_WEBHOOK_SECRET),
        "xpay_direct_api_configured": bool(XPAY_PUBLIC_KEY and XPAY_PRIVATE_KEY),
        "xpay_link_api_configured": bool(XPAY_LINK_API_URL),
        "xpay_sync_api_configured": bool(XPAY_SYNC_API_URL),
    }


def get_order_backend_payload(order_uid: str) -> Dict:
    with get_erp_conn() as conn:
        row = conn.execute(
            """
            SELECT
                order_uid, payment_provider, raw_payload, payment_payload, xpay_reference,
                payment_txn_id, payment_status, status, created_at, updated_at
            FROM erp_orders
            WHERE order_uid = ?
            LIMIT 1
            """,
            (order_uid,),
        ).fetchone()

    if not row:
        return {}

    return {
        "order_uid": row["order_uid"],
        "payment_provider": row["payment_provider"],
        "payment_status": row["payment_status"],
        "status": row["status"],
        "gateway_reference": row["xpay_reference"],
        "xpay_reference": row["xpay_reference"],
        "payment_txn_id": row["payment_txn_id"],
        "raw_payload": parse_json_text(row["raw_payload"]),
        "payment_payload": parse_json_text(row["payment_payload"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def update_order_payment_link(order_uid: str, amount: str = "", currency: str = "") -> Dict:
    existing = get_order_by_uid(order_uid)
    if not existing:
        raise ValueError(f"Order not found: {order_uid}")

    final_amount = parse_amount(amount or existing.get("amount"))
    final_currency = parse_currency(currency or existing.get("currency"), fallback=DEFAULT_CURRENCY)
    _otype = existing.get("order_type") or "ecommerce"
    if _otype == "puja":
        _desc = f"Puja – {existing.get('puja_name') or ''} at {existing.get('temple_name') or ''}"
    else:
        _desc = existing.get("item_name") or "E-commerce Order"
    link_data = create_payment_link_details(
        amount=final_amount,
        order_type=_otype,
        metadata={
            "customer_name": existing.get("customer_name") or "",
            "phone": existing.get("phone") or "",
            "email": existing.get("email") or "",
            "description": _desc,
        },
        order_uid=order_uid,
        currency=final_currency,
    )

    now = utc_now_iso()
    with get_erp_conn() as conn:
        conn.execute(
            """
            UPDATE erp_orders
            SET amount = ?, currency = ?, payment_link = ?, payment_status = ?,
                payment_provider = ?, xpay_reference = COALESCE(?, xpay_reference), updated_at = ?
            WHERE order_uid = ?
            """,
            (
                final_amount,
                final_currency,
                link_data["payment_link"],
                "unpaid",
                str(link_data.get("payment_provider") or existing.get("payment_provider") or "manual"),
                str(link_data.get("gateway_reference") or "").strip() or None,
                now,
                order_uid,
            ),
        )
        row = conn.execute("SELECT * FROM erp_orders WHERE order_uid = ? LIMIT 1", (order_uid,)).fetchone()
    return serialize_order_row(row)


def resolve_order_uid_from_payment(payload: Dict) -> str:
    order_uid = pick_value(payload, "order_uid", "merchant_order_id", "merchantOrderId")
    if order_uid:
        return order_uid

    reference_id = pick_value(payload, "reference_id", "razorpay_payment_link_reference_id")
    if reference_id:
        return reference_id

    maybe_order_id = pick_value(payload, "order_id")
    if maybe_order_id.startswith("ASB-"):
        return maybe_order_id

    for nested_key in ("metadata", "notes", "data", "payload", "payment_link", "payment", "order", "entity"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            order_uid = resolve_order_uid_from_payment(nested)
            if order_uid:
                return order_uid

    for value in payload.values():
        if isinstance(value, dict):
            order_uid = resolve_order_uid_from_payment(value)
            if order_uid:
                return order_uid
    return ""


def record_order_payment(
    *,
    order_uid: str = "",
    gateway_reference: str = "",
    payment_provider: str = "",
    payment_status: str = "",
    payment_txn_id: str = "",
    amount: str = "",
    currency: str = "",
    paid_at: str = "",
    raw_payload: Any = None,
) -> Dict:
    normalized_status = str(payment_status or "").strip().lower()
    if not normalized_status:
        normalized_status = "paid"

    status_map = {
        "paid": "paid",
        "success": "paid",
        "captured": "paid",
        "completed": "paid",
        "payment_link.paid": "paid",
        "failed": "failed",
        "failure": "failed",
        "cancelled": "unpaid",
        "expired": "unpaid",
        "created": "unpaid",
        "issued": "unpaid",
        "pending": "pending",
        "processing": "pending",
        "partially_paid": "pending",
        "payment_link.partially_paid": "pending",
    }
    payment_state = status_map.get(normalized_status, "pending")
    order_state = "paid" if payment_state == "paid" else "pending"

    if not order_uid and gateway_reference:
        with get_erp_conn() as conn:
            row = conn.execute(
                "SELECT order_uid FROM erp_orders WHERE xpay_reference = ? LIMIT 1",
                (gateway_reference,),
            ).fetchone()
        if row:
            order_uid = str(row["order_uid"])

    if not order_uid:
        raise ValueError("Unable to map payment to order: missing order_uid.")

    existing = get_order_by_uid(order_uid)
    if not existing:
        raise ValueError(f"Order not found for payment update: {order_uid}")

    final_amount = parse_amount(amount or existing.get("amount"))
    final_currency = parse_currency(currency or existing.get("currency"), fallback=DEFAULT_CURRENCY)
    final_paid_at = parse_date_input(paid_at, fallback=today_iso()) if paid_at else today_iso()
    now = utc_now_iso()
    payload_text = json.dumps(raw_payload or {}, ensure_ascii=True)

    with get_erp_conn() as conn:
        conn.execute(
            """
            UPDATE erp_orders
            SET payment_status = ?, status = ?, payment_txn_id = ?, payment_amount = ?,
                currency = ?, payment_provider = COALESCE(?, payment_provider),
                paid_at = ?, xpay_reference = COALESCE(?, xpay_reference), payment_payload = ?,
                updated_at = ?
            WHERE order_uid = ?
            """,
            (
                payment_state,
                order_state,
                payment_txn_id or existing.get("payment_txn_id"),
                final_amount,
                final_currency,
                str(payment_provider or existing.get("payment_provider") or "").strip() or None,
                final_paid_at,
                gateway_reference or None,
                payload_text,
                now,
                order_uid,
            ),
        )
        row = conn.execute("SELECT * FROM erp_orders WHERE order_uid = ? LIMIT 1", (order_uid,)).fetchone()
    return serialize_order_row(row)


def order_exists_by_xpay_reference(xpay_reference: str) -> bool:
    if not xpay_reference:
        return False
    with get_erp_conn() as conn:
        row = conn.execute("SELECT id FROM erp_orders WHERE xpay_reference = ? LIMIT 1", (xpay_reference,)).fetchone()
    return row is not None


def pick_value(item: Dict, *keys, default: str = "") -> str:
    for key in keys:
        if key in item and item.get(key) is not None:
            text = str(item.get(key)).strip()
            if text:
                return text
    return default


def extract_orders_from_sync_payload(payload: Any) -> List[Dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("orders", "manual_orders", "results", "data"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [x for x in candidate if isinstance(x, dict)]
        if isinstance(candidate, dict):
            nested = extract_orders_from_sync_payload(candidate)
            if nested:
                return nested
    return []


def normalize_xpay_order(item: Dict) -> Dict:
    order_type_raw = pick_value(item, "order_type", "type", "category", default="ecommerce").lower()
    order_type = "puja" if "puja" in order_type_raw else "ecommerce"

    payment_date = parse_date_input(
        pick_value(item, "payment_date", "paid_on", "paid_at", "payment_timestamp", "created_at"),
        fallback=today_iso(),
    )
    amount = parse_amount(pick_value(item, "amount", "amount_paid", "payment_amount", default="0"))
    currency = parse_currency(pick_value(item, "currency", "currency_code", default=DEFAULT_CURRENCY))
    xpay_reference = pick_value(item, "xpay_reference", "payment_id", "order_id", "id", "reference")

    payload = {
        "order_type": order_type,
        "payment_provider": "xpay",
        "customer_name": pick_value(item, "customer_name", "name", "user_name", default="Unknown Customer"),
        "phone": pick_value(item, "phone", "phone_number", "mobile", default="NA"),
        "email": pick_value(item, "email", "email_id", default="unknown@example.com"),
        "payment_date": payment_date,
        "amount": amount,
        "currency": currency,
        "payment_link": pick_value(item, "payment_link", "payment_url", "link"),
        "notes": pick_value(item, "notes", "remark", "description"),
        "status": pick_value(item, "status", default="pending"),
        "payment_status": pick_value(item, "payment_status", "status", default="unpaid"),
        "xpay_reference": xpay_reference,
        "source": "xpay_sync",
        "raw_payload": json.dumps(item, ensure_ascii=True),
    }

    if order_type == "puja":
        payload["puja_name"] = pick_value(item, "puja_name", "service_name", "item_name", default="Puja")
        payload["temple_name"] = pick_value(item, "temple_name", "location_name", default="Temple")
        payload["puja_schedule_date"] = parse_date_input(
            pick_value(item, "puja_schedule_date", "schedule_date", "event_date"),
            fallback=payment_date,
        )
    else:
        payload["address_line1"] = pick_value(item, "address_line1", "address", "shipping_address", default="NA")
        payload["address_line2"] = pick_value(item, "address_line2")
        payload["city"] = pick_value(item, "city", default="NA")
        payload["state"] = pick_value(item, "state", default="NA")
        payload["postal_code"] = pick_value(item, "postal_code", "pincode", "zip", default="NA")
        payload["item_name"] = pick_value(item, "item_name", "product_name", "sku_name", default="Item")
        payload["quantity"] = parse_positive_int(pick_value(item, "quantity", "qty", default="1"), fallback=1)
    return payload


def normalize_account_id(account_id: str) -> str:
    account_id = (account_id or "").strip()
    if not account_id:
        return account_id
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def derive_title_from_filename(file_name: str) -> str:
    stem = Path(file_name or "").stem.strip()
    if not stem:
        return "Uploaded Asset"
    title = re.sub(r"[_\-]+", " ", stem)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:120] if title else "Uploaded Asset"


def format_graph_error(status_code: int, body):
    if not isinstance(body, dict):
        return f"HTTP {status_code}: {body}"

    err = body.get("error") if isinstance(body.get("error"), dict) else None
    if not err:
        return f"HTTP {status_code}: {body}"

    message = str(err.get("message") or "Unknown Facebook API error.").strip()
    err_type = str(err.get("type") or "UnknownError").strip()
    code = err.get("code")
    subcode = err.get("error_subcode")

    # Common OAuth expiry/invalid-token cases.
    if str(code) == "190" or err_type == "OAuthException":
        expired_on = None
        current_time = None
        m_exp = re.search(r"expired on\s+(.+?)\.\s+The current time", message, flags=re.IGNORECASE)
        m_now = re.search(r"The current time\s+is\s+(.+?)\.", message, flags=re.IGNORECASE)
        if m_exp:
            expired_on = m_exp.group(1).strip()
        if m_now:
            current_time = m_now.group(1).strip()

        parts = ["Facebook access token expired or invalid."]
        if expired_on:
            parts.append(f"Expired on {expired_on}.")
        if current_time:
            parts.append(f"Facebook server time was {current_time}.")
        parts.append("Paste a fresh token with ads_management permission and retry.")
        return " ".join(parts)

    extra = []
    if code is not None:
        extra.append(f"code {code}")
    if subcode is not None:
        extra.append(f"subcode {subcode}")
    extra_label = f" ({', '.join(extra)})" if extra else ""
    return f"Facebook API error{extra_label}: {message}"


def fb_post(account_id: str, token: str, data: Dict, files=None, timeout=300):
    url = f"https://graph.facebook.com/{API_VERSION}/{account_id}/advideos"
    payload = dict(data)
    payload["access_token"] = token
    resp = requests.post(url, data=payload, files=files, timeout=timeout)
    try:
        body = resp.json() if resp.text else {}
    except Exception:
        body = {"raw": resp.text}

    if resp.status_code >= 400 or "error" in body:
        raise RuntimeError(format_graph_error(resp.status_code, body))
    return body


def graph_get(path: str, token: str, params: Dict = None, timeout=120):
    url = f"https://graph.facebook.com/{API_VERSION}/{path.lstrip('/')}"
    query = dict(params or {})
    query["access_token"] = token
    resp = requests.get(url, params=query, timeout=timeout)
    try:
        body = resp.json() if resp.text else {}
    except Exception:
        body = {"raw": resp.text}
    if resp.status_code >= 400 or "error" in body:
        raise RuntimeError(format_graph_error(resp.status_code, body))
    return body


def graph_post(path: str, token: str, data: Dict = None, files=None, timeout=300):
    url = f"https://graph.facebook.com/{API_VERSION}/{path.lstrip('/')}"
    payload = dict(data or {})
    payload["access_token"] = token
    resp = requests.post(url, data=payload, files=files, timeout=timeout)
    try:
        body = resp.json() if resp.text else {}
    except Exception:
        body = {"raw": resp.text}
    if resp.status_code >= 400 or "error" in body:
        raise RuntimeError(format_graph_error(resp.status_code, body))
    return body


def graph_list_all(path: str, token: str, params: Dict = None, max_pages: int = 10):
    data = []
    query = dict(params or {})
    query["access_token"] = token
    url = f"https://graph.facebook.com/{API_VERSION}/{path.lstrip('/')}"
    pages = 0

    while url and pages < max_pages:
        pages += 1
        resp = requests.get(url, params=query if pages == 1 else None, timeout=120)
        try:
            body = resp.json() if resp.text else {}
        except Exception:
            body = {"raw": resp.text}
        if resp.status_code >= 400 or "error" in body:
            raise RuntimeError(format_graph_error(resp.status_code, body))
        data.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
    return data


def validate_token_and_account_access(account_id: str, token: str):
    account = graph_get(account_id, token, params={"fields": "id,name,account_status"})
    return {
        "id": account.get("id"),
        "name": account.get("name", ""),
        "account_status": account.get("account_status"),
    }


def _find_by_name_or_id(items: List[Dict], ref: str):
    if not ref:
        return None
    ref_clean = ref.strip()
    if not ref_clean:
        return None

    if ref_clean.isdigit():
        for x in items:
            if str(x.get("id")) == ref_clean:
                return x

    exact = [x for x in items if str(x.get("name", "")).strip().lower() == ref_clean.lower()]
    if exact:
        return exact[0]
    contains = [x for x in items if ref_clean.lower() in str(x.get("name", "")).lower()]
    if contains:
        return contains[0]
    return None


def resolve_destination(account_id: str, token: str, campaign_ref: str, adset_ref: str):
    resolved = {"campaign": None, "adset": None}

    if campaign_ref:
        campaigns = graph_list_all(f"{account_id}/campaigns", token, params={"fields": "id,name", "limit": 200})
        campaign = _find_by_name_or_id(campaigns, campaign_ref)
        if not campaign:
            raise RuntimeError(f"Campaign not found: {campaign_ref}")
        resolved["campaign"] = {"id": str(campaign["id"]), "name": campaign.get("name", "")}

    if adset_ref:
        adsets = graph_list_all(
            f"{account_id}/adsets",
            token,
            params={"fields": "id,name,campaign_id", "limit": 200},
        )
        adset = _find_by_name_or_id(adsets, adset_ref)
        if not adset:
            raise RuntimeError(f"Ad set not found: {adset_ref}")
        resolved["adset"] = {
            "id": str(adset["id"]),
            "name": adset.get("name", ""),
            "campaign_id": str(adset.get("campaign_id", "")),
        }

    campaign = resolved.get("campaign")
    adset = resolved.get("adset")
    if campaign and adset and adset.get("campaign_id") and adset["campaign_id"] != campaign["id"]:
        raise RuntimeError(
            f"Ad set {adset['name']} ({adset['id']}) does not belong to campaign {campaign['name']} ({campaign['id']})."
        )
    return resolved


def build_destination_config(values: Dict):
    attach = values.get("attach_to_adset", False)
    if not attach:
        return {"enabled": False}

    if not values.get("adset_ref"):
        raise RuntimeError("Ad set is required when 'Attach directly to ad set' is enabled.")
    if not values.get("page_id"):
        raise RuntimeError("Page ID is required when attaching directly to an ad set.")
    if not values.get("destination_url"):
        raise RuntimeError("Destination URL is required when attaching directly to an ad set.")

    return {
        "enabled": True,
        "campaign_ref": values.get("campaign_ref", ""),
        "adset_ref": values.get("adset_ref", ""),
        "page_id": values.get("page_id", ""),
        "destination_url": values.get("destination_url", ""),
        "primary_text": values.get("primary_text", ""),
        "headline": values.get("headline", ""),
        "cta_type": values.get("cta_type", DEFAULT_CTA_TYPE),
        "resolved": None,
    }


def maybe_attach_asset_to_adset(
    account_id: str,
    token: str,
    destination: Dict,
    asset_type: str,
    asset_ref: str,
    file_name: str,
):
    if not destination or not destination.get("enabled"):
        return None

    resolved = destination.get("resolved") or {}
    adset = resolved.get("adset")
    if not adset:
        raise RuntimeError("Destination ad set is not resolved.")

    page_id = destination.get("page_id", "")
    destination_url = destination.get("destination_url", "")
    primary_text = destination.get("primary_text", "") or ""
    headline = destination.get("headline", "") or ""
    cta_type = destination.get("cta_type", "LEARN_MORE")
    fallback_title = derive_title_from_filename(file_name)
    effective_title = headline.strip() or fallback_title

    creative_name = f"Auto {asset_type} | {fallback_title} | {int(time.time())}"
    if asset_type == "image":
        creative = graph_post(
            f"{account_id}/adcreatives",
            token,
            data={
                "name": creative_name,
                "object_story_spec": json.dumps(
                    {
                        "page_id": page_id,
                        "link_data": {
                            "image_hash": asset_ref,
                            "link": destination_url,
                            "message": primary_text,
                            "name": effective_title,
                        },
                    }
                ),
            },
        )
    else:
        creative = graph_post(
            f"{account_id}/adcreatives",
            token,
            data={
                "name": creative_name,
                "object_story_spec": json.dumps(
                    {
                        "page_id": page_id,
                        "video_data": {
                            "video_id": asset_ref,
                            "message": primary_text,
                            "title": effective_title,
                            "call_to_action": {
                                "type": cta_type,
                                "value": {"link": destination_url},
                            },
                        },
                    }
                ),
            },
        )

    ad_name = f"Auto Ad | {fallback_title} | {int(time.time())}"
    ad = graph_post(
        f"{account_id}/ads",
        token,
        data={
            "name": ad_name,
            "adset_id": adset["id"],
            "creative": json.dumps({"creative_id": creative["id"]}),
            "status": "PAUSED",
        },
    )

    return {
        "creative_id": creative.get("id"),
        "ad_id": ad.get("id"),
        "adset_id": adset.get("id"),
    }


def upload_video_resumable(account_id: str, token: str, file_path: Path, progress_cb=None, checkpoint_cb=None):
    file_size = file_path.stat().st_size
    file_name = file_path.name

    start = fb_post(
        account_id,
        token,
        {"upload_phase": "start", "file_size": str(file_size)},
    )

    upload_session_id = start["upload_session_id"]
    video_id = start.get("video_id")
    start_offset = int(start["start_offset"])
    end_offset = int(start["end_offset"])

    with file_path.open("rb") as f:
        while start_offset < end_offset:
            if checkpoint_cb:
                checkpoint_cb()

            chunk_len = end_offset - start_offset
            f.seek(start_offset)
            chunk = f.read(chunk_len)
            if not chunk:
                raise RuntimeError(f"Failed reading chunk at offset {start_offset}")

            transfer = fb_post(
                account_id,
                token,
                {
                    "upload_phase": "transfer",
                    "upload_session_id": upload_session_id,
                    "start_offset": str(start_offset),
                },
                files={"video_file_chunk": ("chunk.bin", chunk, "application/octet-stream")},
            )
            start_offset = int(transfer["start_offset"])
            end_offset = int(transfer["end_offset"])

            if progress_cb:
                progress_cb(start_offset, file_size)

    finish = fb_post(
        account_id,
        token,
        {
            "upload_phase": "finish",
            "upload_session_id": upload_session_id,
            "name": file_name,
            "title": derive_title_from_filename(file_name),
        },
    )

    return {
        "file": file_name,
        "video_id": finish.get("video_id") or video_id,
        "response": finish,
    }


def upload_image(account_id: str, token: str, file_path: Path):
    url = f"https://graph.facebook.com/{API_VERSION}/{account_id}/adimages"
    with file_path.open("rb") as f:
        resp = requests.post(
            url,
            data={"access_token": token},
            files={"filename": (file_path.name, f)},
            timeout=300,
        )

    try:
        body = resp.json() if resp.text else {}
    except Exception:
        body = {"raw": resp.text}

    if resp.status_code >= 400 or "error" in body:
        raise RuntimeError(format_graph_error(resp.status_code, body))

    image_hash = None
    images = body.get("images")
    if isinstance(images, dict) and images:
        image_hash = next(iter(images.keys()))

    return {
        "file": file_path.name,
        "image_hash": image_hash,
        "response": body,
    }


def compute_eta_seconds(started_at: int, overall_percent: float):
    if not started_at or overall_percent <= 0:
        return None
    elapsed = max(time.time() - started_at, 1.0)
    ratio = min(max(overall_percent / 100.0, 0.001), 0.999)
    total_est = elapsed / ratio
    return int(max(0, total_est - elapsed))


def _extract_drive_folder_id(drive_link: str) -> str:
    raw = (drive_link or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", raw):
        return raw

    parsed = urlparse(raw)
    path = parsed.path or ""
    m = re.search(r"/folders/([A-Za-z0-9_-]{10,})", path)
    if m:
        return m.group(1)
    q = parse_qs(parsed.query or "")
    folder_id = (q.get("id") or [""])[0].strip()
    if folder_id:
        return folder_id
    return ""


def _extract_drive_file_id(drive_link: str) -> str:
    raw = (drive_link or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    path = parsed.path or ""
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", path)
    if m:
        return m.group(1)
    q = parse_qs(parsed.query or "")
    file_id = (q.get("id") or [""])[0].strip()
    if file_id:
        return file_id
    return ""


def _parse_drive_link_kind_and_id(href: str):
    url = urljoin("https://drive.google.com", href or "")
    parsed = urlparse(url)
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    for pattern in (
        r"/file/d/([A-Za-z0-9_-]{10,})",
        r"/folders/([A-Za-z0-9_-]{10,})",
    ):
        m = re.search(pattern, path)
        if m:
            item_id = m.group(1)
            return ("folder", item_id) if "/folders/" in pattern else ("file", item_id)

    qid = (query.get("id") or [""])[0].strip()
    if qid:
        # `open?id=` and `uc?id=` links point to files.
        return "file", qid
    return None, ""


def _list_drive_items_via_embedded(folder_id: str, visited=None):
    if not folder_id:
        return []

    if visited is None:
        visited = set()
    if folder_id in visited:
        return []
    visited.add(folder_id)

    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    res = requests.get(
        url,
        timeout=60,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        },
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Embedded folder view request failed with HTTP {res.status_code}.")

    soup = BeautifulSoup(res.text, "html.parser")
    anchors = soup.select("a[href]")
    files = []
    seen_file_ids = set()

    for a in anchors:
        href = a.get("href", "")
        kind, item_id = _parse_drive_link_kind_and_id(href)
        if not kind or not item_id:
            continue

        label = " ".join(a.get_text(" ", strip=True).split()).replace("\xa0", " ").strip()
        if not label:
            label = (a.get("title") or a.get("aria-label") or "").replace("\xa0", " ").strip()

        if kind == "file":
            if item_id in seen_file_ids:
                continue
            seen_file_ids.add(item_id)
            files.append(
                {
                    "id": item_id,
                    "name": label or f"file_{item_id}",
                }
            )
            continue

        # Nested public subfolders are also supported.
        nested = _list_drive_items_via_embedded(item_id, visited=visited)
        files.extend(nested)

    return files


def _infer_drive_file_name(file_id: str) -> str:
    if not file_id:
        return "drive_file"
    try:
        url = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
        res = requests.get(url, timeout=30)
        if res.status_code < 400:
            soup = BeautifulSoup(res.text, "html.parser")
            title = (soup.title.string or "").strip() if soup.title else ""
            if title and " - Google Drive" in title:
                title = title.replace(" - Google Drive", "").strip()
            if title:
                return title.replace("\xa0", " ").strip()
    except Exception:
        pass
    return f"file_{file_id}"


def list_drive_items(drive_link: str):
    input_link = (drive_link or "").strip()
    if not input_link:
        raise RuntimeError("Invalid Google Drive link. Please paste a valid folder or file URL.")

    link_kind, link_id = _parse_drive_link_kind_and_id(input_link)
    if link_kind == "file" and link_id:
        return [{"id": link_id, "name": _infer_drive_file_name(link_id)}]

    gdown_err = None
    try:
        out = gdown.download_folder(
            url=input_link,
            quiet=True,
            use_cookies=False,
            remaining_ok=True,
            skip_download=True,
        )
        if out:
            parsed = []
            for item in out:
                raw_name = Path(getattr(item, "path", "")).name or getattr(item, "id", "unknown")
                parsed.append(
                    {
                        "id": getattr(item, "id", ""),
                        "name": str(raw_name).replace("\xa0", " ").strip(),
                    }
                )
            if parsed:
                return parsed
    except Exception as exc:
        gdown_err = str(exc)

    folder_id = _extract_drive_folder_id(input_link)
    if not folder_id:
        file_id = _extract_drive_file_id(input_link)
        if file_id:
            return [{"id": file_id, "name": _infer_drive_file_name(file_id)}]
        raise RuntimeError("Invalid Google Drive link. Please paste a valid folder or file URL.")

    try:
        embedded_items = _list_drive_items_via_embedded(folder_id)
        if embedded_items:
            return embedded_items
    except Exception as exc:
        embedded_err = str(exc)
        if gdown_err:
            raise RuntimeError(
                "Unable to list files from this Google Drive folder. "
                f"gdown error: {gdown_err} | embedded fallback error: {embedded_err}"
            )
        # If folder parsing fails, attempt treating this as a single-file link.
        file_id = _extract_drive_file_id(input_link) or link_id
        if file_id:
            return [{"id": file_id, "name": _infer_drive_file_name(file_id)}]
        raise RuntimeError(f"Unable to list files from this Google Drive link: {embedded_err}")

    if gdown_err:
        file_id = _extract_drive_file_id(input_link) or link_id
        if file_id:
            return [{"id": file_id, "name": _infer_drive_file_name(file_id)}]
        raise RuntimeError(
            "Unable to list files from this Google Drive link. "
            f"gdown error: {gdown_err}. Please try again after a minute if Drive rate-limited the folder."
        )
    raise RuntimeError("No files found in this Google Drive link.")


def update_item(job_id: str, file_name: str, **fields):
    payload = load_job(job_id) or {}
    items = payload.get("items", [])
    for item in items:
        if item.get("file") == file_name:
            item.update(fields)
            break
    payload["items"] = items
    payload["updated_at"] = now_ts()
    save_job(job_id, payload)


def get_item_status(job_id: str, file_name: str):
    payload = load_job(job_id) or {}
    for item in payload.get("items", []):
        if item.get("file") == file_name:
            return item.get("status")
    return None


def remove_job_file(job_id: str, file_name: str):
    payload = load_job(job_id)
    if not payload:
        return False, f"Job not found: {job_id}"
    if payload.get("status") in TERMINAL_STATUSES:
        return False, f"Job already {payload.get('status')}"

    items = payload.get("items", [])
    target = None
    for item in items:
        if item.get("file") == file_name:
            target = item
            break

    if not target:
        return False, f"File not found in job: {file_name}"

    status = target.get("status")
    if status in {"uploaded", "failed", "removed"}:
        return False, f"Cannot remove file in state: {status}"

    current_file = payload.get("current_file")
    if current_file == file_name and status in {"downloading", "uploading"}:
        return False, "Cannot remove currently active file. Pause and wait for next file."

    target["status"] = "removed"
    target["percent"] = 100
    payload["items"] = items
    payload["updated_at"] = now_ts()
    save_job(job_id, payload)
    return True, "Removed"


def set_step(job_id: str, step: str):
    payload = load_job(job_id) or {}
    payload["step"] = step
    payload["last_step"] = step
    payload["updated_at"] = now_ts()
    save_job(job_id, payload)


def init_job(mode: str, form_values: Dict, items: List[Dict] = None):
    job_id = uuid.uuid4().hex[:12]
    payload = {
        "job_id": job_id,
        "mode": mode,
        "ok": False,
        "status": "queued",
        "control": "run",
        "step": "Queued",
        "last_step": "Queued",
        "overall_percent": 0,
        "current_file": None,
        "current_file_percent": 0,
        "eta_seconds": None,
        "items": items or [],
        "error": None,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "form_values": form_values,
        "total_files": len(items or []),
    }
    save_job(job_id, payload)
    return job_id


def has_failed_items(job_id: str) -> bool:
    payload = load_job(job_id) or {}
    return any(item.get("status") == "failed" for item in payload.get("items", []))


def finalize_job(job_id: str, status: str, ok: bool, step: str, error: str = None):
    payload = load_job(job_id) or {}
    payload["status"] = status
    payload["ok"] = ok
    payload["step"] = step
    payload["last_step"] = step
    payload["eta_seconds"] = 0
    if status == "completed":
        payload["overall_percent"] = 100
        payload["current_file_percent"] = 100
    if error:
        payload["error"] = error
    payload["updated_at"] = now_ts()

    workspace_dir = payload.get("workspace_dir")
    if workspace_dir:
        try:
            shutil.rmtree(workspace_dir, ignore_errors=True)
        except Exception:
            pass

    save_job(job_id, payload)


def process_drive_upload_job(job_id: str, account_id: str, token: str, drive_link: str, destination: Dict):
    try:
        control_checkpoint(job_id)
        update_job(job_id, status="running", overall_percent=1)
        set_step(job_id, "Scanning Google Drive link")

        drive_items = list_drive_items(drive_link)
        if not drive_items:
            raise RuntimeError("No files found in Google Drive link.")

        files_meta = drive_items

        items = [{"file": f["name"], "status": "queued", "percent": 0} for f in files_meta]
        update_job(job_id, items=items, total_files=len(items), overall_percent=2)

        started_at = now_ts()
        update_job(job_id, started_at=started_at)

        with tempfile.TemporaryDirectory(prefix="fb_drive_") as tmp:
            tmp_dir = Path(tmp)
            total_files = len(files_meta)

            for index, meta in enumerate(files_meta, start=1):
                control_checkpoint(job_id)
                file_name = meta["name"]
                file_id = meta["id"]
                if get_item_status(job_id, file_name) == "removed":
                    total_files = len(files_meta)
                    overall = int((index / max(total_files, 1)) * 100)
                    update_job(
                        job_id,
                        overall_percent=overall,
                        current_file=file_name,
                        current_file_percent=100,
                        eta_seconds=compute_eta_seconds(started_at, overall),
                    )
                    set_step(job_id, f"Skipped removed file: {file_name}")
                    continue

                try:
                    update_job(job_id, current_file=file_name, current_index=index)
                    set_step(job_id, f"Downloading {file_name} ({index}/{total_files})")
                    update_item(job_id, file_name, status="downloading", percent=5)

                    local_out = tmp_dir / secure_filename(file_name or f"file_{index}")
                    downloaded_path = gdown.download(
                        id=file_id,
                        output=str(local_out),
                        quiet=True,
                        use_cookies=False,
                        resume=True,
                    )
                    if not downloaded_path:
                        raise RuntimeError(f"Download failed for {file_name}")
                    file_path = Path(downloaded_path)

                    control_checkpoint(job_id)
                    set_step(job_id, f"Uploading {file_name} ({index}/{total_files})")
                    update_item(job_id, file_name, status="uploading", percent=20)

                    last_emit = {"ts": 0.0}

                    def on_progress(sent_bytes: int, total_bytes: int):
                        control_checkpoint(job_id)
                        now = time.time()
                        if now - last_emit["ts"] < 0.6 and sent_bytes < total_bytes:
                            return
                        last_emit["ts"] = now

                        file_pct = 20 + int((sent_bytes / max(total_bytes, 1)) * 80)
                        file_pct = min(99, max(20, file_pct))
                        overall = int((((index - 1) + (file_pct / 100.0)) / max(total_files, 1)) * 100)
                        overall = min(99, max(1, overall))
                        eta = compute_eta_seconds(started_at, overall)

                        update_item(job_id, file_name, status="uploading", percent=file_pct)
                        update_job(
                            job_id,
                            overall_percent=overall,
                            current_file=file_name,
                            current_file_percent=file_pct,
                            eta_seconds=eta,
                        )

                    uploaded = upload_video_resumable(
                        account_id,
                        token,
                        file_path,
                        progress_cb=on_progress,
                        checkpoint_cb=lambda: control_checkpoint(job_id),
                    )
                    if destination.get("enabled") and uploaded.get("video_id"):
                        attach = maybe_attach_asset_to_adset(
                            account_id=account_id,
                            token=token,
                            destination=destination,
                            asset_type="video",
                            asset_ref=uploaded["video_id"],
                            file_name=file_name,
                        )
                        if attach:
                            uploaded["attached"] = attach
                    update_item(job_id, file_name, status="uploaded", percent=100, details=uploaded)

                    overall = int((index / max(total_files, 1)) * 100)
                    update_job(
                        job_id,
                        overall_percent=overall,
                        current_file_percent=100,
                        eta_seconds=compute_eta_seconds(started_at, overall),
                    )
                except StopRequested:
                    raise
                except Exception as exc:
                    update_item(job_id, file_name, status="failed", percent=100, error=str(exc))
                    overall = int((index / max(total_files, 1)) * 100)
                    update_job(
                        job_id,
                        overall_percent=overall,
                        current_file_percent=100,
                        eta_seconds=compute_eta_seconds(started_at, overall),
                    )
                    set_step(job_id, f"Failed file: {file_name}")
                    continue

        if has_failed_items(job_id):
            finalize_job(
                job_id,
                status="completed_with_errors",
                ok=False,
                step="Completed with errors",
                error="One or more files failed. Check row-level errors.",
            )
        else:
            finalize_job(job_id, status="completed", ok=True, step="Completed")
    except StopRequested:
        # status already set by control checkpoint
        pass
    except Exception as exc:
        finalize_job(job_id, status="failed", ok=False, step="Failed", error=str(exc))


def process_images_upload_job(job_id: str, account_id: str, token: str, destination: Dict):
    try:
        control_checkpoint(job_id)
        payload = load_job(job_id) or {}
        workspace_dir = Path(payload.get("workspace_dir", ""))
        files = sorted([p for p in workspace_dir.iterdir() if p.is_file()]) if workspace_dir.exists() else []
        if not files:
            raise RuntimeError("No images found for upload.")

        update_job(job_id, status="running", total_files=len(files), started_at=now_ts())
        set_step(job_id, "Uploading images")

        started_at = (load_job(job_id) or {}).get("started_at") or now_ts()
        total = len(files)

        for index, path in enumerate(files, start=1):
            control_checkpoint(job_id)
            name = path.name
            if get_item_status(job_id, name) == "removed":
                overall = int((index / total) * 100)
                update_job(
                    job_id,
                    overall_percent=overall,
                    current_file=name,
                    current_file_percent=100,
                    eta_seconds=compute_eta_seconds(started_at, overall),
                )
                set_step(job_id, f"Skipped removed file: {name}")
                continue

            try:
                update_job(job_id, current_file=name, current_file_percent=10)
                set_step(job_id, f"Uploading {name} ({index}/{total})")
                update_item(job_id, name, status="uploading", percent=10)

                uploaded = upload_image(account_id, token, path)
                if destination.get("enabled") and uploaded.get("image_hash"):
                    attach = maybe_attach_asset_to_adset(
                        account_id=account_id,
                        token=token,
                        destination=destination,
                        asset_type="image",
                        asset_ref=uploaded["image_hash"],
                        file_name=name,
                    )
                    if attach:
                        uploaded["attached"] = attach
                update_item(job_id, name, status="uploaded", percent=100, details=uploaded)

                overall = int((index / total) * 100)
                update_job(
                    job_id,
                    overall_percent=overall,
                    current_file_percent=100,
                    eta_seconds=compute_eta_seconds(started_at, overall),
                )
            except StopRequested:
                raise
            except Exception as exc:
                update_item(job_id, name, status="failed", percent=100, error=str(exc))
                overall = int((index / total) * 100)
                update_job(
                    job_id,
                    overall_percent=overall,
                    current_file_percent=100,
                    eta_seconds=compute_eta_seconds(started_at, overall),
                )
                set_step(job_id, f"Failed file: {name}")
                continue

        if has_failed_items(job_id):
            finalize_job(
                job_id,
                status="completed_with_errors",
                ok=False,
                step="Completed with errors",
                error="One or more files failed. Check row-level errors.",
            )
        else:
            finalize_job(job_id, status="completed", ok=True, step="Completed")
    except StopRequested:
        pass
    except Exception as exc:
        finalize_job(job_id, status="failed", ok=False, step="Failed", error=str(exc))


def process_videos_upload_job(job_id: str, account_id: str, token: str, destination: Dict):
    try:
        control_checkpoint(job_id)
        payload = load_job(job_id) or {}
        workspace_dir = Path(payload.get("workspace_dir", ""))
        files = sorted([p for p in workspace_dir.iterdir() if p.is_file()]) if workspace_dir.exists() else []
        if not files:
            raise RuntimeError("No videos found for upload.")

        update_job(job_id, status="running", total_files=len(files), started_at=now_ts())
        set_step(job_id, "Uploading videos")

        started_at = (load_job(job_id) or {}).get("started_at") or now_ts()
        total = len(files)

        for index, path in enumerate(files, start=1):
            control_checkpoint(job_id)
            name = path.name
            if get_item_status(job_id, name) == "removed":
                overall = int((index / total) * 100)
                update_job(
                    job_id,
                    overall_percent=overall,
                    current_file=name,
                    current_file_percent=100,
                    eta_seconds=compute_eta_seconds(started_at, overall),
                )
                set_step(job_id, f"Skipped removed file: {name}")
                continue

            try:
                update_job(job_id, current_file=name)
                set_step(job_id, f"Uploading {name} ({index}/{total})")
                update_item(job_id, name, status="uploading", percent=1)

                last_emit = {"ts": 0.0}

                def on_progress(sent_bytes: int, total_bytes: int):
                    control_checkpoint(job_id)
                    now = time.time()
                    if now - last_emit["ts"] < 0.6 and sent_bytes < total_bytes:
                        return
                    last_emit["ts"] = now

                    file_pct = int((sent_bytes / max(total_bytes, 1)) * 100)
                    file_pct = min(99, max(1, file_pct))
                    overall = int((((index - 1) + (file_pct / 100.0)) / max(total, 1)) * 100)
                    overall = min(99, max(1, overall))
                    eta = compute_eta_seconds(started_at, overall)

                    update_item(job_id, name, status="uploading", percent=file_pct)
                    update_job(
                        job_id,
                        overall_percent=overall,
                        current_file=name,
                        current_file_percent=file_pct,
                        eta_seconds=eta,
                    )

                uploaded = upload_video_resumable(
                    account_id,
                    token,
                    path,
                    progress_cb=on_progress,
                    checkpoint_cb=lambda: control_checkpoint(job_id),
                )
                if destination.get("enabled") and uploaded.get("video_id"):
                    attach = maybe_attach_asset_to_adset(
                        account_id=account_id,
                        token=token,
                        destination=destination,
                        asset_type="video",
                        asset_ref=uploaded["video_id"],
                        file_name=name,
                    )
                    if attach:
                        uploaded["attached"] = attach

                update_item(job_id, name, status="uploaded", percent=100, details=uploaded)
                overall = int((index / total) * 100)
                update_job(
                    job_id,
                    overall_percent=overall,
                    current_file_percent=100,
                    eta_seconds=compute_eta_seconds(started_at, overall),
                )
            except StopRequested:
                raise
            except Exception as exc:
                update_item(job_id, name, status="failed", percent=100, error=str(exc))
                overall = int((index / total) * 100)
                update_job(
                    job_id,
                    overall_percent=overall,
                    current_file_percent=100,
                    eta_seconds=compute_eta_seconds(started_at, overall),
                )
                set_step(job_id, f"Failed file: {name}")
                continue

        if has_failed_items(job_id):
            finalize_job(
                job_id,
                status="completed_with_errors",
                ok=False,
                step="Completed with errors",
                error="One or more files failed. Check row-level errors.",
            )
        else:
            finalize_job(job_id, status="completed", ok=True, step="Completed")
    except StopRequested:
        pass
    except Exception as exc:
        finalize_job(job_id, status="failed", ok=False, step="Failed", error=str(exc))


def parse_common_form_values(req):
    ad_account_input = req.form.get("ad_account_id", "").strip() or DEFAULT_AD_ACCOUNT_ID
    token = req.form.get("access_token", "").strip() or DEFAULT_ACCESS_TOKEN
    drive_link = req.form.get("drive_link", "").strip() or DEFAULT_DRIVE_LINK
    campaign_ref = req.form.get("campaign_ref", "").strip() or DEFAULT_CAMPAIGN_REF
    adset_ref = req.form.get("adset_ref", "").strip() or DEFAULT_ADSET_REF
    page_id = req.form.get("page_id", "").strip() or DEFAULT_PAGE_ID
    destination_url = req.form.get("destination_url", "").strip() or DEFAULT_DESTINATION_URL
    primary_text = req.form.get("primary_text", "").strip() or DEFAULT_PRIMARY_TEXT
    headline = req.form.get("headline", "").strip() or DEFAULT_HEADLINE
    cta_type = req.form.get("cta_type", "").strip() or DEFAULT_CTA_TYPE
    attach_to_adset = str(req.form.get("attach_to_adset", "")).lower() in {"on", "true", "1", "yes"}
    return {
        "ad_account_input": ad_account_input,
        "account_id": normalize_account_id(ad_account_input),
        "token": token,
        "drive_link": drive_link,
        "campaign_ref": campaign_ref,
        "adset_ref": adset_ref,
        "page_id": page_id,
        "destination_url": destination_url,
        "primary_text": primary_text,
        "headline": headline,
        "cta_type": cta_type,
        "attach_to_adset": attach_to_adset,
        "form_values": {
            "ad_account_id": ad_account_input,
            "access_token": token,
            "drive_link": drive_link,
            "campaign_ref": campaign_ref,
            "adset_ref": adset_ref,
            "page_id": page_id,
            "destination_url": destination_url,
            "primary_text": primary_text,
            "headline": headline,
            "cta_type": cta_type,
            "attach_to_adset": attach_to_adset,
        },
    }


def start_drive_job(values):
    if not (values["account_id"] and values["token"] and values["drive_link"]):
        raise ValueError("Please provide Google Drive link, ad account ID, and access token.")

    validate_token_and_account_access(values["account_id"], values["token"])

    destination = build_destination_config(values)
    if destination.get("enabled"):
        destination["resolved"] = resolve_destination(
            values["account_id"],
            values["token"],
            destination.get("campaign_ref"),
            destination.get("adset_ref"),
        )

    job_id = init_job("drive", values["form_values"], items=[])
    update_job(job_id, destination=destination)
    worker = threading.Thread(
        target=process_drive_upload_job,
        args=(job_id, values["account_id"], values["token"], values["drive_link"], destination),
        daemon=True,
    )
    worker.start()
    return job_id


def save_uploaded_files(req_files, field_name: str, workspace: Path):
    files = req_files.getlist(field_name)
    saved = []
    for f in files:
        if not f.filename:
            continue
        name = secure_filename(f.filename)
        path = workspace / name
        f.save(path)
        saved.append(path)
    return saved


def start_images_job(values, req_files):
    if not (values["account_id"] and values["token"]):
        raise ValueError("Please provide ad account ID and access token.")

    validate_token_and_account_access(values["account_id"], values["token"])

    destination = build_destination_config(values)
    if destination.get("enabled"):
        destination["resolved"] = resolve_destination(
            values["account_id"],
            values["token"],
            destination.get("campaign_ref"),
            destination.get("adset_ref"),
        )

    workspace = Path(tempfile.mkdtemp(prefix="fb_img_job_"))
    files = save_uploaded_files(req_files, "images", workspace)
    if not files:
        shutil.rmtree(workspace, ignore_errors=True)
        raise ValueError("Please select one or more image files.")

    items = [{"file": p.name, "status": "queued", "percent": 0} for p in files]
    job_id = init_job("images", values["form_values"], items=items)
    update_job(job_id, workspace_dir=str(workspace), destination=destination)

    worker = threading.Thread(
        target=process_images_upload_job,
        args=(job_id, values["account_id"], values["token"], destination),
        daemon=True,
    )
    worker.start()
    return job_id


def start_videos_job(values, req_files):
    if not (values["account_id"] and values["token"]):
        raise ValueError("Please provide ad account ID and access token.")

    validate_token_and_account_access(values["account_id"], values["token"])

    destination = build_destination_config(values)
    if destination.get("enabled"):
        destination["resolved"] = resolve_destination(
            values["account_id"],
            values["token"],
            destination.get("campaign_ref"),
            destination.get("adset_ref"),
        )

    workspace = Path(tempfile.mkdtemp(prefix="fb_vid_job_"))
    files = save_uploaded_files(req_files, "videos", workspace)
    if not files:
        shutil.rmtree(workspace, ignore_errors=True)
        raise ValueError("Please select one or more video files.")

    items = [{"file": p.name, "status": "queued", "percent": 0} for p in files]
    job_id = init_job("videos", values["form_values"], items=items)
    update_job(job_id, workspace_dir=str(workspace), destination=destination)

    worker = threading.Thread(
        target=process_videos_upload_job,
        args=(job_id, values["account_id"], values["token"], destination),
        daemon=True,
    )
    worker.start()
    return job_id


init_erp_db()


@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("erp_dashboard"))


@app.route("/erp", methods=["GET"])
def erp_dashboard():
    app_meta = {
        "version": APP_VERSION,
        "boot_utc": APP_BOOT_UTC,
    }
    return render_template(
        "erp.html",
        app_meta=app_meta,
        today=today_iso(),
        orders=list_orders(limit=150),
        backend_boot=get_backend_overview(),
        supported_currencies=SUPPORTED_CURRENCIES,
        default_currency=DEFAULT_CURRENCY,
    )


def read_request_payload() -> Dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict(flat=True)


@app.route("/api/erp/payment-link", methods=["POST"])
def api_erp_payment_link():
    payload = read_request_payload()
    try:
        amount = parse_amount(payload.get("amount"))
        currency = parse_currency(payload.get("currency"), fallback=DEFAULT_CURRENCY)
        order_type = str(payload.get("order_type") or "ecommerce").strip().lower()
        if order_type not in {"puja", "ecommerce"}:
            order_type = "ecommerce"
        order_uid = str(payload.get("order_uid") or "").strip()
        link_data = create_payment_link_details(
            amount=amount,
            order_type=order_type,
            metadata={
                "customer_name": str(payload.get("customer_name") or "").strip(),
                "phone": str(payload.get("phone") or "").strip(),
                "email": str(payload.get("email") or "").strip(),
            },
            order_uid=order_uid,
            currency=currency,
        )
        return jsonify(
            {
                "ok": True,
                "payment_link": link_data["payment_link"],
                "payment_provider": link_data.get("payment_provider"),
                "gateway_reference": link_data.get("gateway_reference"),
                "amount": amount,
                "currency": currency,
                "order_type": order_type,
                "order_uid": order_uid,
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/erp/orders", methods=["GET"])
def api_erp_list_orders():
    try:
        limit = int(request.args.get("limit", "100"))
    except Exception:
        limit = 100
    order_type = request.args.get("order_type", "")
    return jsonify({"ok": True, "orders": list_orders(limit=limit, order_type=order_type)})


@app.route("/api/erp/backend/overview", methods=["GET"])
def api_erp_backend_overview():
    return jsonify({"ok": True, "backend": get_backend_overview()})


@app.route("/api/erp/backend/orders/<order_uid>", methods=["GET"])
def api_erp_backend_order(order_uid: str):
    order = get_order_by_uid(order_uid)
    if not order:
        return jsonify({"ok": False, "error": f"Order not found: {order_uid}"}), 404
    payloads = get_order_backend_payload(order_uid)
    return jsonify({"ok": True, "order": order, "payloads": payloads})


@app.route("/api/erp/orders", methods=["POST"])
def api_erp_create_order():
    payload = read_request_payload()
    try:
        order = create_order(payload)
    except sqlite3.IntegrityError as exc:
        return jsonify({"ok": False, "error": f"Duplicate order reference: {exc}"}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "order": order})


@app.route("/api/erp/orders/<order_uid>/payment-link", methods=["POST"])
def api_erp_update_payment_link(order_uid: str):
    payload = read_request_payload()
    amount = str(payload.get("amount") or "").strip()
    currency = str(payload.get("currency") or "").strip()
    try:
        order = update_order_payment_link(order_uid=order_uid, amount=amount, currency=currency)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "order": order, "payment_link": order.get("payment_link")})


@app.route("/api/erp/orders/<order_uid>/payment", methods=["POST"])
def api_erp_record_order_payment(order_uid: str):
    payload = read_request_payload()
    status = pick_value(payload, "payment_status", "status", default="paid")
    txn_id = pick_value(payload, "payment_txn_id", "payment_id", "transaction_id", "txn_id")
    gateway_ref = pick_value(
        payload,
        "gateway_reference",
        "xpay_reference",
        "reference",
        "payment_link_id",
        "razorpay_payment_link_id",
        "order_ref",
    )
    amount = pick_value(payload, "amount", "payment_amount")
    currency = pick_value(payload, "currency", "currency_code")
    paid_at = pick_value(payload, "paid_at", "payment_date", "payment_time")
    payment_provider = pick_value(payload, "payment_provider", default=get_active_payment_provider())
    try:
        order = record_order_payment(
            order_uid=order_uid,
            gateway_reference=gateway_ref,
            payment_provider=payment_provider,
            payment_status=status,
            payment_txn_id=txn_id,
            amount=amount,
            currency=currency,
            paid_at=paid_at,
            raw_payload=payload,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "order": order})


@app.route("/api/erp/xpay/webhook", methods=["POST"])
@app.route("/api/xpay/webhook", methods=["POST"])
def api_erp_xpay_webhook():
    payload = read_request_payload()
    order_uid = resolve_order_uid_from_payment(payload)
    status = pick_value(payload, "payment_status", "status", "event", default="paid")
    txn_id = pick_value(payload, "payment_txn_id", "payment_id", "transaction_id", "txn_id", "id")
    gateway_ref = pick_value(payload, "xpay_reference", "reference", "payment_reference", "order_ref")
    amount = pick_value(payload, "amount", "payment_amount", "paid_amount")
    currency = pick_value(payload, "currency", "currency_code")
    paid_at = pick_value(payload, "paid_at", "payment_date", "payment_time", "captured_at")

    try:
        order = record_order_payment(
            order_uid=order_uid,
            gateway_reference=gateway_ref,
            payment_provider="xpay",
            payment_status=status,
            payment_txn_id=txn_id,
            amount=amount,
            currency=currency,
            paid_at=paid_at,
            raw_payload=payload,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "message": "Payment recorded.", "order_uid": order.get("order_uid")})


@app.route("/api/erp/razorpay/webhook", methods=["POST"])
def api_erp_razorpay_webhook():
    raw_body = request.get_data(cache=True) or b""
    signature = request.headers.get("X-Razorpay-Signature", "")
    try:
        verify_razorpay_webhook_signature(raw_body, signature)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    payload = request.get_json(silent=True) or {}
    event = str(payload.get("event") or "").strip()
    payload_root = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    payment_link_entity = (
        ((payload_root.get("payment_link") or {}).get("entity"))
        if isinstance(payload_root, dict)
        else {}
    )
    payment_entity = (
        ((payload_root.get("payment") or {}).get("entity"))
        if isinstance(payload_root, dict)
        else {}
    )

    order_uid = resolve_order_uid_from_payment(payload)
    gateway_ref = pick_value(
        payment_link_entity if isinstance(payment_link_entity, dict) else {},
        "id",
        default=pick_value(payload, "razorpay_payment_link_id", "payment_link_id"),
    )
    txn_id = pick_value(
        payment_entity if isinstance(payment_entity, dict) else {},
        "id",
        default=pick_value(payload, "razorpay_payment_id", "payment_id"),
    )
    currency = pick_value(
        payment_entity if isinstance(payment_entity, dict) else {},
        "currency",
        default=pick_value(payment_link_entity if isinstance(payment_link_entity, dict) else {}, "currency"),
    )
    amount_minor_units = pick_value(
        payment_entity if isinstance(payment_entity, dict) else {},
        "amount",
        "amount_captured",
        default=pick_value(payment_link_entity if isinstance(payment_link_entity, dict) else {}, "amount_paid", "amount"),
    )
    amount = minor_units_to_amount(amount_minor_units, parse_currency(currency or DEFAULT_CURRENCY))
    paid_at = parse_unix_date(
        pick_value(payment_entity if isinstance(payment_entity, dict) else {}, "captured_at", "created_at")
        or pick_value(payload, "created_at")
    )
    status = pick_value(
        payment_entity if isinstance(payment_entity, dict) else {},
        "status",
        default=event or pick_value(payment_link_entity if isinstance(payment_link_entity, dict) else {}, "status", default="paid"),
    )

    try:
        order = record_order_payment(
            order_uid=order_uid,
            gateway_reference=gateway_ref,
            payment_provider="razorpay",
            payment_status=status or event or "paid",
            payment_txn_id=txn_id,
            amount=amount,
            currency=currency,
            paid_at=paid_at,
            raw_payload=payload,
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "message": "Razorpay payment recorded.", "order_uid": order.get("order_uid")})


@app.route("/api/erp/xpay/sync", methods=["POST"])
def api_erp_xpay_sync():
    payload = read_request_payload()
    api_url = str(payload.get("api_url") or XPAY_SYNC_API_URL or "").strip()
    if not api_url:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "XPay API URL is not configured yet. Share the endpoint and key, then this sync can run.",
                }
            ),
            400,
        )

    api_key = str(payload.get("api_key") or XPAY_API_KEY or "").strip()
    method = str(payload.get("method") or "GET").strip().upper()
    body = payload.get("body")

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        if method == "POST":
            outbound = body if isinstance(body, dict) else {}
            resp = requests.post(api_url, json=outbound, headers=headers, timeout=90)
        else:
            resp = requests.get(api_url, headers=headers, timeout=90)
        resp_body = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": f"XPay sync call failed with HTTP {resp.status_code}.",
                        "response": resp_body,
                    }
                ),
                400,
            )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"XPay sync request failed: {exc}"}), 400

    items = extract_orders_from_sync_payload(resp_body)
    created = 0
    skipped = 0
    errors: List[str] = []

    for item in items:
        try:
            normalized = normalize_xpay_order(item)
            xpay_reference = str(normalized.get("xpay_reference") or "").strip()
            if xpay_reference and order_exists_by_xpay_reference(xpay_reference):
                skipped += 1
                continue
            create_order(normalized)
            created += 1
        except Exception as exc:
            skipped += 1
            if len(errors) < 5:
                errors.append(str(exc))

    return jsonify(
        {
            "ok": True,
            "fetched": len(items),
            "created": created,
            "skipped": skipped,
            "errors": errors,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
