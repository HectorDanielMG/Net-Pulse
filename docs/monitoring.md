# Monitoreo y estados

`UP` representa una comprobación TCP exitosa. `DEGRADED` representa respuesta con latencia o pérdida sobre el umbral. `DOWN` requiere dos fallos consecutivos para reducir falsos positivos. `UNKNOWN` representa un dispositivo sin evidencia suficiente, sin puerto TCP o con monitoreo pausado. La ausencia de una medición no equivale a una caída.

Las mediciones guardan fecha, resultado, latencia, paquetes, pérdida, tipo, error y origen simulado. Los datos de alta frecuencia se conservan sin poda automática en esta versión; una política de retención por tiempo es trabajo pendiente antes de un despliegue prolongado.
