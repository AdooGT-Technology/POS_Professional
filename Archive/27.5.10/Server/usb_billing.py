from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select
from models import USBBillingProfile, USBPriceTier

MONEY = Decimal("0.01")
GB = Decimal(1024**3)

def q2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(MONEY, rounding=ROUND_HALF_UP)

def bill_bytes(total_bytes: int, profile: USBBillingProfile, tiers: list[USBPriceTier], free_session: bool = False) -> tuple[Decimal, Decimal, Decimal]:
    if free_session:
        return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    gb = Decimal(max(0, int(total_bytes))) / GB
    billable_gb = max(Decimal("0"), gb - Decimal(profile.free_gb or 0))
    if billable_gb <= 0:
        return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    ordered = sorted(tiers, key=lambda t: Decimal(t.up_to_gb) if t.up_to_gb is not None else Decimal("999999999"))
    subtotal = Decimal("0")
    prev = Decimal("0")
    if ordered:
        for tier in ordered:
            limit = Decimal(tier.up_to_gb) if tier.up_to_gb is not None else billable_gb
            portion = max(Decimal("0"), min(billable_gb, limit) - prev)
            if portion > 0:
                subtotal += portion * Decimal(tier.price_per_gb)
            prev = max(prev, limit)
            if prev >= billable_gb:
                break
        if prev < billable_gb:
            subtotal += (billable_gb - prev) * Decimal(profile.per_gb)
    else:
        subtotal = billable_gb * Decimal(profile.per_gb)
    subtotal = q2(subtotal)
    if subtotal > 0 and Decimal(profile.minimum_charge or 0) > subtotal:
        subtotal = q2(Decimal(profile.minimum_charge))
    tax = q2(subtotal * (Decimal(profile.tax_percent or 0) / Decimal("100")))
    total = q2(subtotal + tax)
    return subtotal, tax, total

def get_active_profile(session):
    profile = session.scalar(select(USBBillingProfile).where(USBBillingProfile.active.is_(True)).order_by(USBBillingProfile.id))
    if profile is None:
        profile = USBBillingProfile(name="Default USB", per_gb=Decimal("1"), tax_percent=Decimal("0"), minimum_charge=Decimal("0"), free_gb=Decimal("0"), free_session_default=False, active=True)
        session.add(profile); session.flush()
    existing={int(Decimal(str(x.up_to_gb))) for x in session.scalars(select(USBPriceTier).where(USBPriceTier.profile_id==profile.id)).all() if x.up_to_gb is not None}
    missing=[USBPriceTier(profile_id=profile.id, up_to_gb=Decimal(gb), price_per_gb=Decimal(str(profile.per_gb or 1))) for gb in range(10,1001,10) if gb not in existing]
    if missing: session.add_all(missing)
    return profile
