"""Subida segura de archivos: extensión + firma real del contenido + reescritura de imágenes."""
import hashlib
import io
import uuid
import zipfile
from pathlib import Path

from flask import current_app, g
from PIL import Image, ImageOps, UnidentifiedImageError

from ..common import ApiError, utcnow
from ..extensions import db
from .models import StoredFile

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
DATA_EXTENSIONS = {".csv", ".xlsx"}
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 50_000_000
SUBDIRS = {"producto": "fotos", "conteo": "procesadas", "importacion": "importaciones"}

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS  # protege contra "bombas" de descompresión


def _safe_original_name(name):
    name = Path(name or "archivo").name.replace("\x00", "")
    return name[:255] or "archivo"


def _target(purpose, extension):
    now = utcnow()
    relative = Path(SUBDIRS[purpose]) / f"{now:%Y}" / f"{now:%m}" / f"{uuid.uuid4().hex}{extension}"
    absolute = current_app.config["STORAGE_DIR"] / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    return relative.as_posix(), absolute


def _register(purpose, original, relative, mime, data, width=None, height=None):
    user = getattr(g, "user", None)
    row = StoredFile(
        purpose=purpose, original_name=original, relative_path=relative, mime_type=mime,
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), width=width, height=height,
        uploaded_by=user.id if user else None,
    )
    db.session.add(row)
    db.session.flush()
    return row


def save_image(file_storage, purpose):
    """Valida que sea una imagen real y la reescribe como JPEG sin metadatos (EXIF/GPS)."""
    if file_storage is None or not file_storage.filename:
        raise ApiError("Selecciona una imagen.", 422)
    original = _safe_original_name(file_storage.filename)
    if Path(original).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ApiError("Formato no permitido. Usa JPG, PNG o WEBP.", 415)
    raw = file_storage.read()
    if not raw:
        raise ApiError("El archivo está vacío.", 422)
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(raw))
        if image.format not in IMAGE_FORMATS:
            raise ApiError("El contenido no es una imagen JPG, PNG o WEBP.", 415)
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ApiError("El archivo no es una imagen válida o está dañado.", 415)
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90, optimize=True)
    data = buffer.getvalue()
    relative, absolute = _target(purpose, ".jpg")
    absolute.write_bytes(data)
    return _register(purpose, original, relative, "image/jpeg", data, image.width, image.height)


def save_data_file(file_storage):
    """Acepta .csv (texto) y .xlsx (paquete OOXML). Rechaza .xls/.xlsm y binarios disfrazados."""
    if file_storage is None or not file_storage.filename:
        raise ApiError("Selecciona un archivo .xlsx o .csv.", 422)
    original = _safe_original_name(file_storage.filename)
    extension = Path(original).suffix.lower()
    if extension not in DATA_EXTENSIONS:
        raise ApiError("Formato no permitido. Usa .xlsx o .csv.", 415)
    data = file_storage.read()
    if not data:
        raise ApiError("El archivo está vacío.", 422)
    if extension == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                names = set(package.namelist())
        except zipfile.BadZipFile:
            raise ApiError("El archivo .xlsx está dañado o no es un libro de Excel.", 415)
        if "[Content_Types].xml" not in names or not any(n.startswith("xl/") for n in names):
            raise ApiError("El archivo .xlsx no es un libro de Excel válido.", 415)
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise ApiError("No se aceptan libros con macros.", 415)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        if b"\x00" in data[:4096]:
            raise ApiError("El CSV contiene datos binarios.", 415)
        mime = "text/csv"
    relative, absolute = _target("importacion", extension)
    absolute.write_bytes(data)
    return _register("importacion", original, relative, mime, data)


def absolute_path(stored):
    """Ruta absoluta verificada: siempre dentro de STORAGE_DIR."""
    root = current_app.config["STORAGE_DIR"].resolve()
    path = (root / stored.relative_path).resolve()
    if root not in path.parents:
        raise ApiError("Archivo no disponible.", 404)
    if not path.is_file():
        raise ApiError("El archivo ya no está en el almacenamiento.", 404)
    return path
