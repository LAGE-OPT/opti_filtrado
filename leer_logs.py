# -*- coding: utf-8 -*-
# (Python 2.7 y 3, sin librerias externas para que corra en cualquier equipo del equipo de soporte)
from __future__ import print_function
import argparse
import getpass
import gzip
import io
import os
import re
import sys
import zipfile
import zlib
from collections import Counter, deque
from datetime import datetime, timedelta


'''
ESTO SOLO FUNCIONA SI LOS LOGS TIENEN UNA ORDEN CRONOLÓGICO (INICIO PRIMER FECHA, FINAL ÚLTIMA FECHA)
EL SCRIPT IGNORA ALGUNOS FORMATOS DE FECHA NO SON REGISTROS DE LOGS, SON PARTE DE STUDIO, COMO LEGS Y TRIPS.
'''

'''CONFIGURACIÓN GENERAL DEL SCRIPT'''
AJUSTE_HORAS_FORMATO_ISO = 0      # Solo si no se puede detectar en el log: horas a sumar al formato 2026-09-08 19:00:07 (UTC)
FECHAS_DEFAULT = 3                # Últimas fechas disponibles que se exportan si no se usa --fecha
ARCHIVO_CONFIG = 'fecha_seleccionada.config' # Uno por usuario; ademas del resultado guarda ruta_logs, que se conserva entre corridas
TAMANO_BLOQUE_COPIA = 1024 * 1024 # Se copia de 1 MB en 1 MB para no cargar el log completo en memoria
LIMITE_LINEA = 1024 * 1024        # Una linea mas larga se lee en pedazos de 1 MB (por ejemplo, un hueco de bytes nulos)
EXTENSIONES_LOG = ('.log', '.out', '.txt')
INICIO_CORRIDA = b'Running script with settings' # Primera linea de cada corrida (la escribe _run_crew_modules_*.sh)
MESES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DIAS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

# ESOS SON LOS PATRONES QUE IDENTIFIQUÉ SE ENCUENTRAR EN "prices_bids.log" y #nohup.out"
# También hay otros patrones pero son operacionales. Fechas de LEGS y TRIPS (las estoy ignorando)
# Utilizo re.compile para contruir los patrones
# El primer patron \d: significa que se trata de un digito y el número entre corchetes la cantidad de digitos
# El segundo patrón utiliza [A-Z][a-z]{2} que significa una letra mayuscula seguida de dos minuculas para los meses. Se repite para conciderar mes y día.add()
# El último patrón utila {4,6}, significa que el número puede tener 4 o 6 digitos
'''COPILAMOS LOS PATRONES'''
PATRONES = [
    re.compile(br'(?P<Y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2}) (?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})'),                     # 2026-09-08 19:00:07
    re.compile(br'[A-Z][a-z]{2} (?P<b>[A-Z][a-z]{2}) +(?P<d>\d{1,2}) (?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2}) (?P<Y>\d{4})'), # Tue Sep  8 13:00:07 2026
    re.compile(br'(?P<Y>\d{4})(?P<m>\d{2})(?P<d>\d{2}) (?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})'),                       # 20261019 14:02:15
    re.compile(br'(?P<Y>\d{4})(?P<m>\d{2})(?P<d>\d{2})_(?P<H>\d{2})(?P<M>\d{2})(?P<S>\d{2})?'),                        # 20261019_140011
]

'''PREFILTRO: TODA FECHA VÁLIDA CONTIENE UNA HORA (1:23:) O UN GUION BAJO ENTRE DÍGITOS (9_1). DESCARTA EL 99% DE LAS LÍNEAS ANTES DE APLICAR LOS PATRONES'''
PREFILTRO = re.compile(br'\d:\d\d:|\d_\d')

ERRORES_DE_LECTURA = (IOError, OSError, EOFError, zlib.error, zipfile.BadZipfile) # .gz o .zip danados


