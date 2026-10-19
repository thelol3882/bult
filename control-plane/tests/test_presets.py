"""Every preset the API accepts has a Dockerfile to build with."""

from typing import get_args

from app.apps.schemas.apps import Preset
from app.deploys.services.runner import PRESETS_DIR


def test_every_accepted_preset_has_a_dockerfile():
    presets = get_args(Preset)

    assert "static" in presets
    for preset in presets:
        assert (PRESETS_DIR / preset / "Dockerfile").is_file(), preset


def test_every_preset_directory_is_accepted_by_the_api():
    on_disk = {p.name for p in PRESETS_DIR.iterdir() if p.is_dir()}

    assert on_disk == set(get_args(Preset))
