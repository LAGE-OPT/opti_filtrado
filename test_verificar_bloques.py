# -*- coding: utf-8 -*-
# (Python 2.7, sin librerias externas para que se pueda ejecutar en los servidores de AMX)
# Uso: python test_verificar_bloques.py      (en la misma carpeta que verificar_bloques.py)
from __future__ import print_function
import sys
import unittest

try:
    from StringIO import StringIO  # Python 2.7
except ImportError:
    from io import StringIO        # Python 3

import verificar_bloques as vb

'''
PRUEBAS DE verificar_bloques.py. LOS LOGS SE ARMAN EN MEMORIA (LISTAS DE LINEAS), NO SE CREA NINGUN ARCHIVO.
LAS LINEAS DE CADA CORRIDA SON COPIAS RECORTADAS DE LAS QUE APARECEN EN LOS LOGS REALES.
'''

'''LINEAS DE UNA CORRIDA DE BIDS COMPLETA, EN EL MISMO ORDEN QUE EN process_bids.log'''
def corrida_bids(hora='20261019_140011', subplan='202611/CCR-787/1.PRODUCCION/999.pubcb_71.CREW-BID4_19101018',
                 quitar=(), sin_cierre=False):
    lineas = [
        '',
        subplan,
        '',
        'Running script with settings',
        'SCRIPT_RUN_DETACHED       =  true',
        'SCRIPT_ERR_MARK_FILE      =  /opt/x/logfiles/bid_processing_orchestrator.py/%s.mark' % hora,
        'SCRIPT_SUBPLANS           =  %s' % subplan,
        'Studio PID: 1600621',
        'cslDispatcher: dispatching PythonRunFile("InitMenuState.py")',
        'Time: 20261019 14:00:17',
        'cslDispatcher: dispatching PythonRunFile("/opt/x/carmusr/lib/python/carmusr/crew_modules/bid/bid_processing_orchestrator.py")',
        'LEG AM 8592  1   7     04Oct2026 : (Trip    25218) Not operating created.',
        'CpmExit: done',
        'CuiExit: shutdown complete.',
        '===== UPLOADING DATA SUCCESSFUL =====',
        'SCRIPT_RUN_TYPE = prod',
        'Subplans to process:',
        subplan,
        'Opening plan: %s' % subplan,
        'Removing marker file /opt/x/logfiles/bid_processing_orchestrator.py/%s.mark' % hora,
    ]
    if sin_cierre:
        quitar = tuple(quitar) + ('CuiExit: shutdown complete.',)
    return [l for l in lineas if not any(l.startswith(q) for q in quitar)]


'''LINEAS DE UNA CORRIDA DE REPORTE (nohup.out), SEPARADAS EN INICIO Y CIERRE PARA PODER ENCIMARLAS'''
def inicio_reporte(subplan='202611/CCR-787/1.PRODUCCION/913.MAX_ROSTER_auto/best_solution', hora='20261019 14:02:15'):
    return [
        'Running script with settings',
        'SCRIPT_RUN_DETACHED       =  true',
        'Studio PID: 1601231',
        'Time: %s' % hora,
        'cslDispatcher: dispatching PythonRunFile("/opt/x/carmusr/lib/python/carmusr/crew_modules/'
        'pbs_aut_opt_helper/opt_aut_report.py","%s","filtro")' % subplan,
    ]


def cierre_reporte():
    return ['CpmExit: done', 'CuiExit: shutdown complete.']


'''CONVIERTE UNA LISTA DE TEXTOS EN LINEAS DE BYTES CON SALTO, COMO LAS DE UN ARCHIVO ABIERTO EN 'rb' '''
def a_bytes(lineas, salto_final=True):
    datos = [(l + '\n').encode('latin-1') for l in lineas]
    if datos and not salto_final:
        datos[-1] = datos[-1].rstrip(b'\n')
    return datos


