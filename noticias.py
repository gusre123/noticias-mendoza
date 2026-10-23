"""Top 5 noticias económicas de Mendoza y Top 5 de Argentina.

Corre solo (GitHub Actions). Sin dependencia de Claude.
Si existe la variable ANTHROPIC_API_KEY, usa un LLM para afinar el ranking
y resumir; si no, usa el puntaje por palabras clave.
"""
from __future__ import annotations

import html
import json
import os
import re
import smtplib
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote_plus, urljoin
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime.now(TZ)
VENTANA_HORAS = 36
TOP_N = 5
MAX_POR_FUENTE = 2
UA = {"User-Agent": "Mozilla/5.0 (noticias-mendoza bot; +https://github.com)"}
BASE = Path(__file__).parent
DOCS = BASE / "docs"

# ---------------------------------------------------------------- palabras clave
MENDOZA = {
    "mendoza": 3, "mendocin": 3, "cuyo": 2, "godoy cruz": 2, "guaymallen": 2,
    "lujan de cuyo": 2, "las heras": 1, "san rafael": 2, "maipu": 1,
    "valle de uco": 2, "tunuyan": 2, "san martin mendoza": 2, "malargue": 2,
    "general alvear": 2, "lavalle": 1, "cornejo": 2, "deie": 3,
    "vendimia": 2, "portezuelo": 2, "potasio rio colorado": 3, "psj cobre": 3,
    "vaca muerta mendocina": 3, "paso cristo redentor": 2,
}
ECONOMIA = {
    "inflacion": 3, "ipc": 3, "precios": 2, "canasta basica": 3, "pobreza": 3,
    "empleo": 3, "desempleo": 3, "desocupacion": 3, "salario": 2, "sipa": 3,
    "trabajo registrado": 3, "paritaria": 2, "exportacion": 3, "importacion": 2,
    "inversion": 2, "rigi": 3, "pbg": 3, "pbi": 2, "emae": 3, "actividad economica": 3,
    "recaudacion": 2, "ingresos brutos": 2, "presupuesto": 2, "deuda": 2,
    "coparticipacion": 2, "industria": 2, "construccion": 2, "comercio": 1,
    "ventas": 1, "consumo": 2, "turismo": 1, "vitivinic": 3, "vino": 2, "uva": 2,
    "bodega": 2, "fruticola": 2, "agro": 1, "cosecha": 2, "mineria": 3, "cobre": 2,
    "petroleo": 2, "hidrocarburo": 2, "energia": 1, "tarifa": 2, "tasa": 1,
    "dolar": 1, "credito": 2, "banco central": 2, "bcra": 2, "pymes": 2, "pyme": 2,
    "riesgo pais": 2, "reservas": 2, "tipo de cambio": 2, "fiscal": 2, "deficit": 2,
    "superavit": 2, "fmi": 2, "bonos": 1, "licitacion": 1, "jubilacion": 1,
    "economia": 1, "indec": 2, "censo": 1, "patentamiento": 2, "escrituras": 2,
}


def norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt.lower()).strip()


def puntaje(diccionario: dict, texto: str) -> int:
    t = norm(texto)
    return sum(peso for clave, peso in diccionario.items() if clave in t)


# ---------------------------------------------------------------- recolección
def leer_rss(url: str) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        fecha = None
        for campo in ("published_parsed", "updated_parsed"):
            if getattr(e, campo, None):
                fecha = datetime(*getattr(e, campo)[:6], tzinfo=timezone.utc).astimezone(TZ)
                break
        resumen = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ")
        titulo = e.get("title", "")
        medio = ""
        if " - " in titulo and "news.google" in url:  # GN agrega " - Medio"
            titulo, medio = titulo.rsplit(" - ", 1)
        items.append({"titulo": titulo.strip(), "url": e.get("link", ""),
                      "fecha": fecha, "resumen": resumen[:400], "medio": medio})
    return items


def leer_gnews(q: str) -> list[dict]:
    url = (f"https://news.google.com/rss/search?q={quote_plus(q + ' when:2d')}"
           "&hl=es-419&gl=AR&ceid=AR:es-419")
    return leer_rss(url)


