from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from db import SessionLocal
from models import ClientUIProfile, ClientUIItem, ClientUIBanner

ASSET_DIR = Path(__file__).resolve().parent / "client_assets"
ASSET_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PROFILE = {
    "logo_asset": "",
    "background_asset": "",
    "video_asset": "",
    "main_image_asset": "",
    "icon_games": "",
    "icon_apps": "",
    "icon_shop": "",
    "icon_events": "",
    "icon_ads": "",
    "icon_my_files": "",
    "icon_profile": "",
    "accent_color": "#41d9ff",
    "accent_2": "#a46cff",
    "text_color": "#edf4ff",
    "muted_color": "#9fb1c8",
    "layout_mode": "grid",
    "kiosk_mode": False,
    "show_profile": True,
    "show_games": True,
    "show_apps": True,
    "show_shop": True,
    "show_events": True,
    "show_ads": True,
    "show_my_files": True,
    "welcome_text": "اختر ما تريد تشغيله",
    "profile_badge": "PLAYER",
}


def _profile_dict(row: ClientUIProfile | None) -> dict[str, Any]:
    if row is None:
        out = dict(DEFAULT_PROFILE)
        return out
    out = {
        "device_id": row.device_id,
        "logo_asset": row.logo_asset,
        "background_asset": row.background_asset,
        "video_asset": row.video_asset,
        "main_image_asset": row.main_image_asset,
        "icon_games": row.icon_games,
        "icon_apps": row.icon_apps,
        "icon_shop": row.icon_shop,
        "icon_events": row.icon_events,
        "icon_ads": row.icon_ads,
        "icon_my_files": row.icon_my_files,
        "icon_profile": row.icon_profile,
        "accent_color": row.accent_color,
        "accent_2": row.accent_2,
        "text_color": row.text_color,
        "muted_color": row.muted_color,
        "layout_mode": row.layout_mode,
        "kiosk_mode": bool(row.kiosk_mode),
        "show_profile": bool(row.show_profile),
        "show_games": bool(row.show_games),
        "show_apps": bool(row.show_apps),
        "show_shop": bool(row.show_shop),
        "show_events": bool(row.show_events),
        "show_ads": bool(row.show_ads),
        "show_my_files": bool(row.show_my_files),
        "welcome_text": row.welcome_text,
        "profile_badge": row.profile_badge,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    return out


def ensure_profile(session, device_id: str) -> ClientUIProfile:
    row = session.scalar(select(ClientUIProfile).where(ClientUIProfile.device_id == device_id))
    if row is None:
        row = ClientUIProfile(device_id=device_id, **DEFAULT_PROFILE)
        session.add(row)
        session.flush()
    return row


def get_profile(device_id: str) -> dict[str, Any]:
    with SessionLocal.begin() as session:
        if str(device_id) != "__DEFAULT__":
            default = ensure_profile(session, "__DEFAULT__")
            row = ensure_profile(session, device_id)
            out = _profile_dict(default)
            specific = _profile_dict(row)
            # Device-specific values override the global default only when explicitly populated.
            for key, value in specific.items():
                if key == "device_id":
                    continue
                if isinstance(value, bool):
                    # Existing profiles retain their own boolean setting.
                    out[key] = value
                elif value not in (None, ""):
                    out[key] = value
            out["device_id"] = device_id
            return out
        row = ensure_profile(session, "__DEFAULT__")
        return _profile_dict(row)


def save_profile(device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULT_PROFILE) - {"device_id"}
    with SessionLocal.begin() as session:
        row = ensure_profile(session, device_id)
        for key in allowed:
            if key not in payload:
                continue
            value = payload[key]
            if isinstance(getattr(row, key), bool):
                value = bool(value)
            elif key in {"accent_color", "accent_2", "text_color", "muted_color"}:
                value = str(value or "")[:40]
            elif key in {"layout_mode", "welcome_text", "profile_badge", "logo_asset", "background_asset", "video_asset", "main_image_asset", "icon_games", "icon_apps", "icon_shop", "icon_events", "icon_ads", "icon_my_files", "icon_profile"}:
                value = str(value or "")[:500]
            setattr(row, key, value)
        row.updated_at = datetime.now()
        session.flush()
        return _profile_dict(row)


def list_items(device_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ClientUIItem).where(ClientUIItem.device_id == device_id, ClientUIItem.enabled.is_(True)).order_by(ClientUIItem.sort_order, ClientUIItem.id)
        ).all()
        return [
            {
                "id": row.id,
                "item_type": row.item_type,
                "name": row.name,
                "description": row.description,
                "icon_asset": row.icon_asset,
                "launch_type": row.launch_type,
                "target": row.target,
                "args": row.args,
                "working_dir": row.working_dir,
                "enabled": bool(row.enabled),
                "sort_order": row.sort_order,
            }
            for row in rows
        ]


