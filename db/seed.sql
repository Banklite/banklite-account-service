-- Datos de ejemplo de account-service. Ejecutar despues de schema.sql.
INSERT INTO usuario_verificado (id_usuario, email, pais_residencia, verificado_en, recibido_en) VALUES
 ('11111111-1111-1111-1111-111111111111','ana.demo@example.com','CO',now()::text,now()),
 ('22222222-2222-2222-2222-222222222222','luis.demo@example.com','CO',now()::text,now())
ON CONFLICT DO NOTHING;
INSERT INTO cuenta (id_cuenta, numero_cuenta, id_usuario, tipo_cuenta, moneda, estado, fecha_apertura) VALUES
 ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1','3001000001','11111111-1111-1111-1111-111111111111','ahorros','COP','activa',now()),
 ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2','3001000002','22222222-2222-2222-2222-222222222222','ahorros','COP','activa',now())
ON CONFLICT DO NOTHING;
INSERT INTO limite_operativo (id_limite, id_cuenta, tipo_limite, monto_maximo, periodo) VALUES
 ('b0000000-0000-0000-0000-000000000001','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1','diario',5000000,'diario'),
 ('b0000000-0000-0000-0000-000000000002','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1','mensual',50000000,'mensual'),
 ('b0000000-0000-0000-0000-000000000003','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2','diario',5000000,'diario'),
 ('b0000000-0000-0000-0000-000000000004','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2','mensual',50000000,'mensual')
ON CONFLICT DO NOTHING;
INSERT INTO restriccion_regulatoria (id_restriccion, id_cuenta, pais, descripcion, fecha_aplicacion) VALUES
 ('c0000000-0000-0000-0000-000000000001','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1','CO','Limites segun regulacion de Colombia',current_date),
 ('c0000000-0000-0000-0000-000000000002','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2','CO','Limites segun regulacion de Colombia',current_date)
ON CONFLICT DO NOTHING;
INSERT INTO bolsillo_ahorro (id_bolsillo, id_cuenta, nombre, emoji, monto_meta, saldo_actual, bloqueado, fecha_creacion) VALUES
 ('b1000000-0000-0000-0000-000000000001','aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1','Vacaciones','✈️',2000000,0,false,now())
ON CONFLICT DO NOTHING;
