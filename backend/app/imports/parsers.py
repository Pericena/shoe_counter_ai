"""Lectura y validación de archivos Excel/CSV. No escribe en la base de datos.

Cada validador devuelve:
  rows    -> filas válidas normalizadas (dict con '_row' = número de fila en el archivo)
  issues  -> lista de (fila, columna, severidad, mensaje)
  info    -> columnas detectadas, faltantes, sobrantes y vista previa
"""
import csv
import io
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

MAX_ROWS = 100_000


def normalize_header(value):
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return text.strip("_")


def read_table(path, sheet=None):
    """Lee .xlsx (primera hoja o `sheet`) o .csv (UTF-8/Latin-1; separador , ; o tabulador) como texto."""
    path = str(path)
    if path.lower().endswith(".xlsx"):
        try:
            book = pd.ExcelFile(path, engine="openpyxl")
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"No se pudo abrir el libro de Excel: {error}")
        sheet_name = sheet if sheet in book.sheet_names else book.sheet_names[0]
        frame = book.parse(sheet_name, dtype=str, keep_default_na=False)
        return frame, sheet_name, book.sheet_names
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:20000]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    frame = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=False)
    return frame, None, None


def parse_number(value):
    """Convierte '1.234,56', '1,234.56', '1234.5' o '12,5' en Decimal.

    Regla: si aparecen '.' y ',' el último es el separador decimal; si solo aparece uno y se
    repite, es separador de miles; si aparece una vez, es decimal.
    """
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace(" ", "").replace("$", "").replace("US", "")
    if text in ("", "-", "nan", "NaN", "None", "null", "NULL", "..", "N/A", "n/a"):
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "") if text.count(",") > 1 else text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"'{value}' no es un número")
    if not number.is_finite():
        raise ValueError(f"'{value}' no es un número finito")
    return number


def _clean_text(value):
    text = str(value).strip() if value is not None else ""
    return text or None


class TableValidator:
    """Base: mapeo de columnas por alias, recorrido de filas y registro de incidencias."""

    columns = {}   # nombre canónico -> (obligatoria, alias normalizados)

    def __init__(self, frame, duplicate_policy="rechazar", mapping_override=None):
        self.frame = frame
        self.duplicate_policy = duplicate_policy
        self.mapping_override = mapping_override or {}
        self.issues = []
        self.rows = []
        self.mapping = {}

    def issue(self, row, column, severity, message):
        self.issues.append((row, column, severity, message[:500]))

    def map_columns(self):
        found = {normalize_header(c): c for c in self.frame.columns}
        by_label = {str(c): c for c in self.frame.columns}
        missing = []
        # Asignaciones elegidas por la persona en el asistente (columna del archivo -> campo del sistema).
        for name, source in self.mapping_override.items():
            if name not in self.columns:
                self.issue(1, name, "error", f"El campo '{name}' no existe en este tipo de importación.")
            elif source not in by_label:
                self.issue(1, name, "error", f"La columna '{source}' no está en el archivo.")
            else:
                self.mapping[name] = by_label[source]
        taken = set(self.mapping.values())
        for name, (required, aliases) in self.columns.items():
            if name in self.mapping:
                continue
            match = next((found[a] for a in (name, *aliases) if a in found and found[a] not in taken), None)
            if match is not None:
                self.mapping[name] = match
            elif required:
                missing.append(name)
        used = set(self.mapping.values())
        extra = [str(c) for c in self.frame.columns if c not in used]
        for name in missing:
            self.issue(1, name, "error", f"Falta la columna obligatoria '{name}'.")
        truncated = [h for h in found for name in missing
                     if any(len(alias) - len(h) == 1 and alias.startswith(h) for alias in (name, *self.columns[name][1]))]
        if truncated:
            self.issue(1, None, "error",
                       "Algunos encabezados parecen haber perdido su último carácter (p. ej. "
                       f"'{', '.join(str(found[h]) for h in truncated[:3])}'). Suele pasar al convertir el archivo con "
                       "una codificación errónea: a los campos con tildes o ñ les falta la última letra. "
                       "Usa el .xlsx original o vuelve a exportar el CSV en UTF-8.")
        return missing, extra

    def diagnose(self):
        """(faltantes, faltantes que parecen encabezados truncados) sin registrar incidencias."""
        found = {normalize_header(c) for c in self.frame.columns}
        missing, truncated = [], []
        for name, (required, aliases) in self.columns.items():
            names = (name, *aliases)
            if not required or any(a in found for a in names):
                continue
            missing.append(name)
            if any(len(a) - len(h) == 1 and a.startswith(h) for a in names for h in found):
                truncated.append(name)
        return missing, truncated

    def value(self, record, name):
        column = self.mapping.get(name)
        return _clean_text(record.get(column)) if column is not None else None

    def run(self):
        if len(self.frame) > MAX_ROWS:
            self.issue(None, None, "error", f"El archivo tiene {len(self.frame)} filas; el máximo es {MAX_ROWS}.")
            return self.result([], [])
        missing, extra = self.map_columns()
        if missing:
            return self.result(missing, extra)
        records = self.frame.to_dict("records")
        for index, record in enumerate(records):
            row_number = index + 2  # +1 por el encabezado, +1 porque las filas empiezan en 1
            if all(not _clean_text(v) for v in record.values()):
                continue
            errors_before = sum(1 for i in self.issues if i[2] == "error")
            clean = self.validate_row(record, row_number)
            if clean is not None and sum(1 for i in self.issues if i[2] == "error") == errors_before:
                clean["_row"] = row_number
                self.rows.append(clean)
        self.after_rows()
        return self.result(missing, extra)

    def validate_row(self, record, row_number):
        raise NotImplementedError

    def after_rows(self):
        pass

    def result(self, missing, extra):
        rejected_rows = {i[0] for i in self.issues if i[2] == "error" and i[0] and i[0] > 1}
        valid = [r for r in self.rows if r["_row"] not in rejected_rows]
        preview = [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in valid[:20]]
        info = {
            "detected_columns": [str(c) for c in self.frame.columns],
            "mapping": {k: str(v) for k, v in self.mapping.items()},
            "missing_columns": missing,
            "extra_columns": extra,
            "total_rows": int(len(self.frame)),
            "preview": preview,
        }
        return valid, self.issues, info


