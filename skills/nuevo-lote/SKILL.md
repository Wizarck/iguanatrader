---
name: nuevo-lote
description: >
  Registra un nuevo lote de producción de pastelitos maracuchos. Asigna número
  de lote automáticamente, recoge datos reales de ingredientes, masa, rendimiento
  y QA, calcula costes y genera un fichero de registro en
  01_produccion/data/lotes/.
argument-hint: "[sabor]  (opcional: pollo|carne|queso|vegano)"
---

# Nuevo Lote de Producción — Pastelitos Maracuchos

Registra un lote de producción paso a paso. Haz una pregunta cada vez y espera
la respuesta antes de continuar. No hagas más de una pregunta por mensaje.

## Precios de referencia (Mar-26)

Usa estos precios para el cálculo de costes al final:

**Rellenos:**
| Ingrediente | B.Imp/kg | Import/kg | IVA |
|---|---|---|---|
| Queso Llanero Barra (QLLB-1000) | €7,73 | €8,04 | 4% |
| Patata (bolsa 5kg) | €1,1827 | €1,23 | 4% |
| Patata (bolsa 3kg) | €1,4904 | €1,55 | 4% |
| Pechugas de pollo | ~€6,145 | ~€6,76 | 10% |
| Carne picada | €9,8182 | €10,80 | 10% |
| Pimentón rojo | €2,7885 | €2,90 | 4% |
| Pimentón verde | €2,4519 | €2,55 | 4% |
| Cebolla | €1,875 | €1,95 | 4% |
| Patata (para carne) | €1,1827 | €1,23 | 4% |
| Cubito de pollo | €0,0549/ud | €0,060/ud | 10% |
| Cubito de carne | €0,0682/ud | €0,075/ud | 10% |

**Masa:**
- Un lote de masa = 7.700 gr
- Coste lote masa: B.Imp **€3,806** / Import **€4,013**

**Precio de venta:** €0,5455/ud (B.Imp) = €0,60 IVA incl.

---

## Paso 1 — Número de lote

**Taxonomía del ID de lote:** `{X}{NNN}-{AA}{L}{DD}`
- `X` = inicial del sabor: **P**=pollo, **C**=carne, **Q**=queso, **V**=vegano
- `NNN` = número secuencial global (sin ceros a la izquierda)
- `AA` = año en 2 dígitos (p.ej. 26 para 2026)
- `L` = letra del mes: A=ene B=feb C=mar D=abr E=may F=jun G=jul H=ago I=sep J=oct K=nov L=dic
- `DD` = día en 2 dígitos

Ejemplo: `C185-26D01` = Carne, lote 185, 1 de abril de 2026.

**Para asignar el número secuencial:**
Busca todos los ficheros `.md` en:
`c:\Users\aramirez\OneDrive\02_WORK\Palafito\01_produccion\data\lotes\`

que sigan el patrón `[CQPV]{número}-*.md` (cualquier sabor).
Extrae todos los números secuenciales y toma el más alto + 1.
Si no hay ningún fichero → el siguiente número es **1**.

No conoces el sabor todavía — usa un número provisional hasta el Paso 3 donde se confirma el sabor y se construye el ID completo.

Comunica al usuario: `Número secuencial asignado: #NNN`
Luego pregunta si quiere usar ese número o asignar otro manualmente.

## Paso 2 — Fecha y hora de inicio

1. Pregunta: **¿Fecha de producción?**
   Muestra la fecha de hoy como valor por defecto (formato YYYY-MM-DD).
   Si el usuario no responde nada o dice "hoy", usa la fecha actual.
2. Pregunta: **¿Hora de inicio del formado?**
   _(cuando se pone en marcha la máquina por primera vez)_
   Si el usuario dice "ahora" o "ahora mismo" → usa la hora actual del sistema automáticamente y confírmala.

## Paso 3 — Sabor

Si el usuario pasó un argumento al invocar el skill (p.ej. `/nuevo-lote queso`),
usa ese valor como sabor y confirma al usuario.

Si no hay argumento, pregunta:
**¿Sabor? → pollo / carne / queso / vegano**

Con el sabor y la fecha confirmados, construye el ID completo del lote:
- Inicial: P/C/Q/V según sabor
- Número secuencial del Paso 1
- Año 2 dígitos, letra del mes (A–L), día 2 dígitos

Comunica: `ID de lote: {X}{NNN}-{AA}{L}{DD}` (p.ej. `Q012-26D07`)

