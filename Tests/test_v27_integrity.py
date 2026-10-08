from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_single_version_identity():
    assert (ROOT/'VERSION.txt').read_text().strip()=='27.5.7'
def test_no_legacy_manager_launcher():
    assert not (ROOT/'Manager'/'run_manager_legacy.bat').exists()
def test_no_duplicate_workspace_menu_labels():
    text=(ROOT/'Manager'/'manager_app'/'web_manager.py').read_text(encoding='utf-8')
    assert 'مركز الأجهزة V13' not in text and 'مركز التشغيل V14' not in text and 'اتصال الجهاز V12' not in text
def test_required_v27_files():
    assert (ROOT/'Manager/manager_app/web_manager.py').exists()
    assert not (ROOT/'Server'/'v27_routes.py').exists()
    assert not (ROOT/'Server'/'diskless_v27_service.py').exists()


def test_manager_nav_click_handler_declares_nav_reference():
    text=(ROOT/'Manager'/'manager_app'/'webui'/'app.js').read_text(encoding='utf-8')
    assert "const nav=e.target.closest('.nav-item')" in text
    assert "if(nav)return loadModule(nav.dataset.module)" in text



def test_v2721_regression_recovery():
    models=(ROOT/'Server'/'models.py').read_text(encoding='utf-8')
    assert 'customer: Mapped["Customer"] = relationship()' in models
    js=(ROOT/'Manager'/'manager_app'/'webui'/'app.js').read_text(encoding='utf-8')
    assert 'const Kpi=kpi;' not in js
    assert 'function boot()' in js
    assert 'function kpi(' in js
    assert "window.addEventListener('pywebviewready',boot)" in js
    assert "action==='game-add'" in js
    assert 'uploadCustomAsset' in js
    wm=(ROOT/'Manager'/'manager_app'/'web_manager.py').read_text(encoding='utf-8')
    assert 'sale_options' in wm and 'hasattr(Sale, "customer")' in wm


def test_dashboard_removed_from_manager_and_server():
    wm=(ROOT/'Manager'/'manager_app'/'web_manager.py').read_text(encoding='utf-8')
    js=(ROOT/'Manager'/'manager_app'/'webui'/'app.js').read_text(encoding='utf-8')
    server=(ROOT/'Server'/'server_app'/'server.py').read_text(encoding='utf-8')
    assert 'def dashboard(' not in wm and "m==='dashboard'" not in js and 'SERVER_ADMIN_HTML' not in server

def test_v2725_telemetry_user_permissions_and_workspaces():
    models=(ROOT/'Server'/'models.py').read_text(encoding='utf-8')
    assert 'ram_speed_mhz' in models
    mm=(ROOT/'Manager'/'models.py').read_text(encoding='utf-8')
    assert 'user_permissions' in mm
    ui=(ROOT/'Manager'/'manager_app'/'webui'/'app.js').read_text(encoding='utf-8')
    assert 'Gizmo-style User & Permission Manager' in ui
    assert 'HARDWARE MONITOR' in ui and 'GIZMO-STYLE GAME MANAGEMENT' in ui and 'GIZMO-STYLE TASK AUTOMATION' in ui and 'GIZMO-STYLE CLIENT DESIGNER' in ui
    assert 'icon_games' in ui and 'icon_profile' in models


def test_v2733_manager_client_control_and_lan():
    js=(ROOT/'Manager'/'manager_app'/'webui'/'app.js').read_text(encoding='utf-8')
    assert 'function renderClientControl(' in js
    assert 'data-control-command' in js
    assert 'function lanRing(' in js
    assert 'lan-good' in js and 'lan-warn' in js
    assert 'function bindLivePreview(' in js and 'syncClientLivePreview' in js
    client=(ROOT/'Client'/'client_app'/'webui'/'index.html').read_text(encoding='utf-8')
    assert 'id="admin-settings-button"' not in client
    assert 'id="admin-panel"' not in client
    assert 'إعدادات الإدارة منفصلة عن واجهة العميل' not in client
    assert 'V27.5.7' in client
    models=(ROOT/'Server'/'models.py').read_text(encoding='utf-8')
    assert 'lan_speed_mbps' in models and 'lan_adapter' in models
    agent=(ROOT/'Client'/'client_app'/'agent.py').read_text(encoding='utf-8')
    assert 'def _lan_stats' in agent and 'lan_speed_mbps' in agent

def test_v2733_database_center_and_usb_tiers():
    js=(ROOT/'Manager'/'manager_app'/'webui'/'app.js').read_text(encoding='utf-8')
    assert 'restore-backup' in js
    assert '10–1000 GB' in js
    assert 'f-usb-tier' in js
    db=(ROOT/'Server'/'db.py').read_text(encoding='utf-8')
    assert 'PERMISSIONS' in db



def test_v2737_separate_boot_stack_and_client_pin_is_removed():
    forbidden_files=['Server/diskless_v27_service.py','Server/iscsi_v27_service.py','Server/pxe_v27_service.py']
    assert all(not (ROOT/x).exists() for x in forbidden_files)
    client=(ROOT/'Client/client_app/webui/index.html').read_text(encoding='utf-8')
    assert 'id="pin"' not in client and 'id="admin-pin"' not in client
    js=(ROOT/'Manager/manager_app/webui/app.js').read_text(encoding='utf-8')
    assert 'pickGamePath' in js and 'modal-global-actions' in js


def test_v2744_client_has_no_admin_pin_surface():
    root = Path(__file__).resolve().parents[1]
    client_js = (root / "Client/client_app/webui/app.js").read_text(encoding="utf-8")
    bridge = (root / "Client/client_app/webview_client.py").read_text(encoding="utf-8")
    assert "admin_unlock" not in client_js
    assert "admin_save_settings" not in client_js
    assert "admin_unlock" not in bridge
    assert "admin_pin" not in bridge


def test_v2747_client_launch_accepts_legacy_catalog_ids():
    import importlib.util

    module_path = ROOT / "Client/client_app/webview_client.py"
    spec = importlib.util.spec_from_file_location("v2747_client_webview", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    ClientWebAPI = module.ClientWebAPI

    class Runtime:
        device_id = "CLIENT-01"

    bridge = ClientWebAPI.__new__(ClientWebAPI)
    bridge.runtime = Runtime()
    calls = []

    class Response:
        def json(self):
            return {"game_id": "valorant"}

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return Response()

    bridge._request = fake_request
    result = bridge.launch("legacy-game:valorant")
    assert result["ok"] is True and result["legacy"] is True
    assert calls[0][0] == "POST" and calls[0][1] == "/api/v15/client/launch"
    assert calls[0][2]["json"]["game_id"] == "valorant"

    calls.clear()
    result = bridge.launch("legacy-app:steam")
    assert result["ok"] is True and result["legacy"] is True
    assert calls[0][2]["json"]["game_id"] == "steam"
