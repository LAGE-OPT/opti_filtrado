# -*- coding: utf-8 -*-
# Filtra un log por fecha y por palabras clave. Python 2.7 y 3, sin librerias externas.
# Uso: python filtrar_log.py process_bids.log [-f 2026-10-19] [-c "frase"] [-e "frase"]   (o --fecha, --conservar, --excluir)
#      python filtrar_log.py process_bids.log -li "inicio" -lf "fin"   (bloques entre dos lineas)
from __future__ import print_function
import argparse
import getpass
import io
import os
import re
import shutil
import sys

CONFIG = 'filtrar_log.config'
INICIO = b'Running script with settings'
MESES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
RAYA = '-' * 89
MARCA_BLOQUE = b'\x00\x00@@BLOQUE@@%d\x00\x00\n' # Lugar del titulo de cada bloque mientras no se sabe donde termina

'''FRASES DEFAULT: SE ESCRIBEN EN EL .config LA PRIMERA VEZ; DESPUES SE EDITAN AHI'''
CONFIG_INICIAL = u'''# Frases default de filtrar_log.py. Una por linea; las que empiezan con # se ignoran.
# Sin distinguir mayusculas. Con el prefijo re: es expresion regular.
# conservar: el log filtrado muestra SOLO las lineas que tienen alguna de estas frases.
# excluir: de esas lineas, se quitan las que tambien tienen una frase de excluir (gana excluir).
# Las lineas que no tienen ninguna frase de conservar no aparecen.
#
# EJEMPLO COMPLETO
# Si agregas esto (sin el # de adelante):
#     [conservar]
#     re:^SCRIPT_
#     [excluir]
#     SCRIPT_ERR_MARK_FILE
# y en el log hay estas lineas:
#     SCRIPT_ERR_MARK_FILE = .../20261019_140011.mark  -> se quita (empieza con SCRIPT_, pero tambien esta en excluir)
#     SCRIPT_RUN_TYPE = prod                           -> se queda (re:^SCRIPT_ : empieza con SCRIPT_)
#     Error! Pid:1601606  Mon Oct 19 14:04:00 2026     -> se queda (Error! es default de conservar)
#     Error! GetTaskCol: Could not to find task column -> se quita (tiene Error!, pero GetTaskCol es default de excluir)
#     Setting baseURL to http://studio-web01...        -> se quita (no tiene ninguna frase de conservar)
#     CuiExit: shutdown complete.                      -> se quita (no tiene ninguna frase de conservar)
# Para dejar de ver algo, borra su linea de [conservar] o ponle # adelante.

[conservar]
Error!
Traceback (most recent call last)
waiting for answer yesorno
ERROR UPLOADING DATA
The X11 connection broke
ERROR: Marker file not removed
KeyboardInterrupt
Segmentation fault
No space left on device
Permission denied
Connection refused

[excluir]
GetTaskCol: Could not to find task column
Not operating created
re:Deprecation [Ww]arning
ERROR MenuParser
ERROR StudioIcon No icon found
re:File not found.*menu_scripts
El valor no existe en la columna de la tabla
read_help_topics
re:[Mm]ap variable \\S+ is not defined
Warning selection string exists
Failed to start TTY watchdog
crsCvtYesNo
_XSERVTrans
 INFO rave.crc.etable
carmusr.crew_modules.request
'''

'''PATRONES DE FECHA. SOLO IMPORTA EL DIA: LA HORA SE IGNORA
OJO: EL FORMATO 2026-10-19 20:00:20 ESTA EN UTC (6 HORAS ADELANTE); POR ESO NO SE USA PARA LA FECHA DE UNA CORRIDA'''
FECHA_ISO = re.compile(br'(\d{4})-(\d\d)-(\d\d) \d\d:\d\d')                                 # 2026-10-19 20:00:20
FECHA_JUNTA = re.compile(br'(20\d\d)(\d\d)(\d\d)[ _]\d\d')                                  # 20261019 14:00:17 o 20261019_140011
FECHA_TEXTO = re.compile(br'[A-Z][a-z]{2} ([A-Z][a-z]{2}) +(\d{1,2}) \d\d:\d\d:\d\d (\d{4})') # Mon Oct 19 14:00:11 2026