Según el sabor, muestra el molde y los pesos de referencia:
- **pollo** → Molde cuadrado R136-7 · 16g masa + 8g relleno = 24g/ud
- **carne** → Molde redondo liso · 15g masa + 8g relleno = 23g/ud
- **queso** → Molde redondo liso · 11,5g masa + 10g relleno = 21,5g/ud
- **vegano** → Molde (por definir) · datos pendientes

## Paso 4 — Datos del relleno

Haz las preguntas una a una. Muestra siempre los valores de referencia entre
paréntesis para orientar al usuario.

### Si sabor = queso

1. **¿Queso Llanero Barra usado (gr)?**
   _(ref: ~9.000g lote simple / ~18.000g lote doble)_
2. **¿Puré de patata (gr, peso neto que entró en el guiso)?**
   _(ref: ~4.500g lote simple / ~9.000g lote doble)_
3. **¿Agua añadida al guiso (ml)?**
   _(ref: 200ml — escribe 0 si no se añadió)_
4. Calcula internamente: `guiso_total = queso_gr + patata_gr`
   Informa: `Guiso total (sin agua): X.XXX gr`
5. **¿Peso del guiso ya frío antes de cargar la máquina (gr)?**
   _(para calcular merma de preparación real)_
   Calcula: `merma_preparacion_gr = guiso_total - guiso_frio_gr`
   `merma_preparacion_pct = merma_preparacion_gr / guiso_total × 100`
   Informa: `Merma preparación: X.XXX gr (XX,X%)`

### Si sabor = pollo

1. **¿Peso bruto total de pechugas compradas (gr)?**
   _(ref: ~10.900g = aprox. 10 bandejas Mercadona)_
2. **¿Pimentón rojo (gr neto, ya limpiado)?** _(ref: 1.600g)_
3. **¿Pimentón verde (gr neto)?** _(ref: 800g)_
4. **¿Cebolla (gr neto)?** _(ref: 1.600g)_
5. **¿Cubitos de caldo de pollo usados (unidades)?** _(ref: 16)_
6. **¿Peso del pollo cocido y desmenuzado (gr)?**
   _(para calcular merma de cocción real)_
   Calcula: `merma_coccion_gr = pollo_bruto_gr - pollo_cocido_gr`
   `merma_coccion_pct = merma_coccion_gr / pollo_bruto_gr × 100`
   Informa: `Merma cocción real: XX,X% (ref: ~27%)`
   Si `merma_coccion_pct > 35%` → advierte: `⚠ Merma de cocción inusualmente alta`
7. **¿Peso del guiso completo (pollo + verduras) antes de cargar la máquina (gr)?**
   Informa: `Guiso total: X.XXX gr`

### Si sabor = carne

1. **¿Carne picada usada (gr)?**
   _(ref: 12.000g = 12 paquetes de 1kg)_
2. **¿Pimentón rojo (gr neto)?** _(ref: 2.400g)_
3. **¿Pimentón verde (gr neto)?** _(ref: 1.200g)_
4. **¿Cebolla (gr neto)?** _(ref: 4.800g)_
5. **¿Patata (gr neto)?** _(ref: 4.800g)_
6. **¿Cubitos de caldo de carne usados (unidades)?** _(ref: 48)_
7. **¿Peso de la carne cocida (gr)?**
   _(para calcular merma de cocción real)_
   Calcula: `merma_coccion_gr = carne_gr - carne_cocida_gr`
   `merma_coccion_pct = merma_coccion_gr / carne_gr × 100`
   Informa: `Merma cocción carne real: XX,X% (ref: pendiente de validar)`
8. **¿Peso del guiso completo (carne + verduras) antes de cargar la máquina (gr)?**
   Informa: `Guiso total: X.XXX gr`

### Si sabor = vegano

Informa al usuario que el proceso de vegano está pendiente de documentar
completamente. Recoge igualmente los datos disponibles de forma libre y
documenta en el fichero final.

## Paso 5 — Masa

1. **¿Cuántos lotes de masa se prepararon?**
   _(cada lote = 7.700g de harina + resto de ingredientes)_
2. **¿Cuántos lotes de masa se usaron realmente?**
   _(puede ser decimal: p.ej. 3,5 si sobró medio lote)_
3. Calcula internamente:
   - `masa_total_usada_gr = lotes_usados × 7700`
   - Informa: `Masa usada: ~X.XXX gr (N,N lotes)`

## Paso 5b — Control de gramaje (opcional)

