from config import CONFIG
ESC = b"\x1b"
GS = b"\x1d"

def arabic_text(text):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return str(text)

def build_receipt(sale):
    w = int(CONFIG.get("receipt_width", 48))
    def center(value):
        return arabic_text(str(value))[:w].center(w)
    lines = [center(CONFIG.get("store_name", "متجري")), center(CONFIG.get("store_address", ""))]
    if CONFIG.get("store_phone"):
        lines.append(center(CONFIG["store_phone"]))
    lines += ["-" * w, center("فاتورة"), str(sale.invoice_no),
              f"{sale.created_at:%Y-%m-%d %H:%M}", "-" * w]
    for item in sale.items:
        name = arabic_text(item.product.name)[:24]
        lines.append(f"{name:<24}{str(item.quantity):>8}{float(item.subtotal):>14.2f}")
    lines += ["-" * w,
              f"{arabic_text('الإجمالي'):<25}{float(sale.total):>18.2f}",
              f"{arabic_text('المدفوع'):<25}{float(sale.paid):>18.2f}",
              f"{arabic_text('الباقي'):<25}{float(sale.change_amount):>18.2f}",
              center("شكراً لزيارتكم"), "", "", ""]
    return "\n".join(lines)

def _escpos(text, drawer=True):
    data = ESC + b"@" + ESC + b"a" + b"\x01" + text.encode("cp864", "replace") + ESC + b"a" + b"\x00"
    if drawer:
        data += ESC + b"p" + b"\x00" + b"\x19" + b"\xfa"
    return data + GS + b"V" + b"\x00"

def _open_printer():
    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError("مكوّن الطباعة pywin32 غير مثبت. شغّل install.bat ثم أعد التشغيل.") from exc
    name = CONFIG.get("printer_name") or win32print.GetDefaultPrinter()
    return win32print, name

def open_cash_drawer():
    win32print, name = _open_printer()
    handle = win32print.OpenPrinter(name)
    try:
        win32print.StartDocPrinter(handle, 1, ("Cash Drawer", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, ESC + b"p" + b"\x00" + b"\x19" + b"\xfa")
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)

def print_sale(sale):
    win32print, name = _open_printer()
    handle = win32print.OpenPrinter(name)
    try:
        win32print.StartDocPrinter(handle, 1, ("POS Receipt", None, "RAW"))
        win32print.StartPagePrinter(handle)
        win32print.WritePrinter(handle, _escpos(build_receipt(sale), CONFIG.get("cash_drawer", True)))
        win32print.EndPagePrinter(handle)
        win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
