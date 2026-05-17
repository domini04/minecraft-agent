"""Drift guard: brain/src/sops/index.yaml must match what build_index() would emit now.

If this test fails, the catalog has drifted from the SOP files. Run:
    cd brain && python -m src.sops.build_index
to regenerate.
"""

from pathlib import Path

from src.sops.build_index import build_index
from src.sops.loader import _sops_dir


def test_index_yaml_matches_build_index_output():
    """Checked-in index.yaml is byte-equal to what build_index() would generate now."""
    checked_in = (_sops_dir() / "index.yaml").read_text(encoding="utf-8")
    regenerated = build_index()
    assert checked_in == regenerated, (
        "brain/src/sops/index.yaml is out of sync with the SOP files.\n"
        "Run: cd brain && python -m src.sops.build_index\n"
        "to regenerate."
    )
