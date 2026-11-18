# -*- coding: utf-8 -*-
# (Python 2.7 y 3, sin librerias externas)
# Uso: python test_palabras_clave.py      (en la misma carpeta que palabras_clave.py y leer_logs.py)
from __future__ import print_function
import unittest

import palabras_clave as pc

'''
PRUEBAS DE LA LECTURA DE [filtros] Y DE LOS PATRONES DE palabras_clave.py. NO SE CREA NINGUN ARCHIVO.
'''

'''UN .config COMO EL QUE ESCRIBE leer_logs.py, CON LA SECCION [filtros] QUE LLENA EL USUARIO'''
def config_con_filtros(filtros):
    return ('[general]\n'
            'ruta_logs = \n'
            'usuario=soporte\n'
            '\n'
            '[/logs/process_bids.log]\n'
            'fechas=2026-10-06\n'
            'log_exportado=/home/soporte/process_bids_20261006.log\n'
            'lineas=100\n'
            '\n'
            '[filtros]\n'
            '# Una frase por linea, debajo de conservar = o excluir =. * significa cualquier texto intermedio.\n'
            + filtros)


def filtros(texto):
    return pc.leer_config(config_con_filtros(texto))['filtros']


class PruebasLeerConfig(unittest.TestCase):

    '''EL ERROR ORIGINAL: LAS FRASES SIN SANGRIA ROMPIAN configparser'''
    def test_frases_sin_sangria(self):
        f = filtros('conservar = Error!\nResponse code*200\nexcluir = LEG AM\nrave\n')
        self.assertEqual(f['conservar'], 'Error!\nResponse code*200')
        self.assertEqual(f['excluir'], 'LEG AM\nrave')

    '''CON SANGRIA (FORMATO DE configparser) SIGUE FUNCIONANDO IGUAL'''
    def test_frases_con_sangria(self):
        f = filtros('conservar = Error!\n    Response code*200\nexcluir = LEG AM\n    rave\n')
        self.assertEqual(f['conservar'], 'Error!\nResponse code*200')
        self.assertEqual(f['excluir'], 'LEG AM\nrave')

    '''TODAS LAS FRASES DEBAJO DE LA CLAVE, SIN NADA EN SU MISMA LINEA'''
    def test_clave_vacia_y_frases_abajo(self):
        f = filtros('conservar =\nError!\nTraceback\nexcluir =\n')
        self.assertEqual(f['conservar'], '\nError!\nTraceback')
        self.assertEqual(f['excluir'], '')
        self.assertEqual(len(pc.preparar_patrones(f['conservar'])), 2)

    '''UNA FRASE CON "=" O ":" NO SE CONFUNDE CON UNA CLAVE NUEVA'''
    def test_frase_con_igual_y_dos_puntos(self):
        f = filtros('conservar = SCRIPT_RUN_TYPE = prod\nResponse code from server: 200\nexcluir =\n')
        self.assertEqual(f['conservar'], 'SCRIPT_RUN_TYPE = prod\nResponse code from server: 200')

    '''LOS COMENTARIOS Y LAS LINEAS VACIAS DENTRO DE [filtros] NO SON FRASES'''
    def test_comentarios_y_lineas_vacias(self):
        f = filtros('conservar = Error!\n\n# esto no es frase\n; esto tampoco\nTraceback\nexcluir =\n')
        self.assertEqual(f['conservar'], 'Error!\nTraceback')

    '''LA SECCION DE CADA LOG SIGUE DANDO SU log_exportado'''
    def test_secciones_de_logs(self):
        config = pc.leer_config(config_con_filtros('conservar =\nexcluir =\n'))
        self.assertEqual(config['/logs/process_bids.log']['log_exportado'], '/home/soporte/process_bids_20261006.log')
        self.assertEqual(config['general']['usuario'], 'soporte')

    '''[FILTROS] EN MAYUSCULAS TAMBIEN CUENTA (leer_logs.py LA BUSCA SIN IMPORTAR MAYUSCULAS)'''
    def test_seccion_en_mayusculas(self):
        config = pc.leer_config('[FILTROS]\nConservar = Error!\n')
        self.assertEqual(config['filtros']['conservar'], 'Error!')

    '''SIN [filtros] NO HAY SECCION; LAS LINEAS ANTES DE LA PRIMERA SECCION SE IGNORAN'''
    def test_sin_filtros(self):
        config = pc.leer_config('suelta = 1\n[general]\nusuario=soporte\n')
        self.assertNotIn('filtros', config)
        self.assertEqual(list(config), ['general'])


class PruebasPatrones(unittest.TestCase):

    '''EL * ACEPTA CUALQUIER TEXTO INTERMEDIO Y NO IMPORTAN MAYUSCULAS'''
    def test_comodin_y_mayusculas(self):
        patrones = pc.preparar_patrones('response code*200')
        self.assertTrue(pc.coincide(b'Response code from server: 200\n', patrones))
        self.assertFalse(pc.coincide(b'Response code from server: 500\n', patrones))

    '''LOS DEMAS CARACTERES SE BUSCAN TAL CUAL (NO SON EXPRESIONES REGULARES)'''
    def test_caracteres_especiales(self):
        patrones = pc.preparar_patrones('Error! (x)')
        self.assertTrue(pc.coincide(b'Error! (x) algo', patrones))
        self.assertFalse(pc.coincide(b'Error x', patrones))


if __name__ == '__main__':
    unittest.main(verbosity=2)
