# Arquitectura

NetPulse se compone de un frontend estático servido por FastAPI, una API REST y SQLite. `netpulse/core.py` concentra persistencia, comprobaciones, reglas e historial; `netpulse/main.py` expone esquemas validados y endpoints. Esta separación evita que la interfaz ejecute diagnósticos por su cuenta.

El monitor periódico mantiene concurrencia limitada y captura errores por comprobación. Las comprobaciones reales usan `asyncio.open_connection` con host y puerto de dispositivos ya registrados. El laboratorio no abre conexiones: entrega mediciones identificadas como `simulated` al mismo motor de alertas.
