
from __future__ import print_function

import io
import os
import re
import sys

try:
    from ConfigParser import RawConfigParser, Error as ConfigError
except ImportError:
    from configparser import RawConfigParser, Error as ConfigError

from leer_logs import ruta_config_usuario, lineas_de, a_texto_nativo


def cargar_config(ruta):
    """Lee el archivo .config que ya genera leer_logs.py."""
    config = RawConfigParser()
    with io.open(ruta, 'r', encoding='utf-8') as archivo:
        if sys.version_info[0] == 2:
            config.readfp(archivo)
        else:
            config.read_file(archivo)
    return config


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
        if not config.has_section('filtros'):
            print('Falta la seccion [filtros] en el .config.')
            return 1

        conservar = preparar_patrones(config.get('filtros', 'conservar'))
        excluir = preparar_patrones(config.get('filtros', 'excluir'))
    except (IOError, OSError, ValueError, KeyError, ConfigError, UnicodeError) as error:
        print('Configuracion invalida: %s' % error, file=sys.stderr)
        return 1

    carpeta = os.path.dirname(ruta_config)
    procesados, errores = set(), 0
    encontrados = 0
    for seccion in config.sections():
        if not config.has_option(seccion, 'log_exportado'):
            continue
        encontrados += 1
        entrada = a_texto_nativo(config.get(seccion, 'log_exportado').strip())
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
