def has_permission(user, code):
    direct = {p.code for p in getattr(user, "permissions", [])}
    if getattr(user, "permissions_override", False):
        return code in direct
    role = getattr(user, "role", None)
    return code in {p.code for p in getattr(role, "permissions", [])}

def require_permission(user, code):
    if not has_permission(user, code):
        raise PermissionError(f"لا تملك الصلاحية: {code}")
