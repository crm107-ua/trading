# Servidor Carlos — acceso y directorio de trabajo

**Host:** `192.168.50.20`  
**Usuario:** `carlos`  
**Directorio de trabajo:** `/var/www/html/trader`  
**Clave SSH (local, gitignored):** `carlos_key` en la raíz del repo

## Conexión SSH (con túnel LDAP)

```powershell
ssh -L 3307:localhost:1389 carlos@192.168.50.20 -i carlos_key
```

Comando remoto:

```powershell
ssh carlos@192.168.50.20 -i carlos_key "cd /var/www/html/trader && pwd"
```

## Permisos clave en Windows

```powershell
icacls carlos_key /inheritance:r
icacls carlos_key /grant:r "$env:USERNAME`:R"
```

## MeanRevBB validation — migración PC1 → servidor (2026-07-11)

**Run:** `run_id=20260709_162954`  
**Estado PC1:** lock liberado ~15:18 (sin `report.json`)  
**Progreso migrado:** semillas 3/3 + WF ventanas 0–3 (`wf0`…`wf3_train.json`) + `hyperopt_results` 1.8G

### Artefactos copiados a `/var/www/html/trader`

| Ruta | Tamaño |
|------|--------|
| `user_data/data/binance/` | 32 MB |
| `user_data/hyperopt_results/` | 1.8 GB |
| `user_data/validation_reports/MeanRevBB/20260709_162954/` | checkpoint + params |

### PM2

| Campo | Valor |
|-------|-------|
| Nombre | `meanrevbb-validation` |
| Config | `scripts/ecosystem.meanrevbb.config.cjs` |
| Script | `scripts/server_resume_meanrevbb.sh` |
| Logs | `user_data/logs/pm2_meanrevbb.{out,err}.log` |

```bash
pm2 list
pm2 logs meanrevbb-validation
pm2 restart meanrevbb-validation   # tras arreglar Docker
pm2 save
```

### Prerrequisito bloqueante: Docker

`carlos` **no** está en el grupo `docker`. PM2 arrancó y paró con:

```
ERROR: carlos sin acceso a Docker
```

**Una vez como root en el servidor:**

```bash
sudo usermod -aG docker carlos
# cerrar sesión SSH de carlos y volver a entrar
docker ps   # debe funcionar sin sudo
pm2 restart meanrevbb-validation
```

### Python en servidor

- Sistema: Python **3.10** (el repo pide ≥3.11).
- Venv: `/var/www/html/trader/.venv` con deps pinneadas (`pandas<3`) — `pipeline` importa OK.
- Ideal a medio plazo: instalar Python 3.11+ en el servidor.

### Reanudar manualmente

```bash
cd /var/www/html/trader
export HYPEROPT_JOB_WORKERS=1
.venv/bin/python -m pipeline.run_validation MeanRevBB --profile full --resume-run-id 20260709_162954
```

**Nota:** el resume salta semillas; el WF puede rehacer ventanas desde 0 (deuda del pipeline).

## Reglas

- PC1: **no** relanzar `run_validation` mientras el servidor tenga el run activo.
- `carlos_key` nunca en git.
