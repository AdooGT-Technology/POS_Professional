from __future__ import annotations

import json
import base64
import secrets
import sys
import os
import webbrowser
from datetime import date, datetime, time, timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import selectinload

from config import CONFIG, save_config
from db import SessionLocal, engine
from models import (
    AuditLog,
    BackupRun,
    Branch,
    CashMovement,
    Customer,
    Device,
    Expense,
    HealthCheckLog,
    InventoryTransfer,
    MigrationRun,
    OutboxEvent,
    Permission,
    Product,
    Purchase,
    Return,
    Role,
    Sale,
    Shift,
    Supplier,
    SyncEvent,
    User,
    UserPermission,
    Warehouse,
    WarehouseStock,
)
from security import hash_password
from services import (
    AuthService,
    CashService,
    CentralBackupService,
    ExpenseService,
    InventoryService,
    MasterService,
    OutboxService,
    ProductService,
    ReportService,
    ReturnService,
    SalesService,
    ShiftService,
    UserService,
    AuditService,
)

WEB_UI_DIR = Path(__file__).resolve().parent / "webui"
APP_VERSION = "V27.5.7"

MANAGER_MENU = [
    ("__HOME_DIRECT__", [("home", "⌂", "الرئيسية", "مركز التشغيل والملخص الحي")]),
    ("الأجهزة", [("clients", "▦", "الأجهزة", "قائمة الأجهزة والجلسات ومراقبتها")]),
    ("Hardware & Operations", [("usb", "⛓", "USB Monitor", "الجلسات والسياسات والتسعير")]),
    ("POS", [
        ("cashier", "▣", "الكاشير والمبيعات والفواتير", "مركز موحد للبيع والفواتير"),
        ("returns", "↺", "المرتجعات", "الاسترداد والمرتجعات"),
        ("shifts", "◷", "الورديات والصندوق", "الوردية والخزينة ويومية الصندوق"),
        ("expenses", "−", "المصروفات", "المصروفات"),
    ]),
    ("المخزون", [
        ("products", "◆", "المنتجات", "الأسعار والمنتجات"),
        ("contacts", "◎", "العملاء والموردون", "جهات التعامل"),
        ("purchases", "⇩", "المشتريات", "التوريد والتكلفة"),
        ("inventory", "▦", "المخزون والتحويلات", "الجرد والتسوية والتحويل بين المخازن"),
        ("branches", "⌂", "الفروع والمخازن", "الهيكل التشغيلي"),
    ]),
    ("الألعاب والمهام", [
        ("game-library", "🎮", "Game Library", "إدارة الألعاب والبرامج مع المعاينة الحية"),
        ("task-library", "⚡", "مكتبة مهام الأجهزة", "مهام الأجهزة الاحترافية ومراحل التنفيذ"),
        ("esports", "◈", "Esports", "مصادر الألعاب وLeaderboard والمباريات الحية"),
    ]),
    ("الإدارة والحماية", [
        ("reports", "◫", "التقارير", "المبيعات والربحية"),
        ("users", "◍", "المستخدمون والصلاحيات", "الحسابات والأدوار"),
        ("data-management", "⬢", "قاعدة البيانات", "Backup / Restore / Merge / Migration"),
        ("audit", "⌁", "سجل النشاط", "Audit Trail"),
    ]),
]


def _dt(value):
    return value.isoformat(sep=" ", timespec="seconds") if isinstance(value, datetime) else value


def _dec(value):
    return float(value or 0)


def _require_admin(user):
    if not user:
        raise PermissionError("يجب تسجيل الدخول أولاً.")


