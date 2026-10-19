"""Native settings survive owner routing and explicit automatic-work overrides."""
from dataclasses import fields

import pytest


@pytest.mark.parametrize('automatic',[False,True])
def test_owner_preserves_every_non_owner_design_configuration_field(tmp_path,monkeypatch,automatic):
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR',str(tmp_path/'profile'))
    monkeypatch.setenv('VITRUVIUS_DATA_DIR',str(tmp_path/'legacy'))
    monkeypatch.setenv('VITRUVIUS_PORT','5299')
    monkeypatch.setenv('VITRUVIUS_ALLOW_LOCAL_URLS','1')
    monkeypatch.setenv('VITRUVIUS_RENDER_TIMEOUT_S','123')
    monkeypatch.setenv('VITRUVIUS_EMBED','none')
    monkeypatch.setenv('VITRUVIUS_EMBED_MODEL','synthetic-native-embedding-model')
    monkeypatch.setenv('PORT_STRICT','1')
    monkeypatch.setenv('VITRUVIUS_ALLOWED_HOSTS','synthetic.invalid')
    monkeypatch.setenv('VITRUVIUS_AUTOSTART','1' if not automatic else '0')
    monkeypatch.setenv('VITRUVIUS_EMBED_AUTO','1' if not automatic else '0')
    from vitruvius_hoard.config import Config
    from vitruvius_hoard.software.native import create_native
    expected=Config.from_env()
    actual=create_native('design',automatic).state.config
    assert actual.data_dir==tmp_path/'profile/design'
    assert actual.data_dir_configured is True
    assert actual.port==5299
    assert actual.autostart is actual.embed_auto is automatic
    owner_fields={'data_dir','data_dir_configured','port','autostart','embed_auto'}
    for field in fields(Config):
        if field.name not in owner_fields:
            assert getattr(actual,field.name)==getattr(expected,field.name),field.name
    # Explicit factory construction may retain copilot identity metadata, but
    # native service stores still belong to its later lifespan.
    assert not (tmp_path/'profile/design/vitruvius.db').exists()
    assert not (tmp_path/'legacy').exists()