'''ABRE UN LOG NORMAL, UN .gz O UN .zip SIN DESCOMPRIMIR NADA EN DISCO
DEVUELVE UNA LISTA DE (NOMBRE, BASE PARA EL ARCHIVO EXPORTADO, FUNCION QUE ABRE EL LOG, SE PUEDE USAR seek)
CADA LOG SE ABRE JUSTO CUANDO SE VA A LEER: EN PYTHON 2.7 LOS ARCHIVOS ABIERTOS DE UN MISMO .zip
COMPARTEN LA POSICION DE LECTURA, Y SI SE ABREN VARIOS A LA VEZ SE MEZCLAN'''
def abrir_fuentes(ruta):
    nombre = os.path.basename(ruta)
    if nombre.lower().endswith('.gz'):
        base = os.path.splitext(nombre[:-3])[0]
        return [(ruta, base, lambda: gzip.open(ruta, 'rb'), False)]
    if nombre.lower().endswith('.zip'):
        comprimido = zipfile.ZipFile(ruta)
        base_zip = os.path.splitext(nombre)[0]
        return [('%s:%s' % (ruta, miembro), '%s_%s' % (base_zip, os.path.splitext(os.path.basename(miembro))[0]),
                 lambda miembro=miembro: comprimido.open(miembro), False)
                for miembro in comprimido.namelist() if miembro.lower().endswith(EXTENSIONES_LOG)]
    return [(ruta, os.path.splitext(nombre)[0], lambda: open(ruta, 'rb'), True)]


'''RUTA DEL .config DEL USUARIO: LA MISMA CARPETA QUE CREA leer_logs.py (<carpeta desde donde se ejecuta>/<usuario>)'''
def ruta_config_usuario():
    return os.path.join(os.getcwd(), getpass.getuser(), ARCHIVO_CONFIG)


CODIFICACION_RUTAS = 'mbcs' if os.name == 'nt' else 'utf-8' # No se usa el locale: con cron suele ser ASCII y fallaria con acentos


'''EN PYTHON 2.7 LA RUTA LEIDA DEL .config ES unicode; SE PASA AL FORMATO NATIVO (str) PARA QUE IMPRIMIRLA
O USARLA EN RUTAS NO FALLE CON ACENTOS CUANDO LA SALIDA NO ES UNA TERMINAL (cron, redireccion a archivo)'''
def a_texto_nativo(valor):
    if sys.version_info[0] == 2 and not isinstance(valor, str):
        return valor.encode(CODIFICACION_RUTAS)
    return valor


'''BUSCA ruta_logs EN EL TEXTO DEL .config DEL USUARIO (SECCION [general] O ANTES DE LA PRIMERA SECCION)
DEVUELVE LA CARPETA DE LOGS, O None SI ESTA VACIA O NO EXISTE. RECIBE EL TEXTO PARA PODER PROBARLO SIN ARCHIVOS'''
def leer_ruta_logs(texto):
    seccion = ''
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.startswith('['):
            seccion = linea.strip('[]').strip().lower()
        elif seccion in ('', 'general') and '=' in linea and not linea.startswith(('#', ';')):
            clave, valor = linea.split('=', 1)
            if clave.strip() == 'ruta_logs':
                valor = a_texto_nativo(valor.strip())
                return os.path.abspath(os.path.expanduser(os.path.expandvars(valor))) if valor else None
    return None


'''CARGA ruta_logs DEL .config DEL USUARIO SI EXISTE'''
def cargar_ruta_logs():
    if not os.path.isfile(ruta_config_usuario()):
        return None
    with io.open(ruta_config_usuario(), encoding='utf-8') as archivo: # Se escribe en UTF-8
        return leer_ruta_logs(archivo.read())


'''RESUELVE EL NOMBRE DE UN LOG: SI ES RELATIVO Y HAY ruta_logs, SE BUSCA PRIMERO AHI Y DESPUES DESDE DONDE SE EJECUTA
(ASI TAMBIEN SE ENCUENTRAN LOS LOGS EXPORTADOS, COMO <usuario>/process_bids_20261020.log)'''
def resolver_log(nombre, ruta_logs):
    if not ruta_logs or os.path.isabs(nombre):
        return nombre
    en_ruta_logs = os.path.join(ruta_logs, nombre)
    if not os.path.exists(en_ruta_logs) and os.path.exists(nombre):
        return nombre
    return en_ruta_logs