1. **¿Hiciste control de gramaje en este lote? (s/n)**
2. Si sí:
   - **¿Cuántas unidades pesaste como muestra?** _(ref: 5–10 uds)_
   - **¿Peso total de la muestra (gr)?**
   - Calcula: `peso_medio_real = peso_muestra / n_muestra`
   - Compara con diseño: pollo=24g, carne=23g, queso=21,5g
   - `desviacion_pct = (peso_medio_real - peso_diseño) / peso_diseño × 100`
   - Informa: `Peso medio real: XX,Xg (diseño: XX,Xg · desviación: +/−X,X%)`
   - Si `|desviacion_pct| > 10%` → advierte: `⚠ Desviación de gramaje significativa`

## Paso 6 — Producción, QA y tiempos

1. **¿Unidades formadas por la máquina (contador)?**
   _(Si no se midió, escribe "no medido")_
2. **¿Unidades desechadas en QA (rotas, mal formadas, sin relleno, quemadas...)?**
3. Calcula internamente:
   - Si se midió formadas: `unidades_buenas = formadas - desechadas`
   - Si no se midió: `unidades_buenas = valor_desconocido` → pregunta directamente
     **¿Unidades buenas totales (después de QA)?**
4. Calcula (si tienes formadas):
   - `tasa_rechazo_pct = desechadas / formadas × 100`
   - `rendimiento_relleno_ud = guiso_total / unidades_buenas` (gr de guiso por ud buena)
5. **¿Relleno sobrante al finalizar (gr que quedó sin usar en la máquina)?**
   _(ref: ~1.500g — escribe 0 si no quedó nada o no se midió)_
   Si se proporcionó: `merma_maquina_pct = relleno_sobrante / guiso_total × 100`
   Informa: `Merma máquina: X.XXX gr (XX,X% del guiso · ref: ~1.500g)`
6. **¿Hora de fin del formado? (HH:MM)**
   Calcula: `tiempo_formado_min = hora_fin - hora_inicio` → informa en horas y minutos
7. **¿Hora de inicio del abatido?**
   Si el usuario dice "ahora" o "ahora mismo" → usa la hora actual del sistema.
8. **¿Hora de fin del abatido?**
   Si el usuario dice "ahora" o "ahora mismo" → usa la hora actual del sistema.
   Calcula: `tiempo_abatido_min = hora_fin_abatido - hora_inicio_abatido`
   Informa: `Abatido: X h YY min`
   Informa también: `Producción total (inicio formado → fin abatido): X h YY min`

## Paso 7 — Observaciones

**¿Observaciones o incidencias del lote?**
_(p.ej. problemas de máquina, consistencia del guiso, ajustes realizados, mermas anómalas — escribe "ninguna" si todo fue normal)_

## Paso 8 — Calcular costes

Con todos los datos recogidos, realiza el siguiente cálculo:

### Queso
```
coste_queso_bimp    = (queso_gr / 1000) × 7.73
coste_queso_import  = (queso_gr / 1000) × 8.04
coste_patata_bimp   = (patata_gr / 1000) × 1.4904   # usar precio 3kg por defecto
coste_patata_import = (patata_gr / 1000) × 1.55
total_relleno_bimp  = coste_queso_bimp + coste_patata_bimp
total_relleno_import = coste_queso_import + coste_patata_import
```

### Pollo
```
coste_pollo_bimp    = (pollo_bruto_gr / 1000) × 6.145
coste_pollo_import  = (pollo_bruto_gr / 1000) × 6.76
coste_p_rojo_bimp   = (p_rojo_gr / 1000) × 2.7885
coste_p_verde_bimp  = (p_verde_gr / 1000) × 2.4519
coste_cebolla_bimp  = (cebolla_gr / 1000) × 1.875
coste_cubitos_bimp  = n_cubitos × 0.0549
total_relleno_bimp  = suma de todo; igualmente para import
```

### Carne
```
coste_carne_bimp    = (carne_gr / 1000) × 9.8182
coste_carne_import  = (carne_gr / 1000) × 10.80
coste_p_rojo_bimp   = (p_rojo_gr / 1000) × 2.7885
coste_p_verde_bimp  = (p_verde_gr / 1000) × 2.4519
coste_cebolla_bimp  = (cebolla_gr / 1000) × 1.875
coste_patata_bimp   = (patata_gr / 1000) × 1.1827
coste_cubitos_bimp  = n_cubitos × 0.0682
total_relleno_bimp  = suma de todo; igualmente para import
```

### Masa y totales (todos los sabores)
```
coste_masa_bimp    = lotes_usados × 3.806
coste_masa_import  = lotes_usados × 4.013
total_bimp         = total_relleno_bimp + coste_masa_bimp
total_import       = total_relleno_import + coste_masa_import
coste_ud_bimp      = total_bimp / unidades_buenas
coste_ud_import    = total_import / unidades_buenas
margen_bruto_pct   = (0.5455 - coste_ud_bimp) / 0.5455 × 100
```

