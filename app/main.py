import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .metrics import instrumentar
from .consumer import start_consumer, stop_consumer
from .database import Base, engine, get_db
from .models import Cuenta
from .routers import accounts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(settings.service_name)


from sqlalchemy import text

def _rellenar_numeros_cuenta() -> None:
    """Asigna numero_cuenta a las cuentas antiguas que lo tienen NULL (idempotente).
    Sin esto esas cuentas nunca aparecen al buscar un destinatario."""
    from .database import SessionLocal
    from .models import Cuenta
    from .routers.accounts import generar_numero_cuenta

    with SessionLocal() as db:
        pendientes = db.query(Cuenta).filter(Cuenta.numero_cuenta.is_(None)).all()
        for c in pendientes:
            c.numero_cuenta = generar_numero_cuenta(db)
            db.flush()
        db.commit()
        if pendientes:
            logger.info("Numero de cuenta asignado a %d cuentas antiguas", len(pendientes))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Migración idempotente: agregar numero_cuenta si no existe
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cuenta ADD COLUMN IF NOT EXISTS numero_cuenta VARCHAR(20);"))
    _rellenar_numeros_cuenta()
    start_consumer()
    logger.info("%s iniciado", settings.service_name)
    yield
    stop_consumer()


app = FastAPI(
    title="BankLite - Account Service",
    description=(
        "Microservicio de cuentas. Consume el evento identity.verified (asincrono) "
        "y valida al usuario contra identity-service por REST (sincrono) antes de "
        "abrir una cuenta con los limites regulatorios de su pais."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

instrumentar(app)  # metricas para Prometheus en GET /metrics

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # solo para desarrollo local; en produccion se restringe al dominio del panel
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "service": settings.service_name}


@app.get("/stats", tags=["infra"])
def stats(db: Session = Depends(get_db)):
    return {
        "total_cuentas": db.execute(select(func.count()).select_from(Cuenta)).scalar(),
        "cuentas_activas": db.execute(
            select(func.count()).select_from(Cuenta).where(Cuenta.estado == "activa")
        ).scalar(),
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servicio"},
    )