def buscar_fecha(linea, con_utc=True):
    m = (con_utc and FECHA_ISO.search(linea)) or FECHA_JUNTA.search(linea)
    if m:
        anio, mes, dia = [int(g) for g in m.groups()]
    else:
        m = FECHA_TEXTO.search(linea)
        if not m or m.group(1).decode('ascii') not in MESES:
            return None
        anio, mes, dia = int(m.group(3)), MESES.index(m.group(1).decode('ascii')) + 1, int(m.group(2))
    if 1 <= mes <= 12 and 1 <= dia <= 31:
        return u'%d-%02d-%02d' % (anio, mes, dia)
    return None


'''PRIMERA LECTURA: EN QUE LINEA EMPIEZA CADA DIA. UNA CORRIDA COMPLETA VA CON LA FECHA DE SU INICIO, AUNQUE CRUCE LA MEDIANOCHE
SI EL LOG NO TIENE CORRIDAS (O ANTES DE LA PRIMERA), CADA FECHA QUE APARECE CAMBIA EL DIA'''
def cambios_de_fecha(ruta):
    cambios, corridas, inicio, en_corridas, buscar = [], {}, 1, False, True
    with open(ruta, 'rb') as log:
        for num, linea in enumerate(log, 1):
            if linea.lstrip(b'\x00').startswith(INICIO):
                inicio, en_corridas, buscar = num, True, True
            elif buscar:
                fecha = buscar_fecha(linea, con_utc=not en_corridas)
                if fecha:
                    if not cambios or cambios[-1][1] != fecha:
                        cambios.append((inicio if en_corridas else num, fecha))
                    if en_corridas:
                        corridas[fecha] = corridas.get(fecha, 0) + 1 # Para mostrarlo en el menu
                    buscar = not en_corridas
    if cambios:
        cambios[0] = (1, cambios[0][1]) # Las lineas antes de la primera fecha van con ella
    return cambios, corridas


'''MENU PARA ELEGIR FECHAS. Enter = LAS ULTIMAS 3. SIN TERMINAL (cron, TUBERIA) NO PREGUNTA Y TOMA LAS ULTIMAS 3'''
def elegir_fechas(nombre, disponibles, corridas):
    if not sys.stdin.isatty():
        return disponibles[-3:]
    print('Fechas en %s:' % nombre)
    for i, fecha in enumerate(disponibles, 1):
        print('  %2d) %s%s' % (i, fecha, '   %d corridas' % corridas[fecha] if fecha in corridas else ''))
    while True:
        print('Elige fechas (ejemplo: 1,3 o 2-4; T = todas; Enter = ultimas 3): ', end='')
        sys.stdout.flush()
        respuesta = sys.stdin.readline().strip().lower()
        if not respuesta:
            return disponibles[-3:]
        if respuesta in ('t', 'todas'):
            return disponibles
        elegidas = set()
        try:
            for parte in respuesta.replace(' ', '').split(','):
                inicio, _, fin = parte.partition('-')
                inicio, fin = int(inicio), int(fin or inicio)
                if not 1 <= inicio <= fin <= len(disponibles):
                    raise ValueError()
                elegidas.update(range(inicio, fin + 1))
            return [disponibles[i - 1] for i in sorted(elegidas)]
        except ValueError:
            print('  No entendi "%s"' % respuesta)


'''LEE LAS FRASES DEL .config (LO CREA CON LAS DEFAULT SI NO EXISTE)'''
def leer_config(ruta):
    if not os.path.isfile(ruta):
        with io.open(ruta, 'w', encoding='utf-8') as archivo:
            archivo.write(CONFIG_INICIAL)
    frases, seccion = {'conservar': [], 'excluir': []}, None
    with io.open(ruta, encoding='utf-8-sig', errors='replace') as archivo:
        for linea in archivo:
            if linea.strip().lower() in ('[conservar]', '[excluir]'):
                seccion = linea.strip().strip('[]').lower()
            elif seccion and linea.strip() and not linea.lstrip().startswith('#'):
                frases[seccion].append(linea.rstrip('\r\n'))
    return frases