'''ATAJO: ANALIZA UN LOG Y DEVUELVE CORRIDAS, ESTADOS Y LOS PROBLEMAS DEL ARCHIVO'''
def analizar(lineas, salto_final=True):
    corridas, huerfanos, nul, sin_salto = vb.leer_corridas(a_bytes(lineas, salto_final))
    estados = [vb.evaluar(c, i == len(corridas) - 1) for i, c in enumerate(corridas)]
    return corridas, estados, huerfanos, nul, sin_salto


'''ATAJO: EJECUTA reportar() CAPTURANDO LO QUE IMPRIME'''
def reportar(lineas, todas=False, salto_final=True):
    salida_original, sys.stdout = sys.stdout, StringIO()
    try:
        problemas = vb.reportar('prueba.log', a_bytes(lineas, salto_final), todas)
        return problemas, sys.stdout.getvalue()
    finally:
        sys.stdout = salida_original


class PruebasBids(unittest.TestCase):

    '''CORRIDA DE BIDS CON TODAS SUS MARCAS: COMPLETA'''
    def test_corrida_completa(self):
        corridas, estados, huerfanos, nul, sin_salto = analizar(corrida_bids())
        self.assertEqual(len(corridas), 1)
        self.assertEqual(estados[0], ('COMPLETA', []))
        self.assertEqual(corridas[0]['tipo'], 'BIDS')
        self.assertEqual((huerfanos, nul, sin_salto), ([], 0, False))

    '''CADA MARCA OBLIGATORIA, QUITADA UNA POR UNA: INCOMPLETA Y FALTA SOLO ESA'''
    def test_falta_cada_marca_por_separado(self):
        for marca in vb.MARCAS_BIDS:
            texto = marca.decode('latin-1')
            corridas, estados, _, _, _ = analizar(corrida_bids(quitar=(texto,)))
            self.assertEqual(estados[0][0], 'INCOMPLETA', texto)
            self.assertEqual(estados[0][1], [texto.strip()], texto)

    '''SIN "UPLOADING DATA SUCCESSFUL": SIN_EXITO (NO INCOMPLETA)'''
    def test_sin_mensaje_de_exito(self):
        _, estados, _, _, _ = analizar(corrida_bids(quitar=('===== UPLOADING',)))
        self.assertEqual(estados[0][0], 'SIN_EXITO')

    '''SI FALTA UNA MARCA Y TAMBIEN EL EXITO, GANA INCOMPLETA'''
    def test_incompleta_tiene_prioridad_sobre_sin_exito(self):
        _, estados, _, _, _ = analizar(corrida_bids(quitar=('===== UPLOADING', 'Opening plan')))
        self.assertEqual(estados[0], ('INCOMPLETA', ['Opening plan:']))

    '''SE PIERDE TODA LA SALIDA DE PYTHON (LO QUE LLEGA DESPUES DE CuiExit)'''
    def test_sin_salida_de_python(self):
        python = ('===== UPLOADING', 'SCRIPT_RUN_TYPE', 'Subplans to process', 'Opening plan', 'Removing marker')
        _, estados, _, _, _ = analizar(corrida_bids(quitar=python))
        self.assertEqual(estados[0][0], 'INCOMPLETA')
        self.assertEqual(estados[0][1], ['SCRIPT_RUN_TYPE =', 'Subplans to process:', 'Opening plan:', 'Removing marker file'])

    '''LA ULTIMA CORRIDA SIN CIERRE: INCOMPLETA, PERO PUEDE SEGUIR EN CURSO'''
    def test_ultima_sin_cierre(self):
        log = corrida_bids() + corrida_bids(hora='20261019_140128', sin_cierre=True)
        _, estados, _, _, _ = analizar(log)
        self.assertEqual(estados[0][0], 'COMPLETA')
        self.assertEqual(estados[1][0], 'INCOMPLETA')
        self.assertIn(vb.FALTA_CIERRE_ULTIMA, estados[1][1])

    '''CORRIDA SIN CIERRE A MITAD DEL LOG: SOLO ESA ES INCOMPLETA, NO LE ROBA EL CIERRE A LA SIGUIENTE'''
    def test_sin_cierre_a_mitad_del_log(self):
        log = corrida_bids() + corrida_bids(hora='20261019_140128', sin_cierre=True) + corrida_bids(hora='20261019_140318')
        corridas, estados, huerfanos, _, _ = analizar(log)
        self.assertEqual([e[0] for e in estados], ['COMPLETA', 'INCOMPLETA', 'COMPLETA'])
        self.assertEqual(estados[1][1], [vb.FALTA_CIERRE_INTERRUMPIDA])
        self.assertFalse(any(c['encimada'] for c in corridas))
        self.assertEqual(huerfanos, [])

    '''CORRIDA CORTADA DE GOLPE: SOLO QUEDA EL INICIO'''
    def test_corrida_cortada_al_inicio(self):
        log = corrida_bids() + corrida_bids(hora='20261019_140128')[:6]
        _, estados, _, _, _ = analizar(log)
        self.assertEqual(estados[1][0], 'INCOMPLETA')
        self.assertIn(vb.FALTA_CIERRE_ULTIMA, estados[1][1])
        self.assertIn('CpmExit: done', estados[1][1])

    '''CORTADA ANTES DE LLEGAR AL COMANDO Y SEGUIDA DE OTRA: SE RECONOCE COMO BIDS POR EL ENCABEZADO, NO COMO ENCIMADA'''
    def test_cortada_antes_del_comando_seguida_de_otra(self):
        log = corrida_bids(hora='20261019_140128')[:6] + corrida_bids(hora='20261019_140318')
        corridas, estados, _, _, _ = analizar(log)
        self.assertEqual(corridas[0]['tipo'], 'BIDS')
        self.assertEqual(estados[0][0], 'INCOMPLETA')
        self.assertIn(vb.FALTA_CIERRE_INTERRUMPIDA, estados[0][1])
        self.assertEqual(estados[1][0], 'COMPLETA')
        self.assertFalse(any(c['encimada'] for c in corridas))

    '''STUDIO 28 (gam_usr_prod_no_interbids) NO ESCRIBE "Studio PID:" NI Hostname/Username: LA CORRIDA ES COMPLETA'''
    def test_studio_28_sin_bloque_de_pid(self):
        log = [l if not l.startswith('Studio PID:') else '        20220908-13:10 Studio, 28.14.57142' for l in corrida_bids()]
        log.insert(log.index('Running script with settings') + 1, '_XSERVTransMakeAllCOTSServerListeners: server already running')
        self.assertFalse(any(l.startswith('Studio PID') for l in log))
        _, estados, _, _, _ = analizar(log)
        self.assertEqual(estados[0], ('COMPLETA', []))

    '''SUBPLAN Y HORA SE TOMAN DEL ENCABEZADO Y SE MUESTRAN EN FORMATO Mon Oct 19 14:00:11 2026'''
    def test_subplan_y_hora(self):
        corridas, _, _, _, _ = analizar(corrida_bids())
        self.assertEqual(corridas[0]['subplan'], '202611/CCR-787/1.PRODUCCION/999.pubcb_71.CREW-BID4_19101018')
        self.assertEqual(corridas[0]['hora'], 'Mon Oct 19 14:00:11 2026')

    '''VARIAS CORRIDAS SEGUIDAS: CADA UNA SE NUMERA Y SE EVALUA POR SEPARADO'''
    def test_varias_corridas(self):
        log = corrida_bids() + corrida_bids(hora='20261019_140128', quitar=('Opening plan',)) + corrida_bids(hora='20261019_140318')
        corridas, estados, _, _, _ = analizar(log)
        self.assertEqual([c['numero'] for c in corridas], [1, 2, 3])
        self.assertEqual([e[0] for e in estados], ['COMPLETA', 'INCOMPLETA', 'COMPLETA'])


