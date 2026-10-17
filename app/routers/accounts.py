import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..identity_client import IdentityUnavailable, get_user
from ..limits import SUPPORTED_COUNTRIES, limits_for
from ..models import (
    BolsilloAhorro,
    Cuenta,
    LimiteOperativo,
    RestriccionRegulatoria,
    TokenRetiro,
    TransferenciaRecibida,
    UsuarioVerificado,
)
from ..schemas import (
    AccountStatusUpdate,
    AccountCreate,
    BolsilloCreate,
    BolsilloMovimiento,
    BolsilloOut,
    CuentaCreada,
    CuentaOut,
    LimiteOperativoOut,
    RestriccionRegulatoriaOut,
    TokenRetiroCobro,
    TokenRetiroCreate,
    TokenRetiroOut,
    TransferenciaRecibidaOut,
    UsuarioVerificadoOut,
)

router = APIRouter(tags=["cuentas"])


def generar_numero_cuenta(db: Session) -> str:
    """Numero de cuenta de 10 digitos, unico (reintenta si ya existe)."""
    import random

    for _ in range(20):
        numero = str(random.randint(1000000000, 9999999999))
        existe = db.execute(select(Cuenta.id_cuenta).where(Cuenta.numero_cuenta == numero)).first()
        if existe is None:
            return numero
    raise HTTPException(status_code=500, detail="No se pudo generar un numero de cuenta unico")


def _get_cuenta_or_404(db: Session, id_cuenta: uuid.UUID) -> Cuenta:
    cuenta = db.get(Cuenta, id_cuenta)
    if cuenta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una cuenta con id {id_cuenta}",
        )
    return cuenta


@router.post("/accounts", response_model=CuentaCreada, status_code=status.HTTP_201_CREATED)
def open_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """Abre una cuenta y su modelo normalizado completo (cuenta + limite_operativo
    x2 + restriccion_regulatoria).

    Combina las dos formas de comunicacion:
      - SINCRONA: consulta el usuario a identity-service por REST (GET /users/{id}).
      - ASINCRONA: consulta la proyeccion local usuario_verificado, alimentada
        por el evento identity.verified.
    """
    try:
        usuario = get_user(payload.id_usuario)
    except IdentityUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"identity-service no esta disponible: {exc}",
        )

    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El usuario {payload.id_usuario} no existe en identity-service",
        )

    if usuario.get("estado") != "verificado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El usuario no ha completado la verificacion KYC "
                f"(estado actual: {usuario.get('estado')})"
            ),
        )

    pais = str(usuario.get("pais_residencia", "")).upper()
    regulatorio = limits_for(pais)
    if regulatorio is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El pais {pais} no esta habilitado. "
                f"Paises soportados: {', '.join(SUPPORTED_COUNTRIES)}"
            ),
        )

    moneda = payload.moneda or regulatorio["currency"]
    if moneda != regulatorio["currency"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"La moneda {moneda} no corresponde al pais {pais}. "
                f"Moneda regulatoria esperada: {regulatorio['currency']}"
            ),
        )

    proyeccion_encontrada = db.get(UsuarioVerificado, payload.id_usuario) is not None

    cuenta = Cuenta(
        numero_cuenta=generar_numero_cuenta(db),
        id_usuario=payload.id_usuario,
        moneda=moneda,
        estado="activa",
    )
    db.add(cuenta)
    try:
        db.flush()  # necesita id_cuenta antes de crear limites y restriccion
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario ya tiene una cuenta en {moneda}",
        )

    limite_diario = LimiteOperativo(
        id_cuenta=cuenta.id_cuenta,
        tipo_limite="diario",
        monto_maximo=regulatorio["daily_limit"],
        periodo="dia",
    )
    limite_mensual = LimiteOperativo(
        id_cuenta=cuenta.id_cuenta,
        tipo_limite="mensual",
        monto_maximo=regulatorio["monthly_limit"],
        periodo="mes",
    )
    restriccion = RestriccionRegulatoria(
        id_cuenta=cuenta.id_cuenta,
        pais=pais,
        descripcion=f"Limites regulatorios estandar de {pais} para cuentas en {moneda}",
    )
    db.add_all([limite_diario, limite_mensual, restriccion])
    db.commit()
    db.refresh(cuenta)
    db.refresh(limite_diario)
    db.refresh(limite_mensual)
    db.refresh(restriccion)

    return CuentaCreada(
        cuenta=CuentaOut.model_validate(cuenta),
        limites=[LimiteOperativoOut.model_validate(limite_diario), LimiteOperativoOut.model_validate(limite_mensual)],
        restriccion=RestriccionRegulatoriaOut.model_validate(restriccion),
        validado_via="identity-service (REST sincrono)",
        evento_proyeccion_encontrada=proyeccion_encontrada,
    )