'''TEXTO DE UNA LINEA PARA BUSCAR LAS FRASES: UTF-8 SI SE PUEDE, SI NO iso-8859-1'''
def a_texto(datos):
    try:
        return datos.decode('utf-8')
    except UnicodeDecodeError:
        return datos.decode('latin-1')


def coincide(frase, texto, minusculas):
    if frase.startswith(u're:'):
        return re.search(frase[3:], texto) is not None
    return frase.lower() in minusculas


'''UNA FRASE DEL USUARIO: EN PYTHON 2.7 LLEGA EN BYTES'''
def argumento(valor):
    if isinstance(valor, bytes):
        return valor.decode('mbcs' if os.name == 'nt' else 'utf-8', 'replace')
    return valor


def frase_valida(frase):
    try:
        if frase.startswith(u're:'):
            re.compile(frase[3:])
        return True
    except re.error:
        print('Se omite la expresion regular invalida: %r' % frase, file=sys.stderr)
        return False


def filtrar(ruta, carpeta, usuario, fechas_pedidas, conservar, excluir, mas_conservar, mas_excluir, inicial=None, final=None, bloque_con=()):
    adicionales = [f for i, f in enumerate(mas_conservar + mas_excluir) if f not in (mas_conservar + mas_excluir)[:i]]
    nombre = os.path.basename(ruta)
    cambios, corridas = cambios_de_fecha(ruta)
    disponibles = sorted(set(fecha for _, fecha in cambios))
    if not disponibles:
        print('%s: no tiene fechas, se omite' % nombre)
        return

    '''ELEGIMOS LAS FECHAS: LAS DE --fecha O CON EL MENU'''
    fechas = [f for f in fechas_pedidas if f in disponibles] if fechas_pedidas else elegir_fechas(nombre, disponibles, corridas)
    for fecha in fechas_pedidas:
        if fecha not in disponibles:
            print('%s: la fecha %s no esta en el log (tiene %s)' % (nombre, fecha, ', '.join(disponibles)))
    if not fechas:
        return

    '''SEGUNDA LECTURA: SE ESCRIBEN LAS LINEAS DE ESAS FECHAS QUE TIENEN UNA FRASE DE conservar Y NINGUNA DE excluir
Y SE CUENTAN LAS FRASES ADICIONALES
CON -li Y -lf, ADEMAS, SE ESCRIBEN LOS BLOQUES COMPLETOS: DESDE UNA LINEA CON EL FRAGMENTO INICIAL HASTA LA SIGUIENTE
CON EL FRAGMENTO FINAL (LAS DOS INCLUIDAS). EL BLOQUE SOLO SE CORTA AL ENCONTRAR LA LINEA FINAL: SI EN MEDIO SE REPITE
LA LINEA INICIAL, ES PARTE DEL MISMO BLOQUE. UN BLOQUE QUE EMPEZO EN UNA FECHA ELEGIDA SIGUE AUNQUE PASE A OTRO DIA
SI EL LOG TERMINA SIN LA LINEA FINAL, ESE ULTIMO BLOQUE NO SE MUESTRA (SOLO SE AVISA)
LOS BLOQUES Y EL FILTRADO VAN A DOS ARCHIVOS TEMPORALES; AL FINAL SE JUNTAN: PRIMERO LOS BLOQUES'''
    contador = dict((frase, [0, 0, 0]) for frase in adicionales) # veces, primera linea, ultima linea
    bloques = []  # [primera linea, ultima linea, tiene una frase de -bc]
    dentro = False
    rango = fechas[0].replace('-', '') + ('' if len(fechas) == 1 else '_a_' + fechas[-1].replace('-', ''))
    salida = os.path.join(carpeta, '%s_filtrado_%s.log' % (os.path.splitext(nombre)[0], rango))
    temporal_bloques, temporal_filtrado = salida + '.bloques.tmp', salida + '.tmp'
    escritas, i, fecha, num = 0, 0, None, 0
    with open(ruta, 'rb') as log, open(temporal_bloques, 'wb') as tmp_bloques, open(temporal_filtrado, 'wb') as tmp_filtrado:
        for num, linea in enumerate(log, 1):
            while i < len(cambios) and cambios[i][0] <= num:
                fecha, i = cambios[i][1], i + 1
            if fecha not in fechas and not dentro:
                continue
            texto = a_texto(linea)
            minusculas = texto.lower()

            '''BLOQUES ENTRE -li Y -lf'''
            if inicial:
                if dentro:
                    tmp_bloques.write(linea)
                    if not bloques[-1][2] and any(coincide(f, texto, minusculas) for f in bloque_con):
                        bloques[-1][2] = True # El bloque tiene una frase de -bc
                    if coincide(final, texto, minusculas):
                        bloques[-1][1], dentro = num, False
                elif fecha in fechas and coincide(inicial, texto, minusculas):
                    bloques.append([num, None, not bloque_con or any(coincide(f, texto, minusculas) for f in bloque_con)])
                    tmp_bloques.write(MARCA_BLOQUE % len(bloques)) # Se cambia por el titulo del bloque al final
                    tmp_bloques.write(linea)
                    dentro = True
            if fecha not in fechas: # Linea de un bloque que ya paso a otro dia: no cuenta para lo demas
                continue

            '''CONTADORES Y FILTRO POR FRASES'''
            for frase in adicionales:
                if coincide(frase, texto, minusculas):
                    c = contador[frase]
                    c[0], c[1], c[2] = c[0] + 1, c[1] or num, num
            if not any(coincide(f, texto, minusculas) for f in conservar) or any(coincide(f, texto, minusculas) for f in excluir):
                continue
            tmp_filtrado.write(linea)
            escritas += 1
    sin_final = bloques.pop() if dentro else None # El log termino antes de la linea final: ese bloque no se muestra

    '''ENCABEZADO: DATOS DEL LOG; DESPUES DE LOS BLOQUES (SI SE PIDIERON) VAN LAS FRASES Y SUS CONTADORES'''
    inicio = [u'LOG ["%s"] FILTRADO' % nombre,
              u'Generado por: %s' % usuario,
              u'Fechas: %s' % u', '.join(fechas),
              RAYA]
    lineas = [u'Conservar [%s]' % u', '.join(mas_conservar),
               u'Excluir [%s]' % u', '.join(mas_excluir),
               u'Las frases default de conservar y excluir se encuentran en %s' % CONFIG,
               RAYA]
    for frase in adicionales:
        veces, primera, ultima = contador[frase]
        if veces == 0:
            lineas.append(u'%s: No encontrado' % frase)
        elif veces == 1:
            lineas.append(u'%s: Encontrado 1 vez en la linea %d' % (frase, primera))
        else:
            lineas.append(u'%s: Encontrado %d veces de la linea %d a la linea %d' % (frase, veces, primera, ultima))
    lineas.append(RAYA)

    '''ARCHIVO FINAL: DATOS DEL LOG, BLOQUES (CADA UNO CON SU TITULO), FRASES CON SUS CONTADORES Y LOG FILTRADO
    LAS LINEAS DEL LOG VAN TAL CUAL EL ORIGINAL'''
    with open(salida, 'wb') as archivo:
        archivo.write(u'\n'.join(inicio).encode('utf-8') + b'\n')
        if inicial:
            '''CON -bc SOLO SE COPIAN LOS BLOQUES QUE TIENEN UNA DE ESAS FRASES; CONSERVAN SU NUMERO ORIGINAL'''
            mostrados = [b for b in bloques if b[2]]
            if bloque_con:
                titulo = u'Bloques desde "%s" hasta "%s" con [%s]: %d de %d encontrados' % (
                    inicial, final, u', '.join(bloque_con), len(mostrados), len(bloques))
            else:
                titulo = u'Bloques desde "%s" hasta "%s": %d encontrados' % (inicial, final, len(bloques))
            if sin_final:
                titulo += u' (el que empieza en la linea %d no se muestra: el log termina sin la linea final)' % sin_final[0]
            archivo.write((titulo + u'\n').encode('utf-8'))
            copiar = False
            with open(temporal_bloques, 'rb') as temporal:
                for linea in temporal:
                    if linea.startswith(b'\x00\x00@@BLOQUE@@'):
                        n = int(linea[len(b'\x00\x00@@BLOQUE@@'):].split(b'\x00')[0])
                        copiar = n <= len(bloques) and bloques[n - 1][2]
                        if not copiar:
                            continue
                        primera, ultima = bloques[n - 1][:2]
                        linea = (u'----- Bloque %d: de la linea %d a la linea %d (%d lineas) -----\n' % (n, primera, ultima, ultima - primera + 1)).encode('utf-8')
                    if copiar:
                        archivo.write(linea)
            archivo.write((RAYA + '\n').encode('ascii'))
        archivo.write(u'\n'.join(lineas).encode('utf-8') + b'\n')
        with open(temporal_filtrado, 'rb') as temporal:
            shutil.copyfileobj(temporal, archivo)
    os.remove(temporal_bloques)
    os.remove(temporal_filtrado)
    detalle = ' %d bloques |' % len([b for b in bloques if b[2]]) if inicial else ''
    print('%s: %s |%s %d lineas filtradas | %s' % (nombre, ', '.join(fechas), detalle, escritas, salida))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Filtra un log por fecha y por palabras clave. Escribe el resultado en <carpeta actual>/<usuario>/.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''ejemplo completo:
  python filtrar_log.py process_bids.log --fecha 2026-10-19 --fecha 2026-10-20 \\
      --conservar "Cannot create gt" --conservar "re:LIMO\\+$" --excluir "Setting baseURL"

  - Toma solo las corridas que empezaron el 19 y el 20 de octubre (sin --fecha: menu para elegirlas).
  - Muestra solo las lineas con "Cannot create gt", las que terminan en "LIMO+" y las de [conservar] del .config.
  - De esas, quita las que tambien tienen "Setting baseURL" o una frase de [excluir] del .config.
  - Las lineas que no tienen ninguna frase de conservar no aparecen.
  - Escribe <usuario>/process_bids_filtrado_20261019_a_20261020.log con este encabezado:

      LOG ["process_bids.log"] FILTRADO
      Generado por: usuario
      Fechas: 2026-10-19, 2026-10-20
      -------------------------------------------------------------------------
      Conservar [Cannot create gt, re:LIMO\\+$]
      Excluir [Setting baseURL]
      Las frases default de conservar y excluir se encuentran en filtrar_log.config
      -------------------------------------------------------------------------
      Cannot create gt: Encontrado 452 veces de la linea 1350 a la linea 74419
      re:LIMO\\+$: Encontrado 452 veces de la linea 1350 a la linea 74419
      Setting baseURL: Encontrado 474 veces de la linea 647 a la linea 75430
      -------------------------------------------------------------------------
      (las lineas del log original que quedaron, tal cual)

