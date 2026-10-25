# Reglas del Panel de Asistencia Oportuna

> Todos los datos del proyecto son **ficticios**. Los números de abajo son una **propuesta del equipo (supuesto [S])**, basada en la definición de ausentismo crónico: faltar el 10% o más de los días de clases.
> Si el equipo decide otros números, se cambian en un solo lugar: `app/config.py`.

## 1. Qué se guarda

**De cada niño, cada día de clases:**

| Dato | Ejemplo |
|---|---|
| Código del niño (sin nombre ni RUT) | `J03-N012` |
| Fecha | 2026-06-15 |
| Estado | presente o ausente |
| Motivo (solo si faltó) | Salud, Traslado o transporte, Situación familiar, Clima, Sin información |
| ¿La familia avisó el motivo? | Sí si hay un motivo distinto de "Sin información" |

**Del jardín:** nombre, comuna y región. **De la sala:** el nivel (Sala cuna, Medio menor, Medio mayor).

**Reglas de calidad de datos:**
- Un niño presente no lleva motivo.
- Si faltó y nadie anotó el motivo, queda como "Sin información".
- No se puede registrar dos veces al mismo niño el mismo día.

## 2. Cómo se calcula el porcentaje de faltas

```
% de faltas = días ausente ÷ días de clases transcurridos × 100
```

**Ejemplo:** un niño faltó 6 días y van 40 días de clases. Su porcentaje es 6 ÷ 40 × 100 = **15%**.

## 3. Qué significa cada color

En riesgo significa estar en amarillo o en rojo, es decir, haber faltado el 10% o más de los días de clases.

| Color | Porcentaje de faltas | Qué significa | Qué se hace |
|---|---|---|---|
| **Verde** | Menos de 10% | Va bien | Nada especial |
| **Amarillo** | Desde 10% hasta menos de 20% | Hay que mirarlo | La directora lo revisa |
| **Rojo** | 20% o más | Hay que actuar | Se abre un caso de seguimiento |
| **Sin datos** | Menos de 10 días de clases | Es muy pronto para decidir | Se espera |

Con pocos días de clases, una sola falta da un porcentaje enorme (1 falta en 3 días es 33%). Por eso, antes de 10 días de clases no se pinta el semáforo.

## 4. Cuándo sale una alerta

| Alerta | Cuándo sale | Para qué sirve |
|---|---|---|
| **Racha** | El niño lleva 3 o más faltas seguidas hasta el último día | Detecta un problema que está pasando ahora, aunque el porcentaje del año se vea bien |
| **Riesgo amarillo** | El niño está en amarillo | Aviso para la directora |
| **Riesgo rojo** | El niño está en rojo | Aviso para el Comité de Asistencia |
| **Tendencia** | El niño está en verde en el año, pero en los últimos 20 días de clases faltó 10% o más | Alerta temprana: va bien, pero está empeorando |

## 5. Lo que muestra el jardín (y por qué importa)

Para cada jardín el panel muestra **dos cosas juntas**:

1. El **promedio de asistencia**, que es lo que se mira hoy.
2. El **número y el porcentaje de niños en rojo**, que es lo que el promedio esconde.

**Ejemplo con datos ficticios:** el jardín "Pequeños Pasos (ficticio)" tiene 92,5% de asistencia promedio, que se ve muy bien. Pero 4 de sus 25 niños (16%) están en rojo. Si solo se mira el promedio, esos 4 niños pasan desapercibidos.

Esa es la brecha del proyecto: se mira el promedio cada 4 meses, y los casos graves aparecen tarde.

## 6. Jardines de demostración

Con los datos ficticios por defecto, los tres primeros jardines están pensados para mostrar situaciones distintas:

| Jardín | Qué muestra |
|---|---|
| Rayito de Sol (ficticio) | Las ausencias **bajan** a lo largo del año |
| Semillitas (ficticio) | Las ausencias **suben** a lo largo del año |
| Pequeños Pasos (ficticio) | Buen promedio, pero con **4 niños en rojo escondidos** |

Los otros nueve jardines tienen un comportamiento parejo, con distintos niveles de ausencia.

## 7. Qué decisión permite cada color y alerta

| Quién | Qué ve | Qué decide |
|---|---|---|
| Directora del jardín | Sus niños en amarillo, rojo y con racha | A quién llamar o visitar esta semana |
| Comité de Asistencia | Los casos en rojo y su seguimiento | Si refuerza el acompañamiento a la familia o cambia la estrategia |
| Subdirección de Educación Inicial | Todos los jardines, con promedio y niños en rojo | En qué jardines reforzar el apoyo antes de que termine el cuatrimestre |
