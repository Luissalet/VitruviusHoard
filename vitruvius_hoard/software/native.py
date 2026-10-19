"""Explicit native factories; never imported during owner catalogue discovery."""
import os
from dataclasses import replace
from pathlib import Path
from .runtime import profile, ROOT


def port():
    return int(os.environ.get('VITRUVIUS_PORT', '5191'))


def create_native(name, automatic=False):
    if name == 'design':
        from vitruvius_hoard.config import Config
        from vitruvius_hoard.main import create_app
        config = replace(Config.from_env(), data_dir=profile()/name, data_dir_configured=True,
                         port=port(), autostart=automatic, embed_auto=automatic)
        return create_app(config)
    if name == 'babel':
        from babels_hoard.api import create_app
        return create_app(profile()/name, ROOT/'babel_client/dist',port=port())
    from theseus.api import create_app
    return create_app(profile()/name,port=port(),recover=False)
