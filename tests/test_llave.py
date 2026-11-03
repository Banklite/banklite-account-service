"""Busqueda de cuenta por llave Bre-B: account-service consulta a identity-service y devuelve la cuenta activa."""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/db")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Cuenta  # noqa: E402

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Sesion = sessionmaker(bind=engine)
Base.metadata.create_all(engine)
ID_USUARIO = uuid.uuid4()


def _override():
    db = Sesion()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override
c = TestClient(app)

with Sesion() as s:
    s.add(Cuenta(id_usuario=ID_USUARIO, numero_cuenta="3136530762", tipo_cuenta="ahorros", moneda="COP", estado="activa"))
    s.commit()


def _identity(respuesta: httpx.Response):
    llamadas = []

    def fake_get(url, timeout=None):
        llamadas.append(url)
        return respuesta

    return fake_get, llamadas


def test_llave_encontrada_devuelve_la_cuenta_y_el_celular(monkeypatch):
    usuario = {"id_usuario": str(ID_USUARIO), "nombre": "Camilo", "apellido": "Beltran", "telefono": "+573136530762"}
    fake, llamadas = _identity(httpx.Response(200, json=usuario))
    monkeypatch.setattr(httpx, "get", fake)
    r = c.get("/accounts/by-llave/78028895")
    assert r.status_code == 200
    assert r.json()["nombre_titular"] == "Camilo Beltran" and r.json()["telefono"] == "3136530762"
    assert llamadas[0].endswith("/users/by-llave/78028895")


def test_llave_con_arroba_se_codifica_en_la_url(monkeypatch):
    fake, llamadas = _identity(httpx.Response(404, json={"detail": "no"}))
    monkeypatch.setattr(httpx, "get", fake)
    r = c.get("/accounts/by-llave/camilo@mail.com")
    assert r.status_code == 404
    assert llamadas[0].endswith("/users/by-llave/camilo%40mail.com")