class ManagerWebAPI:
    """Single modern Manager UI API. There is intentionally no legacy launcher/API."""

    def __init__(self, runtime):
        self._runtime = runtime
        self._window = None
        self._user = None

    def _ensure_auth(self):
        _require_admin(self._user)

    def _server(self) -> str:
        url = self._runtime.ensure_server()
        if not url:
            raise RuntimeError("Central Server غير متصل")
        return url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-Manager-Id": str(self._runtime.device_id), "X-Manager-Version": APP_VERSION}

    def _get_json(self, url: str, *, timeout: float = 5, headers: dict[str, str] | None = None, label: str = "Server"):
        """GET JSON without allowing an HTML/proxy/error page to crash pywebview."""
        response = requests.get(url, headers=headers, timeout=timeout)
        content_type = str(response.headers.get("content-type") or "").lower()
        try:
            return response.json()
        except ValueError as exc:
            snippet = response.text.strip().replace("\n", " ")[:240]
            raise RuntimeError(f"{label}: استجابة غير صالحة من الخادم (HTTP {response.status_code}, {content_type or 'unknown'}): {snippet or 'بدون محتوى'}") from exc


    def menu(self):
        self._ensure_auth()
        # One canonical entry per module. Home is a direct item because it has no children.
        seen=set(); groups=[]
        for g, items in MANAGER_MENU:
            unique=[]
            for i, icon, name, sub in items:
                if i in seen: continue
                seen.add(i); unique.append({"id":i,"icon":icon,"name":name,"description":sub})
            if unique: groups.append({"group":g,"direct":g=="__HOME_DIRECT__","items":unique})
        return groups

    def configure_server(self, payload: dict[str, Any]):
        host=str((payload or {}).get('ip') or '').strip()
        port=int((payload or {}).get('port') or 8787)
        store=str((payload or {}).get('store_name') or '').strip()
        if not host: return {"ok":False,"error":"أدخل IP الخادم."}
        if not (1 <= port <= 65535): return {"ok":False,"error":"البورت غير صحيح."}
        self._runtime.server_url=f"http://{host}:{port}"
        self._runtime.cfg["server_url"]=self._runtime.server_url
        self._runtime.cfg["server_ip"]=host
        self._runtime.cfg["server_port"]=port
        self._runtime.cfg["store_name"]=store
        self._runtime._save()
        CONFIG["store_name"]=store or CONFIG.get("store_name","متجري")
        save_config(CONFIG)
        connected = self._runtime.heartbeat_once()
        return {"ok":True,"connected":bool(connected),"server_url":self._runtime.server_url,"store_name":CONFIG["store_name"],"error":self._runtime.last_error if not connected else ""}

    def login(self, payload: dict[str, Any]):
        username = str((payload or {}).get("username") or "").strip()
        password = str((payload or {}).get("password") or "")
        if not username or not password:
            return {"ok": False, "error": "أدخل اسم المستخدم وكلمة المرور."}
        user = AuthService.login(username, password)
        if not user:
            return {"ok": False, "error": "بيانات الدخول غير صحيحة."}
        role_name = str(getattr(getattr(user, "role", None), "name", "") or "")
        role = role_name
        if role.upper() not in {"ADMIN", "MANAGER", "OWNER", "مدير"} and role not in {"مدير النظام"}:
            return {"ok": False, "error": "هذا الحساب غير مخول للدخول إلى Manager."}
        self._user = user
        try:
            self._runtime.set_online()
        except Exception:
            pass
        return {"ok": True, "user": {"id": user.id, "username": user.username, "name": user.full_name, "role": role}}

    def connection_status(self):
        # The background heartbeat owns connectivity. Avoid a blocking network call on every UI status refresh.
        return self._runtime.connection_status()

    def branding(self):
        return {"store_name": CONFIG.get("store_name", "متجري"), "logo_data": CONFIG.get("store_logo_data", "")}

    def context(self):
        if not self._user:
            return {"authenticated": False}
        role = getattr(getattr(self._user, "role", None), "name", "") or ""
        return {"authenticated": True, "user": {"id": self._user.id, "username": self._user.username, "name": self._user.full_name, "role": role}, "device_id": self._runtime.device_id, "server_url": self._runtime.server_url, "connection": self._runtime.connection_status(), "branding": {"store_name": CONFIG.get("store_name","متجري"), "logo_data": CONFIG.get("store_logo_data","")}}

    def logout(self):
        self._user = None
        return {"ok": True}

    def window_toggle_fullscreen(self):
        self._ensure_auth()
        try:
            if self._window is not None:
                self._window.toggle_fullscreen()
                return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "نافذة Manager غير جاهزة."}

    def clients(self):
        self._ensure_auth()
        return requests.get(self._server() + "/api/v18/manager/clients", headers=self._headers(), timeout=5).json()

    def usb(self):
        self._ensure_auth(); base=self._server(); h=self._headers()
        calls={
            "summary": ("/api/v17/usb/summary", 5),
            "clients": ("/api/v17/usb/clients", 5),
            "sessions": ("/api/v17/usb/sessions?status=OPEN", 5),
            "events": ("/api/v17/usb/events?limit=100", 5),
            "archive": ("/api/v17/usb/archive?limit=100", 5),
            "pricing": ("/api/v17/usb/pricing", 5),
        }
        def fetch(item):
            key,(path,timeout)=item
            return key,self._get_json(base+path, headers=h, timeout=timeout, label=f"USB {key}")
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="ManagerUSB") as ex:
            rows=dict(ex.map(fetch, calls.items()))
        return {"summary":rows.get("summary",{}),"clients":rows.get("clients",{}).get("clients",[]),"sessions":rows.get("sessions",{}).get("sessions",[]),"events":rows.get("events",{}).get("events",[]),"archive":rows.get("archive",{}).get("archive",[]),"pricing":rows.get("pricing",{})}

    # ---------- Generic module data ----------
    def module_data(self, module: str):
        self._ensure_auth()
        with SessionLocal() as s:
            if module == "home":
                try:
                    clients = self._get_json(self._server() + "/api/v27/manager/devices-summary", headers=self._headers(), timeout=4, label="Home devices")
                except Exception as exc:
                    clients = {"clients": [], "error": str(exc)}
                today=date.today(); summary=ReportService.sales_summary(today,today)
                try:
                    pending=int(s.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(["PENDING","FAILED"]))) or 0)
                    health=s.scalars(select(HealthCheckLog).order_by(desc(HealthCheckLog.id)).limit(5)).all()
                    sync=s.scalars(select(SyncEvent).order_by(desc(SyncEvent.id)).limit(5)).all()
                except Exception:
                    pending=0; health=[]; sync=[]
                return {"kind":"home","clients":clients.get("clients",[]),"summary":{"invoices":int(summary[0] or 0),"sales":_dec(summary[4])},"queue_pending":pending,"health":[self._health_row(x) for x in health],"sync":[self._sync_row(x) for x in sync],"server_error":clients.get("error","")}
            if module == "hardware-monitor":
                data=self.client_control()
                data["kind"]="hardware-monitor"
                return data
            if module in {"cashier", "sales", "invoices"}:
                sale_options = [selectinload(Sale.user)]
                if hasattr(Sale, "customer"):
                    sale_options.append(selectinload(Sale.customer))
                rows = s.scalars(select(Sale).options(*sale_options).order_by(desc(Sale.id)).limit(150)).all()
                shifts = s.scalars(select(Shift).options(selectinload(Shift.user)).order_by(desc(Shift.id)).limit(100)).all()
                expenses = s.scalars(select(Expense).order_by(desc(Expense.id)).limit(150)).all()
                cash = s.scalars(select(CashMovement).order_by(desc(CashMovement.id)).limit(150)).all()
                return {"kind": "cashier", "rows": [self._sale_row(x) for x in rows], "products": self._products(s), "suspended": self._suspended(s), "current_shift": self._shift_row(ShiftService.current(self._user.id)), "shifts": [self._shift_row(x) for x in shifts], "expenses": [self._expense_row(x) for x in expenses], "cash": [self._cash_row(x) for x in cash]}
            if module == "returns":
                rows = s.scalars(select(Return).order_by(desc(Return.id)).limit(150)).all()
                return {"kind": "returns", "rows": [self._return_row(x) for x in rows]}
            if module == "purchases":
                rows = s.scalars(select(Purchase).order_by(desc(Purchase.id)).limit(150)).all()
                return {"kind": "purchases", "rows": [self._purchase_row(x) for x in rows]}
            if module == "shifts":
                rows = s.scalars(select(Shift).options(selectinload(Shift.user)).order_by(desc(Shift.id)).limit(100)).all()
                return {"kind": "shifts", "rows": [self._shift_row(x) for x in rows]}
            if module == "cash-day":
                rows = s.scalars(select(CashMovement).order_by(desc(CashMovement.id)).limit(150)).all()
                return {"kind": "cash", "rows": [self._cash_row(x) for x in rows], "current_shift": self._shift_row(ShiftService.current(self._user.id))}
            if module == "expenses":
                rows = s.scalars(select(Expense).order_by(desc(Expense.id)).limit(150)).all()
                return {"kind": "expenses", "rows": [self._expense_row(x) for x in rows]}
            if module == "products":
                return {"kind": "products", "rows": self._products(s)}
            if module == "contacts":
                customers = s.scalars(select(Customer).order_by(Customer.name)).all()
                suppliers = s.scalars(select(Supplier).order_by(Supplier.name)).all()
                return {"kind": "contacts", "customers": [self._contact_row(x) for x in customers], "suppliers": [self._contact_row(x) for x in suppliers]}
            if module in {"branches", "inventory", "transfers"}:
                branches = s.scalars(select(Branch).order_by(Branch.name)).all()
                warehouses = s.scalars(select(Warehouse).options(selectinload(Warehouse.branch)).order_by(Warehouse.name)).all()
                stock = s.scalars(select(WarehouseStock).options(selectinload(WarehouseStock.product), selectinload(WarehouseStock.warehouse)).order_by(WarehouseStock.id).limit(250)).all()
                transfers = s.scalars(select(InventoryTransfer).order_by(desc(InventoryTransfer.id)).limit(100)).all()
                return {"kind": "inventory", "branches": [self._branch_row(x) for x in branches], "warehouses": [self._warehouse_row(x) for x in warehouses], "stock": [self._stock_row(x) for x in stock], "transfers": [self._transfer_row(x) for x in transfers]}
            if module == "reports":
                d = date.today(); summary = ReportService.sales_summary(d, d); profit = ReportService.profit(d, d); top = ReportService.top_products(d, d)
                return {"kind": "reports", "today": {"invoices": int(summary[0] or 0), "subtotal": _dec(summary[1]), "discount": _dec(summary[2]), "tax": _dec(summary[3]), "sales": _dec(summary[4]), "profit": _dec(profit)}, "top": [{"name": x[0], "qty": _dec(x[1]), "amount": _dec(x[2])} for x in top]}
            if module == "users":
                users = UserService.users(); roles = UserService.roles()
                perms = s.scalars(select(Permission).order_by(Permission.code)).all()
                users = s.scalars(select(User).options(selectinload(User.role).selectinload(Role.permissions), selectinload(User.permissions)).order_by(User.username)).all()
                roles = s.scalars(select(Role).options(selectinload(Role.permissions)).order_by(Role.name)).all()
                return {"kind":"users","rows":[{"id":u.id,"username":u.username,"full_name":u.full_name,"active":bool(u.active),"role_id":u.role_id,"role":u.role.name if u.role else "","permission_codes":[p.code for p in u.permissions] if u.permissions else [p.code for p in (u.role.permissions if u.role else [])],"direct_permission_codes":[p.code for p in u.permissions],"permissions_override":bool(u.permissions_override)} for u in users],"roles":[{"id":r.id,"name":r.name,"description":r.description,"permission_codes":[p.code for p in r.permissions]} for r in roles],"permissions":[{"id":p.id,"code":p.code,"name":p.name} for p in perms]}
            if module in {"backup", "migration", "database", "data-recovery", "data-management"}:
                backs = s.scalars(select(BackupRun).order_by(desc(BackupRun.id)).limit(100)).all()
                migs = s.scalars(select(MigrationRun).order_by(desc(MigrationRun.id)).limit(100)).all()
                return {"kind": "recovery", "backups": [self._backup_row(x) for x in backs], "migrations": [self._migration_row(x) for x in migs], "database": self.database_status()}
            if module == "audit":
                rows = s.scalars(select(AuditLog).order_by(desc(AuditLog.id)).limit(200)).all()
                return {"kind": "audit", "rows": [{"id": x.id, "action": x.action, "entity": x.entity, "entity_id": x.entity_id, "details": x.details, "created_at": _dt(x.created_at), "hash": x.hash_value} for x in rows]}
            if module == "ha":
                out = s.scalars(select(OutboxEvent).order_by(desc(OutboxEvent.id)).limit(150)).all()
                health = s.scalars(select(HealthCheckLog).order_by(desc(HealthCheckLog.id)).limit(100)).all()
                sync = s.scalars(select(SyncEvent).order_by(desc(SyncEvent.id)).limit(100)).all()
                return {"kind": "ha", "outbox": [self._outbox_row(x) for x in out], "health": [self._health_row(x) for x in health], "sync": [self._sync_row(x) for x in sync], "summary": OutboxService.summary()}

            if module == "settings":
                try:
                    clients=self._get_json(self._server()+"/api/v18/manager/clients",headers=self._headers(),timeout=3,label="Manager clients").get("clients",[])
                except Exception:
                    clients=[]
                try:
                    session_pricing=self._get_json(self._server()+"/api/v27/session-pricing",headers=self._headers(),timeout=3,label="Session pricing")
                except Exception:
                    session_pricing={"enabled":True,"hourly_rate":0,"minute_rate":0,"billing_mode":"HOURLY","currency":CONFIG.get("currency","جنيه"),"offer_bonus_minutes":0,"minimum_charge":0,"rounding_minutes":1,"grace_minutes":0,"tax_included":False,"tax_rate":CONFIG.get("tax_rate",0),"peak_enabled":False,"peak_start":"18:00","peak_end":"23:00","peak_hourly_rate":0}
                return {"kind":"settings","config":CONFIG,"clients":clients,"session_pricing":session_pricing}
            if module in {"clients", "devices", "connection", "control-center"}:
                # Use the V19 control state so the Clients list and Hardware Monitor share one telemetry source.
                try:
                    base = self._server()
                    payload = self._get_json(base + "/api/v27/manager/devices-summary", headers=self._headers(), timeout=4, label="Devices")
                except Exception as exc:
                    payload = {"clients": [], "error": str(exc)}
                return {"kind": "clients", **payload}
            if module == "usb":
                return self.usb()
            if module == "client-studio":
                try:
                    clients = requests.get(self._server() + "/api/v18/manager/clients", headers=self._headers(), timeout=5).json().get("clients", [])
                except Exception:
                    clients = []
                return {"kind": "client-studio", "clients": clients}
        return {"kind": "info", "title": module, "message": "الوحدة جاهزة في Manager الموحد، ويمكن إضافة الوظائف المتخصصة عبر نفس مساحة العمل."}

    # ---------- Actions ----------
    def save_entity(self, entity: str, payload: dict[str, Any]):
        self._ensure_auth(); payload = dict(payload or {})
        with SessionLocal.begin() as s:
            if entity == "product":
                pid = payload.get("id")
                p = s.get(Product, int(pid)) if pid else Product()
                p.barcode = str(payload.get("barcode") or "").strip() or None
                p.name = str(payload.get("name") or "").strip()
                if not p.name: raise ValueError("اسم المنتج مطلوب.")
                p.price = Decimal(str(payload.get("price") or 0)); p.cost = Decimal(str(payload.get("cost") or 0)); p.stock = Decimal(str(payload.get("stock") or 0)); p.min_stock = Decimal(str(payload.get("min_stock") or 0)); p.unit = str(payload.get("unit") or "قطعة"); p.active = bool(payload.get("active", True))
                s.add(p); s.flush()
                wh_id = payload.get("warehouse_id")
                if wh_id:
                    ws = s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==p.id, WarehouseStock.warehouse_id==int(wh_id)))
                    if not ws: ws = WarehouseStock(warehouse_id=int(wh_id), product_id=p.id, quantity=0, min_stock=p.min_stock); s.add(ws)
                    ws.quantity = Decimal(str(payload.get("warehouse_stock") if payload.get("warehouse_stock") is not None else p.stock)); ws.min_stock=p.min_stock
                return {"ok": True, "id": p.id}
            if entity in {"customer", "supplier"}:
                model = Customer if entity == "customer" else Supplier
                row = s.get(model, int(payload["id"])) if payload.get("id") else model()
                row.name = str(payload.get("name") or "").strip(); row.phone = str(payload.get("phone") or ""); row.address = str(payload.get("address") or "")
                if not row.name: raise ValueError("الاسم مطلوب.")
                s.add(row); s.flush(); return {"ok": True, "id": row.id}
            if entity == "branch":
                row = s.get(Branch, int(payload["id"])) if payload.get("id") else Branch()
                row.code = str(payload.get("code") or "").strip(); row.name = str(payload.get("name") or "").strip(); row.address = str(payload.get("address") or ""); row.phone = str(payload.get("phone") or ""); row.active = bool(payload.get("active", True))
                if not row.code or not row.name: raise ValueError("كود واسم الفرع مطلوبان.")
                s.add(row); s.flush(); return {"ok": True, "id": row.id}
            if entity == "warehouse":
                row = s.get(Warehouse, int(payload["id"])) if payload.get("id") else Warehouse()
                row.code = str(payload.get("code") or "").strip(); row.name = str(payload.get("name") or "").strip(); row.branch_id = int(payload.get("branch_id") or 0); row.active = bool(payload.get("active", True))
                if not row.code or not row.name or not row.branch_id: raise ValueError("كود واسم ومقر المخزن مطلوبة.")
                s.add(row); s.flush(); return {"ok": True, "id": row.id}
            if entity == "user":
                uid = int(payload["id"]) if payload.get("id") else None
                u = s.get(User, uid) if uid else User()
                u.username = str(payload.get("username") or "").strip(); u.full_name = str(payload.get("full_name") or "").strip(); u.role_id = int(payload.get("role_id") or 0); u.active = bool(payload.get("active", True))
                if payload.get("password"): u.password_hash = hash_password(str(payload["password"]))
                if not u.username or not u.full_name or not u.role_id: raise ValueError("بيانات المستخدم غير مكتملة.")
                s.add(u); s.flush(); return {"ok": True, "id": u.id}
            if entity == "expense":
                row = Expense(user_id=self._user.id, amount=Decimal(str(payload.get("amount") or 0)), category=str(payload.get("category") or "عام"), note=str(payload.get("note") or ""), branch_id=int(payload.get("branch_id")) if payload.get("branch_id") else None)
                s.add(row); s.flush(); return {"ok": True, "id": row.id}
        raise ValueError("العنصر غير مدعوم.")

    def delete_entity(self, entity: str, row_id: int):
        self._ensure_auth()
        with SessionLocal.begin() as s:
            model_map = {"product": Product, "customer": Customer, "supplier": Supplier, "branch": Branch, "warehouse": Warehouse, "user": User}
            model = model_map.get(entity)
            if not model: raise ValueError("الحذف غير مدعوم.")
            row = s.get(model, int(row_id))
            if not row: return {"ok": False, "error": "السجل غير موجود."}
            if hasattr(row, "active"): row.active = False
            else: s.delete(row)
            return {"ok": True}

    def create_sale(self, payload: dict[str, Any]):
        self._ensure_auth()
        cart = payload.get("cart") or []
        if not cart: raise ValueError("أضف منتجًا واحدًا على الأقل.")
        sale = SalesService.create(self._user.id, cart, discount=payload.get("discount", 0), payment_method=str(payload.get("payment_method") or "نقدي"), paid=payload.get("paid", 0), customer_id=payload.get("customer_id"), tax_rate=payload.get("tax_rate", CONFIG.get("tax_rate", 0)), branch_id=payload.get("branch_id"), warehouse_id=payload.get("warehouse_id"), client_request_id=payload.get("client_request_id"))
        return {"ok": True, "invoice": sale.invoice_no, "id": sale.id, "total": _dec(sale.total), "change": _dec(sale.change_amount)}

    def open_shift(self, opening_cash=0, branch_id=None, warehouse_id=None):
        self._ensure_auth(); sh = ShiftService.open_shift(self._user.id, branch_id, warehouse_id, opening_cash); return {"ok": True, "id": sh.id}

    def close_shift(self, shift_id: int, closing_cash):
        self._ensure_auth(); sh = ShiftService.close_shift(self._user.id, int(shift_id), closing_cash); return {"ok": True, "difference": _dec(sh.difference)}

    def cash_movement(self, shift_id: int, movement_type: str, amount, note=""):
        self._ensure_auth(); ShiftService.cash_movement(self._user.id, int(shift_id), movement_type, amount, note); return {"ok": True}

    def stock_adjust(self, product_id: int, warehouse_id: int, actual_qty, note=""):
        self._ensure_auth(); InventoryService.count_and_adjust(self._user.id, int(warehouse_id), [{"product_id": int(product_id), "actual_qty": actual_qty}], note); return {"ok": True}

    def requeue_outbox(self):
        self._ensure_auth(); return {"ok": True, "count": OutboxService.requeue_failed(200)}

    def run_backup(self):
        self._ensure_auth(); result=CentralBackupService.run_safely(); return {"ok":True,"result":str(result)}

    def restore_backup(self,path=""):
        self._ensure_auth(); import shutil,sqlite3
        src=Path(str(path or "")).expanduser()
        if not src.is_file():
            with SessionLocal() as s:
                row=s.scalar(select(BackupRun).where(BackupRun.status=="SUCCESS").order_by(desc(BackupRun.id)).limit(1))
            if row: src=Path(row.path)
        if not src.is_file(): raise ValueError("لم يتم العثور على نسخة Backup صالحة")
        db_path=CentralBackupService._sqlite_source()
        if not db_path or not db_path.exists(): raise ValueError("قاعدة SQLite الحالية غير متاحة")
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); safety=db_path.with_name(db_path.stem+f"_before_restore_{stamp}.db"); shutil.copy2(db_path,safety)
        a=sqlite3.connect(src); b=sqlite3.connect(db_path)
        try: a.backup(b); b.commit(); check=b.execute("PRAGMA integrity_check").fetchone()[0]
        finally: b.close(); a.close()
        return {"ok":check=="ok","restored_from":str(src),"safety_backup":str(safety),"integrity":check}

    def merge_database(self,path=""):
        self._ensure_auth(); import sqlite3
        src=Path(str(path or "")).expanduser(); dst=CentralBackupService._sqlite_source()
        if not src.is_file(): raise ValueError("اختر ملف قاعدة بيانات للدمج")
        if not dst or not dst.exists(): raise ValueError("قاعدة SQLite الحالية غير متاحة")
        con=sqlite3.connect(dst); merged=[]
        try:
            con.execute("ATTACH DATABASE ? AS incoming",(str(src),))
            for (table,) in con.execute("SELECT name FROM incoming.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                cols=[r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()]
                if not cols or not con.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?",(table,)).fetchone(): continue
                q=','.join('"'+c.replace('"','""')+'"' for c in cols)
                con.execute(f'INSERT OR IGNORE INTO main."{table}" ({q}) SELECT {q} FROM incoming."{table}"'); merged.append(table)
            con.commit(); con.execute("DETACH DATABASE incoming")
        finally: con.close()
        return {"ok":True,"tables":merged,"source":str(src)}

    def migrate_database(self):
        self._ensure_auth(); from db import init_db; started=datetime.now(); init_db()
        with SessionLocal.begin() as ss: ss.add(MigrationRun(revision="V27.5.7",status="SUCCESS",backup_path="",restore_test_status="NOT_REQUIRED",started_at=started,finished_at=datetime.now(),details="Schema reconciliation from Manager Database Center"))
        return {"ok":True,"revision":"V27.5.7","status":"SUCCESS"}

    def pick_path(self, kind="file"):
        self._ensure_auth()
        if self._window is None: return {"ok":False,"error":"نافذة Manager غير جاهزة"}
        try:
            import webview
            mode = webview.FileDialog.FOLDER if str(kind).lower()=="folder" else webview.FileDialog.OPEN
            result=self._window.create_file_dialog(mode, allow_multiple=False)
            path=result[0] if isinstance(result,(list,tuple)) and result else result
            return {"ok":bool(path),"path":str(path or "")}
        except Exception as exc:
            return {"ok":False,"error":str(exc)}

    def save_branding(self, payload: dict[str, Any]):
        self._ensure_auth()
        name=str((payload or {}).get("store_name") or CONFIG.get("store_name") or "متجري").strip()
        logo=str((payload or {}).get("logo_data") or CONFIG.get("store_logo_data") or "")
        if logo and len(logo)>4_000_000: return {"ok":False,"error":"حجم الشعار كبير جدًا."}
        CONFIG["store_name"]=name
        if logo: CONFIG["store_logo_data"]=logo
        save_config(CONFIG)
        self._runtime.cfg["store_name"]=name
        self._runtime._save()
        server_result={"ok":True,"store_name":name,"logo_data":CONFIG.get("store_logo_data","")}
        try:
            rr=requests.put(self._server()+"/api/v27/branding",headers=self._headers(),json={"store_name":name,"logo_data":logo},timeout=8).json()
            if rr.get("ok"): server_result.update(rr)
        except Exception as exc:
            server_result["server_sync_error"]=str(exc)
        return server_result

    def database_status(self):
        self._ensure_auth()
        db_path = Path(__file__).resolve().parents[2] / "pos_v7.db"
        result = {"ok": False, "connected": False, "path": str(db_path), "exists": db_path.exists(), "size_bytes": db_path.stat().st_size if db_path.exists() else 0, "server_url": self._runtime.server_url, "store_name": CONFIG.get("store_name", "")}
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            result.update({"ok": True, "connected": True, "error": ""})
        except Exception as exc:
            result["error"] = str(exc)
        return result

    def verify_audit_chain(self, limit=None):
        self._ensure_auth()
        ok, detail = AuditService.verify_chain(limit=limit)
        return {"ok": bool(ok), "valid": bool(ok), "detail": detail, "checked": int(limit) if limit else None}

    def save_settings(self, patch: dict[str, Any]):
        self._ensure_auth(); allowed = {"store_name","store_address","store_phone","currency","tax_rate","printer_name","receipt_width","auto_print","touch_mode","cash_drawer","branch_id","warehouse_id","server_port","discovery_port"}; changed={}
        for k,v in (patch or {}).items():
            if k in allowed:
                CONFIG[k]=v; changed[k]=v
        save_config(CONFIG)
        try:
            with SessionLocal.begin() as s: AuditService.append(s,self._user.id,"UPDATE_SETTINGS","settings",None,json.dumps(changed,ensure_ascii=False,default=str))
        except Exception: pass
        return {"ok": True, "changed": changed}

    def save_user_permissions(self, user_id: int, permission_codes: list[str]):
        self._ensure_auth()
        allowed={str(x) for x in (permission_codes or [])}
        with SessionLocal.begin() as s:
            u=s.get(User,int(user_id))
            if not u: raise ValueError("المستخدم غير موجود")
            perms=s.scalars(select(Permission).where(Permission.code.in_(allowed))).all() if allowed else []
            u.permissions=list(perms)
            u.permissions_override=True
            s.flush()
        try:
            with SessionLocal.begin() as s: AuditService.append(s,self._user.id,"UPDATE_PERMISSIONS","user",int(user_id),json.dumps(sorted(allowed),ensure_ascii=False))
        except Exception: pass
        return {"ok":True,"user_id":int(user_id),"permissions":sorted(allowed)}

    def execute_task(self, device_id: str, payload: dict):
        self._ensure_auth()
        return requests.post(self._server()+f"/api/v19/control/clients/{device_id}/commands", headers=self._headers(), json={"command":"TASK_EXECUTE","payload":payload or {}}, timeout=8).json()

    def client_control(self):
        self._ensure_auth()
        base=self._server(); h=self._headers()
        data=self._get_json(base + "/api/v27/manager/devices-summary", headers=h, timeout=4, label="Devices summary")
        # Monitoring counters are local and cheap; products are loaded lazily only when a purchase dialog needs them.
        try:
            with SessionLocal() as s:
                pending=int(s.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(["PENDING","FAILED"]))) or 0)
                health=s.scalars(select(HealthCheckLog).order_by(desc(HealthCheckLog.id)).limit(5)).all()
                sync=s.scalars(select(SyncEvent).order_by(desc(SyncEvent.id)).limit(5)).all()
        except Exception:
            pending=0; health=[]; sync=[]
        data["monitoring"]={"queue_pending":pending,"health":[self._health_row(x) for x in health],"sync":[self._sync_row(x) for x in sync]}
        return data

    def products(self):
        self._ensure_auth()
        with SessionLocal() as s:
            return {"products": self._products(s)}


    def client_control_one(self, device_id: str):
        self._ensure_auth(); return requests.get(self._server() + f"/api/v19/control/clients/{device_id}", headers=self._headers(), timeout=6).json()

    def client_control_profile(self, payload: dict[str, Any]):
        self._ensure_auth(); return requests.put(self._server() + f"/api/v19/control/clients/{payload['device_id']}/profile", headers=self._headers(), json=payload, timeout=6).json()

    def client_control_command(self, device_id: str, command: str, payload: dict[str, Any] | None = None):
        self._ensure_auth(); return requests.post(self._server() + f"/api/v19/control/clients/{device_id}/commands", headers=self._headers(), json={"command":command,"payload":payload or {}}, timeout=6).json()

    def usb_save_pricing(self, payload: dict):
        self._ensure_auth(); return requests.post(self._server()+"/api/v17/usb/pricing", headers=self._headers(), json=payload or {}, timeout=6).json()

    def client_runtime(self, device_id: str, payload: dict):
        self._ensure_auth(); return requests.put(self._server() + f"/api/v19/control/clients/{device_id}/runtime", headers=self._headers(), json=payload or {}, timeout=6).json()

    def session_pricing(self):
        self._ensure_auth(); return requests.get(self._server()+"/api/v27/session-pricing", headers=self._headers(), timeout=5).json()

    def save_session_pricing(self, payload: dict):
        self._ensure_auth(); return requests.put(self._server()+"/api/v27/session-pricing", headers=self._headers(), json=payload or {}, timeout=5).json()

    def usb_default_policy(self):
        self._ensure_auth(); return requests.get(self._server()+"/api/v19/usb/default-policy", headers=self._headers(), timeout=6).json()

    def usb_save_default_policy(self, policy: str, sha256_enabled: bool=False):
        self._ensure_auth(); return requests.put(self._server()+"/api/v19/usb/default-policy", headers=self._headers(), json={"policy":policy,"sha256_enabled":bool(sha256_enabled)}, timeout=6).json()

    def client_control_usb_policy(self, device_id: str, policy: str, sha256_enabled: bool=False):
        self._ensure_auth(); return requests.post(self._server() + f"/api/v19/control/clients/{device_id}/usb-policy", headers=self._headers(), json={"policy":policy,"sha256_enabled":bool(sha256_enabled)}, timeout=6).json()

    def rotate_client_token(self, device_id: str):
        self._ensure_auth(); return requests.post(self._server() + f"/api/v19/manager/clients/{device_id}/rotate-token", headers=self._headers(), timeout=6).json()

    def client_latest_snapshot(self, device_id: str):
        self._ensure_auth(); return requests.get(self._server() + f"/api/v19/control/clients/{device_id}/snapshot/latest", headers=self._headers(), timeout=10).json()

    def pick_asset(self, payload=None):
        self._ensure_auth()
        if self._window is None: return {"ok":False,"error":"نافذة Manager غير جاهزة"}
        try:
            import webview
            kind=str((payload or {}).get("kind") or "image").lower()
            if kind == "video":
                file_types=("Video Files (*.mp4;*.webm;*.mov)",)
            else:
                file_types=("Image Files (*.png;*.jpg;*.jpeg;*.webp;*.gif;*.svg)",)
            result=self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=file_types)
            path=result[0] if isinstance(result,(list,tuple)) and result else result
            return {"ok":bool(path),"path":str(path or ""),"name":Path(path).name if path else ""}
        except Exception as exc: return {"ok":False,"error":str(exc)}

    def upload_selected_client_asset(self, device_id: str, path: str):
        self._ensure_auth()
        src=Path(str(path or "")).expanduser()
        if not src.is_file(): return {"ok":False,"error":"الملف غير موجود"}
        raw=src.read_bytes()
        if len(raw)>10*1024*1024: return {"ok":False,"error":"حجم الأصل يتجاوز 10MB"}
        return self.upload_client_asset(device_id, src.name, base64.b64encode(raw).decode("ascii"))

    def upload_client_asset(self, device_id: str, filename: str, data_base64: str):
        self._ensure_auth();
        raw = base64.b64decode(data_base64)
        files={"asset":(Path(filename).name, raw)}
        r=requests.post(self._server() + "/api/v18/manager/client-ui/asset", headers=self._headers(), files=files, timeout=20)
        out=self._json_response(r,"رفع أصل Client")
        if isinstance(out,dict) and str(out.get("url") or "").startswith("/"): out["url"]=self._server().rstrip("/")+out["url"]
        return out

    # ---------- V27.0.4 centralized workspace configuration ----------
    def module_settings(self, module: str):
        self._ensure_auth()
        return requests.get(self._server() + f"/api/v27/module-settings/{module}", headers=self._headers(), timeout=5).json()

    def save_module_settings(self, module: str, payload: dict[str, Any]):
        self._ensure_auth()
        return requests.put(self._server() + f"/api/v27/module-settings/{module}", headers=self._headers(), json=payload or {}, timeout=5).json()

    def game_library(self):
        self._ensure_auth()
        return requests.get(self._server() + "/api/v27/game-library", headers=self._headers(), timeout=6).json()

    def save_game_library_item(self, payload: dict[str, Any]):
        self._ensure_auth()
        return requests.post(self._server() + "/api/v27/game-library", headers=self._headers(), json=payload or {}, timeout=6).json()

    def upload_game_asset(self, filename: str, data_base64: str):
        self._ensure_auth()
        raw=base64.b64decode(data_base64)
        files={"asset":(Path(filename).name, raw)}
        result=requests.post(self._server()+"/api/v18/manager/client-ui/asset", headers=self._headers(), files=files, timeout=20).json()
        if isinstance(result, dict) and str(result.get("url") or "").startswith("/"):
            result["url"] = self._server().rstrip("/") + result["url"]
        return result

    def delete_game_library_item(self, item_id: str):
        self._ensure_auth()
        return requests.delete(self._server() + f"/api/v27/game-library/{item_id}", headers=self._headers(), timeout=6).json()

    def task_library(self):
        self._ensure_auth()
        return requests.get(self._server() + "/api/v27/task-library", headers=self._headers(), timeout=6).json()

    def save_task_library_item(self, payload: dict[str, Any]):
        self._ensure_auth()
        return requests.post(self._server() + "/api/v27/task-library", headers=self._headers(), json=payload or {}, timeout=6).json()

    def delete_task_library_item(self, item_id: str):
        self._ensure_auth()
        return requests.delete(self._server() + f"/api/v27/task-library/{item_id}", headers=self._headers(), timeout=6).json()

    def client_ui(self, device_id: str):
        self._ensure_auth(); return requests.get(self._server() + f"/api/v18/manager/client-ui/{device_id}", headers=self._headers(), timeout=5).json()

    def save_client_ui_profile(self, payload: dict[str, Any]):
        self._ensure_auth(); return requests.put(self._server() + "/api/v18/manager/client-ui/profile", headers=self._headers(), json=payload, timeout=5).json()

    def _json_response(self, response, operation="Server request"):
        try:
            return response.json()
        except ValueError:
            body=(response.text or "").strip()
            detail=f"{operation}: HTTP {response.status_code}"
            if body: detail += f" — {body[:300]}"
            return {"ok":False,"error":detail,"status_code":response.status_code}

    def save_client_ui_profile_global(self, payload: dict[str, Any]):
        self._ensure_auth(); r=requests.put(self._server() + "/api/v18/manager/client-ui/profile/global", headers=self._headers(), json=payload, timeout=8); return self._json_response(r,"حفظ Customize Client")

    def save_client_ui_item(self, payload: dict[str, Any]):
        self._ensure_auth(); return requests.post(self._server() + "/api/v18/manager/client-ui/item", headers=self._headers(), json=payload, timeout=5).json()

    def delete_client_ui_item(self, device_id: str, item_id: int):
        self._ensure_auth(); return requests.delete(self._server() + f"/api/v18/manager/client-ui/{device_id}/item/{int(item_id)}", headers=self._headers(), timeout=5).json()

    def save_client_ui_banner(self, payload: dict[str, Any]):
        self._ensure_auth(); return requests.post(self._server() + "/api/v18/manager/client-ui/banner", headers=self._headers(), json=payload, timeout=5).json()

    def open_webview_docs(self):
        self._ensure_auth(); webbrowser.open(self._server() + "/docs"); return {"ok": True}

    def esports(self):
        self._ensure_auth(); return requests.get(self._server()+"/api/v22/esports", headers=self._headers(), timeout=8).json()

    def esports_save_provider(self,payload):
        self._ensure_auth(); return requests.post(self._server()+"/api/v22/esports/provider", headers=self._headers(), json=payload, timeout=8).json()

    def esports_save_game(self,payload):
        self._ensure_auth(); return requests.post(self._server()+"/api/v22/esports/game", headers=self._headers(), json=payload, timeout=8).json()

    def esports_toggle_game(self,game_id,payload):
        self._ensure_auth(); return requests.patch(self._server()+f"/api/v22/esports/game/{int(game_id)}", headers=self._headers(), json=payload, timeout=8).json()

    def esports_sync_game(self,game_id):
        self._ensure_auth(); return requests.post(self._server()+f"/api/v22/esports/game/{int(game_id)}/sync", headers=self._headers(), timeout=15).json()

    def esports_sync_all(self):
        self._ensure_auth(); r=requests.post(self._server()+"/api/v22/esports/sync-all", headers=self._headers(), timeout=45); return self._json_response(r,"مزامنة Esports")

    # ---------- serializers ----------
    def _products(self, s):
        rows = s.scalars(select(Product).order_by(Product.name)).all()
        return [{"id":p.id,"barcode":p.barcode or "","name":p.name,"price":_dec(p.price),"cost":_dec(p.cost),"stock":_dec(p.stock),"min_stock":_dec(p.min_stock),"unit":p.unit,"active":bool(p.active),"low":_dec(p.stock)<=_dec(p.min_stock)} for p in rows]
    def _sale_row(self,x): return {"id":x.id,"invoice_no":x.invoice_no,"total":_dec(x.total),"paid":_dec(x.paid),"change":_dec(x.change_amount),"status":x.document_status,"payment":x.payment_method,"customer":getattr(x.customer,"name","") if getattr(x,"customer",None) else "","user":getattr(x.user,"username","") if getattr(x,"user",None) else "","created_at":_dt(x.created_at)}
    def _return_row(self,x): return {"id":x.id,"sale_id":x.sale_id,"total":_dec(x.total),"status":x.document_status,"refund_method":x.refund_method,"reason":x.reason,"created_at":_dt(x.created_at)}
    def _purchase_row(self,x): return {"id":x.id,"invoice_no":x.invoice_no,"total":_dec(x.total),"paid":_dec(x.paid),"status":x.document_status,"created_at":_dt(x.created_at)}
    def _shift_row(self,x): return {"id":x.id if x else None,"user":getattr(x.user,"username","") if x else "","opening":_dec(x.opening_cash) if x else 0,"expected":_dec(x.expected_cash) if x else 0,"closing":_dec(x.closing_cash) if x and x.closing_cash is not None else None,"difference":_dec(x.difference) if x and x.difference is not None else None,"status":x.status if x else "CLOSED","opened_at":_dt(x.opened_at) if x else None,"closed_at":_dt(x.closed_at) if x else None}
    def _cash_row(self,x): return {"id":x.id,"shift_id":x.shift_id,"user_id":x.user_id,"type":x.movement_type,"amount":_dec(x.amount),"note":x.note,"created_at":_dt(x.created_at)}
    def _expense_row(self,x): return {"id":x.id,"amount":_dec(x.amount),"category":x.category,"note":x.note,"created_at":_dt(x.created_at),"user_id":x.user_id}
    def _contact_row(self,x): return {"id":x.id,"name":x.name,"phone":x.phone,"address":x.address}
    def _branch_row(self,x): return {"id":x.id,"code":x.code,"name":x.name,"address":x.address,"phone":x.phone,"active":bool(x.active)}
    def _warehouse_row(self,x): return {"id":x.id,"code":x.code,"name":x.name,"branch_id":x.branch_id,"branch":getattr(x.branch,"name","") if x.branch else "","active":bool(x.active)}
    def _stock_row(self,x): return {"id":x.id,"warehouse_id":x.warehouse_id,"warehouse":getattr(x.warehouse,"name","") if x.warehouse else "","product_id":x.product_id,"product":getattr(x.product,"name","") if x.product else "","quantity":_dec(x.quantity),"min_stock":_dec(x.min_stock),"low":_dec(x.quantity)<=_dec(x.min_stock)}
    def _transfer_row(self,x): return {"id":x.id,"transfer_no":x.transfer_no,"from_warehouse":x.from_warehouse_id,"to_warehouse":x.to_warehouse_id,"user_id":x.user_id,"status":x.status,"note":x.note,"created_at":_dt(x.created_at)}
    def _backup_row(self,x): return {"id":x.id,"mode":x.mode,"path":x.path,"status":x.status,"restore_test":x.restore_test_status,"started_at":_dt(x.started_at),"finished_at":_dt(x.finished_at),"error":x.error}
    def _migration_row(self,x): return {"id":x.id,"revision":x.revision,"status":x.status,"backup_path":x.backup_path,"restore_test":x.restore_test_status,"started_at":_dt(x.started_at),"finished_at":_dt(x.finished_at),"details":x.details}
    def _audit_row(self,x): return {"id":x.id,"action":x.action,"entity":x.entity,"entity_id":x.entity_id,"details":x.details,"created_at":_dt(x.created_at),"hash":x.hash_value}
    def _outbox_row(self,x): return {"id":x.id,"event_id":x.event_id,"type":x.event_type,"aggregate":x.aggregate_type,"aggregate_id":x.aggregate_id,"status":x.status,"attempts":x.attempts,"next_attempt_at":_dt(x.next_attempt_at),"last_error":x.last_error,"created_at":_dt(x.created_at)}
    def _health_row(self,x): return {"id":x.id,"component":x.component,"status":x.status,"latency_ms":_dec(x.latency_ms),"details":x.details,"created_at":_dt(x.created_at)}
    def _sync_row(self,x): return {"id":x.id,"source":x.source,"event_type":x.event_type,"status":x.status,"reference_id":x.reference_id,"details":x.details,"created_at":_dt(x.created_at)}
    def _suspended(self,s):
        try:
            from models import SuspendedSale
            rows=s.scalars(select(SuspendedSale).order_by(desc(SuspendedSale.id)).limit(50)).all()
            return [{"id":r.id,"ticket_no":r.ticket_no,"note":r.note,"created_at":_dt(r.created_at)} for r in rows]
        except Exception:
            return []


