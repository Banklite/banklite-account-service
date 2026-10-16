import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountCreate(BaseModel):
    id_usuario: uuid.UUID
    moneda: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description="Opcional. Si se omite se usa la moneda regulatoria del pais del usuario.",
    )

    @field_validator("moneda")
    @classmethod
    def moneda_upper(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.isalpha():
            raise ValueError("moneda debe ser un codigo ISO de 3 letras, por ejemplo COP")
        return v.upper()


class LimiteOperativoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_limite: uuid.UUID
    tipo_limite: str
    monto_maximo: Decimal
    periodo: str


class RestriccionRegulatoriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_restriccion: uuid.UUID
    pais: str
    descripcion: str | None
    fecha_aplicacion: date


class CuentaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_cuenta: uuid.UUID
    numero_cuenta: str | None = None
    id_usuario: uuid.UUID
    tipo_cuenta: str
    moneda: str
    estado: str
    fecha_apertura: datetime
    fecha_cierre: datetime | None


class CuentaCreada(BaseModel):
    cuenta: CuentaOut
    limites: list[LimiteOperativoOut]
    restriccion: RestriccionRegulatoriaOut
    validado_via: str
    evento_proyeccion_encontrada: bool


class AccountStatusUpdate(BaseModel):
    estado: str

    @field_validator("estado")
    @classmethod
    def estado_valido(cls, v: str) -> str:
        allowed = {"activa", "suspendida", "cerrada"}
        if v not in allowed:
            raise ValueError(f"estado debe ser uno de: {', '.join(sorted(allowed))}")
        return v


class UsuarioVerificadoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_usuario: uuid.UUID
    email: str
    pais_residencia: str
    verificado_en: str
    recibido_en: datetime


class TransferenciaRecibidaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_transferencia: uuid.UUID
    id_cuenta_origen: uuid.UUID
    monto: Decimal
    estado: str
    recibido_en: datetime


class BolsilloCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    emoji: str = Field(default="💰", max_length=16)
    monto_meta: Decimal | None = None
    bloqueado: bool = False


class BolsilloOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_bolsillo: uuid.UUID
    id_cuenta: uuid.UUID
    nombre: str
    emoji: str
    monto_meta: Decimal | None
    saldo_actual: Decimal
    bloqueado: bool
    fecha_creacion: datetime
    progreso_porcentaje: float | None = None


class BolsilloMovimiento(BaseModel):
    monto: Decimal = Field(gt=0)


class TokenRetiroCreate(BaseModel):
    monto: Decimal = Field(gt=0)


class TokenRetiroOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_token: uuid.UUID
    id_cuenta: uuid.UUID
    codigo_retiro: str
    monto: Decimal
    estado: str
    fecha_creacion: datetime
    fecha_expiracion: datetime


class TokenRetiroCobro(BaseModel):
    codigo_retiro: str = Field(min_length=6, max_length=6)
    monto: Decimal = Field(gt=0)