class PruebasReportes(unittest.TestCase):

    '''REPORTE COMPLETO: SE IDENTIFICA EL TIPO Y EL SUBPLAN, Y NO SE LE PIDEN LAS MARCAS DE BIDS'''
    def test_reporte_completo(self):
        corridas, estados, _, _, _ = analizar(inicio_reporte() + cierre_reporte())
        self.assertEqual(corridas[0]['tipo'], 'opt_aut_report.py')
        self.assertEqual(corridas[0]['subplan'], '202611/CCR-787/1.PRODUCCION/913.MAX_ROSTER_auto/best_solution')
        self.assertEqual(corridas[0]['hora'], 'Mon Oct 19 14:02:15 2026')
        self.assertEqual(estados[0], ('COMPLETA', []))

    '''DOS REPORTES ENCIMADOS (INICIO, INICIO, CIERRE, CIERRE): AMBOS COMPLETOS Y MARCADOS COMO ENCIMADOS'''
    def test_reportes_encimados(self):
        log = inicio_reporte() + inicio_reporte(hora='20261019 14:04:30') + cierre_reporte() + cierre_reporte()
        corridas, estados, huerfanos, _, _ = analizar(log)
        self.assertEqual([e[0] for e in estados], ['COMPLETA', 'COMPLETA'])
        self.assertTrue(all(c['encimada'] for c in corridas))
        self.assertEqual(huerfanos, [])

    '''UN REPORTE QUE NO SE ENCIMA CON NADIE NO SE MARCA COMO ENCIMADO'''
    def test_reportes_seguidos_no_encimados(self):
        log = inicio_reporte() + cierre_reporte() + inicio_reporte(hora='20261019 14:04:30') + cierre_reporte()
        corridas, _, _, _, _ = analizar(log)
        self.assertFalse(any(c['encimada'] for c in corridas))

    '''REPORTES ENCIMADOS Y FALTA UN CIERRE: QUEDA UNA SOLA INCOMPLETA (LA ULTIMA ABIERTA)'''
    def test_reportes_encimados_falta_un_cierre(self):
        log = inicio_reporte() + inicio_reporte(hora='20261019 14:04:30') + cierre_reporte()
        _, estados, _, _, _ = analizar(log)
        self.assertEqual([e[0] for e in estados], ['COMPLETA', 'INCOMPLETA'])

    '''LOG MEZCLADO: UNA CORRIDA DE BIDS ABIERTA NO SE CONFUNDE CON UN REPORTE ENCIMADO'''
    def test_bids_abierta_seguida_de_reporte(self):
        log = corrida_bids(sin_cierre=True) + inicio_reporte() + cierre_reporte()
        corridas, estados, _, _, _ = analizar(log)
        self.assertEqual(estados[0], ('INCOMPLETA', [vb.FALTA_CIERRE_INTERRUMPIDA]))
        self.assertEqual(estados[1][0], 'COMPLETA')

    '''CORRIDA SIN COMANDO DE crew_modules: TIPO "?" Y SOLO SE REVISA EL CIERRE'''
    def test_tipo_desconocido(self):
        log = ['Running script with settings', 'Studio PID: 1', 'cslDispatcher: dispatching PythonRunFile("InitMenuState.py")',
               'CuiExit: shutdown complete.']
        corridas, estados, _, _, _ = analizar(log)
        self.assertEqual(corridas[0]['tipo'], '?')
        self.assertEqual(estados[0][0], 'COMPLETA')


