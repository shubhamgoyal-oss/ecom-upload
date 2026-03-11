#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List

import gdown
import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 * 1024

API_VERSION = "v25.0"
DEFAULT_DRIVE_LINK = os.environ.get(
    "DEFAULT_DRIVE_LINK",
    "https://drive.google.com/drive/folders/1ALzsYnTy9v2i7VG-99xpgZ27bO26U-1b",
)
DEFAULT_AD_ACCOUNT_ID = os.environ.get("DEFAULT_AD_ACCOUNT_ID", "508817521835118")
DEFAULT_ACCESS_TOKEN = os.environ.get(
    "DEFAULT_ACCESS_TOKEN",
    "***REMOVED***",
)
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
TERMINAL_STATUSES = {"completed", "failed", "stopped"}


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


def render_page(result=None, form_values=None):
    defaults = {
        "drive_link": DEFAULT_DRIVE_LINK,
        "ad_account_id": DEFAULT_AD_ACCOUNT_ID,
        "access_token": DEFAULT_ACCESS_TOKEN,
        "campaign_ref": DEFAULT_CAMPAIGN_REF,
        "adset_ref": DEFAULT_ADSET_REF,
        "page_id": DEFAULT_PAGE_ID,
        "destination_url": DEFAULT_DESTINATION_URL,
        "primary_text": DEFAULT_PRIMARY_TEXT,
        "headline": DEFAULT_HEADLINE,
        "cta_type": DEFAULT_CTA_TYPE,
        "attach_to_adset": False,
    }
    if form_values:
        for key, value in form_values.items():
            if value:
                defaults[key] = value
    app_meta = {
        "version": APP_VERSION,
        "boot_utc": APP_BOOT_UTC,
    }
    return render_template("index.html", result=result, defaults=defaults, app_meta=app_meta)


def normalize_account_id(account_id: str) -> str:
    account_id = (account_id or "").strip()
    if not account_id:
        return account_id
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


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
        raise RuntimeError(f"HTTP {resp.status_code}: {body}")
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
        raise RuntimeError(f"HTTP {resp.status_code}: {body}")
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
        raise RuntimeError(f"HTTP {resp.status_code}: {body}")
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
            raise RuntimeError(f"HTTP {resp.status_code}: {body}")
        data.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
    return data


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

    creative_name = f"Auto {asset_type} | {file_name} | {int(time.time())}"
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
                            "name": headline,
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
                            "title": headline,
                            "call_to_action": {
                                "type": cta_type,
                                "value": {"link": destination_url},
                            },
                        },
                    }
                ),
            },
        )

    ad_name = f"Auto Ad | {file_name} | {int(time.time())}"
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
        raise RuntimeError(f"HTTP {resp.status_code}: {body}")

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


def list_drive_folder_items(drive_link: str):
    out = gdown.download_folder(
        url=drive_link,
        quiet=True,
        use_cookies=False,
        remaining_ok=True,
        skip_download=True,
    )
    return out or []


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
        set_step(job_id, "Scanning Google Drive folder")

        drive_items = list_drive_folder_items(drive_link)
        if not drive_items:
            raise RuntimeError("No files found in Google Drive folder.")

        files_meta = []
        for item in drive_items:
            name = Path(getattr(item, "path", "")).name or getattr(item, "id", "unknown")
            files_meta.append({"id": getattr(item, "id", ""), "name": name})

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


@app.route("/", methods=["GET"])
def index():
    return render_page(result=None)


@app.route("/upload/drive", methods=["POST"])
def upload_from_drive():
    values = parse_common_form_values(request)
    try:
        job_id = start_drive_job(values)
        return redirect(url_for("job_status_page", job_id=job_id))
    except Exception as exc:
        result = {
            "mode": "drive",
            "ok": False,
            "status": "failed",
            "items": [],
            "error": str(exc),
        }
        return render_page(result=result, form_values=values["form_values"])


