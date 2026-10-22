"""
Shaggy Bot — Pets Virtuais
==========================

Pets:
- Cthulhu de Bolso
- Pinguim Mago
- Gato Cósmico

O diretório e os arquivos de imagem NÃO foram alterados: IMAGE_DIR, o
dicionário PETS e os nomes de arquivo continuam exatamente como antes. As
imagens só são lidas (nunca renomeadas, movidas ou gravadas).

Comandos (o prefixo exibido nas mensagens vem do próprio bot, ex.: s!):
    pet                  ficha do pet ativo, com botões de ação
    pet adotar           adotar ou retomar um mascote
    pet trocar           trocar de pet ou adotar outro
    pet embora           despedir-se do pet ativo (fica no santuário)
    pet santuario        todos os seus mascotes
    pet status           ficha do pet ativo
    pet alimentar        recupera fome
    pet brincar          aumenta felicidade e XP
    pet carinho          afago rápido (NOVO)
    pet habilidade       habilidade especial de cada pet (NOVO)
    pet diario           histórico de cuidados do pet (NOVO)
    pet ver @membro      ficha do pet de outro membro (NOVO)
    pet ranking          melhores pets do servidor (NOVO)
    pet catalogo         espécies, estágios e habilidades (NOVO)
    pet renomear NOME    muda o nome
    pet ajuda            guia

NOVIDADES
---------
- Humor (derivado da fome e da felicidade) com falas próprias de cada pet.
- Estágios cosméticos por nível, por pet (sugestão de expansão, não cânone).
- Carinho e Habilidade Especial (desbloqueia no nível 3), cada pet com a sua.
- Diário de cuidados e contadores por pet.
- Botões na ficha (Alimentar, Brincar, Carinho, Habilidade).
- Ações atômicas: cooldown, efeito e XP na mesma transação (sem cliques duplos).
- Nenhuma ação dá Abysmus: tudo aqui só afeta o próprio pet.

CORREÇÕES
---------
- A perda de fome/felicidade não era mais aplicada se você cuidasse do pet a
  cada menos de 1 hora (o relógio era reiniciado). Agora o relógio de
  decaimento só avança pelas horas realmente cobradas.
- Cooldowns e erros dos subcomandos agora respondem no chat.
- "adotar" volta a permitir retomar pets guardados e "trocar" permite adotar
  um novo (como a ajuda e o texto do menu já prometiam).
- Conexões SQLite são fechadas; chamadas de banco não bloqueiam o loop.
- Nomes não podem mais conter menções e as respostas não notificam ninguém.
- Botões expirados são desativados na própria mensagem.

Compatibilidade:
- discord.py 2.x
- SQLite (migra a tabela virtual_pets do protótipo e acrescenta colunas novas
  a pet_collection sem apagar dados)
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import discord
from discord.ext import commands


log = logging.getLogger("shaggy.pet")


# ============================================================
# CAMINHOS E CONFIGURAÇÕES
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
IMAGE_DIR = ROOT / "assets" / "pets"
DB_PATH = DATA_DIR / "shaggy.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

FOME_MAX = 100
FELICIDADE_MAX = 100

PERDA_FOME_HORA = 3
PERDA_FELICIDADE_HORA = 2

XP_ALIMENTAR = 3
XP_BRINCAR = 10
XP_CARINHO = 2
XP_HABILIDADE = 15
XP_POR_NIVEL = 100

GANHO_ALIMENTAR = 35
GANHO_BRINCAR = 25
GANHO_CARINHO = 8

COOLDOWN_ALIMENTAR = 30 * 60
COOLDOWN_BRINCAR = 15 * 60
COOLDOWN_CARINHO = 5 * 60
COOLDOWN_HABILIDADE = 3 * 60 * 60

# Nível necessário para usar a habilidade especial.
NIVEL_HABILIDADE = 3

# Nunca notificar ninguém por causa de nomes de pets ou membros.
SEM_MENCOES = discord.AllowedMentions.none()


PETS = {
    "cthulhu": {
        "nome": "Cthulhu de Bolso",
        "emoji": "🐙",
        "imagem": "cthulhu.png",
        "personalidade": "Misterioso e caótico",
        "descricao": (
            "Uma pequena entidade cósmica que adora comida "
            "e sussurra segredos impossíveis."
        ),
    },
    "pinguim": {
        "nome": "Pinguim Mago",
        "emoji": "🐧",
        "imagem": "pinguim_mago.png",
        "personalidade": "Estudioso e desastrado",
        "descricao": (
            "Um mago de penas que estuda feitiços antigos "
            "e às vezes conjura peixes por acidente."
        ),
    },
    "gato": {
        "nome": "Gato Cósmico",
        "emoji": "🐈",
        "imagem": "gato_cosmico.png",
        "personalidade": "Curioso e imprevisível",
        "descricao": (
            "Um felino de outra galáxia que parece conhecer "
            "segredos escondidos no universo."
        ),
    },
}


# ============================================================
# PERSONALIDADE DOS PETS (textos; sugestões de expansão, não cânone)
# ============================================================

# Estágios cosméticos: níveis 1, 5, 10 e 20.
NIVEIS_ESTAGIO = (1, 5, 10, 20)

ESTAGIOS = {
    "cthulhu": ("Filhote Sussurrante", "Tentáculo Aprendiz",
                "Arauto de Bolso", "Entidade Anciã em Miniatura"),
    "pinguim": ("Aprendiz de Gelo", "Mago de Penas",
                "Arquimago Desastrado", "Grão-Mestre dos Peixes"),
    "gato": ("Gatinho Estelar", "Caminhante de Constelações",
             "Felino Interdimensional", "Soberano Cósmico"),
}

FRASES = {
    "cthulhu": {
        "alimentar": (
            "devora a refeição sussurrando em línguas que não existem.",
            "engole tudo e deixa um tentáculo satisfeito no seu ombro.",
        ),
        "brincar": (
            "transforma a brincadeira num ritual caótico e adorável.",
            "persegue a própria sombra e diz que perdeu de propósito.",
        ),
        "carinho": (
            "estremece de prazer e brilha em roxo por um instante.",
            "enrola um tentáculo no seu dedo e não solta mais.",
        ),
    },
    "pinguim": {
        "alimentar": (
            "come com pose de arquimago e derruba metade dos peixes.",
            "agradece a comida com uma reverência e um pequeno feitiço torto.",
        ),
        "brincar": (
            "tenta ensinar você a conjurar e acaba escorregando no gelo.",
            "organiza um duelo de magia contra uma almofada. A almofada venceu.",
        ),
        "carinho": (
            "estufa o peito, ajeita o chapéu e finge que não gostou.",
            "pisca devagar e solta uma faísca de gelo de pura alegria.",
        ),
    },
    "gato": {
        "alimentar": (
            "inspeciona a comida como se fosse um mapa estelar e então devora.",
            "come, olha para o nada e parece ter descoberto um segredo.",
        ),
        "brincar": (
            "some por um instante e reaparece em cima de uma estante.",
            "persegue algo que só ele vê e diz que valeu a pena.",
        ),
        "carinho": (
            "ronrona numa frequência que faz as luzes tremerem de leve.",
            "empurra a cabeça contra sua mão e cobra mais.",
        ),
    },
}

FALAS_HUMOR = {
    "cthulhu": {
        "radiante": "Sussurra algo animado. Você preferiu não entender.",
        "contente": "Brilha em roxo e observa você com carinho.",
        "tranquilo": "Boia por perto, tentáculos relaxados.",
        "faminto": "Seus tentáculos apontam para a cozinha, insistentes.",
        "carente": "Fica em silêncio. Um silêncio muito alto.",
        "abatido": "Sussurra um nome. O seu. Em tom de queixa.",
    },
    "pinguim": {
        "radiante": "Dá uma pirueta mágica e faz neve cair na sala.",
        "contente": "Folheia um grimório enquanto balança as nadadeiras.",
        "tranquilo": "Estuda um feitiço, com a língua para fora de concentração.",
        "faminto": "Conjurou um peixe de mentirinha e ficou ainda mais triste.",
        "carente": "Joga o chapéu no chão com um suspiro dramático.",
        "abatido": "Escreve 'ajuda' no gelo com a ponta do cajado.",
    },
    "gato": {
        "radiante": "Ronrona em três frequências e flutua um dedo acima do chão.",
        "contente": "Pisca devagar. É a forma felina de dizer 'gosto de você'.",
        "tranquilo": "Observa uma constelação que só ele consegue ver.",
        "faminto": "Derruba um objeto da mesa olhando fixo para você.",
        "carente": "Finge indiferença, mas dorme encostado na sua sombra.",
        "abatido": "Mia para uma estrela distante e ela não responde.",
    },
}

SEGREDOS_CTHULHU = (
    "Existe uma porta no fim do corredor que só abre quando ninguém olha.",
    "A névoa guarda seu nome desde antes de você nascer. Ela o pronuncia errado.",
    "Todo relógio parado marca a hora em que algo foi esquecido de propósito.",
    "O eco da sua casa responde com um segundo de atraso. Ele está aprendendo.",
    "Sob a cama não há monstros. Há uma biblioteca, e eles são os bibliotecários.",
    "Quando o céu de Da'kor fica roxo, uma mensagem é entregue. Ninguém a lê.",
)

PROFECIAS_GATO = (
    "Hoje você encontrará algo que perdeu... e perderá outra coisa no lugar.",
    "Uma decisão pequena mudará a cor do seu amanhã. Provavelmente para azul.",
    "Alguém pensará em você às 3h17. Não precisa responder.",
    "Evite caixas de papelão. Menos por perigo e mais por inveja minha.",
    "A estrela que você ignorou ontem estava tentando avisar algo sobre o café.",
    "Você vai ouvir uma boa notícia hoje, mas só depois de reclamar da internet.",
)


@dataclass
class EfeitoHabilidade:
    texto: str
    fome: int = 0
    felicidade: int = 0


@dataclass(frozen=True)
class Habilidade:
    titulo: str
    descricao: str
    executar: Callable[[str], EfeitoHabilidade]


def _hab_cthulhu(nome: str) -> EfeitoHabilidade:
    segredo = random.choice(SEGREDOS_CTHULHU)
    return EfeitoHabilidade(f"**{nome}** sussurra: *\"{segredo}\"*",
                            felicidade=10)


def _hab_pinguim(nome: str) -> EfeitoHabilidade:
    if random.random() < 0.7:
        return EfeitoHabilidade(
            f"🐟 **{nome}** conjura um banquete de peixes brilhantes!",
            fome=25, felicidade=5)
    return EfeitoHabilidade(
        f"🐟 O feitiço de **{nome}** dá errado: chovem peixes na sua cabeça. "
        "Ele ri até perder o equilíbrio.", felicidade=15)


def _hab_gato(nome: str) -> EfeitoHabilidade:
    profecia = random.choice(PROFECIAS_GATO)
    return EfeitoHabilidade(f"**{nome}** encara o infinito e declara: "
                            f"*\"{profecia}\"*", felicidade=10)


HABILIDADES = {
    "cthulhu": Habilidade(
        "Sussurro do Abismo",
        "Revela um segredo impossível e alegra o pet (+10 💖).",
        _hab_cthulhu),
    "pinguim": Habilidade(
        "Feitiço Desastrado",
        "70%: conjura um banquete (+25 🍖). Senão, chovem peixes (+15 💖).",
        _hab_pinguim),
    "gato": Habilidade(
        "Profecia Cósmica",
        "Declara uma profecia (puramente cômica) e alegra o pet (+10 💖).",
        _hab_gato),
}


# ============================================================
# REGRAS PURAS (humor, estágio, XP, formatação)
# ============================================================

def calcular_humor(fome: int, felicidade: int) -> tuple[str, str, str]:
    """Retorna (chave, emoji, rótulo) do humor, derivado dos atributos."""
    if fome <= 20 and felicidade <= 20:
        return "abatido", "😢", "Abatido"
    if fome <= 20:
        return "faminto", "😫", "Faminto"
    if felicidade <= 20:
        return "carente", "🥺", "Carente"
    media = (fome + felicidade) / 2
    if media >= 85:
        return "radiante", "🤩", "Radiante"
    if media >= 60:
        return "contente", "😊", "Contente"
    return "tranquilo", "😐", "Tranquilo"


def estagio(pet_id: str, nivel: int) -> str:
    nomes = ESTAGIOS[pet_id]
    indice = 0
    for i, minimo in enumerate(NIVEIS_ESTAGIO):
        if nivel >= minimo:
            indice = i
    return nomes[indice]


def somar_xp(nivel: int, xp: int, quantidade: int) -> tuple[int, int, int]:
    """Soma XP e devolve (nível, xp, níveis ganhos)."""
    xp += max(0, quantidade)
    ganhos = 0
    while xp >= XP_POR_NIVEL * nivel:
        xp -= XP_POR_NIVEL * nivel
        nivel += 1
        ganhos += 1
    return nivel, xp, ganhos


def limitar(valor: int, minimo: int = 0, maximo: int = 100) -> int:
    return max(minimo, min(maximo, valor))


def formatar_tempo(segundos: int) -> str:
    segundos = max(0, int(segundos))
    if segundos < 3600:
        return f"{max(1, math.ceil(segundos / 60))} min"
    horas, resto = divmod(segundos, 3600)
    minutos = math.ceil(resto / 60)
    if minutos == 60:
        horas, minutos = horas + 1, 0
    return f"{horas}h{minutos:02d}"


def limpar_nome(nome: str) -> Optional[str]:
    """Normaliza o nome de um pet. None se for inválido."""
    nome = "".join(c for c in nome if c.isprintable())
    nome = nome.replace("@", "")
    nome = " ".join(nome.split())
    if not nome or len(nome) > 32:
        return None
    return nome


# ============================================================
# BANCO DE DADOS
# ============================================================

COLUNAS_NOVAS = {
    "ultimo_carinho": "REAL NOT NULL DEFAULT 0",
    "ultima_habilidade": "REAL NOT NULL DEFAULT 0",
    "vezes_alimentado": "INTEGER NOT NULL DEFAULT 0",
    "vezes_brincou": "INTEGER NOT NULL DEFAULT 0",
    "vezes_carinho": "INTEGER NOT NULL DEFAULT 0",
    "vezes_habilidade": "INTEGER NOT NULL DEFAULT 0",
}


def conectar_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 15000")
    return con


@contextmanager
def leitura():
    """Conexão somente para leituras; sempre fechada ao final."""
    con = conectar_db()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def transacao():
    """Transação única: confirma no fim, desfaz em qualquer erro."""
    con = conectar_db()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def inicializar_banco() -> None:
    """Cria a coleção, acrescenta colunas novas e migra o protótipo antigo."""
    with transacao() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pet_collection (
                user_id INTEGER NOT NULL,
                pet_id TEXT NOT NULL,
                nome TEXT NOT NULL,
                nivel INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                fome INTEGER NOT NULL DEFAULT 100,
                felicidade INTEGER NOT NULL DEFAULT 100,
                criado_em REAL NOT NULL,
                atualizado_em REAL NOT NULL,
                ultima_alimentacao REAL NOT NULL,
                ultima_brincadeira REAL NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, pet_id)
            )
            """
        )

        # Colunas das funções novas (bancos antigos não as possuem).
        existentes = {
            r["name"]
            for r in con.execute("PRAGMA table_info(pet_collection)").fetchall()
        }
        for coluna, definicao in COLUNAS_NOVAS.items():
            if coluna not in existentes:
                con.execute(
                    f"ALTER TABLE pet_collection ADD COLUMN {coluna} {definicao}"
                )
                log.info("Migração: coluna %s adicionada.", coluna)

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pet_collection_active
            ON pet_collection(user_id, ativo)
            """
        )

        # Migra os dados do cog antigo sem apagá-los.
        tabela_existe = con.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'virtual_pets'
            """
        ).fetchone()

        if tabela_existe:
            colunas = {
                r["name"]
                for r in con.execute("PRAGMA table_info(virtual_pets)").fetchall()
            }
            obrigatorias = {
                "user_id", "pet_id", "nome", "nivel", "xp", "fome",
                "felicidade", "criado_em", "atualizado_em",
                "ultima_alimentacao", "ultima_brincadeira",
            }
            if obrigatorias.issubset(colunas):
                con.execute(
                    """
                    INSERT OR IGNORE INTO pet_collection (
                        user_id, pet_id, nome, nivel, xp,
                        fome, felicidade, criado_em, atualizado_em,
                        ultima_alimentacao, ultima_brincadeira, ativo
                    )
                    SELECT
                        user_id, pet_id, nome, nivel, xp,
                        fome, felicidade, criado_em, atualizado_em,
                        ultima_alimentacao, ultima_brincadeira, 1
                    FROM virtual_pets
                    WHERE pet_id IN ('cthulhu', 'pinguim', 'gato')
                    """
                )

        # Garante um único pet ativo por jogador, sem excluir os demais.
        usuarios = con.execute(
            "SELECT DISTINCT user_id FROM pet_collection WHERE ativo = 1"
        ).fetchall()
        for usuario in usuarios:
            uid = usuario["user_id"]
            ativos = con.execute(
                """
                SELECT pet_id FROM pet_collection
                WHERE user_id = ? AND ativo = 1
                ORDER BY criado_em ASC, pet_id ASC
                """,
                (uid,),
            ).fetchall()
            for pet in ativos[1:]:
                con.execute(
                    "UPDATE pet_collection SET ativo = 0 "
                    "WHERE user_id = ? AND pet_id = ?",
                    (uid, pet["pet_id"]),
                )


