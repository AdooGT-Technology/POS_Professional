from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import shutil
import hashlib
import json
import tempfile
import uuid
from sqlalchemy import select, func, desc, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from db import SessionLocal
from models import (
    User, Role, Permission, Branch, Warehouse, Product, WarehouseStock,
    Customer, Supplier, Sale, SaleItem, Purchase, PurchaseItem, Return, ReturnItem,
    StockMovement, Shift, CashMovement, Expense, AuditLog, InventoryTransfer, InventoryTransferItem, StockCount, StockCountItem, DocumentSequence, SuspendedSale, BackupRun, OutboxEvent
)
from security import hash_password, verify_password
from config import CONFIG, BACKUP_DIR

def D(v): return Decimal(str(v))
def money(v): return D(v).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)

class AuthService:
    @staticmethod
    def login(username,password):
        with SessionLocal() as s:
            u=s.scalar(
                select(User)
                .options(selectinload(User.role).selectinload(Role.permissions), selectinload(User.permissions))
                .where(User.username==username,User.active==True)
            )
            return u if u and verify_password(password,u.password_hash) else None

class BaseService:
    @staticmethod
    def permissions(user):
        direct={p.code for p in getattr(user,"permissions",[])}
        return direct if getattr(user,"permissions_override",False) else {p.code for p in user.role.permissions}


class AuditService:
    @staticmethod
    def append(session, user_id, action, entity="", entity_id=None, details=""):
        previous = session.scalar(select(AuditLog).where(AuditLog.hash_value!="").order_by(desc(AuditLog.id)).limit(1))
        previous_hash = previous.hash_value if previous and previous.hash_value else ""
        created = datetime.now()
        payload = {"user_id": user_id, "action": action, "entity": entity, "entity_id": entity_id, "details": details, "created_at": created.isoformat(timespec="microseconds"), "previous_hash": previous_hash}
        digest = hashlib.sha256((previous_hash + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)).encode("utf-8")).hexdigest()
        row = AuditLog(user_id=user_id, action=action, entity=entity, entity_id=entity_id, details=details, previous_hash=previous_hash, hash_value=digest, created_at=created)
        session.add(row)
        return row

    @staticmethod
    def verify_chain(limit=None):
        with SessionLocal() as session:
            rows = session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
        # V8 logs may predate hashing. They remain readable; V9 verification begins
        # at the first hashed record.
        rows = [r for r in rows if r.hash_value]
        if limit:
            rows = rows[-int(limit):]
        previous = ""
        checked = 0
        for row in rows:
            payload = {"user_id": row.user_id, "action": row.action, "entity": row.entity, "entity_id": row.entity_id, "details": row.details or "", "created_at": row.created_at.isoformat(timespec="microseconds") if row.created_at else "", "previous_hash": row.previous_hash or ""}
            expected = hashlib.sha256(((row.previous_hash or "") + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)).encode("utf-8")).hexdigest()
            if checked == 0:
                if row.previous_hash not in ("", None):
                    # The first hashed record may legitimately point to a prior hashed
                    # record that is outside the requested limit.
                    if limit is None:
                        return False, f"بداية سلسلة غير صالحة عند ID={row.id}"
            else:
                if (row.previous_hash or "") != previous:
                    return False, f"انقطاع في سلسلة السجل عند ID={row.id}"
            if row.hash_value != expected:
                return False, f"تغيير غير متوقع في سجل ID={row.id}"
            previous = row.hash_value
            checked += 1
        return True, f"تم التحقق من {checked} سجل V9."

class SequenceService:
    @staticmethod
    def next(document_type, session=None):
        prefix_map={"SALE":"INV","PURCHASE":"PUR","RETURN":"RET","TRANSFER":"TRF","COUNT":"CNT","SUSPEND":"HOLD"}
        own = session is None
        s = session or SessionLocal()
        try:
            seq=s.scalar(select(DocumentSequence).where(DocumentSequence.document_type==document_type).with_for_update())
            if not seq:
                seq=DocumentSequence(document_type=document_type,prefix=prefix_map.get(document_type,document_type),next_number=1)
                s.add(seq);s.flush()
            number=seq.next_number
            seq.next_number += 1
            result=f"{seq.prefix}-{datetime.now():%Y%m%d}-{number:06d}"
            if own:s.commit()
            return result
        finally:
            if own:s.close()

