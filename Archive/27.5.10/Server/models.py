from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Numeric, Boolean, DateTime, ForeignKey, Text, LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list["Permission"]] = relationship(secondary="role_permissions", back_populates="roles")

class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    roles: Mapped[list["Role"]] = relationship(secondary="role_permissions", back_populates="permissions")

class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"), primary_key=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    role: Mapped["Role"] = relationship()

class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    branch: Mapped["Branch"] = relationship()

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    barcode: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(180))
    price: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    stock: Mapped[Decimal] = mapped_column(Numeric(12,3), default=0)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(12,3), default=0)
    unit: Mapped[str] = mapped_column(String(30), default="قطعة")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class WarehouseStock(Base):
    __tablename__ = "warehouse_stock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12,3), default=0)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(12,3), default=0)
    warehouse: Mapped["Warehouse"] = relationship()
    product: Mapped["Product"] = relationship()

class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(String(255), default="")

class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(String(255), default="")

class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    discount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    tax: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    paid: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    change_amount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    document_status: Mapped[str] = mapped_column(String(20), default="POSTED", server_default="POSTED", nullable=False)
    client_request_id: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    payment_method: Mapped[str] = mapped_column(String(30), default="نقدي")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["SaleItem"]] = relationship(cascade="all, delete-orphan")
    user: Mapped["User"] = relationship()
    customer: Mapped["Customer"] = relationship()
    branch: Mapped["Branch"] = relationship()
    warehouse: Mapped["Warehouse"] = relationship()

class SaleItem(Base):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12,3))
    price: Mapped[Decimal] = mapped_column(Numeric(12,2))
    cost: Mapped[Decimal] = mapped_column(Numeric(12,2))
    discount: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2))
    product: Mapped["Product"] = relationship()

class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    total: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    paid: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    document_status: Mapped[str] = mapped_column(String(20), default="POSTED", server_default="POSTED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["PurchaseItem"]] = relationship(cascade="all, delete-orphan")

class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12,3))
    cost: Mapped[Decimal] = mapped_column(Numeric(12,2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2))

class Return(Base):
    __tablename__ = "returns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    total: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    document_status: Mapped[str] = mapped_column(String(20), default="POSTED", server_default="POSTED", nullable=False)
    refund_method: Mapped[str] = mapped_column(String(20), default="نقدي", server_default="نقدي", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["ReturnItem"]] = relationship(cascade="all, delete-orphan")

class ReturnItem(Base):
    __tablename__ = "return_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("returns.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12,3))
    price: Mapped[Decimal] = mapped_column(Numeric(12,2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2))

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    movement_type: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12,3))
    reference_type: Mapped[str] = mapped_column(String(30), default="")
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class Shift(Base):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    expected_cash: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    difference: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped["User"] = relationship()

class CashMovement(Base):
    __tablename__ = "cash_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    movement_type: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SuspendedSale(Base):
    __tablename__ = "suspended_sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_no: Mapped[str] = mapped_column(String(50), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class InventoryTransfer(Base):
    __tablename__ = "inventory_transfers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(50), unique=True)
    from_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["InventoryTransferItem"]] = relationship(cascade="all, delete-orphan")

class InventoryTransferItem(Base):
    __tablename__ = "inventory_transfer_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("inventory_transfers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12,3))
    product: Mapped["Product"] = relationship()

class StockCount(Base):
    __tablename__ = "stock_counts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count_no: Mapped[str] = mapped_column(String(50), unique=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="POSTED")
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    items: Mapped[list["StockCountItem"]] = relationship(cascade="all, delete-orphan")

class StockCountItem(Base):
    __tablename__ = "stock_count_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    system_qty: Mapped[Decimal] = mapped_column(Numeric(12,3))
    actual_qty: Mapped[Decimal] = mapped_column(Numeric(12,3))
    difference: Mapped[Decimal] = mapped_column(Numeric(12,3))
    product: Mapped["Product"] = relationship()

class DocumentSequence(Base):
    __tablename__ = "document_sequences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_type: Mapped[str] = mapped_column(String(30), unique=True)
    prefix: Mapped[str] = mapped_column(String(20))
    next_number: Mapped[int] = mapped_column(Integer, default=1)




