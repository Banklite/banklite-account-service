# Account Service — BankLite

Apertura, estado y cierre de cuentas; limites diarios y mensuales; restricciones por pais; bolsillos de ahorro y tokens de retiro.

Parte del proyecto **BankLite** (banca digital con microservicios) de *Arquitectura y Modelamiento de Software*, Universidad Cooperativa de Colombia. Cada microservicio tiene su propio repositorio y su propia base de datos (`account_db`).

## Responsabilidad en la arquitectura

Apertura, estado y cierre de cuentas; limites diarios y mensuales; restricciones por pais; bolsillos de ahorro y tokens de retiro. Se comunica con los demas servicios por **REST** (operaciones que necesitan respuesta inmediata) y por **eventos** en RabbitMQ (exchange `banklite.events`, tipo topic).

| Eventos publicados | Eventos consumidos |
|---|---|
| — | `identity.verified`, `transfer.completed` |

## Tecnologias

FastAPI, SQLAlchemy, PostgreSQL, RabbitMQ (pika). Python 3.12, Docker.

## Despliegue

- URL publica: <https://banklite-account-service.onrender.com>
- Salud: <https://banklite-account-service.onrender.com/health>
- Documentacion interactiva (Swagger): <https://banklite-account-service.onrender.com/docs>

Desplegado en Render (plan gratuito: tarda hasta ~1 minuto en responder si estuvo inactivo). Las credenciales se configuran como variables de entorno en la plataforma, no en el codigo.

## Endpoints principales

| Metodo | Ruta | Descripcion |
|---|---|---|
| `POST` | `/accounts` | Abre una cuenta (valida el KYC en identity-service por REST) |
| `GET` | `/accounts/{id}` | Consulta una cuenta |
| `PATCH` | `/accounts/{id}/status` | Cambia el estado (activa/suspendida/cerrada) |
| `GET` | `/accounts/{id}/limits` | Limites operativos de la cuenta |
| `GET` | `/verified-users` | Proyeccion de usuarios verificados (alimentada por evento) |
| `POST` | `/accounts/{id}/bolsillos` | Crea un bolsillo de ahorro |
| `POST` | `/accounts/{id}/retiro-token` | Genera un token de retiro |
| `GET` | `/health` | Estado del servicio |
| `GET` | `/stats` | Contadores del servicio |

La lista completa esta en `/docs`.

## Variables de entorno

Copia `.env.example` a `.env` y completa los valores.

| Variable | Descripcion |
|---|---|
| `DATABASE_URL` | Conexion PostgreSQL |
| `IDENTITY_SERVICE_URL` | URL de identity-service |
| `RABBITMQ_URL` | URL del bus de eventos |
| `EVENTS_EXCHANGE` | Exchange de eventos |
| `EVENTS_QUEUE` | Cola propia |
| `ENABLE_CONSUMER` | Consumir eventos |

## Base de datos

Motor: PostgreSQL. Base: `account_db`.

- `db/schema.sql`: creacion de tablas, indices y restricciones.
- `db/seed.sql`: datos de ejemplo.

El servicio tambien crea las tablas solo al arrancar (`create_all`). Para restaurar a mano:

```bash
createdb account_db
psql -d account_db -f db/schema.sql
psql -d account_db -f db/seed.sql
```

Respaldo completo (para entregar o restaurar): `pg_dump -Fc account_db > account_db.dump` y `pg_restore -d account_db account_db.dump`.

## Instalacion y ejecucion

Con Docker:

```bash
docker build -t banklite-account-service .
docker run --env-file .env -p 8002:8002 -e PORT=8002 banklite-account-service
```

Sin Docker:

```bash
python -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8002
```

Prueba: abre <http://localhost:8002/docs>.

## Repositorios del proyecto

`banklite-identity-service`, `banklite-account-service`, `banklite-ledger-service`, `banklite-transfer-service`, `banklite-card-service`, `banklite-fraud-service`, `banklite-notification-service`, `banklite-compliance-service`. Panel web: `services/web-panel` en el repositorio `banklite-microservicios`.
