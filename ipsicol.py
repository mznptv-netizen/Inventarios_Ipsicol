#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INVENTARIOS_IPSICOL - Escritorio Windows, SQLite y CustomTkinter.

Ejecutar: python ipsicol.py
Instalar: python -m pip install -r requirements.txt
Compilar: GitHub Actions (.github/workflows/build.yml) o compilar_windows.bat.
Todo el código de la aplicación está en este archivo. Logo: caja de envío integrada.
--export-icons assets genera PNG e ICO para el ejecutable.
--self-test prueba la integridad sin modificar datos reales.
--smoke-test --report resultado.json prueba SQLite, PDF, iconos e interfaz.

Los datos continúan en %LOCALAPPDATA%/INVENTARIOS_IPSICOL (Windows).
Nunca se almacenan en sys._MEIPASS. Copia la carpeta completa con el programa
cerrado para respaldar la base y sus soportes. La migración es aditiva.
Las facturas de ingreso y salida tienen consecutivos independientes de ocho
cifras. Cada entrega tiene un número compartido por todos sus productos.
Los saldos iniciales antiguos se identifican como importados; no se conoce
su fecha original de ingreso. Los números de salida antiguos se asignan en
orden de fecha e ID. Los números confirmados nunca se reutilizan ni reinician.
Cantidad ingresada significa total acumulado de ingresos; las devoluciones
reducen salidas netas. Las facturas originales conservan sus cantidades.
PDF con firmas opcionales. Adjuntos PDF/imágenes copiados a soportes.
"""

from __future__ import annotations

import base64
import calendar
import io
import logging
import os
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import date, datetime
from pathlib import Path


APP_NAME = "INVENTARIOS_IPSICOL"
REGIONALES = ("Bogotá", "Cundinamarca")
UBICACIONES = ("REDENTOR", "CIPLA", "CAJICA", "ESMERALDA")
NO_SOPORTE = "No es necesario"
TODOS = "Todos"
MAGENTA = "#BF1672"
MAGENTA_HOVER = "#99115B"
BG = "#F6F3F7"
INK = "#302637"
MUTED = "#605567"
WHITE = "#FFFFFF"
MAX_CANTIDAD = 2_000_000_000
PAGE_SIZE = 200
SUPPORT_TYPES = [("PDF e imágenes", "*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff")]


def validate_support(path: Path):
    """Valida formato y tamaño; no ejecuta ni interpreta documentos PDF."""
    if not path.is_file():
        raise ValueError("El archivo ya no existe. Selecciónalo nuevamente.")
    if not 0 < path.stat().st_size <= 25 * 1024 * 1024:
        raise ValueError("El archivo debe tener contenido y no superar 25 MB.")
    if path.suffix.lower() == ".pdf":
        with path.open("rb") as stream:
            if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                raise ValueError("El archivo no tiene una cabecera PDF válida.")
    elif path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"):
        from PIL import Image
        with Image.open(path) as picture:
            picture.verify()
    else:
        raise ValueError("Selecciona un PDF o una imagen PNG, JPG, WEBP, BMP o TIFF.")


def copy_support(source: Path, folder: Path) -> Path:
    """Copia con nombre único y valida los bytes que realmente se conservarán."""
    source = Path(source)
    validate_support(source)
    target_dir = folder / "soportes"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
    try:
        # Lectura acotada incluso si el archivo original cambia mientras se copia.
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            remaining = 25 * 1024 * 1024 + 1
            while remaining:
                chunk = incoming.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                outgoing.write(chunk)
                remaining -= len(chunk)
        validate_support(target)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def resource_path(filename: str) -> Path:
    """Recursos de solo lectura: script o extracción temporal de --onefile."""
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent
    return base / filename


def load_logo_image():
    """Icono vectorial simple de una caja de envío, dibujado a alta resolución.

    Integrado en Python: funciona también dentro de --onefile sin imágenes externas.
    """
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((12, 12, 500, 500), radius=110, fill="#F9E5F0")
    d.ellipse((90, 401, 423, 449), fill="#E4C0D4")
    d.polygon([(83, 176), (252, 91), (430, 177), (259, 265)], fill="#DEAC6B")
    d.polygon([(83, 176), (259, 265), (259, 431), (83, 337)], fill="#C88949")
    d.polygon([(259, 265), (430, 177), (430, 338), (259, 431)], fill="#AE6A36")
    d.polygon([(151, 141), (188, 123), (365, 209), (328, 229)], fill="#BF1672")
    d.polygon([(328, 229), (365, 209), (365, 276), (328, 296)], fill="#941052")
    d.line([(83, 176), (259, 265), (430, 177)], fill="#794A31", width=5)
    d.line([(259, 265), (259, 431)], fill="#794A31", width=5)
    d.polygon([(112, 242), (207, 289), (207, 337), (112, 290)], fill="white")
    d.line([(127, 264), (188, 294)], fill="#BF1672", width=7)
    d.line([(127, 279), (170, 301)], fill="#7D6B71", width=5)
    d.line([(381, 329), (381, 296)], fill="white", width=7)
    d.polygon([(381, 284), (369, 306), (393, 295)], fill="white")
    return image


def export_icons(folder):
    """Genera iconos de compilación; no escribe en carpetas de datos de usuario."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    icon = load_logo_image()
    icon.save(folder / "caja_envio.png")
    icon.save(folder / "caja_envio.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])


def data_directory() -> Path:
    """Nunca escribir datos de usuario en _MEIPASS ni junto al ejecutable."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    folder = root / APP_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def required_text(value: str, field: str, limit: int = 180) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"Completa el campo {field}.")
    if len(value) > limit:
        raise ValueError(f"{field}: máximo {limit} caracteres.")
    return value


def initial_upper(value: str) -> str:
    """Mayúscula inicial sin cambiar siglas ni el resto del nombre."""
    for index, character in enumerate(value):
        if character.isalpha():
            return value[:index] + character.upper() + value[index + 1:]
    return value


def quantity(value) -> int:
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,10}", text):
        raise ValueError("La cantidad debe ser un número entero positivo, sin puntos ni comas.")
    number = int(text)
    if not 1 <= number <= MAX_CANTIDAD:
        raise ValueError(f"La cantidad debe estar entre 1 y {MAX_CANTIDAD:,}.")
    return number


def parse_date(text: str, optional: bool = False) -> str | None:
    text = text.strip()
    if not text and optional:
        return None
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", text):
        raise ValueError("Escribe la fecha con el formato DD/MM/AAAA.")
    try:
        return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
    except ValueError as exc:
        raise ValueError("La fecha indicada no existe. Revisa el día, mes y año.") from exc


def display_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def product_state(initial: int, current: int) -> str:
    if current == 0:
        return "Agotado"
    if current == initial:
        return "Disponible"
    if current * 5 <= initial:
        return "Bajo"
    return "Con salidas"


class Database:
    """SQL parametrizado, claves foráneas y movimientos atómicos.

    El trigger descuenta la existencia y acumula las salidas en la misma
    transacción que inserta el historial. Un CHECK mantiene la igualdad
    cantidad_actual = cantidad_inicial - salidas_totales.
    """

    def __init__(self, filename: Path):
        self.path = Path(filename)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(filename), timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS regionales (
                id INTEGER PRIMARY KEY,
                nombre TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS inventarios (
                id INTEGER PRIMARY KEY,
                regional_id INTEGER NOT NULL REFERENCES regionales(id),
                nombre TEXT NOT NULL CHECK(length(trim(nombre)) > 0),
                nombre_clave TEXT NOT NULL,
                creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(regional_id, nombre_clave)
            );
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY,
                inventario_id INTEGER NOT NULL REFERENCES inventarios(id),
                objeto TEXT NOT NULL CHECK(length(trim(objeto)) > 0),
                objeto_clave TEXT NOT NULL,
                cantidad_inicial INTEGER NOT NULL
                    CHECK(typeof(cantidad_inicial) = 'integer' AND cantidad_inicial > 0),
                salidas_totales INTEGER NOT NULL DEFAULT 0
                    CHECK(typeof(salidas_totales) = 'integer' AND salidas_totales >= 0),
                cantidad_actual INTEGER NOT NULL
                    CHECK(typeof(cantidad_actual) = 'integer' AND cantidad_actual >= 0),
                CHECK(cantidad_actual = cantidad_inicial - salidas_totales),
                UNIQUE(inventario_id, objeto_clave)
            );
            CREATE TABLE IF NOT EXISTS salidas (
                id INTEGER PRIMARY KEY,
                producto_id INTEGER NOT NULL REFERENCES productos(id),
                cantidad INTEGER NOT NULL CHECK(typeof(cantidad) = 'integer' AND cantidad > 0),
                destino TEXT NOT NULL CHECK(length(trim(destino)) > 0),
                responsable TEXT NOT NULL CHECK(length(trim(responsable)) > 0),
                fecha TEXT NOT NULL,
                ubicacion TEXT NOT NULL CHECK(ubicacion IN ('REDENTOR','CIPLA','CAJICA','ESMERALDA')),
                soporte TEXT NOT NULL DEFAULT 'No es necesario',
                registrado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_salidas_producto ON salidas(producto_id);
            CREATE INDEX IF NOT EXISTS idx_salidas_fecha ON salidas(fecha);
            CREATE INDEX IF NOT EXISTS idx_salidas_ubicacion ON salidas(ubicacion);
            CREATE INDEX IF NOT EXISTS idx_productos_inventario ON productos(inventario_id);
            CREATE TRIGGER IF NOT EXISTS salida_validar_stock
            BEFORE INSERT ON salidas
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM productos WHERE id = NEW.producto_id
                ) THEN RAISE(ABORT, 'El producto no existe.') END;
                SELECT CASE WHEN NEW.cantidad > (
                    SELECT cantidad_actual FROM productos WHERE id = NEW.producto_id
                ) THEN RAISE(ABORT, 'La cantidad supera las existencias disponibles.') END;
            END;
            CREATE TRIGGER IF NOT EXISTS salida_actualizar_stock
            AFTER INSERT ON salidas
            BEGIN
                UPDATE productos SET
                    salidas_totales = salidas_totales + NEW.cantidad,
                    cantidad_actual = cantidad_actual - NEW.cantidad
                WHERE id = NEW.producto_id;
            END;
            CREATE TRIGGER IF NOT EXISTS salida_no_editar
            BEFORE UPDATE ON salidas
            BEGIN
                SELECT RAISE(ABORT, 'El historial de salidas no se puede modificar.');
            END;
            CREATE TRIGGER IF NOT EXISTS salida_no_borrar
            BEFORE DELETE ON salidas
            BEGIN
                SELECT RAISE(ABORT, 'El historial de salidas no se puede borrar.');
            END;
        """)
        with self.conn:
            # Migración aditiva compatible con las versiones anteriores.
            self.conn.execute("BEGIN IMMEDIATE")
            for table in ("inventarios", "productos"):
                columns = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if "eliminado" not in columns:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN eliminado INTEGER NOT NULL DEFAULT 0 CHECK(eliminado IN (0,1))")
            columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(salidas)")}
            if "lote_id" not in columns:
                self.conn.execute("ALTER TABLE salidas ADD COLUMN lote_id TEXT NOT NULL DEFAULT ''")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_salidas_lote ON salidas(lote_id)")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS adjuntos_salidas (
                id INTEGER PRIMARY KEY,
                salida_id INTEGER NOT NULL REFERENCES salidas(id) ON DELETE CASCADE,
                nombre TEXT NOT NULL,
                ruta TEXT NOT NULL,
                registrado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_adjuntos_salida ON adjuntos_salidas(salida_id)")
            # No reutilizar números de movimientos borrados: evita confundirlos
            # con selecciones antiguas de otra instancia abierta.
            self.conn.execute("CREATE TABLE IF NOT EXISTS secuencias (nombre TEXT PRIMARY KEY, ultimo INTEGER NOT NULL)")
            self.conn.execute("""INSERT INTO secuencias(nombre,ultimo)
                VALUES ('salidas',(SELECT COALESCE(MAX(id),0) FROM salidas))
                ON CONFLICT(nombre) DO UPDATE SET ultimo=MAX(ultimo,excluded.ultimo)""")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS anulaciones (
                salida_id INTEGER PRIMARY KEY REFERENCES salidas(id),
                motivo TEXT NOT NULL CHECK(length(trim(motivo)) > 0),
                anulado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            self.conn.execute("""CREATE TRIGGER IF NOT EXISTS anulacion_devolver_stock
                AFTER INSERT ON anulaciones BEGIN
                    UPDATE productos SET
                        cantidad_actual=cantidad_actual+(SELECT cantidad FROM salidas WHERE id=NEW.salida_id),
                        salidas_totales=salidas_totales-(SELECT cantidad FROM salidas WHERE id=NEW.salida_id)
                    WHERE id=(SELECT producto_id FROM salidas WHERE id=NEW.salida_id);
                END""")
            self.conn.execute("""CREATE TRIGGER IF NOT EXISTS anulacion_no_editar
                BEFORE UPDATE ON anulaciones BEGIN
                    SELECT RAISE(ABORT, 'La anulación no se puede modificar.');
                END""")
            self.conn.execute("DROP TRIGGER IF EXISTS salida_no_borrar")
            self.conn.execute("""CREATE TRIGGER salida_no_borrar
                BEFORE DELETE ON salidas
                WHEN NOT EXISTS (SELECT 1 FROM anulaciones WHERE salida_id=OLD.id) BEGIN
                    SELECT RAISE(ABORT, 'Solo se pueden eliminar definitivamente salidas anuladas.');
                END""")
            self.conn.execute("DROP TRIGGER IF EXISTS anulacion_no_borrar")
            self.conn.execute("""CREATE TRIGGER anulacion_no_borrar
                BEFORE DELETE ON anulaciones
                WHEN EXISTS (SELECT 1 FROM salidas WHERE id=OLD.salida_id) BEGIN
                    SELECT RAISE(ABORT, 'Elimina la salida anulada, no su devolución por separado.');
                END""")
            self.conn.execute("""CREATE TRIGGER IF NOT EXISTS salida_limpiar_anulacion
                AFTER DELETE ON salidas BEGIN
                    DELETE FROM anulaciones WHERE salida_id=OLD.id;
                END""")
            self.conn.execute("""CREATE TRIGGER IF NOT EXISTS salida_validar_activo
                BEFORE INSERT ON salidas BEGIN
                    SELECT CASE WHEN NOT EXISTS (
                        SELECT 1 FROM productos p JOIN inventarios i ON i.id=p.inventario_id
                        WHERE p.id=NEW.producto_id AND p.eliminado=0 AND i.eliminado=0
                    ) THEN RAISE(ABORT, 'El producto o inventario fue eliminado.') END;
                END""")
            self.conn.execute("""CREATE TRIGGER IF NOT EXISTS producto_validar_inventario_activo
                BEFORE INSERT ON productos BEGIN
                    SELECT CASE WHEN NOT EXISTS (
                        SELECT 1 FROM inventarios WHERE id=NEW.inventario_id AND eliminado=0
                    ) THEN RAISE(ABORT, 'El inventario no existe o fue eliminado.') END;
                END""")
            self.conn.executemany("INSERT OR IGNORE INTO regionales(nombre) VALUES (?)",
                                  [(name,) for name in REGIONALES])
        self._migrate_receipts()

    def _migrate_receipts(self):
        """Migración aditiva; no cambia existencias ni fechas históricas conocidas."""
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS facturas (
                id INTEGER PRIMARY KEY, tipo TEXT NOT NULL CHECK(tipo IN ('INGRESO','SALIDA')),
                numero INTEGER NOT NULL, clave TEXT NOT NULL UNIQUE, fecha TEXT NOT NULL,
                origen_destino TEXT NOT NULL, responsable TEXT NOT NULL, ubicacion TEXT NOT NULL DEFAULT '',
                observacion TEXT NOT NULL DEFAULT '', creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tipo,numero))''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS ingresos (
                id INTEGER PRIMARY KEY, factura_id INTEGER NOT NULL REFERENCES facturas(id),
                producto_id INTEGER NOT NULL REFERENCES productos(id),
                inventario TEXT NOT NULL, regional TEXT NOT NULL, objeto TEXT NOT NULL,
                cantidad INTEGER NOT NULL CHECK(cantidad>0))''')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_ingresos_producto ON ingresos(producto_id)')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS factura_salidas (
                salida_id INTEGER PRIMARY KEY REFERENCES salidas(id) ON DELETE CASCADE,
                factura_id INTEGER NOT NULL REFERENCES facturas(id),
                inventario TEXT NOT NULL, regional TEXT NOT NULL, objeto TEXT NOT NULL)''')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_factura_salidas ON factura_salidas(factura_id)')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS adjuntos_facturas (
                id INTEGER PRIMARY KEY, factura_id INTEGER NOT NULL REFERENCES facturas(id),
                nombre TEXT NOT NULL, ruta TEXT NOT NULL, registrado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            for kind in ('INGRESO','SALIDA'):
                self.conn.execute('''INSERT INTO secuencias(nombre,ultimo) VALUES(?,
                    (SELECT COALESCE(MAX(numero),0) FROM facturas WHERE tipo=?))
                    ON CONFLICT(nombre) DO UPDATE SET ultimo=MAX(ultimo,excluded.ultimo)''',('factura_'+kind,kind))
            missing=self.conn.execute('''SELECT p.*,i.nombre inventario,r.nombre regional FROM productos p
                JOIN inventarios i ON i.id=p.inventario_id JOIN regionales r ON r.id=i.regional_id
                WHERE NOT EXISTS(SELECT 1 FROM ingresos e WHERE e.producto_id=p.id) ORDER BY i.id,p.id''').fetchall()
            grouped={}
            for p in missing:
                grouped.setdefault(p['inventario_id'],[]).append(p)
            for rows in grouped.values():
                fid=self._new_receipt('INGRESO',date.today().isoformat(),'Saldo inicial importado','Migración automática',
                    note='Cantidades iniciales de la versión anterior. La fecha original de ingreso no estaba registrada; se usa la fecha de migración.')
                for p in rows:
                    self._income_line(fid,p,p['cantidad_inicial'])
            old=self.conn.execute('''SELECT s.*,i.nombre inventario,r.nombre regional,p.objeto
                FROM salidas s JOIN productos p ON p.id=s.producto_id JOIN inventarios i ON i.id=p.inventario_id
                JOIN regionales r ON r.id=i.regional_id
                WHERE NOT EXISTS(SELECT 1 FROM factura_salidas fs WHERE fs.salida_id=s.id) ORDER BY s.fecha,s.id''').fetchall()
            for row in old:
                key='salida:'+(row['lote_id'] or f"individual:{row['id']}")
                found=self.conn.execute('SELECT id FROM facturas WHERE clave=?',(key,)).fetchone()
                fid=found['id'] if found else self._new_receipt('SALIDA',row['fecha'],row['destino'],row['responsable'],row['ubicacion'],key=key)
                self._outgoing_line(fid,row['id'],row)

    def _new_receipt(self,kind,day,destination,responsible,location='',note='',key=None):
        self.conn.execute('UPDATE secuencias SET ultimo=ultimo+1 WHERE nombre=?',('factura_'+kind,))
        number=self.conn.execute('SELECT ultimo FROM secuencias WHERE nombre=?',('factura_'+kind,)).fetchone()[0]
        cur=self.conn.execute('''INSERT INTO facturas(tipo,numero,clave,fecha,origen_destino,responsable,ubicacion,observacion)
            VALUES(?,?,?,?,?,?,?,?)''',(kind,number,key or uuid.uuid4().hex,day,destination,responsible,location,note))
        return cur.lastrowid

    def _income_line(self,fid,p,amount):
        self.conn.execute('''INSERT INTO ingresos(factura_id,producto_id,inventario,regional,objeto,cantidad)
            VALUES(?,?,?,?,?,?)''',(fid,p['id'],p['inventario'],p['regional'],p['objeto'],amount))

    def _outgoing_line(self,fid,sid,p):
        self.conn.execute('INSERT INTO factura_salidas(salida_id,factura_id,inventario,regional,objeto) VALUES(?,?,?,?,?)',
                          (sid,fid,p['inventario'],p['regional'],p['objeto']))

    def receipt_for_exit(self,sid):
        return self.conn.execute('''SELECT f.* FROM facturas f JOIN factura_salidas fs ON fs.factura_id=f.id
            WHERE fs.salida_id=?''',(sid,)).fetchone()

    def receipt(self,fid):
        """Una instantánea coherente de cabecera y líneas para impresión."""
        with self.conn:
            self.conn.execute('BEGIN')
            head=self.conn.execute('SELECT * FROM facturas WHERE id=?',(fid,)).fetchone()
            if head is None: raise ValueError('La factura no existe.')
            if head['tipo']=='INGRESO':
                lines=self.conn.execute("SELECT *, 'Vigente' estado FROM ingresos WHERE factura_id=? ORDER BY id",(fid,)).fetchall()
            else:
                lines=self.conn.execute('''SELECT s.id,s.cantidad,fs.objeto,fs.inventario,fs.regional,
                    CASE WHEN a.salida_id IS NULL THEN 'Vigente' ELSE 'Anulada' END estado,a.motivo
                    FROM factura_salidas fs JOIN salidas s ON s.id=fs.salida_id
                    LEFT JOIN anulaciones a ON a.salida_id=s.id WHERE fs.factura_id=? ORDER BY s.id''',(fid,)).fetchall()
        return dict(head),[dict(l) for l in lines]

    def receipts(self,kind=None,inventory_id=None,number=None):
        sql='''SELECT f.* FROM facturas f WHERE (? IS NULL OR f.tipo=?) AND (? IS NULL OR f.numero=?)
            AND (? IS NULL OR EXISTS(SELECT 1 FROM ingresos e JOIN productos p ON p.id=e.producto_id
                WHERE e.factura_id=f.id AND p.inventario_id=?) OR EXISTS(
                SELECT 1 FROM factura_salidas fs JOIN salidas s ON s.id=fs.salida_id JOIN productos p ON p.id=s.producto_id
                WHERE fs.factura_id=f.id AND p.inventario_id=?)) ORDER BY f.id DESC LIMIT 500'''
        return self.conn.execute(sql,(kind,kind,number,number,inventory_id,inventory_id,inventory_id)).fetchall()

    def register_income(self,inventory_id,lines,day,origin,responsible):
        day=parse_date(day);origin=required_text(origin,'origen / proveedor');responsible=required_text(responsible,'responsable')
        if not lines: raise ValueError('Añade al menos un producto al ingreso.')
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            inv=self.conn.execute('''SELECT i.*,r.nombre regional FROM inventarios i JOIN regionales r ON r.id=i.regional_id
                WHERE i.id=? AND i.eliminado=0''',(inventory_id,)).fetchone()
            if inv is None: raise ValueError('El inventario ya no está disponible.')
            fid=self._new_receipt('INGRESO',day,origin,responsible)
            used=set()
            for line in lines:
                n=quantity(line['amount']);pid=line.get('product_id')
                if pid is None:
                    name=required_text(initial_upper(line['name']),'producto',140)
                    cur=self.conn.execute('''INSERT INTO productos(inventario_id,objeto,objeto_clave,cantidad_inicial,cantidad_actual)
                        VALUES(?,?,?,?,?)''',(inventory_id,name,name.casefold(),n,n))
                    pid=cur.lastrowid
                else:
                    p=self.conn.execute('SELECT * FROM productos WHERE id=? AND inventario_id=? AND eliminado=0',(pid,inventory_id)).fetchone()
                    if p is None: raise ValueError('Un producto ya no está activo o pertenece a otro inventario.')
                    name=p['objeto'];quantity(p['cantidad_inicial']+n)
                    self.conn.execute('UPDATE productos SET cantidad_inicial=cantidad_inicial+?,cantidad_actual=cantidad_actual+? WHERE id=?',(n,n,pid))
                if pid in used: raise ValueError('Combina las cantidades del producto repetido en una sola línea.')
                used.add(pid)
                self._income_line(fid,dict(id=pid,objeto=name,inventario=inv['nombre'],regional=inv['regional']),n)
        return fid

    def attach_receipt(self,fid,source,folder):
        copied=copy_support(Path(source),folder)
        try:
            with self.conn:
                self.conn.execute('''INSERT INTO adjuntos_facturas(factura_id,nombre,ruta) VALUES(?,?,?)''',
                    (fid,Path(source).name,copied.relative_to(folder).as_posix()))
        except Exception:
            copied.unlink(missing_ok=True)
            raise

    def receipt_documents(self,fid):
        return self.conn.execute('SELECT * FROM adjuntos_facturas WHERE factura_id=? ORDER BY id',(fid,)).fetchall()

    def close(self):
        self.conn.close()

    def regions(self):
        return self.conn.execute("SELECT * FROM regionales ORDER BY id").fetchall()

    def inventories(self, region_id=None, include_deleted=False):
        sql = """SELECT i.*, r.nombre AS regional FROM inventarios i
                 JOIN regionales r ON r.id = i.regional_id WHERE 1=1"""
        params = []
        if include_deleted:
            sql += """ AND (i.eliminado=0 OR EXISTS (
                SELECT 1 FROM productos p JOIN salidas s ON s.producto_id=p.id WHERE p.inventario_id=i.id))"""
        else:
            sql += " AND i.eliminado=0"
        if region_id is not None:
            sql += " AND i.regional_id = ?"
            params.append(region_id)
        return self.conn.execute(sql + " ORDER BY r.nombre, i.nombre", params).fetchall()

    def products(self, inventory_id=None, region_id=None, include_deleted=False):
        sql = """SELECT p.*, i.nombre AS inventario, r.nombre AS regional,
                 i.eliminado AS inventario_eliminado
                 FROM productos p JOIN inventarios i ON i.id = p.inventario_id
                 JOIN regionales r ON r.id = i.regional_id WHERE 1=1"""
        params = []
        if include_deleted:
            sql += """ AND ((p.eliminado=0 AND i.eliminado=0) OR EXISTS (
                SELECT 1 FROM salidas s WHERE s.producto_id=p.id))"""
        else:
            sql += " AND p.eliminado=0 AND i.eliminado=0"
        if inventory_id is not None:
            sql += " AND p.inventario_id = ?"
            params.append(inventory_id)
        if region_id is not None:
            sql += " AND i.regional_id = ?"
            params.append(region_id)
        return self.conn.execute(sql + " ORDER BY p.objeto, i.nombre, r.nombre", params).fetchall()

    def product(self, product_id):
        return self.conn.execute("SELECT * FROM productos WHERE id=?", (product_id,)).fetchone()

    def delete_product(self, inventory_id, product_id, expected_stock=None):
        """Eliminación lógica: mantiene IDs, historial y facturas intactos."""
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("""SELECT p.* FROM productos p
                JOIN inventarios i ON i.id=p.inventario_id
                WHERE p.id=? AND p.inventario_id=? AND p.eliminado=0 AND i.eliminado=0""",
                (product_id, inventory_id)).fetchone()
            if row is None:
                raise ValueError("El producto ya fue eliminado o no pertenece a este inventario.")
            if expected_stock is not None and expected_stock != row["cantidad_actual"]:
                raise ValueError("Las existencias cambiaron. Actualiza el inventario y vuelve a confirmar.")
            # Libera el nombre para poder crear el producto corregido.
            self.conn.execute("UPDATE productos SET eliminado=1, objeto_clave=? WHERE id=?",
                              (f"eliminado:{uuid.uuid4().hex}", product_id))

    def delete_inventory(self, inventory_id, expected_products=None):
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT * FROM inventarios WHERE id=? AND eliminado=0",
                                    (inventory_id,)).fetchone()
            if row is None:
                raise ValueError("El inventario ya fue eliminado o no existe.")
            products = self.products(inventory_id)
            snapshot = sorted((p["id"], p["cantidad_actual"]) for p in products)
            if expected_products is not None and snapshot != sorted(expected_products):
                raise ValueError("El inventario cambió. Actualízalo y vuelve a confirmar la eliminación.")
            for p in products:
                self.conn.execute("UPDATE productos SET eliminado=1, objeto_clave=? WHERE id=?",
                                  (f"eliminado:{uuid.uuid4().hex}", p["id"]))
            self.conn.execute("UPDATE inventarios SET eliminado=1, nombre_clave=? WHERE id=?",
                              (f"eliminado:{uuid.uuid4().hex}", inventory_id))

    def create_inventory(self, name: str, region_id: int) -> int:
        name = required_text(initial_upper(name), "nombre del inventario", 100)
        try:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO inventarios(nombre,nombre_clave,regional_id) VALUES (?,?,?)",
                    (name, name.casefold(), region_id))
            return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("La regional no existe o ya hay un inventario con ese nombre en ella.") from exc

    def create_product(self, inventory_id, name, initial) -> int:
        try:
            fid = self.register_income(inventory_id, [{"name":name,"amount":initial}],
                                       date.today().strftime("%d/%m/%Y"),"Registro inicial de producto","Almacén")
        except sqlite3.IntegrityError as exc:
            raise ValueError("El inventario no existe o ya contiene un producto con ese nombre.") from exc
        return self.conn.execute("SELECT producto_id FROM ingresos WHERE factura_id=?",(fid,)).fetchone()[0]

    def register_exit(self, inventory_id, product_id, amount, destination, responsible,
                      day, location, support=NO_SOPORTE) -> int:
        _, ids = self.register_exits(
            [{"inventory_id": inventory_id, "product_id": product_id, "amount": amount}],
            destination, responsible, day, location, support)
        return ids[0]

    def validate_exit_lines(self, lines):
        """Agrupa productos repetidos y valida cantidades acumuladas por ID."""
        if not lines:
            raise ValueError("Añade al menos un producto a la lista de entrega.")
        grouped = {}
        for line in lines:
            inv_id, product_id = line["inventory_id"], line["product_id"]
            amount = quantity(line["amount"])
            key = (inv_id, product_id)
            grouped[key] = quantity(grouped.get(key, 0) + amount)
        result = []
        for (inv_id, product_id), amount in grouped.items():
            row = self.conn.execute("""SELECT p.*, i.nombre AS inventario,
                i.eliminado AS inventario_eliminado, r.nombre AS regional FROM productos p
                JOIN inventarios i ON i.id=p.inventario_id
                JOIN regionales r ON r.id=i.regional_id WHERE p.id=?""", (product_id,)).fetchone()
            if row is None or row["inventario_id"] != inv_id:
                raise ValueError("Un producto de la lista no pertenece al inventario indicado.")
            if row["eliminado"] or row["inventario_eliminado"]:
                raise ValueError(f"{row['objeto']}: el producto o su inventario fue eliminado. Retíralo de la lista.")
            if amount > row["cantidad_actual"]:
                raise ValueError(f"{row['objeto']} ({row['inventario']} / {row['regional']}): "
                                 f"solicitadas {amount}, disponibles {row['cantidad_actual']}.")
            result.append({"inventory_id": inv_id, "product_id": product_id, "amount": amount,
                           "objeto": row["objeto"], "inventario": row["inventario"], "regional": row["regional"]})
        return result

    def register_exits(self, lines, destination, responsible, day, location, support=NO_SOPORTE):
        """Una transacción para toda la entrega: se guarda completa o no se guarda."""
        destination = required_text(destination, "destino")
        responsible = required_text(responsible, "responsable")
        iso_date = parse_date(day)
        if location not in UBICACIONES:
            raise ValueError("Selecciona una ubicación válida.")
        support = required_text(support, "soporte", 2000)
        batch_id = uuid.uuid4().hex
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            prepared = self.validate_exit_lines(lines)
            fid = self._new_receipt('SALIDA', iso_date, destination, responsible, location, key='salida:'+batch_id)
            ids = []
            for line in prepared:
                self.conn.execute("""UPDATE secuencias SET ultimo=MAX(ultimo,
                    (SELECT COALESCE(MAX(id),0) FROM salidas))+1 WHERE nombre='salidas'""")
                movement_id = self.conn.execute("SELECT ultimo FROM secuencias WHERE nombre='salidas'").fetchone()[0]
                cur = self.conn.execute("""INSERT INTO salidas
                    (id,producto_id,cantidad,destino,responsable,fecha,ubicacion,soporte,lote_id)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (movement_id, line["product_id"], line["amount"], destination,
                        responsible, iso_date, location, support, batch_id))
                ids.append(cur.lastrowid)
                self._outgoing_line(fid,cur.lastrowid,line)
        return batch_id, ids

    def attach_document(self, movement_id, source: Path, folder: Path):
        """Adjunta a una sola salida; cantidades y documentos previos quedan intactos."""
        if self.exit_record(movement_id) is None:
            raise ValueError("Esta salida ya no existe. Actualiza Consultas.")
        copied = copy_support(Path(source), folder)
        try:
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                if self.exit_record(movement_id) is None:
                    raise ValueError("La salida fue eliminada mientras se adjuntaba el documento.")
                cur = self.conn.execute("""INSERT INTO adjuntos_salidas(salida_id,nombre,ruta)
                    VALUES (?,?,?)""", (movement_id, Path(source).name, copied.relative_to(folder).as_posix()))
                attachment_id = cur.lastrowid
            return attachment_id
        except Exception:
            copied.unlink(missing_ok=True)
            raise

    def attachments(self, movement_id):
        row = self.exit_record(movement_id)
        if row is None:
            return []
        records = []
        if row["soporte"] != NO_SOPORTE:
            records.append(dict(nombre="Soporte original" + Path(row["soporte"]).suffix,
                                ruta=row["soporte"], registrado_en=row["registrado_en"]))
        records.extend(dict(r) for r in self.conn.execute(
            "SELECT nombre,ruta,registrado_en FROM adjuntos_salidas WHERE salida_id=? ORDER BY id", (movement_id,)))
        return records

    def exit_record(self, movement_id):
        return self.conn.execute("""SELECT s.*, p.objeto, p.inventario_id, p.eliminado AS producto_eliminado,
            i.nombre AS inventario, i.eliminado AS inventario_eliminado, r.nombre AS regional,
            CASE WHEN a.salida_id IS NULL THEN 'Vigente' ELSE 'Anulada' END AS estado,
            a.motivo AS motivo_anulacion, a.anulado_en
            FROM salidas s JOIN productos p ON p.id=s.producto_id
            JOIN inventarios i ON i.id=p.inventario_id JOIN regionales r ON r.id=i.regional_id
            LEFT JOIN anulaciones a ON a.salida_id=s.id WHERE s.id=?""", (movement_id,)).fetchone()

    def batch_exits(self, batch_id):
        if not batch_id:
            return []
        return self.conn.execute("""SELECT s.id FROM salidas s
            LEFT JOIN anulaciones a ON a.salida_id=s.id
            WHERE s.lote_id=? AND a.salida_id IS NULL ORDER BY s.id""", (batch_id,)).fetchall()

    def _restore_for_return(self, product_id):
        # Reactiva el registro original. Si su nombre fue reutilizado, conserva
        # ambos IDs y el nombre histórico; la UI identifica el recuperado por ID.
        p = self.product(product_id)
        inv = self.conn.execute("SELECT * FROM inventarios WHERE id=?", (p["inventario_id"],)).fetchone()
        if inv["eliminado"]:
            key = inv["nombre"].casefold()
            collision = self.conn.execute("SELECT 1 FROM inventarios WHERE regional_id=? AND nombre_clave=? AND id<>?",
                                          (inv["regional_id"], key, inv["id"])).fetchone()
            if collision:
                key = f"recuperado:{uuid.uuid4().hex}"
            self.conn.execute("UPDATE inventarios SET eliminado=0,nombre_clave=? WHERE id=?", (key, inv["id"]))
        if p["eliminado"]:
            key = p["objeto"].casefold()
            collision = self.conn.execute("SELECT 1 FROM productos WHERE inventario_id=? AND objeto_clave=? AND id<>?",
                                          (p["inventario_id"], key, p["id"])).fetchone()
            if collision:
                key = f"recuperado:{uuid.uuid4().hex}"
            self.conn.execute("UPDATE productos SET eliminado=0,objeto_clave=? WHERE id=?", (key, p["id"]))

    def cancel_exits(self, movement_ids, reason):
        reason = required_text(reason, "motivo de la anulación", 500)
        ids = list(dict.fromkeys(movement_ids))
        if not ids:
            raise ValueError("Selecciona una salida vigente para anular.")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            rows = []
            for movement_id in ids:
                row = self.exit_record(movement_id)
                if row is None:
                    raise ValueError(f"La salida #{movement_id} no existe.")
                if row["estado"] == "Anulada":
                    raise ValueError(f"La salida #{movement_id} ya está anulada. No se devolverán unidades dos veces.")
                rows.append(row)
            for row in rows:
                self._restore_for_return(row["producto_id"])
                self.conn.execute("INSERT INTO anulaciones(salida_id,motivo) VALUES (?,?)", (row["id"], reason))
        return sum(row["cantidad"] for row in rows)

    def delete_cancelled_exits(self, movement_ids):
        """Borra registro y anulación en una transacción; no modifica stock.

        El trigger limpia la anulación después de borrar su salida; la FK
        NO ACTION se comprueba al finalizar la sentencia. Los soportes físicos
        permanecen, pues pueden estar compartidos por otras salidas.
        """
        ids = list(dict.fromkeys(movement_ids))
        if not ids:
            raise ValueError("Selecciona al menos una salida anulada.")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            for movement_id in ids:
                row = self.exit_record(movement_id)
                if row is None:
                    raise ValueError(f"La salida #{movement_id} ya no existe. Actualiza la consulta.")
                if row["estado"] != "Anulada":
                    raise ValueError(f"La salida #{movement_id} está vigente. Debes anularla antes de borrarla.")
            self.conn.executemany("DELETE FROM salidas WHERE id=?", [(movement_id,) for movement_id in ids])
        return len(ids)

    def summary(self, inventory_id=None):
        inventory_sql = "SELECT COUNT(*) FROM inventarios WHERE eliminado=0"
        params = []
        if inventory_id is not None:
            inventory_sql += " AND id=?"
            params.append(inventory_id)
        inventories = self.conn.execute(inventory_sql, params).fetchone()[0]
        condition = " AND p.inventario_id=?" if inventory_id is not None else ""
        row = self.conn.execute("""SELECT COUNT(*) AS productos,
            COALESCE(SUM(cantidad_actual),0) AS unidades,
            COALESCE(SUM(cantidad_actual=0),0) AS agotados,
            COALESCE(SUM(cantidad_actual>0 AND cantidad_actual*5<=cantidad_inicial),0) AS bajos
            FROM productos p JOIN inventarios i ON i.id=p.inventario_id
            WHERE p.eliminado=0 AND i.eliminado=0""" + condition, params).fetchone()
        return {"inventarios": inventories, **dict(row)}

    def history(self, region_id=None, inventory_id=None, product_id=None,
                location=None, start=None, end=None, page=0, status=None):
        if start and end and start > end:
            raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")
        where, params = [], []
        for expression, value in (
            ("i.regional_id = ?", region_id), ("i.id = ?", inventory_id),
            ("p.id = ?", product_id), ("s.ubicacion = ?", location),
            ("s.fecha >= ?", start), ("s.fecha <= ?", end),
        ):
            if value is not None:
                where.append(expression)
                params.append(value)
        if status is not None:
            if status not in ("Vigente", "Anulada"):
                raise ValueError("Estado de salida no válido.")
            where.append("a.salida_id IS NULL" if status == "Vigente" else "a.salida_id IS NOT NULL")
        source = """ FROM salidas s JOIN productos p ON p.id=s.producto_id
                     JOIN inventarios i ON i.id=p.inventario_id
                     JOIN regionales r ON r.id=i.regional_id
                     LEFT JOIN anulaciones a ON a.salida_id=s.id"""
        if where:
            source += " WHERE " + " AND ".join(where)
        totals = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN a.salida_id IS NULL THEN s.cantidad ELSE 0 END),0)" + source, params).fetchone()
        rows = self.conn.execute("""SELECT s.*, p.objeto, i.nombre AS inventario,
            (SELECT COUNT(*) FROM adjuntos_salidas d WHERE d.salida_id=s.id)
                + CASE WHEN s.soporte='No es necesario' THEN 0 ELSE 1 END AS documentos,
            r.nombre AS regional, CASE WHEN a.salida_id IS NULL THEN 'Vigente' ELSE 'Anulada' END AS estado,
            a.motivo AS motivo_anulacion, a.anulado_en""" + source + " ORDER BY s.fecha DESC,s.id DESC LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, max(0, page) * PAGE_SIZE]).fetchall()
        return rows, totals[0], totals[1]


from xml.sax.saxutils import escape

def make_pdf(title,subtitle,metadata,headers,rows,sign_store=False,sign_receiver=False,note=''):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,KeepTogether
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_dir=Path(reportlab.__file__).parent / 'fonts'
    if 'IPSBodyFont' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('IPSBodyFont',str(font_dir/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('IPSBoldFont',str(font_dir/'VeraBd.ttf')))
    buffer=io.BytesIO();styles=getSampleStyleSheet()
    body=ParagraphStyle('IPSBody',fontName='IPSBodyFont',fontSize=10.5,leading=14,spaceAfter=5)
    heading=ParagraphStyle('IPSTitle',fontName='IPSBoldFont',fontSize=18,leading=22,textColor=colors.HexColor('#AF126C'))
    center=ParagraphStyle('IPSCenter',parent=body,alignment=TA_CENTER)
    table_heading=ParagraphStyle('IPSTableHeading',parent=center,fontSize=9.5,leading=12)
    def p(text,style=body): return Paragraph(escape(str(text)).replace('\n','<br/>'),style)
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=36,leftMargin=36,topMargin=32,bottomMargin=40,
                          title=title,author='IPSICOL')
    logo_bytes=io.BytesIO()
    load_logo_image().save(logo_bytes,format='PNG')
    logo_bytes.seek(0)
    logo=Image(logo_bytes,width=75,height=75,kind='proportional')
    header=Table([[logo,[p('IPSICOL',heading),p(title,heading),p(subtitle)]]],colWidths=[90,433])
    header.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
    story=[header,Spacer(1,14)]
    for k,v in metadata: story.append(p(f'{k}: {v}'))
    story.append(Spacer(1,12))
    count=len(headers)
    widths=([32,90,94,121,69,65,52] if count==7 else [32,102,95,154,60,80] if count==6 else [523/count]*count)
    table=Table([[p(h,table_heading) for h in headers]]+[[p(v,center) for v in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='CENTER')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F4DCE9')),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#D7C9D1')),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#FCF7FA')])]))
    story.append(table)
    if note: story.extend([Spacer(1,12),p(note)])
    names=[]
    if sign_store: names.append('Responsable de almacén')
    if sign_receiver: names.append('Quien recibe')
    if names:
        signatures=Table([[p('________________________________',center) for _ in names],
                          [p(n,center) for n in names]],colWidths=[523/len(names)]*len(names))
        story.append(KeepTogether([Spacer(1,50),signatures]))
    def footer(canvas,document):
        canvas.saveState();canvas.setFont('IPSBodyFont',9);canvas.setFillColor(colors.HexColor('#65535E'))
        canvas.drawString(36,23,'IPSICOL · Constancia interna de inventario')
        canvas.drawRightString(A4[0]-36,23,f'Página {document.page}');canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()

def receipt_title(head):
    if not head: return "Factura no disponible"
    return f"Factura de {'ingreso' if head['tipo']=='INGRESO' else 'salida'} #{head['numero']:08d}"


def receipt_pdf(head,lines,warehouse=False,receiver=False):
    rows=[[i,l['inventario'],l['regional'],l['objeto'],l['cantidad'],l['estado']] for i,l in enumerate(lines,1)]
    note=head['observacion']
    canceled=[f"{l['objeto']}: {l.get('motivo','')}" for l in lines if l['estado']=='Anulada']
    if canceled: note+='\nDevoluciones: '+'; '.join(canceled)
    if not lines: note+='\nNo quedan líneas: se eliminaron después de anularlas. El número permanece reservado.'
    return make_pdf(receipt_title(head),'Constancia interna de movimiento',
        [('Fecha',display_date(head['fecha'])),('Origen / Destino',head['origen_destino']),('Responsable',head['responsable']),
         ('Ubicación',head['ubicacion'] or 'No aplica')],
        ['N°','Inventario','Regional','Producto','Cantidad','Estado'],rows,warehouse,receiver,note)


def inventory_pdf(inv,products,warehouse=False,receiver=False):
    rows=[[i,inv['nombre'],inv['regional'],p['objeto'],p['cantidad_inicial'],p['salidas_totales'],p['cantidad_actual']] for i,p in enumerate(products,1)]
    return make_pdf('Constancia de inventario',inv['nombre'],
        [('Regional',inv['regional']),('Creado el (UTC)',inv['creado_en']),('Existencias consultadas',datetime.now().strftime('%d/%m/%Y %H:%M'))],
        ['N°','Inventario','Regional','Producto','Ingresadas','Salidas netas','Actual'],rows,warehouse,receiver,
        'La constancia muestra las existencias actuales. Las facturas de ingreso conservan las cantidades de cada recepción.')


def launch_gui(db: Database, folder: Path, smoke=False):
    """Importaciones gráficas diferidas: --self-test funciona sin dependencias."""
    import tkinter as tk
    import queue
    import threading
    from tkinter import filedialog, messagebox, ttk, font as tkfont
    import customtkinter as ctk
    from PIL import Image, ImageOps

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    def button(parent, text, command, secondary=False, **kwargs):
        kwargs.setdefault("font", ctk.CTkFont(size=15))
        return ctk.CTkButton(parent, text=text, command=command, height=38,
                             fg_color="#F9E5F0" if secondary else MAGENTA,
                             hover_color="#F0CEE0" if secondary else MAGENTA_HOVER,
                             text_color=MAGENTA if secondary else WHITE, **kwargs)

    def label(parent, text, **kwargs):
        kwargs.setdefault("text_color", INK)
        kwargs.setdefault("anchor", "w")
        kwargs.setdefault("font", ctk.CTkFont(size=15))
        return ctk.CTkLabel(parent, text=text, **kwargs)

    def field(parent, title, row, col, variable=None, capitalize_name=False):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=12, pady=7)
        label(box, title).pack(fill="x", pady=(0, 5))
        if capitalize_name:
            variable = variable if variable is not None else tk.StringVar(master=parent)
            def capitalize(*_):
                value = variable.get()
                corrected = initial_upper(value)
                if corrected != value:
                    variable.set(corrected)
            variable.trace_add("write", capitalize)
        entry = ctk.CTkEntry(box, textvariable=variable, height=38, font=ctk.CTkFont(size=15))
        if capitalize_name:
            entry.name_variable = variable
        entry.pack(fill="x")
        return entry

    def combo(parent, title, row, col, values, command=None):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, sticky="ew", padx=12, pady=7)
        label(box, title).pack(fill="x", pady=(0, 5))
        widget = ctk.CTkComboBox(box, values=values or ["Sin opciones"], state="readonly",
                                justify="center",
                                font=ctk.CTkFont(size=15), dropdown_font=ctk.CTkFont(size=15),
                                command=command, height=38, button_color=MAGENTA,
                                button_hover_color=MAGENTA_HOVER, dropdown_hover_color="#F9E5F0")
        # Fijar explícitamente la selección inicial también en modo readonly.
        widget.set(values[0] if values else "Sin opciones")
        widget.pack(fill="x")
        return widget

    def set_options(widget, mapping, preferred=None, empty="Sin opciones"):
        old = preferred if preferred is not None else widget.get()
        values = list(mapping) or [empty]
        widget.configure(values=values, state="readonly" if mapping else "disabled")
        widget.set(old if old in values else values[0])

    def inventory_options(rows):
        # El ID evita colisiones aun cuando el nombre contiene paréntesis.
        return {f"{r['nombre']} ({r['regional']}) · #{r['id']}" +
                (" [Eliminado]" if r["eliminado"] else
                 " [Recuperado]" if r["nombre_clave"].startswith("recuperado:") else ""): r["id"] for r in rows}

    def present_dialog(window):
        """Mostrar sin wait_visibility ni bucles de eventos anidados.

        CTkToplevel puede ocultarse brevemente mientras aplica el título en
        Windows. Esperar esa visibilidad de forma síncrona puede dejar el
        formulario sin construir; el enfoque se programa después de crearlo.
        """
        def present(attempt=0):
            if not window.winfo_exists():
                return
            window.deiconify()
            window.lift()
            if window.winfo_viewable():
                try:
                    window.grab_set()
                    window.focus_set()
                except tk.TclError:
                    pass
            elif attempt < 10:
                window.after(50, lambda: present(attempt + 1))
        window.after(250, present)

    class DateField(ctk.CTkFrame):
        def __init__(self, parent, title, row, col, value=""):
            super().__init__(parent, fg_color="transparent")
            self.grid(row=row, column=col, sticky="ew", padx=12, pady=7)
            label(self, title).pack(fill="x", pady=(0, 5))
            line = ctk.CTkFrame(self, fg_color="transparent")
            line.pack(fill="x")
            self.var = tk.StringVar(value=value)
            self.entry = ctk.CTkEntry(line, textvariable=self.var, height=38,
                                      font=ctk.CTkFont(size=15),
                                      placeholder_text="DD/MM/AAAA")
            self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            button(line, "Fecha", self.open_calendar, secondary=True, width=65).pack(side="right")

        def get(self):
            return self.var.get()

        def set(self, value):
            self.var.set(value)

        def open_calendar(self):
            try:
                chosen = date.fromisoformat(parse_date(self.get()))
            except (ValueError, TypeError):
                chosen = date.today()
            window = ctk.CTkToplevel(self)
            window.title("Seleccionar fecha")
            window.geometry("370x390")
            window.resizable(False, False)
            window.transient(self.winfo_toplevel())
            present_dialog(window)
            cursor = [chosen.year, chosen.month]
            head = ctk.CTkFrame(window, fg_color="transparent")
            head.pack(fill="x", padx=15, pady=12)
            title = label(head, "", font=ctk.CTkFont(size=17, weight="bold"))
            grid = ctk.CTkFrame(window, fg_color=WHITE)
            grid.pack(fill="both", expand=True, padx=15)
            months = ("", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                      "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")

            def select(day):
                self.set(day.strftime("%d/%m/%Y"))
                window.destroy()

            def move(delta):
                index = cursor[0] * 12 + cursor[1] - 1 + delta
                year, month = divmod(index, 12)
                if 1 <= year <= 9999:
                    cursor[:] = [year, month + 1]
                    draw()

            def draw():
                for child in grid.winfo_children():
                    child.destroy()
                year, month = cursor
                title.configure(text=f"{months[month]} {year}")
                for col, dayname in enumerate(("Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do")):
                    grid.grid_columnconfigure(col, weight=1)
                    label(grid, dayname, anchor="center").grid(row=0, column=col, padx=2)
                for row, week in enumerate(calendar.monthcalendar(year, month), 1):
                    for col, day in enumerate(week):
                        if day:
                            day_date = date(year, month, day)
                            button(grid, str(day), lambda d=day_date: select(d), width=38,
                                   secondary=(day_date != chosen)).grid(row=row, column=col, padx=2, pady=3)

            button(head, "‹", lambda: move(-1), width=35, secondary=True).pack(side="left")
            title.pack(side="left", expand=True, padx=10)
            button(head, "›", lambda: move(1), width=35, secondary=True).pack(side="right")
            button(window, "Hoy", lambda: select(date.today()), secondary=True).pack(pady=12)
            draw()

    class Table(ctk.CTkFrame):
        def __init__(self, parent, columns):
            super().__init__(parent, fg_color=WHITE)
            self.columns_spec = columns
            self.table_style = ttk.Style(self)
            self.style_name = f"Table{id(self)}.Ipsicol.Treeview"
            # Tamaños negativos de Tk = píxeles, sin conversión implícita a puntos.
            # Conservar los objetos Font impide que Tk los elimine prematuramente.
            self.body_font = tkfont.Font(root=self, family="Segoe UI", size=-16)
            self.header_font = tkfont.Font(root=self, family="Segoe UI", size=-16, weight="bold")
            self.grid_rowconfigure(0, weight=1)
            self.grid_columnconfigure(0, weight=1)
            self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings",
                                     selectmode="browse", style=self.style_name)
            for key, title, width in columns:
                self.tree.heading(key, text=title, anchor="center")
                self.tree.column(key, width=width, minwidth=70, anchor="center", stretch=True)
            self.tree.grid(row=0, column=0, sticky="nsew")
            vertical = ctk.CTkScrollbar(self, orientation="vertical", command=self.tree.yview,
                                       width=16, button_color="#AD6B91", button_hover_color=MAGENTA)
            horizontal = ctk.CTkScrollbar(self, orientation="horizontal", command=self.tree.xview,
                                         height=16, button_color="#AD6B91", button_hover_color=MAGENTA)
            vertical.grid(row=0, column=1, sticky="ns")
            horizontal.grid(row=1, column=0, sticky="ew")
            self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
            for state, fg, bg in (("Disponible", "#176B3A", "#EBF8F0"),
                                  ("Con salidas", "#776000", "#FFF9CD"),
                                  ("Bajo", "#A44805", "#FFF0DE"),
                                  ("Agotado", "#B42835", "#FDECEF")):
                self.tree.tag_configure(state, foreground=fg, background=bg)
            self.tree.tag_configure("odd", background="#FAF6F9")
            self.apply_table_scaling()

        def _set_scaling(self, *args, **kwargs):
            # Sincronizar el Treeview nativo con el escalado DPI de CustomTkinter,
            # también al mover la ventana a un monitor con otra escala.
            super()._set_scaling(*args, **kwargs)
            if hasattr(self, "tree") and hasattr(self, "header_font"):
                self.apply_table_scaling()

        def apply_table_scaling(self):
            def pixels(value):
                return max(1, round(self._apply_widget_scaling(float(value))))

            self.body_font.configure(size=-pixels(16))
            self.header_font.configure(size=-pixels(16))
            row_height = max(pixels(40), self.body_font.metrics("linespace") + pixels(14))
            self.table_style.configure(self.style_name, font=self.body_font, rowheight=row_height,
                                       background=WHITE, foreground=INK, fieldbackground=WHITE)
            self.table_style.configure(self.style_name + ".Heading", font=self.header_font,
                                       background="#F3E6ED", foreground=INK,
                                       padding=(pixels(10), pixels(12)), relief="flat")
            self.table_style.map(self.style_name, background=[("selected", MAGENTA)],
                                 foreground=[("selected", WHITE)])
            for key, title, width in self.columns_spec:
                minimum = max(pixels(80), self.header_font.measure(title) + pixels(32))
                self.tree.column(key, width=max(pixels(width), minimum), minwidth=minimum)

        def clear(self):
            children = self.tree.get_children()
            if children:
                self.tree.delete(*children)

    class App(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.title(APP_NAME)
            self.geometry("1240x800")
            self.minsize(1050, 700)
            self.configure(fg_color=BG)
            self.protocol("WM_DELETE_WINDOW", self.close)
            self.db = db
            self.support_file = None
            self.pending_exits = {}
            self.active = "Resumen"
            self.history_page = 0
            self.history_rows = {}
            self.inventory_map = {}
            self.region_map = {r["nombre"]: r["id"] for r in db.regions()}
            self.grid_rowconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=1)
            self.configure_styles()
            self.sidebar = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color=WHITE)
            self.sidebar.grid(row=0, column=0, sticky="nsew")
            self.sidebar.grid_propagate(False)
            if not self.logo():
                label(self.sidebar, "IPSICOL", font=ctk.CTkFont(size=26, weight="bold"),
                      text_color=MAGENTA).pack(padx=20, pady=(8, 0))
            label(self.sidebar, "INVENTARIOS IPSICOL", text_color=MUTED).pack(pady=(0, 30))
            self.nav = {}
            for title in ("Resumen", "Inventarios", "Ingresos", "Salidas", "Consultas"):
                b = button(self.sidebar, title, lambda t=title: self.show(t), width=174)
                b.pack(padx=18, pady=6)
                self.nav[title] = b
            button(self.sidebar, "Ubicación de datos", self.show_data, secondary=True,
                   width=174).pack(side="bottom", padx=18, pady=20)
            label(self.sidebar, "Bogotá · Cundinamarca", text_color=MUTED,
                  font=ctk.CTkFont(size=14)).pack(side="bottom", pady=3)
            self.content = ctk.CTkFrame(self, fg_color="transparent")
            self.content.grid(row=0, column=1, sticky="nsew", padx=26, pady=22)
            self.content.grid_columnconfigure(0, weight=1)
            self.content.grid_rowconfigure(1, weight=1)
            self.heading = label(self.content, "", font=ctk.CTkFont(size=28, weight="bold"))
            self.heading.grid(row=0, column=0, sticky="w", pady=(0, 18))
            self.pages = {}
            for name in self.nav:
                page = ctk.CTkFrame(self.content, fg_color="transparent")
                page.grid(row=1, column=0, sticky="nsew")
                self.pages[name] = page
            self.build_dashboard()
            self.build_inventory()
            self.build_exits()
            self.build_entries()
            self.build_history()
            self.refresh_options()
            self.show("Resumen")

        def configure_styles(self):
            style = ttk.Style(self)
            style.theme_use("clam")
            style.configure("Ipsicol.Treeview", background=WHITE, foreground=INK,
                            fieldbackground=WHITE, rowheight=40, font=("Segoe UI", -16), borderwidth=0)
            style.configure("Ipsicol.Treeview.Heading", background="#F3E6ED", foreground=INK,
                            font=("Segoe UI", -16, "bold"), padding=(10, 12), relief="flat")
            style.map("Ipsicol.Treeview", background=[("selected", MAGENTA)],
                      foreground=[("selected", WHITE)])

        def logo(self):
            try:
                image = load_logo_image()
                # Mantener proporción y resolución suficiente para pantallas HiDPI.
                scale = min(180 / image.width, 180 / image.height)
                size = (max(1, round(image.width * scale)),
                        max(1, round(image.height * scale)))
                self.logo_image = ctk.CTkImage(light_image=image, size=size)
                from PIL import ImageTk
                self.window_icon = ImageTk.PhotoImage(image.resize((64,64)))
                self.after(300,lambda: self.iconphoto(True,self.window_icon))
                ctk.CTkLabel(self.sidebar, text="", image=self.logo_image).pack(
                    padx=15, pady=(20, 8))
                return True
            except Exception:
                logging.exception("No se pudo cargar el logo integrado")
                label(self.sidebar, "I", text_color=WHITE, fg_color=MAGENTA, corner_radius=14,
                      width=65, height=65, font=ctk.CTkFont(size=42, weight="bold")).pack(pady=(28, 0))
                return False

        def report_callback_exception(self, exc_type, exc, tb):
            logging.error("Error en interfaz", exc_info=(exc_type, exc, tb))
            if isinstance(exc, (ValueError, sqlite3.IntegrityError)):
                text = str(exc)
            elif isinstance(exc, sqlite3.OperationalError):
                text = "No se pudo acceder a la base de datos. Revisa permisos, espacio y otras instancias abiertas."
            else:
                text = "No se pudo completar la operación. Revisa ipsicol.log en la carpeta de datos."
            messagebox.showerror(APP_NAME, text, parent=self)

        def show_data(self):
            messagebox.showinfo("Datos y respaldos",
                f"Base de datos y soportes:\n{folder}\n\n"
                "Para respaldarlos, cierra todas las instancias y copia esta carpeta completa.\n"
                "Los soportes seleccionados se copian automáticamente a la subcarpeta soportes.", parent=self)

        def show(self, name):
            self.active = name
            self.heading.configure(text=name if name != "Salidas" else "Registro de salidas")
            self.pages[name].tkraise()
            for title, nav in self.nav.items():
                nav.configure(fg_color=MAGENTA if title == name else WHITE,
                              text_color=WHITE if title == name else INK,
                              hover_color=MAGENTA_HOVER if title == name else "#F9E5F0")
            self.refresh_options()
            if name == "Resumen":
                self.refresh_dashboard()
            elif name == "Inventarios":
                self.refresh_inventory()
            elif name == "Consultas":
                self.search_history(reset=False)
            elif name == "Ingresos":
                self.refresh_entry_receipts()

        def build_dashboard(self):
            page = self.pages["Resumen"]
            page.grid_columnconfigure(0, weight=1)
            page.grid_rowconfigure(4, weight=1)
            label(page, "Existencias y alertas de todas las regionales", text_color=MUTED).grid(
                row=0, column=0, sticky="w", pady=(0, 15))
            selector = ctk.CTkFrame(page, fg_color=WHITE)
            selector.grid(row=1, column=0, sticky="ew", pady=(0, 14))
            selector.grid_columnconfigure(0, weight=1)
            self.dashboard_select = combo(selector, "Ver resumen de inventario", 0, 0,
                ["Todos los inventarios"], lambda _: self.refresh_dashboard())
            self.dashboard_open = button(selector, "Abrir inventario", self.open_dashboard_inventory,
                                         secondary=True, state="disabled")
            self.dashboard_open.grid(row=0, column=1, padx=12, pady=(24, 0))
            cards = ctk.CTkFrame(page, fg_color="transparent")
            cards.grid(row=2, column=0, sticky="ew")
            self.cards = {}
            for col, (key, title, color) in enumerate((
                ("inventarios", "Inventarios", MAGENTA), ("productos", "Productos registrados", INK),
                ("bajos", "Existencias bajas", "#C66A13"), ("agotados", "Agotados", "#C52D48"))):
                cards.grid_columnconfigure(col, weight=1, uniform="card")
                card = ctk.CTkFrame(cards, fg_color=WHITE, corner_radius=14)
                card.grid(row=0, column=col, sticky="ew", padx=(0, 10))
                value = label(card, "0", text_color=color, font=ctk.CTkFont(size=32, weight="bold"))
                value.pack(anchor="w", padx=15, pady=(18, 2))
                label(card, title, text_color=MUTED, font=ctk.CTkFont(size=14)).pack(
                    anchor="w", padx=15, pady=(0, 18))
                self.cards[key] = value
            line = ctk.CTkFrame(page, fg_color="transparent")
            line.grid(row=3, column=0, sticky="ew", pady=18)
            button(line, "+ Crear Nuevo Inventario", self.new_inventory).pack(side="left")
            self.unit_label = label(line, "", text_color=MUTED)
            self.unit_label.pack(side="right")
            self.alert_table = Table(page, [("objeto", "Producto en alerta", 200),
                                           ("inventario", "Inventario / Regional", 250),
                                           ("actual", "Actual", 80), ("estado", "Estado", 110)])
            self.alert_table.grid(row=4, column=0, sticky="nsew")
            self.alert_label = label(page, "", text_color=MUTED)
            self.alert_label.grid(row=5, column=0, sticky="w", pady=8)

        def refresh_dashboard(self):
            inv_id = self.dashboard_map.get(self.dashboard_select.get())
            self.dashboard_open.configure(state="normal" if inv_id is not None else "disabled")
            stats = self.db.summary(inv_id)
            for key, widget in self.cards.items():
                widget.configure(text=f"{stats[key]:,}")
            self.unit_label.configure(text=f"{stats['unidades']:,} unidades disponibles")
            self.alert_table.clear()
            count = 0
            for p in self.db.products(inv_id):
                state = product_state(p["cantidad_inicial"], p["cantidad_actual"])
                if state in ("Bajo", "Agotado"):
                    count += 1
                    self.alert_table.tree.insert("", "end", values=(p["objeto"],
                        f"{p['inventario']} ({p['regional']})", p["cantidad_actual"], state), tags=(state,))
            self.alert_label.configure(text=f"{count} productos requieren atención." if count else "Sin productos bajos ni agotados.")

        def open_dashboard_inventory(self):
            inv_id = self.dashboard_map.get(self.dashboard_select.get())
            if inv_id is not None:
                key = next((k for k, v in self.inventory_map.items() if v == inv_id), None)
                if key is not None:
                    self.inv_select.set(key)
                    self.show("Inventarios")

        def modal(self, title, height=310):
            window = ctk.CTkToplevel(self)
            window.title(title)
            window.geometry(f"480x{height}")
            window.resizable(False, False)
            window.transient(self)
            window.grid_columnconfigure(0, weight=1)
            present_dialog(window)
            return window

        def new_inventory(self):
            window = self.modal("Crear Nuevo Inventario")
            name = field(window, "Nombre del inventario", 0, 0, capitalize_name=True)
            regional = combo(window, "Regional", 1, 0, list(self.region_map))

            def save():
                try:
                    inv_id = self.db.create_inventory(name.get(), self.region_map[regional.get()])
                except (ValueError, sqlite3.Error) as exc:
                    messagebox.showerror("No se pudo crear", str(exc), parent=window)
                    return
                window.destroy()
                self.refresh_options()
                chosen = next(key for key, value in self.inventory_map.items() if value == inv_id)
                self.inv_select.set(chosen)
                self.exit_inv.set(chosen)
                self.update_exit_inventory()
                self.show("Inventarios")

            button(window, "Crear inventario", save).grid(row=2, column=0, padx=20, pady=24, sticky="ew")
            name.focus_set()

        def build_inventory(self):
            page = self.pages["Inventarios"]
            page.grid_columnconfigure(0, weight=1)
            page.grid_rowconfigure(2, weight=1)
            toolbar = ctk.CTkFrame(page, fg_color=WHITE)
            toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
            toolbar.grid_columnconfigure(0, weight=1)
            self.inv_select = combo(toolbar, "Inventario y regional", 0, 0, [], lambda _: self.refresh_inventory())
            button(toolbar, "+ Producto", self.new_product, width=115).grid(row=0, column=1, padx=12, pady=(25, 0))
            button(toolbar, "+ Inventario", self.new_inventory, secondary=True, width=115).grid(
                row=0, column=2, padx=(0, 12), pady=(25, 0))
            removal = ctk.CTkFrame(toolbar, fg_color="transparent")
            removal.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(6, 12))
            self.delete_product_button = button(removal, "Eliminar producto seleccionado",
                self.remove_product, secondary=True, state="disabled")
            self.delete_product_button.pack(side="left")
            self.delete_inventory_button = button(removal, "Eliminar inventario",
                self.remove_inventory, secondary=True, state="disabled")
            self.delete_inventory_button.pack(side="right")
            button(removal,"Imprimir PDF",self.print_inventory,secondary=True,width=130).pack(side="right",padx=10)
            self.inv_info = label(page, "", text_color=MUTED)
            self.inv_info.grid(row=1, column=0, sticky="w", pady=(0, 12))
            self.products_table = Table(page, [("objeto", "Objeto", 290), ("inicial", "Total ingresado", 135),
                ("salidas", "Salidas totales", 125), ("actual", "Cantidad actual", 135), ("estado", "Estado", 125)])
            self.products_table.grid(row=2, column=0, sticky="nsew")
            self.products_table.tree.bind("<<TreeviewSelect>>", lambda _: self.update_delete_buttons())
            label(page, "Verde: sin salidas   ·   Amarillo: más del 20 %   ·   Naranja: hasta el 20 %   ·   Rojo: 0",
                  text_color=MUTED, font=ctk.CTkFont(size=14),
                  wraplength=740, justify="left").grid(row=3, column=0, sticky="w", pady=12)

        def refresh_inventory(self):
            self.products_table.clear()
            inv_id = self.inventory_map.get(self.inv_select.get())
            self.delete_product_button.configure(state="disabled")
            self.delete_inventory_button.configure(state="normal" if inv_id is not None else "disabled")
            if inv_id is None:
                self.inv_info.configure(text="Crea un inventario para comenzar.")
                return
            rows = self.db.products(inv_id)
            for p in rows:
                state = product_state(p["cantidad_inicial"], p["cantidad_actual"])
                name = p["objeto"] + (f" [Recuperado #{p['id']}]" if p["objeto_clave"].startswith("recuperado:") else "")
                self.products_table.tree.insert("", "end", iid=str(p["id"]), values=(name,
                    p["cantidad_inicial"], p["salidas_totales"], p["cantidad_actual"], state), tags=(state,))
            self.inv_info.configure(text=f"{len(rows)} productos · {sum(p['cantidad_actual'] for p in rows):,} unidades disponibles"
                                    if rows else "Este inventario está vacío. Añade su primer producto.")

        def update_delete_buttons(self):
            selected = self.products_table.tree.selection()
            self.delete_product_button.configure(state="normal" if selected else "disabled")

        def after_removal(self):
            self.refresh_options()
            self.refresh_inventory()
            self.refresh_dashboard()
            # Se vacían resultados anteriores; la próxima consulta carga datos actuales.
            self.history_table.clear()
            self.history_rows = {}
            self.history_page = 0

        def remove_product(self):
            inv_id = self.inventory_map.get(self.inv_select.get())
            selected = self.products_table.tree.selection()
            if inv_id is None or not selected:
                messagebox.showinfo("Selecciona un producto", "Selecciona la fila del producto que deseas eliminar.", parent=self)
                return
            product_id = int(selected[0])
            row = self.db.product(product_id)
            if row is None or row["eliminado"] or row["inventario_id"] != inv_id:
                self.after_removal()
                messagebox.showinfo("Producto no disponible", "El producto ya no está disponible. La lista se actualizó.", parent=self)
                return
            text = (f"Producto: {row['objeto']}\nInventario: {self.inv_select.get()}\n"
                    f"Cantidad inicial: {row['cantidad_inicial']}\n"
                    f"Existencias actuales: {row['cantidad_actual']}\n\n"
                    "Se retirará de este inventario y de los totales del Resumen.\n"
                    "Las salidas anteriores y sus soportes seguirán en Consultas.\n"
                    "Si lo ingresaste por error, podrás crearlo nuevamente con los datos correctos.\n\n"
                    "¿Eliminar este producto?")
            if not messagebox.askyesno("Eliminar producto", text, parent=self, default="no"):
                return
            try:
                self.db.delete_product(inv_id, product_id, expected_stock=row["cantidad_actual"])
            finally:
                self.after_removal()
            messagebox.showinfo("Producto eliminado", "El producto fue retirado del inventario.", parent=self)

        def remove_inventory(self):
            inv_id = self.inventory_map.get(self.inv_select.get())
            if inv_id is None:
                return
            rows = self.db.products(inv_id)
            units = sum(p["cantidad_actual"] for p in rows)
            text = (f"Inventario: {self.inv_select.get()}\nProductos: {len(rows)}\n"
                    f"Unidades que aún contiene: {units}\n\n"
                    "Se retirarán el inventario y todos sus productos de la gestión activa.\n"
                    "Las salidas anteriores y sus soportes se conservarán en Consultas.\n\n")
            if units:
                text += "Este inventario todavía tiene existencias; también se retirarán de los totales.\n\n"
            text += "¿Eliminar este inventario completo?"
            if not messagebox.askyesno("Eliminar inventario completo", text, parent=self, default="no"):
                return
            try:
                self.db.delete_inventory(inv_id, expected_products=[(p["id"], p["cantidad_actual"]) for p in rows])
            finally:
                self.after_removal()
            messagebox.showinfo("Inventario eliminado", "El inventario fue retirado de la gestión activa.", parent=self)

        def new_product(self):
            inv_id = self.inventory_map.get(self.inv_select.get())
            if inv_id is None:
                messagebox.showinfo("Inventario requerido", "Crea o selecciona un inventario primero.", parent=self)
                return
            window = self.modal("Añadir producto", 365)
            label(window, self.inv_select.get(), wraplength=440).grid(row=0, column=0, padx=18, pady=10, sticky="w")
            name = field(window, "Objeto / nombre del producto", 1, 0, capitalize_name=True)
            initial = field(window, "Cantidad inicial (unidades enteras)", 2, 0)

            def save():
                try:
                    self.db.create_product(inv_id, name.get(), initial.get())
                except (ValueError, sqlite3.Error) as exc:
                    messagebox.showerror("No se pudo añadir", str(exc), parent=window)
                    return
                window.destroy()
                self.refresh_options()
                self.refresh_inventory()

            button(window, "Añadir producto", save).grid(row=3, column=0, padx=20, pady=22, sticky="ew")
            name.focus_set()

        def build_exits(self):
            page = self.pages["Salidas"]
            form = ctk.CTkScrollableFrame(page, fg_color=WHITE, corner_radius=14)
            form.pack(fill="both", expand=True)
            for col in (0, 1):
                form.grid_columnconfigure(col, weight=1, uniform="form")
            self.exit_inv = combo(form, "Inventario origen", 0, 0, [], lambda _: self.update_exit_inventory())
            self.exit_regional_var = tk.StringVar()
            regional = field(form, "Regional (automática)", 0, 1, self.exit_regional_var)
            regional.configure(state="disabled")
            self.exit_product = combo(form, "Producto", 1, 0, [], lambda _: self.update_stock())
            self.exit_quantity = field(form, "Cantidad que vas a añadir", 1, 1)
            self.stock_label = label(form, "", text_color=MAGENTA)
            self.stock_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 8))
            cart_actions = ctk.CTkFrame(form, fg_color="transparent")
            cart_actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=15, pady=8)
            self.add_exit_button = button(cart_actions, "Añadir a la entrega", self.add_exit_line)
            self.add_exit_button.pack(side="left")
            self.remove_exit_button = button(cart_actions, "Quitar seleccionado", self.remove_exit_line,
                                             secondary=True, state="disabled")
            self.remove_exit_button.pack(side="left", padx=8)
            self.clear_exit_button = button(cart_actions, "Vaciar lista", self.clear_exit_lines,
                                            secondary=True, state="disabled")
            self.clear_exit_button.pack(side="right")
            self.cart_table = Table(form, [("inventario", "Inventario", 205), ("regional", "Regional", 130),
                                           ("producto", "Producto", 230), ("cantidad", "Cantidad", 95)])
            self.cart_table.configure(height=210)
            self.cart_table.grid_propagate(False)
            self.cart_table.grid(row=4, column=0, columnspan=2, sticky="ew", padx=15, pady=8)
            self.cart_table.tree.bind("<<TreeviewSelect>>", lambda _: self.remove_exit_button.configure(
                state="normal" if self.cart_table.tree.selection() else "disabled"))
            self.cart_info = label(form, "Lista vacía. Añade productos de uno o varios inventarios.", text_color=MUTED)
            self.cart_info.grid(row=5, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 8))
            label(form, "Datos comunes de esta entrega", font=ctk.CTkFont(size=17, weight="bold")).grid(
                row=6, column=0, columnspan=2, sticky="w", padx=15, pady=(12, 4))
            self.exit_destination = field(form, "Destino", 7, 0)
            self.exit_responsible = field(form, "Responsable", 7, 1)
            self.exit_date = DateField(form, "Fecha de salida (DD/MM/AAAA)", 8, 0, date.today().strftime("%d/%m/%Y"))
            self.exit_location = combo(form, "Ubicación", 8, 1, list(UBICACIONES))
            self.support_var = tk.BooleanVar(value=False)
            ctk.CTkCheckBox(form, text="Añadir factura/autorización (PDF o imagen) para esta entrega", variable=self.support_var,
                            font=ctk.CTkFont(size=15), command=self.toggle_support,
                            fg_color=MAGENTA, hover_color=MAGENTA_HOVER).grid(
                                row=9, column=0, columnspan=2, sticky="w", padx=15, pady=(16, 10))
            self.support_label = label(form, NO_SOPORTE, text_color=MUTED, wraplength=550)
            self.support_label.grid(row=10, column=0, columnspan=2, padx=15, sticky="w")
            self.support_button = button(form, "Cambiar imagen", self.choose_support, secondary=True, state="disabled")
            self.support_button.grid(row=11, column=0, padx=15, pady=10, sticky="w")
            label(form, "Revisa la lista: se registrarán todos sus productos en una sola entrega.",
                  text_color=MUTED, wraplength=750).grid(row=12, column=0, columnspan=2, padx=15, pady=(12, 8), sticky="w")
            self.save_exit_button = button(form, "Registrar entrega completa", self.save_exit, width=260, state="disabled")
            self.save_exit_button.grid(row=13, column=0, padx=15, pady=(8, 22), sticky="w")

        def add_exit_line(self):
            inv_id = self.inventory_map.get(self.exit_inv.get())
            product_id = self.exit_product_map.get(self.exit_product.get())
            if inv_id is None or product_id is None:
                raise ValueError("Selecciona el inventario y el producto que vas a añadir.")
            amount = quantity(self.exit_quantity.get())
            previous = self.pending_exits.get(product_id, {}).get("amount", 0)
            lines = self.db.validate_exit_lines([
                {"inventory_id": inv_id, "product_id": product_id, "amount": amount + previous}])
            self.pending_exits[product_id] = lines[0]
            self.exit_quantity.delete(0, "end")
            self.refresh_exit_cart()

        def refresh_exit_cart(self):
            self.cart_table.clear()
            for product_id, line in self.pending_exits.items():
                self.cart_table.tree.insert("", "end", iid=str(product_id), values=(
                    f"{line['inventario']} · #{line['inventory_id']}", line["regional"],
                    f"{line['objeto']} · #{product_id}", line["amount"]))
            count = len(self.pending_exits)
            units = sum(line["amount"] for line in self.pending_exits.values())
            inventories = len({line["inventory_id"] for line in self.pending_exits.values()})
            self.cart_info.configure(text=f"{count} productos · {units} unidades · {inventories} inventarios" if count
                else "Lista vacía. Añade productos de uno o varios inventarios.")
            self.clear_exit_button.configure(state="normal" if count else "disabled")
            self.remove_exit_button.configure(state="disabled")
            self.update_stock()

        def remove_exit_line(self):
            selected = self.cart_table.tree.selection()
            if selected:
                self.pending_exits.pop(int(selected[0]), None)
                self.refresh_exit_cart()

        def clear_exit_lines(self):
            if self.pending_exits and messagebox.askyesno("Vaciar lista",
                    "¿Quitar todos los productos de esta entrega pendiente?", parent=self, default="no"):
                self.pending_exits.clear()
                self.refresh_exit_cart()

        def refresh_options(self):
            self.inventory_rows = self.db.inventories()
            self.inventory_map = inventory_options(self.inventory_rows)
            self.dashboard_map = {"Todos los inventarios": None, **self.inventory_map}
            set_options(self.dashboard_select, self.dashboard_map)
            set_options(self.inv_select, self.inventory_map, empty="Sin inventarios")
            set_options(self.exit_inv, self.inventory_map, empty="Sin inventarios")
            self.update_exit_inventory()
            self.update_filter_inventories()
            if hasattr(self,"entry_inv"):
                set_options(self.entry_inv,self.inventory_map,empty="Sin inventarios")

        def update_exit_inventory(self):
            inv_id = self.inventory_map.get(self.exit_inv.get())
            inv = next((r for r in self.inventory_rows if r["id"] == inv_id), None)
            self.exit_regional_var.set(inv["regional"] if inv else "")
            rows = self.db.products(inv_id) if inv_id is not None else []
            self.exit_product_map = {f"{p['objeto']} · #{p['id']}": p["id"] for p in rows}
            set_options(self.exit_product, self.exit_product_map, empty="Sin productos")
            self.update_stock()

        def update_stock(self):
            product_id = self.exit_product_map.get(self.exit_product.get())
            p = self.db.product(product_id) if product_id is not None else None
            reserved = self.pending_exits.get(product_id, {}).get("amount", 0)
            remaining = max(0, p["cantidad_actual"] - reserved) if p else 0
            self.stock_label.configure(text=(f"Existencias: {p['cantidad_actual']} · En esta lista: {reserved} · "
                f"Puedes añadir: {remaining}" if p else "Selecciona un inventario con productos."))
            self.add_exit_button.configure(state="normal" if p and not p["eliminado"] and remaining else "disabled")
            self.save_exit_button.configure(state="normal" if self.pending_exits else "disabled")

        def toggle_support(self):
            if self.support_var.get():
                self.choose_support()
            else:
                self.support_file = None
                self.support_label.configure(text=NO_SOPORTE)
                self.support_button.configure(state="disabled")

        def choose_support(self):
            filename = filedialog.askopenfilename(parent=self, title="Seleccionar factura o autorización",
                filetypes=SUPPORT_TYPES)
            if filename:
                try:
                    path = Path(filename)
                    validate_support(path)
                    self.support_file = path
                except Exception as exc:
                    messagebox.showerror("Documento no válido", f"No se pudo usar el archivo: {exc}", parent=self)
            enabled = self.support_file is not None
            self.support_var.set(enabled)
            self.support_label.configure(text=self.support_file.name if enabled else NO_SOPORTE)
            self.support_button.configure(state="normal" if enabled else "disabled")

        def save_exit(self):
            copied = None
            try:
                if self.exit_quantity.get().strip():
                    raise ValueError("Hay una cantidad escrita que aún no se añadió. Pulsa «Añadir a la entrega» o borra ese campo.")
                lines = self.db.validate_exit_lines(list(self.pending_exits.values()))
                destination = required_text(self.exit_destination.get(), "destino")
                responsible = required_text(self.exit_responsible.get(), "responsable")
                day = self.exit_date.get()
                parse_date(day)
                if self.support_var.get() and (not self.support_file or not self.support_file.is_file()):
                    raise ValueError("Selecciona nuevamente el documento de soporte.")
                units = sum(line["amount"] for line in lines)
                inventories = len({line["inventory_id"] for line in lines})
                if not messagebox.askyesno("Confirmar entrega completa",
                    f"Productos: {len(lines)}\nUnidades: {units}\nInventarios: {inventories}\n"
                    f"Destino: {destination}\nResponsable: {responsible}\n"
                    f"Ubicación: {self.exit_location.get()}\nFecha: {day}\n\n"
                    "¿Registrar todos los productos de la lista?", parent=self, default="no"):
                    return
                self.save_exit_button.configure(state="disabled")
                support = NO_SOPORTE
                if self.support_var.get():
                    copied = copy_support(self.support_file, folder)
                    support = copied.relative_to(folder).as_posix()
                batch_id, ids = self.db.register_exits(lines, destination, responsible, day,
                                                       self.exit_location.get(), support)
            except Exception:
                if copied is not None:
                    copied.unlink(missing_ok=True)
                raise
            finally:
                self.update_stock()
            self.pending_exits.clear()
            self.refresh_exit_cart()
            for entry in (self.exit_quantity, self.exit_destination, self.exit_responsible):
                entry.delete(0, "end")
            self.support_var.set(False)
            self.toggle_support()
            self.refresh_options()
            self.refresh_inventory()
            self.refresh_dashboard()
            messagebox.showinfo("Entrega registrada", f"{receipt_title(self.db.receipt_for_exit(ids[0]))} guardada.\n"
                f"{len(ids)} productos · {units} unidades.\nTodos los inventarios fueron actualizados.", parent=self)

        def exit_receipt_number(self,sid):
            row=self.db.receipt_for_exit(sid)
            return f"#{row['numero']:08d}" if row else f"Movimiento #{sid}"

        def print_dialog(self,title,renderer):
            window=self.modal('Imprimir constancia',330)
            label(window,title,wraplength=430,font=ctk.CTkFont(size=17,weight='bold')).grid(row=0,column=0,padx=18,pady=18,sticky='ew')
            warehouse=tk.BooleanVar(value=False);receiver=tk.BooleanVar(value=False)
            ctk.CTkCheckBox(window,text='Firma de responsable de almacén',variable=warehouse,
                font=ctk.CTkFont(size=16)).grid(row=1,column=0,padx=24,pady=10,sticky='w')
            ctk.CTkCheckBox(window,text='Firma de quien recibe',variable=receiver,
                font=ctk.CTkFont(size=16)).grid(row=2,column=0,padx=24,pady=10,sticky='w')
            label(window,'Sin marcar: el PDF no incluye espacios de firma.\nAbre el PDF y utiliza Imprimir (Ctrl+P).',
                  wraplength=430,justify='left',text_color=MUTED).grid(row=3,column=0,padx=18,pady=10)
            def save():
                filename=filedialog.asksaveasfilename(parent=window,title='Guardar constancia PDF',
                    defaultextension='.pdf',initialfile=re.sub(r'[^\w -]','',title)+'.pdf',filetypes=[('PDF','*.pdf')])
                if not filename: return
                temporary=None
                try:
                    data=renderer(warehouse.get(),receiver.get())
                    target=Path(filename)
                    temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                    temporary.write_bytes(data)
                    os.replace(temporary,target)
                    window.destroy()
                    self.open_document(target,self)
                except Exception as exc:
                    if temporary: temporary.unlink(missing_ok=True)
                    messagebox.showerror('No se pudo generar el PDF',str(exc),parent=window)
            button(window,'Guardar PDF y abrir',save).grid(row=4,column=0,padx=18,pady=15,sticky='ew')

        def print_receipt(self,fid):
            head,_=self.db.receipt(fid)
            def render(a,b):
                current,lines=self.db.receipt(fid)
                return receipt_pdf(current,lines,a,b)
            self.print_dialog(receipt_title(head),render)

        def print_inventory(self):
            inv_id=self.inventory_map.get(self.inv_select.get())
            if inv_id is None:
                messagebox.showinfo('Selecciona un inventario','Selecciona el inventario que deseas imprimir.',parent=self)
                return
            def render(a,b):
                with self.db.conn:
                    self.db.conn.execute('BEGIN')
                    inv=self.db.conn.execute('''SELECT i.*,r.nombre regional FROM inventarios i
                        JOIN regionales r ON r.id=i.regional_id WHERE i.id=?''',(inv_id,)).fetchone()
                    products=self.db.products(inv_id)
                return inventory_pdf(dict(inv),[dict(p) for p in products],a,b)
            self.print_dialog('Constancia de inventario',render)

        def build_entries(self):
            page=self.pages['Ingresos']
            page.grid_columnconfigure(0,weight=1)
            page.grid_rowconfigure(2,weight=1)
            bar=ctk.CTkFrame(page,fg_color=WHITE)
            bar.grid(row=0,column=0,sticky='ew',pady=(0,10))
            bar.grid_columnconfigure(0,weight=1)
            self.entry_inv=combo(bar,'Inventario para registrar ingreso',0,0,[])
            button(bar,'+ Registrar ingreso',self.new_income,width=170).grid(row=0,column=1,padx=12,pady=(22,0))
            tools=ctk.CTkFrame(page,fg_color='transparent')
            tools.grid(row=1,column=0,sticky='ew',pady=10)
            label(tools,'Facturas de ingreso').pack(side='left')
            self.income_number=ctk.CTkEntry(tools,placeholder_text='N.º de factura',width=140,height=38,font=ctk.CTkFont(size=15))
            self.income_number.pack(side='left',padx=12)
            button(tools,'Buscar',self.refresh_entry_receipts,secondary=True,width=85).pack(side='left')
            button(tools,'Ver detalle / PDF',self.income_detail,secondary=True,width=160).pack(side='right')
            self.income_table=Table(page,[('numero','Factura de ingreso',155),('fecha','Fecha',110),
                ('origen','Origen / Proveedor',260),('responsable','Responsable',240)])
            self.income_table.grid(row=2,column=0,sticky='nsew')
            self.income_table.tree.bind('<Double-1>',lambda _:self.income_detail())
            label(page,'Últimas 500 facturas de todos los inventarios. Busca por número para localizar una anterior.',
                  text_color=MUTED,wraplength=800).grid(row=3,column=0,sticky='w',pady=12)

        def refresh_entry_receipts(self):
            raw=self.income_number.get().strip()
            if raw and not raw.isdigit(): raise ValueError('El número de factura debe contener solo dígitos.')
            self.income_table.clear()
            for row in self.db.receipts('INGRESO',number=int(raw) if raw else None):
                self.income_table.tree.insert('','end',iid=str(row['id']),values=(f"#{row['numero']:08d}",
                    display_date(row['fecha']),row['origen_destino'],row['responsable']))

        def run_background(self,window,controls,job,completed):
            """Trabajo de SQLite/copias con conexión propia y sondeo no bloqueante."""
            if getattr(self,'io_running',False): return
            self.io_running=True
            for control in controls: control.configure(state='disabled')
            window.protocol('WM_DELETE_WINDOW',lambda:None)
            mailbox=queue.Queue()
            def worker():
                connection=None
                try:
                    connection=Database(self.db.path)
                    result=job(connection)
                    mailbox.put((True,result))
                except Exception as exc:
                    logging.exception('No se pudo guardar la operación')
                    mailbox.put((False,str(exc)))
                finally:
                    if connection: connection.close()
            def poll():
                try: success,result=mailbox.get_nowait()
                except queue.Empty:
                    window.after(80,poll);return
                self.io_running=False
                for control in controls: control.configure(state='normal')
                window.protocol('WM_DELETE_WINDOW',window.destroy)
                if not success:
                    messagebox.showerror('No se pudo guardar',result,parent=window);return
                completed(result)
            threading.Thread(target=worker,daemon=True).start()
            window.after(80,poll)

        def new_income(self):
            inv_id=self.inventory_map.get(self.entry_inv.get())
            if inv_id is None:
                messagebox.showinfo('Inventario requerido','Crea un inventario desde Resumen.',parent=self);return
            window=self.modal('Registrar ingreso',700)
            window.geometry(f'800x{min(760,self.winfo_screenheight()-100)}')
            window.resizable(True,True)
            window.grid_rowconfigure(0,weight=1)
            form=ctk.CTkScrollableFrame(window,fg_color=WHITE)
            form.grid(row=0,column=0,sticky='nsew',padx=10,pady=10)
            form.grid_columnconfigure(0,weight=1);form.grid_columnconfigure(1,weight=1)
            label(form,self.entry_inv.get(),wraplength=700,font=ctk.CTkFont(size=17,weight='bold')).grid(row=0,column=0,columnspan=2,padx=12,pady=10)
            options={'Nuevo producto':None,**{f"{p['objeto']} · #{p['id']}":p['id'] for p in self.db.products(inv_id)}}
            choice=combo(form,'Producto existente o nuevo',1,0,list(options))
            name=field(form,'Nombre (solo para producto nuevo)',1,1,capitalize_name=True)
            amount=field(form,'Cantidad a ingresar',2,0)
            pending=[]
            preview=Table(form,[('producto','Producto',420),('cantidad','Cantidad',120)])
            preview.configure(height=180)
            preview.grid(row=3,column=0,columnspan=2,sticky='nsew',padx=12,pady=12)
            def refresh():
                preview.clear()
                for i,line in enumerate(pending): preview.tree.insert('','end',iid=str(i),values=(line['display'],line['amount']))
            def add():
                try:
                    pid=options[choice.get()];n=quantity(amount.get())
                    title=required_text(initial_upper(name.get()),'nombre del producto',140) if pid is None else choice.get()
                    key=('id',pid) if pid is not None else ('name',title.casefold())
                    current=next((p for p in pending if p['key']==key),None)
                    if current: current['amount']=quantity(current['amount']+n)
                    else: pending.append(dict(product_id=pid,name=title,amount=n,key=key,display=title))
                    amount.delete(0,'end');name.delete(0,'end');refresh()
                except ValueError as exc: messagebox.showerror('Revisa los datos',str(exc),parent=window)
            add_button=button(form,'Añadir a la lista',add)
            add_button.grid(row=2,column=1,padx=12,pady=(24,0))
            def remove():
                selected=preview.tree.selection()
                if selected: pending.pop(int(selected[0]));refresh()
            remove_button=button(form,'Retirar seleccionado',remove,secondary=True)
            remove_button.grid(row=4,column=0,padx=12,pady=4,sticky='w')
            day=DateField(form,'Fecha del ingreso',5,0)
            day.set(date.today().strftime('%d/%m/%Y'))
            origin=field(form,'Origen / Proveedor',5,1)
            responsible=field(form,'Responsable del ingreso',6,0)
            label(form,'Puedes adjuntar la factura después desde el detalle del ingreso.',wraplength=340,text_color=MUTED).grid(row=6,column=1,padx=12,pady=8)
            def save():
                try:
                    if amount.get().strip(): raise ValueError('Añade primero la cantidad escrita a la lista, o borra ese campo.')
                    if not pending: raise ValueError('Añade al menos un producto.')
                    args=(inv_id,[dict(p) for p in pending],day.get(),required_text(origin.get(),'origen / proveedor'),required_text(responsible.get(),'responsable'))
                    parse_date(day.get())
                    if not messagebox.askyesno('Confirmar ingreso',f"Productos: {len(pending)}\nUnidades: {sum(p['amount'] for p in pending)}\n\n¿Registrar este ingreso?",parent=window,default='no'): return
                except ValueError as exc:
                    messagebox.showerror('Revisa el ingreso',str(exc),parent=window);return
                def completed(fid):
                    window.destroy()
                    self.refresh_options();self.refresh_inventory();self.refresh_dashboard();self.refresh_entry_receipts()
                    self.income_table.tree.selection_set(str(fid))
                    self.show_receipt(fid)
                self.run_background(window,[save_button,add_button,remove_button],lambda connection:connection.register_income(*args),completed)
            save_button=button(form,'Registrar ingreso completo',save)
            save_button.grid(row=7,column=0,columnspan=2,sticky='ew',padx=12,pady=20)

        def income_detail(self):
            selected=self.income_table.tree.selection()
            if not selected:
                messagebox.showinfo('Selecciona un ingreso','Selecciona la factura de ingreso que deseas consultar.',parent=self);return
            self.show_receipt(int(selected[0]))

        def show_receipt(self,fid):
            head,lines=self.db.receipt(fid)
            window=ctk.CTkToplevel(self)
            window.title(receipt_title(head));window.geometry('820x650');window.minsize(640,480)
            window.transient(self)
            frame=ctk.CTkScrollableFrame(window,fg_color=WHITE)
            frame.pack(fill='both',expand=True,padx=14,pady=14)
            label(frame,receipt_title(head),font=ctk.CTkFont(size=21,weight='bold')).pack(anchor='w',pady=12)
            label(frame,f"Fecha: {display_date(head['fecha'])}\nOrigen / Destino: {head['origen_destino']}\nResponsable: {head['responsable']}",
                  wraplength=720,justify='left').pack(anchor='w',pady=8)
            table=Table(frame,[('inv','Inventario / Regional',240),('producto','Producto',290),('cantidad','Cantidad',95)])
            table.configure(height=240);table.pack(fill='both',expand=True,pady=8)
            for line in lines: table.tree.insert('','end',values=(f"{line['inventario']} ({line['regional']})",line['objeto'],line['cantidad']))
            if head['observacion']: label(frame,head['observacion'],wraplength=720,justify='left',text_color=MUTED).pack(pady=8)
            button(frame,'Imprimir factura / constancia PDF',lambda:self.print_receipt(fid)).pack(pady=8)
            def attach():
                source=filedialog.askopenfilename(parent=window,title='Añadir factura o soporte',filetypes=SUPPORT_TYPES)
                if not source: return
                def completed(_):
                    window.destroy();self.show_receipt(fid)
                self.run_background(window,[attach_button],lambda connection:connection.attach_receipt(fid,source,folder),completed)
            attach_button=button(frame,'Adjuntar factura o soporte',attach,secondary=True)
            attach_button.pack(pady=8)
            for document in self.db.receipt_documents(fid):
                label(frame,document['nombre'],wraplength=720).pack(anchor='w',pady=6)
                path=folder / document['ruta']
                button(frame,'Abrir documento',lambda p=path:self.open_document(p,window),secondary=True).pack(pady=4)

        def build_history(self):
            page = self.pages["Consultas"]
            page.grid_columnconfigure(0, weight=1)
            page.grid_rowconfigure(3, weight=1)
            # Filtros plegables: la tabla ocupa casi toda la altura al entrar.
            filters = ctk.CTkFrame(page, fg_color=WHITE)
            self.history_filters = filters
            self.history_filters_visible = False
            filters.grid(row=0, column=0, sticky="ew")
            filters.grid_remove()
            for col in range(3):
                filters.grid_columnconfigure(col, weight=1, uniform="filter")
            self.filter_region = combo(filters, "Regional", 0, 0, [TODOS] + list(self.region_map),
                                       lambda _: self.update_filter_inventories())
            self.filter_inventory = combo(filters, "Inventario", 0, 1, [TODOS],
                                          lambda _: self.update_filter_products())
            self.filter_location = combo(filters, "Ubicación", 0, 2, [TODOS] + list(UBICACIONES))
            self.filter_product = combo(filters, "Producto", 1, 0, [TODOS])
            self.filter_start = DateField(filters, "Desde (DD/MM/AAAA)", 1, 1)
            self.filter_end = DateField(filters, "Hasta (DD/MM/AAAA)", 1, 2)
            self.filter_status = combo(filters, "Estado de la salida", 2, 0, [TODOS, "Vigente", "Anulada"])
            button(filters, "Aplicar filtros", self.search_history).grid(row=2, column=1, padx=12, pady=(22, 0))
            button(filters, "Limpiar filtros", self.clear_filters, secondary=True).grid(
                row=2, column=2, padx=12, pady=(22, 0))
            actions = ctk.CTkFrame(page, fg_color="transparent")
            actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
            self.filters_button = button(actions, "Mostrar filtros", self.toggle_history_filters, secondary=True, width=135)
            self.filters_button.pack(side="left", padx=(0, 8))
            self.cancel_button = button(actions, "Devolver producto", lambda: self.cancel_history("one"),
                                        secondary=True, state="disabled", width=158)
            self.cancel_button.pack(side="left", padx=(0, 8))
            self.cancel_batch_button = button(actions, "Devolver entrega", lambda: self.cancel_history("all"),
                                              secondary=True, state="disabled", width=155)
            self.cancel_batch_button.pack(side="left", padx=(0, 8))
            self.attach_button = button(actions, "Adjuntar factura", self.attach_history_document,
                                        state="disabled", width=145)
            self.attach_button.pack(side="left", padx=(0, 8))
            button(actions, "Ver detalle", self.history_detail, secondary=True, width=105).pack(side="right")
            self.history_info = label(page, "", text_color=MUTED)
            self.history_info.grid(row=2, column=0, sticky="w", pady=(0, 6))
            self.history_table = Table(page, [("id", "N.º", 70), ("fecha", "Fecha", 105),
                ("estado", "Estado", 115), ("entrega", "Factura de salida", 160),
                ("regional", "Regional", 125), ("inventario", "Inventario", 170),
                ("producto", "Producto", 190), ("cantidad", "Cantidad", 85),
                ("destino", "Destino", 170), ("responsable", "Responsable", 180),
                ("ubicacion", "Ubicación", 115), ("soporte", "Soporte / Factura", 200)])
            self.history_table.grid(row=3, column=0, sticky="nsew")
            self.history_table.tree.configure(selectmode="extended")
            self.history_table.tree.bind("<Double-1>", lambda _: self.history_detail())
            self.history_table.tree.tag_configure("anulada", background="#EDE9EF", foreground="#63536C")
            self.history_table.tree.bind("<<TreeviewSelect>>", lambda _: self.update_cancel_button())
            pagination = ctk.CTkFrame(page, fg_color="transparent")
            pagination.grid(row=4, column=0, sticky="ew", pady=(8, 0))
            self.previous_button = button(pagination, "‹ Anterior", lambda: self.change_page(-1), secondary=True)
            self.previous_button.pack(side="left")
            self.page_info = label(pagination, "", text_color=MUTED)
            self.page_info.pack(side="left", padx=16)
            self.next_button = button(pagination, "Siguiente ›", lambda: self.change_page(1), secondary=True)
            self.next_button.pack(side="right")
            self.delete_cancelled_button = button(pagination, "Eliminar anuladas", self.delete_cancelled_history,
                                                  secondary=True, state="disabled", width=160)
            self.delete_cancelled_button.pack(side="right", padx=12)

        def toggle_history_filters(self):
            self.history_filters_visible = not self.history_filters_visible
            if self.history_filters_visible:
                self.history_filters.grid()
            else:
                self.history_filters.grid_remove()
            self.filters_button.configure(text="Ocultar filtros" if self.history_filters_visible else "Mostrar filtros")

        def update_filter_inventories(self):
            region = self.region_map.get(self.filter_region.get())
            self.filter_inventory_map = {TODOS: None, **inventory_options(self.db.inventories(region, include_deleted=True))}
            set_options(self.filter_inventory, self.filter_inventory_map)
            self.update_filter_products()

        def update_filter_products(self):
            inv_id = self.filter_inventory_map.get(self.filter_inventory.get())
            region_id = self.region_map.get(self.filter_region.get())
            rows = self.db.products(inv_id, region_id, include_deleted=True)
            self.filter_product_map = {TODOS: None}
            for p in rows:
                text = f"{p['objeto']} · {p['inventario']} ({p['regional']}) · #{p['id']}"
                if p["eliminado"] or p["inventario_eliminado"]:
                    text += " [Eliminado]"
                self.filter_product_map[text] = p["id"]
            set_options(self.filter_product, self.filter_product_map)

        def filter_values(self):
            return dict(region_id=self.region_map.get(self.filter_region.get()),
                        inventory_id=self.filter_inventory_map.get(self.filter_inventory.get()),
                        product_id=self.filter_product_map.get(self.filter_product.get()),
                        location=None if self.filter_location.get() == TODOS else self.filter_location.get(),
                        start=parse_date(self.filter_start.get(), optional=True),
                        end=parse_date(self.filter_end.get(), optional=True),
                        status=None if self.filter_status.get() == TODOS else self.filter_status.get())

        def search_history(self, reset=True):
            filters = self.filter_values()
            if reset or filters != getattr(self, "last_filters", None):
                self.history_page = 0
            rows, count, units = self.db.history(**filters, page=self.history_page)
            self.last_filters = filters
            self.history_count = count
            self.history_table.clear()
            self.cancel_button.configure(state="disabled")
            self.cancel_batch_button.configure(state="disabled")
            self.delete_cancelled_button.configure(state="disabled")
            self.attach_button.configure(state="disabled")
            self.history_rows = {str(r["id"]): r for r in rows}
            for index, r in enumerate(rows):
                self.history_table.tree.insert("", "end", iid=str(r["id"]), values=(r["id"],
                    display_date(r["fecha"]), r["estado"], self.exit_receipt_number(r["id"]),
                    r["regional"], r["inventario"], r["objeto"], r["cantidad"],
                    r["destino"], r["responsable"], r["ubicacion"],
                    f"{r['documentos']} documento(s)" if r["documentos"] else NO_SOPORTE),
                    tags=("anulada",) if r["estado"] == "Anulada" else ("odd",) if index % 2 else ())
            filtered = any(value is not None for value in filters.values())
            description = f"{count:,} movimientos · {units:,} unidades en salidas vigentes" if count else "No hay movimientos que coincidan."
            self.history_info.configure(text=description + (" · Filtros activos" if filtered else ""))
            self.page_info.configure(text=f"Página {self.history_page + 1} de {max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)}")
            self.previous_button.configure(state="normal" if self.history_page else "disabled")
            self.next_button.configure(state="normal" if (self.history_page + 1) * PAGE_SIZE < count else "disabled")

        def change_page(self, delta):
            self.history_page = max(0, self.history_page + delta)
            self.search_history(reset=False)

        def clear_filters(self):
            self.filter_region.set(TODOS)
            self.filter_inventory.set(TODOS)
            self.filter_product.set(TODOS)
            self.filter_location.set(TODOS)
            self.filter_status.set(TODOS)
            self.filter_start.set("")
            self.filter_end.set("")
            self.update_filter_inventories()
            self.search_history()

        def update_cancel_button(self):
            selected = self.history_table.tree.selection()
            row = self.history_rows.get(selected[0]) if len(selected) == 1 else None
            busy = (getattr(self, "cancellation_running", False) or getattr(self, "deletion_running", False)
                    or getattr(self, "attachment_running", False))
            self.attach_button.configure(state="normal" if row and not busy else "disabled")
            self.cancel_button.configure(state="normal" if row and row["estado"] == "Vigente" and not busy else "disabled")
            # Una fila ya anulada también permite localizar el resto de su entrega.
            self.cancel_batch_button.configure(state="normal" if row and not busy else "disabled")
            cancelled = bool(selected) and all(i in self.history_rows and self.history_rows[i]["estado"] == "Anulada"
                                               for i in selected)
            self.delete_cancelled_button.configure(state="normal" if cancelled and not busy else "disabled")

        def cancel_history(self, scope="one"):
            existing = getattr(self, "cancel_dialog", None)
            if existing is not None and existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                return
            selected = self.history_table.tree.selection()
            if len(selected) != 1:
                messagebox.showinfo("Selecciona una salida", "Selecciona una sola fila para devolver ese producto o su entrega.", parent=self)
                return
            row = self.db.exit_record(int(selected[0]))
            if row is None:
                return
            if scope == "one":
                ids = [row["id"]] if row["estado"] == "Vigente" else []
            else:
                ids = [r["id"] for r in self.db.batch_exits(row["lote_id"])] if row["lote_id"] else (
                    [row["id"]] if row["estado"] == "Vigente" else [])
            if not ids:
                messagebox.showinfo("Sin productos por devolver", "Esta salida o entrega ya está anulada por completo.", parent=self)
                self.search_history()
                return
            chosen_rows = [self.db.exit_record(i) for i in ids]
            title = "Devolver producto seleccionado" if scope == "one" else "Devolver entrega completa"
            window = self.modal(title, 590)
            self.cancel_dialog = window
            window.geometry("710x590")
            window.resizable(True, True)
            window.minsize(600, 520)
            frame = ctk.CTkFrame(window, fg_color=WHITE)
            frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
            window.grid_rowconfigure(0, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(1, weight=1)
            total = sum(r["cantidad"] for r in chosen_rows)
            label(frame, f"{title}\n{len(ids)} productos · {total} unidades a devolver",
                  font=ctk.CTkFont(size=17, weight="bold"), wraplength=640,
                  justify="left").grid(row=0, column=0, sticky="w", padx=12, pady=12)
            preview = Table(frame, [("producto", "Producto", 210), ("inventario", "Inventario / Regional", 270),
                                    ("cantidad", "Cantidad", 95)])
            preview.configure(height=150)
            preview.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
            for record in chosen_rows:
                preview.tree.insert("", "end", values=(record["objeto"],
                    f"{record['inventario']} ({record['regional']})", record["cantidad"]))
            label(frame, "Motivo de la devolución (obligatorio)").grid(row=2, column=0, sticky="w", padx=12)
            reason = ctk.CTkTextbox(frame, height=72, font=ctk.CTkFont(size=15))
            reason.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 8))
            explanation = "Se anularán las salidas indicadas y se devolverán sus unidades al inventario."
            if any(r["producto_eliminado"] or r["inventario_eliminado"] for r in chosen_rows):
                explanation += " Los registros eliminados se recuperarán con sus IDs originales."
            status_label = label(frame, explanation, wraplength=640, justify="left", text_color=MUTED)
            status_label.grid(row=4, column=0, sticky="ew", padx=12, pady=8)
            controls = ctk.CTkFrame(frame, fg_color="transparent")
            controls.grid(row=5, column=0, sticky="ew", padx=12, pady=12)
            mailbox = queue.Queue()
            working = False

            def close_dialog():
                if not working:
                    window.destroy()
                    self.cancel_dialog = None

            def worker(reason_text):
                connection = None
                try:
                    connection = Database(self.db.path)
                    returned = connection.cancel_exits(ids, reason_text)
                    mailbox.put((True, returned))
                except Exception as exc:
                    logging.exception("No se pudo completar la devolución")
                    mailbox.put((False, str(exc)))
                finally:
                    if connection is not None:
                        connection.close()

            def poll_result():
                nonlocal working
                if not window.winfo_exists():
                    return
                try:
                    success, result = mailbox.get_nowait()
                except queue.Empty:
                    window.after(80, poll_result)
                    return
                working = False
                self.cancellation_running = False
                if not success:
                    confirm_button.configure(state="normal", text="Confirmar devolución")
                    back_button.configure(state="normal")
                    reason.configure(state="normal")
                    status_label.configure(text="No se guardó la devolución. Revisa el mensaje e inténtalo nuevamente.")
                    messagebox.showerror("No se pudo devolver", result, parent=window)
                    return
                close_dialog()
                self.refresh_options()
                self.refresh_inventory()
                self.refresh_dashboard()
                self.search_history()
                messagebox.showinfo("Devolución registrada", f"Se devolvieron {result} unidades.\n"
                    "Las existencias y las salidas totales están actualizadas.", parent=self)

            def confirm():
                nonlocal working
                if working:
                    return
                try:
                    reason_text = required_text(reason.get("1.0", "end").strip(), "motivo de la devolución", 500)
                except ValueError as exc:
                    messagebox.showerror("Motivo requerido", str(exc), parent=window)
                    return
                working = True
                self.cancellation_running = True
                confirm_button.configure(state="disabled", text="Guardando devolución…")
                back_button.configure(state="disabled")
                reason.configure(state="disabled")
                status_label.configure(text="Procesando la devolución. Espera a que termine antes de cerrar.")
                # SQLite usa su propia conexión en el trabajador; todos los widgets
                # se consultan y actualizan únicamente desde el hilo de Tk.
                threading.Thread(target=worker, args=(reason_text,), daemon=True).start()
                window.after(80, poll_result)

            confirm_button = button(controls, "Confirmar devolución", confirm, width=220)
            confirm_button.pack(side="left")
            back_button = button(controls, "Cancelar", close_dialog, secondary=True, width=110)
            back_button.pack(side="right")
            window.protocol("WM_DELETE_WINDOW", close_dialog)
            window.bind("<Escape>", lambda _: close_dialog())

        def delete_cancelled_history(self):
            previous = getattr(self, "delete_dialog", None)
            if previous is not None and previous.winfo_exists():
                previous.deiconify()
                previous.lift()
                return
            ids = [int(i) for i in self.history_table.tree.selection()]
            if not ids:
                return
            rows = [self.db.exit_record(i) for i in ids]
            if any(r is None or r["estado"] != "Anulada" for r in rows):
                messagebox.showerror("Solo salidas anuladas",
                    "Selecciona únicamente salidas con estado Anulada. No se borró ningún registro.", parent=self)
                self.search_history()
                return
            window = self.modal("Eliminar salidas anuladas definitivamente", 535)
            self.delete_dialog = window
            window.geometry("710x535")
            window.resizable(True, True)
            window.minsize(600, 470)
            window.grid_rowconfigure(0, weight=1)
            frame = ctk.CTkFrame(window, fg_color=WHITE)
            frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(1, weight=1)
            label(frame, f"Eliminar definitivamente {len(rows)} salidas anuladas",
                  font=ctk.CTkFont(size=17, weight="bold"), wraplength=630).grid(
                      row=0, column=0, sticky="w", padx=12, pady=12)
            preview = Table(frame, [("id", "N.º", 75), ("producto", "Producto", 205),
                                   ("inventario", "Inventario / Regional", 260), ("cantidad", "Cantidad", 90)])
            preview.grid(row=1, column=0, sticky="nsew", padx=12)
            for row in rows:
                preview.tree.insert("", "end", values=(row["id"], row["objeto"],
                    f"{row['inventario']} ({row['regional']})", row["cantidad"]))
            status = label(frame,
                "Se borrarán estas salidas y sus datos de anulación del historial. Esta acción no se puede deshacer desde el programa.\n\n"
                "Las existencias no cambiarán: las unidades ya fueron devueltas. Los archivos de soporte se conservarán.",
                wraplength=630, justify="left", text_color="#A0243E")
            status.grid(row=2, column=0, sticky="ew", padx=12, pady=14)
            controls = ctk.CTkFrame(frame, fg_color="transparent")
            controls.grid(row=3, column=0, sticky="ew", padx=12, pady=12)
            mailbox = queue.Queue()
            working = False

            def close_dialog():
                if not working:
                    window.destroy()
                    self.delete_dialog = None

            def worker():
                connection = None
                try:
                    connection = Database(self.db.path)
                    mailbox.put((True, connection.delete_cancelled_exits(ids)))
                except Exception as exc:
                    logging.exception("No se pudo borrar la salida anulada")
                    mailbox.put((False, str(exc)))
                finally:
                    if connection is not None:
                        connection.close()

            def poll():
                nonlocal working
                if not window.winfo_exists():
                    return
                try:
                    success, result = mailbox.get_nowait()
                except queue.Empty:
                    window.after(80, poll)
                    return
                working = False
                self.deletion_running = False
                if not success:
                    erase.configure(state="normal", text="Eliminar definitivamente")
                    back.configure(state="normal")
                    status.configure(text="No se borró ningún registro. Revisa el mensaje antes de intentarlo de nuevo.")
                    messagebox.showerror("No se pudo eliminar", result, parent=window)
                    return
                close_dialog()
                self.refresh_options()
                self.search_history()
                messagebox.showinfo("Salidas eliminadas", f"Se eliminaron definitivamente {result} salidas anuladas.\n"
                    "Las existencias permanecen iguales.", parent=self)

            def confirm():
                nonlocal working
                if working:
                    return
                working = True
                self.deletion_running = True
                erase.configure(state="disabled", text="Eliminando…")
                back.configure(state="disabled")
                status.configure(text="Eliminando los registros seleccionados. Espera a que termine antes de cerrar.")
                threading.Thread(target=worker, daemon=True).start()
                window.after(80, poll)

            erase = button(controls, "Eliminar definitivamente", confirm, width=230)
            erase.configure(fg_color="#AD2540", hover_color="#861B30")
            erase.pack(side="left")
            back = button(controls, "Cancelar", close_dialog, secondary=True, width=110)
            back.pack(side="right")
            window.protocol("WM_DELETE_WINDOW", close_dialog)
            window.bind("<Escape>", lambda _: close_dialog())

        def attach_history_document(self):
            existing = getattr(self, "attachment_dialog", None)
            if existing is not None and existing.winfo_exists():
                existing.lift()
                return
            selected = self.history_table.tree.selection()
            if len(selected) != 1:
                messagebox.showinfo("Selecciona una salida", "Selecciona una sola fila para adjuntarle la factura.", parent=self)
                return
            row = self.db.exit_record(int(selected[0]))
            if row is None:
                self.search_history(reset=False)
                return
            window = self.modal("Adjuntar factura o documento", 430)
            self.attachment_dialog = window
            window.geometry("650x430")
            window.minsize(600, 430)
            label(window, f"Salida #{row['id']} · {row['objeto']}\n"
                  f"{row['inventario']} ({row['regional']})\n"
                  f"Fecha: {display_date(row['fecha'])} · Cantidad: {row['cantidad']}\n"
                  f"Destino: {row['destino']}", wraplength=570, justify="left").grid(
                      row=0, column=0, sticky="ew", padx=20, pady=15)
            label(window, "Se añadirá solo a esta salida. Puedes conservar varios documentos.\n"
                  "PDF o imagen · Máximo 25 MB · Se guarda una copia dentro del sistema.",
                  wraplength=570, justify="left", text_color=MUTED).grid(row=1, column=0, padx=20, pady=8, sticky="ew")
            status = label(window, "Ningún archivo seleccionado", wraplength=570, justify="left")
            status.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
            chosen = None
            working = False
            mailbox = queue.Queue()

            def choose():
                nonlocal chosen
                filename = filedialog.askopenfilename(parent=window, title="Seleccionar factura o documento",
                                                      filetypes=SUPPORT_TYPES)
                if filename:
                    chosen = Path(filename)
                    status.configure(text=chosen.name)
                    save.configure(state="normal")

            def close_dialog():
                if not working:
                    window.destroy()
                    self.attachment_dialog = None

            def worker(source):
                connection = None
                try:
                    connection = Database(self.db.path)
                    connection.attach_document(row["id"], source, folder)
                    mailbox.put((True, None))
                except Exception as exc:
                    logging.exception("No se pudo adjuntar el documento")
                    mailbox.put((False, str(exc)))
                finally:
                    if connection is not None:
                        connection.close()

            def poll():
                nonlocal working
                try:
                    success, error = mailbox.get_nowait()
                except queue.Empty:
                    window.after(80, poll)
                    return
                working = False
                self.attachment_running = False
                self.update_cancel_button()
                if not success:
                    save.configure(state="normal", text="Guardar documento")
                    choose_button.configure(state="normal")
                    back.configure(state="normal")
                    status.configure(text=chosen.name)
                    messagebox.showerror("No se pudo adjuntar", error, parent=window)
                    return
                close_dialog()
                self.search_history(reset=False)
                if str(row["id"]) in self.history_rows:
                    self.history_table.tree.selection_set(str(row["id"]))
                    self.history_table.tree.see(str(row["id"]))
                messagebox.showinfo("Documento guardado", "La copia quedó guardada en el sistema.\n"
                    "Puedes consultarla en «Ver detalle», aunque muevas o borres el archivo original.", parent=self)

            def confirm():
                nonlocal working
                if working or chosen is None:
                    return
                working = True
                self.attachment_running = True
                self.update_cancel_button()
                save.configure(state="disabled", text="Guardando…")
                choose_button.configure(state="disabled")
                back.configure(state="disabled")
                status.configure(text="Copiando el documento. Espera a que termine antes de cerrar.")
                threading.Thread(target=worker, args=(chosen,), daemon=True).start()
                window.after(80, poll)

            choose_button = button(window, "Elegir archivo…", choose, secondary=True)
            choose_button.grid(row=3, column=0, pady=8)
            controls = ctk.CTkFrame(window, fg_color="transparent")
            controls.grid(row=4, column=0, sticky="ew", padx=20, pady=15)
            save = button(controls, "Guardar documento", confirm, state="disabled", width=210)
            save.pack(side="left")
            back = button(controls, "Cancelar", close_dialog, secondary=True)
            back.pack(side="right")
            window.protocol("WM_DELETE_WINDOW", close_dialog)
            window.bind("<Escape>", lambda _: close_dialog())

        def open_document(self, path, parent):
            try:
                path = path.resolve()
                if not path.is_file():
                    raise ValueError("No se encuentra el documento en la carpeta de datos.")
                if sys.platform == "win32":
                    os.startfile(str(path))
                else:
                    import subprocess
                    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
            except Exception as exc:
                messagebox.showerror("No se pudo abrir", f"{exc}\nPuedes guardar una copia y abrirla con un visor PDF o de imágenes.", parent=parent)

        def export_document(self, path, name, parent):
            destination = filedialog.asksaveasfilename(parent=parent, title="Guardar copia del documento",
                initialfile=name, defaultextension=path.suffix)
            if destination:
                try:
                    if path.resolve() != Path(destination).resolve():
                        shutil.copy2(path, destination)
                except Exception as exc:
                    messagebox.showerror("No se pudo guardar la copia", str(exc), parent=parent)

        def history_detail(self):
            selected = self.history_table.tree.selection()
            if len(selected) != 1:
                messagebox.showinfo("Selecciona un movimiento", "Selecciona una fila del historial para ver sus detalles.", parent=self)
                return
            row = self.db.exit_record(int(selected[0]))
            if row is None:
                return
            window = ctk.CTkToplevel(self)
            window.title(f"Movimiento #{row['id']}")
            window.geometry("730x710")
            window.minsize(560, 500)
            window.transient(self)
            frame = ctk.CTkScrollableFrame(window, fg_color=WHITE)
            frame.pack(fill="both", expand=True, padx=15, pady=15)
            detail = (f"MOVIMIENTO #{row['id']} · {row['estado']}\n"
                f"{receipt_title(self.db.receipt_for_exit(row['id']))}\n\nFecha: {display_date(row['fecha'])}\n"
                f"Regional: {row['regional']}\nInventario: {row['inventario']}\nProducto: {row['objeto']}\n"
                f"Cantidad: {row['cantidad']}\nDestino: {row['destino']}\nResponsable: {row['responsable']}\n"
                f"Ubicación: {row['ubicacion']}\nRegistro técnico (UTC): {row['registrado_en']}")
            if row["estado"] == "Anulada":
                detail += (f"\n\nUnidades devueltas: {row['cantidad']}\nMotivo: {row['motivo_anulacion']}\n"
                           f"Anulada el (UTC): {row['anulado_en']}")
            label(frame, detail, justify="left", wraplength=620).pack(anchor="w", padx=12, pady=12)
            receipt = self.db.receipt_for_exit(row["id"])
            if receipt:
                button(frame,"Imprimir factura de salida (entrega completa)",
                       lambda: self.print_receipt(receipt["id"])).pack(padx=12,pady=8)
            documents = self.db.attachments(row["id"])
            label(frame, f"Documentos adjuntos: {len(documents)}", font=ctk.CTkFont(size=17, weight="bold")).pack(
                anchor="w", padx=12, pady=(15, 8))
            for document in documents:
                path = Path(document["ruta"])
                if not path.is_absolute():
                    path = folder / path
                card = ctk.CTkFrame(frame, fg_color=BG)
                card.pack(fill="x", padx=12, pady=8)
                label(card, f"{document['nombre']}\nAñadido (UTC): {document['registrado_en']}",
                      wraplength=580, justify="left").pack(anchor="w", padx=12, pady=8)
                controls = ctk.CTkFrame(card, fg_color="transparent")
                controls.pack(fill="x", padx=12, pady=(0, 12))
                button(controls, "Abrir documento", lambda p=path: self.open_document(p, window)).pack(side="left")
                button(controls, "Guardar copia", lambda p=path, n=document["nombre"]: self.export_document(p, n, window),
                       secondary=True).pack(side="right")
            # Mantener la vista previa del soporte original cuando sea una imagen.
            if row["soporte"] != NO_SOPORTE and Path(row["soporte"]).suffix.lower() != ".pdf":
                try:
                    path = Path(row["soporte"])
                    if not path.is_absolute():
                        path = folder / path
                    with Image.open(path) as image:
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        image.thumbnail((630, 420))
                        photo = ctk.CTkImage(light_image=image.copy(), size=image.size)
                    preview = ctk.CTkLabel(frame, text="", image=photo)
                    preview.image = photo
                    preview.pack(padx=12, pady=10)
                except Exception:
                    logging.exception("No se pudo abrir soporte")
                    label(frame, "No se pudo abrir la imagen de soporte. Revisa que exista en la carpeta de datos.",
                          text_color="#B42835", wraplength=620).pack(padx=12, pady=12)

        def close(self):
            if (getattr(self, "cancellation_running", False) or getattr(self, "deletion_running", False)
                    or getattr(self, "attachment_running", False) or getattr(self,"io_running",False)):
                return
            if self.pending_exits and not messagebox.askyesno("Entrega pendiente",
                    "Tienes productos en una entrega sin registrar. ¿Cerrar y descartar esta lista?",
                    parent=self, default="no"):
                return
            self.destroy()

    app = App()
    if smoke:
        app.after(800,app.destroy)
    app.mainloop()


def self_test():
    """Pruebas reproducibles del núcleo con bases de datos temporales."""
    import tempfile
    import unittest
    from concurrent.futures import ThreadPoolExecutor

    class IntegrityTests(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            self.path = Path(self.tmp.name) / "test.db"
            self.db = Database(self.path)
            regions = self.db.regions()
            self.bogota, self.cundinamarca = regions[0]["id"], regions[1]["id"]
            self.inv1 = self.db.create_inventory("Tecnología", self.bogota)
            self.inv2 = self.db.create_inventory("Tecnología", self.cundinamarca)
            self.p1 = self.db.create_product(self.inv1, "Monitor", 10)
            self.p2 = self.db.create_product(self.inv2, "Monitor", 10)

        def tearDown(self):
            self.db.close()
            self.tmp.cleanup()

        def exit(self, amount=1, **kwargs):
            values = dict(inventory_id=self.inv1, product_id=self.p1, amount=amount,
                          destination="Sistemas", responsible="Responsable prueba",
                          day="08/10/2026", location="REDENTOR")
            values.update(kwargs)
            return self.db.register_exit(**values)

        def test_regional_isolation_and_duplicates(self):
            self.exit(3)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 7)
            self.assertEqual(self.db.product(self.p2)["cantidad_actual"], 10)
            with self.assertRaises(ValueError):
                self.db.create_inventory("  TECNOLOGÍA ", self.bogota)
            with self.assertRaises(ValueError):
                self.exit(inventory_id=self.inv2)

        def test_atomic_insufficient_stock(self):
            self.exit(8)
            with self.assertRaises(ValueError):
                self.exit(3)
            self.assertEqual(self.db.history()[1], 1)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 2)
            self.assertEqual(self.db.product(self.p1)["salidas_totales"], 8)

        def test_states_including_boundary(self):
            for current, state in ((10, "Disponible"), (9, "Con salidas"),
                                   (3, "Con salidas"), (2, "Bajo"), (1, "Bajo"), (0, "Agotado")):
                self.assertEqual(product_state(10, current), state)
            self.exit(10)
            self.assertEqual(self.db.summary()["agotados"], 1)

        def test_invalid_input(self):
            for amount in (0, -1, "1.5", "1,5", "abc", "", MAX_CANTIDAD + 1):
                with self.assertRaises(ValueError):
                    self.exit(amount)
            for day in ("31/02/2026", "2026-10-08", "8/10/2026", ""):
                with self.assertRaises(ValueError):
                    self.exit(day=day)
            with self.assertRaises(ValueError):
                self.exit(responsible="  ")
            with self.assertRaises(ValueError):
                self.exit(location="DESCONOCIDA")
            self.assertEqual(self.db.history()[1], 0)

        def test_filters_and_support(self):
            self.exit(2, day="01/10/2026", support="soportes/prueba.png")
            self.exit(3, day="09/10/2026", location="CIPLA")
            self.exit(1, inventory_id=self.inv2, product_id=self.p2)
            rows, count, units = self.db.history(region_id=self.bogota, inventory_id=self.inv1,
                product_id=self.p1, location="REDENTOR", start="2026-10-01", end="2026-10-01")
            self.assertEqual((count, units), (1, 2))
            self.assertEqual(rows[0]["soporte"], "soportes/prueba.png")
            self.assertEqual(self.db.history(region_id=self.cundinamarca)[1], 1)
            self.assertEqual(self.db.history(location="ESMERALDA")[1], 0)
            self.assertEqual(self.db.history()[1:], (3, 6))
            with self.assertRaises(ValueError):
                self.db.history(start="2026-10-09", end="2026-10-01")

        def test_sql_guards_and_immutable_history(self):
            self.exit()
            for sql in ("UPDATE salidas SET cantidad=2", "DELETE FROM salidas",
                        "UPDATE productos SET cantidad_actual=-1",
                        "UPDATE productos SET salidas_totales=100"):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.db.conn:
                        self.db.conn.execute(sql)
            with self.assertRaises(sqlite3.IntegrityError):
                with self.db.conn:
                    self.db.conn.execute("""INSERT INTO salidas
                        (producto_id,cantidad,destino,responsable,fecha,ubicacion)
                        VALUES (?,100,'D','R','2026-10-08','REDENTOR')""", (self.p1,))
            self.assertEqual(self.db.history()[1], 1)

        def test_persistence(self):
            self.exit(4)
            other = Database(self.path)
            try:
                self.assertEqual(other.product(self.p1)["cantidad_actual"], 6)
                self.assertEqual(other.history()[1], 1)
                self.assertEqual(other.history()[0][0]["soporte"], NO_SOPORTE)
            finally:
                other.close()

        def test_concurrent_instances(self):
            def worker():
                other = Database(self.path)
                try:
                    try:
                        other.register_exit(self.inv1, self.p1, 7, "D", "R", "08/10/2026", "CIPLA")
                        return True
                    except ValueError:
                        return False
                finally:
                    other.close()
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: worker(), range(2)))
            self.assertEqual(sum(results), 1)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 3)
            self.assertEqual(self.db.history()[1], 1)

        def test_delete_product_and_recreate_corrected(self):
            self.db.delete_product(self.inv1, self.p1, expected_stock=10)
            self.assertEqual(self.db.products(self.inv1), [])
            self.assertEqual(self.db.products(self.inv1, include_deleted=True), [])
            new_id = self.db.create_product(self.inv1, "Monitor", 25)
            self.assertNotEqual(new_id, self.p1)
            self.assertEqual(self.db.product(new_id)["cantidad_actual"], 25)
            self.assertEqual(self.db.product(self.p2)["cantidad_actual"], 10)

        def test_delete_product_preserves_history_and_support(self):
            self.exit(4, support="soportes/factura.png")
            before = dict(self.db.history(product_id=self.p1)[0][0])
            self.db.delete_product(self.inv1, self.p1)
            self.assertEqual(dict(self.db.history(product_id=self.p1)[0][0]), before)
            self.assertEqual(self.db.products(self.inv1), [])
            self.assertEqual(len(self.db.products(self.inv1, include_deleted=True)), 1)
            self.assertEqual(self.db.summary(self.inv1)["unidades"], 0)
            with self.assertRaises(ValueError):
                self.exit()
            # Protección equivalente incluso si alguien omite la API de Python.
            with self.assertRaises(sqlite3.IntegrityError):
                with self.db.conn:
                    self.db.conn.execute("""INSERT INTO salidas
                        (producto_id,cantidad,destino,responsable,fecha,ubicacion)
                        VALUES (?,1,'D','R','2026-10-08','REDENTOR')""", (self.p1,))

        def test_delete_finished_inventory_and_recreate(self):
            self.exit(10)
            self.db.delete_inventory(self.inv1, expected_products=[(self.p1, 0)])
            self.assertEqual(len(self.db.inventories()), 1)
            self.assertEqual(len(self.db.inventories(include_deleted=True)), 2)
            self.assertEqual(self.db.summary()["agotados"], 0)
            self.assertEqual(self.db.summary(self.inv1)["inventarios"], 0)
            rows, count, units = self.db.history(inventory_id=self.inv1)
            self.assertEqual((count, units), (1, 10))
            self.assertEqual(rows[0]["inventario"], "Tecnología")
            new_id = self.db.create_inventory("Tecnología", self.bogota)
            self.assertNotEqual(new_id, self.inv1)
            with self.assertRaises(ValueError):
                self.db.create_product(self.inv1, "Teclado", 1)
            self.assertEqual(self.db.product(self.p2)["cantidad_actual"], 10)

        def test_delete_inventory_with_remaining_products(self):
            self.exit(2)
            extra = self.db.create_product(self.inv1, "Teclado", 3)
            self.db.delete_inventory(self.inv1)
            self.assertEqual(self.db.products(self.inv1), [])
            self.assertEqual(self.db.product(extra)["eliminado"], 1)
            self.assertEqual(self.db.summary()["unidades"], 10)
            self.assertEqual(self.db.history(inventory_id=self.inv1)[1:], (1, 2))

        def test_deletion_rejects_changed_confirmation(self):
            self.exit(1)
            with self.assertRaises(ValueError):
                self.db.delete_product(self.inv1, self.p1, expected_stock=10)
            with self.assertRaises(ValueError):
                self.db.delete_inventory(self.inv1, expected_products=[(self.p1, 10)])
            with self.assertRaises(ValueError):
                self.db.delete_product(self.inv2, self.p1)
            self.assertEqual(self.db.product(self.p1)["eliminado"], 0)
            self.assertEqual(len(self.db.inventories()), 2)

        def test_dashboard_inventory_filter(self):
            self.exit(8)
            self.assertEqual(self.db.summary(self.inv1),
                {"inventarios": 1, "productos": 1, "unidades": 2, "agotados": 0, "bajos": 1})
            self.assertEqual(self.db.summary(self.inv2)["unidades"], 10)
            self.assertEqual(self.db.summary()["unidades"], 12)
            self.db.delete_product(self.inv1, self.p1)
            self.assertEqual(self.db.summary(self.inv1)["bajos"], 0)
            self.assertEqual(self.db.summary()["productos"], 1)

        def batch(self, lines):
            return self.db.register_exits(lines, "Destino común", "Responsable", "09/10/2026", "REDENTOR", "soportes/lote.png")

        def test_batch_multiple_inventories(self):
            code, ids = self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                                    {"inventory_id": self.inv2, "product_id": self.p2, "amount": 4}])
            self.assertEqual(len(ids), 2)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 7)
            self.assertEqual(self.db.product(self.p2)["cantidad_actual"], 6)
            for movement_id in ids:
                row = self.db.exit_record(movement_id)
                self.assertEqual(row["lote_id"], code)
                self.assertEqual(row["soporte"], "soportes/lote.png")
                self.assertEqual(row["estado"], "Vigente")
            self.assertEqual(self.db.history()[1:], (2, 7))

        def test_batch_invalid_line_rolls_back_all(self):
            for lines in ([], [
                {"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                {"inventory_id": self.inv2, "product_id": self.p2, "amount": 11}], [
                {"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                {"inventory_id": self.inv1, "product_id": self.p2, "amount": 2}]):
                with self.assertRaises(ValueError):
                    self.batch(lines)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertEqual(self.db.history()[1], 0)

        def test_batch_aggregates_duplicate_product(self):
            line = {"inventory_id": self.inv1, "product_id": self.p1, "amount": 6}
            with self.assertRaises(ValueError):
                self.batch([line, line])
            line["amount"] = 3
            _, ids = self.batch([line, line])
            self.assertEqual(len(ids), 1)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 4)

        def test_batch_database_failure_is_atomic(self):
            self.db.conn.execute(f"""CREATE TRIGGER fail_test BEFORE INSERT ON salidas
                WHEN NEW.producto_id={self.p2} BEGIN SELECT RAISE(ABORT,'Prueba de fallo'); END""")
            with self.assertRaises(sqlite3.IntegrityError):
                self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                            {"inventory_id": self.inv2, "product_id": self.p2, "amount": 4}])
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertEqual(self.db.history()[1], 0)

        def test_cancel_restores_exactly_once(self):
            movement_id = self.exit(8, support="soportes/prueba.png")
            self.assertEqual(self.db.cancel_exits([movement_id], "Devolución completa"), 8)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertEqual(self.db.product(self.p1)["salidas_totales"], 0)
            row = self.db.exit_record(movement_id)
            self.assertEqual(row["estado"], "Anulada")
            self.assertEqual(row["soporte"], "soportes/prueba.png")
            self.assertEqual(row["motivo_anulacion"], "Devolución completa")
            self.assertTrue(row["anulado_en"])
            self.assertEqual(self.db.history()[1:], (1, 0))
            self.assertEqual(self.db.history(status="Anulada")[1], 1)
            self.assertEqual(self.db.history(status="Vigente")[1], 0)
            with self.assertRaises(ValueError):
                self.db.cancel_exits([movement_id], "Otra devolución")
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            # Se pueden volver a entregar las unidades devueltas.
            self.exit(10)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 0)

        def test_cancel_entire_batch_and_single_line(self):
            code, ids = self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                                    {"inventory_id": self.inv2, "product_id": self.p2, "amount": 4}])
            self.db.cancel_exits([ids[0]], "Retorno de un producto")
            self.assertEqual([r["id"] for r in self.db.batch_exits(code)], [ids[1]])
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertEqual(self.db.product(self.p2)["cantidad_actual"], 6)
            self.db.cancel_exits([ids[1]], "Retorno del resto")
            self.assertEqual(self.db.product(self.p2)["cantidad_actual"], 10)
            _, ids = self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 2},
                                {"inventory_id": self.inv2, "product_id": self.p2, "amount": 5}])
            self.assertEqual(self.db.cancel_exits(ids, "Retorno total"), 7)
            self.assertEqual(self.db.summary()["unidades"], 20)

        def test_cancel_validation_is_atomic(self):
            movement_id = self.exit(4)
            with self.assertRaises(ValueError):
                self.db.cancel_exits([movement_id], " ")
            with self.assertRaises(ValueError):
                self.db.cancel_exits([movement_id, 999999], "Retorno")
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 6)
            self.assertEqual(self.db.exit_record(movement_id)["estado"], "Vigente")

        def test_cancel_recovers_deleted_original_with_name_collision(self):
            movement_id = self.exit(6)
            self.db.delete_product(self.inv1, self.p1)
            replacement = self.db.create_product(self.inv1, "Monitor", 20)
            self.db.cancel_exits([movement_id], "Retorno después de eliminación")
            rows = self.db.products(self.inv1)
            self.assertEqual({r["id"] for r in rows}, {self.p1, replacement})
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertEqual(self.db.product(replacement)["cantidad_actual"], 20)
            movement_id = self.exit(5)
            self.db.delete_inventory(self.inv1)
            new_inv = self.db.create_inventory("Tecnología", self.bogota)
            self.db.cancel_exits([movement_id], "Retorno a inventario eliminado")
            self.assertIn(self.inv1, [r["id"] for r in self.db.inventories()])
            self.assertIn(new_inv, [r["id"] for r in self.db.inventories()])
            self.assertEqual(self.db.exit_record(movement_id)["inventario"], "Tecnología")

        def test_concurrent_cancellations_do_not_duplicate_returns(self):
            movement_id = self.exit(7)
            def worker(_):
                other = Database(self.path)
                try:
                    try:
                        other.cancel_exits([movement_id], "Devolución")
                        return True
                    except ValueError:
                        return False
                finally:
                    other.close()
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(sum(executor.map(worker, range(2))), 1)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertEqual(self.db.product(self.p1)["salidas_totales"], 0)

        def test_names_start_uppercase_and_keep_acronyms(self):
            inv = self.db.create_inventory("  papelería USB  ", self.bogota)
            product = self.db.create_product(inv, "  lápiz HB  ", 2)
            self.assertEqual(next(r["nombre"] for r in self.db.inventories() if r["id"] == inv), "Papelería USB")
            self.assertEqual(self.db.product(product)["objeto"], "Lápiz HB")
            self.assertEqual(initial_upper("monitor LED"), "Monitor LED")
            self.assertEqual(initial_upper("USB"), "USB")

        def test_delete_cancelled_preserves_stock_and_other_exits(self):
            _, ids = self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                                {"inventory_id": self.inv2, "product_id": self.p2, "amount": 4}])
            self.db.cancel_exits([ids[0]], "Devuelto")
            before = [dict(self.db.product(i)) for i in (self.p1, self.p2)]
            self.assertEqual(self.db.delete_cancelled_exits([ids[0]]), 1)
            self.assertIsNone(self.db.exit_record(ids[0]))
            self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM anulaciones").fetchone()[0], 0)
            self.assertEqual([dict(self.db.product(i)) for i in (self.p1, self.p2)], before)
            self.assertEqual(self.db.exit_record(ids[1])["soporte"], "soportes/lote.png")
            self.assertEqual(self.db.history()[1:], (1, 4))
            self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

        def test_delete_cancelled_rejects_mixed_or_missing_atomically(self):
            cancelled = self.exit(2)
            active = self.exit(3)
            self.db.cancel_exits([cancelled], "Devuelto")
            for ids in ([cancelled, active], [cancelled, 999999], []):
                with self.assertRaises(ValueError):
                    self.db.delete_cancelled_exits(ids)
            self.assertIsNotNone(self.db.exit_record(cancelled))
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 7)

        def test_delete_cancelled_whole_group(self):
            _, ids = self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 3},
                                {"inventory_id": self.inv2, "product_id": self.p2, "amount": 4}])
            self.db.cancel_exits(ids, "Retorno total")
            self.assertEqual(self.db.delete_cancelled_exits(ids + ids), 2)
            self.assertEqual(self.db.summary()["unidades"], 20)
            self.assertEqual(self.db.history()[1:], (0, 0))
            self.assertEqual(self.db.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")

        def test_deleted_numbers_are_not_reused(self):
            old_id = self.exit(2)
            self.db.cancel_exits([old_id], "Devuelto")
            self.db.delete_cancelled_exits([old_id])
            self.db.close()
            self.db = Database(self.path)
            new_id = self.exit(1)
            self.assertGreater(new_id, old_id)
            with self.assertRaises(ValueError):
                self.db.delete_cancelled_exits([old_id])
            self.assertEqual(self.db.exit_record(new_id)["estado"], "Vigente")

        def test_cancellation_cannot_be_deleted_independently(self):
            movement_id = self.exit(3)
            self.db.cancel_exits([movement_id], "Devuelto")
            with self.assertRaises(sqlite3.IntegrityError):
                with self.db.conn:
                    self.db.conn.execute("DELETE FROM anulaciones WHERE salida_id=?", (movement_id,))
            self.assertEqual(self.db.exit_record(movement_id)["estado"], "Anulada")

        def pdf_fixture(self):
            source = Path(self.tmp.name) / "Factura de prueba.pdf"
            source.write_bytes(b"%PDF-1.4\n% Archivo de prueba de almacenamiento\n%%EOF\n")
            return source

        def test_attachment_persists_without_original_and_keeps_stock(self):
            movement = self.exit(3)
            original = dict(self.db.exit_record(movement))
            source = self.pdf_fixture()
            content = source.read_bytes()
            self.db.attach_document(movement, source, Path(self.tmp.name))
            source.unlink()
            self.db.close()
            self.db = Database(self.path)
            doc = self.db.attachments(movement)[0]
            self.assertEqual(doc["nombre"], "Factura de prueba.pdf")
            self.assertFalse(Path(doc["ruta"]).is_absolute())
            self.assertEqual((Path(self.tmp.name) / doc["ruta"]).read_bytes(), content)
            self.assertEqual(dict(self.db.exit_record(movement)), original)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 7)
            self.assertEqual(self.db.history()[0][0]["documentos"], 1)

        def test_attachments_are_per_product_and_preserve_existing_documents(self):
            _, ids = self.batch([{"inventory_id": self.inv1, "product_id": self.p1, "amount": 2},
                                 {"inventory_id": self.inv2, "product_id": self.p2, "amount": 3}])
            source = self.pdf_fixture()
            for _ in range(2):
                self.db.attach_document(ids[0], source, Path(self.tmp.name))
            first, second = self.db.attachments(ids[0]), self.db.attachments(ids[1])
            self.assertEqual(len(first), 3)
            self.assertEqual(len(second), 1)
            self.assertEqual(first[0]["ruta"], "soportes/lote.png")
            self.assertNotEqual(first[1]["ruta"], first[2]["ruta"])

        def test_attachment_failure_cleans_copy_and_preserves_database(self):
            movement = self.exit()
            self.db.conn.execute("""CREATE TRIGGER test_fail_attachment BEFORE INSERT ON adjuntos_salidas
                BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.attach_document(movement, self.pdf_fixture(), Path(self.tmp.name))
            self.assertEqual(list((Path(self.tmp.name) / "soportes").iterdir()), [])
            self.assertEqual(self.db.attachments(movement), [])

        def test_attachment_validation_and_missing_movement(self):
            movement = self.exit()
            source = self.pdf_fixture()
            source.write_bytes(b"archivo que no es PDF")
            with self.assertRaises(ValueError):
                self.db.attach_document(movement, source, Path(self.tmp.name))
            with self.assertRaises(ValueError):
                self.db.attach_document(99999, self.pdf_fixture(), Path(self.tmp.name))
            self.assertFalse((Path(self.tmp.name) / "soportes").exists())

        def test_attachments_survive_cancellation_and_allow_final_deletion(self):
            movement = self.exit(4)
            source = self.pdf_fixture()
            self.db.attach_document(movement, source, Path(self.tmp.name))
            self.db.cancel_exits([movement], "Devolución de prueba")
            self.db.attach_document(movement, source, Path(self.tmp.name))
            documents = self.db.attachments(movement)
            self.assertEqual(len(documents), 2)
            self.db.delete_cancelled_exits([movement])
            self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM adjuntos_salidas").fetchone()[0], 0)
            self.assertEqual(self.db.product(self.p1)["cantidad_actual"], 10)
            self.assertTrue(all((Path(self.tmp.name) / d["ruta"]).exists() for d in documents))
            self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

        def test_income_receipt_and_replenishment(self):
            original=self.db.receipts('INGRESO')[0]
            before=self.db.receipt(original['id'])[1][0]['cantidad']
            fid=self.db.register_income(self.inv2,[{'product_id':self.p2,'amount':7},{'name':'resma','amount':5}],
                '25/10/2026','Proveedor','Responsable')
            self.assertEqual(self.db.product(self.p2)['cantidad_actual'],17)
            self.assertEqual(self.db.product(self.p2)['cantidad_inicial'],17)
            self.assertEqual(self.db.receipt(original['id'])[1][0]['cantidad'],before)
            head,lines=self.db.receipt(fid)
            self.assertEqual(head['tipo'],'INGRESO')
            self.assertEqual(sum(l['cantidad'] for l in lines),12)
            self.assertEqual(len(lines),2)

        def test_income_failure_rolls_back_stock_and_receipt(self):
            total=len(self.db.receipts())
            with self.assertRaises(ValueError):
                self.db.register_income(self.inv1,[{'product_id':self.p1,'amount':4},{'product_id':self.p2,'amount':5}],
                    '25/10/2026','Proveedor','Responsable')
            self.assertEqual(self.db.product(self.p1)['cantidad_actual'],10)
            self.assertEqual(len(self.db.receipts()),total)

        def test_outgoing_receipt_number_preserved_after_purge(self):
            batch,ids=self.batch([{'inventory_id':self.inv1,'product_id':self.p1,'amount':2},
                                  {'inventory_id':self.inv2,'product_id':self.p2,'amount':3}])
            head=self.db.receipt_for_exit(ids[0])
            self.assertEqual(head['numero'],1)
            self.assertEqual(self.db.receipt_for_exit(ids[1])['id'],head['id'])
            self.db.cancel_exits(ids,'Devolución')
            self.db.delete_cancelled_exits(ids)
            self.assertEqual(self.db.receipt(head['id'])[1],[])
            new_id=self.exit()
            self.assertEqual(self.db.receipt_for_exit(new_id)['numero'],2)
            self.assertEqual(receipt_title(head),'Factura de salida #00000001')

        def test_concurrent_income_numbers(self):
            def write(_):
                db=Database(self.path)
                try:
                    fid=db.register_income(self.inv1,[{'product_id':self.p1,'amount':1}],
                        '25/10/2026','Proveedor','Responsable')
                    return db.receipt(fid)[0]['numero']
                finally: db.close()
            with ThreadPoolExecutor(max_workers=2) as executor:
                numbers=list(executor.map(write,range(2)))
            self.assertEqual(len(set(numbers)),2)
            self.assertEqual(self.db.product(self.p1)['cantidad_actual'],12)

        def test_migration_preserves_stock_and_numbers_on_reopen(self):
            sid=self.exit(3)
            head=self.db.receipt_for_exit(sid)
            self.db.close()
            self.db=Database(self.path)
            self.assertEqual(self.db.receipt_for_exit(sid)['numero'],head['numero'])
            self.assertEqual(self.db.product(self.p1)['cantidad_actual'],7)
            self.assertEqual(len(self.db.receipts('SALIDA')),1)
            self.assertEqual(self.db.conn.execute('PRAGMA foreign_key_check').fetchall(),[])

        def test_resource_paths(self):
            old = getattr(sys, "_MEIPASS", None)
            try:
                sys._MEIPASS = self.tmp.name
                self.assertEqual(resource_path("logo.png"), Path(self.tmp.name) / "logo.png")
            finally:
                if old is None:
                    del sys._MEIPASS
                else:
                    sys._MEIPASS = old

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IntegrityTests))
    return 0 if result.wasSuccessful() else 1


