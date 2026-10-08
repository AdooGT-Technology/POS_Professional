from __future__ import annotations

import logging
import os
import base64
import hashlib
import json
import threading
import webbrowser
import secrets
from decimal import Decimal
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server_config import SERVER_CONFIG, save_server_config
from security import verify_password
import db as dbmod
from db import Base
from usb_billing import bill_bytes, get_active_profile
from models import Device, User, OutboxEvent, USBPolicy, USBBillingProfile, USBPriceTier, USBSession, USBTransferEvent, USBInvoice, ClientControlProfile, ClientControlTelemetry, ClientControlToken, ClientControlCommand, ClientScreenSnapshot, ClientUIProfile
from client_ui_v18 import get_profile, save_profile, list_items, list_all_items, upsert_item, delete_item, list_banners, list_all_banners, upsert_banner, delete_banner, ASSET_DIR
from esports_service import snapshot as esports_snapshot, save_provider as esports_save_provider, save_game as esports_save_game, toggle_game as esports_toggle_game, sync_game as esports_sync_game, client_catalog as esports_client_catalog

LOGGER = logging.getLogger("pos.v18.server")
APP_VERSION = "V27.5.7"
SERVER_BUILD = "V27.5.7-Server-Esports-USB-HA"
app = FastAPI(title="POS Professional V27 Central Server", version="V27")

CONTROL_COMMANDS = {"LOCK", "SESSION_PAUSE", "SCREENSHOT", "REFRESH_UI", "TASK_EXECUTE"}

# V27.5.7 persistent Manager libraries.
GAME_LIBRARY_FILE = ROOT / "game_library_v27.json"
CLIENT_RUNTIME_STATE_FILE = ROOT / "client_runtime_state_v27.json"
TASK_LIBRARY_FILE = ROOT / "task_library_v27.json"

def _load_library(path: Path):
    try:
        data=json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return data if isinstance(data,list) else []
    except Exception:
        return []

def _save_library(path: Path, rows):
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")




def _load_client_runtime_state():
    try:
        data=json.loads(CLIENT_RUNTIME_STATE_FILE.read_text(encoding="utf-8")) if CLIENT_RUNTIME_STATE_FILE.exists() else {}
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}

