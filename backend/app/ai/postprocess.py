"""Postproceso del detector (sin dependencias de Flask: lo reutiliza entrenamiento/scripts/exportar.py)."""
import numpy as np

PAD_VALUE = 114


def letterbox(rgb, imgsz):
    """Réplica exacta de ultralytics LetterBox(auto=False, center=True) para entrada fija imgsz×imgsz.

    Debe coincidir con el preprocesado usado al validar el modelo exportado: con PIL (que suaviza al
    reducir) el conteo difería del de Ultralytics en 8 de 40 imágenes de test; con esta función, 40/40.
    Devuelve (tensor 1×3×H×W float32 en [0,1], escala, pad_x, pad_y).
    """
    import cv2

    h, w = rgb.shape[:2]
    r = min(imgsz / h, imgsz / w)
    new_w, new_h = int(round(w * r)), int(round(h * r))
    dw, dh = (imgsz - new_w) / 2, (imgsz - new_h) / 2
    if (w, h) != (new_w, new_h):
        rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    rgb = cv2.copyMakeBorder(rgb, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(PAD_VALUE,) * 3)
    tensor = (rgb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
    return np.ascontiguousarray(tensor), r, left, top


def decode_output(output, conf):
    """Admite la salida cruda de YOLOv8/11 (1, 4+nc, N) y la salida con NMS integrado (1, N, 6)."""
    output = np.asarray(output)
    if output.ndim != 3:
        raise ValueError(f"Salida de modelo inesperada: {output.shape}")
    if output.shape[2] == 6 and output.shape[1] != 6:
        rows = output[0]
        rows = rows[rows[:, 4] >= conf]
        return rows[:, :4], rows[:, 4], rows[:, 5].astype(int)
    predictions = output[0].T  # (N, 4+nc)
    class_scores = predictions[:, 4:]
    labels = class_scores.argmax(axis=1)
    scores = class_scores.max(axis=1)
    mask = scores >= conf
    predictions, scores, labels = predictions[mask], scores[mask], labels[mask]
    cx, cy, w, h = predictions[:, 0], predictions[:, 1], predictions[:, 2], predictions[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    return boxes, scores, labels


def nms(boxes, scores, iou_threshold):
    """Supresión de no máximos clásica (independiente de la clase: solo hay 'zapato')."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        union = areas[i] + areas[order[1:]] - inter
        overlap = np.where(union > 0, inter / union, 0)
        order = order[1:][overlap <= iou_threshold]
    return keep