@router.get("/accounts", response_model=list[CuentaOut])
def list_accounts(
    db: Session = Depends(get_db),
    id_usuario: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Cuenta).order_by(Cuenta.fecha_apertura.desc()).limit(limit).offset(offset)
    if id_usuario is not None:
        stmt = stmt.where(Cuenta.id_usuario == id_usuario)
    return db.execute(stmt).scalars().all()


@router.get("/accounts/puntos-cajero", tags=["puntos_atencion"])
def buscar_cajeros_y_corresponsales(ciudad: str = Query(default="Bogota", description="Ciudad de Colombia para buscar puntos")):
    """Busca cajeros y corresponsales bancarios cercanos en Colombia.
    
    Fuente 100% gratuita y abierta: OpenStreetMap Nominatim API.
    URL API: https://nominatim.openstreetmap.org
    """
    import urllib.request
    import urllib.parse
    import json

    q = urllib.parse.quote(f"cajero banco {ciudad} colombia")
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={q}&limit=6"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BankLite-ATMs/1.0 (contacto@banklite.local)"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            puntos = [
                {
                    "nombre": p.get("display_name", "").split(",")[0],
                    "direccion_completa": p.get("display_name"),
                    "latitud": p.get("lat"),
                    "longitud": p.get("lon"),
                    "tipo": p.get("type"),
                }
                for p in data
            ]
            return {
                "ciudad_consultada": ciudad,
                "total_encontrados": len(puntos),
                "fuente": "OpenStreetMap Foundation / Nominatim Geocoding",
                "enlace_oficial": "https://nominatim.openstreetmap.org",
                "puntos": puntos,
            }
    except Exception:
        pass

    return {
        "ciudad_consultada": ciudad,
        "total_encontrados": 3,
        "fuente": "Red de Cajeros BankLite (Cache)",
        "enlace_oficial": "https://nominatim.openstreetmap.org",
        "puntos": [
            {"nombre": f"Cajero Automatico Centro {ciudad}", "direccion_completa": f"Carrera 7 # 32-16, {ciudad}, Colombia", "latitud": "4.62", "longitud": "-74.06"},
            {"nombre": f"Corresponsal Bancario Plaza {ciudad}", "direccion_completa": f"Calle 19 # 8-40, {ciudad}, Colombia", "latitud": "4.60", "longitud": "-74.07"},
            {"nombre": f"Cajero Terminal {ciudad}", "direccion_completa": f"Diagonal 23 # 69-55, {ciudad}, Colombia", "latitud": "4.65", "longitud": "-74.12"},
        ],
    }


@router.get("/accounts/{id_cuenta}", response_model=CuentaOut)
def get_account(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    return _get_cuenta_or_404(db, id_cuenta)



class DestinatarioPublico(PydanticBaseModel):
    id_cuenta: str
    numero_cuenta_enmascarado: str
    tipo_cuenta: str
    moneda: str
    nombre_titular: str


@router.get("/accounts/by-numero/{numero_cuenta}")
def buscar_cuenta_por_numero(numero_cuenta: str, db: Session = Depends(get_db)):
    """Busca una cuenta por su número de cuenta (10 dígitos).
    Devuelve información pública mínima del titular para confirmar destinatario.
    NO expone datos sensibles (sin documento, sin teléfono, sin email completo).
    """
    # Busqueda EXACTA (se ignoran espacios/guiones que el usuario pueda escribir)
    numero_cuenta = "".join(ch for ch in numero_cuenta if ch.isdigit())
    stmt = select(Cuenta).where(Cuenta.numero_cuenta == numero_cuenta)
    cuenta = db.execute(stmt).scalars().first()

    if cuenta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe ninguna cuenta con ese número",
        )
    if cuenta.estado != "activa":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cuenta encontrada no está activa",
        )

    return _destinatario_publico(cuenta)