class SuspensionService:
    @staticmethod
    def suspend(user_id, cart, branch_id=None, warehouse_id=None, note=""):
        import json
        with SessionLocal() as s:
            ticket = SequenceService.next("SUSPEND", s)
            s.add(SuspendedSale(ticket_no=ticket, user_id=user_id, branch_id=branch_id,
                                warehouse_id=warehouse_id, payload_json=json.dumps(cart, ensure_ascii=False), note=note))
            s.commit()
            return ticket

    @staticmethod
    def list_open():
        with SessionLocal() as s:
            return s.scalars(select(SuspendedSale).order_by(desc(SuspendedSale.id)).limit(100)).all()

    @staticmethod
    def load(ticket_no):
        import json
        with SessionLocal() as s:
            row = s.scalar(select(SuspendedSale).where(SuspendedSale.ticket_no == ticket_no))
            return (row, json.loads(row.payload_json)) if row else None

    @staticmethod
    def remove(ticket_no):
        with SessionLocal() as s:
            row = s.scalar(select(SuspendedSale).where(SuspendedSale.ticket_no == ticket_no))
            if row:
                s.delete(row)
                s.commit()

class CashDrawerService:
    @staticmethod
    def kick():
        from printer import open_cash_drawer
        return open_cash_drawer()

class InvoiceService:
    @staticmethod
    def get(invoice_no):
        from sqlalchemy.orm import selectinload
        with SessionLocal() as s:
            return s.scalar(select(Sale).options(selectinload(Sale.items).selectinload(SaleItem.product)).where(Sale.invoice_no == invoice_no))

class InventoryService:
    @staticmethod
    def warehouses():
        return MasterService.warehouses()

    @staticmethod
    def transfer(user_id, from_warehouse_id, to_warehouse_id, items, note=""):
        if int(from_warehouse_id)==int(to_warehouse_id):
            raise ValueError("المخزن المصدر والوجهة يجب أن يكونا مختلفين.")
        with SessionLocal() as s:
            tr=InventoryTransfer(
                transfer_no=SequenceService.next("TRANSFER", s),
                from_warehouse_id=int(from_warehouse_id),
                to_warehouse_id=int(to_warehouse_id),
                user_id=user_id,status="COMPLETED",note=note
            ); s.add(tr); s.flush()
            for item in items:
                pid=int(item["product_id"]); qty=D(item["quantity"])
                if qty<=0: raise ValueError("كمية التحويل يجب أن تكون أكبر من صفر.")
                src=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==pid,WarehouseStock.warehouse_id==int(from_warehouse_id)))
                if not src or src.quantity<qty: raise ValueError("المخزون غير كافٍ في المخزن المصدر.")
                dst=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==pid,WarehouseStock.warehouse_id==int(to_warehouse_id)))
                if not dst:
                    p=s.get(Product,pid); dst=WarehouseStock(warehouse_id=int(to_warehouse_id),product_id=pid,quantity=0,min_stock=p.min_stock if p else 0); s.add(dst)
                src.quantity-=qty; dst.quantity+=qty
                s.add(InventoryTransferItem(transfer_id=tr.id,product_id=pid,quantity=qty))
                s.add(StockMovement(product_id=pid,user_id=user_id,warehouse_id=int(from_warehouse_id),movement_type="TRANSFER_OUT",quantity=-qty,reference_type="TRANSFER",reference_id=tr.id))
                s.add(StockMovement(product_id=pid,user_id=user_id,warehouse_id=int(to_warehouse_id),movement_type="TRANSFER_IN",quantity=qty,reference_type="TRANSFER",reference_id=tr.id))
            s.commit(); return tr

    @staticmethod
    def count_and_adjust(user_id, warehouse_id, items, note=""):
        with SessionLocal() as s:
            cnt=StockCount(count_no=SequenceService.next("COUNT", s),warehouse_id=int(warehouse_id),user_id=user_id,status="POSTED",note=note)
            s.add(cnt); s.flush()
            for item in items:
                pid=int(item["product_id"]);actual=D(item["actual_qty"])
                ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==pid,WarehouseStock.warehouse_id==int(warehouse_id)))
                system=D(ws.quantity if ws else 0); diff=actual-system
                if diff!=0:
                    if not ws:
                        p=s.get(Product,pid); ws=WarehouseStock(warehouse_id=int(warehouse_id),product_id=pid,quantity=0,min_stock=p.min_stock if p else 0); s.add(ws)
                    ws.quantity=actual
                    s.add(StockMovement(product_id=pid,user_id=user_id,warehouse_id=int(warehouse_id),movement_type="COUNT_ADJUST",quantity=diff,reference_type="COUNT",reference_id=cnt.id,note=note))
                s.add(StockCountItem(count_id=cnt.id,product_id=pid,system_qty=system,actual_qty=actual,difference=diff))
            s.commit(); return cnt