class PruebasArchivo(unittest.TestCase):

    '''LOG VACIO: NINGUNA CORRIDA Y NINGUN PROBLEMA'''
    def test_log_vacio(self):
        corridas, _, huerfanos, nul, sin_salto = analizar([])
        self.assertEqual((corridas, huerfanos, nul, sin_salto), ([], [], 0, False))
        self.assertEqual(reportar([])[0], 0)

    '''LINEAS ANTES DE LA PRIMERA CORRIDA (EL SUBPLAN Y LINEAS EN BLANCO) SE IGNORAN'''
    def test_lineas_antes_del_primer_inicio(self):
        corridas, _, huerfanos, _, _ = analizar(['', '', 'texto suelto'] + corrida_bids())
        self.assertEqual(len(corridas), 1)
        self.assertEqual(huerfanos, [])

    '''EL LOG EMPIEZA A MITAD DE UNA CORRIDA: CIERRE SIN INICIO'''
    def test_cierre_sin_inicio(self):
        log = corrida_bids()[10:] + corrida_bids(hora='20261019_140128')
        corridas, estados, huerfanos, _, _ = analizar(log)
        self.assertEqual(len(huerfanos), 1)
        self.assertEqual(len(corridas), 1)
        self.assertEqual(estados[0][0], 'COMPLETA')

    '''BYTES NULOS (ARCHIVO VACIADO MIENTRAS OTRO ESCRIBIA)'''
    def test_bytes_nulos(self):
        _, _, _, nul, _ = analizar(['\x00' * 50] + corrida_bids())
        self.assertEqual(nul, 1)

    '''ULTIMA LINEA SIN SALTO (ESCRITURA CORTADA A MITAD DE LINEA)'''
    def test_ultima_linea_sin_salto(self):
        self.assertTrue(analizar(corrida_bids(), salto_final=False)[4])
        self.assertFalse(analizar(corrida_bids(), salto_final=True)[4])