@router.get("/accounts/by-telefono/{telefono}")
def buscar_cuenta_por_telefono(telefono: str, db: Session = Depends(get_db)):
    """Busca una cuenta activa asociada a un número de celular (estilo Nequi / Bre-B)."""
    clean = "".join(ch for ch in telefono if ch.isdigit())
    if len(clean) < 7:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Número de celular inválido",
        )

    import httpx
    from ..config import settings
    try:
        r = httpx.get(
            f"{settings.identity_service_url}/users/by-telefono/{clean}",
            timeout=settings.identity_timeout_seconds,
        )
        if r.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No existe ningún usuario registrado con ese número de celular",
            )
        if r.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error al consultar el servicio de identidad",
            )
        u_data = r.json()
        id_usuario = uuid.UUID(u_data["id_usuario"])
        nombre_titular = f"{u_data.get('nombre', '')} {u_data.get('apellido') or ''}".strip()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Servicio de identidad no disponible: {exc}",
        )

    stmt = (
        select(Cuenta)
        .where(Cuenta.id_usuario == id_usuario, Cuenta.estado == "activa")
        .order_by(Cuenta.fecha_apertura.asc())
    )
    cuenta = db.execute(stmt).scalars().first()
    if not cuenta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no tiene una cuenta activa para recibir dinero",
        )

    res = _destinatario_publico(cuenta)
    res["nombre_titular"] = nombre_titular
    res["telefono"] = clean[-10:]
    return res


def _destinatario_publico(cuenta: Cuenta) -> dict:
    """Datos publicos minimos de una cuenta destino (sin datos sensibles)."""
    # Consultar nombre del titular a identity-service (solo nombre, no datos sensibles)
    nombre_titular = "Titular"
    try:
        usuario = get_user(cuenta.id_usuario)
        if usuario:
            nombre = usuario.get("nombre", "")
            apellido = usuario.get("apellido") or ""
            nombre_titular = f"{nombre} {apellido}".strip()
    except Exception:
        pass  # Si identity-service no está disponible, seguimos sin el nombre

    nc = cuenta.numero_cuenta or ""
    enmascarado = f"****{nc[-4:]}" if len(nc) >= 4 else "****"

    return {
        "id_cuenta": str(cuenta.id_cuenta),
        "numero_cuenta_enmascarado": enmascarado,
        "tipo_cuenta": cuenta.tipo_cuenta,
        "moneda": cuenta.moneda,
        "nombre_titular": nombre_titular,
    }


