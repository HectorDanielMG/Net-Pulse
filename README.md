# NetPulse

**Plataforma local de monitoreo y diagnóstico de redes con observabilidad, alertas explicables y laboratorio reproducible.** NetPulse está diseñada como un proyecto de portafolio para roles de redes, NOC, infraestructura y automatización.

No afirma supervisar dispositivos reales: al iniciar no hay equipos ni métricas. El laboratorio añade dispositivos y datos identificados permanentemente como simulados. Las comprobaciones TCP reales solo se ejecutan contra destinos que el operador haya registrado de forma explícita.

## Funcionalidades implementadas

- Registro de routers, switches, servidores, firewalls y otros dispositivos.
- Comprobaciones TCP con tiempo de espera y concurrencia limitada.
- Estados `UP`, `DOWN`, `DEGRADED` y `UNKNOWN`.
- Historial SQLite de mediciones, eventos, alertas e incidentes.
- Alertas de conectividad y rendimiento; una caída requiere dos fallos consecutivos.
- Incidentes que se abren tras la confirmación y se resuelven al recuperarse el dispositivo.
- Diagnóstico basado en reglas y evidencia, sin afirmar causas raíz.
- Topología para enlaces de laboratorio configurados explícitamente.
- Laboratorio determinista: saludable, caída, latencia, pérdida y recuperación.
- API REST con documentación en `/docs`, salud en `/healthz` y métricas simples en `/metrics`.
- Interfaz web adaptable conectada al backend.

## Inicio rápido

### Con Docker

```bash
docker compose up --build
```

Abre [http://localhost:8010](http://localhost:8010). El puerto se liga a `127.0.0.1`; no expone NetPulse a la red local.

### Con Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn netpulse.main:app --host 127.0.0.1 --port 8010 --reload
```

Puedes copiar `.env.example` como referencia; no contiene secretos. `DATABASE_PATH` permite elegir otro archivo SQLite local.

## Demostración del laboratorio

1. Abre el panel y selecciona **Cargar laboratorio**.
2. En **Lab Simulator**, ejecuta dos veces **Caída**: se generan alertas e incidentes después de la segunda comprobación.
3. Ejecuta **Recuperación** para resolver los incidentes.
4. Consulta **Alerts**, **Incidents**, **Performance**, **Network Topology** y **Diagnostics** para observar la misma evidencia.
5. Usa **Limpiar datos de laboratorio** para retirar únicamente dispositivos y mediciones simuladas.

## Arquitectura

```mermaid
flowchart LR
  UI[Panel web] --> API[FastAPI]
  API --> DB[(SQLite)]
  Monitor[Motor de comprobaciones] --> API
  Monitor --> DB
  Lab[Laboratorio simulado] --> Monitor
  API --> Metrics[/metrics]
```

La arquitectura y las decisiones están detalladas en [docs/architecture.md](docs/architecture.md).

## Pruebas

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

La suite usa un SQLite temporal y no necesita conectividad externa. Consulta [docs/testing.md](docs/testing.md).

## Limitaciones conocidas

- La primera versión usa comprobaciones TCP; ICMP y SNMPv3 están documentados como próximas integraciones.
- No implementa autenticación ni autorización corporativa.
- La topología muestra enlaces configurados por el laboratorio; no realiza descubrimiento físico.
- Prometheus y Grafana son integraciones opcionales futuras; `/metrics` ofrece métricas iniciales.
- SQLite es apropiado para laboratorio y equipos pequeños, no para alta concurrencia empresarial.

## Documentación

- [Arquitectura](docs/architecture.md)
- [Monitoreo](docs/monitoring.md)
- [Topología](docs/network-topology.md)
- [SNMP](docs/snmp.md)
- [Seguridad](docs/security.md)
- [Pruebas](docs/testing.md)
- [Roadmap](docs/roadmap.md)