class PruebasAcceso(unittest.TestCase):

    '''SOLO SE ACEPTAN LOGS DENTRO DE LAS CARPETAS PERMITIDAS (NO SE ABRE NINGUN ARCHIVO EN ESTAS PRUEBAS)'''
    def setUp(self):
        self.originales = vb.CARPETAS_PERMITIDAS
        vb.CARPETAS_PERMITIDAS = ['/opt/logs_prueba']

    def tearDown(self):
        vb.CARPETAS_PERMITIDAS = self.originales

    def test_por_defecto_solo_la_carpeta_desde_donde_se_ejecuta(self):
        import os
        self.assertEqual(self.originales, [os.getcwd()])

    def test_extensiones_aceptadas(self):
        vb.CARPETAS_PERMITIDAS = ['/opt/logs_prueba']
        for nombre in ('a.log', 'a.out', 'a.txt', 'a.log.gz', 'a.out.gz', 'a.txt.gz', 'a.zip', 'A.LOG'):
            self.assertIn('no existe', vb.validar_ruta('/opt/logs_prueba/' + nombre), nombre)
        for nombre in ('a.py', 'a.gz', 'a.tar', 'a.log.bz2'):
            self.assertIn('no es un log', vb.validar_ruta('/opt/logs_prueba/' + nombre), nombre)

    def test_fuera_de_la_carpeta(self):
        self.assertIn('fuera de las carpetas', vb.validar_ruta('/etc/passwd'))

    def test_no_se_puede_salir_con_puntos(self):
        self.assertIn('fuera de las carpetas', vb.validar_ruta('/opt/logs_prueba/../../etc/passwd.log'))

    def test_carpeta_con_nombre_parecido(self):
        self.assertIn('fuera de las carpetas', vb.validar_ruta('/opt/logs_prueba_falsa/process_bids.log'))

    def test_extension_no_permitida(self):
        self.assertIn('no es un log', vb.validar_ruta('/opt/logs_prueba/config.py'))

    def test_log_que_no_existe(self):
        self.assertIn('no existe', vb.validar_ruta('/opt/logs_prueba/no_existe.log'))

    def test_dispositivo_no_es_archivo_normal(self):
        vb.CARPETAS_PERMITIDAS = ['/dev']
        self.assertIsNotNone(vb.validar_ruta('/dev/null.log'))
        self.assertIsNotNone(vb.validar_ruta('/dev/zero'))


class PruebasDatosDelCliente(unittest.TestCase):

    '''LAS SECUENCIAS DE ESCAPE Y CARACTERES DE CONTROL DEL LOG NO LLEGAN A LA CONSOLA'''
    def test_limpiar(self):
        self.assertEqual(vb.limpiar(u'abc/123_X.Y'), u'abc/123_X.Y')
        self.assertEqual(vb.limpiar(u'a\x1b[2Jb'), u'a?[2Jb')
        self.assertEqual(vb.limpiar(u'a\x9b31mb\x07'), u'a?31mb?')
        self.assertEqual(vb.limpiar(u'Producci\xf3n'), u'Producci?n')

    def test_subplan_con_escape_en_el_reporte(self):
        log = corrida_bids(subplan='202611/CCR\x1b]0;hackeado\x07/1.PRODUCCION')
        _, texto = reportar(log, todas=True)
        self.assertNotIn('\x1b', texto)
        self.assertNotIn('\x07', texto)
        self.assertIn('202611/CCR?]0;hackeado?/1.PRODUCCION', texto)