class CashService:
    @staticmethod
    def daily_summary(shift_id):
        with SessionLocal() as s:
            sh=s.get(Shift,shift_id)
            if not sh:return None
            cash_sales=s.scalar(select(func.coalesce(func.sum(Sale.total),0)).where(Sale.shift_id==shift_id,Sale.payment_method=="نقدي")) or 0
            card_sales=s.scalar(select(func.coalesce(func.sum(Sale.total),0)).where(Sale.shift_id==shift_id,Sale.payment_method=="بطاقة")) or 0
            transfer_sales=s.scalar(select(func.coalesce(func.sum(Sale.total),0)).where(Sale.shift_id==shift_id,Sale.payment_method=="تحويل")) or 0
            returns=s.scalar(select(func.coalesce(func.sum(Return.total),0)).join(Sale,Return.sale_id==Sale.id).where(Sale.shift_id==shift_id)) or 0
            cash_in=s.scalar(select(func.coalesce(func.sum(CashMovement.amount),0)).where(CashMovement.shift_id==shift_id,CashMovement.movement_type.in_(["OPENING","IN"]))) or 0
            cash_out=s.scalar(select(func.coalesce(func.sum(CashMovement.amount),0)).where(CashMovement.shift_id==shift_id,CashMovement.movement_type=="OUT")) or 0
            return {
                "opening":D(sh.opening_cash),"cash_sales":D(cash_sales),"card_sales":D(card_sales),
                "transfer_sales":D(transfer_sales),"returns":D(returns),"cash_in":D(cash_in),
                "cash_out":D(cash_out),"expected":ShiftService.expected_cash(shift_id)
            }

class MasterService:
    @staticmethod
    def branches():
        with SessionLocal() as s:return s.scalars(select(Branch).where(Branch.active==True).order_by(Branch.name)).all()
    @staticmethod
    def warehouses(branch_id=None):
        with SessionLocal() as s:
            q=select(Warehouse).where(Warehouse.active==True)
            if branch_id:q=q.where(Warehouse.branch_id==branch_id)
            return s.scalars(q.order_by(Warehouse.name)).all()
    @staticmethod
    def save_branch(code,name,address="",phone="",branch_id=None):
        with SessionLocal() as s:
            b=s.get(Branch,branch_id) if branch_id else Branch()
            b.code=code;b.name=name;b.address=address;b.phone=phone;b.active=True
            s.add(b);s.commit();return b.id
    @staticmethod
    def save_warehouse(code,name,branch_id,warehouse_id=None):
        with SessionLocal() as s:
            w=s.get(Warehouse,warehouse_id) if warehouse_id else Warehouse()
            w.code=code;w.name=name;w.branch_id=int(branch_id);w.active=True
            s.add(w);s.commit();return w.id

class ProductService:
    @staticmethod
    def search(text=""):
        with SessionLocal() as s:
            q=select(Product).where(Product.active==True)
            if text:q=q.where((Product.name.like(f"%{text}%"))|(Product.barcode==text))
            return s.scalars(q.order_by(Product.name)).all()
    @staticmethod
    def get_stock(product_id,warehouse_id=None):
        with SessionLocal() as s:
            if warehouse_id:
                ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==product_id,WarehouseStock.warehouse_id==warehouse_id))
                return D(ws.quantity) if ws else D(0)
            p=s.get(Product,product_id);return D(p.stock if p else 0)
    @staticmethod
    def save(data,product_id=None):
        with SessionLocal() as s:
            p=s.get(Product,product_id) if product_id else Product()
            p.barcode=data.get("barcode") or None;p.name=data["name"];p.price=D(data["price"])
            p.cost=D(data.get("cost",0));p.stock=D(data.get("stock",0));p.min_stock=D(data.get("min_stock",0))
            p.unit=data.get("unit","قطعة");p.active=True
            s.add(p);s.flush()
            wh_id=data.get("warehouse_id")
            if wh_id is not None:
                ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==p.id,WarehouseStock.warehouse_id==int(wh_id)))
                if not ws:ws=WarehouseStock(warehouse_id=int(wh_id),product_id=p.id,quantity=0,min_stock=p.min_stock);s.add(ws)
                ws.quantity=D(data.get("warehouse_stock",data.get("stock",0)));ws.min_stock=p.min_stock
            s.commit();return p.id
    @staticmethod
    def low_stock(warehouse_id=None):
        with SessionLocal() as s:
            if warehouse_id:
                return s.scalars(select(WarehouseStock).where(WarehouseStock.warehouse_id==warehouse_id,WarehouseStock.quantity<=WarehouseStock.min_stock).order_by(WarehouseStock.quantity)).all()
            return s.scalars(select(Product).where(Product.active==True,Product.stock<=Product.min_stock).order_by(Product.stock)).all()