bloques entre dos lineas (-li y -lf, siempre juntas; pueden ser solo un fragmento de la linea):
  python filtrar_log.py process_bids.log -f 2026-10-19 -li "LEG AM" -lf "LEG LA"

  - Escribe primero cada bloque completo, desde una linea con el fragmento inicial hasta la siguiente con el
    fragmento final (las dos incluidas), y despues el log filtrado por conservar y excluir, como siempre.
  - El bloque solo se corta al encontrar la linea final: si la linea inicial se repite en medio, sigue el mismo bloque.
  - Cada bloque lleva un titulo con sus lineas: ----- Bloque 1: de la linea 99 a la linea 376 (278 lineas) -----
  - Si el log termina sin la linea final, ese ultimo bloque no se muestra; el encabezado avisa donde empezaba.
  - Con -bc "frase" solo se muestran los bloques que tienen esa frase en alguna de sus lineas (se puede repetir;
    basta una). Ejemplo, solo los errores del vuelo duplicado MTY4044:
      python filtrar_log.py process_bids.log -li "Error! Pid" -lf "Legend:" -bc "MTY4044OD"

forma corta: -f es --fecha, -c es --conservar, -e es --excluir. El mismo ejemplo:
  python filtrar_log.py process_bids.log -f 2026-10-19 -f 2026-10-20 -c "Cannot create gt" -c "re:LIMO\\+$" -e "Setting baseURL"

