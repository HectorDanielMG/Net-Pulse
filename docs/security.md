# Seguridad

NetPulse escucha en `127.0.0.1` en las instrucciones y Docker Compose. Los diagnósticos no aceptan hosts libres: solo operan sobre dispositivos almacenados. Las conexiones TCP se crean con argumentos estructurados, tiempo de espera y límite de concurrencia; no se construyen comandos de shell. `.env`, SQLite y artefactos locales se excluyen de Git.

Antes de una implementación empresarial se requieren autenticación, control de roles, cifrado de secretos, auditoría de cambios, revisión de dependencias y pruebas de seguridad.
