"""Pruebas UNITARIAS de la comunicacion con otros servicios, usando mocks.

- Cliente REST hacia identity-service (httpx.get simulado).
- Despacho de eventos de RabbitMQ (canal y handlers simulados).
"""
import json
import uuid
from unittest.mock import Mock, patch

import httpx
import pytest

from app import consumer
from app.identity_client import IdentityUnavailable, get_user

ID_USUARIO = uuid.uuid4()


def _respuesta(status: int, cuerpo: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=cuerpo or {}, request=httpx.Request("GET", "http://identity-service"))


@patch("app.identity_client.httpx.get")
def test_usuario_existente(mock_get: Mock):
    mock_get.return_value = _respuesta(200, {"id_usuario": str(ID_USUARIO), "estado": "verificado", "pais_residencia": "CO"})

    usuario = get_user(ID_USUARIO)

    assert usuario["estado"] == "verificado"
    assert mock_get.call_args.args[0].endswith(f"/users/{ID_USUARIO}")


@patch("app.identity_client.httpx.get")
def test_usuario_inexistente_devuelve_none(mock_get: Mock):
    mock_get.return_value = _respuesta(404)
    assert get_user(ID_USUARIO) is None


@patch("app.identity_client.httpx.get")
def test_identity_caido_o_con_error_5xx(mock_get: Mock):
    mock_get.side_effect = httpx.ConnectTimeout("timeout")
    with pytest.raises(IdentityUnavailable):
        get_user(ID_USUARIO)

    mock_get.side_effect = None
    mock_get.return_value = _respuesta(500)
    with pytest.raises(IdentityUnavailable, match="500"):
        get_user(ID_USUARIO)


def _mensaje(routing_key: str, cuerpo: dict):
    canal, metodo = Mock(), Mock(routing_key=routing_key, delivery_tag=7)
    return canal, metodo, json.dumps(cuerpo).encode("utf-8")


def test_cada_evento_va_a_su_handler_y_se_confirma():
    with (
        patch("app.consumer._handle_identity_verified") as verificado,
        patch("app.consumer._handle_transfer_completed") as transferencia,
    ):
        canal, metodo, cuerpo = _mensaje("identity.verified", {"id_usuario": str(ID_USUARIO)})
        consumer._on_message(canal, metodo, None, cuerpo)
        canal2, metodo2, cuerpo2 = _mensaje("transfer.completed", {"id_transferencia": "t1"})
        consumer._on_message(canal2, metodo2, None, cuerpo2)

    verificado.assert_called_once_with({"id_usuario": str(ID_USUARIO)})
    transferencia.assert_called_once_with({"id_transferencia": "t1"})
    canal.basic_ack.assert_called_once_with(delivery_tag=7)
    canal2.basic_ack.assert_called_once_with(delivery_tag=7)


def test_evento_que_falla_se_descarta_sin_reencolar():
    with patch("app.consumer._handle_identity_verified", side_effect=KeyError("email")):
        canal, metodo, cuerpo = _mensaje("identity.verified", {"id_usuario": str(ID_USUARIO)})
        consumer._on_message(canal, metodo, None, cuerpo)

    canal.basic_nack.assert_called_once_with(delivery_tag=7, requeue=False)
    canal.basic_ack.assert_not_called()
