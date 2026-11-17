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
from datetime import datetime


'''
HERRAMIENTA DE SOPORTE PARA AMX: LAS MARCAS QUE REVISA SON DEL carmusr DE AMX
(_run_crew_modules_command_headless.sh Y bid_processing_orchestrator.py). CON LOGS DE OTRO CLIENTE NO APLICA.
REVISA SI LAS CORRIDAS ESCRITAS EN UN LOG ESTAN COMPLETAS.
UNA CORRIDA EMPIEZA CON "Running script with settings" (LO ESCRIBE EL .sh) Y TERMINA CON "CuiExit: shutdown complete." (LO ESCRIBE STUDIO).
EN LOS LOGS DE BIDS, LA SALIDA DEL ORQUESTADOR (PYTHON) LLEGA DESPUES DEL CIERRE DE STUDIO; SI FALTA, SE PERDIO AL ESCRIBIR.
LAS CORRIDAS DE BIDS SON SECUENCIALES (process_bids.py USA os.system): SI EMPIEZA OTRA SIN QUE LA ANTERIOR CIERRE, LA ANTERIOR SE CORTO.
LAS CORRIDAS DE REPORTES (nohup.out) SI PUEDEN ENCIMARSE: AHI SE CUENTAN LAS ABIERTAS Y SE CIERRA PRIMERO LA MAS ANTIGUA.
'''

'''UNICOS LUGARES QUE ESTE MODULO PUEDE LEER (Y SUS SUBCARPETAS): LA CARPETA DESDE DONDE SE EJECUTA
Y, SI EL .config DEL USUARIO TRAE ruta_logs, ESA CARPETA (NO HAY OPCION EN LA LINEA DE COMANDOS PARA LEER FUERA)'''
CARPETAS_PERMITIDAS = [os.getcwd()]
ARCHIVO_CONFIG = 'fecha_seleccionada.config' # El .config por usuario que crea leer_logs.py; de ahi se toma ruta_logs

EXTENSIONES_LOG = ('.log', '.out', '.txt')                                   # Los clientes a veces renombran el log a .txt
EXTENSIONES_PERMITIDAS = EXTENSIONES_LOG + tuple(e + '.gz' for e in EXTENSIONES_LOG) + ('.zip',)
LIMITE_LINEA = 1024 * 1024 # Una linea mas larga se lee en pedazos de 1 MB, para no agotar la memoria con un hueco de bytes nulos

'''MARCAS DE INICIO Y FIN DE CADA CORRIDA'''
INICIO = b'Running script with settings'
FIN = b'CuiExit: shutdown complete.'

'''MARCAS QUE DEBE ESCRIBIR CADA CORRIDA DE BIDS (bid_processing_orchestrator.py)
NO SE INCLUYE "Studio PID:": STUDIO 31 LA ESCRIBE, PERO STUDIO 28 (gam_usr_prod_no_interbids) NO. QUE STUDIO ARRANCO
Y TERMINO YA LO COMPRUEBAN "CpmExit: done" Y EL CIERRE "CuiExit: shutdown complete."'''
MARCAS_BIDS = [
    b'CpmExit: done',
    b'SCRIPT_RUN_TYPE = ',
    b'Subplans to process:',
    b'Opening plan:',
    b'Removing marker file',
]
MARCA_EXITO_BIDS = b'===== UPLOADING DATA SUCCESSFUL ====='

'''TODO LO QUE NO SEA ASCII IMPRIMIBLE (CARACTERES DE CONTROL, SECUENCIAS DE ESCAPE DE TERMINAL, ACENTOS) SE CAMBIA POR ?
LOS LOGS VIENEN DEL CLIENTE, ASI QUE LO QUE SE IMPRIME DE ELLOS NO DEBE PODER ALTERAR LA CONSOLA DE SOPORTE
(QUITAR LOS ACENTOS TAMBIEN EVITA ERRORES DE CODIFICACION AL IMPRIMIR EN PYTHON 2.7)'''
PATRON_CONTROL = re.compile(u'[^\x20-\x7e]')

MESES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DIAS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