'''DEVUELVE ruta_logs TAL COMO ESTA ESCRITA EN EL .config (SIN EXPANDIR ~ NI VARIABLES), PARA CONSERVARLA AL REESCRIBIRLO'''
def leer_ruta_logs_texto():
    if not os.path.isfile(ruta_config_usuario()):
        return ''
    seccion = ''
    with io.open(ruta_config_usuario(), encoding='utf-8') as archivo: # Se escribe en UTF-8
        for linea in archivo:
            linea = linea.strip()
            if linea.startswith('['):
                seccion = linea.strip('[]').strip().lower()
            elif seccion in ('', 'general') and '=' in linea and not linea.startswith(('#', ';')):
                clave, valor = linea.split('=', 1)
                if clave.strip() == 'ruta_logs':
                    return a_texto_nativo(valor.strip())
    return ''


'''LEE LINEA POR LINEA CON UN LIMITE DE TAMANO (UNA LINEA GIGANTE SE ENTREGA EN PEDAZOS)'''
def lineas_de(archivo):
    return iter(lambda: archivo.readline(LIMITE_LINEA), b'')


'''DETECTA LA ZONA HORARIA DEL LOG: AL ARRANCAR CADA CORRIDA STUDIO ESCRIBE "Time: 20261019 14:00:17" (HORA LOCAL)
Y SEGUNDOS DESPUES "2026-10-19 20:00:20" (UTC). LA DIFERENCIA, REDONDEADA A MEDIA HORA, ES EL AJUSTE (AMX MEXICO = -6)
SE QUEDA CON EL VALOR MAS REPETIDO EN LAS PRIMERAS 5 CORRIDAS; SI NO ENCUENTRA PARES, USA AJUSTE_HORAS_FORMATO_ISO'''
def detectar_ajuste(abrir, pares_necesarios=5, distancia_maxima=40):
    ajustes, hora_local, linea_local = [], None, 0
    archivo = abrir()
    try:
        for num, linea in enumerate(lineas_de(archivo), 1):
            if linea.startswith(b'Time: '):
                encontrado = PATRONES[2].search(linea)
                if encontrado:
                    g = encontrado.groupdict()
                    hora_local = datetime(int(g['Y']), int(g['m']), int(g['d']), int(g['H']), int(g['M']), int(g['S']))
                    linea_local = num
                continue
            if hora_local is None or num - linea_local > distancia_maxima:
                continue
            encontrado = PATRONES[0].match(linea) # El formato UTC va al inicio de la linea
            if encontrado:
                g = encontrado.groupdict()
                hora_utc = datetime(int(g['Y']), int(g['m']), int(g['d']), int(g['H']), int(g['M']), int(g['S']))
                diferencia = (hora_utc - hora_local).total_seconds()
                if abs(diferencia) <= 14 * 3600:
                    ajustes.append(-round(diferencia / 1800.0) / 2.0) # Media hora mas cercana, con signo para pasar de UTC a local
                hora_local = None
                if len(ajustes) >= pares_necesarios:
                    break
    finally:
        archivo.close()
    if not ajustes:
        return AJUSTE_HORAS_FORMATO_ISO, False
    return Counter(ajustes).most_common(1)[0][0], True


'''ESTA FUNCIÓN BUSCA EN LAS LINEAS POR CADA PATRÓN DE FECHA (4 veces por línea)'''
def buscar_fecha(linea, ajuste):
    if not PREFILTRO.search(linea):
        return None
    for numero, patron in enumerate(PATRONES):
        encontrado = patron.search(linea)
        if not encontrado:
            continue
        g = encontrado.groupdict()
        try:
            mes = MESES.index(g['b'].decode('ascii')) + 1 if g.get('b') else int(g['m'])
            fecha = datetime(int(g['Y']), mes, int(g['d']), int(g['H']), int(g['M']), int(g['S'] or 0))
        except ValueError:
            continue
        return fecha + timedelta(hours=ajuste) if numero == 0 else fecha
    return None


