"""
Shaggy Bot — Central de Notícias (v2)
=====================================

Comandos:
    /noticia categoria: IA | RPG | Bots
    s!noticia IA
    s!noticia RPG
    s!noticia Bots

Banco:
    data/noticias.db

Dependências:
    pip install discord.py python-dotenv openai aiohttp feedparser tzdata

.env:
    OPENROUTER_API_KEY=sua_chave
    OPENROUTER_NEWS_MODEL=openrouter/free

O que mudou em relação à v1 (resumo):
    * resumir_com_ia usava variáveis inexistentes (MODELO_NOTICIAS e
      `mensagens`) e o prompt nunca era enviado → sempre dava erro.
    * Se a IA falhar, agora cai automaticamente para o resumo sem IA.
    * Se "ontem" tiver poucas notícias, amplia a janela para alguns dias
      (antes a resposta vinha quase sempre vazia).
    * Pontuação por palavra inteira (antes "api" casava com "capital").
    * Limite de notícias por fonte (arXiv não domina mais o boletim).
    * Links são anexados pelo código, não pela IA (sem links inventados).
    * Texto dividido em vários embeds (limite de 4096 caracteres).
    * Cache no SQLite por (categoria, url): a mesma matéria pode existir
      em mais de uma categoria.
    * Conexões SQLite fechadas e chamadas bloqueantes fora do event loop.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import sqlite3
import unicodedata

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import aiohttp
import discord
import feedparser

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI


# ============================================================
# CONFIGURAÇÃO
# ============================================================

load_dotenv()

logger = logging.getLogger("shaggy.noticias")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "noticias.db"

FUSO = ZoneInfo("America/Sao_Paulo")

MODELO_IA = os.getenv("OPENROUTER_NEWS_MODEL", "openrouter/free")

MAX_NOTICIAS = 10  # máximo exibido no boletim
MIN_NOTICIAS_ONTEM = 3  # abaixo disso, amplia a janela de datas
JANELA_AMPLA_DIAS = 3  # janela de apoio: hoje - 3 dias até agora
MAX_POR_FONTE = 3  # evita que uma fonte domine o boletim
MAX_RESUMO_NOTICIA = 900
DIAS_CACHE = 30  # notícias mais antigas são apagadas do banco
LIMITE_EMBED = 4000  # descrição de embed aceita até 4096
MAX_EMBEDS = 3  # mensagens enviadas por boletim

TIMEOUT_RSS = aiohttp.ClientTimeout(total=20, connect=8)

HEADERS_RSS = {
    "User-Agent": "Mozilla/5.0 (compatible; ShaggyBotNews/2.0; +RSS Reader)",
    "Accept": (
        "application/rss+xml, application/atom+xml, "
        "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"
    ),
}

# Peso por tipo de fonte no ranking final.
BONUS_TIPO = {
    "oficial": 3,
    "imprensa": 2,
    "terceiro": 2,
    "pesquisa": 1,
    "comunidade": 0,
    "agregador": 0,
}


# ============================================================
# FONTES RSS
# ============================================================
#
# tipo:
#   "oficial"    publicado pela própria organização
#   "imprensa"   veículo jornalístico
#   "pesquisa"   repositório/publicação científica
#   "agregador"  resultados reunidos por outro serviço (Google News)
#   "terceiro"   feed mantido por terceiros
#   "comunidade" fórum/comunidade
#
# filtrar:
#   True  → só entra se o texto casar com os termos da categoria.
#   False → a fonte já é 100% do tema (ou a busca já é temática).
# ============================================================


class Fonte(NamedTuple):
    categoria: str
    nome: str
    url: str
    tipo: str
    filtrar: bool = True


def google_news_rss(
    consulta: str,
    idioma: str = "pt-BR",
) -> str:
    base = "https://news.google.com/rss/search?q=" + quote_plus(consulta)

    if idioma == "en-US":
        return base + "&hl=en-US&gl=US&ceid=US:en"

    return base + "&hl=pt-BR&gl=BR&ceid=BR:pt-419"


FEEDS: list[Fonte] = [
    # -------------------- INTELIGÊNCIA ARTIFICIAL --------------------
    Fonte(
        "ia",
        "OpenAI News",
        "https://openai.com/news/rss.xml",
        "oficial",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "Google DeepMind",
        "https://deepmind.google/blog/rss.xml",
        "oficial",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "Hugging Face",
        "https://huggingface.co/blog/feed.xml",
        "oficial",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "arXiv — Inteligência Artificial",
        "https://rss.arxiv.org/rss/cs.AI",
        "pesquisa",
    ),
    Fonte(
        "ia",
        "Anthropic News — feed de terceiros",
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
        "terceiro",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "TechCrunch — IA",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "imprensa",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "Google News — IA e modelos",
        google_news_rss(
            '(OpenAI OR Anthropic OR Claude OR Gemini OR "artificial intelligence") when:3d'
        ),
        "agregador",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "Google News — IA (Brasil)",
        google_news_rss('("inteligência artificial" OR ChatGPT OR "IA generativa") when:3d'),
        "agregador",
        filtrar=False,
    ),
    Fonte(
        "ia",
        "AkitaOnRails — Fabio Akita",
        google_news_rss(
            "site:akitaonrails.com "
            '(IA OR LLM OR "inteligência artificial" OR "coding agents") when:7d'
        ),
        "agregador",
        filtrar=False,
    ),
    # ---------------------------- RPG -------------------------------
    Fonte(
        "rpg",
        "EN World — RPG",
        "https://www.enworld.org/forums/-/index.rss",
        "comunidade",
    ),
    Fonte(
        "rpg",
        "Google News — RPG de mesa",
        google_news_rss(
            '("tabletop RPG" OR "RPG de mesa" OR "roleplaying game" '
            'OR "Dungeons & Dragons" OR Pathfinder) when:3d'
        ),
        "agregador",
        filtrar=False,
    ),
    Fonte(
        "rpg",
        "Google News — RPG (Brasil)",
        google_news_rss('("RPG de mesa" OR "D&D" OR Tormenta20 OR "Ordem Paranormal") when:3d'),
        "agregador",
        filtrar=False,
    ),
    Fonte(
        "rpg",
        "Google News — sistemas e lançamentos de RPG",
        google_news_rss(
            '("tabletop roleplaying" OR "RPG system" OR "TTRPG" '
            'OR "Dungeons and Dragons") when:3d',
            idioma="en-US",
        ),
        "agregador",
        filtrar=False,
    ),
    # ------------------------- BOTS E DEV ---------------------------
    Fonte(
        "bots",
        "Discord Blog",
        "https://discord.com/blog/rss.xml",
        "oficial",
    ),
    Fonte(
        "bots",
        "GitHub Blog",
        "https://github.blog/feed/",
        "oficial",
    ),
    Fonte(
        "bots",
        "Python Insider",
        "https://blog.python.org/feeds/posts/default",
        "oficial",
    ),
    Fonte(
        "bots",
        "Google News — Discord bots",
        google_news_rss(
            '("Discord bot" OR discord.py OR "bot development" '
            'OR "chatbot development") when:3d'
        ),
        "agregador",
        filtrar=False,
    ),
    Fonte(
        "bots",
        "AkitaOnRails — desenvolvimento",
        google_news_rss(
            "site:akitaonrails.com "
            "(programação OR Python OR software OR automação OR tecnologia) when:7d"
        ),
        "agregador",
        filtrar=False,
    ),
]


# ============================================================
# CATEGORIAS
# ============================================================
#
# Os termos são comparados por PALAVRA INTEIRA, então "api" não
# casa mais com "capital" nem "bot" com "robot".
# ============================================================

CATEGORIAS = {
    "ia": {
        "nome": "Inteligência Artificial",
        "emoji": "🧠",
        "cor": discord.Color.blurple(),
        "termos": (
            "ai",
            "ia",
            "artificial intelligence",
            "inteligência artificial",
            "inteligencia artificial",
            "machine learning",
            "aprendizado de máquina",
            "openai",
            "anthropic",
            "claude",
            "chatgpt",
            "gpt",
            "gemini",
            "llm",
            "llms",
            "large language model",
            "modelo de linguagem",
            "neural",
            "deepmind",
            "hugging face",
            "copilot",
            "agentic",
            "ai agent",
            "ai agents",
            "agente de ia",
            "diffusion",
        ),
    },
    "rpg": {
        "nome": "RPG",
        "emoji": "🎲",
        "cor": discord.Color.dark_red(),
        "termos": (
            "rpg",
            "rpgs",
            "roleplaying",
            "role-playing",
            "tabletop",
            "dungeons",
            "dragons",
            "d&d",
            "dnd",
            "pathfinder",
            "starfinder",
            "ttrpg",
            "game master",
            "dungeon master",
            "mestre de jogo",
            "campanha",
            "campaign",
            "worldbuilding",
            "tormenta",
            "call of cthulhu",
        ),
    },
    "bots": {
        "nome": "Bots e Desenvolvimento",
        "emoji": "🤖",
        "cor": discord.Color.green(),
        "termos": (
            "bot",
            "bots",
            "discord",
            "discord.py",
            "chatbot",
            "chatbots",
            "automation",
            "automação",
            "automacao",
            "api",
            "apis",
            "python",
            "github",
            "open source",
            "código aberto",
            "sdk",
            "webhook",
            "webhooks",
            "programação",
            "software",
            "developer",
            "desenvolvedor",
            "pypi",
        ),
    },
}


def _compilar_termos(termos: tuple[str, ...]) -> re.Pattern:
    partes = sorted(termos, key=len, reverse=True)
    padrao = "|".join(re.escape(t) for t in partes)
    return re.compile(rf"(?<!\w)(?:{padrao})(?!\w)", re.IGNORECASE)


for _cfg in CATEGORIAS.values():
    _cfg["regex"] = _compilar_termos(_cfg["termos"])


def normalizar_categoria(texto: str) -> str | None:
    """Converte o que o usuário digitou em 'ia' | 'rpg' | 'bots'."""
    texto = unicodedata.normalize("NFKD", texto.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))

    aliases = {
        "ia": "ia",
        "ai": "ia",
        "inteligencia artificial": "ia",
        "rpg": "rpg",
        "rpgs": "rpg",
        "jogos": "rpg",
        "bots": "bots",
        "bot": "bots",
        "dev": "bots",
        "desenvolvimento": "bots",
        "programacao": "bots",
        "automacao": "bots",
    }

    return aliases.get(texto)


# ============================================================
# BANCO SQLITE
# ============================================================


@contextmanager
def banco():
    """Abre a conexão, faz commit/rollback e SEMPRE fecha."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row

    try:
        with con:
            yield con
    finally:
        con.close()


