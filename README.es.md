# qa-agent-evals

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[RU](README.md) · [EN](README.en.md) · [中文](README.zh.md) · **Español** · [Français](README.fr.md)

Un plugin de Claude Code para pruebas de aceptación de sistemas LLM con subagentes que interpretan roles. Tú señalas el sistema bajo prueba (SUT). El plugin construye su perfil, genera tarjetas de escenarios de cinco tipos, las ejecuta con subagentes actores a través de un adaptador aislado, emite veredictos con un juez que corre sobre otro modelo y arma un informe con tasa de aprobación y matriz de cobertura.

Lo separan de ejecutar prompts a mano tres cosas: la respuesta esperada de cada tarjeta queda escrita antes de la corrida (el oráculo), una capa de máquina verifica los hechos con grep antes de que el juez vea la respuesta, y el juez mismo corre sobre otro modelo y se calibra contra una muestra de control con veredictos conocidos. Las confirmaciones humanas tras la aceptación hacen crecer esa muestra. El entorno está aislado de los skills y el MCP del dueño. Los veredictos son asimétricos: FAIL prueba un defecto, GOT solo significa "no refutado".

![Cómo funciona: el plugin estudia el sistema, escribe tareas, un actor interpreta al usuario, el plugin ajeno corre tras un cristal, un juez puntúa las respuestas, el informe muestra el resultado](assets/concept.en.gif)

*Un proyecto personal: entender las evals de aceptación construyendo un instrumento funcional y ejecutándolo sobre sí mismo.*

## Cómo funciona

```
[A: analizar SUT] → [B: adaptador + prueba de humo] → [C: tarjetas] → [D: corridas × N repeticiones] → [E: informe]
```

- **El analista** (paso A) lee el SUT y construye un perfil: registro de funciones, mapa de riesgos, superficie de ataque, puntos de ambigüedad, opciones de adaptador.
- **Las tarjetas** (paso C) son de cinco tipos: obvious (camino feliz), convoluted (ambigüedad de varios turnos), critical (zonas de daño), adversarial (un ataque por tarjeta), out-of-scope (¿el SUT admite lo que no sabe?). Formato: YAML con una persona, una instrucción, un oráculo (hechos requeridos y prohibidos + expectativa en prosa) y un presupuesto.
- **El actor role-user** interpreta la persona contra el SUT a través del adaptador. Para sistemas CLI es una sesión headless aislada: directorio de trabajo neutral, sin acceso a los skills ni al MCP del dueño. Los SUT web van por un adaptador de navegador con superficie Playwright, ver `knowledge/adapters.md`. Las repeticiones las maneja `scripts/run-cards.sh`.
- **La capa de máquina** (`scripts/check-facts.py`) corre antes del juez: hace grep de los marcadores del oráculo sobre las transcripciones y sobre los archivos que el propio SUT escribió. Lo que la máquina prueba, el juez no lo re-juzga, y una autocontradicción (veredicto positivo sobre una violación probada) dispara un re-juzgado automático.
- **El juez** corre sobre otro modelo y trabaja en dos pasos: primero puntúa la respuesta contra el oráculo sin conocer la intención del escenario, luego supervisa al actor. Antes de cada corrida de aceptación se calibra con una muestra de control: casos escritos a mano, casos de datasets abiertos (TruthfulQA, Apache 2.0; ataques HH-RLHF, MIT) y una sección viva que crece con el feedback humano.
- **Bucle de feedback (Growing-Golden)**: tras una corrida el dueño confirma o corrige veredictos, por una página de marcado con clics o por texto directo en el chat. Solo un veredicto humano se vuelve etalón; el veredicto del propio juez nunca.
- **Informe**: veredictos y votos de las repeticiones, matriz de cobertura función por tipo, hallazgos con prioridades, análisis de causas, limitaciones de la corrida y su costo en tokens y dólares (lado del SUT y lado del juez medidos por separado).

El mapa completo (aislamiento, jerarquía de contextos, matriz de responsabilidades) está en [docs/architecture.md](docs/architecture.md). Versión interactiva: [docs/architecture.html](docs/architecture.html), cada nodo muestra qué archivo o parámetro lo mueve. Abre el archivo localmente en un navegador.

## Aislamiento de ejecución (v0.5.0)

El plugin probado corre en uno de dos niveles de aislamiento, registrado en el informe de cada corrida:

- **host** (por defecto): sin Docker ni dependencias extra. Aislamiento del entorno como antes: lista blanca de variables de entorno, MCP vacío, directorio de trabajo neutral, detector de manipulación. No hay barrera de sistema de archivos ni de red, y el informe marca este nivel honestamente como "no sandbox". Suficiente para plugins públicos de fuentes conocidas.
- **docker** (para material no confiable): un contenedor que monta solo el directorio de trabajo y una copia del plugin, raíz de solo lectura, usuario non-root, límites de recursos; la única salida es un contenedor proxy interno hacia la pasarela LLM. Si Docker no está disponible, la corrida se niega a arrancar (fail-closed), sin retroceso silencioso al modo inseguro.

Verificado en corridas vivas contra nuestro propio examples/evil-plugin (un plugin que nunca se niega): bajo docker quedaron bloqueados leer un secreto del host, el acceso a red, escribir fuera del espacio de trabajo y la manipulación de evidencia; en host los mismos ataques quedan registrados honestamente como riesgos del nivel. Hallazgo lateral: las herramientas del lado servidor de la pasarela (lectura web) meten contenido en la red cerrada, así que están prohibidas en modo docker.

Endurecido en v0.5.1: las fuentes del plugin se montan de solo lectura con una prueba de escritura al arrancar (si se puede escribir, la corrida se rechaza); la clave real de la pasarela vive solo dentro del contenedor proxy mientras el proceso probado recibe un marcador de posición; el proxy acepta solo rutas de la API LLM y limita las peticiones. Una suite de seguridad automatizada (`python scripts/sec-checks.py docker`) corre las seis verificaciones en un solo comando y en CI, en verde tanto en Windows como en el runner de Linux (runs/2026-10-13-sec/). Endurecimiento final en v0.5.2: la prueba de escritura es basada en evidencia (éxito solo con bloqueo confirmado), la normalización de rutas del proxy cierra traversals con /../, límites de frecuencia/volumen/tiempo añadidos, y el propio contenedor proxy corre como non-root sin capabilities; SEC-06 se divide en un ataque al oráculo y una falsificación de veredicto (ambos con verificación de hash); un test de integración corre el pipeline vivo con Claude Code real (runs/2026-10-13-secint/).

## Inicio rápido

Requisitos: Claude Code, bash, python3. En Windows usa Git Bash o WSL.

Instala el plugin (con `--plugin-dir <ruta>` al iniciar la sesión o vía un marketplace), abre una sesión en el directorio del sistema probado y escribe:

```
ejecuta las pruebas de aceptación en <ruta al SUT>
```

El pipeline recorre los pasos A-E solo y se detiene exactamente una vez, antes de la revisión de tarjetas: te las muestra y espera tu aprobación.

## Contenido

```
.claude-plugin/plugin.json    manifiesto
skills/acceptance-test/       el pipeline de cinco pasos (orquestador)
agents/analyst.md             perfilador del SUT
agents/role-user.md           actor que interpreta roles
agents/judge.md               juez de dos pasos (anclado a otro modelo)
agents/visual-reviewer.md     revisión visual de capturas (marcado solo para el humano)
knowledge/taxonomy.md         5 tipos de tarjetas, patrones, YAML de referencia
knowledge/adapters.md         adaptadores CLI y navegador (Playwright), aislamiento del entorno
knowledge/oracle.md           oráculos, escala de veredictos, plantillas de informe
knowledge/sandbox.md          niveles host/docker: fronteras, proxy, verificaciones
knowledge/golden-live.md      sección viva de la muestra de control (casos golden del feedback)
scripts/run-cards.sh          corredor CLI de tarjetas de un turno con repeticiones
scripts/run-integrity.sh      detector de manipulación del directorio de corrida
scripts/parse-events.py       parser de events.jsonl: respuestas, procedencia, diagnóstico
scripts/check-facts.py        verificador de hechos de máquina (transcripciones + archivos escritos por el SUT)
scripts/judge-batch.py        lote del juez + re-juzgado automático de autocontradicciones
scripts/judge-control.py      muestra de control del juez (conjuntos golden)
scripts/collect-feedback.py   feedback humano: página de marcado + candidatos golden
scripts/annotate-visuals.py   revisión visual: valida el marcado, página anotada, selección de muestras (--publish)
scripts/build-index.py        índice de corrida legible por máquina (index.jsonl)
scripts/cost-report.py        costo y duración de la corrida
scripts/judge-metrics.py      métricas de acuerdo del juez sobre corpus
scripts/diff-runs.py          comparación de dos corridas (una vista, no un criterio)
scripts/make-golden-*.py      conversores desde datasets abiertos (TruthfulQA, HH-RLHF)
scripts/sandbox.py            backend de niveles de aislamiento para sesiones del SUT
scripts/sandbox-proxy.py      proxy inverso a la pasarela LLM para el nivel docker
scripts/sec-checks.py         suite de seguridad de seis verificaciones del aislamiento docker
scripts/sec-integration.py    test de integración: pipeline vivo dentro del sandbox docker
scripts/Dockerfile.sandbox    imagen del contenedor de aislamiento
examples/evil-plugin          plugin objetivo para verificar el aislamiento
tests/                        tests unitarios y vivos del pipeline
docs/spec.md                  especificación
docs/plan.md                  plan de implementación
docs/architecture.md          cómo funciona: pipeline, aislamiento, responsabilidad
docs/research-2026-10-09.md   revisión de frameworks de origen
docs/research-2026-10-10-rsi.md  notas sobre fuentes de self-improvement
docs/research-2026-10-11-kaggle-golden.md  datasets abiertos para casos golden
docs/reviews/                 revisiones externas de la spec y code reviews
runs/                         artefactos de auto-aceptación y corridas de terceros (logs crudos y datos sensibles eliminados)
```