def leer_html(url: str) -> list[dict]:
    """Toma los enlaces de una página oficial. Sin fecha confiable: se marca como 'hoy'
    sólo si el enlace no se vio en corridas anteriores (ver vistos.json)."""
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items, vistos = [], set()
    for a in soup.find_all("a", href=True):
        texto = a.get_text(" ", strip=True)
        if len(texto) < 25 or len(texto) > 250:
            continue
        link = urljoin(url, a["href"])
        if link in vistos or link.startswith(("mailto:", "javascript:")):
            continue
        vistos.add(link)
        items.append({"titulo": texto, "url": link, "fecha": None, "resumen": "", "medio": ""})
    return items


def recolectar(fuentes: list[dict], vistos_previos: set[str]) -> tuple[list[dict], list[dict]]:
    notas, estado = [], []
    limite = AHORA - timedelta(hours=VENTANA_HORAS)
    for f in fuentes:
        try:
            if f["tipo"] == "rss":
                items = leer_rss(f["url"])
            elif f["tipo"] == "gnews":
                items = leer_gnews(f["q"])
            elif f["tipo"] == "html":
                items = leer_html(f["url"])
            else:
                raise ValueError(f"tipo desconocido {f['tipo']}")
            n = 0
            for it in items:
                if it["fecha"] is None:
                    if it["url"] in vistos_previos:  # enlace viejo de página oficial
                        continue
                    it["fecha"] = AHORA
                    it["fecha_estimada"] = True
                if it["fecha"] < limite:
                    continue
                it["fuente"] = f["nombre"]
                it["medio"] = it["medio"] or f["nombre"]
                it["categoria"] = f.get("categoria", "nacional")
                it["solo_mendoza"] = f.get("solo_mendoza", False)
                it["alcance"] = f.get("alcance", "mendoza")
                notas.append(it)
                n += 1
            estado.append({"fuente": f["nombre"], "ok": True, "notas": n})
        except Exception as ex:  # una fuente caída no frena el resto
            estado.append({"fuente": f["nombre"], "ok": False, "error": str(ex)[:120]})
    return notas, estado


# ---------------------------------------------------------------- ranking
PESO_CATEGORIA = {"oficial": 1.5, "local": 1.25, "nacional": 1.0}


def tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", norm(t))}


def agrupar(notas: list[dict]) -> list[dict]:
    """Junta la misma noticia publicada por varios medios (similitud de títulos)."""
    grupos: list[dict] = []
    for n in notas:
        tk = tokens(n["titulo"])
        if not tk:
            continue
        for g in grupos:
            inter = len(tk & g["tokens"]) / max(1, min(len(tk), len(g["tokens"])))
            if inter >= 0.6 or n["url"] == g["nota"]["url"]:
                g["medios"].add(n["medio"])
                g["nacional"] |= n["alcance"] == "nacional"
                if PESO_CATEGORIA[n["categoria"]] > PESO_CATEGORIA[g["nota"]["categoria"]]:
                    g["nota"] = n
                break
        else:
            grupos.append({"nota": n, "tokens": tk, "medios": {n["medio"]},
                           "nacional": n["alcance"] == "nacional"})
    return grupos


def calificar(grupos: list[dict], modo: str = "mendoza") -> list[dict]:
    """modo 'mendoza': relevancia provincial. modo 'argentina': economía nacional."""
    salida = []
    for g in grupos:
        n = g["nota"]
        texto = f"{n['titulo']} {n['resumen']}"
        pm, pe = puntaje(MENDOZA, texto), puntaje(ECONOMIA, texto)
        if pe == 0:
            continue
        if modo == "mendoza" and pm == 0 and (n["solo_mendoza"] or n["categoria"] == "nacional"
                                              or n["alcance"] == "nacional"):
            continue
        if modo == "argentina" and not g["nacional"]:
            continue
        horas = max(0.0, (AHORA - n["fecha"]).total_seconds() / 3600)
        frescura = max(0.3, 1 - horas / (VENTANA_HORAS * 1.2))
        if modo == "mendoza":
            cobertura = 1 + 0.25 * (len(g["medios"]) - 1)
            base = pe + 1.5 * min(pm, 6)
        else:  # en lo nacional pesa más que varios medios cubran el tema
            cobertura = 1 + 0.4 * (len(g["medios"]) - 1)
            base = min(pe, 12)
        score = base * PESO_CATEGORIA[n["categoria"]] * frescura * cobertura
        salida.append({**n, "score": round(score, 2), "medios": sorted(g["medios"]),
                       "fecha": n["fecha"].isoformat()})
    salida.sort(key=lambda x: x["score"], reverse=True)
    return salida