def list_all_items(device_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(ClientUIItem).where(ClientUIItem.device_id == device_id).order_by(ClientUIItem.item_type, ClientUIItem.sort_order, ClientUIItem.id)).all()
        return [
            {
                "id": row.id,
                "item_type": row.item_type,
                "name": row.name,
                "description": row.description,
                "icon_asset": row.icon_asset,
                "launch_type": row.launch_type,
                "target": row.target,
                "args": row.args,
                "working_dir": row.working_dir,
                "enabled": bool(row.enabled),
                "sort_order": row.sort_order,
            }
            for row in rows
        ]


def upsert_item(device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item_id = payload.get("id")
    with SessionLocal.begin() as session:
        row = None
        if item_id:
            row = session.scalar(select(ClientUIItem).where(ClientUIItem.id == int(item_id), ClientUIItem.device_id == device_id))
        if row is None:
            row = ClientUIItem(device_id=device_id, item_type=str(payload.get("item_type") or "GAME").upper())
            session.add(row)
        for key in ("item_type", "name", "description", "icon_asset", "launch_type", "target", "args", "working_dir"):
            if key in payload:
                setattr(row, key, str(payload.get(key) or ""))
        row.item_type = row.item_type.upper() if row.item_type else "GAME"
        row.launch_type = row.launch_type.upper() if row.launch_type else "EXE"
        row.enabled = bool(payload.get("enabled", True))
        row.sort_order = int(payload.get("sort_order", 0) or 0)
        session.flush()
        return {
            "id": row.id,
            "item_type": row.item_type,
            "name": row.name,
            "description": row.description,
            "icon_asset": row.icon_asset,
            "launch_type": row.launch_type,
            "target": row.target,
            "args": row.args,
            "working_dir": row.working_dir,
            "enabled": bool(row.enabled),
            "sort_order": row.sort_order,
        }


def delete_item(device_id: str, item_id: int) -> bool:
    with SessionLocal.begin() as session:
        row = session.scalar(select(ClientUIItem).where(ClientUIItem.id == item_id, ClientUIItem.device_id == device_id))
        if not row:
            return False
        session.delete(row)
        return True


def list_banners(device_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(ClientUIBanner).where(ClientUIBanner.device_id == device_id, ClientUIBanner.enabled.is_(True)).order_by(ClientUIBanner.sort_order, ClientUIBanner.id)).all()
        return [_banner_dict(row) for row in rows]


def list_all_banners(device_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(ClientUIBanner).where(ClientUIBanner.device_id == device_id).order_by(ClientUIBanner.sort_order, ClientUIBanner.id)).all()
        return [_banner_dict(row) for row in rows]


def _banner_dict(row: ClientUIBanner) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "image_asset": row.image_asset,
        "url": row.url,
        "enabled": bool(row.enabled),
        "sort_order": row.sort_order,
    }


def upsert_banner(device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    banner_id = payload.get("id")
    with SessionLocal.begin() as session:
        row = None
        if banner_id:
            row = session.scalar(select(ClientUIBanner).where(ClientUIBanner.id == int(banner_id), ClientUIBanner.device_id == device_id))
        if row is None:
            row = ClientUIBanner(device_id=device_id)
            session.add(row)
        for key in ("title", "body", "image_asset", "url"):
            if key in payload:
                setattr(row, key, str(payload.get(key) or ""))
        row.enabled = bool(payload.get("enabled", True))
        row.sort_order = int(payload.get("sort_order", 0) or 0)
        session.flush()
        return _banner_dict(row)


def delete_banner(device_id: str, banner_id: int) -> bool:
    with SessionLocal.begin() as session:
        row = session.scalar(select(ClientUIBanner).where(ClientUIBanner.id == banner_id, ClientUIBanner.device_id == device_id))
        if not row:
            return False
        session.delete(row)
        return True