class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_uuid: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    device_name: Mapped[str] = mapped_column(String(150), nullable=False)
    device_type: Mapped[str] = mapped_column(String(30), default="POS", nullable=False)
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OFFLINE", nullable=False)
    app_version: Mapped[str] = mapped_column(String(30), default="V27", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    branch: Mapped["Branch | None"] = relationship()
    warehouse: Mapped["Warehouse | None"] = relationship()


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    branch_id: Mapped[int | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12,2))
    category: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    previous_hash: Mapped[str] = mapped_column(String(64), default="")
    hash_value: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class BackupRun(Base):
    __tablename__ = "backup_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(30))
    path: Mapped[str] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    restore_test_status: Mapped[str] = mapped_column(String(20), default="NOT_TESTED")
    error: Mapped[str] = mapped_column(Text, default="")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MigrationRun(Base):
    __tablename__ = "migration_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    backup_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    restore_test_status: Mapped[str] = mapped_column(String(20), default="NOT_TESTED", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)

class HealthCheckLog(Base):
    __tablename__ = "health_check_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    component: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(12,3), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class SyncEvent(Base):
    __tablename__ = "sync_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    details: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class USBPolicy(Base):
    __tablename__ = "usb_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    policy: Mapped[str] = mapped_column(String(20), default="ALLOW", server_default="ALLOW")
    sha256_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class USBBillingProfile(Base):
    __tablename__ = "usb_billing_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    per_gb: Mapped[Decimal] = mapped_column(Numeric(12,4), default=1)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(8,3), default=0)
    minimum_charge: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    free_gb: Mapped[Decimal] = mapped_column(Numeric(12,4), default=0)
    free_session_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class USBPriceTier(Base):
    __tablename__ = "usb_price_tiers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("usb_billing_profiles.id"), index=True)
    up_to_gb: Mapped[Decimal | None] = mapped_column(Numeric(12,4), nullable=True)
    price_per_gb: Mapped[Decimal] = mapped_column(Numeric(12,4), default=1)
    profile: Mapped["USBBillingProfile"] = relationship()


class USBSession(Base):
    __tablename__ = "usb_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(80), index=True)
    volume_id: Mapped[str] = mapped_column(String(120), default="")
    volume_label: Mapped[str] = mapped_column(String(180), default="")
    mount_path: Mapped[str] = mapped_column(String(260), default="")
    customer_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="OPEN", server_default="OPEN")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bytes_to_usb: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bytes_from_usb: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    free_session: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, server_default="0")
    tax: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0, server_default="0")


class USBTransferEvent(Base):
    __tablename__ = "usb_transfer_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("usb_sessions.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(80), index=True)
    file_name: Mapped[str] = mapped_column(String(500))
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    direction: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    event_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(30), default="RECORDED")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    sha256_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class USBInvoice(Base):
    __tablename__ = "usb_invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True)
    client_id: Mapped[str] = mapped_column(String(80), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("usb_sessions.id"), unique=True)
    customer_name: Mapped[str] = mapped_column(String(120), default="")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    tax: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12,2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="POSTED", server_default="POSTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

class ClientUIProfile(Base):
    __tablename__ = "client_ui_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    logo_asset: Mapped[str] = mapped_column(String(500), default="")
    background_asset: Mapped[str] = mapped_column(String(500), default="")
    video_asset: Mapped[str] = mapped_column(String(500), default="")
    main_image_asset: Mapped[str] = mapped_column(String(500), default="")
    icon_games: Mapped[str] = mapped_column(String(500), default="")
    icon_apps: Mapped[str] = mapped_column(String(500), default="")
    icon_shop: Mapped[str] = mapped_column(String(500), default="")
    icon_events: Mapped[str] = mapped_column(String(500), default="")
    icon_ads: Mapped[str] = mapped_column(String(500), default="")
    icon_my_files: Mapped[str] = mapped_column(String(500), default="")
    icon_profile: Mapped[str] = mapped_column(String(500), default="")
    accent_color: Mapped[str] = mapped_column(String(40), default="#41d9ff")
    accent_2: Mapped[str] = mapped_column(String(40), default="#a46cff")
    text_color: Mapped[str] = mapped_column(String(40), default="#edf4ff")
    muted_color: Mapped[str] = mapped_column(String(40), default="#9fb1c8")
    layout_mode: Mapped[str] = mapped_column(String(30), default="grid")
    kiosk_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    show_profile: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_games: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_apps: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_shop: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_events: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_ads: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    show_my_files: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    welcome_text: Mapped[str] = mapped_column(String(255), default="اختر ما تريد تشغيله")
    profile_badge: Mapped[str] = mapped_column(String(80), default="PLAYER")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ClientUIItem(Base):
    __tablename__ = "client_ui_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    item_type: Mapped[str] = mapped_column(String(20), default="GAME")
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(String(255), default="")
    icon_asset: Mapped[str] = mapped_column(String(500), default="")
    launch_type: Mapped[str] = mapped_column(String(20), default="EXE")
    target: Mapped[str] = mapped_column(String(1000), default="")
    args: Mapped[str] = mapped_column(String(1000), default="")
    working_dir: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ClientUIBanner(Base):
    __tablename__ = "client_ui_banners"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(180), default="")
    body: Mapped[str] = mapped_column(String(500), default="")
    image_asset: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ClientControlProfile(Base):
    __tablename__ = "client_control_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    room_name: Mapped[str] = mapped_column(String(120), default="")
    console_name: Mapped[str] = mapped_column(String(120), default="")
    screen_monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    retention_hours: Mapped[int] = mapped_column(Integer, default=24, server_default="24")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ClientControlTelemetry(Base):
    __tablename__ = "client_control_telemetry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    cpu_percent: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    cpu_temperature: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    ram_percent: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    ram_used_gb: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    ram_total_gb: Mapped[Decimal | None] = mapped_column(Numeric(12,2), nullable=True)
    ram_speed_mhz: Mapped[Decimal | None] = mapped_column(Numeric(10,2), nullable=True)
    gpu_name: Mapped[str] = mapped_column(String(180), default='')
    gpu_percent: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    gpu_temperature: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    gpu_memory_percent: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    disk_health_percent: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    disk_temperature: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    disk_usage_percent: Mapped[Decimal | None] = mapped_column(Numeric(8,2), nullable=True)
    disks_json: Mapped[str] = mapped_column(Text, default='[]')
    running_apps_json: Mapped[str] = mapped_column(Text, default="[]")
    current_user: Mapped[str] = mapped_column(String(120), default="")
    session_paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    lan_speed_mbps: Mapped[Decimal | None] = mapped_column(Numeric(10,2), nullable=True)
    lan_adapter: Mapped[str] = mapped_column(String(180), default="")


