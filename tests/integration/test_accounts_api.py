"""Pruebas de INTEGRACION de account-service: endpoint + reglas de negocio + base de datos.

La base es SQLite en memoria. identity-service (otro microservicio) se reemplaza con un mock.
"""
import uuid
from unittest.mock import patch

import pytest

from app import consumer
from app.identity_client import IdentityUnavailable
from app.models import Cuenta, LimiteOperativo, RestriccionRegulatoria, UsuarioVerificado

ID_USUARIO = uuid.uuid4()
USUARIO_CO = {"id_usuario": str(ID_USUARIO), "estado": "verificado", "pais_residencia": "CO",
              "nombre": "Juan", "apellido": "Rhenals", "telefono": "+573001234567"}


@pytest.fixture
def identity():
    with patch("app.routers.accounts.get_user", return_value=dict(USUARIO_CO)) as mock:
        yield mock


def _abrir(client, id_usuario=ID_USUARIO, **extra):
    return client.post("/accounts", json={"id_usuario": str(id_usuario), **extra})


# --- Apertura de cuenta ----------------------------------------------------------------------

def test_abrir_cuenta_crea_la_cuenta_sus_limites_y_su_restriccion(client, sesiones, identity):
    r = _abrir(client)

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["cuenta"]["estado"] == "activa" and cuerpo["cuenta"]["moneda"] == "COP"
    assert cuerpo["cuenta"]["numero_cuenta"] == "3001234567"  # el celular del titular es el numero de cuenta
    assert {(l["tipo_limite"], l["monto_maximo"]) for l in cuerpo["limites"]} == {("diario", "5000000.00"), ("mensual", "50000000.00")}
    assert cuerpo["restriccion"]["pais"] == "CO"
    assert cuerpo["validado_via"].startswith("identity-service") and cuerpo["evento_proyeccion_encontrada"] is False
    with sesiones() as db:
        assert db.query(Cuenta).count() == 1
        assert db.query(LimiteOperativo).count() == 2
        assert db.query(RestriccionRegulatoria).count() == 1
    identity.assert_called_once_with(ID_USUARIO)


def test_un_usuario_no_puede_tener_dos_cuentas_en_la_misma_moneda(client, sesiones, identity):
    assert _abrir(client).status_code == 201

    r = _abrir(client)

    assert r.status_code == 409 and "ya tiene una cuenta" in r.json()["detail"]
    with sesiones() as db:
        assert db.query(Cuenta).count() == 1


@pytest.mark.parametrize("usuario, moneda, esperado, texto", [
    (None, None, 404, "no existe"),
    ({**USUARIO_CO, "estado": "pendiente"}, None, 409, "verificacion KYC"),
    ({**USUARIO_CO, "pais_residencia": "VE"}, None, 400, "no esta habilitado"),
    (USUARIO_CO, "USD", 400, "no corresponde al pais"),
])
def test_reglas_que_impiden_abrir_la_cuenta(client, sesiones, identity, usuario, moneda, esperado, texto):
    identity.return_value = usuario

    r = _abrir(client, **({"moneda": moneda} if moneda else {}))

    assert r.status_code == esperado and texto in r.json()["detail"]
    with sesiones() as db:
        assert db.query(Cuenta).count() == 0


def test_identity_service_caido_responde_503(client, identity):
    identity.side_effect = IdentityUnavailable("timeout")
    assert _abrir(client).status_code == 503


def test_si_el_celular_ya_es_numero_de_otra_cuenta_se_genera_uno_nuevo(client, identity):
    primera = _abrir(client).json()["cuenta"]
    otro = uuid.uuid4()
    identity.return_value = {**USUARIO_CO, "id_usuario": str(otro)}

    segunda = _abrir(client, otro).json()["cuenta"]

    assert segunda["numero_cuenta"] != primera["numero_cuenta"] and len(segunda["numero_cuenta"]) == 10


def test_evento_identity_verified_alimenta_la_proyeccion_local(client, sesiones, identity):
    """Comunicacion asincrona: el evento llega antes y la apertura lo encuentra."""
    evento = {"id_usuario": str(ID_USUARIO), "email": "juan@example.com", "pais_residencia": "CO", "verificado_en": "2026-11-10"}
    with patch("app.consumer.SessionLocal", sesiones):
        consumer._handle_identity_verified(evento)
        consumer._handle_identity_verified({**evento, "email": "nuevo@example.com"})  # repetido: actualiza, no duplica

    with sesiones() as db:
        assert db.query(UsuarioVerificado).one().email == "nuevo@example.com"
    assert _abrir(client).json()["evento_proyeccion_encontrada"] is True
    assert client.get("/verified-users").json()[0]["pais_residencia"] == "CO"


def test_evento_transfer_completed_se_guarda_una_sola_vez(client, sesiones):
    evento = {"id_transferencia": str(uuid.uuid4()), "id_cuenta_origen": str(uuid.uuid4()), "monto": "150000.00"}
    with patch("app.consumer.SessionLocal", sesiones):
        consumer._handle_transfer_completed(evento)
        consumer._handle_transfer_completed(evento)

    recibidas = client.get("/transfers-received").json()
    assert len(recibidas) == 1 and recibidas[0]["estado"] == "completada"


# --- Consulta y cambio de estado -------------------------------------------------------------

