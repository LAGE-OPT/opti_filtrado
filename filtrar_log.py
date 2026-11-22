# -*- coding: utf-8 -*-
'''
OPTI FILTRADO
-------------
Este programa es una herramienta para el equipo de soporte de Aeroméxico.
Utiliza como input archivos .log y .out junto con algunos parámetros que facilitan la búsqueda de información.

-f y --fecha: En formato AAAA-MM-DD para una fecha en específico. En caso de no utilizar este parámetro, un menú se desplegará en la terminal para seleccionar la o las fechas a filtrar.
-li (línea inicial), -lf (línea final): Una string entre comillas para guardar todas las líneas entre estas dos líneas, se guardan en bloques en caso de que se repita en múltiples ocasiones a lo largo del log.
-bc: Un string entre comillas, se tiene que utilizar en conjunto con -li y -lf. Es un condicional de frase dentro de los bloques, se descarta el bloque si la frase -bc no se encuentra dentro del mismo.
-c y --conservar: Frase en string dentro de comillas. Conserva las líneas que contengan la frase
-e y --excluir: Frase en string dentro de comillas. Se utiliza en conjunto a -c. Excluye las líneas que contengan la frase a pesar de ser conservadas por -c

EJEMPLO DE TERMINAL:
python filtrar_log.py -f 2026-09-08 -c "could not read help topic file:" -e "etab" -li "Studio PID:" -lf "Release:" -bc "Display:   :1" process_bids_AMCUS_2129.log
'''
from __future__ import print_function
import argparse
import getpass
import io
import os
import re
import sys
import time

CONFIG = 'filtrar_log.config'
INICIO = b'Running script with settings'
MESES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
RAYA = '-' * 89
NUMERADO = re.compile(r'^\d+_.+_filtrado_\d{8}(_a_\d{8})?\.log$') # Outputs con numero: 1_process_bids_filtrado_20261019.log
MARCA_BLOQUE = b'\x00\x00@@BLOQUE@@%d\x00\x00\n' # Lugar del titulo de cada bloque mientras no se sabe donde termina

