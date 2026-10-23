# INVENTARIOS_IPSICOL · Versión web

La aplicación se abre en el navegador. Streamlit ejecuta Python en un servidor; PostgreSQL conserva inventarios, movimientos, documentos y auditoría. Las personas que la utilicen no necesitan instalar Python ni un programa de escritorio.

## 1. Archivos de la entrega

- `ipsicol.py`: aplicación completa; logo original integrado.
- `requirements.txt`: dependencias para Streamlit Cloud.
- `schema.sql`: estructura inicial de PostgreSQL; ejecutar una vez.
- `permisos.sql`: crea un usuario de base de datos exclusivo para la aplicación.
- `secrets.example.toml`: modelo de credenciales y usuarios, sin contraseñas reales.
- `.streamlit/config.toml`: colores, tamaño de texto y límite de carga.
- `.gitignore`: impide subir secretos, bases locales y soportes al repositorio.
- `migrar_sqlite.py`: importación opcional de la base de escritorio.
- `ejemplos/`: constancias PDF con datos ficticios para revisar el formato.

## 2. Crear la base gratuita en Supabase

1. Abre https://supabase.com y crea un proyecto en una organización con plan **Free**. Guarda la contraseña de la base.
2. En el proyecto, abre **SQL Editor**, pega el contenido completo de `schema.sql` y ejecútalo. Se crea el esquema privado `ipsicol` con las dos regionales.
3. Abre `permisos.sql`, reemplaza `CAMBIA_ESTA_CONTRASENA_ANTES_DE_EJECUTAR` por una contraseña larga y única, y ejecútalo. Se crea el rol `ipsicol_app`. Este paso se ejecuta una sola vez; si ya existe, puedes cambiar la contraseña con `ALTER ROLE ipsicol_app PASSWORD '...';`.
4. Pulsa **Connect** y busca **Session pooler**, normalmente puerto **5432**. Copia host, puerto, nombre de base y referencia del proyecto.
5. En las credenciales de la aplicación, el usuario será `ipsicol_app.REFERENCIA_DEL_PROYECTO`, con el mismo host del Session pooler y la contraseña creada en el paso 3. Con PostgreSQL independiente utiliza los datos de tu proveedor; el sufijo de proyecto solo corresponde al pooler de Supabase.
6. No añadas `ipsicol` a los esquemas expuestos de la Data API. La aplicación se conecta desde el servidor por SSL. No utiliza ni necesita las claves públicas `anon` ni `service_role`.

Ejemplo de conexión, con valores ficticios:

```toml
[postgres]
host = "aws-0-TU-REGION.pooler.supabase.com"
port = 5432
dbname = "postgres"
user = "ipsicol_app.TU_PROJECT_REF"
password = "TU_CONTRASENA_PRIVADA_DEL_ROL"
sslmode = "require"
```

Los parámetros están separados para que contraseñas con símbolos no requieran codificación en una URL. No copies una dirección de la API HTTPS en el campo `host`. El host exacto debe salir del panel Connect, no del ejemplo.

## 3. Configurar inicio de sesión

Cada usuario se define en Secrets; no hay una contraseña predeterminada. Las contraseñas se guardan como hashes PBKDF2 con sal aleatoria, nunca como texto dentro del código.

En una terminal, dentro de la carpeta del proyecto, ejecuta:

```bash
python ipsicol.py --hash-password
```

Escribe dos veces una contraseña de al menos 12 caracteres. Copia el resultado completo que comienza con `pbkdf2_sha256$600000$`:

```toml
[users.almacen]
name = "Responsable de almacén"
role = "admin"
password_hash = "PEGA_AQUI_EL_HASH_COMPLETO"
```

El usuario de acceso será `almacen`; la contraseña será la que escribiste al generar el hash. Para crear otro usuario añade otro bloque `[users.nombre]`, con nombre en minúscula y un hash diferente.

Roles:

- `admin`: todas las operaciones y eliminación definitiva de salidas anuladas.
- `editor`: ingresos, salidas, correcciones, adjuntos, devoluciones y eliminación lógica de productos/inventarios.
- `consulta`: consulta e impresión; no puede modificar existencias.

Hay bloqueo de 15 minutos tras cinco fallos para un usuario configurado. La sesión dura ocho horas. Al cerrar sesión se limpia la información de esa sesión. Para cambiar una contraseña, genera otro hash y sustituye el valor en Secrets; la sesión anterior deja de ser válida cuando vuelve a realizar una operación.

Puedes generar los hashes en **GitHub Codespaces**, desde el navegador, si no quieres instalar Python en tu equipo. Solo el administrador necesita hacer la configuración.

## 4. Publicar en Streamlit Community Cloud

