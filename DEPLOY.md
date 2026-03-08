# Local deployment on Raspberry Pi (Docker)

This project includes a one-command deploy script: `deploy.sh`.

## 0) Requirements (run once)

```bash
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# Log out + log in again so docker group is applied.
```

## 1) First install from GitHub (new machine)

```bash
git clone https://github.com/btranier/cargadoresCT79.git cargadoresCT79
cd cargadoresCT79
```

If you copy a browser URL like `https://github.com/btranier/cargadoresCT79/tree/main`, use the repository root URL (or `.git`) for cloning:

```bash
git clone https://github.com/btranier/cargadoresCT79.git
```

Start everything:

```bash
./deploy.sh main
```

or:

```bash
make deploy REF=main
```

## 2) Update to a new version (existing machine)

From inside the project folder:

```bash
cd /path/to/cargadoresCT79
./deploy.sh main
```

> Nota: la base de datos SQLite se guarda en `./data/saci.db` (volumen montado en `/app/data`).
> No uses `docker compose down -v` si quieres conservar datos de producción.

What this does:
1. fetches latest refs from GitHub
2. checks out the branch/ref you pass (`main` by default)
3. fast-forwards local branch from `origin`
4. stops and removes current compose containers
5. rebuilds images with latest base layers
6. starts containers again
7. shows running container status

## 3) Stop containers for this project only

```bash
cd /path/to/cargadoresCT79
docker compose down --remove-orphans
```

## 4) Stop **all** running Docker containers on the machine

Use with care (this affects other apps too):

```bash
make stop-all-containers
```

Equivalent command:

```bash
docker stop $(docker ps -q) || true
```

## 5) Verify services after deployment

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 collector
docker compose logs --tail=100 daily-finalizer
```

## 6) Optional: auto-start on reboot

If your Docker service is enabled and compose containers use restart policies (`unless-stopped` in this repo), they come back after reboot.

Check Docker service:

```bash
sudo systemctl enable docker
sudo systemctl status docker
```
