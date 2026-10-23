# Validación de esta entrega

Realizada el 23/10/2026 en un entorno temporal, sin datos reales del usuario.

- Compilación sintáctica de la aplicación y del importador.
- Creación del esquema y operaciones SQL con psycopg sobre PGlite (motor PostgreSQL compilado a WebAssembly).
- Inventarios con el mismo nombre en dos regionales, consecutivos independientes y salida de productos de varios inventarios.
- Rechazo de existencias insuficientes con reversión completa de la entrega.
- Reintento del mismo formulario sin duplicación de cantidades ni de factura.
- Solicitudes desde dos hilos usando una conexión de prueba serializada: una sola salida cuando el stock no alcanza para ambas.
- Corrección de cantidad y rechazo de una edición basada en una versión anterior del producto.
- Devolución individual, prevención de doble devolución y recuperación de inventario eliminado ante un nombre ocupado.
- Adjuntos PDF e imagen, rechazo de contenido inválido, asociación a línea o factura y conservación del adjunto general al borrar una línea anulada.
- Acceso con contraseña, bloqueo tras cinco intentos fallidos y cierre de sesión.
- Streamlit AppTest: inicio de sesión, renderizado de las cinco secciones, creación de una entrega desde el formulario y cierre de sesión.
- Importación desde una base SQLite creada con la versión anterior: cantidades, anulaciones, productos eliminados y adjuntos conservados; rechazo de una segunda importación.
- PDF con ambos campos de firma, con uno y sin ninguno; lectura de texto, paginación y revisión visual de los tres ejemplos incluidos.

Limitaciones de la verificación: no se dispone de credenciales del proyecto Supabase del usuario. No se ha realizado un despliegue real, una prueba de su conexión SSL ni una prueba de carga entre servidores independientes. PGlite serializa conexiones y no reproduce todas las condiciones de una instalación PostgreSQL en red. El código usa una transacción y un bloqueo PostgreSQL compartido para las escrituras; se recomienda comprobar un ingreso, una salida y una devolución de prueba tras configurar el proyecto real.