class ShiftService:
    @staticmethod
    def open_shift(user_id,branch_id,warehouse_id,opening_cash):
        with SessionLocal() as s:
            open_existing=s.scalar(select(Shift).where(Shift.user_id==user_id,Shift.status=="OPEN"))
            if open_existing:raise ValueError("لديك وردية مفتوحة بالفعل.")
            sh=Shift(user_id=user_id,branch_id=branch_id,warehouse_id=warehouse_id,opening_cash=money(opening_cash),status="OPEN")
            s.add(sh);s.flush();s.add(CashMovement(shift_id=sh.id,user_id=user_id,movement_type="OPENING",amount=money(opening_cash),note="رصيد افتتاحي"))
            s.commit();return sh
    @staticmethod
    def current(user_id):
        with SessionLocal() as s:return s.scalar(select(Shift).where(Shift.user_id==user_id,Shift.status=="OPEN").order_by(desc(Shift.id)))
    @staticmethod
    def expected_cash(shift_id):
        with SessionLocal() as s:
            sh=s.get(Shift,shift_id)
            sales=s.scalar(select(func.coalesce(func.sum(Sale.paid-Sale.change_amount),0)).where(Sale.shift_id==shift_id,Sale.payment_method=="نقدي")) or 0
            cash_in=s.scalar(select(func.coalesce(func.sum(CashMovement.amount),0)).where(CashMovement.shift_id==shift_id,CashMovement.movement_type.in_(["OPENING","IN"]))) or 0
            cash_out=s.scalar(select(func.coalesce(func.sum(CashMovement.amount),0)).where(CashMovement.shift_id==shift_id,CashMovement.movement_type=="OUT")) or 0
            returns=s.scalar(select(func.coalesce(func.sum(Return.total),0)).join(Sale,Return.sale_id==Sale.id).where(Sale.shift_id==shift_id)) or 0
            return money(D(sh.opening_cash)+D(sales)+D(cash_in)-D(cash_out)-D(returns))
    @staticmethod
    def cash_movement(user_id,shift_id,movement_type,amount,note=""):
        with SessionLocal() as s:
            s.add(CashMovement(shift_id=shift_id,user_id=user_id,movement_type=movement_type,amount=money(amount),note=note));s.commit()
    @staticmethod
    def close_shift(user_id,shift_id,closing_cash):
        with SessionLocal() as s:
            sh=s.get(Shift,shift_id)
            if not sh or sh.status!="OPEN":raise ValueError("الوردية غير مفتوحة.")
            expected=ShiftService.expected_cash(shift_id);actual=money(closing_cash)
            sh.closing_cash=actual;sh.expected_cash=expected;sh.difference=money(actual-expected);sh.status="CLOSED";sh.closed_at=datetime.now()
            AuditService.append(s,user_id,"CLOSE_SHIFT","Shift",sh.id,f"expected={expected};actual={actual}")
            s.commit();return sh