class PruebasComprimidos(unittest.TestCase):

    '''LOS .gz Y .zip SE LEEN DIRECTAMENTE, SIN DESCOMPRIMIR EN DISCO'''
    def contenido(self):
        return b''.join(a_bytes(corrida_bids() + corrida_bids(hora='20261019_140128')))

    def corridas_de(self, nombre, archivo):
        logs = vb.abrir_logs(nombre, archivo)
        return [(n, len(vb.leer_corridas(vb.lineas_del_archivo(abrir()))[0])) for n, abrir in logs]

    def test_gz(self):
        import gzip
        from io import BytesIO
        memoria = BytesIO()
        with gzip.GzipFile(fileobj=memoria, mode='wb') as comprimido:
            comprimido.write(self.contenido())
        memoria.seek(0)
        self.assertEqual(self.corridas_de('caso/process_bids.log.gz', memoria), [('caso/process_bids.log.gz', 2)])

    def test_zip_con_varios_logs_y_otros_archivos(self):
        import zipfile
        from io import BytesIO
        memoria = BytesIO()
        comprimido = zipfile.ZipFile(memoria, 'w')
        comprimido.writestr('process_bids.log', self.contenido())
        comprimido.writestr('logs/nohup.out', b''.join(a_bytes(inicio_reporte() + cierre_reporte())))
        comprimido.writestr('captura.png', b'no es un log')
        comprimido.close()
        memoria.seek(0)
        self.assertEqual(self.corridas_de('caso.zip', memoria),
                         [('caso.zip:process_bids.log', 2), ('caso.zip:logs/nohup.out', 1)])

    def test_zip_sin_logs(self):
        import zipfile
        from io import BytesIO
        memoria = BytesIO()
        comprimido = zipfile.ZipFile(memoria, 'w')
        comprimido.writestr('captura.png', b'no es un log')
        comprimido.close()
        memoria.seek(0)
        self.assertEqual(vb.abrir_logs('caso.zip', memoria), [])

    def test_log_normal_no_se_toca(self):
        from io import BytesIO
        memoria = BytesIO(self.contenido())
        self.assertEqual(self.corridas_de('process_bids.log', memoria), [('process_bids.log', 2)])


class PruebasConfigLogs(unittest.TestCase):

    '''ruta_logs EN EL .config DEL USUARIO (SE PASA EL TEXTO, NO SE LEE NINGUN ARCHIVO)'''
    CONFIG = ('[general]\n# ruta_logs: carpeta donde estan los logs\nruta_logs = %s\nusuario=luigar\n'
              'fecha_seleccionada=2026-10-20\n\n[process_bids.log]\nfechas=2026-10-20\nruta_logs = /no/debe/usarse\n')

    def test_ruta_vacia(self):
        self.assertIsNone(vb.leer_ruta_logs(self.CONFIG % ''))

    def test_ruta_con_valor(self):
        import os
        self.assertEqual(vb.leer_ruta_logs(self.CONFIG % '/opt/logs_prueba '), os.path.abspath('/opt/logs_prueba'))

    def test_solo_cuenta_la_seccion_general(self):
        texto = '[general]\nusuario=luigar\n\n[process_bids.log]\nruta_logs = /no/debe/usarse\n'
        self.assertIsNone(vb.leer_ruta_logs(texto))

    def test_formato_anterior_sin_seccion(self):
        self.assertIsNone(vb.leer_ruta_logs('usuario=luigar\ngenerado=2026-11-13\n\n[a.log]\nfechas=x\n'))

    def test_comentario_no_cuenta(self):
        self.assertIsNone(vb.leer_ruta_logs('[general]\n# ruta_logs = /opt/comentada\n'))

    def test_ruta_con_variable_de_entorno(self):
        import os
        os.environ['CARPETA_PRUEBA_LOGS'] = '/opt/desde_variable'
        try:
            self.assertEqual(vb.leer_ruta_logs(self.CONFIG % '$CARPETA_PRUEBA_LOGS/casos'),
                             os.path.abspath('/opt/desde_variable/casos'))
        finally:
            del os.environ['CARPETA_PRUEBA_LOGS']

    def test_config_en_la_carpeta_del_usuario(self):
        import os, getpass
        self.assertEqual(vb.ruta_config_usuario(), os.path.join(os.getcwd(), getpass.getuser(), 'fecha_seleccionada.config'))

    def test_resolver_log(self):
        import os
        self.assertEqual(vb.resolver_log('process_bids.log', None), 'process_bids.log')
        self.assertEqual(vb.resolver_log('no_existe.log', '/opt/logs'), os.path.join('/opt/logs', 'no_existe.log'))
        self.assertEqual(vb.resolver_log('/otra/ruta/a.log', '/opt/logs'), '/otra/ruta/a.log')
        self.assertEqual(vb.resolver_log('.', '/opt/no_existe'), '.') # Existe desde donde se ejecuta: se usa ese