@app.route("/upload/images", methods=["POST"])
def upload_manual_images():
    values = parse_common_form_values(request)
    try:
        job_id = start_images_job(values, request.files)
        return redirect(url_for("job_status_page", job_id=job_id))
    except Exception as exc:
        result = {
            "mode": "images",
            "ok": False,
            "status": "failed",
            "items": [],
            "error": str(exc),
        }
        return render_page(result=result, form_values=values["form_values"])


@app.route("/upload/videos", methods=["POST"])
def upload_manual_videos():
    values = parse_common_form_values(request)
    try:
        job_id = start_videos_job(values, request.files)
        return redirect(url_for("job_status_page", job_id=job_id))
    except Exception as exc:
        result = {
            "mode": "videos",
            "ok": False,
            "status": "failed",
            "items": [],
            "error": str(exc),
        }
        return render_page(result=result, form_values=values["form_values"])


@app.route("/jobs/<job_id>", methods=["GET"])
def job_status_page(job_id: str):
    payload = load_job(job_id)
    if not payload:
        result = {
            "mode": "unknown",
            "ok": False,
            "status": "failed",
            "items": [],
            "error": f"Job not found: {job_id}",
        }
        return render_page(result=result)
    return render_page(result=format_job_state_for_api(payload), form_values=payload.get("form_values"))


# Backward-compatible route aliases for previously shared URLs.
@app.route("/upload/drive/status/<job_id>", methods=["GET"])
def legacy_drive_status_page(job_id: str):
    return redirect(url_for("job_status_page", job_id=job_id))


@app.route("/api/upload/drive/start", methods=["POST"])
def api_start_drive():
    values = parse_common_form_values(request)
    try:
        job_id = start_drive_job(values)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "mode": "drive",
            "status_url": url_for("job_status_page", job_id=job_id),
            "poll_url": url_for("api_job_status", job_id=job_id),
        }
    )


@app.route("/api/upload/images/start", methods=["POST"])
def api_start_images():
    values = parse_common_form_values(request)
    try:
        job_id = start_images_job(values, request.files)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "mode": "images",
            "status_url": url_for("job_status_page", job_id=job_id),
            "poll_url": url_for("api_job_status", job_id=job_id),
        }
    )


@app.route("/api/upload/videos/start", methods=["POST"])
def api_start_videos():
    values = parse_common_form_values(request)
    try:
        job_id = start_videos_job(values, request.files)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "mode": "videos",
            "status_url": url_for("job_status_page", job_id=job_id),
            "poll_url": url_for("api_job_status", job_id=job_id),
        }
    )


@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_job_status(job_id: str):
    payload = load_job(job_id)
    if not payload:
        return jsonify({"ok": False, "error": f"Job not found: {job_id}"}), 404
    return jsonify({"ok": True, "job": format_job_state_for_api(payload)})


@app.route("/api/upload/drive/status/<job_id>", methods=["GET"])
def legacy_api_drive_status(job_id: str):
    return api_job_status(job_id)


@app.route("/api/jobs/<job_id>/control", methods=["POST"])
def api_job_control(job_id: str):
    action = request.form.get("action")
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        action = action or payload.get("action")
    action = (action or "").strip().lower()
    if action not in {"pause", "resume", "stop"}:
        return jsonify({"ok": False, "error": "Invalid action. Use pause, resume, or stop."}), 400

    payload = set_job_control(job_id, action)
    if payload is None:
        return jsonify({"ok": False, "error": f"Job not found: {job_id}"}), 404

    return jsonify({"ok": True, "job": format_job_state_for_api(payload)})


@app.route("/api/jobs/<job_id>/remove-file", methods=["POST"])
def api_job_remove_file(job_id: str):
    file_name = request.form.get("file")
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        file_name = file_name or payload.get("file")
    file_name = (file_name or "").strip()
    if not file_name:
        return jsonify({"ok": False, "error": "Missing file name."}), 400

    ok, message = remove_job_file(job_id, file_name)
    if not ok:
        return jsonify({"ok": False, "error": message}), 400

    payload = load_job(job_id)
    return jsonify({"ok": True, "message": message, "job": format_job_state_for_api(payload)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