class OutboxService:
    @staticmethod
    def enqueue(session, event_type, aggregate_type, aggregate_id=None, payload=None, idempotency_key=None):
        import json
        payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True, default=str)
        if idempotency_key:
            existing=session.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key==idempotency_key))
            if existing:
                return existing
        row=OutboxEvent(event_id=str(uuid.uuid4()), event_type=event_type, aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id, payload_json=payload_json, idempotency_key=idempotency_key,
                        status="PENDING", attempts=0, next_attempt_at=None)
        session.add(row);session.flush();return row

    @staticmethod
    def due(limit=100):
        from datetime import datetime
        with SessionLocal() as s:
            return s.scalars(select(OutboxEvent).where(OutboxEvent.status.in_(("PENDING","FAILED")),
                (OutboxEvent.next_attempt_at.is_(None)) | (OutboxEvent.next_attempt_at<=datetime.now()))
                .order_by(OutboxEvent.id).limit(int(limit))).all()

    @staticmethod
    def mark_sent(event_id):
        with SessionLocal.begin() as s:
            row=s.scalar(select(OutboxEvent).where(OutboxEvent.event_id==event_id))
            if not row:return False
            row.status="SENT";row.sent_at=datetime.now();return True

    @staticmethod
    def mark_retry(event_id, error, base_seconds=None, max_attempts=None):
        base=int(base_seconds or CONFIG.get("outbox_backoff_seconds",5))
        max_tries=int(max_attempts or CONFIG.get("outbox_max_attempts",8))
        with SessionLocal.begin() as s:
            row=s.scalar(select(OutboxEvent).where(OutboxEvent.event_id==event_id))
            if not row:return False
            row.attempts=int(row.attempts or 0)+1
            row.last_error=str(error)[:4000]
            if row.attempts>=max_tries:
                row.status="FAILED";row.next_attempt_at=None
            else:
                row.status="FAILED"
                row.next_attempt_at=datetime.now()+timedelta(seconds=base*(2**max(0,row.attempts-1)))
            return True

    @staticmethod
    def requeue_failed(limit=100):
        changed=0
        with SessionLocal.begin() as s:
            rows=s.scalars(select(OutboxEvent).where(OutboxEvent.status=="FAILED").order_by(OutboxEvent.id).limit(int(limit))).all()
            for row in rows:
                row.status="PENDING";row.next_attempt_at=None;changed+=1
        return changed

    @staticmethod
    def summary():
        from sqlalchemy import func
        with SessionLocal() as s:
            rows=s.execute(select(OutboxEvent.status,func.count(OutboxEvent.id)).group_by(OutboxEvent.status)).all()
            return {str(status):int(count) for status,count in rows}

class SalesService:
    @staticmethod
    def create(user_id,cart,discount=0,payment_method="نقدي",paid=0,customer_id=None,tax_rate=0,branch_id=None,warehouse_id=None,client_request_id=None):
        discount=money(discount);paid=money(paid)
        request_id=(str(client_request_id).strip() if client_request_id else None) or None
        try:
            with SessionLocal.begin() as s:
                if request_id:
                    old=s.scalar(select(Sale).where(Sale.client_request_id==request_id))
                    if old:
                        return old
                shift=s.scalar(select(Shift).where(Shift.user_id==user_id,Shift.status=="OPEN")) if payment_method=="نقدي" else None
                if payment_method=="نقدي" and not shift:raise ValueError("افتح وردية قبل البيع النقدي.")
                subtotal=D(0);rows=[]
                for item in cart:
                    p=s.get(Product,int(item["product_id"]))
                    if not p or not p.active:raise ValueError("يوجد منتج غير صالح.")
                    qty=D(item["quantity"]);price=money(item.get("price",p.price))
                    if qty<=0:raise ValueError(f"الكمية غير صالحة: {p.name}")
                    if warehouse_id:
                        ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==p.id,WarehouseStock.warehouse_id==warehouse_id))
                        if not ws or ws.quantity<qty:raise ValueError(f"المخزون غير كافٍ: {p.name}")
                    elif p.stock<qty:raise ValueError(f"المخزون غير كافٍ: {p.name}")
                    line=money(price*qty);subtotal+=line;rows.append((p,qty,price,line))
                taxable=max(D(0),subtotal-discount);tax=money(taxable*D(tax_rate)/D(100));total=money(taxable+tax)
                if paid<total:raise ValueError("المدفوع أقل من الإجمالي.")
                change=money(paid-total);invoice=SequenceService.next("SALE", s)
                sale=Sale(invoice_no=invoice,branch_id=branch_id,warehouse_id=warehouse_id,customer_id=customer_id,user_id=user_id,shift_id=shift.id if shift else None,
                          subtotal=subtotal,discount=discount,tax=tax,total=total,paid=paid,change_amount=change,payment_method=payment_method,document_status="POSTED",client_request_id=request_id)
                s.add(sale);s.flush()
                for p,qty,price,line in rows:
                    s.add(SaleItem(sale_id=sale.id,product_id=p.id,quantity=qty,price=price,cost=p.cost,subtotal=line))
                    if warehouse_id:
                        ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==p.id,WarehouseStock.warehouse_id==warehouse_id));ws.quantity-=qty
                    else:p.stock-=qty
                    s.add(StockMovement(product_id=p.id,user_id=user_id,warehouse_id=warehouse_id,movement_type="SALE",quantity=-qty,reference_type="SALE",reference_id=sale.id))
                AuditService.append(s,user_id,"CREATE_SALE","Sale",sale.id,invoice)
                OutboxService.enqueue(s,"SALE_CREATED","Sale",sale.id,{"invoice_no":invoice,"total":str(total),"user_id":user_id},idempotency_key=request_id)
                sale_id=sale.id
            return _get_sale(invoice)
        except IntegrityError:
            if request_id:
                with SessionLocal() as s:
                    old=s.scalar(select(Sale).where(Sale.client_request_id==request_id))
                if old:
                    return _get_sale(old.invoice_no)
            raise

