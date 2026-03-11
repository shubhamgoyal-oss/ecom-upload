#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

API_VERSION = "v25.0"


def load_state(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_state(path: Path, state: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(path)


def graph_post(account_id: str, token: str, data: dict, files=None, timeout=300):
    url = f"https://graph.facebook.com/{API_VERSION}/{account_id}/advideos"
    payload = dict(data)
    payload["access_token"] = token
    resp = requests.post(url, data=payload, files=files, timeout=timeout)

    body = {}
    if resp.text:
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}

    if resp.status_code >= 400 or "error" in body:
        raise RuntimeError(f"HTTP {resp.status_code}: {json.dumps(body)}")

    return body


def upload_file(account_id: str, token: str, file_path: Path, max_retries: int = 3):
    file_size = file_path.stat().st_size
    name = file_path.name

    start_resp = graph_post(
        account_id,
        token,
        {
            "upload_phase": "start",
            "file_size": str(file_size),
        },
    )

    upload_session_id = start_resp["upload_session_id"]
    video_id = start_resp.get("video_id")
    start_offset = int(start_resp["start_offset"])
    end_offset = int(start_resp["end_offset"])

    print(f"[START] {name} size={file_size} session={upload_session_id}", flush=True)

    with file_path.open("rb") as f:
        while start_offset < end_offset:
            chunk_len = end_offset - start_offset
            f.seek(start_offset)
            chunk = f.read(chunk_len)
            if not chunk:
                raise RuntimeError(f"Failed reading chunk at offset {start_offset}")

            retries = 0
            while True:
                try:
                    transfer_resp = graph_post(
                        account_id,
                        token,
                        {
                            "upload_phase": "transfer",
                            "upload_session_id": upload_session_id,
                            "start_offset": str(start_offset),
                        },
                        files={
                            "video_file_chunk": ("chunk.bin", chunk, "application/octet-stream"),
                        },
                    )
                    break
                except Exception as exc:
                    retries += 1
                    if retries > max_retries:
                        raise
                    sleep_s = min(2 ** retries, 10)
                    print(f"[RETRY] {name} transfer offset={start_offset} err={exc} sleep={sleep_s}s", flush=True)
                    time.sleep(sleep_s)

            start_offset = int(transfer_resp["start_offset"])
            end_offset = int(transfer_resp["end_offset"])
            pct = (start_offset / file_size) * 100 if file_size else 100
            print(f"[TRANSFER] {name} {pct:.2f}% ({start_offset}/{file_size})", flush=True)

    finish_resp = graph_post(
        account_id,
        token,
        {
            "upload_phase": "finish",
            "upload_session_id": upload_session_id,
            "name": name,
        },
    )

    result_video_id = finish_resp.get("video_id") or video_id
    print(f"[FINISH] {name} video_id={result_video_id} response={finish_resp}", flush=True)
    return {
        "file": name,
        "video_id": result_video_id,
        "finish_response": finish_resp,
    }


def main():
    parser = argparse.ArgumentParser(description="Upload local videos to Facebook ad account media library via resumable upload.")
    parser.add_argument("--account-id", required=True, help="Ad account ID with act_ prefix")
    parser.add_argument("--token", default=os.environ.get("FB_ACCESS_TOKEN"), help="Facebook access token")
    parser.add_argument("--folder", default="drive_videos", help="Folder containing videos")
    parser.add_argument("--state", default="fb_upload_state.json", help="State file path")
    parser.add_argument("--max-files", type=int, default=0, help="Optional max files to upload in this run")
    args = parser.parse_args()

    if not args.token:
        print("Missing token. Use --token or FB_ACCESS_TOKEN env var.", file=sys.stderr)
        sys.exit(2)

    folder = Path(args.folder)
    if not folder.exists():
        print(f"Folder not found: {folder}", file=sys.stderr)
        sys.exit(2)

    state_path = Path(args.state)
    state = load_state(state_path)

    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".part"))

    done = 0
    for p in files:
        entry = state.get(p.name, {})
        if entry.get("status") == "uploaded" and entry.get("video_id"):
            print(f"[SKIP] {p.name} already uploaded as {entry['video_id']}", flush=True)
            continue

        try:
            result = upload_file(args.account_id, args.token, p)
            state[p.name] = {
                "status": "uploaded",
                "video_id": result.get("video_id"),
                "updated_at": int(time.time()),
            }
            save_state(state_path, state)
            done += 1
            if args.max_files and done >= args.max_files:
                break
        except Exception as exc:
            state[p.name] = {
                "status": "failed",
                "error": str(exc),
                "updated_at": int(time.time()),
            }
            save_state(state_path, state)
            print(f"[ERROR] {p.name} failed: {exc}", file=sys.stderr, flush=True)

    print("[DONE] run complete", flush=True)


if __name__ == "__main__":
    main()
