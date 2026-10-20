"""Características visuales clásicas y explicables para comparar fotos de calzado con el catálogo.

  - Firma de color: histograma HSV 18×4×4 normalizado (intersección de histogramas, 0–1).
  - Colores dominantes: k-means (k=3) en Lab, nombrados con una paleta en español.
  - Estructura: descriptores ORB (puntos característicos), emparejados con la prueba de razón de Lowe.
  - Puntuación = 55 % estructura + 45 % color, de 0 a 100.

No es un modelo entrenado con fotos de la tienda: las puntuaciones deben calibrarse con revisiones reales
(tabla identification_feedback) antes de confiar en un umbral.
"""
import cv2
import numpy as np

FEATURE_VERSION = "orb500-hsv18x4x4-v1"
PALETTE = {
    "Negro": (20, 20, 20), "Blanco": (240, 240, 240), "Gris": (128, 128, 128), "Rojo": (190, 30, 35),
    "Azul": (35, 70, 190), "Azul marino": (25, 35, 80), "Celeste": (120, 180, 230), "Verde": (40, 140, 60),
    "Amarillo": (230, 200, 40), "Naranja": (235, 130, 30), "Marrón": (110, 70, 40), "Beige": (215, 195, 155),
    "Rosa": (235, 150, 180), "Morado": (120, 60, 150),
}
_PALETTE_LAB = {name: cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(float) for name, rgb in PALETTE.items()}
_ORB = None


def _orb():
    global _ORB
    if _ORB is None:
        _ORB = cv2.ORB_create(nfeatures=500)
    return _ORB


def crop(rgb, box=None, margin=0.08):
    if box is None:
        return rgb
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * margin, (y2 - y1) * margin
    a, b = int(max(0, (x1 - dx) * w)), int(max(0, (y1 - dy) * h))
    c, d = int(min(w, (x2 + dx) * w)), int(min(h, (y2 + dy) * h))
    if c - a < 8 or d - b < 8:
        return rgb
    return rgb[b:d, a:c]


def _resize(rgb, side=320):
    h, w = rgb.shape[:2]
    scale = side / max(h, w)
    if scale < 1:
        rgb = cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return rgb


def dominant_colors(rgb, k=3):
    pixels = cv2.cvtColor(_resize(rgb, 120), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    if len(pixels) < k:
        return []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    result = {}
    for center, count in zip(centers, counts):
        name = min(_PALETTE_LAB, key=lambda n: float(np.linalg.norm(_PALETTE_LAB[n] - center)))
        result[name] = result.get(name, 0) + count / len(pixels)
    return sorted(({"name": n, "share": round(float(s), 3)} for n, s in result.items() if s >= 0.12),
                  key=lambda c: -c["share"])


def extract(rgb, box=None):
    """Devuelve las características de la imagen (o del recorte indicado por la caja normalizada)."""
    region = _resize(crop(rgb, box))
    hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [18, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
    total = float(hist.sum()) or 1.0
    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    keypoints, descriptors = _orb().detectAndCompute(gray, None)
    return {
        "version": FEATURE_VERSION,
        "color_hist": (hist / total).astype(np.float32),
        "orb": descriptors if descriptors is not None else np.zeros((0, 32), dtype=np.uint8),
        "colors": dominant_colors(region),
    }


def serialize(features):
    return {"color_hist": features["color_hist"].tobytes(), "orb": features["orb"].tobytes(),
            "orb_count": int(len(features["orb"])), "colors": features["colors"], "version": features["version"]}


def deserialize(row):
    return {"color_hist": np.frombuffer(row.color_hist, dtype=np.float32),
            "orb": np.frombuffer(row.orb, dtype=np.uint8).reshape(-1, 32) if row.orb_count else np.zeros((0, 32), np.uint8),
            "colors": row.colors or [], "version": row.version}


def similarity(query, reference):
    """Puntuación 0–100 y sus componentes (para explicar la coincidencia)."""
    color = float(np.minimum(query["color_hist"], reference["color_hist"]).sum())
    structure, good = 0.0, 0
    if len(query["orb"]) >= 2 and len(reference["orb"]) >= 2:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(query["orb"], reference["orb"], k=2)
        good = sum(1 for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance)
        structure = min(1.0, good / max(10, min(len(query["orb"]), len(reference["orb"])) * 0.5))
    score = 100 * (0.55 * structure + 0.45 * color)
    return {"score": round(score, 1), "color": round(color * 100, 1), "structure": round(structure * 100, 1),
            "matches": good}
