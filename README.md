# Top 5 · Economía de Mendoza

Todos los días a las 06:37 (hora argentina) GitHub Actions corre `noticias.py`, revisa medios locales, nacionales y organismos oficiales (`fuentes.yaml`), elige las 5 noticias económicas más relevantes para Mendoza y publica una página web. No depende de Claude ni de tu computadora.

## Puesta en marcha (una sola vez, ~10 minutos)

1. **Crear el repositorio**: en github.com → *New repository* → nombre `noticias-mendoza` (puede ser público o privado; GitHub Pages gratis requiere público).
2. **Subir los archivos**: *Add file → Upload files* y arrastrá todo el contenido de esta carpeta, **incluida la carpeta oculta `.github`** (si el explorador no la muestra, creala a mano con *Add file → Create new file* y el nombre `.github/workflows/diario.yml`, pegando su contenido).
3. **Permitir que el bot publique**: *Settings → Actions → General → Workflow permissions →* "Read and write permissions" → *Save*.
4. **Primera corrida**: pestaña *Actions* → "Noticias económicas Mendoza" → *Run workflow*. Tarda 1–2 minutos y crea la carpeta `docs/`.
5. **Activar la página**: *Settings → Pages → Source: Deploy from a branch → Branch: `main` / carpeta `/docs`* → *Save*. Queda en `https://<tu-usuario>.github.io/noticias-mendoza/`.

## Opcionales (en *Settings → Secrets and variables → Actions → New repository secret*)

| Secreto | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | Ranking y resumen de una línea con un LLM en vez del puntaje por palabras clave (costo: centavos por mes). Sin la clave, el sistema funciona igual. |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO` | Recibir el top 5 por mail. Con Gmail: `smtp.gmail.com`, tu dirección, una *contraseña de aplicación* y el destinatario. |

## Cómo decide qué es "importante"

Sin LLM, cada nota recibe un puntaje = (palabras económicas + 1,5 × menciones a Mendoza) × peso de la fuente (oficial 1,5; local 1,25; nacional 1,0) × frescura × cobertura (sube si varios medios publican lo mismo). Las notas de medios nacionales sólo entran si mencionan Mendoza o Cuyo; como máximo 2 por fuente.

## Ajustes

- **Fuentes**: editá `fuentes.yaml` (rss, html o búsqueda de Google News con `site:`).
- **Palabras clave y pesos**: diccionarios `MENDOZA` y `ECONOMIA` al inicio de `noticias.py`.
- **Horario**: línea `cron` en `.github/workflows/diario.yml` (está en UTC; 9:37 UTC = 6:37 ART).
- **Diagnóstico**: al pie de la página, "Estado de las fuentes" muestra cuáles respondieron y cuántas notas aportó cada una; `docs/data/AAAA-MM-DD.json` guarda las 40 mejores candidatas con su puntaje.

Nota: GitHub pausa los workflows programados de repos sin actividad durante 60 días; como el bot hace un commit diario, eso no debería ocurrir.
