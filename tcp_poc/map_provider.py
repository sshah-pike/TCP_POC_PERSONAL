"""Aerial/map context providers. The pipeline only sees MapProvider.fetch_context()."""
import datetime, io, math, os
from .models import MapProviderError, r

R = 6378137.0
WEBMERC_MPP_Z0 = 2 * math.pi * R / 256  # ground resolution at zoom 0 for 256-px tiles (equator)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def build_metadata(provider, lat, lon, width, height, mpp, extra=None):
    """Georeferencing metadata for a north-up image centred on (lat, lon)."""
    gw, gh = width * mpp, height * mpp
    dlat = math.degrees((gh / 2) / R); dlon = math.degrees((gw / 2) / (R * math.cos(math.radians(lat))))
    meta = {"provider": provider, "retrieved_at": _now(),
            "center": {"latitude": r(lat, 7), "longitude": r(lon, 7)},
            "bounding_box": {"min_latitude": r(lat - dlat, 7), "min_longitude": r(lon - dlon, 7),
                             "max_latitude": r(lat + dlat, 7), "max_longitude": r(lon + dlon, 7)},
            "width_pixels": width, "height_pixels": height,
            "ground_extent_m": {"width": r(gw, 3), "height": r(gh, 3)},
            "metres_per_pixel": r(mpp, 6), "orientation": "NORTH_UP",
            "georeference_model": "LOCAL_TANGENT_PLANE_AT_CENTER"}
    meta.update(extra or {})
    return meta


def view_metres_per_pixel(lat, zoom, tile_px=512):
    """Ground resolution of a fetch_view() image (Azure static-image 512-px grid; the offline provider uses the same)."""
    return 2 * math.pi * R * math.cos(math.radians(lat)) / (tile_px * 2 ** int(zoom))


class MapProvider:
    name = "abstract"

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        """Return (PIL.Image RGB, metadata dict). Must cover at least +/- half_extent_m around the work point."""
        raise NotImplementedError