## Estado

v0.6.0. El pipeline creció sobre sistemas de terceros y sobre sí mismo.

v0.6.0 añadió una capa visual para las aceptaciones de navegador: el adaptador toma capturas de los estados junto a las transcripciones, un subagente revisor marca defectos en ellas (recuadro + severidad + comentario) y la página de feedback muestra las capturas anotadas junto a los veredictos. El marcado es una pista para el humano: el juez jamás lo ve, los veredictos no cambian y las capturas nunca entran en oráculos ni en la capa de máquina. Solo se publican muestras elegidas a mano por el dueño (`annotate-visuals.py --publish`).

Primero vinieron cuatro auto-aceptaciones (v1-v4, informes en [runs/](runs/2026-10-08-qa-agent-evals-selftest/report.md)): v1 encontró 3 defectos reales (límites de alcance, prometer lo no implementado, control de aprobación); cada corrida siguiente verificaba las correcciones anteriores y buscaba otras nuevas.

Luego sistemas de terceros: un skill de edición de prosa (dos corridas con comparación de versiones, [runs/](runs/2026-10-11-stop-slop-r2/report.md)), un generador de diapositivas con una inyección vía contenido, un skill de inglés técnico, el clásico 2048 a través del adaptador de navegador (un SUT determinista sin LLM) y sistemas de un perímetro cerrado (detalles reservados). Esas corridas hicieron crecer v0.3-v0.4: la capa de máquina de hechos (fugas cazadas por grep, incluidos archivos escritos por el SUT), la muestra de control del juez con datasets abiertos (TruthfulQA 45/45; ataques HH-RLHF), el bucle de feedback Growing-Golden con página de marcado, el re-juzgado automático de autocontradicciones y la economía medida: una aceptación típica cuesta $0.6-1.8 del lado del SUT más unos $0.4 por llamada del juez, porque una llamada CLI del juez arrastra ~75K tokens de preámbulo de sesión.

v0.5.0 añadió el aislamiento de ejecución (host/docker) con pruebas vivas contra evil-plugin, y los fallos de infraestructura ya se separan de los defectos del plugin (estados BLOCKED/ERROR). v0.5.1 y v0.5.2 lo endurecieron: la clave de la pasarela vive solo en el contenedor proxy, las fuentes se montan de solo lectura con una prueba de escritura basada en evidencia, la normalización de rutas del proxy cierra traversals con /../, límites de frecuencia/volumen/tiempo añadidos, y el proxy corre como non-root sin capabilities. La suite de seguridad (`python scripts/sec-checks.py docker`) está en verde en Windows y en el runner de CI de Linux (runs/2026-10-13-sec/); un test de integración corre el pipeline vivo con Claude Code real (runs/2026-10-13-secint/). En total: 52 tests: 43 unitarios del pipeline y 9 vivos de proxy.

Aún no funciona: solo están implementados los adaptadores CLI y de navegador; el aislamiento corta la invocación de skills pero no el conocimiento de su existencia; el juez se conecta a mano (`--model` explícito o elección del dueño en el paso B), porque el campo `model` del agente no funciona en todos los entornos.

Spec: [docs/spec.md](docs/spec.md), plan: [docs/plan.md](docs/plan.md).