'''CONVIERTE LA FECHA AL FORMATO Mon Oct 19 14:00:11 2026'''
def formatear(fecha):
    return '%s %s %2d %s' % (DIAS[fecha.weekday()], MESES[fecha.month - 1], fecha.day, fecha.strftime('%H:%M:%S %Y'))


'''DETECTA EL ENCABEZADO QUE process_bids ESCRIBE ANTES DE CADA CORRIDA: LINEA VACIA, SUBPLAN, LINEA VACIA
SI ESTA, LA CORRIDA EMPIEZA AHI (Y NO EN "Running script with settings"), PARA QUE EL SUBPLAN QUEDE EN SU CORRIDA'''
def inicio_con_encabezado(ultimas, posicion):
    if len(ultimas) == 3:
        (pos_1, linea_1), (_, linea_2), (_, linea_3) = ultimas
        subplan = linea_2.strip()
        if not linea_1.strip() and not linea_3.strip() and subplan and b' ' not in subplan:
            return pos_1, 3
    return posicion, 0


'''LEE EL LOG UNA SOLA VEZ: OBTIENE PRIMERA FECHA, ÚLTIMA FECHA, FECHAS DISPONIBLES Y SEGMENTOS A EXPORTAR
UN SEGMENTO ES (fecha, byte_inicio, byte_fin, linea_inicio, linea_fin)
SI EL LOG TIENE CORRIDAS, CADA CORRIDA COMPLETA ES UN SEGMENTO Y SU FECHA ES LA DE SU INICIO (LA PRIMERA FECHA QUE ESCRIBE):
ASI NINGUNA CORRIDA SE PARTE NI SE DUPLICA AUNQUE CRUCE LA MEDIANOCHE. LAS LINEAS ANTES DE LA PRIMERA CORRIDA VAN CON ELLA.
SI EL LOG NO TIENE CORRIDAS, SE CORTA POR DIA COMO ANTES: LAS LINEAS SIN FECHA VAN CON LA ULTIMA FECHA VISTA'''
def analizar_log(abrir, ajuste):
    primera_fecha = ultima_fecha = None
    corridas = []                 # [fecha, byte_inicio, linea_inicio] de cada corrida
    por_dia, dia_actual = [], None
    ultimas = deque(maxlen=3)     # (posicion, linea) de las 3 lineas anteriores, para el encabezado
    posicion = num = 0

    archivo = abrir()
    try:
        for linea in lineas_de(archivo):
            if linea.startswith(INICIO_CORRIDA):
                byte_inicio, atras = inicio_con_encabezado(ultimas, posicion)
                corridas.append([None, 0 if not corridas else byte_inicio, 0 if not corridas else num - atras])

            fecha = buscar_fecha(linea, ajuste)
            if fecha:
                if primera_fecha is None or fecha < primera_fecha: #Únicamente guardamos la primer fecha
                    primera_fecha = fecha
                if ultima_fecha is None or fecha > ultima_fecha: #Siempre guardamos la última fecha encontrada como últma fecha
                    ultima_fecha = fecha
                if corridas and corridas[-1][0] is None: # La primera fecha de la corrida es su fecha de inicio
                    corridas[-1][0] = fecha.date()
                if dia_actual is None or fecha.date() != dia_actual: # Corte por dia (solo se usa si no hay corridas)
                    por_dia.append([fecha.date(), 0 if not por_dia else posicion, 0 if not por_dia else num])
                    dia_actual = fecha.date()

            ultimas.append((posicion, linea))
            posicion += len(linea)
            num += 1
    finally:
        archivo.close()

    '''CERRAMOS CADA SEGMENTO DONDE EMPIEZA EL SIGUIENTE; UNA CORRIDA SIN NINGUNA FECHA TOMA LA DE LA ANTERIOR'''
    marcas = corridas if corridas else por_dia
    for i in range(len(corridas)):
        if corridas[i][0] is None:
            corridas[i][0] = corridas[i - 1][0] if i > 0 else next((c[0] for c in corridas if c[0]), None)
    segmentos = []
    for i, (fecha, byte_inicio, linea_inicio) in enumerate(marcas):
        byte_fin, linea_fin = (marcas[i + 1][1], marcas[i + 1][2]) if i + 1 < len(marcas) else (posicion, num)
        if fecha is not None:
            segmentos.append((fecha, byte_inicio, byte_fin, linea_inicio, linea_fin))
    fechas_disponibles = sorted(set(segmento[0] for segmento in segmentos))
    return primera_fecha, ultima_fecha, fechas_disponibles, segmentos, posicion, bool(corridas)