'''PATRONES PARA IDENTIFICAR CADA CORRIDA: TIPO, SUBPLAN Y HORA DE INICIO'''
PATRON_COMANDO = re.compile(br'PythonRunFile\("([^"]*crew_modules[^"]*)"(?:,"([^"]*)")?') # Ignora los scripts de arranque de Studio (InitMenuState.py, etc.)
PATRON_SUBPLAN = re.compile(br'^SCRIPT_SUBPLANS\s+=\s+(\S+)')
PATRON_MARK = re.compile(br'(\d{8}_\d{6})\.mark')
PATRON_TIME = re.compile(br'^Time: (\d{8} \d{2}:\d{2}:\d{2})')

FALTA_CIERRE = 'cierre de Studio (CuiExit)'
FALTA_CIERRE_ULTIMA = FALTA_CIERRE + ' - puede seguir en curso'
FALTA_CIERRE_INTERRUMPIDA = FALTA_CIERRE + ' - empezo otra corrida antes de que terminara'


'''CONVIERTE 20261019_140011 O 20261019 14:00:11 AL FORMATO Mon Oct 19 14:00:11 2026'''
def formatear_hora(texto):
    fecha = datetime.strptime(texto.replace('_', ' ').replace(':', ''), '%Y%m%d %H%M%S')
    return '%s %s %2d %s' % (DIAS[fecha.weekday()], MESES[fecha.month - 1], fecha.day, fecha.strftime('%H:%M:%S %Y'))


'''QUITA LOS CARACTERES DE CONTROL DE UN TEXTO QUE VIENE DEL LOG'''
def limpiar(texto):
    return PATRON_CONTROL.sub(u'?', texto)


'''CREA EL REGISTRO DE UNA CORRIDA NUEVA'''
def nueva_corrida(numero, linea):
    return {'numero': numero, 'linea_inicio': linea, 'linea_fin': None, 'tipo': '?', 'subplan': '', 'hora': '',
            'marcas': set(), 'exito': False, 'encimada': False, 'interrumpida': False}


'''RECORRE LAS LINEAS DEL LOG Y ARMA LA LISTA DE CORRIDAS CON LO QUE ESCRIBIO CADA UNA
RECIBE LAS LINEAS (EN BYTES) PARA PODER PROBARLO SIN ARCHIVOS'''
def leer_corridas(lineas):
    corridas, abiertas, cierres_huerfanos = [], [], []
    lineas_con_nul, sin_salto_final = 0, False

    for num, linea in enumerate(lineas, 1):
        if b'\x00' in linea:
            lineas_con_nul += 1
        sin_salto_final = not linea.endswith(b'\n')

        if linea.startswith(INICIO):
            '''LAS DE BIDS ABIERTAS SE CORTARON; LAS DE REPORTES SE ESTAN ENCIMANDO CON LA NUEVA'''
            corrida = nueva_corrida(len(corridas) + 1, num)
            for otra in [c for c in abiertas if c['tipo'] == 'BIDS']:
                otra['interrumpida'] = True
                abiertas.remove(otra)
            if abiertas:
                corrida['encimada'] = True
                for otra in abiertas:
                    otra['encimada'] = True
            corridas.append(corrida)
            abiertas.append(corrida)
            continue

        if linea.startswith(FIN): # Termina la corrida abierta mas antigua (las lineas no traen PID para saber cual)
            if abiertas:
                abiertas.pop(0)['linea_fin'] = num
            else:
                cierres_huerfanos.append(num)
            continue

        if not corridas:
            continue
        actual = corridas[-1] # El resto de las marcas se asigna a la corrida mas reciente

        for marca in MARCAS_BIDS:
            if marca in linea:
                actual['marcas'].add(marca)
        if MARCA_EXITO_BIDS in linea:
            actual['exito'] = True

        if actual['tipo'] == '?' and b'bid_processing_orchestrator' in linea: # Ya viene en el encabezado (SCRIPT_ERR_MARK_FILE)
            actual['tipo'] = 'BIDS'

        comando = PATRON_COMANDO.search(linea)
        if comando and not actual['subplan'] and comando.group(2):
            actual['subplan'] = limpiar(comando.group(2).decode('latin-1'))
        if comando and actual['tipo'] == '?':
            actual['tipo'] = limpiar(comando.group(1).decode('latin-1').split('/')[-1])

        subplan = PATRON_SUBPLAN.search(linea)
        if subplan and not actual['subplan']:
            actual['subplan'] = limpiar(subplan.group(1).decode('latin-1'))

        hora = PATRON_MARK.search(linea) or PATRON_TIME.search(linea)
        if hora and not actual['hora']:
            actual['hora'] = formatear_hora(hora.group(1).decode('latin-1'))

    return corridas, cierres_huerfanos, lineas_con_nul, sin_salto_final


