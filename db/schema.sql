-- Esquema de account-service (PostgreSQL). Generado a partir de los modelos SQLAlchemy.
-- Tambien se crea solo al arrancar el servicio (Base.metadata.create_all).

CREATE TABLE cuenta (
	id_cuenta UUID NOT NULL, 
	numero_cuenta VARCHAR(20), 
	id_usuario UUID NOT NULL, 
	tipo_cuenta VARCHAR(32) NOT NULL, 
	moneda VARCHAR(3) NOT NULL, 
	estado VARCHAR(16) NOT NULL, 
	fecha_apertura TIMESTAMP WITH TIME ZONE NOT NULL, 
	fecha_cierre TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id_cuenta), 
	CONSTRAINT uq_cuenta_usuario_moneda UNIQUE (id_usuario, moneda), 
	CONSTRAINT ck_cuenta_estado CHECK (estado IN ('activa','suspendida','cerrada')), 
	UNIQUE (numero_cuenta)
);
CREATE INDEX idx_cuenta_usuario ON cuenta (id_usuario);

CREATE TABLE transferencia_recibida (
	id_transferencia UUID NOT NULL, 
	id_cuenta_origen UUID NOT NULL, 
	monto NUMERIC(18, 2) NOT NULL, 
	estado VARCHAR(16) NOT NULL, 
	recibido_en TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id_transferencia)
);

CREATE TABLE usuario_verificado (
	id_usuario UUID NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	pais_residencia VARCHAR(2) NOT NULL, 
	verificado_en VARCHAR(64) NOT NULL, 
	recibido_en TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id_usuario)
);

CREATE TABLE bolsillo_ahorro (
	id_bolsillo UUID NOT NULL, 
	id_cuenta UUID NOT NULL, 
	nombre VARCHAR(80) NOT NULL, 
	emoji VARCHAR(16) NOT NULL, 
	monto_meta NUMERIC(18, 2), 
	saldo_actual NUMERIC(18, 2) NOT NULL, 
	bloqueado BOOLEAN NOT NULL, 
	fecha_creacion TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id_bolsillo), 
	CONSTRAINT ck_bolsillo_saldo_no_negativo CHECK (saldo_actual >= 0), 
	FOREIGN KEY(id_cuenta) REFERENCES cuenta (id_cuenta) ON DELETE CASCADE
);
CREATE INDEX idx_bolsillo_cuenta ON bolsillo_ahorro (id_cuenta);

CREATE TABLE limite_operativo (
	id_limite UUID NOT NULL, 
	id_cuenta UUID NOT NULL, 
	tipo_limite VARCHAR(16) NOT NULL, 
	monto_maximo NUMERIC(18, 2) NOT NULL, 
	periodo VARCHAR(16) NOT NULL, 
	PRIMARY KEY (id_limite), 
	CONSTRAINT ck_limite_monto_no_negativo CHECK (monto_maximo >= 0), 
	FOREIGN KEY(id_cuenta) REFERENCES cuenta (id_cuenta) ON DELETE CASCADE
);
CREATE INDEX idx_limite_cuenta ON limite_operativo (id_cuenta);

CREATE TABLE restriccion_regulatoria (
	id_restriccion UUID NOT NULL, 
	id_cuenta UUID NOT NULL, 
	pais VARCHAR(2) NOT NULL, 
	descripcion VARCHAR(255), 
	fecha_aplicacion DATE NOT NULL, 
	PRIMARY KEY (id_restriccion), 
	FOREIGN KEY(id_cuenta) REFERENCES cuenta (id_cuenta) ON DELETE CASCADE
);
CREATE INDEX idx_restriccion_cuenta ON restriccion_regulatoria (id_cuenta);

CREATE TABLE token_retiro (
	id_token UUID NOT NULL, 
	id_cuenta UUID NOT NULL, 
	codigo_retiro VARCHAR(6) NOT NULL, 
	monto NUMERIC(18, 2) NOT NULL, 
	estado VARCHAR(20) NOT NULL, 
	fecha_creacion TIMESTAMP WITH TIME ZONE NOT NULL, 
	fecha_expiracion TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id_token), 
	FOREIGN KEY(id_cuenta) REFERENCES cuenta (id_cuenta) ON DELETE CASCADE
);
CREATE INDEX idx_retiro_codigo ON token_retiro (codigo_retiro);
CREATE INDEX idx_retiro_cuenta ON token_retiro (id_cuenta);