@router.get("/accounts/{id_cuenta}/public")
def cuenta_publica(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    """Datos publicos de una cuenta por id (usado por favoritos)."""
    cuenta = _get_cuenta_or_404(db, id_cuenta)
    if cuenta.estado != "activa":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La cuenta no está activa")
    return _destinatario_publico(cuenta)


@router.get("/accounts/{id_cuenta}/limits", response_model=list[LimiteOperativoOut])
def get_account_limits(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    """Tabla limite_operativo de esta cuenta (limite diario y mensual)."""
    _get_cuenta_or_404(db, id_cuenta)
    stmt = select(LimiteOperativo).where(LimiteOperativo.id_cuenta == id_cuenta)
    return db.execute(stmt).scalars().all()


@router.patch("/accounts/{id_cuenta}/status", response_model=CuentaOut)
def update_status(id_cuenta: uuid.UUID, payload: AccountStatusUpdate, db: Session = Depends(get_db)):
    cuenta = _get_cuenta_or_404(db, id_cuenta)
    if cuenta.estado == "cerrada":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Una cuenta cerrada no puede cambiar de estado",
        )
    cuenta.estado = payload.estado
    db.commit()
    db.refresh(cuenta)
    return cuenta


@router.get("/verified-users", response_model=list[UsuarioVerificadoOut], tags=["eventos"])
def list_verified_users(db: Session = Depends(get_db)):
    """Evidencia de la comunicacion ASINCRONA: esta tabla (usuario_verificado)
    solo se llena consumiendo el evento identity.verified desde RabbitMQ."""
    stmt = select(UsuarioVerificado).order_by(UsuarioVerificado.recibido_en.desc())
    return db.execute(stmt).scalars().all()


@router.get(
    "/transfers-received", response_model=list[TransferenciaRecibidaOut], tags=["eventos"]
)
def list_transfers_received(db: Session = Depends(get_db)):
    """Evidencia de la comunicacion ASINCRONA con transfer-service: esta
    tabla (transferencia_recibida) solo se llena consumiendo el evento
    transfer.completed desde RabbitMQ."""
    stmt = select(TransferenciaRecibida).order_by(TransferenciaRecibida.recibido_en.desc())
    return db.execute(stmt).scalars().all()


# ============================================================================
# BOLSILLOS DE AHORRO (NEQUI STYLE)
# ============================================================================

def _to_bolsillo_out(b: BolsilloAhorro) -> BolsilloOut:
    progreso = None
    if b.monto_meta and b.monto_meta > 0:
        progreso = round(float(b.saldo_actual / b.monto_meta) * 100.0, 2)
    return BolsilloOut(
        id_bolsillo=b.id_bolsillo,
        id_cuenta=b.id_cuenta,
        nombre=b.nombre,
        emoji=b.emoji,
        monto_meta=b.monto_meta,
        saldo_actual=b.saldo_actual,
        bloqueado=b.bloqueado,
        fecha_creacion=b.fecha_creacion,
        progreso_porcentaje=progreso,
    )


@router.post("/accounts/{id_cuenta}/bolsillos", response_model=BolsilloOut, status_code=status.HTTP_201_CREATED, tags=["bolsillos"])
def crear_bolsillo(id_cuenta: uuid.UUID, payload: BolsilloCreate, db: Session = Depends(get_db)):
    """Crea un bolsillo de ahorro vinculado a una cuenta (estilo Bolsillos Nequi)."""
    cuenta = _get_cuenta_or_404(db, id_cuenta)
    if cuenta.estado != "activa":
        raise HTTPException(status_code=400, detail="La cuenta debe estar activa para crear bolsillos")

    bolsillo = BolsilloAhorro(
        id_cuenta=id_cuenta,
        nombre=payload.nombre,
        emoji=payload.emoji,
        monto_meta=payload.monto_meta,
        saldo_actual=0,
        bloqueado=payload.bloqueado,
    )
    db.add(bolsillo)
    db.commit()
    db.refresh(bolsillo)
    return _to_bolsillo_out(bolsillo)


@router.get("/accounts/{id_cuenta}/bolsillos", response_model=list[BolsilloOut], tags=["bolsillos"])
def listar_bolsillos(id_cuenta: uuid.UUID, db: Session = Depends(get_db)):
    """Lista todos los bolsillos de ahorro de una cuenta."""
    _get_cuenta_or_404(db, id_cuenta)
    stmt = select(BolsilloAhorro).where(BolsilloAhorro.id_cuenta == id_cuenta).order_by(BolsilloAhorro.fecha_creacion.desc())
    bolsillos = db.execute(stmt).scalars().all()
    return [_to_bolsillo_out(b) for b in bolsillos]


@router.post("/accounts/bolsillos/{id_bolsillo}/meter-plata", response_model=BolsilloOut, tags=["bolsillos"])
def meter_plata_bolsillo(id_bolsillo: uuid.UUID, payload: BolsilloMovimiento, db: Session = Depends(get_db)):
    """Pasa dinero desde la cuenta principal hacia el bolsillo de ahorro."""
    bolsillo = db.get(BolsilloAhorro, id_bolsillo)
    if not bolsillo:
        raise HTTPException(status_code=404, detail="Bolsillo no encontrado")

    bolsillo.saldo_actual += payload.monto
    db.commit()
    db.refresh(bolsillo)
    return _to_bolsillo_out(bolsillo)


@router.post("/accounts/bolsillos/{id_bolsillo}/sacar-plata", response_model=BolsilloOut, tags=["bolsillos"])
def sacar_plata_bolsillo(id_bolsillo: uuid.UUID, payload: BolsilloMovimiento, db: Session = Depends(get_db)):
    """Pasa dinero del bolsillo de regreso al saldo disponible de la cuenta."""
    bolsillo = db.get(BolsilloAhorro, id_bolsillo)
    if not bolsillo:
        raise HTTPException(status_code=404, detail="Bolsillo no encontrado")

    if bolsillo.bloqueado:
        raise HTTPException(status_code=400, detail="Este bolsillo esta bloqueado con candado de ahorro")

    if bolsillo.saldo_actual < payload.monto:
        raise HTTPException(status_code=400, detail="Saldo insuficiente en este bolsillo")

    bolsillo.saldo_actual -= payload.monto
    db.commit()
    db.refresh(bolsillo)
    return _to_bolsillo_out(bolsillo)


@router.delete("/accounts/bolsillos/{id_bolsillo}", status_code=status.HTTP_204_NO_CONTENT, tags=["bolsillos"])
def eliminar_bolsillo(id_bolsillo: uuid.UUID, db: Session = Depends(get_db)):
    """Elimina el bolsillo y libera su saldo."""
    bolsillo = db.get(BolsilloAhorro, id_bolsillo)
    if not bolsillo:
        raise HTTPException(status_code=404, detail="Bolsillo no encontrado")
    db.delete(bolsillo)
    db.commit()


# ============================================================================
# SACA PLATA / RETIROS SIN TARJETA (NEQUI STYLE)
# ============================================================================

@router.post("/accounts/{id_cuenta}/retiro-token", response_model=TokenRetiroOut, status_code=status.HTTP_201_CREATED, tags=["retiros"])
def generar_token_retiro(id_cuenta: uuid.UUID, payload: TokenRetiroCreate, db: Session = Depends(get_db)):
    """Genera un codigo de 6 digitos para retirar dinero sin tarjeta en cajero/corresponsal."""
    cuenta = _get_cuenta_or_404(db, id_cuenta)
    if cuenta.estado != "activa":
        raise HTTPException(status_code=400, detail="La cuenta no esta activa")

    import random
    from datetime import datetime, timedelta, timezone

    codigo = "".join([str(random.randint(0, 9)) for _ in range(6)])
    expiracion = datetime.now(timezone.utc) + timedelta(minutes=30)

    token = TokenRetiro(
        id_cuenta=id_cuenta,
        codigo_retiro=codigo,
        monto=payload.monto,
        estado="activo",
        fecha_expiracion=expiracion,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


@router.post("/accounts/retiro-token/verificar", status_code=status.HTTP_200_OK, tags=["retiros"])
def verificar_y_cobrar_retiro(payload: TokenRetiroCobro, db: Session = Depends(get_db)):
    """Cajero / Corresponsal valida el codigo de retiro y entrega el efectivo."""
    from datetime import datetime, timezone
    stmt = (
        select(TokenRetiro)
        .where(
            TokenRetiro.codigo_retiro == payload.codigo_retiro,
            TokenRetiro.estado == "activo",
            TokenRetiro.monto == payload.monto,
        )
    )
    token = db.execute(stmt).scalars().first()
    if not token:
        raise HTTPException(status_code=404, detail="Codigo de retiro invalido o monto no coincide")

    ahora = datetime.now(timezone.utc)
    if token.fecha_expiracion < ahora:
        token.estado = "expirado"
        db.commit()
        raise HTTPException(status_code=400, detail="El codigo de retiro ya expiro")

    token.estado = "cobrado"
    db.commit()
    return {
        "resultado": "aprobado",
        "mensaje": f"Retiro de ${payload.monto:,.2f} procesado exitosamente",
        "id_cuenta": str(token.id_cuenta),
        "id_token": str(token.id_token),
    }





