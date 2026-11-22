# Política de seguridad

## Alcance

Esta política cubre el código de este repositorio: servidor (`backend/`), interfaz web/PWA (`frontend/`), aplicación
de escritorio (`desktop/`) y scripts (`scripts/`). No cubre la infraestructura donde cada negocio lo instala (equipo
Windows, red, proxy HTTPS, copias de seguridad), que es responsabilidad de quien lo opera.

## Versiones con soporte

| Versión | Soporte |
|---|---|
| Rama `Principal` (última publicación) | Sí |
| Rama `Beta` | Sí, para pruebas antes de publicar |
| Versiones anteriores | No: actualice a la última |

## Cómo reportar una vulnerabilidad

- Use el reporte privado de vulnerabilidades de GitHub del repositorio
  ([Security › Report a vulnerability](https://github.com/AlejandroDukesini/Sy-POS-Gestion/security/advisories/new)).
- **No** abra un issue público ni publique detalles antes de la corrección.
- Incluya: versión o commit, pasos para reproducir, impacto y, si puede, una prueba de concepto **contra una
  instalación de prueba**. No pruebe contra instalaciones de terceros ni use datos reales de clientes.

## Proceso

1. Acuse de recibo en un plazo objetivo de 5 días hábiles.
2. Reproducción y clasificación (crítico, alto, medio, bajo, informativo).
3. Corrección con prueba de regresión, revisión y publicación en `Beta` y luego en `Principal`.
4. Aviso a quien reportó y, si corresponde, aviso de seguridad público con el crédito que desee.

Es un proyecto mantenido por su autor: no hay recompensas económicas ni acuerdos de nivel de servicio.

## Responsabilidades

- **Mantenedor**: corregir vulnerabilidades del código, mantener las dependencias y los controles de CI.
- **Quien instala y opera**: mantener Windows y la aplicación actualizados, usar HTTPS fuera del propio equipo,
  proteger la cuenta de Windows y el disco (BitLocker), resguardar las copias de seguridad y gestionar usuarios,
  permisos y equipos autorizados.

## Buenas prácticas de instalación y operación

- Por defecto el servidor solo escucha en el propio equipo. Para otros equipos, publíquelo detrás de un proxy con
  **HTTPS** y `POS_SECURE_COOKIES=1`; nunca exponga HTTP sin cifrar a Internet.
- Asigne contraseña a todo administrador y active el inicio de sesión si hay más de una persona.
- Active **Gestión › Equipos autorizados** si quiere limitar el uso a los computadores del negocio.
- Dé a cada empleado solo los permisos que necesita y revise **Historial de actividad**.
- Haga copias de seguridad periódicas y guárdelas en un medio de acceso restringido (contienen datos del negocio).
- No comparta el archivo `setup-code.txt` ni la carpeta de datos.

## Limitaciones conocidas

- No hay autenticación de dos factores.
- La restricción por equipo se basa en una clave no exportable del navegador: reduce mucho el uso desde otros
  computadores, pero un navegador no identifica de forma infalible un equipo físico.
- Quien tenga acceso al archivo de la base de datos en el equipo servidor tiene acceso a los datos: los permisos de la
  aplicación no reemplazan la protección del sistema operativo.
- Detalle técnico y riesgos residuales: [docs/developer/seguridad.md](docs/developer/seguridad.md) y
  [docs/developer/auditoria-seguridad-2026-11.md](docs/developer/auditoria-seguridad-2026-11.md).

Esta política y las evaluaciones internas no constituyen una certificación de ningún organismo externo.
