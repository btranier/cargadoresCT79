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

Opcionalmente, para otro destino de DB:

```bash
DB_PATH=./data/saci.db ./import_readings.sh readings_20260201.csv
```

También disponible como `make`:

```bash
make import-readings CSV=readings_20260201.csv
```

## Versión local HTML5 (sin backend)

Se añadió una versión 100% cliente en:

- `frontend/local.html`

### Funcionalidad local

- Carga de **todos** los `readings_yyyymmdd*.csv` desde Google Drive (o desde archivos locales).
- Dashboard local con métricas, gráfico diario y **filtro por rango de días** después de cargar las lecturas.
- Facturación mensual local por medidor (sin backend), exportable a CSV.
- Gestión local de mapeos `meter_id` ↔ parking/propietario/slot (editable y persistido en `localStorage`).
- Importación de mapeos desde `data/active_mapping.csv` (si se sirve por HTTP) o mediante subida manual de CSV.

### Uso rápido

1. Abre `frontend/local.html` en navegador (recomendado servirlo con `python3 -m http.server`).
2. Pulsa **Load all readings from Drive** o selecciona CSV locales.
3. Ajusta el rango en **From day / To day** y pulsa **Apply day filter** para el dashboard.
4. En **Mappings**, importa/edita la relación parking-slot por medidor y guarda localmente.
5. En **Invoicing**, selecciona mes y tarifas, y genera/exporta facturas.

> Nota: el acceso automático a Drive puede requerir API key u OAuth token según permisos de la carpeta.
