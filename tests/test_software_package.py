"""Installed profile selection and the resource used by standalone exports."""
from pathlib import Path


def test_installed_default_is_external_and_explicit_profile_wins(tmp_path, monkeypatch):
    from vitruvius_hoard.software import runtime
    monkeypatch.setattr(runtime, 'ROOT', tmp_path/'installed')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'localappdata'))
    monkeypatch.delenv('VITRUVIUS_PROFILE_DIR', raising=False)
    assert runtime.profile()==tmp_path/'localappdata/VitruviusHoard/data'
    monkeypatch.setenv('VITRUVIUS_PROFILE_DIR', str(tmp_path/'explicit'))
    assert runtime.profile()==tmp_path/'explicit'
    assert not list(tmp_path.iterdir())


def test_checkout_retains_existing_default(tmp_path,monkeypatch):
    from vitruvius_hoard.software import runtime
    (tmp_path/'.git').write_text('synthetic worktree marker')
    monkeypatch.setattr(runtime,'ROOT',tmp_path)
    monkeypatch.delenv('VITRUVIUS_PROFILE_DIR',raising=False)
    assert runtime.profile()==tmp_path/'data'


def test_packaged_export_license_matches_owner_notice():
    import vitruvius_hoard
    package=Path(vitruvius_hoard.__file__).parent
    assert (package/'LICENSE').read_text(encoding='utf8')==(package.parent/'LICENSE').read_text(encoding='utf8')


def test_launcher_and_host_share_default(monkeypatch):
    import vitruvius_hoard.__main__ as launcher
    from vitruvius_hoard.software.runtime import profile
    captured={}
    def run(**kwargs):
        captured.update(kwargs)
        return 0
    monkeypatch.setattr(launcher,'run_main',run)
    assert launcher.main()==0
    assert captured['default_data_dir'] is profile