class ReturnService:
    @staticmethod
    def create(user_id,invoice,items,reason="",warehouse_id=None,refund_method="نقدي"):
        with SessionLocal() as s:
            sale=s.scalar(select(Sale).where(Sale.invoice_no==invoice))
            if not sale:raise ValueError("الفاتورة غير موجودة.")
            returned={}
            previous=s.scalars(select(ReturnItem).join(Return).where(Return.sale_id==sale.id)).all()
            for r in previous:returned[r.product_id]=returned.get(r.product_id,D(0))+r.quantity
            total=D(0);valid=[]
            for item in items:
                si=s.scalar(select(SaleItem).where(SaleItem.sale_id==sale.id,SaleItem.product_id==int(item["product_id"])))
                qty=D(item["quantity"])
                if not si or qty<=0 or qty>si.quantity-returned.get(si.product_id,D(0)):raise ValueError("كمية المرتجع غير صالحة.")
                sub=money(qty*si.price);total+=sub;valid.append((si,qty,sub))
            ret=Return(sale_id=sale.id,user_id=user_id,warehouse_id=warehouse_id,reason=reason,total=money(total),document_status="POSTED",refund_method=refund_method);s.add(ret);s.flush()
            for si,qty,sub in valid:
                s.add(ReturnItem(return_id=ret.id,product_id=si.product_id,quantity=qty,price=si.price,subtotal=sub))
                p=s.get(Product,si.product_id)
                if warehouse_id:
                    ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==p.id,WarehouseStock.warehouse_id==warehouse_id))
                    if not ws:ws=WarehouseStock(warehouse_id=warehouse_id,product_id=p.id,quantity=0,min_stock=p.min_stock);s.add(ws)
                    ws.quantity+=qty
                else:p.stock+=qty
                s.add(StockMovement(product_id=p.id,user_id=user_id,warehouse_id=warehouse_id,movement_type="RETURN",quantity=qty,reference_type="RETURN",reference_id=ret.id))
            if refund_method=="نقدي":
                sh=s.scalar(select(Shift).where(Shift.user_id==user_id,Shift.status=="OPEN").order_by(desc(Shift.id)))
                if not sh: raise ValueError("افتح وردية قبل رد المبلغ النقدي.")
                s.add(CashMovement(shift_id=sh.id,user_id=user_id,movement_type="OUT",amount=money(total),note=f"مرتجع نقدي {invoice}"))
            AuditService.append(s,user_id,"CREATE_RETURN","Return",ret.id,f"{invoice}|refund={refund_method}")
            s.commit();return ret

