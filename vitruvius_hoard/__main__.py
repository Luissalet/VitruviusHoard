"""`python -m vitruvius_hoard` — run the app with uvicorn on 127.0.0.1 (the shared `hoard_link.service.run_main`: a second start
reports the running instance and exits before touching the data folder or the token)."""

from __future__ import annotations

from .hoard_link.service import run_main


def main() -> int:
    from .software.runtime import profile
    return run_main(service="vitruvius-hoard", package="vitruvius_hoard", default_port=5191, app_factory="vitruvius_hoard.software.host:create_app",
                    data_dir_env="VITRUVIUS_PROFILE_DIR", default_data_dir=profile, port_env="VITRUVIUS_PORT", title="Vitruvius's Hoard", open_browser_default=False)


if __name__ == "__main__":
    raise SystemExit(main())
