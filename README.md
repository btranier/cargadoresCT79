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
