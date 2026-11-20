# filtrar_log.py

Filtra un log de corridas de Jeppesen Studio (`process_bids.log`, `nohup.out`, `process_requests.log`) por fecha y por palabras clave. Lo usa el equipo de soporte de AMX para revisar rápido los logs que comparten los clientes.

El resultado es un archivo nuevo. Trae un encabezado que dice cuántas veces aparece cada frase pedida. Debajo van las líneas del log que interesan, copiadas tal cual del original. El log original nunca se modifica.

## Requisitos

- Python 2.7 o Python 3. Corre igual en los dos.
- Solo usa la librería estándar de Python: no hay nada que instalar.
- Linux o Windows.
- Es un solo archivo: no necesita `diagnostico.py`, `leer_logs.py` ni `verificar_bloques.py`.

## Uso rápido

```
python filtrar_log.py process_bids.log
```

1. El script lista las fechas que hay en el log y cuántas corridas tiene cada una.
2. Eliges las fechas.
3. El script escribe el log filtrado en `<carpeta actual>/<tu usuario>/`.

```
Fechas en process_bids.log:
   1) 2026-10-19   60 corridas
   2) 2026-10-20   98 corridas
   3) 2026-10-21   36 corridas
Elige fechas (ejemplo: 1,3 o 2-4; T = todas; Enter = ultimas 3):
```

## Opciones

| Opción | Forma corta | Qué hace |
|---|---|---|
| `--fecha AAAA-MM-DD` | `-f` | Fecha a filtrar. Se puede repetir. Si se usa, no sale el menú. |
| `--conservar "frase"` | `-c` | Muestra las líneas que tienen esta frase, además de las de `[conservar]` del `.config`. Se puede repetir. |
| `--excluir "frase"` | `-e` | Quita las líneas que tienen esta frase, aunque tengan una de conservar. Se puede repetir. |
| `--help` | `-h` | Ayuda con un ejemplo completo. |

Se puede pasar más de un log; cada uno tiene su propio menú y su propio archivo de salida.

## Reglas del filtro

1. **Fecha.** Solo importa el día; la hora se ignora. Cada corrida completa queda en el día en que empezó, aunque termine al día siguiente.
2. **Conservar.** El log filtrado muestra solo las líneas que tienen alguna frase de conservar.
3. **Excluir.** Si una de esas líneas también tiene una frase de excluir, se quita: gana excluir.
4. **Frases.**
   - No distinguen mayúsculas.
   - Con el prefijo `re:` son una expresión regular, por ejemplo `re:LIMO\+$`.
   - Una expresión regular inválida se avisa y se omite.

## Ejemplo completo

```
python filtrar_log.py process_bids.log -f 2026-10-19 -f 2026-10-20 -c "Cannot create gt" -c "re:LIMO\+$" -e "Setting baseURL"
```

Escribe `<usuario>/process_bids_filtrado_20261019_a_20261020.log`:

```
LOG ["process_bids.log"] FILTRADO
Generado por: usuario
Fechas: 2026-10-19, 2026-10-20
Conservar [Cannot create gt, re:LIMO\+$]
Excluir [Setting baseURL]
Las frases default de conservar y excluir se encuentran en filtrar_log.config
-----------------------------------------------------------------------------------------
Cannot create gt: Encontrado 452 veces de la linea 1350 a la linea 74419
re:LIMO\+$: Encontrado 452 veces de la linea 1350 a la linea 74419
Setting baseURL: Encontrado 474 veces de la linea 647 a la linea 75430
-----------------------------------------------------------------------------------------
(las lineas del log original que quedaron, tal cual)
```

El contador solo incluye las frases que se pasan con `-c` y `-e`. Las frases del `.config` se aplican, pero no se cuentan.

## El archivo de configuración

La primera vez que corre, el script crea `<tu usuario>/filtrar_log.config` con las frases default:

- **`[conservar]`:** `Error!`, `Traceback`, `waiting for answer yesorno`, `ERROR UPLOADING DATA`, `The X11 connection broke` y otras fallas graves.
- **`[excluir]`:** ruido conocido de Studio, como `GetTaskCol`, `Not operating created` o `ERROR MenuParser`.

Se edita a mano: una frase por línea, y las líneas que empiezan con `#` se ignoran. Al inicio del archivo hay un ejemplo comentado que muestra qué pasa con cada línea.

Si borras el archivo, se vuelve a crear con las frases default. Las frases que hayas agregado se pierden.

Cada usuario tiene su propia carpeta y su propio `.config`. Así, varios ingenieros pueden usar el script en el mismo servidor sin pisarse.

## Cuando no hay terminal

En cron, o con la entrada redirigida, el menú no aparece y se toman las últimas 3 fechas del log. Ctrl-C cancela sin mostrar errores.

## Limitaciones

- No lee `.gz` ni `.zip`: hay que descomprimirlos antes.
- Las horas con formato `2026-10-19 20:00:20` están en UTC (6 horas adelante de México). No se usan para fechar corridas. En un log sin corridas, una línea de la noche puede quedar en el día siguiente.
- Si una frase de conservar coincide con casi todo el log, el log filtrado sale casi del mismo tamaño que el original.