class AzureMapsProvider(MapProvider):
    """Azure Maps Render 'Get Map Static Image' with the microsoft.imagery tileset.

    Uses centre + integer zoom. The static image is rendered on the 512-px tile grid: zoom z has
    2*pi*R*cos(lat) / (512 * 2**z) metres per pixel. (Measured 2026-10-16: two images whose centres were
    320 / 160 px apart on a 256-px grid overlapped at exactly 640 / 320 px, correlation 0.98. The earlier
    256-px assumption reported twice the true ground extent.)
    Requests larger than the endpoint limit (width <= 2000, height <= 1500 px) are composed from tiles
    at the same zoom whose centres sit at exact pixel offsets, so the mosaic has the requested centre,
    scale and size. Requires AZURE_MAPS_KEY (sent as a header, never in the URL or logs).
    """
    name = "azure_maps"
    URL = "https://atlas.microsoft.com/map/static"
    API_VERSION = os.environ.get("AZURE_MAPS_API_VERSION", "2024-04-01")
    TILE_PX = 512                 # static-image pixel grid (see docstring)
    SCALE_MODEL = "azure-static-512px-v2"
    MAX_REQUEST_PX = 1280         # per request; within the endpoint limits (width 2000, height 1500)
    MAX_ZOOM = 19                 # microsoft.imagery supports zoom 0-19

    def _mpp_z0(self, lat):
        return 2 * math.pi * R * math.cos(math.radians(lat)) / self.TILE_PX

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        import requests
        key = os.environ.get("AZURE_MAPS_KEY") or os.environ.get("AZURE_MAPS_SUBSCRIPTION_KEY")
        if not key: raise MapProviderError("MAP_CREDENTIALS_MISSING", "set AZURE_MAPS_KEY to use Azure Maps imagery")
        lat = project_geometry["work_reference"]["latitude"]; lon = project_geometry["work_reference"]["longitude"]
        mpp0 = self._mpp_z0(lat)
        zoom = int(math.floor(math.log2(mpp0 * size_px / (2 * half_extent_m))))
        zoom = max(1, min(self.MAX_ZOOM, zoom))
        mpp = mpp0 / (2 ** zoom)
        if size_px * mpp < 2 * half_extent_m:
            raise MapProviderError("MAP_EXTENT_INSUFFICIENT", "cannot cover the analysis extent at supported zoom")
        from PIL import Image
        n = math.ceil(size_px / self.MAX_REQUEST_PX); tile = math.ceil(size_px / n)
        if n == 1:
            img = self._get(requests, key, zoom, lat, lon, size_px)
        else:  # compose n x n tiles on the global pixel grid of this zoom
            world = self.TILE_PX * 2 ** zoom
            cx = (lon + 180) / 360 * world
            cy = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * world
            img = Image.new("RGB", (n * tile, n * tile))
            for j in range(n):
                for i in range(n):
                    tx = cx - n * tile / 2 + (i + 0.5) * tile; ty = cy - n * tile / 2 + (j + 0.5) * tile
                    t_lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / world))))
                    t_lon = tx / world * 360 - 180
                    img.paste(self._get(requests, key, zoom, t_lat, t_lon, tile), (i * tile, j * tile))
            off = (n * tile - size_px) // 2
            img = img.crop((off, off, off + size_px, off + size_px))
        return img, build_metadata("AZURE_MAPS", lat, lon, size_px, size_px, mpp,
                                   {"zoom": zoom, "tileset": "microsoft.imagery", "api_version": self.API_VERSION,
                                    "scale_model": self.SCALE_MODEL, "request_tiles": n * n})

    def fetch_view(self, lat, lon, zoom, size_px):
        """One north-up view centred at (lat, lon) at an explicit zoom (multi-resolution evidence, agent crops).
        The zoom is requested exactly as asked - no silent clamp to MAX_ZOOM - so a request above the documented
        imagery range either fails (the caller falls back) or is detected as upsampled by the sharpness check."""
        import requests
        key = os.environ.get("AZURE_MAPS_KEY") or os.environ.get("AZURE_MAPS_SUBSCRIPTION_KEY")
        if not key: raise MapProviderError("MAP_CREDENTIALS_MISSING", "set AZURE_MAPS_KEY to use Azure Maps imagery")
        zoom = max(1, int(zoom))
        if size_px > self.MAX_REQUEST_PX:
            raise MapProviderError("MAP_EXTENT_INSUFFICIENT", f"view size {size_px}px exceeds {self.MAX_REQUEST_PX}px")
        img = self._get(requests, key, zoom, lat, lon, size_px)
        return img, build_metadata("AZURE_MAPS", lat, lon, size_px, size_px, self._mpp_z0(lat) / 2 ** zoom,
                                   {"zoom": zoom, "tileset": "microsoft.imagery", "api_version": self.API_VERSION,
                                    "scale_model": self.SCALE_MODEL, "request_tiles": 1})

    def _get(self, requests, key, zoom, lat, lon, px):
        params = {"api-version": self.API_VERSION, "tilesetId": "microsoft.imagery", "zoom": zoom,
                  "center": f"{lon:.7f},{lat:.7f}", "width": px, "height": px}
        try:
            resp = requests.get(self.URL, params=params, timeout=(5, 60),
                                headers={"subscription-key": key, "Accept": "image/jpeg, image/png",
                                         "User-Agent": "tcp-poc/0.2"})
        except requests.RequestException as e:
            raise MapProviderError("MAP_REQUEST_FAILED", type(e).__name__)
        ctype = resp.headers.get("content-type", "")[:100]
        if resp.status_code != 200:
            raise MapProviderError("MAP_REQUEST_FAILED", f"Azure Maps HTTP {resp.status_code}",
                                   {"http_status": resp.status_code, "content_type": ctype})
        if not ctype.startswith("image"):  # the endpoint can answer 200 with a JSON body
            raise MapProviderError("MAP_REQUEST_FAILED", "Azure Maps returned non-image content",
                                   {"http_status": resp.status_code, "content_type": ctype})
        from PIL import Image, UnidentifiedImageError
        try:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        except (UnidentifiedImageError, OSError):
            raise MapProviderError("MAP_REQUEST_FAILED", "Azure Maps image could not be decoded",
                                   {"http_status": resp.status_code, "content_type": ctype})
        if img.size != (px, px):
            raise MapProviderError("MAP_GEOREFERENCE_MISMATCH", f"expected {px}px image, got {img.size}")
        return img


class EsriDemoProvider(MapProvider):
    """INACTIVE legacy provider (Esri World Imagery export). Licensing is NOT cleared - demo only.
    Selected only when TCP_MAP_PROVIDER=esri_demo is set explicitly."""
    name = "esri_demo"

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        import requests
        from PIL import Image
        lat = project_geometry["work_reference"]["latitude"]; lon = project_geometry["work_reference"]["longitude"]
        x = R * math.radians(lon); y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        h = half_extent_m / math.cos(math.radians(lat))
        url = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export"
               f"?bbox={x-h},{y-h},{x+h},{y+h}&bboxSR=3857&imageSR=3857&size={size_px},{size_px}&format=jpg&f=image")
        try:
            resp = requests.get(url, timeout=60, headers={"User-Agent": "tcp-poc/0.2"}); resp.raise_for_status()
        except requests.RequestException as e:
            raise MapProviderError("MAP_REQUEST_FAILED", type(e).__name__)
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        return img, build_metadata("ESRI_WORLD_IMAGERY_DEMO", lat, lon, size_px, size_px, 2 * half_extent_m / size_px,
                                   {"licensing": "NOT_CLEARED_DEMO_ONLY"})


