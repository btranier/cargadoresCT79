# cargadoresCT79

## Configurar Git antes de hacer commit (error: "Identidad del autor desconocido")

Si al ejecutar `git commit` aparece:

- `Identidad del autor desconocido`
- `fatal: no es posible auto-detectar la dirección de correo`

configura tu identidad de Git en la Raspberry Pi:

```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu-correo@ejemplo.com"
```

Si quieres configurarlo solo para este repositorio (sin `--global`):

```bash
git config user.name "Tu Nombre"
git config user.email "tu-correo@ejemplo.com"
```

Verifica configuración:

```bash
git config --get user.name
git config --get user.email
```

Luego puedes volver a ejecutar:

```bash
git add .
git commit -m "Apply assistant changes"
git push -u origin main
```


## Carga inicial de configuración (CSV)

Puedes llenar este archivo plantilla y entregármelo para importarlo:

- `data/initial_config_template.csv`

### Formato esperado de columnas

```csv
gateway_host,gateway_port,unit_id,slot_code,description,phase,status,multiplier,owner_name,parking_slot,is_active,device_uid
```

### Significado de cada campo

- `gateway_host` (obligatorio si no usas `device_uid`): IP o hostname del gateway (ej: `192.168.1.101`).
- `gateway_port` (obligatorio si no usas `device_uid`): puerto Modbus TCP (normalmente `502`).
- `unit_id` (obligatorio si no usas `device_uid`): ID del medidor dentro del gateway.
- `slot_code`: código visible en UI (ej: `P246`).
- `description`: descripción legible (ej: `Cargador plaza 246`).
- `phase`: opcional.
- `status`: recomendado `Activo` o `Inactivo`.
- `multiplier`: factor de escala numérico (ej: `1.0`).
- `owner_name`: nombre del propietario/usuario.
- `parking_slot`: plaza/estacionamiento.
- `is_active`: `1` activo / `0` inactivo (también acepta `true/false`, `yes/no`, `inactive`).
- `device_uid`: opcional, útil si quieres mapear por UID en vez de `gateway_host+gateway_port+unit_id`.

### Reglas rápidas

- Si **no** pones `device_uid`, debes completar `gateway_host`, `gateway_port` y `unit_id`.
- Si pones `device_uid`, puede faltar gateway/unit inicialmente y luego completarse.
- Guarda el CSV en UTF-8 con cabecera.

## Importar lecturas CSV (desde Raspberry por línea de comandos)

Ejecuta directamente:

```bash
cd /ruta/a/cargadoresCT79
./import_readings.sh readings_20260201.csv
```

Este flujo:
- crea/reutiliza gateways detectados en lecturas + mapping,
- precarga **32 medidores por gateway** (unit_id 1..32),
- aplica el mapping activo desde `data/active_mapping.csv`.

Opcionalmente, para otro destino de DB o mapping:

```bash
DB_PATH=./data/saci.db MAPPING_CSV=./data/active_mapping.csv ./import_readings.sh readings_20260201.csv
```

También disponible como `make`:

```bash
make import-readings CSV=readings_20260201.csv
```

## Versión local HTML5 (sin backend)

Se añadió una versión 100% cliente en:

- `frontend/local.html`

### Funcionalidad local

- Carga incremental por período desde Google Drive: solo consulta/descarga los días seleccionados y conserva en memoria los días ya cargados.
- Dashboard local con métricas, gráfico **horario apilado por parking_slot** y filtro por rango de días después de cargar las lecturas.
- Facturación mensual local por medidor (sin backend), exportable a CSV.
- Gestión local de mapeos `meter_id` ↔ parking/propietario/slot (editable y persistido en `localStorage`).
- Importación de mapeos desde `data/local_standard_mapping.csv` (mapping estándar) o mediante subida manual de CSV.
- Ignora lecturas no válidas (`ok=false`) y descarta medidores con consumo total < 0.5 kWh en el periodo (dashboard/invoicing).
- Gráfico horario de kWh apilado por `parking_slot`, KPI de capacidad máxima y validación de medidores activos no mapeados.
- Tabla resumen e invoicing con desglose P1..P6, validación de delta (primera/última lectura) y formato a 2 decimales.
- UI bilingüe (ES/EN) y pestaña de lecturas con `volt_v`, `current_a`, `power_kw`, `kwh_import` y paginación por bloques de 1000 filas.
- Panel de validaciones dedicado (medidores activos no mapeados, periodos faltantes por medidor mapeado, deltas inconsistentes y reseteos de contador).
- Clic en una barra del gráfico para ver lecturas subyacentes del bloque seleccionado.


