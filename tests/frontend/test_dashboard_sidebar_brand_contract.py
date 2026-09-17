from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.no_infrastructure


def test_sidebar_brand_text_stays_vertically_centered_with_logo():
    source = (ROOT / "frontend/src/views/Dashboard.vue").read_text(encoding="utf-8")

    assert 'class="h-16 flex items-center bg-sidebar' in source
    assert 'class="ml-2.5 flex flex-col justify-center"' in source
    assert "-translate-y-0.5" not in source


def test_sidebar_brand_does_not_show_dev_build_version():
    source = (ROOT / "frontend/src/views/Dashboard.vue").read_text(encoding="utf-8")

    assert "appVersion" not in source
    assert "Dev Build" not in source
    assert "VITE_APP_VERSION" not in source
    assert "v{{" not in source


def test_branding_hydrates_from_local_cache_before_network():
    source = (ROOT / "frontend/src/composables/useBranding.ts").read_text(encoding="utf-8")

    assert 'BRANDING_CACHE_KEY = \'nanzi_public_branding\'' in source
    assert "readCachedBranding()" in source
    assert "product_name: ''" in source
    assert "void loadBranding()" in source
    assert "branding.value = { ...DEFAULT_BRANDING }" in source
    assert "if (!branding.value.product_name)" in source