'''COPIA AL NUEVO LOG SOLO LOS SEGMENTOS DE LAS FECHAS SELECCIONADAS (SIN VOLVER A BUSCAR FECHAS)
EN UN LOG NORMAL SE SALTA DIRECTO A CADA SEGMENTO (seek); EN UN .gz O .zip SE AVANZA LEYENDO, PORQUE NO SE PUEDE SALTAR
DEVUELVE (LINEAS ESCRITAS, None) O (LINEAS ESCRITAS, MOTIVO) SI LA COPIA NO SE PUDO TERMINAR'''
def copiar_segmentos(abrir, se_puede_saltar, segmentos, ruta_salida):
    escritas, posicion = 0, 0
    entrada = abrir()
    try:
        with open(ruta_salida, 'wb') as salida:
            for fecha, inicio, fin, linea_inicio, linea_fin in segmentos:
                if se_puede_saltar:
                    entrada.seek(inicio)
                else:
                    while posicion < inicio: # Se lee y se descarta lo que no se exporta
                        datos = entrada.read(min(TAMANO_BLOQUE_COPIA, inicio - posicion))
                        if not datos:
                            return escritas, 'el log termino antes de lo esperado; el log exportado quedo incompleto'
                        posicion += len(datos)
                while inicio < fin:
                    datos = entrada.read(min(TAMANO_BLOQUE_COPIA, fin - inicio))
                    if not datos: # El archivo se recorto mientras se copiaba: sin esto el ciclo nunca termina
                        return escritas, 'el log se recorto mientras se copiaba; el log exportado quedo incompleto'
                    salida.write(datos)
                    inicio += len(datos)
                posicion = fin
                escritas += linea_fin - linea_inicio
    finally:
        entrada.close()
    return escritas, None


'''RECUPERA LA SECCION EDITABLE [filtros] ANTES DE REESCRIBIR EL RESUMEN DE EJECUCION.'''
def conservar_seccion_filtros(ruta_config):
    predeterminada = (u'\n[filtros]\n'
                     u'# Una frase por linea. * significa cualquier texto intermedio.\n'
                     u'conservar =\n'
                     u'excluir =\n')

    if not os.path.isfile(ruta_config):
        return predeterminada

    with io.open(ruta_config, 'r', encoding='utf-8') as archivo:
        lineas = archivo.readlines()

    dentro, bloque = False, []
    for linea in lineas:
        titulo = linea.strip()
        if titulo.startswith('[') and titulo.endswith(']'):
            if dentro:
                break
            dentro = titulo.lower() == '[filtros]'
        if dentro:
            bloque.append(linea)
    return u'\n' + u''.join(bloque).strip(u'\n') + u'\n' if bloque else predeterminada



