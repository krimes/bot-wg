from __future__ import annotations

import io

import qrcode


def qr_png(payload: str) -> bytes:
    img = qrcode.make(payload, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