'''DECIDE EL ESTADO DE CADA CORRIDA: COMPLETA, SIN_EXITO O INCOMPLETA (CON LO QUE LE FALTA)'''
def evaluar(corrida, es_la_ultima):
    faltantes = []
    if corrida['interrumpida']:
        faltantes.append(FALTA_CIERRE_INTERRUMPIDA)
    elif corrida['linea_fin'] is None:
        faltantes.append(FALTA_CIERRE_ULTIMA if es_la_ultima else FALTA_CIERRE)
    if corrida['tipo'] == 'BIDS':
        faltantes += [m.decode('latin-1').strip() for m in MARCAS_BIDS if m not in corrida['marcas']]
    if faltantes:
        return 'INCOMPLETA', faltantes
    if corrida['tipo'] == 'BIDS' and not corrida['exito']:
        return 'SIN_EXITO', ['no aparece "UPLOADING DATA SUCCESSFUL" (escritura completa, pero el proceso pudo fallar)']
    return 'COMPLETA', []


'''IMPRIME EL RESUMEN DE UN LOG Y EL DETALLE DE LAS CORRIDAS CON PROBLEMAS (O DE TODAS CON --todas)
DEVUELVE CUANTOS PROBLEMAS ENCONTRO (0 = TODO BIEN)'''
def reportar(nombre, lineas, mostrar_todas):
    corridas, cierres_huerfanos, lineas_con_nul, sin_salto_final = leer_corridas(lineas)
    estados = [evaluar(c, i == len(corridas) - 1) for i, c in enumerate(corridas)]
    conteo = dict((e, sum(1 for est, _ in estados if est == e)) for e in ('COMPLETA', 'SIN_EXITO', 'INCOMPLETA'))
    encimadas = sum(1 for c in corridas if c['encimada'])

    print('=' * 78)
    print(limpiar(nombre))
    print('=' * 78)
    print('  Corridas encontradas : %d' % len(corridas))
    print('  Completas            : %d' % conteo['COMPLETA'])
    print('  Sin mensaje de exito : %d' % conteo['SIN_EXITO'])
    print('  Incompletas          : %d' % conteo['INCOMPLETA'])
    print('  Encimadas con otra   : %d%s' % (encimadas, '  (aviso: varias corridas escribiendo a la vez)' if encimadas else ''))

    '''PROBLEMAS DEL ARCHIVO COMPLETO, NO DE UNA CORRIDA'''
    problemas_archivo = 0
    if cierres_huerfanos:
        problemas_archivo += 1
        print('  [!] %d cierre(s) sin inicio, primero en la linea %d: el log empieza a mitad de una corrida '
              '(posible vaciado por restart_watcher)' % (len(cierres_huerfanos), cierres_huerfanos[0]))
    if lineas_con_nul:
        problemas_archivo += 1
        print('  [!] %d linea(s) con bytes nulos: el archivo se vacio mientras un proceso seguia escribiendo' % lineas_con_nul)
    if sin_salto_final:
        problemas_archivo += 1
        print('  [!] La ultima linea no termina en salto de linea: la escritura se corto a mitad de linea')

    '''DETALLE DE CADA CORRIDA'''
    for corrida, (estado, faltantes) in zip(corridas, estados):
        if estado == 'COMPLETA' and not mostrar_todas:
            continue
        print('  #%-4d %-10s linea %-8d %-24s %-17s %s' % (corrida['numero'], estado, corrida['linea_inicio'],
                                                         corrida['hora'], corrida['tipo'], corrida['subplan']))
        for faltante in faltantes:
            print('         falta: %s' % faltante)
    print('')

    return conteo['INCOMPLETA'] + problemas_archivo


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