class PruebasLimiteDeLinea(unittest.TestCase):

    '''UNA LINEA ENORME SE LEE EN PEDAZOS; LAS CORRIDAS SE SIGUEN DETECTANDO'''
    def test_linea_gigante_de_nulos(self):
        from io import BytesIO
        limite_original, vb.LIMITE_LINEA = vb.LIMITE_LINEA, 100
        try:
            datos = b'\x00' * 1000 + b'\n' + b''.join(a_bytes(corrida_bids()))
            lineas = list(vb.lineas_del_archivo(BytesIO(datos)))
            self.assertTrue(all(len(l) <= 100 for l in lineas))
            corridas, _, nul, _ = vb.leer_corridas(lineas)
            self.assertEqual(len(corridas), 1)
            self.assertEqual(nul, 10)
        finally:
            vb.LIMITE_LINEA = limite_original


class PruebasReporte(unittest.TestCase):

    '''SIN PROBLEMAS: DEVUELVE 0 Y NO LISTA CORRIDAS'''
    def test_sin_problemas(self):
        problemas, texto = reportar(corrida_bids())
        self.assertEqual(problemas, 0)
        self.assertIn('Completas            : 1', texto)
        self.assertNotIn('#1', texto)

    '''CON --todas TAMBIEN LISTA LAS COMPLETAS'''
    def test_opcion_todas(self):
        _, texto = reportar(corrida_bids(), todas=True)
        self.assertIn('#1', texto)
        self.assertIn('COMPLETA', texto)

    '''CADA TIPO DE PROBLEMA SUMA AL CONTADOR QUE DECIDE EL CODIGO DE SALIDA'''
    def test_cuenta_de_problemas(self):
        self.assertEqual(reportar(corrida_bids(sin_cierre=True))[0], 1)                     # corrida incompleta
        self.assertEqual(reportar(corrida_bids()[10:] + corrida_bids())[0], 1)               # cierre sin inicio
        self.assertEqual(reportar(['\x00'] + corrida_bids())[0], 1)                          # bytes nulos
        self.assertEqual(reportar(corrida_bids(), salto_final=False)[0], 1)                  # sin salto final
        self.assertEqual(reportar(corrida_bids(quitar=('===== UPLOADING',)))[0], 0)          # SIN_EXITO no cuenta como problema

    '''LAS INCOMPLETAS MUESTRAN LO QUE LES FALTA'''
    def test_detalle_de_faltantes(self):
        _, texto = reportar(corrida_bids(quitar=('Opening plan',)))
        self.assertIn('INCOMPLETA', texto)
        self.assertIn('falta: Opening plan:', texto)


if __name__ == '__main__':
    unittest.main(verbosity=2)