def elegir_top(candidatas: list[dict], max_por_fuente: int = MAX_POR_FUENTE) -> list[dict]:
    top, por_fuente = [], {}
    for c in candidatas:
        if por_fuente.get(c["fuente"], 0) >= max_por_fuente:
            continue
        top.append(c)
        por_fuente[c["fuente"]] = por_fuente.get(c["fuente"], 0) + 1
        if len(top) == TOP_N:
            break
    for c in candidatas:  # si el tope por fuente dejó lugares vacíos, se completan
        if len(top) >= TOP_N:
            break
        if c not in top:
            top.append(c)
    return top


def rankear_con_llm(candidatas: list[dict], modo: str = "mendoza") -> list[dict] | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not candidatas:
        return None
    lista = "\n".join(f"[{i}] ({c['medio']}, {c['categoria']}) {c['titulo']} — {c['resumen'][:200]}"
                      for i, c in enumerate(candidatas[:30]))
    foco = ("para la economía de Mendoza (priorizá datos oficiales, empleo, precios, actividad, "
            "inversión, sectores productivos provinciales" if modo == "mendoza" else
            "para la economía argentina (priorizá datos oficiales, inflación, actividad, empleo, "
            "política monetaria y cambiaria, fiscal, deuda, reservas")
    prompt = (
        "Sos un economista que arma un resumen diario para un analista de Mendoza, Argentina. "
        f"De estas notas, elegí las {TOP_N} noticias económicas más relevantes {foco}; "
        "evitá duplicados y notas de color). "
        'Respondé SOLO con JSON: [{"i": <índice>, "resumen": "<una oración neutral>"}]\n\n' + lista
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.environ.get("LLM_MODEL", "claude-haiku-5-5"),
                  "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        texto = r.json()["content"][0]["text"]
        elegidas = json.loads(texto[texto.find("["): texto.rfind("]") + 1])
        top = []
        for e in elegidas[:TOP_N]:
            c = dict(candidatas[int(e["i"])])
            c["resumen_llm"] = e.get("resumen", "")
            top.append(c)
        return top or None
    except Exception as ex:
        print(f"LLM no disponible, uso ranking por palabras clave: {ex}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- salida
def tarjetas_html(top: list[dict]) -> str:
    tarjetas = ""
    for i, n in enumerate(top, 1):
        resumen = n.get("resumen_llm") or n["resumen"][:240]
        f = datetime.fromisoformat(n["fecha"]).strftime("%d/%m %H:%M")
        if n.get("fecha_estimada"):
            f = "detectada hoy"
        tarjetas += f"""
      <article>
        <span class="num">{i}</span>
        <div>
          <a href="{html.escape(n['url'])}" target="_blank" rel="noopener">{html.escape(n['titulo'])}</a>
          <p>{html.escape(resumen)}</p>
          <small>{html.escape(', '.join(n['medios']))} · {f} · {n['categoria']}</small>
        </div>
      </article>"""
    return tarjetas or "<p>No se encontraron noticias que cumplan los criterios hoy.</p>"


def render(top_mza: list[dict], top_arg: list[dict], estado: list[dict], metodo: str,
           archivo: list[str]) -> str:
    fecha_txt = AHORA.strftime("%d/%m/%Y")
    filas = "".join(
        f"<li class='{'ok' if s['ok'] else 'err'}'>{html.escape(s['fuente'])}: "
        f"{s['notas'] if s['ok'] else html.escape(s['error'])}</li>" for s in estado)
    links = "".join(f"<a href='archivo/{d}.html'>{d}</a> " for d in archivo[:30])
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Economía Mendoza y Argentina {fecha_txt}</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--acc:#7a1f2b;--card:#fff;--line:#e6e3dc}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ecebe7;--mut:#a3a19b;--acc:#e0788a;--card:#1f1f1d;--line:#33322f}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 Georgia,serif}}
main{{max-width:760px;margin:0 auto;padding:32px 16px}}
h1{{font-size:1.6rem;margin:0}} h2{{font-size:1.25rem;margin:32px 0 12px;color:var(--acc)}} .sub{{color:var(--mut);margin:4px 0 28px;font-family:system-ui,sans-serif;font-size:.85rem}}
article{{display:flex;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:12px}}
.num{{font-size:1.8rem;color:var(--acc);font-weight:700;min-width:28px}}
article a{{color:var(--fg);font-weight:700;text-decoration:none;font-size:1.05rem}} article a:hover{{color:var(--acc)}}
article p{{margin:6px 0}} small{{color:var(--mut);font-family:system-ui,sans-serif}}
details{{margin-top:28px;font-family:system-ui,sans-serif;font-size:.8rem;color:var(--mut)}}
.err{{color:#c0392b}} .arch a{{color:var(--acc);margin-right:8px}}
</style></head><body><main>
<h1>Noticias económicas del día</h1>
<p class="sub">{fecha_txt} · actualizado {AHORA.strftime('%H:%M')} · ranking: {metodo}</p>
<h2>Top {TOP_N} · Mendoza</h2>
{tarjetas_html(top_mza)}
<h2>Top {TOP_N} · Argentina</h2>
{tarjetas_html(top_arg)}
<details><summary>Estado de las fuentes</summary><ul>{filas}</ul></details>
<details><summary>Días anteriores</summary><p class="arch">{links}</p></details>
</main></body></html>"""


def enviar_mail(cuerpo_html: str) -> None:
    host, user, pwd, dest = (os.environ.get(k) for k in
                             ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO"))
    if not all((host, user, pwd, dest)):
        return
    msg = MIMEText(cuerpo_html, "html", "utf-8")
    msg["Subject"] = f"Economía Mendoza y Argentina – {AHORA:%d/%m/%Y}"
    msg["From"], msg["To"] = user, dest
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", 465))) as s:
        s.login(user, pwd)
        s.sendmail(user, dest.split(","), msg.as_string())


def main() -> None:
    fuentes = yaml.safe_load((BASE / "fuentes.yaml").read_text(encoding="utf-8"))["fuentes"]
    vistos_path = DOCS / "data" / "vistos.json"
    vistos = set(json.loads(vistos_path.read_text())) if vistos_path.exists() else set()

    notas, estado = recolectar(fuentes, vistos)
    grupos = agrupar(notas)
    candidatas = calificar(grupos, "mendoza")
    top = rankear_con_llm(candidatas, "mendoza")
    metodo = "LLM" if top else "palabras clave"
    top = top or elegir_top(candidatas)

    ya = {n["url"] for n in top}
    cand_arg = [c for c in calificar(grupos, "argentina") if c["url"] not in ya]
    top_arg = rankear_con_llm(cand_arg, "argentina") or elegir_top(cand_arg, 3)

    hoy = AHORA.strftime("%Y-%m-%d")
    (DOCS / "archivo").mkdir(parents=True, exist_ok=True)
    (DOCS / "data").mkdir(parents=True, exist_ok=True)
    (DOCS / "data" / f"{hoy}.json").write_text(
        json.dumps({"top_mendoza": top, "top_argentina": top_arg, "estado": estado,
                    "candidatas_mendoza": candidatas[:40], "candidatas_argentina": cand_arg[:40]},
                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    vistos |= {n["url"] for n in notas}
    vistos_path.write_text(json.dumps(sorted(vistos)[-5000:]))

    archivo = sorted((p.stem for p in (DOCS / "archivo").glob("*.html")), reverse=True)
    archivo = [hoy] + [d for d in archivo if d != hoy]
    pagina = render(top, top_arg, estado, metodo, archivo)
    (DOCS / "archivo" / f"{hoy}.html").write_text(pagina.replace("href='archivo/", "href='"),
                                                  encoding="utf-8")
    (DOCS / "index.html").write_text(pagina, encoding="utf-8")
    enviar_mail(pagina)

    print(f"{len(notas)} notas, método {metodo}")
    for nombre, lista in (("MENDOZA", top), ("ARGENTINA", top_arg)):
        print(nombre)
        for n in lista:
            print(f"- [{n['score']}] {n['titulo']} ({n['medio']})")


if __name__ == "__main__":
    main()