# ---------- Catálogo de la tienda ----------

SIZE_SYSTEMS = ("EU", "US", "UK", "BR", "CM", "MX", "otro")
NUMERIC_SIZE = re.compile(r"^\d{1,2}([.,]5)?$")
LETTER_SIZE = re.compile(r"^(XXS|XS|S|M|L|XL|XXL|XXXL|U|TU|UNICA|ÚNICA)$", re.IGNORECASE)


def size_problem(size, system=None):
    """None si la talla es válida; si no, el motivo. 'otro' acepta cualquier texto."""
    if system == "otro":
        return None
    text = size.strip()
    if LETTER_SIZE.match(text):
        return None
    if not NUMERIC_SIZE.match(text):
        return f"Talla '{size}' no reconocida (usa números como 38 o 38.5, o elige sistema_tallas = otro)."
    value = float(text.replace(",", "."))
    low, high = {"US": (1, 18), "UK": (1, 16), "MX": (10, 33), "CM": (10, 35), "BR": (15, 50)}.get(system or "EU", (15, 52))
    if not low <= value <= high:
        return f"Talla {size} fuera de rango para el sistema {system or 'EU'} ({low}–{high})."
    return None


class CatalogValidator(TableValidator):
    columns = {
        "codigo_producto": (True, ("codigo", "codigo_modelo", "product_code", "codigo_interno")),
        "marca": (True, ("brand",)),
        "modelo": (True, ("model", "model_name", "nombre_modelo")),
        "nombre": (False, ("nombre_comercial", "name", "producto")),
        "categoria": (False, ("category",)),
        "subcategoria": (False, ("subcategory",)),
        "tipo_calzado": (False, ("tipo", "footwear_type")),
        "segmento": (False, ("segment", "genero", "publico")),
        "material": (False, ()),
        "temporada": (False, ("season",)),
        "coleccion": (False, ("collection",)),
        "sistema_tallas": (False, ("size_system", "sistema_talla")),
        "proveedor": (False, ("supplier",)),
        "ref_proveedor": (False, ("referencia_proveedor", "supplier_ref")),
        "descripcion": (False, ("description",)),
        "imagen_url": (False, ("imagen", "foto", "url_imagen", "image", "image_url")),
        "sku": (True, ()),
        "codigo_barras": (False, ("barcode", "ean", "upc")),
        "talla": (True, ("size",)),
        "color": (True, ()),
        "costo": (False, ("cost", "costo_unitario")),
        "precio": (False, ("price", "precio_venta")),
        "stock_minimo": (False, ("min_stock", "minimo")),
        "stock_inicial": (False, ("stock", "existencias", "stock_actual", "saldo_inicial")),
        "cantidad_entrada": (False, ("entrada", "cantidad", "compra")),
        "ubicacion": (False, ("location", "almacen", "tienda")),
    }
    limits = {"codigo_producto": 50, "marca": 100, "modelo": 150, "nombre": 200, "categoria": 100,
              "subcategoria": 100, "tipo_calzado": 100, "segmento": 60, "material": 100, "temporada": 60,
              "coleccion": 100, "proveedor": 150, "ref_proveedor": 100, "descripcion": 5000, "imagen_url": 1000,
              "sku": 60, "codigo_barras": 64, "talla": 20, "color": 50, "ubicacion": 30, "sistema_tallas": 10}

    def validate_row(self, record, row):
        clean = {}
        for name, limit in self.limits.items():
            value = self.value(record, name)
            if value and len(value) > limit:
                self.issue(row, name, "error", f"Máximo {limit} caracteres.")
            clean[name] = value
        for name in ("codigo_producto", "marca", "modelo", "sku", "talla", "color"):
            if not clean[name]:
                self.issue(row, name, "error", "Campo obligatorio vacío.")
        system = clean["sistema_tallas"]
        if system:
            match = next((s for s in SIZE_SYSTEMS if s.lower() == system.lower()), None)
            if match is None:
                self.issue(row, "sistema_tallas", "error", f"Sistema de tallas no válido; usa {', '.join(SIZE_SYSTEMS)}.")
            clean["sistema_tallas"] = system = match
        if clean["talla"] and (problem := size_problem(clean["talla"], system)):
            self.issue(row, "talla", "error", problem)
        if clean["color"] and not re.search(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]", clean["color"]):
            self.issue(row, "color", "error", f"Color '{clean['color']}' no válido: debe ser un nombre (p. ej. Negro).")
        if clean["codigo_barras"] and not re.fullmatch(r"[0-9A-Za-z\-]{4,64}", clean["codigo_barras"]):
            self.issue(row, "codigo_barras", "error", "Código de barras con caracteres no válidos.")
        if clean["imagen_url"]:
            # Nunca se descargan URLs de un archivo: la foto se sube desde la ficha (validada y re-codificada).
            self.issue(row, "imagen_url", "advertencia",
                       "La imagen no se descarga desde la URL: el producto quedará con foto pendiente de subir.")
        for name in ("costo", "precio"):
            try:
                number = parse_number(self.value(record, name))
            except ValueError as error:
                self.issue(row, name, "error", str(error))
                continue
            if number is not None and number < 0:
                self.issue(row, name, "error", "No puede ser negativo.")
            clean[name] = number.quantize(Decimal("0.01")) if number is not None else None
        for name in ("stock_minimo", "stock_inicial", "cantidad_entrada"):
            try:
                number = parse_number(self.value(record, name))
            except ValueError as error:
                self.issue(row, name, "error", str(error))
                continue
            if number is not None and (number < 0 or number != number.to_integral_value()):
                self.issue(row, name, "error", "Debe ser un entero mayor o igual a 0.")
                continue
            clean[name] = int(number) if number is not None else None
        if clean.get("precio") is not None and clean.get("costo") is not None and clean["precio"] < clean["costo"]:
            self.issue(row, "precio", "advertencia", f"Precio {clean['precio']} menor que el costo {clean['costo']} (margen negativo).")
        if clean.get("precio") == 0:
            self.issue(row, "precio", "advertencia", "Precio 0: el artículo no podrá venderse hasta fijar un precio.")
        return clean

    def after_rows(self):
        by_sku, products = {}, {}
        for r in self.rows:
            by_sku.setdefault(r["sku"].lower(), []).append(r["_row"])
            key = r["codigo_producto"].lower()
            signature = (r["marca"].lower(), r["modelo"].lower(), (r["categoria"] or "").lower())
            products.setdefault(key, {}).setdefault(signature, []).append(r["_row"])
        for sku, rows in by_sku.items():
            if len(rows) > 1:
                for row in rows:
                    self.issue(row, "sku", "error", f"SKU repetido en el archivo (filas {', '.join(map(str, rows))}).")
        for code, signatures in products.items():
            if len(signatures) > 1:
                for rows in signatures.values():
                    for row in rows:
                        self.issue(row, "codigo_producto", "error",
                                   f"El producto {code} tiene marca/modelo/categoría distintos en varias filas.")
        variants = {}
        for r in self.rows:
            variants.setdefault((r["codigo_producto"].lower(), r["talla"].lower(), r["color"].lower()), []).append(r["_row"])
        for rows in variants.values():
            if len(rows) > 1:
                for row in rows:
                    self.issue(row, "talla", "error", f"Talla+color repetidos para el mismo producto (filas {rows}).")