Redondea costes/ud a 3 decimales. Redondea porcentajes a 1 decimal.

## Paso 9 — Confirmar y guardar

Muestra el resumen al usuario:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESUMEN LOTE {ID_LOTE}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fecha:         YYYY-MM-DD
Sabor:         SABOR
Uds buenas:    X.XXX
Coste/ud:      €0,XXX (B.Imp) · €0,XXX (Import)
Margen bruto:  XX,X%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Pregunta: **¿Confirmar y guardar el fichero? (s/n)**

Si el usuario dice no o quiere corregir algo, permite editar el dato que indique
y recalcula antes de volver a mostrar el resumen.

Si confirma, genera el fichero.

## Paso 10 — Generar fichero

Crea el fichero en:
```
c:\Users\aramirez\OneDrive\02_WORK\Palafito\01_produccion\data\lotes\{ID_LOTE}.md
```
donde `{ID_LOTE}` es el ID construido en el Paso 3 (p.ej. `C185-26D01.md`).

Usando esta plantilla (sustituye todos los valores en MAYÚSCULAS con los datos reales):

---

```markdown
# Lote {ID_LOTE} — SABOR — YYYY-MM-DD

## Datos generales

| Campo | Valor |
|---|---|
| ID de lote | {ID_LOTE} |
| Fecha de producción | YYYY-MM-DD |
| Sabor | SABOR |
| Molde | MOLDE |
| Relleno por unidad | X gr |
| Masa por unidad | X gr |
| Inicio formado | HH:MM |
| Fin formado | HH:MM |
| Tiempo de formado | X h YY min |
| Inicio abatido | HH:MM |
| Fin abatido | HH:MM |
| Tiempo de abatido | X h YY min |
| Tiempo total producción | X h YY min |

---

## Relleno

### Ingredientes usados

[TABLA CON INGREDIENTES REALES — filas según sabor]

| Concepto | Valor |
|---|---|
| **Guiso total** | **X.XXX gr** |
| Agua añadida | X ml |   ← solo para queso

### Análisis de merma

| Concepto | Valor |
|---|---|
| Ingredientes crudos totales | X.XXX gr |
| Merma cocción real | X.XXX gr (XX,X%) |
| Guiso total antes máquina | X.XXX gr |
| Merma preparación | X.XXX gr (XX,X%) |  ← solo queso
| Relleno sobrante en máquina | X.XXX gr (XX,X%) |
| Relleno consumido real | X.XXX gr |
| Relleno por unidad (diseño) | X gr |
| Uds teóricas por relleno | X.XXX |
| Uds buenas reales | X.XXX |
| Eficiencia relleno real | XX,X% |

---

## Masa

| Concepto | Valor |
|---|---|
| Lotes preparados | N |
| Lotes usados | N,N |
| Masa total usada | X.XXX gr |
| Masa por unidad (diseño) | X gr |

---

## Producción y QA

| Concepto | Valor |
|---|---|
| Unidades formadas (contador) | XXX / no medido |
| Unidades desechadas QA | XXX |
| **Unidades buenas** | **X.XXX** |
| Tasa de rechazo | X,X% / — |

## Control de gramaje

| Concepto | Valor |
|---|---|
| Muestra (uds) | X / no realizado |
| Peso muestra (gr) | X.XXX |
| Peso medio real | XX,X gr |
| Peso diseño | XX,X gr |
| Desviación | +/−X,X% |

---

## Costes

### Desglose

[TABLA CON TODOS LOS INGREDIENTES — B.Imp y Import]

### Resumen

| Concepto | B.Imp | Import |
|---|---|---|
| Relleno total | €XX,XX | €XX,XX |
| Masa (N,N lotes) | €XX,XX | €XX,XX |
| **Total producción** | **€XXX,XX** | **€XXX,XX** |
| **Coste / unidad** | **€0,XXX** | **€0,XXX** |
| **Margen bruto** | **XX,X%** | — |

> Precio de venta referencia: €0,5455/ud (B.Imp) = €0,60 IVA incl.

---

## Observaciones

TEXTO_OBSERVACIONES

---

*Registrado el YYYY-MM-DD con /nuevo-lote · ID {ID_LOTE}*
```

---

Tras crear el fichero, confirma al usuario:
```
✓ Fichero creado: 01_produccion/data/lotes/{ID_LOTE}.md
```

$ARGUMENTS
