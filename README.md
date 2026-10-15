# 🍅 TOMATOES

> Un tomate del tamaño de una casa. Un cocinero diminuto con guantes de boxeo. Noventa segundos.

**TOMATOES** es un arcade de acción en 2D con vista lateral, escrito en Python. Controlas a **Rufo**, un pinche de cocina bajito y testarudo que ha decidido que el tomate gigante que ha aparecido en su almacén no va a acabar en salsa por las buenas. Corres, saltas, esquivas y golpeas hasta que el tomate revienta. Luego aparece otro, más grande y con peor carácter.

Todo el juego cabe en **un único fichero, `pytomatoes.py`**. No usa ni una imagen ni un sonido externos: los gráficos, las luces, las partículas, los efectos de sonido y la música se generan por código al arrancar.

---

## Cómo jugar

Necesitas Python 3.12 o posterior.

```bash
pip install pygame-ce numpy
python pytomatoes.py
```

O, con [uv](https://docs.astral.sh/uv/), sin instalar nada a mano (el fichero declara sus dependencias):

```bash
uv run pytomatoes.py
```

> ⚠️ No instales `pygame` y `pygame-ce` a la vez: los dos ocupan el módulo `pygame` y se pisan.

| Opción | Qué hace |
|---|---|
| `--mute` | Arranca sin sonido |
| `--selftest` | Pruebas unitarias y una partida completa jugada por un bot, sin ventana |
| `--shots DIR` | Guarda capturas PNG de cada pantalla en `DIR` (útil en CI) |

---

## Controles

| Acción | Teclado | Mando |
|---|---|---|
| Moverse | `A` / `D` o `←` / `→` | Stick izquierdo / cruceta |
| Saltar (doble salto en el aire) | `W`, `↑` o `Espacio` | A / ✕ |
| Agacharse | `S` o `↓` | Abajo |
| Jab (mantener: golpe cargado) | `J` | X / □ |
| Gancho | `K` | Y / △ |
| Gancho ascendente | `↑` + `J` | Arriba + X / □ |
| Martillo aéreo | `↓` + `J` en el aire | Abajo + X / □ en el aire |
| Esquiva rápida | `Shift` o `L` | RB / R1 |
| Pausa | `P` o `Esc` | Start |
| Pantalla completa | `F11` | — |
| Bloom on/off | `B` | — |
| Silenciar | `M` | — |
| Depuración (cajas de colisión y estados) | `F3` | — |

En pausa, `Q` vuelve al menú. El juego se pausa solo si la ventana pierde el foco o se desconecta el mando.

**Las teclas se pueden reasignar.** La primera vez que arranca, el juego crea `~/.tomatoes/config.json` con los valores por defecto. Edítalo con los nombres de tecla de pygame (`"a"`, `"left"`, `"left shift"`, `"f11"`…). El récord se guarda en `~/.tomatoes/record.json`.

---

## Reglas

- La ronda dura **90 segundos** y Rufo tiene **3 corazones**.
- La partida acaba si el reloj llega a cero **o** si Rufo pierde todos los corazones.
- Cada tomate reventado suma **10 segundos**, recupera **1 corazón** (máximo 3), da `500 × nivel` puntos y hace aparecer el siguiente nivel.

```
Aparece tomate ──► Rufo se acerca, esquiva y golpea ──► El tomate se agrieta y contraataca
       ▲                                                          │
       │                                                          ▼
  Siguiente nivel ◄── +10 s, bonus y 1 corazón ◄── ¡SPLASH! (revienta)
```

### El ritmo: esquivar, castigar, repetir

El tomate **siempre avisa** antes de atacar: con una animación, un sonido y, a veces, una marca en el suelo. Después de cada ataque queda **aturdido 0,8 s**, con estrellas girando sobre él. Los golpes en esa ventana valen el doble de puntos y suman el doble de combo.

| Ataque | Aviso | Cómo esquivarlo | Desde |
|---|---|---|---|
| **Rodar** | Se encoge y tiembla (0,6 s) | Esquiva a través de él, o salta encima y cabalga la rodada | Nivel 1 |
| **Bote aplastante** | Salta fuera de pantalla; su sombra crece en el suelo (0,8 s) | Salir de la sombra, o esquivar justo al impacto | Nivel 1 |
| **Chorro de jugo** | Se hincha por un lado; línea de aviso y «¡AGÁCHATE!» / «¡SALTA!» (0,5 s) | Agacharse (chorro alto) o saltar (chorro bajo) | Nivel 3 |
| **Lluvia de pepitas** | Tiembla con chasquidos (0,7 s); el suelo marca dónde caerán | Colocarse en uno de los huecos | Nivel 5 |
| **Furia** (con menos del 25 % de vida) | Se pone rojo oscuro y vibra | Encadena dos ataques seguidos antes de aturdirse | — |

Si Rufo está de pie sobre el tomate cuando va a rodar o botar, el tomate se lo sacude de encima sin hacerle daño.

### El punto débil

Cada tomate tiene un **punto débil** que brilla con pulso en una grieta. Golpearlo es un **crítico**: daño ×2, «¡JUGOSO!», zoom y aberración cromática. Después de cada crítico, el punto débil salta a otra grieta. Nunca aparece por debajo del tomate, donde no llega nadie, pero puede quedar arriba: entonces hay que **trepar**.

### Trepar

Con doble salto, Rufo llega a la corona del tomate del nivel 1. Para los tomates más grandes: cualquier golpe aéreo en la mitad alta del tomate hace **rebotar** a Rufo y le devuelve el doble salto. Así se encadenan golpes sin tocar el suelo y se sube a lo más alto.

### Escalado por nivel

| Propiedad | Nivel 1 | Por nivel | Tope |
|---|---|---|---|
| Radio | 220 px | +12 px | 320 px |
| Vida | 30 | +10 | — |
| Pausa entre ataques | 3,0 s | −0,25 s | 1,2 s |

---

## Golpes

Los tiempos están en fotogramas a 60 FPS: preparación, golpe activo y recuperación.

| Golpe | Entrada | Tiempos | Daño | Puntos | Notas |
|---|---|---|---|---|---|
| **Jab** | `J` | 3 / 3 / 8 | 1 | 10 | Rápido y seguro; abre combos |
| **Gancho** | `K` | 7 / 4 / 14 | 2 | 25 | Más alcance; empuja al tomate |
| **Gancho ascendente** | `↑` + `J` | 6 / 5 / 16 | 2 | 25 | Golpea hacia arriba y eleva a Rufo una vez por salto |
| **Golpe cargado** | Mantener `J` 0,4–1,2 s y soltar | — / 6 / 20 | 3–6 | 15 × daño | Rufo brilla dorado y es vulnerable mientras carga |
| **Martillo aéreo** | `↓` + `J` en el aire | 5 / 8 / 18 | 3 | 40 | Picado sobre la corona del tomate |

- **Cadena:** durante la recuperación de un golpe se puede lanzar el siguiente si la secuencia es válida: Jab → Jab → Gancho → Gancho ascendente. En el cuarto paso basta con `J`.
- **Búfer de entrada de 0,1 s:** si pulsas un poco antes de que termine la recuperación, el golpe sale igual.
- **Pared:** si empujas al tomate contra una pared con un gancho o un golpe cargado, rebota y queda aturdido.

## Puntuación y combo

| Acción | Puntos |
|---|---|
| Crítico (punto débil) | ×2 |
| Golpe durante el aturdimiento | ×2, y el combo sube de dos en dos |
| Esquiva perfecta (esquivar en los últimos 0,15 s antes del impacto) | 100 |
| Reventar un tomate | 500 × nivel |

- **Combo:** cada golpe encadenado en menos de 1,2 s lo incrementa. El multiplicador es `1 + 0,1 × (combo − 1)`, con tope en **×5**.
- **El combo se rompe** si Rufo recibe daño o si pasa la ventana sin golpear.

---

## Dirección visual

- **Almacén de cocina de noche:** estanterías desenfocadas (profundidad de campo), luces lejanas en *bokeh*, claraboyas con luz de luna, polvo en suspensión que brilla al cruzar los conos de luz, y lámparas colgantes que oscilan cuando el tomate bota.
- **El tomate:** sombreado píxel a píxel con numpy. Tiene luz principal, gajos, translucidez en el borde (la luz atraviesa la piel), rebote cálido del suelo, brillo especular difuso y punto de luz duro. A medida que pierde vida se oscurece y se llena de moratones; cada golpe abre una grieta con interior jugoso y pepitas, y gotea cuando está malherido. El cáliz de seis hojas se marchita.
- **Rufo:** figura vectorial supermuestreada ×2, con contorno fino y **animación procedural**: inclinación al correr, estirarse al saltar, aplastarse al aterrizar, golpes como poses clave con curvas elásticas, gorro con su propio muelle y cejas testarudas. Brilla dorado al cargar, parpadea cuando es invulnerable y el delantal guarda las manchas de jugo toda la partida.
- **Efectos:** suelo pulido con reflejos, manchas persistentes en suelo y paredes que se desvanecen poco a poco, estelas de guante, fantasmas de la esquiva, ondas de choque, bloom, viñeta y aberración cromática en los críticos.
- **Sensación de golpe (*game feel*):** pausa breve en cada impacto (*hit-stop*), sacudida de cámara proporcional al golpe, zoom sobre Rufo en los críticos y cámara lenta al reventar.

## Audio

Todo se sintetiza con numpy al arrancar: golpes de distinta intensidad, chapoteo en los críticos, un aviso propio para cada ataque (crujido grave al rodar, silbido ascendente al botar, gorgoteo antes del chorro, chasquidos antes de las pepitas), «tic» en los últimos 10 segundos, el estampido del ¡SPLASH! y un bucle musical con bombo, caja, bajo y acordes. Si no hay dispositivo de audio, el juego arranca igual, mudo.

---

## Técnica

| Pieza | Elección |
|---|---|
| Lenguaje | Python 3.12+ |
| Ventana, entrada, mando y audio | **pygame-ce** ≥ 2.4 |
| Sombreado procedural y síntesis de audio | **numpy** |
| Configuración y récord | JSON en `~/.tomatoes/` |

Decisiones clave:

- **Física a paso fijo de 120 Hz**, separada del render, para que saltos y tiempos de golpe sean iguales en cualquier máquina.
- **Búfer de entrada de 0,1 s** y ***coyote time*** de 0,1 s: la diferencia entre un control rígido y uno que se siente bien.
- **Combate con cajas de golpe** rectangulares contra la elipse del tomate, sin colisión por píxel: predecible y fácil de ajustar.
- **Rufo y el tomate son máquinas de estados explícitas**, visibles con `F3`.
- **Cachés:** el sombreado del tomate se calcula una vez por tamaño y nivel de daño; los gradientes, manchas y conos de luz se generan una sola vez.
- **Modo sin pantalla** (`SDL_VIDEODRIVER=dummy`) para el selftest y las capturas. El selftest usa un directorio temporal y nunca toca tu récord.

### Organización del fichero

`pytomatoes.py` está dividido en secciones numeradas:

1. Constantes (física, tiempos de golpe, paleta, controles por defecto)
2. Utilidades (muelles, curvas de suavizado, sprites procedurales cacheados)
3. Audio sintetizado
4. Entrada: teclado, mando y reasignación
5. Rufo: física, estados y golpes
6. El tomate: cerebro, ataques y daño
7. Efectos: partículas, manchas, ondas y textos
8. Escenario: el almacén
9. Render del tomate
10. Render de Rufo
11. Texto e interfaz
12. El juego: estados, combate, dibujo y postprocesado
13. Arranque, selftest y capturas

### Rendimiento

Con el selftest sin pantalla, en CPU y sin GPU, un fotograma completo con bloom tarda **unos 8 ms de media y unos 14 ms en el 5 % más lento**: holgado para 60 FPS y cerca de 120.

---

## Ideas para después

- Postprocesado por GPU con moderngl (bloom real, distorsión).
- Tomates especiales: cherry rápido en enjambre, tomate verde blindado, tomate podrido que deja charcos resbaladizos.
- Guantes alternativos con otras propiedades.
- Modo cooperativo con un segundo pinche.

## Licencia

[MIT](LICENSE).
