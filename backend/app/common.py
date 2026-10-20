"""Utilidades compartidas: errores de API y validación de entrada."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    """ISO 8601 con zona. SQLite devuelve fechas sin zona: se guardaron en UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class ApiError(Exception):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details or {}


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("El cuerpo debe ser un objeto JSON.")
    return data


class Validator:
    """Acumula errores por campo y los devuelve todos juntos."""

    def __init__(self, data):
        self.data = data
        self.errors = {}
        self.clean = {}

    def text(self, field, required=False, max_len=200):
        value = self.data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                self.errors[field] = "Campo obligatorio."
            elif field in self.data:
                self.clean[field] = None
            return
        if not isinstance(value, str):
            self.errors[field] = "Debe ser texto."
            return
        value = value.strip()
        if len(value) > max_len:
            self.errors[field] = f"Máximo {max_len} caracteres."
            return
        self.clean[field] = value

    def money(self, field, required=False):
        value = self.data.get(field)
        if value is None or value == "":
            if required:
                self.errors[field] = "Campo obligatorio."
            elif field in self.data:
                self.clean[field] = None
            return
        if isinstance(value, bool):
            self.errors[field] = "Debe ser un número."
            return
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            self.errors[field] = "Debe ser un número."
            return
        if not amount.is_finite() or amount < 0:
            self.errors[field] = "Debe ser un número mayor o igual a 0."
            return
        self.clean[field] = amount.quantize(Decimal("0.01"))

    def integer(self, field, required=False, minimum=None):
        value = self.data.get(field)
        if value is None or value == "":
            if required:
                self.errors[field] = "Campo obligatorio."
            return
        if isinstance(value, bool) or not isinstance(value, int):
            self.errors[field] = "Debe ser un número entero."
            return
        if minimum is not None and value < minimum:
            self.errors[field] = f"Debe ser mayor o igual a {minimum}."
            return
        self.clean[field] = value

    def choice(self, field, options, required=False):
        value = self.data.get(field)
        if value is None:
            if required:
                self.errors[field] = "Campo obligatorio."
            return
        if value not in options:
            self.errors[field] = "Valor no permitido. Opciones: " + ", ".join(options)
            return
        self.clean[field] = value

    def raise_if_errors(self):
        if self.errors:
            raise ApiError("Datos no válidos.", 422, self.errors)
        return self.clean


def parse_date_range(from_name="from", to_name="to"):
    """Lee ?from=AAAA-MM-DD&to=AAAA-MM-DD (ambos incluidos). Devuelve datetimes UTC [inicio, fin)."""
    from datetime import date, timedelta

    def parse(name):
        raw = request.args.get(name)
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise ApiError(f"El parámetro '{name}' debe tener formato AAAA-MM-DD.")

    start, end = parse(from_name), parse(to_name)
    if start and end and end < start:
        raise ApiError("La fecha final es anterior a la inicial.")
    to_dt = lambda d: datetime(d.year, d.month, d.day, tzinfo=timezone.utc)  # noqa: E731
    return (to_dt(start) if start else None, to_dt(end + timedelta(days=1)) if end else None)


def query_int(name, default=None, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(f"El parámetro '{name}' debe ser un entero.")
    if minimum is not None and value < minimum:
        raise ApiError(f"El parámetro '{name}' debe ser >= {minimum}.")
    if maximum is not None:
        value = min(value, maximum)
    return value
