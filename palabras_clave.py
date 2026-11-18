
from __future__ import print_function

import io
import os
import re
import sys

from leer_logs import ruta_config_usuario, lineas_de, a_texto_nativo

CLAVES_FILTROS = ('conservar', 'excluir')


def leer_config(texto):
    """Lee el texto del .config que genera leer_logs.py y devuelve {seccion: {clave: valor}}.
    No se usa configparser: en [filtros] cada frase va en su propia linea, con o sin sangria,
    y una frase puede traer '=' o ':' (por ejemplo "SCRIPT_RUN_TYPE = prod") sin confundirse con una clave.
    Recibe el texto para poder probarlo sin archivos."""
    secciones, seccion, clave = {}, None, None
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith(('#', ';')):
            continue
        if limpia.startswith('[') and limpia.endswith(']'):
            seccion = limpia[1:-1].strip()
            if seccion.lower() == 'filtros':
                seccion = 'filtros'
            secciones.setdefault(seccion, {})
            clave = None
            continue
        if seccion is None:
            continue
        nombre, separador, valor = limpia.partition('=')
        if seccion == 'filtros':
            if separador and nombre.strip().lower() in CLAVES_FILTROS:
                clave = nombre.strip().lower()
                secciones[seccion][clave] = valor.strip()
            elif clave: # Cualquier otra linea es una frase mas de la ultima clave
                secciones[seccion][clave] += '\n' + limpia
        elif separador:
            secciones[seccion][nombre.strip()] = valor.strip()
    return secciones


def cargar_config(ruta):
    """Lee el archivo .config que ya genera leer_logs.py."""
    with io.open(ruta, 'r', encoding='utf-8') as archivo:
        return leer_config(archivo.read())


def preparar_patrones(texto):
    """Una frase por linea. El asterisco (*) acepta cualquier texto intermedio."""
    patrones = []
    for linea in texto.splitlines():
        frase = linea.strip()
        if not frase or frase.startswith(('#', ';')):
            continue
        partes = frase.split('*')
        expresion = b'.*'.join(re.escape(parte.encode('utf-8')) for parte in partes)
        patrones.append(re.compile(expresion, re.IGNORECASE))
    return patrones


def coincide(linea, patrones):
    return any(patron.search(linea) for patron in patrones)


def filtrar_archivo(entrada, salida, conservar, excluir):
    """Crea un log reducido sin modificar el archivo que recibe."""
    total, guardadas = 0, 0
    with open(entrada, 'rb') as origen:
        with open(salida, 'wb') as destino:
            for linea in lineas_de(origen):
                total += 1
                if coincide(linea, conservar) or not coincide(linea, excluir):
                    destino.write(linea)
                    guardadas += 1
    return total, guardadas


def dentro_de_carpeta(ruta, carpeta):
    """Evita filtrar accidentalmente un archivo fuera de la carpeta del usuario."""
    ruta = os.path.normcase(os.path.realpath(ruta))
    carpeta = os.path.normcase(os.path.realpath(carpeta))
    return ruta.startswith(carpeta.rstrip(os.sep) + os.sep)


def ejecutar():
    ruta_config = ruta_config_usuario()
    if not os.path.isfile(ruta_config):
        print('No se encontro el .config. Primero ejecuta leer_logs.py.')
        return 1

    try:
        config = cargar_config(ruta_config)
        if 'filtros' not in config:
            print('Falta la seccion [filtros] en el .config.')
            return 1

        conservar = preparar_patrones(config['filtros'].get('conservar', ''))
        excluir = preparar_patrones(config['filtros'].get('excluir', ''))
    except (IOError, OSError, ValueError, UnicodeError) as error:
        print('Configuracion invalida: %s' % error, file=sys.stderr)
        return 1

    carpeta = os.path.dirname(ruta_config)
    procesados, errores = set(), 0
    encontrados = 0
    for seccion in sorted(config):
        if 'log_exportado' not in config[seccion]:
            continue
        encontrados += 1
        entrada = a_texto_nativo(config[seccion]['log_exportado'])
        if not os.path.isabs(entrada):
            entrada = os.path.join(carpeta, entrada)
        entrada = os.path.realpath(entrada)

        if not dentro_de_carpeta(entrada, carpeta) or not os.path.isfile(entrada):
            print('Se omite %s: no existe o esta fuera de la carpeta del usuario.' % entrada, file=sys.stderr)
            errores += 1
            continue
        if entrada in procesados:
            continue
        procesados.add(entrada)

        salida = os.path.splitext(entrada)[0] + '_filtrado.log'
        try:
            total, guardadas = filtrar_archivo(entrada, salida, conservar, excluir)
        except (IOError, OSError) as error:
            print('Error al filtrar %s: %s' % (entrada, error), file=sys.stderr)
            errores += 1
            continue
        print('Archivo: %s' % entrada)
        print('Resultado: %s' % salida)
        print('Lineas: %d originales, %d conservadas, %d excluidas\n' % (
            total, guardadas, total - guardadas))

    if not encontrados:
        print('El .config no contiene logs exportados para procesar.')
        return 1
    return 1 if errores else 0


if __name__ == '__main__':
    sys.exit(ejecutar())
