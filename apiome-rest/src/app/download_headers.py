"""Headers for a file the export surface hands back as a download (X6, #6227).

An export's file name comes from the source — an API title, a type, a namespace — and the source
is imported, user-controlled content. Two things go wrong when that name is pasted into
``Content-Disposition`` as is:

* a name outside Latin-1 (``注文 API.jtd.json``) cannot be encoded into an HTTP header, so the
  response fails with a 500 instead of downloading;
* a quote, backslash or control character breaks the header's quoting.

:func:`attachment_headers` sends an ASCII ``filename`` every browser understands plus, when the
real name differs, an RFC 6266 / RFC 5987 ``filename*`` carrying it in UTF-8. It also sends
``X-Content-Type-Options: nosniff``, so a browser trusts the declared media type of an emitted
document instead of guessing one from its bytes.
"""

from __future__ import annotations

import re
from typing import Dict
from urllib.parse import quote

from .zip_bundle import safe_bundle_path

__all__ = ["attachment_headers", "download_basename"]

#: Characters an ASCII ``filename="…"`` cannot carry safely: non-ASCII, quotes, backslashes, controls.
_UNSAFE_ASCII = re.compile(r'[^\x20-\x7e]|["\\]')


def download_basename(path: str, fallback: str = "download") -> str:
    """The last segment of an emitted path, safe to offer as a file name.

    Args:
        path: The emitted (bundle-relative) path, or a bare file name.
        fallback: The name to use when nothing usable remains.

    Returns:
        A non-empty name with no separator, quote or control character.
    """
    name = safe_bundle_path(path, fallback).rsplit("/", 1)[-1]
    name = name.replace('"', "").replace("\\", "")
    return name or fallback


def attachment_headers(filename: str, fallback: str = "download") -> Dict[str, str]:
    """``Content-Disposition`` (attachment) and ``X-Content-Type-Options`` for a download.

    Args:
        filename: The file name to offer — any Unicode; only its last path segment is used.
        fallback: The ASCII name when nothing of ``filename`` survives.

    Returns:
        The two headers, every value encodable as Latin-1.
    """
    name = download_basename(filename, fallback)
    ascii_name = _UNSAFE_ASCII.sub("_", name).strip("_ ") or fallback
    disposition = f'attachment; filename="{ascii_name}"'
    if ascii_name != name:
        disposition += f"; filename*=UTF-8''{quote(name, safe='')}"
    return {"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"}