def inicializar_banco() -> None:
    # Tabela nova: a antiga `noticias` tinha UNIQUE(url), o que impedia
    # a mesma matéria de existir em duas categorias (ex.: AkitaOnRails).
    # A antiga fica intacta e pode ser apagada manualmente.
    with banco() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS noticias_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                titulo TEXT NOT NULL,
                url TEXT NOT NULL,
                fonte TEXT NOT NULL,
                tipo_fonte TEXT NOT NULL,
                publicado_em TEXT NOT NULL,
                descricao TEXT NOT NULL DEFAULT '',
                pontos INTEGER NOT NULL DEFAULT 0,
                coletado_em TEXT NOT NULL,
                UNIQUE (categoria, url)
            )
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cache_categoria_data
            ON noticias_cache (categoria, publicado_em)
            """
        )

        limite = (datetime.now(timezone.utc) - timedelta(days=DIAS_CACHE)).isoformat()

        con.execute(
            "DELETE FROM noticias_cache WHERE publicado_em < ?",
            (limite,),
        )

    logger.info("Banco de notícias pronto: %s", DB_PATH)


def guardar_noticias(categoria: str, artigos: list[dict]) -> None:
    if not artigos:
        return

    agora = datetime.now(timezone.utc).isoformat()

    linhas = [
        (
            categoria,
            a["titulo"],
            a["url"],
            a["fonte"],
            a["tipo_fonte"],
            a["publicado_em"],
            a["descricao"],
            a.get("pontos", 0),
            agora,
        )
        for a in artigos
    ]

    with banco() as con:
        con.executemany(
            """
            INSERT INTO noticias_cache (
                categoria, titulo, url, fonte, tipo_fonte,
                publicado_em, descricao, pontos, coletado_em
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (categoria, url) DO UPDATE SET
                titulo = excluded.titulo,
                fonte = excluded.fonte,
                tipo_fonte = excluded.tipo_fonte,
                publicado_em = excluded.publicado_em,
                pontos = excluded.pontos,
                descricao = CASE
                    WHEN excluded.descricao != '' THEN excluded.descricao
                    ELSE noticias_cache.descricao
                END
            """,
            linhas,
        )


def obter_cache(
    categoria: str,
    inicio: datetime,
    fim: datetime,
) -> list[dict]:
    with banco() as con:
        rows = con.execute(
            """
            SELECT titulo, url, fonte, tipo_fonte,
                   publicado_em, descricao, pontos
            FROM noticias_cache
            WHERE categoria = ?
              AND publicado_em >= ?
              AND publicado_em < ?
            ORDER BY publicado_em DESC
            """,
            (categoria, inicio.isoformat(), fim.isoformat()),
        ).fetchall()

    return [dict(r) for r in rows]


# ============================================================
# UTILITÁRIOS DE RSS
# ============================================================


def limpar_html(texto: str | None) -> str:
    if not texto:
        return ""

    texto = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)
    return re.sub(r"\s+", " ", texto).strip()


def limpar_descricao(descricao: str, titulo: str) -> str:
    # arXiv: "arXiv:2501.00001v1 Announce Type: new Abstract: ..."
    descricao = re.sub(
        r"^arXiv:\S+\s+Announce Type:\s*\S+\s+Abstract:\s*",
        "",
        descricao,
        flags=re.IGNORECASE,
    )

    # Google News devolve a própria manchete como "descrição".
    base_titulo = re.sub(r"\W+", "", titulo.lower())
    base_desc = re.sub(r"\W+", "", descricao.lower())

    if not base_desc or base_desc.startswith(base_titulo[:60]):
        return ""

    return descricao[:MAX_RESUMO_NOTICIA]


def obter_data(entry) -> datetime | None:
    estrutura = entry.get("published_parsed") or entry.get("updated_parsed")

    if estrutura:
        try:
            return datetime(*estrutura[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass

    for campo in ("published", "updated", "created"):
        valor = entry.get(campo)

        if not valor:
            continue

        valor = str(valor).strip()

        try:
            data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            try:
                data = parsedate_to_datetime(valor)
            except (TypeError, ValueError):
                continue

        if data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)

        return data.astimezone(timezone.utc)

    # Sem data verificável, não inventamos uma.
    return None


def pontuar_artigo(titulo: str, descricao: str, categoria: str) -> int:
    regex = CATEGORIAS[categoria]["regex"]

    no_titulo = {m.lower() for m in regex.findall(titulo)}
    no_texto = {m.lower() for m in regex.findall(f"{titulo} {descricao}")}

    pontos = 2 * len(no_titulo) + len(no_texto - no_titulo)
    return min(pontos, 10)


def limpar_titulo_agregador(titulo: str) -> str:
    # Google News: "Manchete - Veículo"
    return re.sub(r"\s+[-–—]\s+[^-–—]{2,60}$", "", titulo).strip()


def chave_titulo(titulo: str) -> str:
    return re.sub(r"\W+", "", limpar_titulo_agregador(titulo).lower())


# ============================================================
# COLETA DOS FEEDS
# ============================================================


async def baixar_feed(
    session: aiohttp.ClientSession,
    fonte: Fonte,
) -> bytes | None:
    for tentativa in (1, 2):
        try:
            async with session.get(
                fonte.url,
                headers=HEADERS_RSS,
                allow_redirects=True,
            ) as resposta:
                if resposta.status == 200:
                    return await resposta.read()

                logger.warning(
                    "Feed '%s' retornou HTTP %s (tentativa %s)",
                    fonte.nome,
                    resposta.status,
                    tentativa,
                )

                if resposta.status in (401, 403, 404, 410):
                    return None  # insistir não adianta

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Falha ao ler feed '%s' (tentativa %s): %s",
                fonte.nome,
                tentativa,
                exc,
            )

        await asyncio.sleep(1)

    return None


def extrair_artigos(
    feed,
    fonte: Fonte,
    categoria: str,
    inicio: datetime,
    fim: datetime,
) -> list[dict]:
    artigos = []

    for entry in feed.entries[:200]:
        titulo = limpar_html(entry.get("title", ""))
        url = str(entry.get("link", "")).strip()

        if not titulo or not url.startswith(("http://", "https://")):
            continue

        data = obter_data(entry)

        if data is None or not (inicio <= data < fim):
            continue

        origem = fonte.nome

        if fonte.tipo == "agregador":
            titulo = limpar_titulo_agregador(titulo)

            # Google News informa o veículo original em <source>.
            veiculo = limpar_html((entry.get("source") or {}).get("title", ""))

            if veiculo:
                origem = veiculo

        descricao = limpar_descricao(
            limpar_html(entry.get("summary") or entry.get("description") or ""),
            titulo,
        )

        pontos = pontuar_artigo(titulo, descricao, categoria)

        if fonte.filtrar and pontos == 0:
            continue

        artigos.append(
            {
                "titulo": titulo[:300],
                "url": url.split("#")[0],
                "fonte": origem,
                "tipo_fonte": fonte.tipo,
                "publicado_em": data.isoformat(),
                "descricao": descricao,
                "pontos": pontos,
            }
        )

    return artigos


async def ler_feed(
    session: aiohttp.ClientSession,
    fonte: Fonte,
    categoria: str,
    inicio: datetime,
    fim: datetime,
) -> list[dict]:
    conteudo = await baixar_feed(session, fonte)

    if conteudo is None:
        return []

    # feedparser é síncrono e pesado em feeds grandes (arXiv).
    feed = await asyncio.to_thread(feedparser.parse, conteudo)

    if not feed.entries:
        logger.warning(
            "Feed '%s' veio sem entradas (bozo=%s).",
            fonte.nome,
            getattr(feed, "bozo", None),
        )
        return []

    artigos = extrair_artigos(feed, fonte, categoria, inicio, fim)

    logger.info(
        "Feed '%s': %s entradas, %s aproveitadas.",
        fonte.nome,
        len(feed.entries),
        len(artigos),
    )

    return artigos


def deduplicar(artigos: list[dict]) -> list[dict]:
    """Remove repetidos por URL e por título, mantendo o de maior nota."""
    ordenados = sorted(
        artigos,
        key=lambda a: (a.get("pontos", 0), a["publicado_em"]),
        reverse=True,
    )

    urls, titulos, unicos = set(), set(), []

    for artigo in ordenados:
        url = artigo["url"].rstrip("/")
        titulo = chave_titulo(artigo["titulo"])

        if url in urls or titulo in titulos:
            continue

        urls.add(url)
        titulos.add(titulo)
        artigo["url"] = url
        unicos.append(artigo)

    return unicos


def selecionar(artigos: list[dict], limite: int = MAX_NOTICIAS) -> list[dict]:
    """Ranking por nota + tipo de fonte + data, com teto por fonte."""

    def nota(a: dict) -> tuple:
        return (
            a.get("pontos", 0) + BONUS_TIPO.get(a.get("tipo_fonte", ""), 0),
            a["publicado_em"],
        )

    ordenados = sorted(artigos, key=nota, reverse=True)

    escolhidos, contagem, sobras = [], {}, []

    for artigo in ordenados:
        fonte = artigo["fonte"]

        if contagem.get(fonte, 0) < MAX_POR_FONTE:
            escolhidos.append(artigo)
            contagem[fonte] = contagem.get(fonte, 0) + 1
        else:
            sobras.append(artigo)

        if len(escolhidos) >= limite:
            break

    # Se sobrou espaço, completa com o que o teto por fonte deixou de fora.
    for artigo in sobras:
        if len(escolhidos) >= limite:
            break
        escolhidos.append(artigo)

    escolhidos.sort(key=lambda a: a["publicado_em"], reverse=True)
    return escolhidos


async def coletar_noticias(categoria: str) -> tuple[list[dict], str]:
    """
    Retorna (artigos, rótulo_do_período).

    Tenta "ontem". Se houver menos de MIN_NOTICIAS_ONTEM, usa uma
    janela de alguns dias (e diz isso no rótulo — sem fingir).
    """
    agora = datetime.now(FUSO)
    hoje = agora.date()

    ini_ontem = datetime.combine(hoje - timedelta(days=1), time.min, tzinfo=FUSO)
    ini_hoje = datetime.combine(hoje, time.min, tzinfo=FUSO)
    ini_amplo = datetime.combine(
        hoje - timedelta(days=JANELA_AMPLA_DIAS), time.min, tzinfo=FUSO
    )
    fim_amplo = agora + timedelta(minutes=15)

    ini_amplo_utc = ini_amplo.astimezone(timezone.utc)
    fim_amplo_utc = fim_amplo.astimezone(timezone.utc)
    ini_ontem_utc = ini_ontem.astimezone(timezone.utc)
    ini_hoje_utc = ini_hoje.astimezone(timezone.utc)

    fontes = [f for f in FEEDS if f.categoria == categoria]

    async with aiohttp.ClientSession(timeout=TIMEOUT_RSS) as session:
        resultados = await asyncio.gather(
            *(
                ler_feed(session, f, categoria, ini_amplo_utc, fim_amplo_utc)
                for f in fontes
            ),
            return_exceptions=True,
        )

    coletados: list[dict] = []

    for fonte, resultado in zip(fontes, resultados):
        if isinstance(resultado, Exception):
            logger.warning("Erro inesperado no feed '%s': %r", fonte.nome, resultado)
            continue

        coletados.extend(resultado)

    # Persiste e mescla com o cache (cobre feeds que falharam agora).
    await asyncio.to_thread(guardar_noticias, categoria, coletados)
    em_cache = await asyncio.to_thread(
        obter_cache, categoria, ini_amplo_utc, fim_amplo_utc
    )

    todos = deduplicar(coletados + em_cache)

    ontem = [
        a
        for a in todos
        if ini_ontem_utc <= datetime.fromisoformat(a["publicado_em"]) < ini_hoje_utc
    ]

    if len(ontem) >= MIN_NOTICIAS_ONTEM:
        rotulo = f"ontem, {ini_ontem:%d/%m/%Y}"
        return selecionar(ontem), rotulo

    if todos:
        rotulo = (
            f"{ini_amplo:%d/%m} a {agora:%d/%m/%Y} "
            f"(ontem teve poucas publicações)"
        )
        return selecionar(todos), rotulo

    return [], f"ontem, {ini_ontem:%d/%m/%Y}"


# ============================================================
# RESUMO COM OPENROUTER
# ============================================================

PROMPT_SISTEMA = """\
Você é o editor do boletim de notícias do Shaggy Bot, um bot de Discord.
Escreva em português brasileiro, com clareza e precisão.

Regras:
- Use SOMENTE as informações do material fornecido.
- Não invente fatos, datas, números ou declarações.
- Você recebeu dados de RSS, não os artigos completos: não diga que leu a matéria.
- Se a descrição for insuficiente, diga que o feed não trouxe detalhes.
- Não transforme rumor em fato. Não complete a lista artificialmente.
- NÃO escreva links nem URLs: eles são adicionados automaticamente.
"""


def resumir_com_ia(
    client: OpenAI,
    categoria: str,
    artigos: list[dict],
    periodo: str,
) -> str:
    material = []

    for n, artigo in enumerate(artigos, start=1):
        descricao = artigo.get("descricao") or "O feed não forneceu descrição."

        material.append(
            f"[{n}] TÍTULO: {artigo['titulo']}\n"
            f"FONTE: {artigo['fonte']} ({artigo['tipo_fonte']})\n"
            f"DATA: {artigo['publicado_em'][:10]}\n"
            f"DESCRIÇÃO: {descricao[:700]}"
        )

    pedido = (
        f"Categoria: {CATEGORIAS[categoria]['nome']}\n"
        f"Período: {periodo}\n\n"
        "Formato para cada notícia, na mesma numeração do material:\n"
        "N. **Título** — Fonte\n"
        "Resumo em no máximo 2 frases.\n\n"
        "Ao final, escreva a seção **O panorama** com no máximo 3 "
        "observações curtas que o material sustente.\n"
        "Seja conciso: o boletim inteiro deve ter menos de 3500 caracteres.\n\n"
        "MATERIAL:\n\n" + "\n\n".join(material)
    )

    resposta = client.chat.completions.create(
        model=MODELO_IA,
        messages=[
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": pedido},
        ],
        temperature=0.3,
        max_tokens=2500,
    )

    if not resposta.choices:
        raise RuntimeError(f"O modelo não retornou escolhas: {resposta}")

    escolha = resposta.choices[0]
    texto = (escolha.message.content or "").strip()

    if len(texto) < 50:
        raise RuntimeError(
            f"Resumo vazio ou curto demais (finish_reason={escolha.finish_reason})."
        )

    return texto


def montar_links(artigos: list[dict]) -> str:
    linhas = ["**🔗 Links**"]

    for n, artigo in enumerate(artigos, start=1):
        fonte = artigo["fonte"][:40]
        linhas.append(f"{n}. [{fonte}]({artigo['url']})")

    return "\n".join(linhas)


def resumo_sem_ia(artigos: list[dict], periodo: str) -> str:
    blocos = [f"**Publicações de {periodo}:**"]

    for n, artigo in enumerate(artigos, start=1):
        descricao = artigo.get("descricao") or "O feed não forneceu descrição."

        if len(descricao) > 240:
            descricao = descricao[:240].rstrip() + "…"

        blocos.append(
            f"**{n}. {artigo['titulo']}**\n"
            f"{descricao}\n"
            f"*{artigo['fonte']}* • "
            f"[Ler publicação]({artigo['url']})"
        )

    return "\n\n".join(blocos)


def dividir_texto(texto: str, limite: int = LIMITE_EMBED) -> list[str]:
    """Divide em pedaços ≤ limite, quebrando em parágrafos."""
    partes, atual = [], ""

    for paragrafo in texto.split("\n\n"):
        while len(paragrafo) > limite:
            corte = paragrafo.rfind(" ", 0, limite)
            corte = corte if corte > 0 else limite
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(paragrafo[:corte])
            paragrafo = paragrafo[corte:].lstrip()

        candidato = f"{atual}\n\n{paragrafo}" if atual else paragrafo

        if len(candidato) <= limite:
            atual = candidato
        else:
            partes.append(atual)
            atual = paragrafo

    if atual:
        partes.append(atual)

    return partes


# ============================================================
# COG DISCORD
# ============================================================


class Noticias(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client: OpenAI | None = None

        chave = os.getenv("OPENROUTER_API_KEY")

        if chave:
            self.client = OpenAI(
                api_key=chave,
                base_url="https://openrouter.ai/api/v1",
                timeout=40.0,
                max_retries=0,
            )
        else:
            logger.warning(
                "OPENROUTER_API_KEY não configurada. O comando usará resumos sem IA."
            )

        inicializar_banco()

    # --------------------------------------------------------
    # /noticia
    # --------------------------------------------------------

    @app_commands.command(
        name="noticia",
        description="Receba até 10 notícias recentes resumidas.",
    )
    @app_commands.describe(categoria="Escolha a categoria do boletim")
    @app_commands.choices(
        categoria=[
            app_commands.Choice(name="🧠 Inteligência Artificial", value="ia"),
            app_commands.Choice(name="🎲 RPG", value="rpg"),
            app_commands.Choice(name="🤖 Bots e Desenvolvimento", value="bots"),
        ]
    )
    @app_commands.checks.cooldown(
        1,
        60.0,
        key=lambda interaction: interaction.user.id,
    )
    async def noticia_slash(
        self,
        interaction: discord.Interaction,
        categoria: app_commands.Choice[str],
    ):
        await interaction.response.defer(thinking=True)
        await self.executar(interaction, categoria.value)

    # --------------------------------------------------------
    # s!noticia
    # --------------------------------------------------------

    @commands.command(name="noticia", aliases=["noticias", "news"])
    @commands.cooldown(1, 60.0, commands.BucketType.user)
    async def noticia_prefixo(
        self,
        ctx: commands.Context,
        *,
        categoria: str = "",
    ):
        chave = normalizar_categoria(categoria)

        if chave is None:
            # Não gasta o cooldown quando o usuário só errou o comando.
            ctx.command.reset_cooldown(ctx)
            await ctx.send(
                "Escolha uma categoria:\n"
                "`s!noticia IA`\n"
                "`s!noticia RPG`\n"
                "`s!noticia Bots`"
            )
            return

        async with ctx.typing():
            await self.executar(ctx, chave)

    # --------------------------------------------------------
    # PROCESSAMENTO CENTRAL
    # --------------------------------------------------------

    async def executar(self, destino, categoria: str):
        config = CATEGORIAS[categoria]
        aviso = ""
        artigos: list[dict] = []
        periodo = "ontem"

        try:
            artigos, periodo = await asyncio.wait_for(
                coletar_noticias(categoria),
                timeout=60,
            )

            if not artigos:
                texto = (
                    f"Não encontrei notícias com data verificável "
                    f"({periodo}) nesta categoria.\n\n"
                    "Os feeds podem não ter publicado, ou estar "
                    "temporariamente indisponíveis. Não vou inventar "
                    "notícias para completar a lista."
                )
            else:
                texto = None

                if self.client:
                    try:
                        texto = await asyncio.wait_for(
                            asyncio.to_thread(
                                resumir_com_ia,
                                self.client,
                                categoria,
                                artigos,
                                periodo,
                            ),
                            timeout=50,
                        )
                        texto = f"**Publicações de {periodo}**\n\n{texto}\n\n"
                        texto += montar_links(artigos)

                    except Exception:
                        # Qualquer falha da IA (timeout, cota, modelo
                        # fora do ar…) não derruba o boletim.
                        logger.exception("Falha ao resumir com IA; usando fallback.")
                        texto = None
                        aviso = "⚠️ Resumo por IA indisponível agora — exibindo o texto original dos feeds.\n\n"

                if texto is None:
                    texto = aviso + resumo_sem_ia(artigos, periodo)

        except asyncio.TimeoutError:
            logger.warning("Timeout na coleta de notícias: %s", categoria)
            texto = "A pesquisa demorou mais que o esperado. Tente novamente em instantes."
            artigos = []

        except Exception:
            logger.exception("Erro ao montar o boletim de '%s'", categoria)
            texto = (
                "Ocorreu um erro ao montar o boletim. "
                "Confira os logs do Shaggy."
            )
            artigos = []

        partes = dividir_texto(texto)[:MAX_EMBEDS]

        for i, parte in enumerate(partes):
            embed = discord.Embed(
                description=parte,
                color=config["cor"],
            )

            if i == 0:
                embed.title = f"{config['emoji']} Boletim Shaggy — {config['nome']}"

            if i == len(partes) - 1:
                embed.set_footer(text=f"RSS + SQLite • {len(artigos)} notícia(s)")
                embed.timestamp = datetime.now(timezone.utc)

            await self.enviar(destino, embed=embed)

    # --------------------------------------------------------
    # ENVIO DISCORD
    # --------------------------------------------------------

    @staticmethod
    async def enviar(
        destino,
        mensagem: str | None = None,
        *,
        embed: discord.Embed | None = None,
    ):
        # Só envia os campos preenchidos: passar embed=None ao
        # followup.send pode gerar erro dependendo da versão.
        kwargs = {"allowed_mentions": discord.AllowedMentions.none()}

        if mensagem:
            kwargs["content"] = mensagem

        if embed is not None:
            kwargs["embed"] = embed

        if isinstance(destino, discord.Interaction):
            await destino.followup.send(**kwargs)
        else:
            await destino.send(**kwargs)

    # --------------------------------------------------------
    # ERROS DE COMANDO
    # --------------------------------------------------------

    @noticia_prefixo.error
    async def noticia_prefixo_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Aguarde **{error.retry_after:.0f} segundos** "
                "antes de pesquisar notícias novamente."
            )
            return

        logger.error("Erro no comando s!noticia", exc_info=error)
        await ctx.send("Não consegui executar a pesquisa de notícias.")

    @noticia_slash.error
    async def noticia_slash_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            mensagem = (
                f"⏳ Aguarde {error.retry_after:.0f}s antes de "
                "pesquisar notícias novamente."
            )
        else:
            logger.error("Erro no comando /noticia", exc_info=error)
            mensagem = "Não consegui executar a pesquisa de notícias."

        if interaction.response.is_done():
            await interaction.followup.send(mensagem, ephemeral=True)
        else:
            await interaction.response.send_message(mensagem, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Noticias(bot))
