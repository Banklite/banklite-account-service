"""Pruebas UNITARIAS de reglas puras: limites regulatorios por pais y validacion de datos de entrada."""
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.limits import SUPPORTED_COUNTRIES, limits_for
from app.schemas import AccountCreate, AccountStatusUpdate, BolsilloMovimiento, TokenRetiroCobro


def test_limites_de_colombia():
    limites = limits_for("CO")
    assert limites == {"currency": "COP", "daily_limit": Decimal("5000000.00"), "monthly_limit": Decimal("50000000.00")}


@pytest.mark.parametrize("pais, moneda", [("co", "COP"), ("Mx", "MXN"), ("US", "USD"), ("es", "EUR"), ("pe", "PEN")])
def test_el_pais_no_distingue_mayusculas(pais, moneda):
    assert limits_for(pais)["currency"] == moneda


@pytest.mark.parametrize("pais", ["VE", "XX", ""])
def test_pais_no_habilitado_no_tiene_limites(pais):
    assert limits_for(pais) is None


def test_el_limite_mensual_siempre_es_diez_veces_el_diario():
    for pais in SUPPORTED_COUNTRIES:
        limites = limits_for(pais)
        assert limites["monthly_limit"] == limites["daily_limit"] * 10


def test_la_moneda_se_normaliza_a_mayusculas_y_es_opcional():
    assert AccountCreate(id_usuario=uuid.uuid4(), moneda="cop").moneda == "COP"
    assert AccountCreate(id_usuario=uuid.uuid4()).moneda is None


@pytest.mark.parametrize("moneda", ["C0P", "CO", "PESOS", "$$$"])
def test_moneda_que_no_es_codigo_iso_se_rechaza(moneda):
    with pytest.raises(ValidationError):
        AccountCreate(id_usuario=uuid.uuid4(), moneda=moneda)


def test_solo_se_aceptan_los_tres_estados_de_cuenta():
    for estado in ("activa", "suspendida", "cerrada"):
        assert AccountStatusUpdate(estado=estado).estado == estado
    with pytest.raises(ValidationError, match="estado debe ser uno de"):
        AccountStatusUpdate(estado="congelada")


def test_montos_y_codigo_de_retiro_invalidos():
    with pytest.raises(ValidationError):
        BolsilloMovimiento(monto=Decimal("0"))
    with pytest.raises(ValidationError):
        TokenRetiroCobro(codigo_retiro="12345", monto=Decimal("50000"))  # el codigo es de 6 digitos