def _aplicar_decaimento(con, user_id: int, agora: float) -> None:
    """Cobra a perda de fome/felicidade pelas horas COMPLETAS decorridas.

    O relógio (atualizado_em) avança somente pelas horas cobradas; a fração
    de hora restante é preservada e nenhuma outra ação reinicia esse relógio.
    """
    rows = con.execute(
        """
        SELECT pet_id, atualizado_em, fome, felicidade
        FROM pet_collection WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()

    for row in rows:
        marco = float(row["atualizado_em"])
        horas = int((agora - marco) // 3600)
        if horas <= 0:
            continue
        con.execute(
            """
            UPDATE pet_collection
            SET fome = ?, felicidade = ?, atualizado_em = ?
            WHERE user_id = ? AND pet_id = ?
            """,
            (
                max(0, int(row["fome"]) - horas * PERDA_FOME_HORA),
                max(0, int(row["felicidade"]) - horas * PERDA_FELICIDADE_HORA),
                marco + horas * 3600,
                user_id,
                row["pet_id"],
            ),
        )


def atualizar_atributos(user_id: int, agora: Optional[float] = None) -> None:
    """Aplica a perda de atributos a todos os pets do jogador."""
    agora = time.time() if agora is None else agora
    with transacao() as con:
        _aplicar_decaimento(con, user_id, agora)


def buscar_pet_ativo(user_id: int, agora: Optional[float] = None):
    agora = time.time() if agora is None else agora
    with transacao() as con:
        _aplicar_decaimento(con, user_id, agora)
        return con.execute(
            "SELECT * FROM pet_collection WHERE user_id = ? AND ativo = 1 LIMIT 1",
            (user_id,),
        ).fetchone()


def listar_pets(user_id: int, agora: Optional[float] = None):
    agora = time.time() if agora is None else agora
    with transacao() as con:
        _aplicar_decaimento(con, user_id, agora)
        return con.execute(
            """
            SELECT * FROM pet_collection WHERE user_id = ?
            ORDER BY ativo DESC, criado_em ASC
            """,
            (user_id,),
        ).fetchall()


def selecionar_pet(user_id: int, pet_id: str) -> tuple[bool, str]:
    """Ativa um pet existente ou registra a primeira adoção."""
    if pet_id not in PETS:
        return False, "Esse mascote não existe."

    agora = time.time()
    dados = PETS[pet_id]

    try:
        with transacao() as con:
            existente = con.execute(
                "SELECT pet_id FROM pet_collection WHERE user_id = ? AND pet_id = ?",
                (user_id, pet_id),
            ).fetchone()

            con.execute(
                "UPDATE pet_collection SET ativo = 0 WHERE user_id = ?",
                (user_id,),
            )

            if existente:
                con.execute(
                    "UPDATE pet_collection SET ativo = 1 "
                    "WHERE user_id = ? AND pet_id = ?",
                    (user_id, pet_id),
                )
                return True, "Você voltou a ficar com esse companheiro!"

            con.execute(
                """
                INSERT INTO pet_collection (
                    user_id, pet_id, nome, nivel, xp,
                    fome, felicidade, criado_em, atualizado_em,
                    ultima_alimentacao, ultima_brincadeira, ativo
                )
                VALUES (?, ?, ?, 1, 0, 100, 100, ?, ?, ?, ?, 1)
                """,
                (user_id, pet_id, dados["nome"], agora, agora, agora, agora),
            )
        return True, "Seu novo companheiro chegou!"
    except sqlite3.Error:
        log.exception("Falha ao selecionar o pet %s de %s.", pet_id, user_id)
        return False, "Não consegui salvar a troca. Tente novamente."


def mandar_pet_embora(user_id: int) -> bool:
    """Desativa o pet atual, preservando-o no santuário."""
    try:
        with transacao() as con:
            cursor = con.execute(
                "UPDATE pet_collection SET ativo = 0 "
                "WHERE user_id = ? AND ativo = 1",
                (user_id,),
            )
            return cursor.rowcount > 0
    except sqlite3.Error:
        log.exception("Falha ao despedir o pet de %s.", user_id)
        return False


def renomear_pet(user_id: int, nome: str) -> Optional[sqlite3.Row]:
    """Renomeia o pet ativo. Retorna a linha atualizada ou None."""
    with transacao() as con:
        cursor = con.execute(
            "UPDATE pet_collection SET nome = ? WHERE user_id = ? AND ativo = 1",
            (nome, user_id),
        )
        if cursor.rowcount == 0:
            return None
        return con.execute(
            "SELECT * FROM pet_collection WHERE user_id = ? AND ativo = 1",
            (user_id,),
        ).fetchone()


def ranking_geral(limite: int = 100):
    with leitura() as con:
        return con.execute(
            """
            SELECT user_id, pet_id, nome, nivel, xp, ativo
            FROM pet_collection
            ORDER BY nivel DESC, xp DESC, criado_em ASC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()


# Funções antigas mantidas para compatibilidade com outros códigos.

def adicionar_xp(user_id: int, pet_id: str, quantidade: int) -> int:
    """Adiciona XP ao pet ativo e devolve os níveis ganhos."""
    with transacao() as con:
        row = con.execute(
            "SELECT nivel, xp FROM pet_collection "
            "WHERE user_id = ? AND pet_id = ? AND ativo = 1",
            (user_id, pet_id),
        ).fetchone()
        if row is None:
            return 0
        nivel, xp, ganhos = somar_xp(int(row["nivel"]), int(row["xp"]), quantidade)
        con.execute(
            "UPDATE pet_collection SET nivel = ?, xp = ? "
            "WHERE user_id = ? AND pet_id = ? AND ativo = 1",
            (nivel, xp, user_id, pet_id),
        )
        return ganhos


def cuidar_pet(user_id: int, pet_id: str, atributo: str, quantidade: int,
               coluna_tempo: str) -> bool:
    """Atualiza atributos de cuidado do pet ativo."""
    permitidos = {"fome": "ultima_alimentacao", "felicidade": "ultima_brincadeira"}
    if permitidos.get(atributo) != coluna_tempo:
        raise ValueError("Operação de cuidado inválida.")
    with transacao() as con:
        cursor = con.execute(
            f"""
            UPDATE pet_collection
            SET {atributo} = MIN(100, MAX(0, {atributo} + ?)),
                {coluna_tempo} = ?
            WHERE user_id = ? AND pet_id = ? AND ativo = 1
            """,
            (quantidade, time.time(), user_id, pet_id),
        )
        return cursor.rowcount > 0


# ============================================================
# AÇÕES DE CUIDADO (atômicas)
# ============================================================

ACOES = {
    "alimentar": {"tempo": "ultima_alimentacao", "cooldown": COOLDOWN_ALIMENTAR,
                  "xp": XP_ALIMENTAR, "contador": "vezes_alimentado"},
    "brincar": {"tempo": "ultima_brincadeira", "cooldown": COOLDOWN_BRINCAR,
                "xp": XP_BRINCAR, "contador": "vezes_brincou"},
    "carinho": {"tempo": "ultimo_carinho", "cooldown": COOLDOWN_CARINHO,
                "xp": XP_CARINHO, "contador": "vezes_carinho"},
    "habilidade": {"tempo": "ultima_habilidade", "cooldown": COOLDOWN_HABILIDADE,
                   "xp": XP_HABILIDADE, "contador": "vezes_habilidade"},
}


@dataclass
class ResultadoAcao:
    ok: bool
    codigo: str                 # ok, sem_pet, cooldown, cheio, sem_fome, bloqueado
    restante: int = 0           # segundos de cooldown restantes
    nivel_necessario: int = 0
    delta_fome: int = 0
    delta_felicidade: int = 0
    xp: int = 0
    nivel_antes: int = 0
    nivel: int = 0
    ganhos_nivel: int = 0
    texto: str = ""             # texto da habilidade
    row: Optional[sqlite3.Row] = None


def executar_acao(user_id: int, acao: str,
                  agora: Optional[float] = None) -> ResultadoAcao:
    """Valida cooldown, aplica efeito, XP e contadores numa transação só.

    Cliques/comandos simultâneos são serializados pelo BEGIN IMMEDIATE: o
    segundo encontra o cooldown já gravado pelo primeiro.
    """
    if acao not in ACOES:
        raise ValueError(f"Ação desconhecida: {acao}")
    cfg = ACOES[acao]
    agora = time.time() if agora is None else agora

    with transacao() as con:
        _aplicar_decaimento(con, user_id, agora)
        row = con.execute(
            "SELECT * FROM pet_collection WHERE user_id = ? AND ativo = 1 LIMIT 1",
            (user_id,),
        ).fetchone()

        if row is None:
            return ResultadoAcao(False, "sem_pet")

        pet_id = row["pet_id"]
        nivel_antes = int(row["nivel"])
        fome = int(row["fome"])
        felicidade = int(row["felicidade"])

        if acao == "habilidade" and nivel_antes < NIVEL_HABILIDADE:
            return ResultadoAcao(False, "bloqueado",
                                 nivel_necessario=NIVEL_HABILIDADE, row=row)

        restante = cfg["cooldown"] - (agora - float(row[cfg["tempo"]]))
        if restante > 0:
            return ResultadoAcao(False, "cooldown",
                                 restante=math.ceil(restante), row=row)

        d_fome = d_felicidade = 0
        texto = ""
        if acao == "alimentar":
            if fome >= FOME_MAX:
                return ResultadoAcao(False, "cheio", row=row)
            d_fome = GANHO_ALIMENTAR
        elif acao == "brincar":
            if fome <= 0:
                return ResultadoAcao(False, "sem_fome", row=row)
            d_felicidade = GANHO_BRINCAR
        elif acao == "carinho":
            if felicidade >= FELICIDADE_MAX:
                return ResultadoAcao(False, "cheio", row=row)
            d_felicidade = GANHO_CARINHO
        else:  # habilidade
            efeito = HABILIDADES[pet_id].executar(row["nome"])
            d_fome, d_felicidade, texto = efeito.fome, efeito.felicidade, efeito.texto

        nova_fome = limitar(fome + d_fome, 0, FOME_MAX)
        nova_felicidade = limitar(felicidade + d_felicidade, 0, FELICIDADE_MAX)
        nivel, xp, ganhos = somar_xp(nivel_antes, int(row["xp"]), cfg["xp"])

        con.execute(
            f"""
            UPDATE pet_collection
            SET fome = ?, felicidade = ?, nivel = ?, xp = ?,
                {cfg['tempo']} = ?, {cfg['contador']} = {cfg['contador']} + 1
            WHERE user_id = ? AND pet_id = ? AND ativo = 1
            """,
            (nova_fome, nova_felicidade, nivel, xp, agora, user_id, pet_id),
        )
        novo = con.execute(
            "SELECT * FROM pet_collection WHERE user_id = ? AND pet_id = ?",
            (user_id, pet_id),
        ).fetchone()

    return ResultadoAcao(
        True, "ok",
        delta_fome=nova_fome - fome,
        delta_felicidade=nova_felicidade - felicidade,
        xp=cfg["xp"], nivel_antes=nivel_antes, nivel=nivel,
        ganhos_nivel=ganhos, texto=texto, row=novo,
    )


# ============================================================
# TEXTOS DAS AÇÕES
# ============================================================

EMOJI_ACAO = {"alimentar": "🍖", "brincar": "🎮", "carinho": "🤗",
              "habilidade": "✨"}


def mensagem_erro(res: ResultadoAcao, acao: str, prefixo: str) -> str:
    if res.codigo == "sem_pet":
        return f"Você não tem pet ativo. Use `{prefixo}pet adotar`."
    if res.codigo == "cooldown":
        espera = formatar_tempo(res.restante)
        return {
            "alimentar": f"🍖 Seu pet ainda está satisfeito. Tente em {espera}.",
            "brincar": f"🎮 Seu pet precisa descansar. Tente em {espera}.",
            "carinho": f"🤗 Ele ainda está aproveitando o último afago. Tente em {espera}.",
            "habilidade": f"✨ A habilidade ainda está se recarregando. Tente em {espera}.",
        }[acao]
    if res.codigo == "cheio":
        return ("🍖 Seu pet está de barriga cheia!" if acao == "alimentar"
                else "🤗 Seu pet já está radiante de felicidade!")
    if res.codigo == "sem_fome":
        return "🍖 Seu pet está com muita fome para brincar. Alimente-o primeiro."
    if res.codigo == "bloqueado":
        return (f"🔒 A habilidade especial desbloqueia no "
                f"**nível {res.nivel_necessario}**. Cuide bem do seu pet!")
    return "Não consegui concluir a ação. Tente novamente."


def descrever_resultado(acao: str, res: ResultadoAcao) -> str:
    row = res.row
    pet_id, nome = row["pet_id"], row["nome"]

    if acao == "habilidade":
        habilidade = HABILIDADES[pet_id]
        principal = f"✨ **{habilidade.titulo}!**\n{res.texto}"
    else:
        frase = random.choice(FRASES[pet_id][acao])
        principal = f"{EMOJI_ACAO[acao]} **{nome}** {frase}"

    ganhos = []
    if res.delta_fome:
        ganhos.append(f"+{res.delta_fome} 🍖")
    if res.delta_felicidade:
        ganhos.append(f"+{res.delta_felicidade} 💖")
    ganhos.append(f"+{res.xp} ✨ XP")

    linhas = [principal, " · ".join(ganhos)]
    if res.ganhos_nivel:
        linhas.append(f"🌟 Subiu para o **nível {res.nivel}**!")
    antes = estagio(pet_id, res.nivel_antes)
    depois = estagio(pet_id, res.nivel)
    if antes != depois:
        linhas.append(f"🔮 Evolução: **{depois}**!")
    return "\n".join(linhas)


def linhas_acoes(row, agora: Optional[float] = None) -> str:
    """Estado de cada ação (pronta ou em quantos minutos)."""
    agora = time.time() if agora is None else agora
    pet_id = row["pet_id"]

    def estado(acao: str) -> str:
        restante = ACOES[acao]["cooldown"] - (agora - float(row[ACOES[acao]["tempo"]]))
        return "pronto" if restante <= 0 else f"em {formatar_tempo(math.ceil(restante))}"

    alimentar = "cheio" if int(row["fome"]) >= FOME_MAX else estado("alimentar")
    carinho = ("radiante" if int(row["felicidade"]) >= FELICIDADE_MAX
               else estado("carinho"))
    if int(row["nivel"]) < NIVEL_HABILIDADE:
        habilidade = f"🔒 nível {NIVEL_HABILIDADE}"
    else:
        habilidade = estado("habilidade")
    return (f"🍖 Alimentar: {alimentar}\n"
            f"🎮 Brincar: {estado('brincar')}\n"
            f"🤗 Carinho: {carinho}\n"
            f"✨ {HABILIDADES[pet_id].titulo}: {habilidade}")


# ============================================================
# FICHAS E IMAGENS (somente leitura do diretório de imagens)
# ============================================================

def imagem_disponivel(pet_id: str) -> bool:
    return (IMAGE_DIR / PETS[pet_id]["imagem"]).is_file()


def barra(valor: int, cheio: str) -> str:
    n = limitar(valor // 10, 0, 10)
    return f"{cheio * n}{'⬛' * (10 - n)} {valor}/100"


def criar_embed(row: sqlite3.Row, aviso: Optional[str] = None,
                com_imagem: Optional[bool] = None) -> discord.Embed:
    pet_id = row["pet_id"]
    pet = PETS[pet_id]
    fome = int(row["fome"])
    felicidade = int(row["felicidade"])
    nivel = int(row["nivel"])
    xp = int(row["xp"])
    chave_humor, emoji_humor, rotulo_humor = calcular_humor(fome, felicidade)

    descricao = f"*{pet['descricao']}*"
    if aviso:
        descricao = f"{aviso}\n\n{descricao}"

    embed = discord.Embed(
        title=f'{pet["emoji"]} {row["nome"]}',
        description=descricao,
        color=discord.Color.purple(),
    )

    embed.add_field(name="⭐ Nível", value=f"{nivel} · {estagio(pet_id, nivel)}",
                    inline=True)
    embed.add_field(name="✨ XP", value=f"{xp}/{XP_POR_NIVEL * nivel}", inline=True)
    embed.add_field(name="🎭 Personalidade", value=pet["personalidade"],
                    inline=False)
    embed.add_field(name=f"{emoji_humor} Humor: {rotulo_humor}",
                    value=FALAS_HUMOR[pet_id][chave_humor], inline=False)
    embed.add_field(name="🍖 Fome", value=barra(fome, "🟩"), inline=False)
    embed.add_field(name="💖 Felicidade", value=barra(felicidade, "🟪"),
                    inline=False)
    embed.add_field(name="🕹️ Ações", value=linhas_acoes(row), inline=False)

    if fome <= 20:
        embed.add_field(name="⚠️ Fome", value="Seu mascote precisa comer!",
                        inline=False)
    if felicidade <= 20:
        embed.add_field(name="⚠️ Felicidade",
                        value="Seu mascote precisa de atenção!", inline=False)

    if com_imagem is None:
        com_imagem = imagem_disponivel(pet_id)
    if com_imagem:
        embed.set_image(url=f"attachment://{pet['imagem']}")

    embed.set_footer(text="Shaggy Bot • Santuário de Mascotes")
    return embed


async def enviar_ficha(destino, row: sqlite3.Row, aviso: Optional[str] = None,
                       view: Optional[discord.ui.View] = None):
    """Envia a ficha (com a imagem do pet, se existir). Retorna a mensagem."""
    pet = PETS[row["pet_id"]]
    tem_imagem = imagem_disponivel(row["pet_id"])
    embed = criar_embed(row, aviso, com_imagem=tem_imagem)

    kwargs = {"embed": embed, "allowed_mentions": SEM_MENCOES}
    if tem_imagem:
        kwargs["file"] = discord.File(IMAGE_DIR / pet["imagem"],
                                      filename=pet["imagem"])
    if view is not None:
        kwargs["view"] = view

    if isinstance(destino, discord.Interaction):
        if destino.response.is_done():
            mensagem = await destino.followup.send(**kwargs)
        else:
            await destino.response.send_message(**kwargs)
            mensagem = await destino.original_response()
    else:
        mensagem = await destino.send(**kwargs)

    if view is not None and hasattr(view, "message"):
        view.message = mensagem
    return mensagem


# ============================================================
# INTERFACE (botões)
# ============================================================

def botao(rotulo: str, emoji: str, estilo, callback) -> discord.ui.Button:
    b = discord.ui.Button(label=rotulo[:80], emoji=emoji, style=estilo)
    b.callback = callback
    return b


class ViewDoDono(discord.ui.View):
    """Base: só o dono usa os botões; ao expirar, desativa a mensagem."""

    def __init__(self, user_id: int, timeout: float):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Esses botões não pertencem a você.", ephemeral=True)
            return False
        return True

    def desabilitar(self) -> None:
        for item in self.children:
            item.disabled = True

    async def on_timeout(self) -> None:
        self.desabilitar()
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class FichaView(ViewDoDono):
    """Botões de cuidado na ficha do pet."""

    def __init__(self, user_id: int, prefixo: str):
        super().__init__(user_id, timeout=180)
        self.prefixo = prefixo
        self.add_item(botao("Alimentar", "🍖", discord.ButtonStyle.success,
                            self._alimentar))
        self.add_item(botao("Brincar", "🎮", discord.ButtonStyle.primary,
                            self._brincar))
        self.add_item(botao("Carinho", "🤗", discord.ButtonStyle.secondary,
                            self._carinho))
        self.add_item(botao("Habilidade", "✨", discord.ButtonStyle.secondary,
                            self._habilidade))

    async def _alimentar(self, interaction):
        await self._agir(interaction, "alimentar")

    async def _brincar(self, interaction):
        await self._agir(interaction, "brincar")

    async def _carinho(self, interaction):
        await self._agir(interaction, "carinho")

    async def _habilidade(self, interaction):
        await self._agir(interaction, "habilidade")

    async def _agir(self, interaction: discord.Interaction, acao: str):
        await interaction.response.defer()
        try:
            res = await asyncio.to_thread(executar_acao, self.user_id, acao)
        except sqlite3.Error:
            log.exception("Falha na ação %s do usuário %s.", acao, self.user_id)
            await interaction.followup.send(
                "Não consegui atualizar seu pet. Tente novamente.", ephemeral=True)
            return

        if not res.ok:
            await interaction.followup.send(
                mensagem_erro(res, acao, self.prefixo), ephemeral=True,
                allowed_mentions=SEM_MENCOES)
            return

        aviso = descrever_resultado(acao, res)
        await interaction.edit_original_response(
            embed=criar_embed(res.row, aviso), view=self,
            allowed_mentions=SEM_MENCOES)


class SelecaoPetView(ViewDoDono):
    def __init__(self, user_id: int, modo: str, pets_existentes: dict,
                 prefixo: str):
        super().__init__(user_id, timeout=90)
        self.modo = modo
        self.prefixo = prefixo

        for pet_id, pet in PETS.items():
            existente = pets_existentes.get(pet_id)

            # "trocar" mostra os outros pets; o ativo nunca aparece.
            if modo == "trocar" and existente and existente["ativo"]:
                continue

            if modo == "trocar" and existente:
                rotulo = f'Trocar para {pet["nome"]}'
            elif existente:
                rotulo = f'Retomar {pet["nome"]}'
            else:
                rotulo = f'Adotar {pet["nome"]}'

            self.add_item(botao(rotulo, pet["emoji"],
                                discord.ButtonStyle.primary,
                                self._criar_callback(pet_id)))

        self.add_item(botao("Cancelar", "❌", discord.ButtonStyle.secondary,
                            self._cancelar))

    def _criar_callback(self, pet_id: str):
        async def callback(interaction: discord.Interaction):
            ok, mensagem = await asyncio.to_thread(
                selecionar_pet, self.user_id, pet_id)
            if not ok:
                await interaction.response.send_message(mensagem, ephemeral=True)
                return

            self.desabilitar()
            self.stop()
            row = await asyncio.to_thread(buscar_pet_ativo, self.user_id)

            await interaction.response.edit_message(
                content=f"🌌 {mensagem}", embed=None, view=self, attachments=[])

            if row:
                await enviar_ficha(interaction, row,
                                   view=FichaView(self.user_id, self.prefixo))
        return callback

    async def _cancelar(self, interaction: discord.Interaction):
        self.desabilitar()
        self.stop()
        await interaction.response.edit_message(
            content="Seleção cancelada.", embed=None, view=self)


class ConfirmarDespedidaView(ViewDoDono):
    def __init__(self, user_id: int, prefixo: str):
        super().__init__(user_id, timeout=30)
        self.prefixo = prefixo
        self.add_item(botao("Despedir", "👋", discord.ButtonStyle.danger,
                            self._confirmar))
        self.add_item(botao("Cancelar", "❤️", discord.ButtonStyle.success,
                            self._cancelar))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Somente quem iniciou a despedida pode confirmar.",
                ephemeral=True)
            return False
        return True

    async def _confirmar(self, interaction: discord.Interaction):
        sucesso = await asyncio.to_thread(mandar_pet_embora, self.user_id)
        self.desabilitar()
        self.stop()
        mensagem = (
            "🌌 Seu mascote partiu para outra realidade. Ele continuará no "
            "santuário, com seu progresso preservado. "
            f"Use `{self.prefixo}pet adotar` para escolher outro."
            if sucesso else "Não encontrei um pet ativo para despedir."
        )
        await interaction.response.edit_message(
            content=mensagem, embed=None, view=self)

    async def _cancelar(self, interaction: discord.Interaction):
        self.desabilitar()
        self.stop()
        await interaction.response.edit_message(
            content="❤️ Você decidiu continuar com seu companheiro.",
            embed=None, view=self)


# ============================================================
# COG PRINCIPAL
# ============================================================

class PetCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        inicializar_banco()

    # ---------- utilidades ----------

    @staticmethod
    async def _sem_pet(ctx: commands.Context) -> None:
        await ctx.send(f"Você não tem pet ativo. Use `{ctx.clean_prefix}pet adotar`.")

    async def _acao(self, ctx: commands.Context, acao: str) -> None:
        res = await asyncio.to_thread(executar_acao, ctx.author.id, acao)
        if not res.ok:
            await ctx.send(mensagem_erro(res, acao, ctx.clean_prefix),
                           allowed_mentions=SEM_MENCOES)
            return
        await enviar_ficha(ctx, res.row, aviso=descrever_resultado(acao, res),
                           view=FichaView(ctx.author.id, ctx.clean_prefix))

    async def mostrar_adocao(self, ctx: commands.Context, modo: str) -> None:
        prefixo = ctx.clean_prefix
        pets = await asyncio.to_thread(listar_pets, ctx.author.id)
        existentes = {p["pet_id"]: p for p in pets}
        ativos = [p for p in pets if p["ativo"]]

        if modo == "adotar" and ativos:
            await ctx.send(
                f"🐾 Você já tem um pet ativo. Use `{prefixo}pet trocar` "
                f"para escolher outro ou `{prefixo}pet embora` para se despedir.")
            return

        if modo == "trocar" and not ativos:
            await ctx.send(f"Você não tem pet ativo. Use `{prefixo}pet adotar`.")
            return

        view = SelecaoPetView(ctx.author.id, modo, existentes, prefixo)
        if len(view.children) <= 1:  # só o botão Cancelar
            await ctx.send(
                "Não há opções disponíveis para essa ação. "
                f"Consulte `{prefixo}pet santuario`.")
            return

        titulo = ("🌠 Escolha seu companheiro" if modo == "adotar"
                  else "🌀 Troca de mascote")
        embed = discord.Embed(
            title=titulo,
            description=("Escolha um mascote. Os que você já possui podem ser "
                         "retomados sem perder o progresso."),
            color=discord.Color.purple(),
        )
        for pet in PETS.values():
            embed.add_field(name=f'{pet["emoji"]} {pet["nome"]}',
                            value=pet["descricao"], inline=False)

        view.message = await ctx.send(embed=embed, view=view)

    # ---------- comandos ----------

    @commands.group(
        name="pet",
        invoke_without_command=True,
        help="Consulte seu mascote ou comece uma adoção.",
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet(self, ctx: commands.Context):
        row = await asyncio.to_thread(buscar_pet_ativo, ctx.author.id)
        if row:
            await enviar_ficha(ctx, row,
                               view=FichaView(ctx.author.id, ctx.clean_prefix))
            return
        await self.mostrar_adocao(ctx, modo="adotar")

    @pet.command(name="adotar", aliases=["novo"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_adotar(self, ctx: commands.Context):
        await self.mostrar_adocao(ctx, "adotar")

    @pet.command(name="trocar", aliases=["switch"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_trocar(self, ctx: commands.Context):
        await self.mostrar_adocao(ctx, "trocar")

    @pet.command(name="embora", aliases=["despedir", "mandar_embora"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_embora(self, ctx: commands.Context):
        row = await asyncio.to_thread(buscar_pet_ativo, ctx.author.id)
        if not row:
            await ctx.send("Você não tem um mascote ativo para despedir.")
            return

        pet = PETS[row["pet_id"]]
        embed = discord.Embed(
            title="🌌 Uma despedida?",
            description=(
                f"Você deseja se despedir de **{row['nome']}**?\n\n"
                f"{pet['emoji']} Seu companheiro ficará guardado no santuário, "
                "com seu nível e progresso preservados."),
            color=discord.Color.orange(),
        )
        view = ConfirmarDespedidaView(ctx.author.id, ctx.clean_prefix)
        view.message = await ctx.send(embed=embed, view=view,
                                      allowed_mentions=SEM_MENCOES)

    @pet.command(name="santuario", aliases=["colecao", "coleção"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_santuario(self, ctx: commands.Context):
        pets = await asyncio.to_thread(listar_pets, ctx.author.id)
        embed = discord.Embed(
            title="🏛️ Santuário de Mascotes",
            description="Seus companheiros permanecem aqui, mesmo quando não estão ativos.",
            color=discord.Color.purple(),
        )

        if not pets:
            embed.description = (
                f"Seu santuário está vazio. Use `{ctx.clean_prefix}pet adotar` "
                "para conhecer seu primeiro companheiro.")
        else:
            for row in pets:
                pet = PETS[row["pet_id"]]
                estado = "🟢 Ativo" if row["ativo"] else "🌙 Guardado"
                _, emoji_humor, rotulo_humor = calcular_humor(
                    int(row["fome"]), int(row["felicidade"]))
                embed.add_field(
                    name=f'{pet["emoji"]} {row["nome"]} — {estado}',
                    value=(
                        f"{estagio(row['pet_id'], int(row['nivel']))} · "
                        f"Nível {row['nivel']} · XP {row['xp']}\n"
                        f"Fome {row['fome']}/100 · Felicidade {row['felicidade']}/100 "
                        f"· {emoji_humor} {rotulo_humor}"),
                    inline=False,
                )
        await ctx.send(embed=embed, allowed_mentions=SEM_MENCOES)

    @pet.command(name="status")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_status(self, ctx: commands.Context):
        row = await asyncio.to_thread(buscar_pet_ativo, ctx.author.id)
        if not row:
            await self._sem_pet(ctx)
            return
        await enviar_ficha(ctx, row, view=FichaView(ctx.author.id, ctx.clean_prefix))

    @pet.command(name="alimentar", aliases=["comida", "feed"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_alimentar(self, ctx: commands.Context):
        await self._acao(ctx, "alimentar")

    @pet.command(name="brincar", aliases=["play"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_brincar(self, ctx: commands.Context):
        await self._acao(ctx, "brincar")

    @pet.command(name="carinho", aliases=["afagar", "mimo"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_carinho(self, ctx: commands.Context):
        await self._acao(ctx, "carinho")

    @pet.command(name="habilidade", aliases=["poder", "especial", "skill"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_habilidade(self, ctx: commands.Context):
        await self._acao(ctx, "habilidade")

    @pet.command(name="diario", aliases=["diário", "historico"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_diario(self, ctx: commands.Context):
        row = await asyncio.to_thread(buscar_pet_ativo, ctx.author.id)
        if not row:
            await self._sem_pet(ctx)
            return

        pet_id = row["pet_id"]
        pet = PETS[pet_id]
        nivel = int(row["nivel"])
        embed = discord.Embed(
            title=f'📖 Diário de {row["nome"]}',
            description=f'{pet["emoji"]} {estagio(pet_id, nivel)} · Nível {nivel}',
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="Juntos desde",
            value=f"<t:{int(row['criado_em'])}:D> (<t:{int(row['criado_em'])}:R>)",
            inline=False)
        embed.add_field(
            name="Cuidados registrados",
            value=(f"🍖 Refeições: {row['vezes_alimentado']}\n"
                   f"🎮 Brincadeiras: {row['vezes_brincou']}\n"
                   f"🤗 Carinhos: {row['vezes_carinho']}\n"
                   f"✨ {HABILIDADES[pet_id].titulo}: {row['vezes_habilidade']}"),
            inline=False)

        proximo = next((n for n in NIVEIS_ESTAGIO if n > nivel), None)
        if proximo is not None:
            i = NIVEIS_ESTAGIO.index(proximo)
            embed.add_field(
                name="Próxima evolução",
                value=f"**{ESTAGIOS[pet_id][i]}** no nível {proximo}",
                inline=False)
        else:
            embed.add_field(name="Próxima evolução",
                            value="Seu pet alcançou a forma final. 🌟",
                            inline=False)
        await ctx.send(embed=embed, allowed_mentions=SEM_MENCOES)

    @pet.command(name="ver", aliases=["visitar"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_ver(self, ctx: commands.Context, membro: discord.Member):
        row = await asyncio.to_thread(buscar_pet_ativo, membro.id)
        if not row:
            await ctx.send(f"**{membro.display_name}** não tem um pet ativo.",
                           allowed_mentions=SEM_MENCOES)
            return
        await enviar_ficha(
            ctx, row, aviso=f"🏠 Mascote de **{membro.display_name}**")

    @pet.command(name="ranking", aliases=["top", "rank"])
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def pet_ranking(self, ctx: commands.Context):
        candidatos = await asyncio.to_thread(ranking_geral, 100)
        linhas = []
        consultas = 0
        for row in candidatos:
            membro = ctx.guild.get_member(row["user_id"])
            if membro is None and consultas < 20:
                consultas += 1
                try:
                    membro = await ctx.guild.fetch_member(row["user_id"])
                except discord.HTTPException:
                    membro = None
            if membro is None:
                continue
            pet = PETS[row["pet_id"]]
            linhas.append(
                f"**{len(linhas) + 1}.** {pet['emoji']} {row['nome']} — "
                f"nível {row['nivel']} · {estagio(row['pet_id'], int(row['nivel']))} "
                f"(de {membro.display_name})")
            if len(linhas) >= 10:
                break

        embed = discord.Embed(
            title="🏆 Melhores Mascotes do Servidor",
            description="\n".join(linhas) or "Nenhum mascote encontrado ainda.",
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed, allowed_mentions=SEM_MENCOES)

    @pet.command(name="catalogo", aliases=["catálogo", "especies", "espécies"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_catalogo(self, ctx: commands.Context):
        pets = await asyncio.to_thread(listar_pets, ctx.author.id)
        possui = {p["pet_id"] for p in pets}
        embed = discord.Embed(
            title="📚 Catálogo de Mascotes",
            description=(f"A habilidade especial desbloqueia no nível "
                         f"{NIVEL_HABILIDADE}."),
            color=discord.Color.purple(),
        )
        for pet_id, pet in PETS.items():
            habilidade = HABILIDADES[pet_id]
            tem = "✅ No seu santuário" if pet_id in possui else "▫️ Ainda não adotado"
            embed.add_field(
                name=f'{pet["emoji"]} {pet["nome"]} — {tem}',
                value=(f"{pet['descricao']}\n"
                       f"**Habilidade:** {habilidade.titulo} — {habilidade.descricao}\n"
                       f"**Estágios:** " + " → ".join(ESTAGIOS[pet_id])),
                inline=False)
        await ctx.send(embed=embed)

    @pet.command(name="renomear", aliases=["nome"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_renomear(self, ctx: commands.Context, *, nome: str):
        limpo = limpar_nome(nome)
        if limpo is None:
            await ctx.send("O nome precisa ter entre 1 e 32 caracteres.")
            return

        novo = await asyncio.to_thread(renomear_pet, ctx.author.id, limpo)
        if novo is None:
            await self._sem_pet(ctx)
            return

        await enviar_ficha(ctx, novo, aviso=f"🏷️ Seu pet agora se chama **{limpo}**!",
                           view=FichaView(ctx.author.id, ctx.clean_prefix))

    @pet.command(name="ajuda")
    async def pet_ajuda(self, ctx: commands.Context):
        p = ctx.clean_prefix
        embed = discord.Embed(
            title="🐾 Guia dos Mascotes",
            description="Adote, cuide, evolua e troque de companheiro.",
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="Básico",
            value=(f"`{p}pet` — ver o pet ativo (com botões de ação)\n"
                   f"`{p}pet adotar` — adotar ou retomar um mascote\n"
                   f"`{p}pet trocar` — trocar de pet ou adotar outro\n"
                   f"`{p}pet embora` — despedir-se do pet ativo\n"
                   f"`{p}pet santuario` — ver todos os seus mascotes\n"
                   f"`{p}pet renomear NOME` — mudar o nome"),
            inline=False)
        embed.add_field(
            name="Cuidados",
            value=(f"`{p}pet alimentar` — recupera fome (30 min)\n"
                   f"`{p}pet brincar` — felicidade e XP (15 min)\n"
                   f"`{p}pet carinho` — afago rápido (5 min)\n"
                   f"`{p}pet habilidade` — poder especial, nível "
                   f"{NIVEL_HABILIDADE}+ (3 h)"),
            inline=False)
        embed.add_field(
            name="Explorar",
            value=(f"`{p}pet status` — consultar atributos\n"
                   f"`{p}pet diario` — histórico de cuidados\n"
                   f"`{p}pet catalogo` — espécies, estágios e habilidades\n"
                   f"`{p}pet ver @membro` — pet de outro membro\n"
                   f"`{p}pet ranking` — melhores pets do servidor"),
            inline=False)
        await ctx.send(embed=embed)

    # ---------- erros (inclui subcomandos) ----------

    async def cog_command_error(self, ctx: commands.Context,
                                error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Espere {error.retry_after:.1f} segundos antes de tentar "
                "novamente.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"Faltou informar `{error.param.name}`. "
                f"Veja `{ctx.clean_prefix}pet ajuda`.")
        elif isinstance(error, (commands.MemberNotFound, commands.BadArgument)):
            await ctx.send("Não encontrei esse membro. Mencione-o ou use o nome exato.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("Este comando só funciona em servidores.")
        else:
            log.error("Erro no comando %s", ctx.command, exc_info=error)


async def setup(bot: commands.Bot):
    await bot.add_cog(PetCog(bot))