class ReportService:
    @staticmethod
    def sales_summary(d1,d2,branch_id=None,warehouse_id=None):
        start=datetime.combine(d1,time.min);end=datetime.combine(d2,time.max)
        with SessionLocal() as s:
            q=select(func.count(Sale.id),func.coalesce(func.sum(Sale.subtotal),0),func.coalesce(func.sum(Sale.discount),0),func.coalesce(func.sum(Sale.tax),0),func.coalesce(func.sum(Sale.total),0)).where(Sale.created_at.between(start,end))
            if branch_id:q=q.where(Sale.branch_id==branch_id)
            if warehouse_id:q=q.where(Sale.warehouse_id==warehouse_id)
            return s.execute(q).one()
    @staticmethod
    def profit(d1,d2,branch_id=None):
        start=datetime.combine(d1,time.min);end=datetime.combine(d2,time.max)
        with SessionLocal() as s:
            q=select(func.coalesce(func.sum(SaleItem.subtotal),0),func.coalesce(func.sum(SaleItem.cost*SaleItem.quantity),0)).join(Sale).where(Sale.created_at.between(start,end))
            if branch_id:q=q.where(Sale.branch_id==branch_id)
            rev,cost=s.execute(q).one()
            ret=s.scalar(select(func.coalesce(func.sum(ReturnItem.subtotal),0)).join(Return).join(Sale).where(Return.created_at.between(start,end))) or 0
            return money(D(rev or 0)-D(cost or 0)-D(ret or 0))
    @staticmethod
    def top_products(d1,d2,limit=20):
        start=datetime.combine(d1,time.min);end=datetime.combine(d2,time.max)
        with SessionLocal() as s:
            q=select(Product.name,func.sum(SaleItem.quantity).label("qty"),func.sum(SaleItem.subtotal).label("amount")).join(SaleItem).join(Sale).where(Sale.created_at.between(start,end)).group_by(Product.id,Product.name).order_by(desc("qty")).limit(limit)
            return s.execute(q).all()
    @staticmethod
    def inventory(warehouse_id=None):
        with SessionLocal() as s:
            if warehouse_id:
                q=select(Product.name,WarehouseStock.quantity,WarehouseStock.min_stock).join(WarehouseStock,WarehouseStock.product_id==Product.id).where(WarehouseStock.warehouse_id==warehouse_id).order_by(Product.name)
                return s.execute(q).all()
            return s.execute(select(Product.name,Product.stock,Product.min_stock).order_by(Product.name)).all()

class UserService:
    @staticmethod
    def users():
        with SessionLocal() as s:return s.scalars(select(User).options(selectinload(User.role)).order_by(User.username)).all()
    @staticmethod
    def roles():
        with SessionLocal() as s:return s.scalars(select(Role).order_by(Role.name)).all()
    @staticmethod
    def save(username,full_name,password,role_id,active=True,user_id=None):
        with SessionLocal() as s:
            u=s.get(User,user_id) if user_id else User()
            u.username=username;u.full_name=full_name;u.role_id=int(role_id);u.active=active
            if password:u.password_hash=hash_password(password)
            s.add(u);s.commit();return u.id

class ExpenseService:
    @staticmethod
    def add(user_id,amount,category,note="",branch_id=None):
        with SessionLocal() as s:s.add(Expense(user_id=user_id,amount=money(amount),category=category,note=note,branch_id=branch_id));s.commit()