def main():
    if "--export-icons" in sys.argv:
        index=sys.argv.index("--export-icons")
        export_icons(sys.argv[index+1] if len(sys.argv)>index+1 else "assets")
        return 0
    if "--smoke-test" in sys.argv:
        import tempfile
        import json
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            db=Database(folder / "test.sqlite3")
            try:
                inv=db.create_inventory("Prueba",db.regions()[0]["id"])
                pid=db.create_product(inv,"Caja",5)
                sid=db.register_exit(inv,pid,1,"Destino","Prueba",date.today().strftime("%d/%m/%Y"),"REDENTOR")
                head,lines=db.receipt(db.receipt_for_exit(sid)["id"])
                data=receipt_pdf(head,lines,True,True)
                if not data.startswith(b"%PDF-"): raise RuntimeError("PDF no generado")
                export_icons(folder)
                launch_gui(db,folder,smoke=True)
            finally:
                db.close()
        if "--report" in sys.argv:
            Path(sys.argv[sys.argv.index("--report")+1]).write_text(json.dumps({"ok":True,"pdf":True,"sqlite":True,"gui":True}),encoding="utf-8")
        return 0
    if "--self-test" in sys.argv:
        return self_test()
    db = None
    try:
        folder = data_directory()
        logging.basicConfig(filename=str(folder / "ipsicol.log"), level=logging.ERROR,
                            format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
        db = Database(folder / "inventarios_ipsicol.sqlite3")
        launch_gui(db, folder)
        return 0
    except Exception as exc:
        logging.exception("No se pudo iniciar la aplicación")
        text = ("Faltan dependencias. Instala con:\npy -m pip install customtkinter Pillow"
                if isinstance(exc, ModuleNotFoundError) else f"No se pudo iniciar {APP_NAME}:\n{exc}")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, text, parent=root)
            root.destroy()
        except Exception:
            print(text, file=sys.stderr)
        return 1
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    # PyInstaller --windowed no proporciona consola.
    if sys.stdout is None: sys.stdout=io.StringIO()
    if sys.stderr is None: sys.stderr=io.StringIO()
    raise SystemExit(main())