'''GUARDA LA FECHA SELECCIONADA Y EL RESULTADO DE CADA LOG EN EL ARCHIVO .config
ruta_logs SE ESCRIBE TAL COMO LA DEJO EL USUARIO (SE CONSERVA ENTRE EJECUCIONES)'''
def guardar_config(carpeta, usuario, fecha_seleccionada, resultados, ruta_logs_texto):
    ruta_config = os.path.join(carpeta, ARCHIVO_CONFIG)
    seleccion = fecha_seleccionada.strftime('%Y-%m-%d') if fecha_seleccionada else 'default_ultimas_%d_fechas' % FECHAS_DEFAULT
    texto = ('[general]\n'
             '# ruta_logs: carpeta donde estan los logs. Vacia = carpeta desde donde se ejecuta.\n'
             '# Acepta ~ y variables de entorno. Este valor se conserva cada vez que se ejecuta leer_logs.py.\n'
             'ruta_logs = %s\n'
             'usuario=%s\ngenerado=%s\nfecha_seleccionada=%s\n') % (
                 ruta_logs_texto, usuario, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), seleccion)
    for nombre, fechas, salida, escritas, ajuste, por_corrida in resultados:
        texto += '\n[%s]\nfechas=%s\nlog_exportado=%s\nlineas=%d\najuste_horas_utc=%+g\ncorte=%s\n' % (
            nombre, ','.join(f.strftime('%Y-%m-%d') for f in fechas), salida, escritas, ajuste,
            'corridas_completas' if por_corrida else 'por_dia')
    filtros = conservar_seccion_filtros(ruta_config)
    with io.open(ruta_config, 'w', encoding='utf-8') as config:
        resumen = texto.decode(CODIFICACION_RUTAS) if isinstance(texto, bytes) else texto
        config.write(resumen + filtros)
    return ruta_config



'''LEE LOS ARGUMENTOS: LOS LOGS Y LA FECHA OPCIONAL (--fecha AAAA-MM-DD)'''
def leer_argumentos():
    parser = argparse.ArgumentParser(description='Filtra logs por fecha y los exporta a una carpeta con el nombre del usuario.')
    parser.add_argument('logs', nargs='+', help='uno o mas logs (.log, .out, .txt, sus .gz, o .zip)')
    parser.add_argument('--fecha', help='AAAA-MM-DD (default: ultimas %d fechas disponibles de cada log)' % FECHAS_DEFAULT)
    args = parser.parse_args()
    if args.fecha:
        try:
            args.fecha = datetime.strptime(args.fecha, '%Y-%m-%d').date()
        except ValueError:
            parser.error('la fecha debe tener el formato AAAA-MM-DD, por ejemplo 2026-10-19')
    return args


'''PROCESA UN LOG (O UN LOG DENTRO DE UN .zip): RESUMEN, SELECCION DE FECHAS Y EXPORTACION
DEVUELVE EL RESULTADO PARA EL .config, O None SI NO SE EXPORTO NADA; Y SI HUBO UN PROBLEMA'''
def procesar(nombre, base, abrir, se_puede_saltar, ruta, carpeta, fecha_pedida):
    ajuste, detectado = detectar_ajuste(abrir)
    primera_fecha, ultima_fecha, fechas_disponibles, segmentos, tamano, por_corrida = analizar_log(abrir, ajuste)
    print(nombre)
    print('  Ajuste de zona horaria para 2026-..-.. hh:mm:ss: %+g h (%s)' % (
        ajuste, 'detectado en el log' if detectado else 'no se pudo detectar, se usa AJUSTE_HORAS_FORMATO_ISO'))
    print('  Corte: %s' % ('corridas completas, por fecha de inicio' if por_corrida else 'por dia (el log no tiene corridas)'))
    if ultima_fecha is None:
        print('  Se omite: no tiene fechas.\n')
        return None, False

    '''MOSTRAMOS EL RESUMEN Y LAS FECHAS DISPONIBLES DEL LOG'''
    print('  \nPrimera fecha: %s' % formatear(primera_fecha))
    print('  \nUltima fecha: %s' % formatear(ultima_fecha))
    print('  Fechas disponibles:')
    for dia in fechas_disponibles:
        print('      %s' % dia.strftime('%Y-%m-%d'))

    '''ELEGIMOS LAS FECHAS: LA DE --fecha O LAS ÚLTIMAS FECHAS_DEFAULT DISPONIBLES'''
    if fecha_pedida and fecha_pedida not in fechas_disponibles:
        print('  Se omite: la fecha %s no aparece en este log.\n' % fecha_pedida.strftime('%Y-%m-%d'))
        return None, False
    fechas = [fecha_pedida] if fecha_pedida else fechas_disponibles[-FECHAS_DEFAULT:]

    '''EN PROD EL LOG PUEDE VACIARSE ENTRE LA LECTURA Y LA COPIA (restart_watcher HACE echo "" >)'''
    if se_puede_saltar and os.path.getsize(ruta) < tamano:
        print('  [!] el log se vacio o se recorto despues de analizarlo (posible restart_watcher); vuelve a correr el script\n',
              file=sys.stderr)
        return None, True

    '''EXPORTAMOS EL NUEVO LOG A LA CARPETA DEL USUARIO'''
    rango = fechas[0].strftime('%Y%m%d') + ('' if len(fechas) == 1 else '_a_' + fechas[-1].strftime('%Y%m%d'))
    salida = os.path.join(carpeta, '%s_%s.log' % (base, rango))
    elegidos = [s for s in segmentos if s[0] in set(fechas)]
    escritas, error = copiar_segmentos(abrir, se_puede_saltar, elegidos, salida)
    if error:
        print('  [!] %s' % error, file=sys.stderr)
    print('  Fechas exportadas: %s' % ', '.join(f.strftime('%Y-%m-%d') for f in fechas))
    print('  Exportado: %s (%d lineas)\n' % (salida, escritas))
    return (nombre, fechas, salida, escritas, ajuste, por_corrida), bool(error)


