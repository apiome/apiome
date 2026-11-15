"""Write ``schemas/sdk-compat-manifest.v1.json`` from the model — SGD-2.1 (#4735).

Run from ``apiome-rest/``::

    uv run python scripts/generate_sdk_compat_schema.py

``tests/test_sdk_compat_manifest.py`` fails when the committed schema and the model drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.sdk_compat_manifest import SdkCompatManifest  # noqa: E402


def main() -> None:
    target = ROOT / "schemas" / "sdk-compat-manifest.v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(SdkCompatManifest.model_json_schema(), indent=2, sort_keys=True) + "\n")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