1. Crea un repositorio de GitHub y sube el contenido de esta carpeta, incluyendo `.streamlit/config.toml`. `ipsicol.py` y `requirements.txt` deben estar en la raíz del repositorio.
2. **No subas `.streamlit/secrets.toml`, tu SQLite ni archivos de facturas reales.** `secrets.example.toml` contiene únicamente ejemplos y sí puede subirse.
3. En https://share.streamlit.io elige **Create app**, selecciona el repositorio, la rama y el archivo principal `ipsicol.py`. Usa Python **3.12** en la configuración avanzada.
4. En **Advanced settings → Secrets**, pega el contenido de `secrets.example.toml` y reemplaza los ejemplos por la conexión y los hashes reales. Mantén los bloques `[postgres]` y `[users.almacen]`.
5. Pulsa **Deploy**. Cuando termine, abre la dirección `https://...streamlit.app`, inicia sesión y comparte ese enlace con el personal autorizado.
6. Crea usuarios distintos para identificar quién registra cada movimiento. No compartas las credenciales de PostgreSQL con los usuarios de la aplicación.

No se entrega un sitio ya publicado: necesitas configurar tu proyecto Supabase, tu repositorio y los Secrets. Esta versión ya no se compila con PyInstaller.

Para ejecutarla tú en una terminal de desarrollo:

```bash
python -m pip install -r requirements.txt
# Copia secrets.example.toml a .streamlit/secrets.toml y completa los datos.
python -m streamlit run ipsicol.py
```

## 5. Uso del sistema

### Inventarios e ingresos

En **Resumen → Crear nuevo inventario**, escribe el nombre y selecciona Bogotá o Cundinamarca. Añade los productos iniciales con sus cantidades y registra el ingreso. Los nombres se guardan con mayúscula inicial, conservando siglas y el resto del texto.

En **Ingresos**, selecciona un inventario y añade productos nuevos o unidades de productos existentes. Cada ingreso tiene fecha, origen/proveedor y responsable. Puedes adjuntar una factura durante el registro o posteriormente desde Consultas.

**Corregir nombre o cantidad**, en Inventarios, sirve para errores de digitación o conteo. Exige un motivo y deja auditoría. No genera una factura de ingreso porque es una corrección; para una compra o recepción real utiliza Ingresos. Si otro usuario modificó el producto mientras lo editabas, debes recargarlo antes de guardar.

Eliminar un producto o inventario lo retira de la gestión activa, manteniendo su historial. Si se devuelven productos de un inventario eliminado, el sistema lo recupera. Ante un nombre ocupado se agrega una referencia de recuperación.

### Salidas y devoluciones

En **Salidas**, añade productos a la entrega. Puedes cambiar el inventario origen y seguir añadiendo productos de otras regionales o inventarios. Revisa la lista, completa destino, responsable, fecha y ubicación y confirma toda la entrega.

En **Consultas**, selecciona la factura y abre **Anular / devolver productos**. Puedes seleccionar líneas individuales o marcar toda la entrega vigente. La cantidad completa de cada línea seleccionada regresa al inventario exactamente una vez. Esta opción no divide una línea: por ejemplo, si la línea tiene 10 unidades, devuelve las 10.

Un administrador puede eliminar definitivamente líneas anuladas y sus adjuntos individuales. El número de factura, la auditoría y los documentos adjuntados a toda la factura se conservan. El borrado no devuelve unidades por segunda vez.

### Numeración automática

- Factura de ingreso **#00000001**, **#00000002**, etc.
- Factura de salida **#00000001**, **#00000002**, etc.

Son dos consecutivos independientes, globales para todos los usuarios. Una entrega con varios productos y varios inventarios tiene **un solo número de salida**. El número se asigna al guardar, nunca se reinicia por mes/año y nunca se reutiliza al anular o borrar. Puede haber saltos si una transacción falla después de reservar un número; esto evita duplicados. Los ocho dígitos son un mínimo visual: el consecutivo puede seguir creciendo.

Estas son **constancias internas de inventario**. No constituyen facturación electrónica ni sustituyen una factura fiscal del proveedor.

### Imprimir PDF

- **Inventarios → Imprimir constancia**: nombre, regional, productos y existencias actuales.
- **Consultas → Imprimir esta factura / constancia**: productos, inventarios, cantidades, origen/destino, fecha, responsable y estado de cada línea.
- La factura del primer ingreso sirve como constancia de creación con las cantidades originales. Las constancias de inventario muestran el estado actual.

Antes de descargar el PDF puedes marcar por separado **Responsable de almacén** y **Quien recibe**. Sin marcas, no aparece ningún bloque ni línea de firma. Con una sola marca aparece únicamente esa firma. Descarga el PDF, ábrelo y pulsa **Ctrl+P** o el botón Imprimir del visor.

### Adjuntar la factura después

En **Consultas**, busca por regional, inventario, producto, ubicación, fechas, estado, tipo o número. Selecciona la factura y abre **Facturas y documentos adjuntos**. Elige **Toda la factura** o un producto concreto y guarda el documento. Puedes añadir varios archivos. La copia se guarda en PostgreSQL y permanece aunque borres el original de tu computador.

Se aceptan PDF, PNG, JPG y WEBP, hasta **5 MB por archivo**. Para consultar un adjunto, pulsa **Preparar descarga** y luego **Descargar documento**. La descarga requiere una sesión autorizada.