frases: sin distinguir mayusculas; con el prefijo re: son expresion regular.
Solo se muestran las lineas con una frase de conservar; si tambien tienen una de excluir, se quitan (gana excluir).
Las frases default estan en <usuario>/filtrar_log.config; se crea la primera vez.''')
    parser.add_argument('logs', nargs='+', help='uno o mas logs')
    parser.add_argument('-f', '--fecha', action='append', default=[], help='AAAA-MM-DD; se puede repetir. Sin -f sale un menu (Enter = ultimas 3; sin terminal, como en cron, toma las ultimas 3)')
    parser.add_argument('-c', '--conservar', action='append', default=[], help='frase de las lineas que se muestran; se puede repetir')
    parser.add_argument('-li', '--linea-inicial', help='fragmento de la linea donde empieza cada bloque (con -lf)')
    parser.add_argument('-lf', '--linea-final', help='fragmento de la linea donde termina cada bloque (con -li)')
    parser.add_argument('-bc', '--bloque-con', action='append', default=[],
                        help='solo muestra los bloques de -li/-lf que tienen esta frase; se puede repetir (basta una)')
    parser.add_argument('-e', '--excluir', action='append', default=[], help='quita las lineas que la tengan, aunque tengan una de conservar; se puede repetir')
    args = parser.parse_args()
    if bool(args.linea_inicial) != bool(args.linea_final):
        parser.error('-li y -lf van juntas: indica la linea inicial y la final')
    if args.bloque_con and not args.linea_inicial:
        parser.error('-bc necesita -li y -lf: solo filtra bloques')
    for fecha in args.fecha:
        if not re.match(r'^\d{4}-\d\d-\d\d$', fecha):
            parser.error('la fecha debe ser AAAA-MM-DD, por ejemplo 2026-10-19')

    '''CARPETA CON EL NOMBRE DEL USUARIO, AHI VAN EL .config Y LOS LOGS FILTRADOS'''
    usuario = getpass.getuser()
    carpeta = os.path.join(os.getcwd(), usuario)
    if not os.path.isdir(carpeta):
        os.makedirs(carpeta)
    default = leer_config(os.path.join(carpeta, CONFIG))

    '''FRASES ADICIONALES (LINEA DE COMANDOS) MAS LAS DEFAULT DEL .config'''
    mas_conservar = [f for f in map(argumento, args.conservar) if frase_valida(f)]
    mas_excluir = [f for f in map(argumento, args.excluir) if frase_valida(f)]
    conservar = [f for f in default['conservar'] if frase_valida(f)] + mas_conservar
    excluir = [f for f in default['excluir'] if frase_valida(f)] + mas_excluir

    inicial = argumento(args.linea_inicial) if args.linea_inicial else None
    final = argumento(args.linea_final) if args.linea_final else None
    bloque_con = [argumento(f) for f in args.bloque_con]
    if inicial and not all(frase_valida(f) for f in [inicial, final] + bloque_con):
        sys.exit(1)
    if not conservar:
        print('Aviso: no hay frases de conservar (ni en %s ni con -c): el log filtrado por frases saldra vacio' % CONFIG)
    try:
        for ruta in args.logs:
            if not os.path.isfile(ruta):
                print('%s: no existe, se omite' % ruta)
                continue
            filtrar(ruta, carpeta, usuario, [argumento(f) for f in args.fecha], conservar, excluir, mas_conservar, mas_excluir,
                    inicial, final, bloque_con)
    except KeyboardInterrupt: # Ctrl-C en el menu o mientras filtra
        print('\nCancelado.')