# ---------- Comercio exterior de calzado ----------

FLOW_ALIASES = {
    "importacion": "Importación", "importaciones": "Importación", "import": "Importación",
    "imports": "Importación", "m": "Importación",
    "exportacion": "Exportación", "exportaciones": "Exportación", "export": "Exportación",
    "exports": "Exportación", "x": "Exportación",
    "reexportacion": "Reexportación", "re_export": "Reexportación", "reexport": "Reexportación",
    "reimportacion": "Reimportación", "re_import": "Reimportación", "reimport": "Reimportación",
}
AGGREGATE_PARTNERS = {"mundo", "world", "total", "todos", "all", "total_mundo", "otros_no_especificados"}
TOLERANCE = Decimal("0.01")  # 1 % de diferencia relativa


def relative_gap(a, b):
    if a is None or b is None:
        return None
    base = max(abs(a), abs(b))
    return Decimal(0) if base == 0 else abs(a - b) / base


class TradeValidator(TableValidator):
    columns = {
        "pais_reportante": (True, ("reporter", "pais")),
        "flujo_comercial": (True, ("flujo", "flow", "trade_flow")),
        "ano": (True, ("anio", "year", "periodo")),
        "codigo_sa6": (True, ("sa6", "hs6", "codigo_hs", "hs_code")),
        "categoria_calzado": (False, ("categoria", "category")),
        "socio_comercial": (True, ("socio", "partner")),
        "valor_miles_usd": (False, ("valor_miles", "trade_value_thousand_usd")),
        "cantidad_pares": (False, ("cantidad", "quantity", "pares")),
        "valor_usd": (False, ("valor", "trade_value_usd", "value_usd")),
        "valor_usd_por_par": (False, ("valor_por_par", "usd_por_par")),
    }

    def validate_row(self, record, row):
        clean = {"quality_flags": [], "occurrence": 1}
        reporter = self.value(record, "pais_reportante")
        partner = self.value(record, "socio_comercial")
        for name, value, limit in (("pais_reportante", reporter, 100), ("socio_comercial", partner, 150)):
            if not value:
                self.issue(row, name, "error", "Campo obligatorio vacío.")
            elif len(value) > limit:
                self.issue(row, name, "error", f"Máximo {limit} caracteres.")
        clean["reporter"], clean["partner"] = reporter, partner
        clean["is_aggregate"] = bool(partner) and normalize_header(partner) in AGGREGATE_PARTNERS

        flow_raw = self.value(record, "flujo_comercial")
        flow = FLOW_ALIASES.get(normalize_header(flow_raw or ""))
        if not flow:
            self.issue(row, "flujo_comercial", "error",
                       f"Flujo '{flow_raw}' no reconocido (se esperan Importación/Exportación/Reexportación/Reimportación).")
        clean["flow"] = flow

        year_raw = self.value(record, "ano")
        try:
            year = parse_number(year_raw)
            if year is None or year != year.to_integral_value() or not 1900 <= year <= date.today().year:
                raise ValueError
            clean["year"] = int(year)
        except ValueError:
            self.issue(row, "ano", "error", f"Año '{year_raw}' no válido (1900–{date.today().year}).")

        hs = (self.value(record, "codigo_sa6") or "").replace(" ", "").replace(".", "")
        if hs.endswith("0") and len(hs) == 7 and (self.value(record, "codigo_sa6") or "").endswith(".0"):
            hs = hs[:-1]  # número de Excel leído como '640399.0'
        if not re.fullmatch(r"\d{6}", hs):
            self.issue(row, "codigo_sa6", "error",
                       f"Código SA6 '{self.value(record, 'codigo_sa6')}' no válido: deben ser 6 dígitos.")
        elif not hs.startswith("64"):
            self.issue(row, "codigo_sa6", "advertencia", "El código SA6 no pertenece al capítulo 64 (calzado).")
        clean["hs6_code"] = hs
        category = self.value(record, "categoria_calzado")
        clean["category"] = category[:200] if category else None

        numbers = {}
        for name in ("valor_miles_usd", "cantidad_pares", "valor_usd", "valor_usd_por_par"):
            try:
                numbers[name] = parse_number(self.value(record, name))
            except ValueError as error:
                self.issue(row, name, "error", str(error))
                numbers[name] = None
                continue
            if numbers[name] is not None and numbers[name] < 0:
                self.issue(row, name, "error", "No puede ser negativo.")

        thousand, qty, value, per_pair_src = (numbers["valor_miles_usd"], numbers["cantidad_pares"],
                                              numbers["valor_usd"], numbers["valor_usd_por_par"])
        if value is not None and thousand is not None:
            gap = relative_gap(value, thousand * 1000)
            if gap is not None and gap > TOLERANCE:
                self.issue(row, "valor_usd", "advertencia",
                           f"Valor_USD ({value}) no coincide con Valor_miles_USD × 1000 ({thousand * 1000}). "
                           "Se conserva Valor_USD tal como viene; revisa las unidades.")
                clean["quality_flags"].append("unidades_inconsistentes")
        elif value is None and thousand is not None:
            value = thousand * 1000
            clean["quality_flags"].append("valor_usd_derivado_de_miles")
        if value is None:
            clean["quality_flags"].append("sin_valor")
        if qty is None or qty == 0:
            clean["quality_flags"].append("sin_cantidad")

        per_pair = None
        if value is not None and qty is not None and qty > 0 and value > 0:
            per_pair = (value / qty).quantize(Decimal("0.0001"))
            gap = relative_gap(per_pair, per_pair_src)
            if gap is not None and gap > TOLERANCE:
                self.issue(row, "valor_usd_por_par", "advertencia",
                           f"Valor_USD_por_par del archivo ({per_pair_src}) difiere del recalculado ({per_pair}).")
                clean["quality_flags"].append("valor_por_par_inconsistente")
        clean.update({"value_thousand_usd": thousand, "quantity_pairs": qty, "value_usd": value,
                      "value_usd_per_pair_source": per_pair_src, "value_usd_per_pair": per_pair})
        return clean

    def after_rows(self):
        """Clave natural: (reportante, flujo, año, SA6, socio). Duplicados exactos se omiten; distintos se rechazan."""
        groups = {}
        for r in self.rows:
            key = (r["reporter"].lower(), r["flow"], r.get("year"), r["hs6_code"], r["partner"].lower())
            groups.setdefault(key, []).append(r)
        keep = []
        for rows in groups.values():
            first = rows[0]
            if len(rows) == 1:
                keep.append(first)
                continue
            signature = lambda r: (r["value_usd"], r["quantity_pairs"], r["value_thousand_usd"], r["category"])  # noqa: E731
            if all(signature(r) == signature(first) for r in rows):
                keep.append(first)
                for r in rows[1:]:
                    self.issue(r["_row"], None, "advertencia",
                               f"Fila duplicada exacta de la fila {first['_row']}: se omite.")
                    r["_omitted"] = True
            else:
                numbers = ", ".join(str(r["_row"]) for r in rows)
                if self.duplicate_policy == "separados":
                    for occurrence, r in enumerate(rows, start=1):
                        r["occurrence"] = occurrence
                        self.issue(r["_row"], None, "advertencia",
                                   f"Misma clave que las filas {numbers} con valores distintos: se conserva como "
                                   f"operación separada (ocurrencia {occurrence}) por la política elegida.")
                    keep.extend(rows)
                    continue
                for r in rows:
                    self.issue(r["_row"], None, "error",
                               f"Misma clave (reportante, flujo, año, SA6, socio) con valores distintos en las filas "
                               f"{numbers}. Revisa cuál es correcta o importa con la política «conservar como "
                               "operaciones separadas» si son operaciones distintas.")
        self.rows = [r for r in self.rows if not r.get("_omitted")]


VALIDATORS = {"catalogo": CatalogValidator, "comercio": TradeValidator}


def detect_kind(frame):
    """Elige el tipo cuyas columnas obligatorias encajan (contando encabezados truncados). None si ninguno."""
    best, best_score = None, None
    for kind, validator in VALIDATORS.items():
        missing, truncated = validator(frame).diagnose()
        score = len(missing) - len(truncated)  # un encabezado truncado reconocible cuenta como presente
        if best_score is None or score < best_score:
            best, best_score = kind, score
    return best if best_score == 0 else None

TEMPLATES = {
    "catalogo": list(CatalogValidator.columns),
    "comercio": ["País_reportante", "Flujo_comercial", "Año", "Código_SA6", "Categoría_calzado",
                 "Socio_comercial", "Valor_miles_USD", "Cantidad_pares", "Valor_USD", "Valor_USD_por_par"],
}