class ClientControlToken(Base):
    __tablename__ = "client_control_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    token_hint: Mapped[str] = mapped_column(String(12), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ClientControlCommand(Base):
    __tablename__ = "client_control_commands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    command: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", server_default="QUEUED")
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class ClientScreenSnapshot(Base):
    __tablename__ = "client_screen_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80), index=True)
    command_id: Mapped[str] = mapped_column(String(80), index=True)
    mime_type: Mapped[str] = mapped_column(String(50), default="image/jpeg")
    image_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)



class EsportsProvider(Base):
    __tablename__ = "esports_providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider_type: Mapped[str] = mapped_column(String(40), default="GENERIC")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    leaderboard_path_template: Mapped[str] = mapped_column(String(500), default="/games/{code}/leaderboard")
    tournament_path_template: Mapped[str] = mapped_column(String(500), default="/games/{code}/tournaments")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

class EsportsGame(Base):
    __tablename__ = "esports_games"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("esports_providers.id"), nullable=True)
    tournament_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    leaderboard_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    leaderboard_path: Mapped[str] = mapped_column(String(500), default="")
    tournament_path: Mapped[str] = mapped_column(String(500), default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(30), default="NEVER")
    last_sync_error: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    provider: Mapped["EsportsProvider | None"] = relationship()

class EsportsLeaderboardEntry(Base):
    __tablename__ = "esports_leaderboard_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("esports_games.id"), index=True)
    external_player_id: Mapped[str] = mapped_column(String(120), default="")
    player_name: Mapped[str] = mapped_column(String(180))
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    matches: Mapped[int] = mapped_column(Integer, default=0)
    region: Mapped[str] = mapped_column(String(80), default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    game: Mapped["EsportsGame"] = relationship()

class EsportsTournament(Base):
    __tablename__ = "esports_tournaments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("esports_games.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(120), default="")
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="UPCOMING")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    game: Mapped["EsportsGame"] = relationship()

class EsportsMatch(Base):
    __tablename__ = "esports_matches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("esports_tournaments.id"), nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(120), default="")
    round_name: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(40), default="SCHEDULED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    participant_json: Mapped[str] = mapped_column(Text, default="[]")
    winner_player_id: Mapped[str] = mapped_column(String(120), default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    tournament: Mapped["EsportsTournament | None"] = relationship()

class EsportsSyncLog(Base):
    __tablename__ = "esports_sync_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("esports_providers.id"), nullable=True, index=True)
    game_id: Mapped[int | None] = mapped_column(ForeignKey("esports_games.id"), nullable=True, index=True)
    sync_type: Mapped[str] = mapped_column(String(30), default="LEADERBOARD")
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class EsportsConfig(Base):
    __tablename__ = "esports_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_name: Mapped[str] = mapped_column(String(160), default="POS Professional Esports")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    default_provider_id: Mapped[int | None] = mapped_column(ForeignKey("esports_providers.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