if __name__ == '__main__':
    args = leer_argumentos()

    '''CREAMOS LA CARPETA CON EL NOMBRE DEL USUARIO (getpass, PORQUE sys NO DA EL USUARIO)'''
    usuario = getpass.getuser()
    carpeta = os.path.join(os.getcwd(), usuario)
    if not os.path.isdir(carpeta):
        os.makedirs(carpeta)

    '''SI EL .config DEL USUARIO TRAE ruta_logs, LOS NOMBRES DE LOG SE BUSCAN EN ESA CARPETA'''
    ruta_logs, ruta_logs_texto = cargar_ruta_logs(), leer_ruta_logs_texto()
    if ruta_logs:
        if not os.path.isdir(ruta_logs):
            print('La carpeta ruta_logs de %s no existe: %s' % (ruta_config_usuario(), ruta_logs), file=sys.stderr)
            sys.exit(1)
        print('Carpeta de logs (%s): %s\n' % (ruta_config_usuario(), ruta_logs))

    resultados, problemas = [], 0
    for nombre_log in args.logs: #Por cada ruta (en caso de mas de un log)
        ruta = resolver_log(nombre_log, ruta_logs)
        '''SI LA RUTA NO EXISTE O NO ES UN ARCHIVO, SE AVISA Y SE SIGUE CON LOS DEMAS LOGS'''
        if not os.path.isfile(ruta):
            print('Se omite %s: no existe o no es un archivo normal' % ruta, file=sys.stderr)
            problemas += 1
            continue

        '''UN .zip PUEDE TRAER VARIOS LOGS: CADA UNO SE PROCESA Y SE EXPORTA POR SEPARADO'''
        try:
            fuentes = abrir_fuentes(ruta)
            if not fuentes:
                print('Se omite %s: el .zip no contiene logs (%s)' % (ruta, ', '.join(EXTENSIONES_LOG)), file=sys.stderr)
                problemas += 1
            for nombre, base, abrir, se_puede_saltar in fuentes:
                resultado, hubo_problema = procesar(nombre, base, abrir, se_puede_saltar, ruta, carpeta, args.fecha)
                problemas += hubo_problema
                if resultado:
                    resultados.append(resultado)
        except ERRORES_DE_LECTURA as error:
            print('Se omite %s: no se pudo leer (%s)' % (ruta, error), file=sys.stderr)
            problemas += 1

    print('Configuracion guardada en: %s' % guardar_config(carpeta, usuario, args.fecha, resultados, ruta_logs_texto))

    '''CODIGO DE SALIDA 1 SI ALGUN LOG SE OMITIO O NO SE PUDO EXPORTAR COMPLETO (IGUAL QUE verificar_bloques.py)'''
    sys.exit(1 if problemas else 0)