def main(runtime) -> int:
    try:
        import webview
    except Exception as exc:
        print(f"WebView2 Manager dependency error: {exc}", file=sys.stderr)
        print("ثبت pywebview و Microsoft Edge WebView2 Runtime على جهاز الإدارة.", file=sys.stderr)
        return 10
    html = WEB_UI_DIR / "index.html"
    if not html.is_file():
        raise FileNotFoundError(html)
    api = ManagerWebAPI(runtime)
    try:
        webview.settings["JS_API_MAX_DEPTH"] = 1
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.settings["ALLOW_FILE_URLS"] = True
    except Exception:
        pass
    window = webview.create_window(
        f"{CONFIG.get("store_name", "Manager")} — Manager V27.5.7",
        html.as_uri(),
        js_api=api,
        width=1600,
        height=980,
        min_size=(900, 620),
        resizable=True,
        zoomable=True,
        background_color="#050914",
    )
    api._window = window
    try:
        runtime.start()
    except Exception as exc:
        print(f"[POS MANAGER] background runtime warning: {exc}", file=sys.stderr, flush=True)
    storage_path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "POSProfessionalRuntime" / "WebView2Data"
    storage_path.mkdir(parents=True, exist_ok=True)
    webview.start(gui="edgechromium", debug=False, private_mode=False, storage_path=str(storage_path))
    return 0