def test_consultar_listar_y_ver_limites(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]

    assert client.get(f"/accounts/{id_cuenta}").json()["id_usuario"] == str(ID_USUARIO)
    assert len(client.get("/accounts", params={"id_usuario": str(ID_USUARIO)}).json()) == 1
    assert client.get("/accounts", params={"id_usuario": str(uuid.uuid4())}).json() == []
    assert len(client.get(f"/accounts/{id_cuenta}/limits").json()) == 2
    assert client.get(f"/accounts/{uuid.uuid4()}").status_code == 404


def test_suspender_reactivar_y_cerrar_una_cuenta(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]

    assert client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "suspendida"}).json()["estado"] == "suspendida"
    assert client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "activa"}).json()["estado"] == "activa"
    assert client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "cerrada"}).json()["estado"] == "cerrada"
    # Una cuenta cerrada no se puede reabrir
    reabrir = client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "activa"})
    assert reabrir.status_code == 409
    assert client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "congelada"}).status_code == 422


def test_busqueda_por_numero_solo_expone_datos_publicos(client, identity):
    cuenta = _abrir(client).json()["cuenta"]

    r = client.get("/accounts/by-numero/300-123 4567")  # se ignoran espacios y guiones

    assert r.status_code == 200
    assert r.json() == {
        "id_cuenta": cuenta["id_cuenta"], "numero_cuenta_enmascarado": "****4567",
        "tipo_cuenta": "ahorros", "moneda": "COP", "nombre_titular": "Juan Rhenals",
    }
    assert client.get("/accounts/by-numero/9999999999").status_code == 404


def test_una_cuenta_suspendida_no_puede_recibir_dinero(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]
    client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "suspendida"})

    assert client.get("/accounts/by-numero/3001234567").status_code == 409
    assert client.get(f"/accounts/{id_cuenta}/public").status_code == 409


# --- Bolsillos de ahorro ---------------------------------------------------------------------

def test_ciclo_de_un_bolsillo_de_ahorro(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]

    bolsillo = client.post(f"/accounts/{id_cuenta}/bolsillos", json={"nombre": "Viaje", "monto_meta": "1000000"})
    assert bolsillo.status_code == 201 and bolsillo.json()["saldo_actual"] == "0.00"
    id_bolsillo = bolsillo.json()["id_bolsillo"]

    metido = client.post(f"/accounts/bolsillos/{id_bolsillo}/meter-plata", json={"monto": "250000"})
    assert metido.json()["saldo_actual"] == "250000.00" and metido.json()["progreso_porcentaje"] == 25.0

    de_mas = client.post(f"/accounts/bolsillos/{id_bolsillo}/sacar-plata", json={"monto": "300000"})
    assert de_mas.status_code == 400 and "Saldo insuficiente" in de_mas.json()["detail"]

    sacado = client.post(f"/accounts/bolsillos/{id_bolsillo}/sacar-plata", json={"monto": "50000"})
    assert sacado.json()["saldo_actual"] == "200000.00"
    assert len(client.get(f"/accounts/{id_cuenta}/bolsillos").json()) == 1

    assert client.delete(f"/accounts/bolsillos/{id_bolsillo}").status_code == 204
    assert client.get(f"/accounts/{id_cuenta}/bolsillos").json() == []
    assert client.delete(f"/accounts/bolsillos/{id_bolsillo}").status_code == 404


def test_bolsillo_con_candado_no_deja_sacar_plata(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]
    id_bolsillo = client.post(f"/accounts/{id_cuenta}/bolsillos", json={"nombre": "Emergencias", "bloqueado": True}).json()["id_bolsillo"]
    client.post(f"/accounts/bolsillos/{id_bolsillo}/meter-plata", json={"monto": "100000"})

    r = client.post(f"/accounts/bolsillos/{id_bolsillo}/sacar-plata", json={"monto": "10000"})

    assert r.status_code == 400 and "bloqueado" in r.json()["detail"]


def test_cuenta_suspendida_no_crea_bolsillos_ni_codigos_de_retiro(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]
    client.patch(f"/accounts/{id_cuenta}/status", json={"estado": "suspendida"})

    assert client.post(f"/accounts/{id_cuenta}/bolsillos", json={"nombre": "Viaje"}).status_code == 400
    assert client.post(f"/accounts/{id_cuenta}/retiro-token", json={"monto": "50000"}).status_code == 400


# --- Retiro sin tarjeta ----------------------------------------------------------------------

def test_codigo_de_retiro_tiene_seis_digitos_y_queda_activo(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]

    r = client.post(f"/accounts/{id_cuenta}/retiro-token", json={"monto": "200000"})

    assert r.status_code == 201
    token = r.json()
    assert len(token["codigo_retiro"]) == 6 and token["codigo_retiro"].isdigit()
    assert token["estado"] == "activo" and token["monto"] == "200000.00"


def test_codigo_de_retiro_equivocado_o_con_otro_monto_se_rechaza(client, identity):
    id_cuenta = _abrir(client).json()["cuenta"]["id_cuenta"]
    token = client.post(f"/accounts/{id_cuenta}/retiro-token", json={"monto": "200000"}).json()

    otro_monto = client.post("/accounts/retiro-token/verificar", json={"codigo_retiro": token["codigo_retiro"], "monto": "999"})
    otro_codigo = client.post("/accounts/retiro-token/verificar", json={"codigo_retiro": "000000" if token["codigo_retiro"] != "000000" else "111111", "monto": "200000"})

    assert otro_monto.status_code == 404 and otro_codigo.status_code == 404