class CentralBackupService:
    @staticmethod
    def _sqlite_source():
        url = CONFIG["database_url"]
        if not url.startswith("sqlite:///"):
            return None
        src = Path(url.replace("sqlite:///", "", 1))
        return src if src.is_absolute() else Path(__file__).resolve().parent / src

    @staticmethod
    def run():
        import os, subprocess, urllib.parse as up
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        out=Path(CONFIG.get("backup_dir","backups"));out.mkdir(parents=True,exist_ok=True)
        url=CONFIG["database_url"]
        if url.startswith("sqlite:///"):
            src=CentralBackupService._sqlite_source()
            if not src or not src.exists(): raise ValueError("ملف قاعدة البيانات غير موجود بعد.")
            dst=out/f"sqlite_{stamp}.db"
            # SQLite backup API creates a consistent snapshot even while the
            # application has the database open.
            import sqlite3
            source=sqlite3.connect(src)
            target=sqlite3.connect(dst)
            try:
                source.backup(target)
                target.commit()
            finally:
                target.close();source.close()
            return dst
        if url.startswith("mysql"):
            u=up.urlparse(url);dump=CONFIG.get("mysql_dump_path") or "mysqldump";dst=out/f"mysql_{stamp}.sql"
            env=os.environ.copy();env["MYSQL_PWD"]=u.password or ""
            cmd=[dump,"-h",u.hostname or "localhost","-P",str(u.port or 3306),"-u",u.username or "","--single-transaction","--routines","--triggers",u.path.lstrip("/")]
            try:
                with dst.open("wb") as f: subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.PIPE,check=True)
            except FileNotFoundError as exc: raise ValueError("mysqldump غير موجود. عيّن mysql_dump_path أو أضفه إلى PATH.") from exc
            return dst
        if url.startswith("mssql+pyodbc://"):
            u=up.urlparse(url);db_name=u.path.lstrip("/");dst=out/f"sqlserver_{stamp}.bak";script=out/f"sqlserver_{stamp}_backup.sql"
            script.write_text(f"BACKUP DATABASE [{db_name}] TO DISK = N'{str(dst).replace(chr(39),chr(39)*2)}' WITH INIT;",encoding="utf-8")
            return script
        raise ValueError("نوع قاعدة البيانات غير مدعوم.")

    @staticmethod
    def run_safely():
        started=datetime.now();mode="";path="";status="FAILED";restore="FAIL";error=""
        try:
            path_obj=CentralBackupService.run();path=str(path_obj)
            url=CONFIG["database_url"]
            mode="sqlite" if url.startswith("sqlite:///") else ("mysql" if url.startswith("mysql") else "sqlserver")
            if url.startswith("sqlite:///"):
                import sqlite3
                with tempfile.TemporaryDirectory(prefix="pos_restore_") as td:
                    probe=Path(td)/Path(path).name
                    shutil.copy2(path,probe)
                    con=sqlite3.connect(probe);result=con.execute("PRAGMA integrity_check").fetchone()[0];con.close()
                    restore="PASS" if result=="ok" else "FAIL"
            else:
                restore="NOT_TESTED"
            status="SUCCESS"
            return_path=Path(path)
        except Exception as exc:
            error=str(exc);raise
        finally:
            try:
                with SessionLocal.begin() as s:
                    s.add(BackupRun(mode=mode,path=path,started_at=started,finished_at=datetime.now(),status=status,restore_test_status=restore,error=error))
            except Exception:
                pass
        return return_path

class BackupService:
    @staticmethod
    def backup():
        return CentralBackupService.run()

class BackupScheduler:
    @staticmethod
    def start():
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler=BackgroundScheduler()
        hours=float(CONFIG.get("backup_schedule_hours",24))
        scheduler.add_job(CentralBackupService.run_safely,"interval",hours=max(0.1,hours),id="daily_backup",replace_existing=True)
        scheduler.start()
        return scheduler


# Compatibility / purchasing / sales lookup
def _get_sale(invoice):
    from sqlalchemy.orm import selectinload
    with SessionLocal() as s:
        return s.scalar(
            select(Sale).options(
                selectinload(Sale.items).selectinload(SaleItem.product)
            ).where(Sale.invoice_no==invoice)
        )
SalesService.get = staticmethod(_get_sale)

class PurchaseService:
    @staticmethod
    def create(user_id,items,supplier_id=None,paid=0,branch_id=None,warehouse_id=None):
        with SessionLocal() as s:
            total=D(0); rows=[]
            for item in items:
                p=s.get(Product,int(item["product_id"]));qty=D(item["quantity"]);cost=money(item["cost"])
                if not p or qty<=0:raise ValueError("بيانات شراء غير صالحة.")
                sub=money(qty*cost);total+=sub;rows.append((p,qty,cost,sub))
            inv=SequenceService.next("PURCHASE", s)
            pu=Purchase(invoice_no=inv,branch_id=branch_id,warehouse_id=warehouse_id,supplier_id=supplier_id,user_id=user_id,total=money(total),paid=money(paid),document_status="POSTED")
            s.add(pu);s.flush()
            for p,qty,cost,sub in rows:
                s.add(PurchaseItem(purchase_id=pu.id,product_id=p.id,quantity=qty,cost=cost,subtotal=sub))
                if warehouse_id:
                    ws=s.scalar(select(WarehouseStock).where(WarehouseStock.product_id==p.id,WarehouseStock.warehouse_id==warehouse_id))
                    if not ws:ws=WarehouseStock(warehouse_id=warehouse_id,product_id=p.id,quantity=0,min_stock=p.min_stock);s.add(ws)
                    ws.quantity+=qty
                else:p.stock+=qty
                s.add(StockMovement(product_id=p.id,user_id=user_id,warehouse_id=warehouse_id,movement_type="PURCHASE",quantity=qty,reference_type="PURCHASE",reference_id=pu.id))
            s.commit();return pu