def _save_client_runtime_state(data):
    CLIENT_RUNTIME_STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _client_runtime_row(device_id: str):
    state=_load_client_runtime_state().get(device_id) or {}
    ends_at=state.get("ends_at")
    remaining=state.get("remaining_minutes")
    if ends_at:
        try: remaining=max(0, int((datetime.fromisoformat(ends_at)-datetime.now()).total_seconds()//60))
        except Exception: pass
    state["remaining_minutes"]=remaining if remaining is not None else 0
    if state.get("ends_at") and state["remaining_minutes"]<=0: state["open"]=False
    return state

def _hash_token(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()

def _control_requires_https(request: Request):
    if bool(SERVER_CONFIG.get("control_require_https", False)):
        proto = request.headers.get("X-Forwarded-Proto", request.url.scheme).lower()
        if proto != "https":
            raise HTTPException(400, "V27 control APIs require HTTPS/TLS")

def _require_manager_control(request: Request):
    _control_requires_https(request)
    manager_id = (request.headers.get("X-Manager-Id") or "").strip()
    if not manager_id:
        raise HTTPException(401, "Manager authentication required")
    return manager_id

def _token_from_request(request: Request) -> str:
    return (request.headers.get("X-Device-Token") or "").strip()

def _require_client_token(device_id: str, request: Request):
    _control_requires_https(request)
    token = _token_from_request(request)
    if not token:
        raise HTTPException(401, "Device token required")
    with dbmod.SessionLocal() as session:
        row = session.scalar(select(ClientControlToken).where(ClientControlToken.device_id == device_id, ClientControlToken.active.is_(True)))
        if not row or row.token_hash != _hash_token(token):
            raise HTTPException(401, "Invalid device token")
        return row

def _ensure_control_profile(session, device_id: str) -> ClientControlProfile:
    row = session.scalar(select(ClientControlProfile).where(ClientControlProfile.device_id == device_id))
    if row is None:
        row = ClientControlProfile(device_id=device_id, screen_monitoring_enabled=bool(SERVER_CONFIG.get("screen_monitoring_enabled", False)), retention_hours=int(SERVER_CONFIG.get("screen_snapshot_retention_hours", 24)))
        session.add(row); session.flush()
    return row

def _ensure_device_token(session, device_id: str):
    row = session.scalar(select(ClientControlToken).where(ClientControlToken.device_id == device_id))
    if row is not None:
        return row, None
    token = secrets.token_urlsafe(32)
    row = ClientControlToken(device_id=device_id, token_hash=_hash_token(token), token_hint=token[-8:])
    session.add(row); session.flush()
    return row, token

def _control_state(device_id: str):
    with dbmod.SessionLocal() as session:
        device = session.scalar(select(Device).where(Device.device_uuid == device_id))
        if device is None: raise HTTPException(404, "client not found")
        profile = _ensure_control_profile(session, device_id)
        telemetry = session.scalar(select(ClientControlTelemetry).where(ClientControlTelemetry.device_id == device_id))
        usb = session.scalar(select(USBPolicy).where(USBPolicy.client_id == device_id))
        snap = session.scalars(select(ClientScreenSnapshot).where(ClientScreenSnapshot.device_id == device_id).order_by(desc(ClientScreenSnapshot.created_at)).limit(1)).first()
        return {
            "device_id": device.device_uuid, "name": device.device_name, "ip": device.ip_address, "status": _device_status(device),
            "app_version": device.app_version, "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "branch_id": device.branch_id, "warehouse_id": device.warehouse_id,
            "room_name": profile.room_name, "console_name": profile.console_name,
            "screen_monitoring_enabled": bool(profile.screen_monitoring_enabled) and bool(SERVER_CONFIG.get("screen_monitoring_enabled", False)),
            "retention_hours": int(profile.retention_hours or 24),
            "cpu_percent": float(telemetry.cpu_percent or 0) if telemetry else 0,
            "cpu_temperature": float(telemetry.cpu_temperature or 0) if telemetry and telemetry.cpu_temperature is not None else None,
            "ram_percent": float(telemetry.ram_percent or 0) if telemetry else 0,
            "ram_used_gb": float(telemetry.ram_used_gb or 0) if telemetry else 0,
            "ram_total_gb": float(telemetry.ram_total_gb or 0) if telemetry else 0,
            "ram_speed_mhz": float(telemetry.ram_speed_mhz or 0) if telemetry and telemetry.ram_speed_mhz is not None else None,
            "gpu_name": telemetry.gpu_name if telemetry else '',
            "gpu_percent": float(telemetry.gpu_percent or 0) if telemetry else 0,
            "gpu_temperature": float(telemetry.gpu_temperature or 0) if telemetry and telemetry.gpu_temperature is not None else None,
            "gpu_memory_percent": float(telemetry.gpu_memory_percent or 0) if telemetry else 0,
            "disk_health_percent": float(telemetry.disk_health_percent or 0) if telemetry and telemetry.disk_health_percent is not None else None,
            "disk_temperature": float(telemetry.disk_temperature or 0) if telemetry and telemetry.disk_temperature is not None else None,
            "disk_usage_percent": float(telemetry.disk_usage_percent or 0) if telemetry else 0,
            "disks": json.loads(telemetry.disks_json or '[]') if telemetry else [],
            "running_apps": json.loads(telemetry.running_apps_json or "[]") if telemetry else [],
            "current_user": telemetry.current_user if telemetry else "",
            "session_paused": bool(telemetry.session_paused) if telemetry else False,
            "lan_speed_mbps": float(telemetry.lan_speed_mbps or 0) if telemetry and telemetry.lan_speed_mbps is not None else None,
            "lan_adapter": telemetry.lan_adapter if telemetry else "",
            "telemetry_updated_at": telemetry.updated_at.isoformat() if telemetry and telemetry.updated_at else None,
            "usb_policy": usb.policy if usb else "ALLOW",
            "runtime": _client_runtime_row(device_id),
            "sha256_enabled": bool(usb.sha256_enabled) if usb else False,
            "last_snapshot_at": snap.created_at.isoformat() if snap else None,
            "screen_snapshot_available": bool(snap),
            "branch_name": getattr(getattr(device, "branch", None), "name", "") or "",
            "ui": get_profile(device_id),
            "ui_items": list_all_items(device_id),
            "ui_banners": list_all_banners(device_id),
        }


def _purge_old_snapshots():
    hours = max(1, int(SERVER_CONFIG.get("screen_snapshot_retention_hours", 24)))
    cutoff = datetime.now() - __import__('datetime').timedelta(hours=hours)
    with dbmod.SessionLocal.begin() as session:
        rows = session.scalars(select(ClientScreenSnapshot).where(ClientScreenSnapshot.created_at < cutoff)).all()
        for row in rows: session.delete(row)



class Heartbeat(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    device_name: str = ""
    device_type: str = "CLIENT"
    branch_id: int | None = None
    warehouse_id: int | None = None
    app_version: str = "V27"
    status: str = "ONLINE"
    last_error: str = ""


class ClientLogin(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    pin: str = Field(default="", max_length=32)
    device_id: str = Field(min_length=1, max_length=80)


class LaunchRequest(BaseModel):
    game_id: str = Field(min_length=1, max_length=120)
    device_id: str = Field(min_length=1, max_length=80)


class USBPolicyRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    policy: str = "ALLOW"
    sha256_enabled: bool = False


class USBSessionStart(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    volume_id: str = ""
    volume_label: str = ""
    mount_path: str = ""
    customer_name: str = ""
    free_session: bool = False


class USBSessionHeartbeat(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    bytes_to_usb: int = Field(default=0, ge=0)
    bytes_from_usb: int = Field(default=0, ge=0)


class USBTransferRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=80)
    file_name: str = Field(min_length=1, max_length=500)
    file_size_bytes: int = Field(default=0, ge=0)
    direction: str = "TO_USB"
    status: str = "RECORDED"
    sha256: str = ""




class ClientUIProfilePayload(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    logo_asset: str = ""
    background_asset: str = ""
    video_asset: str = ""
    main_image_asset: str = ""
    icon_games: str = ""
    icon_apps: str = ""
    icon_shop: str = ""
    icon_events: str = ""
    icon_ads: str = ""
    icon_my_files: str = ""
    icon_profile: str = ""
    accent_color: str = "#41d9ff"
    accent_2: str = "#a46cff"
    text_color: str = "#edf4ff"
    muted_color: str = "#9fb1c8"
    layout_mode: str = "grid"
    kiosk_mode: bool = False
    show_profile: bool = True
    show_games: bool = True
    show_apps: bool = True
    show_shop: bool = True
    show_events: bool = True
    show_ads: bool = True
    show_my_files: bool = True
    welcome_text: str = "اختر ما تريد تشغيله"
    profile_badge: str = "PLAYER"


class ClientUIItemPayload(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    id: int | None = None
    item_type: str = "GAME"
    name: str = Field(min_length=1, max_length=150)
    description: str = ""
    icon_asset: str = ""
    launch_type: str = "EXE"
    target: str = ""
    args: str = ""
    working_dir: str = ""
    enabled: bool = True
    sort_order: int = 0


class ClientUIBannerPayload(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    id: int | None = None
    title: str = ""
    body: str = ""
    image_asset: str = ""
    url: str = ""
    enabled: bool = True
    sort_order: int = 0


class ClientUILaunchRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    item_id: int = Field(ge=1)


class USBPricingRequest(BaseModel):
    name: str = "Default USB"
    per_gb: Decimal = Decimal("1.0")
    tax_percent: Decimal = Decimal("0")
    minimum_charge: Decimal = Decimal("0")
    free_gb: Decimal = Decimal("0")
    free_session_default: bool = False
    enabled: bool = True
    tiers: list[dict] = []


class EsportsProviderPayload(BaseModel):
    id: int | None = None
    name: str = "Generic Esports Provider"
    provider_type: str = "GENERIC"
    base_url: str = ""
    api_key: str = ""
    leaderboard_path_template: str = "/games/{code}/leaderboard"
    tournament_path_template: str = "/games/{code}/tournaments"
    enabled: bool = True

class EsportsGamePayload(BaseModel):
    id: int | None = None
    code: str
    name: str
    provider_id: int | None = None
    tournament_enabled: bool = False
    leaderboard_visible: bool = True
    enabled: bool = True
    leaderboard_path: str = ""
    tournament_path: str = ""

class EsportsTogglePayload(BaseModel):
    tournament_enabled: bool | None = None
    leaderboard_visible: bool | None = None

def _central_url_config():
    return str(SERVER_CONFIG.get("database_url", "sqlite:///pos_v15_server.db"))


def _device_status(device: Device) -> str:
    now = datetime.now()
    age = (now - device.last_seen_at).total_seconds() if device.last_seen_at else 999999
    if age > int(SERVER_CONFIG.get("offline_after_seconds", 15)):
        return "OFFLINE"
    return device.status or "ONLINE"


def _update_device(h: Heartbeat, ip: str):
    with dbmod.SessionLocal.begin() as session:
        device = session.scalar(select(Device).where(Device.device_uuid == h.device_id))
        if not device:
            device = Device(device_uuid=h.device_id, device_name=h.device_name or h.device_id, device_type=h.device_type)
            session.add(device)
        device.device_name = h.device_name or device.device_name
        device.device_type = h.device_type or "CLIENT"
        device.branch_id = h.branch_id
        device.warehouse_id = h.warehouse_id
        device.app_version = h.app_version or APP_VERSION
        device.status = h.status if h.status in {"ONLINE", "OFFLINE", "SYNCING", "IDLE", "BUSY"} else "ONLINE"
        device.ip_address = ip
        device.last_seen_at = datetime.now()
        device.last_error = (h.last_error or "")[:4000]


def _ensure_test_game_library():
    """Seed the central library with the same test catalog exposed by Client V15."""
    rows = _load_library(GAME_LIBRARY_FILE)
    existing = {str(x.get("id")): x for x in rows}
    defaults = [
        ("legacy-game:valorant", "VALORANT", "GAME", "FPS", "VALORANT"),
        ("legacy-game:fortnite", "Fortnite", "GAME", "Battle Royale", "Fortnite"),
        ("legacy-game:pubg_mobile", "PUBG Mobile", "GAME", "Battle Royale", "PUBG Mobile"),
        ("legacy-game:cs2", "Counter-Strike 2", "GAME", "FPS", "Counter-Strike 2"),
        ("legacy-app:steam", "Steam", "APP", "Platforms", "Steam"),
        ("legacy-app:discord", "Discord", "APP", "Communication", "Discord"),
        ("legacy-app:epic", "Epic Games", "APP", "Platforms", "Epic Games"),
    ]
    changed = False
    for gid, name, kind, category, stem in defaults:
        if gid in existing:
            continue
        ext = "_180x240.jpg" if kind == "GAME" else "_180x240.jpg"
        icon = f"/client-assets/test_{stem.lower().replace(' ','_')}_64x64.png"
        poster = f"/client-assets/test_{stem.lower().replace(' ','_')}{ext}"
        existing[gid] = {"id":gid,"name":name,"item_type":kind,"category":category,"group":category,"version":"TEST","description":f"{name} — Server / Client test catalog","folder":"","executable":"","working_dir":"","arguments":"","save_path":"","shader_path":"","poster":poster,"icon":icon,"launch_type":"LEGACY_APP" if kind=="APP" else "LEGACY_GAME","target":gid.split(":",1)[1],"enabled":True,"sort_order":0}
        changed = True
    if changed:
        _save_library(GAME_LIBRARY_FILE, list(existing.values()))


@app.on_event("startup")
def startup():
    # Do not replace an engine explicitly configured by an embedding app/test.
    # The real standalone server initializes once here; callers that configure
    # a database before creating the ASGI client keep their selected engine.
    if dbmod.engine is None:
        dbmod.configure_engine(_central_url_config(), initialize=True)
    Base.metadata.create_all(dbmod.engine)
    with dbmod.SessionLocal.begin() as session:
        get_active_profile(session)
    _ensure_test_game_library()
    _purge_old_snapshots()
    LOGGER.info("V27 central server started on %s:%s", SERVER_CONFIG.get("server_host"), SERVER_CONFIG.get("server_port"))


def _game_library_client_items():
    """Expose the central Game Library to every Client without duplicating Studio items."""
    out = []
    for game in _load_library(GAME_LIBRARY_FILE):
        if game.get("enabled") is False:
            continue
        gid = str(game.get("id") or "").strip()
        if not gid:
            continue
        kind = "APP" if str(game.get("item_type") or "GAME").upper() == "APP" else "GAME"
        target = str(game.get("target") or gid)
        launch_type = str(game.get("launch_type") or ("LEGACY_APP" if kind == "APP" else "LEGACY_GAME"))
        icon = str(game.get("icon") or game.get("icon_asset") or "")
        poster = str(game.get("poster") or game.get("poster_asset") or "")
        out.append({
            "id": gid, "item_type": kind, "name": game.get("name", "Game"),
            "description": game.get("description") or game.get("category") or "",
            "category": game.get("category") or game.get("group") or "Games",
            "icon_asset": icon, "icon_url": icon, "poster": poster, "poster_url": poster,
            "launch_type": launch_type, "target": target,
            "args": game.get("arguments", ""), "working_dir": game.get("working_dir", ""),
            "enabled": True, "sort_order": int(game.get("sort_order") or 0),
            "source": "GAME_LIBRARY"
        })
    return out


@app.get("/api/v18/client/{device_id}/ui")
def client_ui_bootstrap(device_id: str):
    profile = get_profile(device_id)
    managed_items = list_items(device_id)
    banners = list_banners(device_id)
    central_items = _game_library_client_items()
    # Central Game Library is always visible to the Client; Studio items are
    # preserved and take precedence when they intentionally use the same id.
    seen = {str(x.get("id")) for x in managed_items}
    items = list(managed_items) + [x for x in central_items if str(x.get("id")) not in seen]
    # If neither V18 nor Game Library has content, preserve the legacy catalog.
    if not items:
        try:
            legacy = client_catalog()
            for item in legacy.get("games", []):
                items.append({"id": f"legacy-game:{item.get('id')}", "item_type": "GAME", "name": item.get("name", "Game"), "description": item.get("category", ""), "icon_asset": "", "icon_url": "", "poster_url": "", "launch_type": "LEGACY_GAME", "target": str(item.get("id", "")), "args": "", "working_dir": "", "enabled": True, "sort_order": 0})
            for item in legacy.get("apps", []):
                items.append({"id": f"legacy-app:{item.get('id')}", "item_type": "APP", "name": item.get("name", "App"), "description": item.get("category", ""), "icon_asset": "", "icon_url": "", "poster_url": "", "launch_type": "LEGACY_APP", "target": str(item.get("id", "")), "args": "", "working_dir": "", "enabled": True, "sort_order": 0})
        except Exception:
            items = []
    return {"version": "V27.5.7", "client_id": device_id, "store_name": SERVER_CONFIG.get("store_name", "متجري"), "store_logo": SERVER_CONFIG.get("store_logo_data", ""), "profile": profile, "items": items, "banners": banners, "esports": esports_client_catalog()}


@app.get("/api/v27/game-library")
def game_library_list():
    return {"ok": True, "games": _load_library(GAME_LIBRARY_FILE)}

@app.post("/api/v27/game-library")
async def game_library_save(request: Request):
    payload=await request.json()
    rows=_load_library(GAME_LIBRARY_FILE)
    item=dict(payload or {})
    item["id"]=str(item.get("id") or secrets.token_hex(8))
    item.setdefault("enabled", True)
    existing=next((i for i,x in enumerate(rows) if str(x.get("id"))==str(item["id"])),None)
    if existing is None:
        rows.append(item)
    else:
        # Patch semantics: omitted/blank media fields never erase an existing poster/icon.
        old=dict(rows[existing])
        for k,v in item.items():
            if k in {"poster","icon"} and (v is None or str(v).strip()==""):
                continue
            old[k]=v
        item=old
        rows[existing]=item
    _save_library(GAME_LIBRARY_FILE,rows)
    return {"ok":True,"game":item}

@app.delete("/api/v27/game-library/{item_id}")
def game_library_delete(item_id: str):
    rows=[x for x in _load_library(GAME_LIBRARY_FILE) if str(x.get("id"))!=str(item_id)]
    _save_library(GAME_LIBRARY_FILE,rows)
    return {"ok":True}

@app.get("/api/v27/task-library")
def task_library_list():
    return {"ok":True,"tasks":_load_library(TASK_LIBRARY_FILE)}

@app.post("/api/v27/task-library")
async def task_library_save(request: Request):
    payload=await request.json(); rows=_load_library(TASK_LIBRARY_FILE); item=dict(payload or {}); item["id"]=str(item.get("id") or secrets.token_hex(8)); item.setdefault("enabled",True)
    existing=next((i for i,x in enumerate(rows) if str(x.get("id"))==str(item["id"])),None)
    if existing is None: rows.append(item)
    else: rows[existing]=item
    _save_library(TASK_LIBRARY_FILE,rows)
    return {"ok":True,"task":item}

@app.delete("/api/v27/task-library/{item_id}")
def task_library_delete(item_id: str):
    rows=[x for x in _load_library(TASK_LIBRARY_FILE) if str(x.get("id"))!=str(item_id)]; _save_library(TASK_LIBRARY_FILE,rows); return {"ok":True}

@app.get("/api/v27/branding")
def branding_get():
    return {"ok":True,"store_name":SERVER_CONFIG.get("store_name","متجري"),"logo_data":SERVER_CONFIG.get("store_logo_data","")}

@app.put("/api/v27/branding")
async def branding_save(request: Request):
    data=await request.json(); name=str(data.get("store_name") or SERVER_CONFIG.get("store_name") or "متجري").strip(); logo=str(data.get("logo_data") or "")
    if logo and len(logo)>4_000_000: raise HTTPException(413,"حجم الشعار كبير جدًا")
    SERVER_CONFIG["store_name"]=name
    if logo: SERVER_CONFIG["store_logo_data"]=logo
    try:
        cfg_path=ROOT/"server_config.json"
        cfg_path.write_text(json.dumps(SERVER_CONFIG,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:
        pass
    return {"ok":True,"store_name":name,"logo_data":SERVER_CONFIG.get("store_logo_data","")}

@app.get("/api/v18/manager/clients")
def manager_clients_v18():
    with dbmod.SessionLocal() as session:
        rows = session.scalars(select(Device).where(Device.device_type == "CLIENT").order_by(Device.device_name, Device.id)).all()
        return {"clients": [{"device_id": d.device_uuid, "name": d.device_name, "status": _device_status(d), "ip": d.ip_address, "branch_id": d.branch_id, "warehouse_id": d.warehouse_id, "app_version": d.app_version, "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None} for d in rows]}


@app.get("/api/v18/manager/client-ui/{device_id}")
def manager_client_ui(device_id: str):
    return {"device_id": device_id, "profile": get_profile(device_id), "items": list_all_items(device_id), "banners": list_all_banners(device_id)}


@app.put("/api/v18/manager/client-ui/profile")
def manager_save_client_ui(payload: ClientUIProfilePayload, x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    return save_profile(payload.device_id, payload.model_dump())

@app.put("/api/v18/manager/client-ui/profile/global")
def manager_save_client_ui_global(payload: ClientUIProfilePayload, x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    incoming=payload.model_dump(); incoming["device_id"]="__DEFAULT__"
    # Pydantic supplies defaults for omitted fields; preserve existing assets/icons instead of clearing them.
    current=save_profile("__DEFAULT__", {"device_id":"__DEFAULT__"})
    data=dict(incoming)
    preserve_if_empty={"logo_asset","background_asset","video_asset","main_image_asset","icon_games","icon_apps","icon_shop","icon_events","icon_ads","icon_my_files","icon_profile","accent_color","accent_2","text_color","muted_color","layout_mode","welcome_text","profile_badge"}
    for key in preserve_if_empty:
        if key in data and str(data.get(key) or "").strip()=="":
            data[key]=current.get(key, data[key])
    saved=save_profile("__DEFAULT__", data)
    # Propagate the visual configuration to existing Client profiles. New Clients inherit __DEFAULT__ automatically.
    from client_ui_v18 import DEFAULT_PROFILE
    allowed=set(DEFAULT_PROFILE)-{"device_id"}
    with dbmod.SessionLocal.begin() as session:
        rows=session.scalars(select(ClientUIProfile)).all()
        for row in rows:
            if row.device_id=="__DEFAULT__":
                continue
            for key in allowed:
                if key in data:
                    setattr(row,key,data[key])
            row.updated_at=datetime.now()
    return {"ok":True,"profile":saved,"applied_to_existing":True}


@app.post("/api/v18/manager/client-ui/item")
def manager_save_client_item(payload: ClientUIItemPayload, x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    return upsert_item(payload.device_id, payload.model_dump())


@app.delete("/api/v18/manager/client-ui/{device_id}/item/{item_id}")
def manager_delete_client_item(device_id: str, item_id: int, x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    if not delete_item(device_id, item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}


@app.post("/api/v18/manager/client-ui/banner")
def manager_save_client_banner(payload: ClientUIBannerPayload, x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    return upsert_banner(payload.device_id, payload.model_dump())


@app.delete("/api/v18/manager/client-ui/{device_id}/banner/{banner_id}")
def manager_delete_client_banner(device_id: str, banner_id: int, x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    if not delete_banner(device_id, banner_id):
        raise HTTPException(status_code=404, detail="Banner not found")
    return {"ok": True}


@app.post("/api/v18/manager/client-ui/asset")
async def manager_upload_client_asset(asset: UploadFile = File(...), x_manager_id: str = Header(default="")):
    if not x_manager_id.strip():
        raise HTTPException(status_code=401, detail="Manager identity required")
    original = Path(asset.filename or "asset.bin").name
    suffix = Path(original).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".mp4", ".webm"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="نوع الأصل غير مسموح")
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(original).stem)[:80] or "asset"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    filename = f"{stem}_{stamp}{suffix}"
    dest = ASSET_DIR / filename
    data = await asset.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم الصورة يتجاوز 10MB")
    dest.write_bytes(data)
    return {"ok": True, "asset": filename, "url": f"/client-assets/{filename}"}


@app.get("/client-assets/{filename}", include_in_schema=False)
def client_asset(filename: str):
    safe = Path(filename).name
    file_path = ASSET_DIR / safe
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(file_path)


@app.post("/api/v18/client/launch")
def client_launch_v18(payload: ClientUILaunchRequest):
    from sqlalchemy import select
    from models import ClientUIItem
    with dbmod.SessionLocal() as session:
        item = session.scalar(select(ClientUIItem).where(ClientUIItem.id == payload.item_id, ClientUIItem.device_id == payload.device_id, ClientUIItem.enabled.is_(True)))
        if item is None:
            raise HTTPException(status_code=404, detail="Client item not found")
        if item.launch_type.upper() not in {"EXE", "URL"}:
            raise HTTPException(status_code=400, detail="Unsupported launch type")
        return {"ok": True, "item_id": item.id, "item_type": item.item_type, "launch_type": item.launch_type.upper(), "target": item.target, "args": item.args, "working_dir": item.working_dir}




class V19ClientRegister(BaseModel):
    device_name: str = ""
    device_type: str = "CLIENT"
    app_version: str = "V27"

class V19Telemetry(BaseModel):
    cpu_percent: float = Field(default=0, ge=0, le=100)
    cpu_temperature: float | None = Field(default=None, ge=-20, le=150)
    ram_percent: float = Field(default=0, ge=0, le=100)
    ram_used_gb: float = Field(default=0, ge=0)
    ram_total_gb: float = Field(default=0, ge=0)
    ram_speed_mhz: float | None = Field(default=None, ge=0)
    gpu_name: str = ''
    gpu_percent: float = Field(default=0, ge=0, le=100)
    gpu_temperature: float | None = Field(default=None, ge=-20, le=150)
    gpu_memory_percent: float = Field(default=0, ge=0, le=100)
    disk_health_percent: float | None = Field(default=None, ge=0, le=100)
    disk_temperature: float | None = Field(default=None, ge=-20, le=150)
    disk_usage_percent: float = Field(default=0, ge=0, le=100)
    disks: list[dict] = []
    running_apps: list[str] = []
    current_user: str = ""
    session_paused: bool = False
    lan_speed_mbps: float | None = Field(default=None, ge=0)
    lan_adapter: str = ""
    status: str = "ONLINE"

class V19CommandRequest(BaseModel):
    command: str
    payload: dict = {}

class V19ScreenUpload(BaseModel):
    command_id: str = ""
    image_base64: str = ""

class V19CommandAck(BaseModel):
    status: str = "SUCCESS"
    result: dict = {}

class V19ClientProfileRequest(BaseModel):
    room_name: str = ""
    console_name: str = ""
    screen_monitoring_enabled: bool = False
    retention_hours: int = 24

class V19USBPolicyRequest(BaseModel):
    policy: str = "ALLOW"
    sha256_enabled: bool = False

@app.get("/api/v19/control/clients")
def v19_control_clients(request: Request):
    _require_manager_control(request)
    with dbmod.SessionLocal() as session:
        rows = session.scalars(select(Device).where(Device.device_type == "CLIENT").order_by(Device.device_name, Device.id)).all()
        result = []
        for d in rows:
            try: result.append(_control_state(d.device_uuid))
            except Exception: pass
        return {"clients": result, "screen_monitoring_global": bool(SERVER_CONFIG.get("screen_monitoring_enabled", False)), "require_https": bool(SERVER_CONFIG.get("control_require_https", False))}


@app.get("/api/v27/manager/devices-summary")
def v27_manager_devices_summary(request: Request):
    """Lightweight Manager device feed: telemetry/session data only; no Client Studio catalog or screenshots."""
    _require_manager_control(request)
    with dbmod.SessionLocal() as session:
        devices = session.scalars(
            select(Device)
            .where(Device.device_type == "CLIENT")
            .options(selectinload(Device.branch), selectinload(Device.warehouse))
            .order_by(Device.device_name, Device.id)
        ).all()
        ids = [d.device_uuid for d in devices]
        profiles = {}
        telemetry = {}
        usb = {}
        if ids:
            for row in session.scalars(select(ClientControlProfile).where(ClientControlProfile.device_id.in_(ids))).all():
                profiles[row.device_id] = row
            for row in session.scalars(select(ClientControlTelemetry).where(ClientControlTelemetry.device_id.in_(ids))).all():
                telemetry[row.device_id] = row
            for row in session.scalars(select(USBPolicy).where(USBPolicy.client_id.in_(ids))).all():
                usb[row.client_id] = row
        runtime_all = _load_client_runtime_state()
        result = []
        for d in devices:
            tid = d.device_uuid
            tm = telemetry.get(tid)
            pr = profiles.get(tid)
            up = usb.get(tid)
            runtime = runtime_all.get(tid) or {}
            # Reuse only the small runtime fields needed by the grid; do not call _control_state().
            remaining = runtime.get("remaining_minutes") or 0
            ends_at = runtime.get("ends_at")
            if ends_at:
                try:
                    remaining = max(0, int((datetime.fromisoformat(ends_at)-datetime.now()).total_seconds()//60))
                except Exception:
                    pass
            if ends_at and remaining <= 0:
                runtime = dict(runtime)
                runtime["remaining_minutes"] = 0
                runtime["open"] = False
            disks=[]
            running_apps=[]
            if tm:
                try: disks=json.loads(tm.disks_json or '[]')
                except Exception: disks=[]
                try: running_apps=json.loads(tm.running_apps_json or '[]')
                except Exception: running_apps=[]
            result.append({
                "device_id": d.device_uuid,
                "name": d.device_name,
                "ip": d.ip_address or "",
                "status": _device_status(d),
                "app_version": d.app_version or "",
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                "last_sync_at": d.last_sync_at.isoformat() if d.last_sync_at else None,
                "last_error": d.last_error or "",
                "branch_id": d.branch_id,
                "warehouse_id": d.warehouse_id,
                "branch_name": getattr(d.branch, "name", "") or "",
                "warehouse_name": getattr(d.warehouse, "name", "") or "",
                "room_name": pr.room_name if pr else "",
                "console_name": pr.console_name if pr else "",
                "screen_monitoring_enabled": bool(pr.screen_monitoring_enabled) if pr else False,
                "cpu_percent": float(tm.cpu_percent or 0) if tm else 0,
                "cpu_temperature": float(tm.cpu_temperature or 0) if tm and tm.cpu_temperature is not None else None,
                "ram_percent": float(tm.ram_percent or 0) if tm else 0,
                "ram_used_gb": float(tm.ram_used_gb or 0) if tm else 0,
                "ram_total_gb": float(tm.ram_total_gb or 0) if tm else 0,
                "ram_speed_mhz": float(tm.ram_speed_mhz or 0) if tm and tm.ram_speed_mhz is not None else None,
                "gpu_name": tm.gpu_name if tm else "",
                "gpu_percent": float(tm.gpu_percent or 0) if tm else 0,
                "gpu_temperature": float(tm.gpu_temperature or 0) if tm and tm.gpu_temperature is not None else None,
                "gpu_memory_percent": float(tm.gpu_memory_percent or 0) if tm else 0,
                "disk_health_percent": float(tm.disk_health_percent or 0) if tm and tm.disk_health_percent is not None else None,
                "disk_temperature": float(tm.disk_temperature or 0) if tm and tm.disk_temperature is not None else None,
                "disk_usage_percent": float(tm.disk_usage_percent or 0) if tm else 0,
                "disks": disks,
                "running_apps": running_apps[:12],
                "current_user": tm.current_user if tm else "",
                "session_paused": bool(tm.session_paused) if tm else False,
                "lan_speed_mbps": float(tm.lan_speed_mbps or 0) if tm and tm.lan_speed_mbps is not None else None,
                "lan_adapter": tm.lan_adapter if tm else "",
                "telemetry_updated_at": tm.updated_at.isoformat() if tm and tm.updated_at else None,
                "usb_policy": up.policy if up else "ALLOW",
                "sha256_enabled": bool(up.sha256_enabled) if up else False,
                "runtime": {k: runtime.get(k) for k in ("open","remaining_minutes","balance","username","user_name","hourly_rate","started_at","ends_at") if k in runtime},
            })
        return {"clients": result, "count": len(result), "screen_monitoring_global": bool(SERVER_CONFIG.get("screen_monitoring_enabled", False)), "require_https": bool(SERVER_CONFIG.get("control_require_https", False))}

@app.get("/api/v19/control/clients/{device_id}")
def v19_control_client(device_id: str, request: Request):
    _require_manager_control(request)
    return _control_state(device_id)

@app.put("/api/v19/control/clients/{device_id}/profile")
def v19_control_profile(device_id: str, payload: V19ClientProfileRequest, request: Request):
    _require_manager_control(request)
    with dbmod.SessionLocal.begin() as session:
        _ensure_control_profile(session, device_id)
        row = session.scalar(select(ClientControlProfile).where(ClientControlProfile.device_id == device_id))
        row.room_name = payload.room_name[:120]
        row.console_name = payload.console_name[:120]
        row.screen_monitoring_enabled = bool(payload.screen_monitoring_enabled) and bool(SERVER_CONFIG.get("screen_monitoring_enabled", False))
        row.retention_hours = max(1, min(int(payload.retention_hours or 24), 720))
    return {"ok": True, "state": _control_state(device_id)}

@app.post("/api/v19/control/clients/{device_id}/commands")
def v19_control_command(device_id: str, payload: V19CommandRequest, request: Request):
    manager_id = _require_manager_control(request)
    command = str(payload.command or "").upper().strip()
    if command not in CONTROL_COMMANDS:
        raise HTTPException(400, "Unsupported command")
    if command == "SCREENSHOT" and not bool(SERVER_CONFIG.get("screen_monitoring_enabled", False)):
        raise HTTPException(403, "Screen Monitoring is disabled by policy")
    command_id = secrets.token_urlsafe(18)
    with dbmod.SessionLocal.begin() as session:
        if not session.scalar(select(Device).where(Device.device_uuid == device_id)):
            raise HTTPException(404, "client not found")
        session.add(ClientControlCommand(command_id=command_id, device_id=device_id, command=command, payload_json=json.dumps(payload.payload or {}, ensure_ascii=False), requested_by=manager_id))
    return {"ok": True, "command_id": command_id, "command": command, "status": "QUEUED"}

@app.post("/api/v19/manager/clients/{device_id}/rotate-token")
def v19_rotate_device_token(device_id: str, request: Request):
    _require_manager_control(request)
    token = secrets.token_urlsafe(32)
    with dbmod.SessionLocal.begin() as session:
        row = session.scalar(select(ClientControlToken).where(ClientControlToken.device_id == device_id))
        if row is None:
            row = ClientControlToken(device_id=device_id, token_hash=_hash_token(token), token_hint=token[-8:])
            session.add(row)
        else:
            row.token_hash = _hash_token(token); row.token_hint = token[-8:]; row.rotated_at = datetime.now(); row.active = True
    return {"ok": True, "device_id": device_id, "token": token, "token_hint": token[-8:]}

class V19ClientRuntimeRequest(BaseModel):
    minutes: int = Field(default=0, ge=0, le=100000)
    amount: float = Field(default=0, ge=0, le=100000000)
    mode: str = "ADD"
    hourly_rate: float = Field(default=0, ge=0, le=100000)
    open_session: bool | None = None

class V27SessionPricingRequest(BaseModel):
    enabled: bool = True
    hourly_rate: float = Field(default=0, ge=0, le=100000)
    minute_rate: float = Field(default=0, ge=0, le=100000)
    billing_mode: str = "HOURLY"
    currency: str = "جنيه"
    offer_bonus_minutes: int = Field(default=0, ge=0, le=100000)
    minimum_charge: float = Field(default=0, ge=0, le=100000)
    rounding_minutes: int = Field(default=1, ge=1, le=1440)
    grace_minutes: int = Field(default=0, ge=0, le=1440)
    tax_included: bool = False
    tax_rate: float = Field(default=0, ge=0, le=100)
    peak_enabled: bool = False
    peak_start: str = "18:00"
    peak_end: str = "23:00"
    peak_hourly_rate: float = Field(default=0, ge=0, le=100000)

@app.get("/api/v27/session-pricing")
def v27_session_pricing(request: Request):
    _require_manager_control(request)
    return {"enabled":bool(SERVER_CONFIG.get("session_pricing_enabled",True)),"hourly_rate":float(SERVER_CONFIG.get("session_hourly_rate",0) or 0),"minute_rate":float(SERVER_CONFIG.get("session_minute_rate",0) or 0),"billing_mode":str(SERVER_CONFIG.get("session_billing_mode") or "HOURLY"),"currency":str(SERVER_CONFIG.get("session_currency") or SERVER_CONFIG.get("currency") or "جنيه"),"offer_bonus_minutes":int(SERVER_CONFIG.get("session_offer_bonus_minutes",0) or 0),"minimum_charge":float(SERVER_CONFIG.get("session_minimum_charge",0) or 0),"rounding_minutes":int(SERVER_CONFIG.get("session_rounding_minutes",1) or 1),"grace_minutes":int(SERVER_CONFIG.get("session_grace_minutes",0) or 0),"tax_included":bool(SERVER_CONFIG.get("session_tax_included",False)),"tax_rate":float(SERVER_CONFIG.get("session_tax_rate",SERVER_CONFIG.get("tax_rate",0)) or 0),"peak_enabled":bool(SERVER_CONFIG.get("session_peak_enabled",False)),"peak_start":str(SERVER_CONFIG.get("session_peak_start") or "18:00"),"peak_end":str(SERVER_CONFIG.get("session_peak_end") or "23:00"),"peak_hourly_rate":float(SERVER_CONFIG.get("session_peak_hourly_rate",0) or 0)}

@app.put("/api/v27/session-pricing")
def v27_session_pricing_save(payload: V27SessionPricingRequest, request: Request):
    _require_manager_control(request)
    SERVER_CONFIG["session_pricing_enabled"]=bool(payload.enabled)
    SERVER_CONFIG["session_hourly_rate"]=float(payload.hourly_rate or 0)
    SERVER_CONFIG["session_minute_rate"]=float(payload.minute_rate or 0)
    SERVER_CONFIG["session_billing_mode"]=str(payload.billing_mode or "HOURLY").upper()[:20]
    SERVER_CONFIG["session_currency"]=str(payload.currency or "جنيه")[:20]
    SERVER_CONFIG["session_offer_bonus_minutes"]=int(payload.offer_bonus_minutes or 0)
    SERVER_CONFIG["session_minimum_charge"]=float(payload.minimum_charge or 0)
    SERVER_CONFIG["session_rounding_minutes"]=int(payload.rounding_minutes or 1)
    SERVER_CONFIG["session_grace_minutes"]=int(payload.grace_minutes or 0)
    SERVER_CONFIG["session_tax_included"]=bool(payload.tax_included)
    SERVER_CONFIG["session_tax_rate"]=float(payload.tax_rate or 0)
    SERVER_CONFIG["session_peak_enabled"]=bool(payload.peak_enabled)
    SERVER_CONFIG["session_peak_start"]=str(payload.peak_start or "18:00")[:5]
    SERVER_CONFIG["session_peak_end"]=str(payload.peak_end or "23:00")[:5]
    SERVER_CONFIG["session_peak_hourly_rate"]=float(payload.peak_hourly_rate or 0)
    save_server_config(SERVER_CONFIG)
    return v27_session_pricing(request)

@app.put("/api/v19/control/clients/{device_id}/runtime")
def v19_control_runtime(device_id: str, payload: V19ClientRuntimeRequest, request: Request):
    _require_manager_control(request)
    with dbmod.SessionLocal() as session:
        if not session.scalar(select(Device).where(Device.device_uuid == device_id, Device.device_type == "CLIENT")):
            raise HTTPException(404, "client not found")
    data=_load_client_runtime_state(); cur=_client_runtime_row(device_id)
    mode=str(payload.mode or "ADD").upper()
    configured_rate=float(SERVER_CONFIG.get("session_hourly_rate",0) or 0)
    rate=configured_rate if configured_rate>0 else float(payload.hourly_rate or cur.get("hourly_rate") or 0)
    amount=float(payload.amount or 0)
    requested_minutes=int(payload.minutes or 0)
    if mode=="ADD" and requested_minutes<=0 and amount>0 and rate>0:
        requested_minutes=max(1,int((amount/rate)*60))
    if mode=="DEBIT":
        if amount>float(cur.get("balance") or 0)+0.00001: raise HTTPException(400,"الرصيد غير كافٍ")
        remaining=int(cur.get("remaining_minutes") or 0); balance=max(0.0,float(cur.get("balance") or 0)-amount); is_open=bool(cur.get("open")) and remaining>0
    elif mode=="OFFER":
        bonus=int(payload.minutes or SERVER_CONFIG.get("session_offer_bonus_minutes",0) or 0)
        remaining=int(cur.get("remaining_minutes") or 0)+max(0,bonus); balance=float(cur.get("balance") or 0); is_open=remaining>0; requested_minutes=bonus
    elif mode=="SET":
        remaining=requested_minutes; balance=amount; is_open=bool(payload.open_session) if payload.open_session is not None else remaining>0
    else:
        remaining=int(cur.get("remaining_minutes") or 0)+requested_minutes; balance=float(cur.get("balance") or 0)+amount; is_open=bool(payload.open_session) if payload.open_session is not None else bool(cur.get("open")) or remaining>0
    started_at=cur.get("started_at") or datetime.now().isoformat(timespec="seconds")
    ends_at=(datetime.now().replace(microsecond=0)+__import__('datetime').timedelta(minutes=remaining)).isoformat(timespec="seconds") if is_open and remaining>0 else None
    row={"remaining_minutes":remaining,"balance":round(balance,2),"hourly_rate":rate,"open":is_open,"started_at":started_at if is_open else cur.get("started_at"),"ends_at":ends_at,"updated_at":datetime.now().isoformat(timespec="seconds")}
    data[device_id]=row; _save_client_runtime_state(data)
    return {"ok":True,"device_id":device_id,"runtime":_client_runtime_row(device_id)}

@app.get("/api/v19/usb/default-policy")
def v19_usb_default_policy(request: Request):
    _require_manager_control(request)
    return {"policy":str(SERVER_CONFIG.get("usb_default_policy") or "ALLOW").upper(),"sha256_enabled":bool(SERVER_CONFIG.get("usb_default_sha256", False))}

@app.put("/api/v19/usb/default-policy")
def v19_usb_default_policy_save(payload: V19USBPolicyRequest, request: Request):
    _require_manager_control(request)
    policy=str(payload.policy or "ALLOW").upper().strip()
    if policy not in {"ALLOW","READ_ONLY","BLOCK"}: raise HTTPException(400,"Invalid USB policy")
    SERVER_CONFIG["usb_default_policy"]=policy
    SERVER_CONFIG["usb_default_sha256"]=bool(payload.sha256_enabled)
    try:
        from server_config import save_server_config
        save_server_config(SERVER_CONFIG)
    except Exception:
        try:
            cfg_path=ROOT / "server_config.json"
            cfg_path.write_text(json.dumps(SERVER_CONFIG,ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception: pass
    return {"ok":True,"policy":policy,"sha256_enabled":bool(payload.sha256_enabled)}

@app.post("/api/v19/control/clients/{device_id}/usb-policy")
def v19_control_usb_policy(device_id: str, payload: V19USBPolicyRequest, request: Request):
    _require_manager_control(request)
    policy = str(payload.policy).upper().strip()
    if policy not in {"ALLOW", "READ_ONLY", "BLOCK"}: raise HTTPException(400, "Invalid USB policy")
    with dbmod.SessionLocal.begin() as session:
        row = session.scalar(select(USBPolicy).where(USBPolicy.client_id == device_id))
        if row is None:
            row = USBPolicy(client_id=device_id); session.add(row)
        row.policy = policy; row.sha256_enabled = bool(payload.sha256_enabled)
    return {"ok": True, "device_id": device_id, "policy": policy, "sha256_enabled": bool(payload.sha256_enabled)}

@app.get("/api/v19/client/{device_id}/register")
def v19_client_register_get(device_id: str):
    # Read-only registration state; token is never returned here.
    with dbmod.SessionLocal() as session:
        row = session.scalar(select(ClientControlToken).where(ClientControlToken.device_id == device_id, ClientControlToken.active.is_(True)))
        return {"device_id": device_id, "registered": bool(row), "token_hint": row.token_hint if row else ""}

@app.post("/api/v19/client/{device_id}/register")
def v19_client_register(device_id: str, payload: V19ClientRegister, request: Request):
    _control_requires_https(request)
    with dbmod.SessionLocal.begin() as session:
        device = session.scalar(select(Device).where(Device.device_uuid == device_id))
        if not device:
            device = Device(device_uuid=device_id, device_name=(payload.device_name or device_id)[:150], device_type=payload.device_type or "CLIENT", app_version=payload.app_version or "V27.5.7", ip_address=str(request.client.host if request.client else "")[:64])
            session.add(device); session.flush()
        else:
            device.device_name = (payload.device_name or device.device_name)[:150]
            device.device_type = payload.device_type or "CLIENT"
            device.app_version = payload.app_version or "V27.5.7"
            device.ip_address = str(request.client.host if request.client else "")[:64]
            device.last_seen_at = datetime.now()
        _ensure_control_profile(session, device_id)
        row, token = _ensure_device_token(session, device_id)
        return {"ok": True, "device_id": device_id, "device_token": token, "token_hint": row.token_hint, "new_token": bool(token)}

@app.get("/api/v19/client/{device_id}/commands/poll")
def v19_client_poll(device_id: str, request: Request):
    _require_client_token(device_id, request)
    with dbmod.SessionLocal.begin() as session:
        rows = session.scalars(select(ClientControlCommand).where(ClientControlCommand.device_id == device_id, ClientControlCommand.status == "QUEUED").order_by(ClientControlCommand.id).limit(10)).all()
        now = datetime.now(); out=[]
        for row in rows:
            row.status = "CLAIMED"; row.claimed_at = now
            out.append({"command_id": row.command_id, "command": row.command, "payload": json.loads(row.payload_json or "{}")})
        return {"commands": out}

@app.post("/api/v19/client/{device_id}/commands/{command_id}/ack")
def v19_client_ack(device_id: str, command_id: str, payload: V19CommandAck, request: Request):
    _require_client_token(device_id, request)
    with dbmod.SessionLocal.begin() as session:
        row = session.scalar(select(ClientControlCommand).where(ClientControlCommand.command_id == payload.command_id, ClientControlCommand.device_id == device_id))
        if row is None: raise HTTPException(404, "command not found")
        row.status = "SUCCESS" if str(payload.status).upper() in {"SUCCESS", "OK"} else "FAILED"
        row.result_json = json.dumps(payload.result or {}, ensure_ascii=False)
        row.executed_at = datetime.now()
    return {"ok": True}

@app.post("/api/v19/client/{device_id}/telemetry")
def v19_client_telemetry(device_id: str, payload: V19Telemetry, request: Request):
    _require_client_token(device_id, request)
    with dbmod.SessionLocal.begin() as session:
        device = session.scalar(select(Device).where(Device.device_uuid == device_id))
        if device:
            device.status = payload.status if payload.status in {"ONLINE", "SYNCING", "IDLE", "BUSY"} else "ONLINE"
            device.last_seen_at = datetime.now()
        row = session.scalar(select(ClientControlTelemetry).where(ClientControlTelemetry.device_id == device_id))
        if row is None:
            row = ClientControlTelemetry(device_id=device_id); session.add(row)
        row.cpu_percent = payload.cpu_percent; row.cpu_temperature = payload.cpu_temperature
        row.ram_percent = payload.ram_percent; row.ram_used_gb = payload.ram_used_gb; row.ram_total_gb = payload.ram_total_gb; row.ram_speed_mhz = payload.ram_speed_mhz
        row.gpu_name = str(payload.gpu_name or '')[:180]; row.gpu_percent = payload.gpu_percent; row.gpu_temperature = payload.gpu_temperature; row.gpu_memory_percent = payload.gpu_memory_percent
        row.disk_health_percent = payload.disk_health_percent; row.disk_temperature = payload.disk_temperature; row.disk_usage_percent = payload.disk_usage_percent
        row.disks_json = json.dumps(payload.disks[:32], ensure_ascii=False)
        row.running_apps_json = json.dumps([str(x)[:120] for x in payload.running_apps[:30]], ensure_ascii=False)
        row.current_user = payload.current_user[:120]
        row.session_paused = bool(payload.session_paused)
        row.lan_speed_mbps = payload.lan_speed_mbps
        row.lan_adapter = str(payload.lan_adapter or "")[:180]
    return {"ok": True}

@app.post("/api/v19/client/{device_id}/screen")
def v19_client_screen(device_id: str, payload: V19ScreenUpload, request: Request):
    _require_client_token(device_id, request)
    if not bool(SERVER_CONFIG.get("screen_monitoring_enabled", False)):
        raise HTTPException(403, "Screen Monitoring disabled")
    try:
        raw = base64.b64decode(payload.image_base64, validate=True)
    except Exception:
        raise HTTPException(400, "Invalid image payload")
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Snapshot exceeds 5MB")
    _purge_old_snapshots()
    with dbmod.SessionLocal.begin() as session:
        snap = ClientScreenSnapshot(device_id=device_id, command_id=payload.command_id[:80], mime_type="image/jpeg", image_bytes=raw)
        session.add(snap); session.flush()
        cmd = session.scalar(select(ClientControlCommand).where(ClientControlCommand.command_id == payload.command_id, ClientControlCommand.device_id == device_id)) if command_id else None
        if cmd:
            cmd.status = "SUCCESS"; cmd.executed_at = datetime.now(); cmd.result_json=json.dumps({"snapshot_id": snap.id}, ensure_ascii=False)
        return {"ok": True, "snapshot_id": snap.id, "created_at": snap.created_at.isoformat()}

@app.get("/api/v19/control/clients/{device_id}/snapshot/latest")
def v19_latest_snapshot(device_id: str, request: Request):
    _require_manager_control(request)
    with dbmod.SessionLocal() as session:
        snap = session.scalars(select(ClientScreenSnapshot).where(ClientScreenSnapshot.device_id == device_id).order_by(desc(ClientScreenSnapshot.created_at)).limit(1)).first()
        if snap is None: raise HTTPException(404, "No snapshot available")
        return {"ok": True, "device_id": device_id, "mime_type": snap.mime_type, "image_base64": base64.b64encode(snap.image_bytes).decode("ascii"), "created_at": snap.created_at.isoformat(), "snapshot_id": snap.id}

@app.get("/api/v22/esports")
def v22_esports_snapshot(request: Request):
    _require_manager_control(request)
    return esports_snapshot()

@app.get("/api/v22/esports/catalog")
def v22_esports_catalog():
    return {"games": esports_client_catalog()}

@app.post("/api/v22/esports/provider")
def v22_esports_provider(payload: EsportsProviderPayload, request: Request):
    _require_manager_control(request)
    try: return esports_save_provider(payload.model_dump())
    except Exception as exc: raise HTTPException(400,str(exc))

@app.post("/api/v22/esports/game")
def v22_esports_game(payload: EsportsGamePayload, request: Request):
    _require_manager_control(request)
    try: return esports_save_game(payload.model_dump())
    except Exception as exc: raise HTTPException(400,str(exc))

@app.patch("/api/v22/esports/game/{game_id}")
def v22_esports_toggle(game_id: int, payload: EsportsTogglePayload, request: Request):
    _require_manager_control(request)
    try: return esports_toggle_game(game_id,payload.tournament_enabled,payload.leaderboard_visible)
    except Exception as exc: raise HTTPException(400,str(exc))

@app.post("/api/v22/esports/game/{game_id}/sync")
def v22_esports_sync(game_id: int, request: Request):
    _require_manager_control(request)
    try: return esports_sync_game(game_id)
    except Exception as exc: raise HTTPException(400,str(exc))

@app.post("/api/v22/esports/sync-all")
def v22_esports_sync_all(request: Request):
    _require_manager_control(request)
    try:
        snap=esports_snapshot(); results=[]
        for g in snap.get("games",[]):
            if not g.get("enabled",True): continue
            results.append({"game_id":g["id"],"game":g["name"],**esports_sync_game(int(g["id"]))})
        return {"ok":True,"results":results}
    except Exception as exc:
        raise HTTPException(400,str(exc))

@app.get("/health")
def health():
    return {"status": "UP", "app_version": APP_VERSION, "server_build": SERVER_BUILD, "server_time": datetime.now().isoformat(), "store_name": SERVER_CONFIG.get("store_name", "متجري"), "role": "SERVER"}


@app.get("/api/v15/architecture")
def architecture():
    return {
        "version": APP_VERSION,
        "server": ["database", "api", "discovery", "heartbeat", "outbox", "ha", "device_gateway", "client_ui_profiles", "client_ui_catalog", "client_assets"],
        "manager": ["operator_ui", "pos", "billing", "inventory", "users", "reports", "settings", "client_control"],
        "client": ["webview2_ui", "login", "games", "apps", "session", "wallet", "shop", "ads", "heartbeat", "launcher"],
        "rule": "Client never owns Manager menus; Server never acts as Manager UI."
    }


@app.post("/api/v1/heartbeat")
def heartbeat(h: Heartbeat, request: Request):
    ip = request.client.host if request.client else ""
    _update_device(h, ip)
    return {"ok": True, "server_time": datetime.now().isoformat(), "server_status": "UP"}


@app.post("/api/v15/client/login")
def client_login(data: ClientLogin):
    if not data.customer_name.strip():
        raise HTTPException(400, "customer_name required")
    token = secrets.token_urlsafe(24)
    with dbmod.SessionLocal.begin() as session:
        row = session.scalar(select(Device).where(Device.device_uuid == data.device_id))
        if row:
            row.status = "BUSY"
            row.last_error = ""
            row.last_seen_at = datetime.now()
    return {"ok": True, "token": token, "customer_name": data.customer_name.strip(), "session_status": "ACTIVE", "server_time": datetime.now().isoformat()}


@app.get("/api/v15/client/catalog")
def client_catalog():
    # Server-owned catalog until the full Game Catalog module is introduced.
    return {
        "games": [
            {"id": "valorant", "name": "VALORANT", "category": "FPS", "launch_ready": True},
            {"id": "fortnite", "name": "Fortnite", "category": "Battle Royale", "launch_ready": True},
            {"id": "pubg_mobile", "name": "PUBG Mobile", "category": "Battle Royale", "launch_ready": True},
            {"id": "cs2", "name": "Counter-Strike 2", "category": "FPS", "launch_ready": True},
        ],
        "apps": [
            {"id": "steam", "name": "Steam"}, {"id": "discord", "name": "Discord"}, {"id": "epic", "name": "Epic Games"}
        ]
    }


@app.post("/api/v15/client/launch")
def client_launch(data: LaunchRequest):
    with dbmod.SessionLocal.begin() as session:
        row = session.scalar(select(Device).where(Device.device_uuid == data.device_id))
        if not row:
            raise HTTPException(404, "device not registered")
        row.status = "BUSY"
        row.last_seen_at = datetime.now()
    return {"ok": True, "game_id": data.game_id, "command": "LAUNCH_GAME", "server_time": datetime.now().isoformat()}


@app.get("/api/v15/summary")
def summary_v15():
    with dbmod.SessionLocal() as session:
        total = int(session.scalar(select(func.count(Device.id))) or 0)
        online = syncing = offline = busy = 0
        for device in session.scalars(select(Device)):
            state = _device_status(device)
            if state == "ONLINE": online += 1
            elif state == "SYNCING": syncing += 1
            elif state == "BUSY": busy += 1
            else: offline += 1
        pending = int(session.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(["PENDING", "FAILED"]))) or 0)
        return {"devices_total": total, "online": online, "syncing": syncing, "busy": busy, "offline": offline, "outbox_pending": pending}


@app.get("/api/v15/devices")
def devices_v15():
    with dbmod.SessionLocal() as session:
        result = []
        for device in session.scalars(select(Device).order_by(desc(Device.last_seen_at))).all():
            result.append({
                "id": device.device_uuid, "name": device.device_name, "type": device.device_type,
                "status": _device_status(device), "ip": device.ip_address, "branch_id": device.branch_id,
                "warehouse_id": device.warehouse_id, "last_seen": device.last_seen_at.isoformat() if device.last_seen_at else None,
                "app_version": device.app_version, "last_error": device.last_error or "",
            })
        return {"server_status": "UP", "devices": result}



@app.get("/api/v17/architecture")
def architecture_v17():
    return {
        "version": APP_VERSION,
        "server": ["database", "api", "discovery", "heartbeat", "outbox", "ha", "usb_monitor", "usb_billing"],
        "manager": ["operator_ui", "pos", "billing", "inventory", "users", "reports", "settings", "client_control", "usb_monitor", "usb_billing"],
        "client": ["customer_ui", "login", "games", "apps", "session", "wallet", "shop", "heartbeat", "launcher", "usb_telemetry"],
        "usb_policy": ["ALLOW", "READ_ONLY", "BLOCK"],
        "policy_enforcement": "ADVISORY_UNTIL_ENDPOINT_ADAPTER",
        "file_content_recorded": False,
        "sha256_default": False,
    }


@app.get("/api/v17/usb/summary")
def usb_summary():
    with dbmod.SessionLocal() as session:
        sessions_open = int(session.scalar(select(func.count(USBSession.id)).where(USBSession.status == "OPEN")) or 0)
        clients = set(session.scalars(select(USBSession.client_id).where(USBSession.status == "OPEN")).all())
        events_today = int(session.scalar(select(func.count(USBTransferEvent.id)).where(func.date(USBTransferEvent.event_time) == datetime.now().date())) or 0)
        invoices_today = int(session.scalar(select(func.count(USBInvoice.id)).where(func.date(USBInvoice.created_at) == datetime.now().date())) or 0)
        billed_today = session.scalar(select(func.coalesce(func.sum(USBInvoice.total), 0)).where(func.date(USBInvoice.created_at) == datetime.now().date())) or 0
        return {"clients_with_usb": len(clients), "sessions_open": sessions_open, "events_today": events_today, "invoices_today": invoices_today, "billed_today": float(billed_today)}


@app.get("/api/v17/usb/clients")
def usb_clients():
    with dbmod.SessionLocal() as session:
        policies = {p.client_id: p for p in session.scalars(select(USBPolicy)).all()}
        open_sessions = {}
        for x in session.scalars(select(USBSession).where(USBSession.status == "OPEN").order_by(desc(USBSession.started_at))).all():
            open_sessions[x.client_id] = x
        result=[]
        for d in session.scalars(select(Device).order_by(desc(Device.last_seen_at))).all():
            sid = open_sessions.get(d.device_uuid)
            pol = policies.get(d.device_uuid)
            result.append({"client_id":d.device_uuid,"name":d.device_name,"ip":d.ip_address,"status":_device_status(d),"policy":pol.policy if pol else "ALLOW","sha256_enabled":bool(pol.sha256_enabled) if pol else False,"usb_connected":bool(sid),"session_id":sid.id if sid else None,"volume_label":sid.volume_label if sid else "","mount_path":sid.mount_path if sid else "","bytes_to_usb":sid.bytes_to_usb if sid else 0,"bytes_from_usb":sid.bytes_from_usb if sid else 0})
        return {"clients": result}


@app.get("/api/v17/usb/sessions")
def usb_sessions(status: str | None = None):
    with dbmod.SessionLocal() as session:
        stmt = select(USBSession).order_by(desc(USBSession.started_at))
        if status:
            stmt = stmt.where(USBSession.status == status)
        rows=session.scalars(stmt.limit(500)).all()
        return {"sessions":[{"id":x.id,"client_id":x.client_id,"volume_label":x.volume_label,"mount_path":x.mount_path,"customer_name":x.customer_name,"status":x.status,"started_at":x.started_at.isoformat(),"ended_at":x.ended_at.isoformat() if x.ended_at else None,"bytes_to_usb":x.bytes_to_usb,"bytes_from_usb":x.bytes_from_usb,"subtotal":float(x.subtotal or 0),"tax":float(x.tax or 0),"total":float(x.total or 0),"free_session":bool(x.free_session)} for x in rows]}


@app.get("/api/v17/usb/events")
def usb_events(limit: int = 500):
    limit=max(1,min(limit,1000))
    with dbmod.SessionLocal() as session:
        rows=session.scalars(select(USBTransferEvent).order_by(desc(USBTransferEvent.event_time)).limit(limit)).all()
        return {"events":[{"id":x.id,"session_id":x.session_id,"client_id":x.client_id,"file_name":x.file_name,"file_size_bytes":x.file_size_bytes,"direction":x.direction,"event_time":x.event_time.isoformat(),"status":x.status,"sha256":x.sha256 if x.sha256_enabled else ""} for x in rows]}


@app.get("/api/v17/usb/policy/{client_id}")
def get_usb_policy(client_id: str):
    with dbmod.SessionLocal() as session:
        p=session.scalar(select(USBPolicy).where(USBPolicy.client_id==client_id))
        return {"client_id":client_id,"policy":p.policy if p else "ALLOW","sha256_enabled":bool(p.sha256_enabled) if p else False,"enforcement":"ADVISORY"}


@app.put("/api/v17/usb/policy")
def set_usb_policy(data: USBPolicyRequest):
    policy=str(data.policy).upper().strip()
    if policy not in {"ALLOW","READ_ONLY","BLOCK"}:
        raise HTTPException(400,"policy must be ALLOW, READ_ONLY or BLOCK")
    with dbmod.SessionLocal.begin() as session:
        p=session.scalar(select(USBPolicy).where(USBPolicy.client_id==data.client_id))
        if not p:
            p=USBPolicy(client_id=data.client_id); session.add(p)
        p.policy=policy; p.sha256_enabled=bool(data.sha256_enabled); p.updated_at=datetime.now()
    return {"ok":True,"client_id":data.client_id,"policy":policy,"sha256_enabled":bool(data.sha256_enabled),"enforcement":"ADVISORY"}


@app.post("/api/v17/usb/pricing")
def set_usb_pricing(data: USBPricingRequest):
    if data.per_gb < 0 or data.tax_percent < 0 or data.minimum_charge < 0 or data.free_gb < 0:
        raise HTTPException(400,"pricing values cannot be negative")
    with dbmod.SessionLocal.begin() as session:
        current=get_active_profile(session)
        current.name=data.name.strip() or "Default USB"; current.per_gb=data.per_gb; current.tax_percent=data.tax_percent; current.minimum_charge=data.minimum_charge; current.free_gb=data.free_gb; current.free_session_default=data.free_session_default; current.active=bool(data.enabled)
        for tier in list(session.scalars(select(USBPriceTier).where(USBPriceTier.profile_id==current.id))): session.delete(tier)
        for item in data.tiers:
            session.add(USBPriceTier(profile_id=current.id, up_to_gb=(Decimal(str(item.get("up_to_gb"))) if item.get("up_to_gb") not in (None, "", "null") else None), price_per_gb=Decimal(str(item.get("price_per_gb", data.per_gb)))))
    return {"ok":True}


@app.get("/api/v17/usb/pricing")
def usb_pricing():
    with dbmod.SessionLocal() as session:
        p=get_active_profile(session); tiers=session.scalars(select(USBPriceTier).where(USBPriceTier.profile_id==p.id).order_by(USBPriceTier.id)).all()
        return {"profile":{"name":p.name,"per_gb":float(p.per_gb),"tax_percent":float(p.tax_percent),"minimum_charge":float(p.minimum_charge),"free_gb":float(p.free_gb),"free_session_default":bool(p.free_session_default),"enabled":bool(p.active)},"tiers":[{"up_to_gb":float(t.up_to_gb) if t.up_to_gb is not None else None,"price_per_gb":float(t.price_per_gb)} for t in tiers]}


@app.post("/api/v17/usb/session/start")
def usb_session_start(data: USBSessionStart):
    with dbmod.SessionLocal.begin() as session:
        existing=session.scalar(select(USBSession).where(USBSession.client_id==data.client_id, USBSession.status=="OPEN"))
        if existing:
            return {"ok":True,"session_id":existing.id,"already_open":True}
        policy=session.scalar(select(USBPolicy).where(USBPolicy.client_id==data.client_id))
        free_session=bool(data.free_session) or bool(policy is None and get_active_profile(session).free_session_default)
        row=USBSession(client_id=data.client_id,volume_id=data.volume_id[:120],volume_label=data.volume_label[:180],mount_path=data.mount_path[:260],customer_name=data.customer_name[:120],free_session=free_session)
        session.add(row); session.flush()
        return {"ok":True,"session_id":row.id,"policy":policy.policy if policy else "ALLOW","sha256_enabled":bool(policy.sha256_enabled) if policy else False}


@app.post("/api/v17/usb/session/{session_id}/heartbeat")
def usb_session_heartbeat(session_id:int, data:USBSessionHeartbeat):
    with dbmod.SessionLocal.begin() as session:
        row=session.get(USBSession,session_id)
        if not row or row.status != "OPEN": raise HTTPException(404,"open USB session not found")
        if row.client_id != data.client_id: raise HTTPException(403,"client mismatch")
        row.bytes_to_usb=max(row.bytes_to_usb,int(data.bytes_to_usb)); row.bytes_from_usb=max(row.bytes_from_usb,int(data.bytes_from_usb))
        return {"ok":True,"session_id":row.id}


@app.post("/api/v17/usb/session/{session_id}/event")
def usb_session_event(session_id:int, data:USBTransferRequest):
    direction=str(data.direction).upper().strip()
    if direction not in {"TO_USB","FROM_USB","UNKNOWN"}: raise HTTPException(400,"invalid direction")
    with dbmod.SessionLocal.begin() as session:
        row=session.get(USBSession,session_id)
        if not row or row.status != "OPEN": raise HTTPException(404,"open USB session not found")
        if row.client_id != data.client_id: raise HTTPException(403,"client mismatch")
        policy=session.scalar(select(USBPolicy).where(USBPolicy.client_id==data.client_id))
        sha_ok=bool(policy.sha256_enabled) if policy else False
        digest=(data.sha256 or "")[:64] if sha_ok else ""
        event=USBTransferEvent(session_id=session_id,client_id=data.client_id,file_name=data.file_name[:500],file_size_bytes=int(data.file_size_bytes),direction=direction,status=data.status[:30],sha256=digest,sha256_enabled=sha_ok)
        session.add(event)
        session.flush()
        if direction == "TO_USB": row.bytes_to_usb += int(data.file_size_bytes)
        elif direction == "FROM_USB": row.bytes_from_usb += int(data.file_size_bytes)
        return {"ok":True,"event_id":event.id,"sha256_recorded":bool(digest)}


@app.post("/api/v17/usb/session/{session_id}/close")
def usb_session_close(session_id:int, client_id:str=""):
    with dbmod.SessionLocal.begin() as session:
        row=session.get(USBSession,session_id)
        if not row: raise HTTPException(404,"USB session not found")
        if client_id and row.client_id != client_id: raise HTTPException(403,"client mismatch")
        if row.status == "CLOSED": return {"ok":True,"session_id":row.id,"total":float(row.total or 0),"invoice_no":None}
        profile=get_active_profile(session); tiers=session.scalars(select(USBPriceTier).where(USBPriceTier.profile_id==profile.id).order_by(USBPriceTier.id)).all()
        subtotal,tax,total=bill_bytes(row.bytes_to_usb+row.bytes_from_usb,profile,tiers,row.free_session)
        row.subtotal=subtotal; row.tax=tax; row.total=total; row.status="CLOSED"; row.ended_at=datetime.now()
        invoice=None
        if total > 0 or not row.free_session:
            next_id=(session.scalar(select(func.max(USBInvoice.id))) or 0) + 1
            invoice_no=f"USB-{datetime.now():%Y%m%d}-{next_id:06d}"
            invoice=USBInvoice(invoice_no=invoice_no,client_id=row.client_id,session_id=row.id,customer_name=row.customer_name,subtotal=subtotal,tax=tax,total=total,status="POSTED")
            session.add(invoice)
        return {"ok":True,"session_id":row.id,"subtotal":float(subtotal),"tax":float(tax),"total":float(total),"invoice_no":invoice.invoice_no if invoice else None}


@app.get("/api/v17/usb/archive")
def usb_archive(limit:int=500):
    limit=max(1,min(limit,1000))
    with dbmod.SessionLocal() as session:
        rows=session.scalars(select(USBInvoice).order_by(desc(USBInvoice.created_at)).limit(limit)).all()
        return {"invoices":[{"id":x.id,"invoice_no":x.invoice_no,"client_id":x.client_id,"session_id":x.session_id,"customer_name":x.customer_name,"subtotal":float(x.subtotal),"tax":float(x.tax),"total":float(x.total),"status":x.status,"created_at":x.created_at.isoformat()} for x in rows]}

def run() -> None:
    import uvicorn
    host = str(SERVER_CONFIG.get("server_host", "0.0.0.0"))
    port = int(SERVER_CONFIG.get("server_port", 8787))
    print("=" * 72, flush=True)
    print("POS Professional V27 Central Server", flush=True)
    print(f"Server build: {SERVER_BUILD}", flush=True)
    print(f"Loaded server module: {__file__}", flush=True)
    print(f"Role: SERVER only (API / DB / Discovery / HA)", flush=True)
    print(f"Listening: http://{host}:{port}", flush=True)
    print("=" * 72, flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()


