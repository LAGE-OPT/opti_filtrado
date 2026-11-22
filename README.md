# filtrar_log.py

Herramienta para filtrar uno o más logs de Jeppesen Studio (`process_bids.log`, `nohup.out`, `process_requests.log`) por fecha y por palabras clave. Lo usa el equipo de soporte de AMX para revisar rápido los logs que comparten los clientes.

El resultado es un encabezado que dice cuántas veces aparece cada frase pedida. Debajo van las líneas del log que interesan, copiadas tal cual del original. El log original nunca se modifica.

### Ejecutable en:

- Linux o Windows.
- Python 2.7 o Python 3. Corre igual en los dos.
    - Solo usa la librería estándar de Python: no hay nada que instalar.

## Uso básico

```
python filtrar_log.py archivo.log
```

1. Últimas tres fechas, con las palabras por default del archivo .config
2. El script lista las fechas que hay en el log y cuántas corridas tiene cada una.
    1. Estas fechas solo son compatibles con process_bids, process_requests y nohup.out
3. Eliges las fechas.
4. El script escribe el log filtrado en `<carpeta actual>/<tu usuario>/`, junto a un archivo `.config`.

#### El menú solo se despliega si no se determina una fecha

```
Fechas en process_bids.log:
   1) 2026-10-19   60 corridas
   2) 2026-10-20   98 corridas
   3) 2026-10-21   36 corridas
Elige fechas (ejemplo: 1,3 o 2-4; T = todas; Enter = ultimas 3):
```

## Opciones

|Opción|Forma corta|Qué hace|
|---|---|---|
|`--fecha AAAA-MM-DD`|`-f`|Fecha a filtrar. Se puede repetir. Si se usa, no sale el menú.|
|`--conservar "frase"`|`-c`|Muestra las líneas que tienen esta frase, además de las de `[conservar]` del `.config`. Se puede repetir.|
|`--bloque-con "frase"`|`-bc`|Con `-li` y `-lf`: muestra solo los bloques que tienen esta frase. Se puede repetir; basta con que un bloque tenga una.|
|`--excluir "frase"`|`-e`|Quita las líneas que tienen esta frase, aunque tengan una de conservar. Se puede repetir.|
|`--linea-inicial "fragmento"`|`-li`|Línea donde empieza cada bloque. Va siempre con `-lf`.|
|`--linea-final "fragmento"`|`-lf`|Línea donde termina cada bloque. Va siempre con `-li`.|
|`--delete`||Borra todos los outputs de este script en `<carpeta actual>/<usuario>/`. Pide confirmación. No toca los logs originales ni el `.config`.|
|`--help`|`-h`|Ayuda con un ejemplo completo.|

**Se puede filtrar más de un log a la vez, pero son procesos separados. Una ejecución por LOG. Un menú de fechas por LOG**

## Nombre del archivo de salida

```
<n>_<log>_filtrado_<fechas>.log
1_process_bids_AMCUS_2129_filtrado_20260908_a_20261019.log
2_process_bids_AMCUS_2129_filtrado_20260908.log
```

- `<fechas>`: un día (`20260908`) o del primero al último elegido (`20260908_a_20261019`).
- Si ya hay un output del mismo log con las mismas fechas, se sobreescribe y conserva su número.
- Si las fechas cambian, el output lleva el siguiente número de la carpeta.
- Las frases usadas quedan en el encabezado del archivo (`Conservar`, `Excluir` y `Comando:`), no en el nombre.

## Reglas del filtro

1. **Fecha.** En formato AAAA-MM-DD
2. **Frases de `-c`.** Primero salen, debajo del contador de cada frase, las líneas con esa frase, sin las que tengan una frase de `-e`. Sin `-e` salen todas. Una frase de `-c` gana a `[excluir]` del `.config`; solo `-e` la quita.
3. **Frases default del `.config`.** Después salen las líneas con una frase de `[conservar]`, sin las que tengan una frase de `[excluir]` o de `-e`. Las que ya salieron con `-c` no se repiten.
4. Cada línea va tal cual del log, seguida de `linea N` (su número en el log original).
5. **Frases.**
    - No distinguen mayúsculas.
    - Con el prefijo `re:` son una expresión regular (se busca con el módulo `re` de Python).
    - Una expresión regular inválida se avisa y se omite.

## Ejemplo completo

```
python filtrar_log.py process_bids.log -f 2026-10-19 -f 2026-10-20 -c "Cannot create gt" -c "LIMO+" -e "Setting baseURL"
```

Escribe `<usuario>/1_process_bids_filtrado_20261019_a_20261020.log`:

```
LOG ["process_bids.log"] FILTRADO
Generado por: usuario el 2026-11-21 17:19:00
Comando: python filtrar_log.py process_bids.log -f 2026-10-19 -f 2026-10-20 -c "Cannot create gt" -c LIMO+ -e "Setting baseURL"
Fechas: 2026-10-19, 2026-10-20
-----------------------------------------------------------------------------------------
Conservar [Cannot create gt, LIMO+]
Excluir [Setting baseURL]
Las frases default de conservar y excluir se encuentran en filtrar_log.config
-----------------------------------------------------------------------------------------
Cannot create gt: Encontrado 452 veces de la linea 1350 a la linea 74419
avi_rml_match_leg: Cannot create gt from str: SEA+0000+OD+++20261019+20261019+1700++60+BFI+1800++LIMO+ linea 1350
...
avi_rml_match_leg: Cannot create gt from str: ...+LIMO+ linea 74419

LIMO+: Encontrado 452 veces de la linea 1350 a la linea 74419
(las mismas líneas, cada una con su número)

Setting baseURL: Encontrado 474 veces de la linea 647 a la linea 75430
-----------------------------------------------------------------------------------------
Frases default de filtrar_log.config: 102 lineas
Error! Pid:1601606  Mon Oct 19 14:04:00 2026  User:amxcrewbidsvc linea 2149
...
```

El contador solo incluye las frases que se pasan con `-c` y `-e`. Las frases del `.config` se aplican, pero no se cuentan.

Debajo del contador de cada frase de `-c` van sus líneas, tal cual del log, cada una seguida de `linea N`. Esas líneas no se repiten en la sección del `.config`. Las de `-e` solo llevan el contador. Si `-e` quita líneas de una frase de `-c`, el contador lo dice al final: `(N quitadas por -e)`.

Después de la última raya va `Frases default de filtrar_log.config: N lineas` y esas líneas, con el mismo formato. Sin `-c` es la única sección.

## Bloques entre dos líneas (-li y -lf)

Con `-li` y `-lf`, el script agrega bloques completos: desde una línea que tenga el fragmento inicial hasta la siguiente que tenga el fragmento final, incluidas las dos. Los bloques van primero y después el resultado del filtro de conservar y excluir, como siempre.

```
python filtrar_log.py -c "could not read help topic file:" -li "Studio PID:" -lf "Release:" -bc "Display:   :1" -c "amxcrewbidsvc" process_bids_AMCUS_2129.log
```

Sin `-f` sale el menú de fechas. Con Enter (últimas 3 fechas: 2026-10-05, 2026-10-06 y 2026-10-19) escribe:

```
Bloques desde "Studio PID:" hasta "Release:" con [Display:   :1]: 15 de 16 encontrados
----- Bloque 2: de la linea 1430843 a la linea 1430857 (15 lineas) -----
Studio PID: 183560
Hostname:   app12.dal09.amx.jepphost.com
Username:   amxcrewbidsvc
...
X Server
 Display:   :1
 Protocol:  11.0
 Vendor:    The X.Org Foundation
 Release:   12011000
----- Bloque 3: de la linea 1431235 a la linea 1431249 (15 lineas) -----
...
-----------------------------------------------------------------------------------------
Conservar [could not read help topic file:, amxcrewbidsvc]
Excluir []
Las frases default de conservar y excluir se encuentran en filtrar_log.config
-----------------------------------------------------------------------------------------
could not read help topic file:: Encontrado 16 veces de la linea 1429525 a la linea 1482876
...
amxcrewbidsvc: Encontrado 48 veces de la linea 1429510 a la linea 1482923
...
```

El bloque 1 (línea 1429508) no se muestra porque su display es `:2`, no `:1`; por eso la lista empieza en el bloque 2.

Después de los bloques siguen las frases, sus contadores y el log filtrado por conservar y excluir, igual que sin `-li` y `-lf`. Todas las líneas del log van tal cual el original.

- `-li` y `-lf` pueden ser un fragmento de la línea. Siguen las reglas de las frases: no distinguen mayúsculas y aceptan `re:`.
- El bloque solo se corta al encontrar la línea final. Si la línea inicial se repite en medio, sigue siendo el mismo bloque.
- La línea final se busca a partir de la línea siguiente a la inicial. Una línea final suelta, fuera de un bloque, se ignora.
- Un bloque empieza solo en las fechas elegidas, pero sigue hasta su línea final aunque pase a otro día.
- Si el log termina sin la línea final, ese último bloque no se muestra. El encabezado avisa en qué línea empezaba.
- Con `-li "Running script with settings"` y `-lf "CuiExit"`, una corrida colgada (sin `CuiExit`) queda en el mismo bloque que la corrida siguiente, hasta el `CuiExit` de esa.

### Solo los bloques que tienen una frase (-bc)

```
python filtrar_log.py process_bids.log -f 2026-10-19 -li "Error! Pid" -lf "Legend:" -bc "MTY4044OD"
```

```
Bloques desde "Error! Pid" hasta "Legend:" con [MTY4044OD]: 10 de 10 encontrados
----- Bloque 1: de la linea 2149 a la linea 2153 (5 lineas) -----
...
```

- Se muestran solo los bloques que tienen la frase en alguna de sus líneas, incluidas la inicial y la final.
- `-bc` se puede repetir: basta con que el bloque tenga una de las frases. Sigue las reglas de las frases (sin distinguir mayúsculas, `re:`).
- Cada bloque conserva su número original. El encabezado dice cuántos se muestran de cuántos hay.
- `-bc` no cambia el log filtrado por conservar y excluir, que sigue debajo de los bloques.
- Usar `-bc` sin `-li` y `-lf` es un error.

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