'''VALIDA QUE LA RUTA SEA UN LOG DENTRO DE LAS CARPETAS PERMITIDAS Y QUE SEA UN ARCHIVO NORMAL
realpath RESUELVE LINKS Y "..", ASI NO SE PUEDE SALIR DE LA CARPETA CON ../../etc/passwd O CON UN LINK'''
def validar_ruta(ruta):
    real = os.path.normcase(os.path.realpath(ruta)) # normcase: en Windows C:\Logs y c:\logs son la misma carpeta
    carpetas = [os.path.normcase(os.path.realpath(c)) for c in CARPETAS_PERMITIDAS]
    if not any(real.startswith(c.rstrip(os.sep) + os.sep) for c in carpetas):
        return 'esta fuera de las carpetas permitidas (%s)' % ', '.join(CARPETAS_PERMITIDAS)
    if not real.lower().endswith(EXTENSIONES_PERMITIDAS):
        return 'no es un log (%s)' % ', '.join(EXTENSIONES_PERMITIDAS)
    if not os.path.isfile(real):
        return 'no existe o no es un archivo normal'
    return None


'''LEE EL ARCHIVO EN MODO LECTURA, CON UN LIMITE POR LINEA'''
def lineas_del_archivo(archivo):
    return iter(lambda: archivo.readline(LIMITE_LINEA), b'')


'''ABRE UN LOG NORMAL, UN .gz O UN .zip SIN DESCOMPRIMIR NADA EN DISCO
DEVUELVE (NOMBRE, FUNCION QUE ABRE EL LOG) POR CADA LOG; DE UN .zip SOLO TOMA LOS QUE TIENEN EXTENSION DE LOG
CADA LOG SE ABRE JUSTO CUANDO SE VA A LEER: EN PYTHON 2.7 LOS ARCHIVOS ABIERTOS DE UN MISMO .zip COMPARTEN
LA POSICION DE LECTURA, Y SI SE ABREN TODOS DE GOLPE SE MEZCLAN Y SE PIERDEN CORRIDAS'''
def abrir_logs(ruta, archivo):
    nombre = ruta.lower()
    if nombre.endswith('.gz'):
        return [(ruta, lambda: gzip.GzipFile(fileobj=archivo, mode='rb'))]
    if nombre.endswith('.zip'):
        comprimido = zipfile.ZipFile(archivo)
        return [('%s:%s' % (ruta, miembro), lambda miembro=miembro: comprimido.open(miembro))
                for miembro in comprimido.namelist() if miembro.lower().endswith(EXTENSIONES_LOG)]
    return [(ruta, lambda: archivo)]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Revisa si las corridas escritas en los logs estan completas.')
    parser.add_argument('logs', nargs='+', help='uno o mas archivos de log')
    parser.add_argument('--todas', action='store_true', help='muestra tambien las corridas completas')
    args = parser.parse_args()

    '''SI EL .config DEL USUARIO TRAE ruta_logs, AHI SE BUSCAN LOS LOGS Y SE PUEDE LEER ESA CARPETA
    (ADEMAS DE LA CARPETA DESDE DONDE SE EJECUTA, DONDE leer_logs.py DEJA LOS LOGS EXPORTADOS)'''
    ruta_logs = cargar_ruta_logs()
    if ruta_logs:
        if not os.path.isdir(ruta_logs):
            print('La carpeta ruta_logs de %s no existe: %s' % (ruta_config_usuario(), ruta_logs), file=sys.stderr)
            sys.exit(1)
        CARPETAS_PERMITIDAS = [os.getcwd(), ruta_logs]
        print('Carpeta de logs (%s): %s\n' % (ruta_config_usuario(), ruta_logs))

    '''REVISAMOS CADA LOG; EL CODIGO DE SALIDA ES 1 SI ALGUNO TIENE PROBLEMAS (UTIL PARA cron)'''
    problemas = 0
    for nombre in args.logs: #Por cada ruta (en caso de mas de un log)
        ruta = resolver_log(nombre, ruta_logs)
        error = validar_ruta(ruta)
        if error:
            print('Se omite %s: %s' % (ruta, error), file=sys.stderr)
            problemas += 1
            continue
        with open(os.path.realpath(ruta), 'rb') as archivo:
            try:
                logs = abrir_logs(ruta, archivo)
                if not logs:
                    print('Se omite %s: el .zip no contiene logs (%s)' % (ruta, ', '.join(EXTENSIONES_LOG)), file=sys.stderr)
                    problemas += 1
                for nombre, abrir in logs:
                    problemas += reportar(nombre, lineas_del_archivo(abrir()), args.todas)
            except (IOError, OSError, EOFError, zlib.error, zipfile.BadZipfile) as error: # .gz o .zip danado
                print('Se omite %s: no se pudo leer (%s)' % (ruta, error), file=sys.stderr)
                problemas += 1
    sys.exit(1 if problemas else 0)