### Actualización entre usuarios

Los cambios se confirman en la base compartida. Las tablas de Resumen, Inventarios y Consultas se actualizan automáticamente cada **10 segundos** mientras la sesión está abierta. Es actualización periódica, no una suscripción instantánea por WebSocket a Supabase Realtime. El botón **Actualizar datos** recarga inmediatamente también los selectores y el detalle de la factura. La existencia se vuelve a validar en el servidor al guardar una salida.

Los filtros de Consultas encuentran facturas que contienen líneas coincidentes; al abrir una factura se muestra **toda su entrega**, para que la impresión y las devoluciones tengan contexto completo.

## 6. Importar tu SQLite anterior (opcional)

La versión web no puede acceder automáticamente al AppData de tu computador. Importa una copia de la carpeta de datos antes de comenzar a registrar movimientos nuevos en la nube.

1. Cierra el programa de escritorio y copia su carpeta de datos completa, incluido `inventarios_ipsicol.sqlite3` y `soportes`. En la versión adjunta la ruta habitual es `%LOCALAPPDATA%\INVENTARIOS_IPSICOL`.
2. Inicializa PostgreSQL con `schema.sql` y `permisos.sql`, pero **no crees inventarios todavía**.
3. Configura `.streamlit/secrets.toml` en un entorno de administración, con las mismas credenciales.
4. Ejecuta, ajustando ambas rutas:

```bash
python migrar_sqlite.py "C:/respaldo/INVENTARIOS_IPSICOL/inventarios_ipsicol.sqlite3" --soportes "C:/respaldo/INVENTARIOS_IPSICOL"
```

La importación exige un destino vacío. No borra ni modifica el archivo SQLite. Si un registro o soporte falla, se revierte la importación completa. Conserva cantidades, regionales, nombres, salidas agrupadas, anulaciones y adjuntos. Crea una factura de ingreso por inventario para sus cantidades iniciales, identificada como saldo histórico importado con fecha de importación, ya que el código anterior no guardaba una fecha de ingreso por producto.

Asigna nuevos números de salida en orden de fecha e ID anterior y conserva referencias a los IDs antiguos en la auditoría. Las líneas que hubieras borrado definitivamente antes ya no pueden reconstruirse. Para proteger la integridad, un adjunto ausente, mayor de 5 MB o con formato no compatible detiene la importación; restaura o adapta el soporte en la **copia de respaldo** antes de reintentar. No omite archivos silenciosamente.

Si la base anterior usa una estructura distinta de la del archivo adjunto, se necesita revisar la migración antes de ejecutarla. Después de importar, comprueba los totales y conserva el respaldo original.

## 7. Gratuidad, almacenamiento y copias de seguridad

A 23 de octubre de 2026, Streamlit Community Cloud ofrece alojamiento gratuito y Supabase Free incluye **500 MB de base de datos**. Supabase puede pausar los proyectos gratuitos tras **una semana de inactividad**. Los límites y condiciones pueden cambiar.

Esta versión guarda los documentos dentro de PostgreSQL (`bytea`): cuentan dentro de los **500 MB de base de datos**, no dentro del GB separado de Supabase Storage. Usa PDF comprimidos e imágenes moderadas. La ventaja es que documento y movimiento se guardan juntos en la misma transacción, sin depender del disco temporal del servidor ni de URLs públicas. Para un volumen alto de facturas convendría pasar los documentos a un bucket privado de Storage.

Streamlit Cloud también tiene límites de recursos e hibernación. No se garantiza disponibilidad permanente con servicios gratuitos. Revisa uso de espacio y tráfico en los paneles. No hay pagos ni suscripciones configurados en el código.

Haz respaldos periódicos de PostgreSQL; por ejemplo con `pg_dump` desde un entorno administrativo, usando las credenciales del proyecto. La copia de base incluye también los archivos adjuntos. Guarda los respaldos fuera del servidor de Streamlit y prueba su restauración. No dependas del disco local de Streamlit para datos permanentes.

## 8. Validación y alcance

El proyecto incluye validación de entradas, SQL parametrizado, claves foráneas, restricciones de cantidades, registro de auditoría, contraseñas con hash, permisos de interfaz y comprobación de sesión antes de las acciones. La operación de cada formulario tiene un identificador para impedir que un reintento de red duplique movimientos.

Los nombres se conservan en las líneas de las facturas como estaban al registrar el movimiento, aunque posteriormente se corrija el nombre del producto. Las correcciones de cantidad se suman aparte; no reescriben facturas anteriores.

La estructura usa un esquema privado y un rol de base exclusivo. Las credenciales deben permanecer en Secrets del servidor. No actives acceso anónimo de la Data API al esquema `ipsicol`.

## Fuentes oficiales de configuración

- Streamlit Community Cloud: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Configurar Secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- Actualización periódica: https://docs.streamlit.io/develop/concepts/architecture/fragments
- Conexión y Session pooler de Supabase: https://supabase.com/docs/guides/database/connecting-to-postgres
- Tarifas y límites de Supabase: https://supabase.com/pricing
