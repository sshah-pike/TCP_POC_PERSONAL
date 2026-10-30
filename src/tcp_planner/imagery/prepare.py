"""Image preparation for the model (S6 Q5 A): resize in code to the profile's limit, downscale only, hash the bytes sent.

The AI reports pixel positions in the image as sent, so every conversion to ground distance uses `mpp_sent`
(source metres per pixel divided by the resize scale), never the scale of the source image.
"""
import hashlib, io
from PIL import Image

JPEG_QUALITY = 88            # fixed, the same as the provider's own encoder
RESAMPLE = Image.LANCZOS
MEDIA_TYPE = "image/jpeg"


def resize_for_model(data, max_px, mpp_source=None):
    """(bytes to send, record). Downscale only: an image already within max_px is sent as is when it is a JPEG
    (scale 1.0), otherwise re-encoded once without resizing. The record's sha256 and size are those of the bytes returned."""
    if not isinstance(max_px, int) or isinstance(max_px, bool) or max_px < 1: raise ValueError("max_px must be a positive integer")
    with Image.open(io.BytesIO(data)) as im:
        im.load(); w, h = im.size; fmt = im.format
        scale = min(1.0, max_px / max(w, h))
        if scale == 1.0 and fmt == "JPEG": out, sw, sh = data, w, h
        else:
            if scale < 1.0: im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), RESAMPLE)
            sw, sh = im.size
            buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY); out = buf.getvalue()
    real = sw / w                                          # the scale actually applied (rounding of the new size)
    return out, {"source_px": [w, h], "sent_px": [sw, sh], "resize_scale": real, "mpp_source": mpp_source,
                 "mpp_sent": None if mpp_source is None else mpp_source / real,
                 "sha256": hashlib.sha256(out).hexdigest(), "size": len(out), "media_type": MEDIA_TYPE, "max_px": max_px}
