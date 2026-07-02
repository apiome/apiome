"""Tests for ``types publish`` and ``types unpublish`` commands."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="type publish/unpublish not supported via /v1 REST")