class UsgsNaipProvider(MapProvider):
    """USGS The National Map 'NAIP Plus' orthoimagery (NAIP + high-resolution orthoimagery).

    Public-domain US Government imagery, conterminous US only, ~0.15-1 m native resolution.
    Interim open-data provider until an Azure Maps key is available (TCP_MAP_PROVIDER=usgs_naip).
    The export bbox is square in Web Mercator and scaled by 1/cos(lat), so ground resolution is exact.
    """
    name = "usgs_naip"
    SERVICE = os.environ.get("TCP_USGS_NAIP_SERVICE", "USGSNAIPPlus")
    BASE = "https://imagery.nationalmap.gov/arcgis/rest/services/{svc}/ImageServer/exportImage"
    # The service renders exports on demand; uncached areas were measured at 30-90 s, so 90 s timed out.
    READ_TIMEOUT_S = float(os.environ.get("TCP_USGS_NAIP_READ_TIMEOUT_S", "180"))

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        import requests
        from PIL import Image
        lat = project_geometry["work_reference"]["latitude"]; lon = project_geometry["work_reference"]["longitude"]
        x = R * math.radians(lon); y = R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        h = half_extent_m / math.cos(math.radians(lat))
        params = {"bbox": f"{x-h},{y-h},{x+h},{y+h}", "bboxSR": 3857, "imageSR": 3857,
                  "size": f"{size_px},{size_px}", "format": "jpg", "f": "image"}
        try:
            resp = requests.get(self.BASE.format(svc=self.SERVICE), params=params, timeout=(5, self.READ_TIMEOUT_S),
                                headers={"User-Agent": "tcp-poc/0.2"})
        except requests.RequestException as e:
            raise MapProviderError("MAP_REQUEST_FAILED", type(e).__name__)
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image"):
            raise MapProviderError("MAP_REQUEST_FAILED", f"USGS NAIP HTTP {resp.status_code}",
                                   {"http_status": resp.status_code,
                                    "content_type": resp.headers.get("content-type", "")[:100]})
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        if img.size != (size_px, size_px):
            raise MapProviderError("MAP_GEOREFERENCE_MISMATCH", f"expected {size_px}px image, got {img.size}")
        if img.getextrema() in (((0, 0),) * 3, ((255, 255),) * 3):
            raise MapProviderError("MAP_NO_COVERAGE", "USGS NAIP returned a blank image (outside coverage)")
        return img, build_metadata("USGS_NAIP_PLUS", lat, lon, size_px, size_px, 2 * half_extent_m / size_px,
                                   {"service": self.SERVICE, "licensing": "PUBLIC_DOMAIN_US_GOVERNMENT",
                                    "attribution": "USGS, USDA, The National Map: Orthoimagery"})


class StaticMapProvider(MapProvider):
    """Returns a pre-built image (offline tests / synthetic scenarios)."""
    name = "offline_synthetic"

    def __init__(self, image, mpp, center=None):
        self.image = image; self.mpp = mpp; self.center = center  # (lat, lon) of the image centre, if known

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        w, h = self.image.size
        if w * self.mpp < 2 * half_extent_m:
            raise MapProviderError("MAP_EXTENT_INSUFFICIENT", "synthetic image smaller than analysis extent")
        ref = project_geometry["work_reference"]
        return self.image, build_metadata("OFFLINE_SYNTHETIC", ref["latitude"], ref["longitude"], w, h, self.mpp)

    def fetch_view(self, lat, lon, zoom, size_px):
        """Synthetic view: resampled crop of the synthetic image at the Azure 512-px zoom scale (offline only)."""
        if self.center is None:
            raise MapProviderError("MAP_VIEW_UNSUPPORTED", "synthetic image centre unknown")
        from .geometry import enu
        mpp = 2 * math.pi * R * math.cos(math.radians(lat)) / (512 * 2 ** int(zoom))
        dx, dy = enu(lat, lon, *self.center); w, h = self.image.size
        cx, cy = w / 2 + dx / self.mpp, h / 2 - dy / self.mpp; half = size_px * mpp / 2 / self.mpp
        view = self.image.crop((round(cx - half), round(cy - half), round(cx + half), round(cy + half)))
        return view.resize((size_px, size_px)), build_metadata("OFFLINE_SYNTHETIC", lat, lon, size_px, size_px, mpp,
                                                               {"zoom": int(zoom), "synthetic_resampled": True})


def get_map_provider(name=None):
    name = (name or os.environ.get("TCP_MAP_PROVIDER") or "azure_maps").strip().lower()
    if name == "azure_maps": return AzureMapsProvider()
    if name == "usgs_naip": return UsgsNaipProvider()
    if name == "esri_demo": return EsriDemoProvider()
    raise MapProviderError("MAP_PROVIDER_UNKNOWN", f"unknown map provider {name!r}")