'''FRASES DEFAULT: SE ESCRIBEN EN EL .config LA PRIMERA VEZ; DESPUES SE EDITAN AHI'''
CONFIG_INICIAL = u'''# OPTI FILTRADO - frases default de filtrar_log.py. Una por linea; las que empiezan con # se ignoran.
# Sin distinguir mayusculas. Con el prefijo re: es expresion regular.
#
# COMO SE USAN
# El archivo de salida tiene dos partes; cada linea va tal cual del log, seguida de su numero: <linea del log> linea N
# 1. Frases de -c (terminal): debajo del contador de cada frase, sus lineas, sin las que tengan una frase de -e.
#    Una frase de -c gana a [excluir] de este archivo; solo -e la quita.
# 2. Frases default (este archivo): las lineas con una frase de [conservar], sin las que tengan una frase de
#    [excluir] o de -e. Las lineas que ya salieron en la parte 1 no se repiten.
# Una linea sin ninguna frase de -c ni de [conservar] no aparece.
#
# EJEMPLO COMPLETO
# python filtrar_log.py -f 2026-09-08 -c "could not read help topic file:" -e "etab" process_bids_AMCUS_2129.log
# con estas lineas en el log:
#     read_help_topics: could not read help topic file: .../topics.list -> parte 1 (tiene la frase de -c; read_help_topics
#                                                                          esta en [excluir], pero -c gana)
#     could not read help topic file: .../x.etab                        -> se quita (tiene la frase de -c, pero tambien etab de -e)
#     Error! Pid:1601606 ...                                            -> parte 2 (Error! esta en [conservar])
#     Error! GetTaskCol: Could not to find task column                  -> se quita (GetTaskCol esta en [excluir])
#     CuiExit: shutdown complete.                                       -> se quita (no tiene frase de -c ni de [conservar])
# Para dejar de ver algo siempre, borra su linea de [conservar] o ponle # adelante.

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


def nombre_de_salida(carpeta, nombre, fechas):
    '''NOMBRE DEL OUTPUT: <n>_<log>_filtrado_<fechas>.log
    1_process_bids_AMCUS_2129_filtrado_20260908_a_20261019.log
    2_process_bids_AMCUS_2129_filtrado_20260908.log
    SI YA HAY UN OUTPUT DEL MISMO LOG Y LAS MISMAS FECHAS, SE SOBREESCRIBE (CONSERVA SU NUMERO);
    SI NO, LLEVA EL SIGUIENTE NUMERO DE LA CARPETA'''
    rango = fechas[0].replace('-', '') + ('' if len(fechas) == 1 else '_a_' + fechas[-1].replace('-', ''))
    base = '%s_filtrado_%s.log' % (os.path.splitext(nombre)[0], rango)
    ultimo = 0
    for archivo in os.listdir(carpeta):
        numero = re.match(r'^(\d+)_(.+)$', archivo)
        if numero and numero.group(2) == base:
            return os.path.join(carpeta, archivo)
        if numero and NUMERADO.search(archivo):
            ultimo = max(ultimo, int(numero.group(1)))
    return os.path.join(carpeta, '%d_%s' % (ultimo + 1, base))


def frase_valida(frase):
    try:
        if frase.startswith(u're:'):
            re.compile(frase[3:])
        return True
    except re.error:
        print('Se omite la expresion regular invalida: %r' % frase, file=sys.stderr)
        return False


def filtrar(ruta, carpeta, usuario, comando, fechas_pedidas, conservar, excluir, mas_conservar, mas_excluir, inicial=None, final=None, bloque_con=()):
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
    contador = dict((frase, [0, 0, 0, 0]) for frase in adicionales) # veces, primera linea, ultima linea, quitadas por -e
    bloques = []  # [primera linea, ultima linea, tiene una frase de -bc]
    dentro = False
    ahora = time.localtime()
    salida = nombre_de_salida(carpeta, nombre, fechas)
    temporal_bloques, temporal_filtrado, temporal_frases = salida + '.bloques.tmp', salida + '.tmp', salida + '.frases.tmp'
    escritas, del_config, i, fecha, num = 0, 0, 0, None, 0
    with open(ruta, 'rb') as log, open(temporal_bloques, 'wb') as tmp_bloques, open(temporal_filtrado, 'wb') as tmp_filtrado, \
            open(temporal_frases, 'wb') as tmp_frases:
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
            encontradas = [f for f in adicionales if coincide(f, texto, minusculas)]
            for frase in encontradas:
                c = contador[frase]
                c[0], c[1], c[2] = c[0] + 1, c[1] or num, num
            de_c = [f for f in encontradas if f in mas_conservar]
            if de_c: # Linea de -c: va bajo el contador de su frase, salvo que tenga una frase de -e
                quitar = any(f in mas_excluir for f in encontradas)
                for frase in de_c:
                    if quitar:
                        contador[frase][3] += 1
                    else:
                        tmp_frases.write(b'%d %d ' % (adicionales.index(frase), num) + linea.rstrip(b'\r\n') + b'\n')
                escritas += not quitar
                continue # Ya se mostro (o la quito -e): no se repite en la seccion del .config
            if any(coincide(f, texto, minusculas) for f in conservar) and not any(coincide(f, texto, minusculas) for f in excluir):
                tmp_filtrado.write(b'%d ' % num + linea.rstrip(b'\r\n') + b'\n') # Frases default del .config (y -e)
                escritas += 1
                del_config += 1
    sin_final = bloques.pop() if dentro else None # El log termino antes de la linea final: ese bloque no se muestra

    '''ENCABEZADO: DATOS DEL LOG; DESPUES DE LOS BLOQUES (SI SE PIDIERON) VAN LAS FRASES Y SUS CONTADORES'''
    inicio = [u'LOG ["%s"] FILTRADO' % nombre,
              u'Generado por: %s el %s' % (usuario, time.strftime('%Y-%m-%d %H:%M:%S', ahora)),
              u'Comando: %s' % comando,
              u'Fechas: %s' % u', '.join(fechas),
              RAYA]
    lineas = [u'Conservar [%s]' % u', '.join(mas_conservar),
               u'Excluir [%s]' % u', '.join(mas_excluir),
               u'Las frases default de conservar y excluir se encuentran en %s' % CONFIG,
               RAYA]
    def contador_de(frase):
        veces, primera, ultima, quitadas = contador[frase]
        if veces == 0:
            texto = u'%s: No encontrado' % frase
        elif veces == 1:
            texto = u'%s: Encontrado 1 vez en la linea %d' % (frase, primera)
        else:
            texto = u'%s: Encontrado %d veces de la linea %d a la linea %d' % (frase, veces, primera, ultima)
        if quitadas:
            texto += u' (%d quitadas por -e)' % quitadas
        return (texto + u'\n').encode('utf-8')

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
        '''CADA FRASE ADICIONAL CON SU CONTADOR; DEBAJO DE LAS DE -c, SUS LINEAS CONSERVADAS: [linea del log] linea N'''
        for n, frase in enumerate(adicionales):
            archivo.write(contador_de(frase))
            if frase in mas_conservar:
                with open(temporal_frases, 'rb') as temporal:
                    for linea in temporal:
                        indice, numero, original = linea.split(b' ', 2)
                        if int(indice) == n:
                            archivo.write(original.rstrip(b'\n') + b' linea ' + numero + b'\n')
                archivo.write(b'\n')
        if adicionales:
            archivo.write((RAYA + '\n').encode('ascii'))
        '''DESPUES, LAS LINEAS DE LAS FRASES DEFAULT DEL .config (SIN LAS DE -c, QUE YA SALIERON ARRIBA)'''
        archivo.write((u'Frases default de %s: %d lineas\n' % (CONFIG, del_config)).encode('utf-8'))
        with open(temporal_filtrado, 'rb') as temporal:
            for linea in temporal:
                numero, original = linea.split(b' ', 1)
                archivo.write(original.rstrip(b'\n') + b' linea ' + numero + b'\n')
    os.remove(temporal_bloques)
    os.remove(temporal_filtrado)
    os.remove(temporal_frases)
    detalle = ' %d bloques |' % len([b for b in bloques if b[2]]) if inicial else ''
    print('%s: %s |%s %d lineas filtradas | %s' % (nombre, ', '.join(fechas), detalle, escritas, salida))

'''--delete: SOLO BORRA LOS OUTPUTS DE ESTE SCRIPT EN <carpeta actual>/<usuario>/. NUNCA LOS LOGS ORIGINALES NI EL .config'''
OUTPUT = re.compile(r'_filtrado_\d{8}(_a_\d{8})?\.log(\.bloques\.tmp|\.frases\.tmp|\.tmp)?$')


def borrar_salidas(carpeta):
    if not os.path.isdir(carpeta):
        print('No hay outputs que borrar: no existe %s' % carpeta)
        return
    archivos = sorted(a for a in os.listdir(carpeta) if OUTPUT.search(a) and os.path.isfile(os.path.join(carpeta, a))
                      and not os.path.islink(os.path.join(carpeta, a)))
    if not archivos:
        print('No hay outputs que borrar en %s' % carpeta)
        return
    for archivo in archivos:
        print('  ' + archivo)
    if not sys.stdin.isatty():
        print('Sin terminal no se borra nada: corre --delete desde una terminal para confirmar')
        return
    print('Se borraran %d outputs de %s (los logs originales y %s no se tocan). Escribe s para confirmar: '
          % (len(archivos), carpeta, CONFIG), end='')
    sys.stdout.flush()
    if sys.stdin.readline().strip().lower() not in ('s', 'si', 'y', 'yes'):
        print('No se borro nada.')
        return
    for archivo in archivos:
        os.remove(os.path.join(carpeta, archivo))
    print('%d outputs borrados.' % len(archivos))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Filtra un log por fecha y por palabras clave. Escribe el resultado en <carpeta actual>/<usuario>/.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''ejemplo completo:
  python filtrar_log.py process_bids.log --fecha 2026-10-19 --fecha 2026-10-20 \\
      --conservar "Cannot create gt" --conservar "re:LIMO\\+$" --excluir "Setting baseURL"

  - Toma solo las corridas que empezaron el 19 y el 20 de octubre (sin --fecha: menu para elegirlas).
  - Primero, bajo su contador, las lineas con "Cannot create gt" o que terminan en "LIMO+" (-c),
    sin las que tambien tienen "Setting baseURL" (-e). Sin -e salen todas.
  - Despues, las lineas de [conservar] del .config, sin las de [excluir] ni las de -e (sin repetir las de -c).
  - Cada linea va tal cual del log, seguida de: linea N
  - Escribe <usuario>/1_process_bids_filtrado_20261019_a_20261020.log con este encabezado
    (mismo log y mismas fechas: se sobreescribe; fechas distintas: siguiente numero):

      LOG ["process_bids.log"] FILTRADO
      Generado por: usuario el 2026-11-21 17:19:00
      Comando: python filtrar_log.py process_bids.log --fecha 2026-10-19 ...
      Fechas: 2026-10-19, 2026-10-20
      -------------------------------------------------------------------------
      Conservar [Cannot create gt, re:LIMO\\+$]
      Excluir [Setting baseURL]
      Las frases default de conservar y excluir se encuentran en filtrar_log.config
      -------------------------------------------------------------------------
      Cannot create gt: Encontrado 452 veces de la linea 1350 a la linea 74419
      (cada linea con "Cannot create gt", tal cual del log, seguida de: linea N)

      re:LIMO\\+$: Encontrado 452 veces de la linea 1350 a la linea 74419
      (cada linea que termina en "LIMO+", seguida de: linea N)

      Setting baseURL: Encontrado 474 veces de la linea 647 a la linea 75430
      -------------------------------------------------------------------------
      Frases default de filtrar_log.config: 30 lineas
      Error! Pid:1601606  Mon Oct 19 14:04:00 2026  User:amxcrewbidsvc linea 2149
      ...

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

borrar outputs:
  python filtrar_log.py --delete
  - Borra los outputs de este script en <usuario>/ despues de pedir confirmacion (s).
  - No toca los logs originales ni filtrar_log.config. Sin terminal no borra nada.

forma corta: -f es --fecha, -c es --conservar, -e es --excluir. El mismo ejemplo:
  python filtrar_log.py process_bids.log -f 2026-10-19 -f 2026-10-20 -c "Cannot create gt" -c "re:LIMO\\+$" -e "Setting baseURL"

frases: sin distinguir mayusculas; con el prefijo re: son expresion regular.
Solo se muestran las lineas con una frase de -c o de [conservar]; si tambien tienen una de excluir, se quitan.
Una frase de -c gana a [excluir] del .config; solo -e la quita. Si -e quita lineas de una frase de -c,
el contador lo dice: (N quitadas por -e).
Las frases default estan en <usuario>/filtrar_log.config; se crea la primera vez.''')
    parser.add_argument('logs', nargs='*', help='uno o mas logs')
    parser.add_argument('--delete', action='store_true',
                        help='borra todos los outputs de este script en <carpeta actual>/<usuario>/ (pide confirmacion); '
                             'no toca los logs originales ni el .config')
    parser.add_argument('-f', '--fecha', action='append', default=[], help='AAAA-MM-DD; se puede repetir. Sin -f sale un menu (Enter = ultimas 3; sin terminal, como en cron, toma las ultimas 3)')
    parser.add_argument('-c', '--conservar', action='append', default=[], help='frase de las lineas que se muestran; se puede repetir')
    parser.add_argument('-li', '--linea-inicial', help='fragmento de la linea donde empieza cada bloque (con -lf)')
    parser.add_argument('-lf', '--linea-final', help='fragmento de la linea donde termina cada bloque (con -li)')
    parser.add_argument('-bc', '--bloque-con', action='append', default=[],
                        help='solo muestra los bloques de -li/-lf que tienen esta frase; se puede repetir (basta una)')
    parser.add_argument('-e', '--excluir', action='append', default=[], help='quita las lineas que la tengan, aunque tengan una de conservar; se puede repetir')
    args = parser.parse_args()
    if args.delete:
        try:
            borrar_salidas(os.path.join(os.getcwd(), getpass.getuser()))
        except KeyboardInterrupt:
            print('\nCancelado.')
        sys.exit(0)
    if not args.logs:
        parser.error('indica uno o mas logs (o --delete para borrar los outputs)')
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
    comando = u' '.join([u'python', os.path.basename(argumento(sys.argv[0]))] +
                        [u'"%s"' % x if (u' ' in x or not x) else x for x in map(argumento, sys.argv[1:])])
    try:
        for ruta in args.logs:
            if not os.path.isfile(ruta):
                print('%s: no existe, se omite' % ruta)
                continue
            filtrar(ruta, carpeta, usuario, comando, [argumento(f) for f in args.fecha], conservar, excluir, mas_conservar, mas_excluir,
                    inicial, final, bloque_con)
    except KeyboardInterrupt: # Ctrl-C en el menu o mientras filtra
        print('\nCancelado.')