### Uso rápido

1. Abre `frontend/local.html` en navegador (recomendado servirlo con `python3 -m http.server`).
2. Selecciona periodo (`start`/`end`) y pulsa **Load selected period from Drive**. Si cambias periodo, solo se consultan días faltantes.
3. Ajusta el rango en **From day / To day** y pulsa **Apply day filter** para el dashboard.
4. En **Mappings**, importa/edita la relación parking-slot por medidor y guarda localmente.
5. En **Invoicing**, selecciona mes y tarifas, y genera/exporta facturas.

> Nota: el acceso automático a Drive puede requerir API key u OAuth token según permisos de la carpeta.

## Guía básica de uso (ES) – `frontend/local.html`

Esta guía resume el flujo recomendado para operar la herramienta local: carga de datos, revisión de calidad y facturación mensual.

### 1) Cargar lecturas (local o Google Drive)

En la cabecera tienes el bloque **Load Data**:

- **Load local files**: carga archivos `readings_yyyymmdd*.csv` desde tu equipo.
- **Load period from Drive**: descarga lecturas del periodo seleccionado (en **Analysis period**) desde la carpeta de Drive configurada.
- **Load standard mapping**: carga el mapeo estándar incluido en el repo.
- **Clear cache**: limpia caché en memoria para reiniciar la sesión de análisis.

Recomendación:
1. Define primero el periodo en **Analysis period**.
2. Carga datos (local o Drive).
3. Pulsa **Apply filter** para recalcular Dashboard, Missing Readings e Invoicing con ese rango.

### 2) Configuración de mapeos (archivo de configuración)

En la pestaña **Mappings** puedes:

- Cargar `data/local_standard_mapping.csv`.
- Importar tu propio CSV de mapeo.
- Editar columnas clave (`slot_code`, `description`, `status`) directamente.
- Guardar localmente en navegador (**Save local**) y exportar copia (**Export**).

Objetivo del mapeo:
- Asociar cada medidor con su plaza/slot para que Dashboard, validaciones y facturación salgan por parking slot correctamente.

### 3) Identificar lecturas faltantes / calidad de datos

En la pestaña **Missing Readings** revisa:

- Intervalos con huecos de lectura (por medidor/plaza y rango de tiempo).
- Señales de calidad para detectar problemas de comunicaciones o medidores sin datos.

Buenas prácticas:
- Revisar esta pestaña antes de facturar.
- Corregir mapeos faltantes y recargar datos si detectas incoherencias.

### 4) Proceso de facturación mensual (Invoicing)

En la pestaña **Invoicing**:

1. Selecciona **Month**.
2. Define precios por periodo **P1..P6 (€/kWh)**.
3. Si aplica, informa **P1..P6 Excess Power €**.
4. Define costes fijos: **Capacity €** y **Admin €**.
5. Pulsa **Calculate Invoice**.
6. Revisa la tabla y exporta con **Export CSV**.

Qué valida la tabla:
- **Start Value kWh** y **End Value kWh** por fila.
- Energía por periodos P1..P6.
- **Energy kWh**, **Energy €**, reparto de **Capacity €**/**Admin €** y **Total €**.

### 5) Control recomendado de cierre de mes

Para cada parking slot:

1. Toma el **End Value kWh** del mes anterior.
2. Comprueba que coincide con el **Start Value kWh** del nuevo mes.
3. Verifica que la energía facturada (P1..P6 / Energy kWh) es consistente con el salto entre lecturas.
4. Si hay desvíos, revisa **Missing Readings** y el mapeo.

### 6) Flujo operativo recomendado (resumen)

1. Cargar mapping (estándar o propio).
2. Cargar lecturas del periodo.
3. Revisar Dashboard y Missing Readings.
4. Ejecutar Invoicing del mes.
5. Verificar Start/End entre meses.
6. Exportar CSV final de facturación.
