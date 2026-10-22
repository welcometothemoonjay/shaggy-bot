"""
BADGES — Loja de insígnias compráveis com Abysmus e cargos do Discord
=====================================================================

Cog do Shaggy Bot (discord.py 2.x). Salve como  cogs/badges.py.
O main.py já carrega automaticamente tudo que está em cogs/.

REQUISITO: aplicar o patch no cogs/XpAndCoins.py (arquivo XpAndCoins.py
entregue junto). Ele só ADICIONA dois métodos (obter_saldo_tx e
alterar_coins_tx) e faz alterar_coins() usá-los; nada muda para os
outros cogs.

COMO A COMPRA FICA CONSISTENTE
------------------------------
Economia e loja moram no MESMO arquivo SQLite (data/shaggy.db). Por isso a
compra roda em UMA transação (a do próprio XpAndCoins):

    valida -> debita Abysmus -> registra a posse -> grava no histórico
           -> enfileira a entrega do cargo          (tudo ou nada)

O cargo do Discord é um efeito externo que não dá para desfazer em
transação, então ele usa uma FILA PERSISTENTE (padrão "outbox"):
  * a compra já enfileira "dar cargo" dentro da transação;
  * logo depois o bot tenta entregar; se der certo, a fila é limpa;
  * se falhar (permissão, hierarquia, membro ausente, Discord fora do ar),
    a pendência continua no banco, é reprocessada a cada poucos minutos,
    sobrevive a reinícios e pode ser forçada com /insignia_sincronizar;
  * ninguém é cobrado de novo em nenhum desses casos.

TABELAS (criadas/migradas com segurança; nada é apagado)
--------------------------------------------------------
  badge_defs        catálogo por servidor (preço, raridade, cargo...)
  badge_owned       posse (PK servidor+membro+insígnia: impede duplicidade)
  badge_ledger      histórico de compras e operações administrativas
  badge_role_queue  entregas/remoções de cargo pendentes

COMANDOS
--------
Membros:  /insignias  /insignia_comprar  /minhas_insignias
          /insignia_detalhes  /insignia_sincronizar
Admins:   /insignia_criar  /insignia_editar  /insignia_ativar
          /insignia_desativar  /insignia_configurar_cargo
          /insignia_conceder  /insignia_revogar  /insignia_auditoria

REGRAS DE CARGO
---------------
  * O cargo é sempre identificado pelo ID salvo no banco, nunca pelo nome.
  * O bot só cria cargo novo se a insígnia permitir (auto_criar) e nunca
    "adota" um cargo existente pelo nome.
  * Sincronizar só ADICIONA cargos de insígnias que o membro possui no
    banco; nunca remove cargos de quem não tem a insígnia.
  * Cargos com permissões perigosas (administrador, banir, etc.) são
    recusados, porque a loja seria uma escalada de privilégio.
"""

import asyncio
import logging
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks


# Logger do cog; aparece no terminal do Shaggy Bot (logging do main.py).
log = logging.getLogger("shaggy.badges")


# ============================================================
# CONFIGURAÇÕES
# ============================================================

# ID da insígnia: 2 a 40 caracteres de a-z, 0-9, _ ou -.
ID_RE = re.compile(r"^[a-z0-9_-]{2,40}$")

MAX_NOME = 80
MAX_DESCRICAO = 300
MAX_BENEFICIOS = 300
MAX_EMOJI = 32

POR_PAGINA_LOJA = 5          # insígnias por página na loja
LINHAS_POR_PAGINA = 8        # linhas por página em listas/auditoria
LIMITE_AUDITORIA = 200       # registros máximos lidos por consulta

INTERVALO_FILA_MIN = 5       # de quanto em quanto tempo reprocessar a fila
LOTE_FILA = 25               # itens processados por rodada
MAX_TENTATIVAS_AUTO = 12     # depois disso só o /insignia_sincronizar tenta

# Permissões que nunca podem estar num cargo vendido pela loja.
PERMISSOES_PERIGOSAS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "manage_messages", "ban_members", "kick_members",
    "moderate_members", "mention_everyone",
)

# Raridades: chave -> (rótulo, emoji, cor do embed).
RARIDADES = {
    "comum": ("Comum", "⚪", 0x95A5A6),
    "raro": ("Raro", "🔵", 0x3498DB),
    "epico": ("Épico", "🟣", 0x9B59B6),
    "lendario": ("Lendário", "🟡", 0xF1C40F),
}
ESCOLHAS_RARIDADE = [
    app_commands.Choice(name=rotulo, value=chave)
    for chave, (rotulo, _emoji, _cor) in RARIDADES.items()
]

# Nomes legíveis das ações gravadas no histórico.
ACOES = {
    "create": "criação",
    "edit": "edição",
    "enable": "ativação",
    "disable": "desativação",
    "set_role": "cargo configurado",
    "role_created": "cargo criado",
    "purchase": "compra",
    "admin_grant": "concessão",
    "admin_revoke": "revogação",
    "role_fail": "falha de cargo",
    "role_recovered": "cargo recuperado",
}


# ------------------------------------------------------------
# CATÁLOGO INICIAL: tema lua + horror cósmico (lore de Da'kor).
# É instalado automaticamente ao iniciar o cog em cada servidor.
# Só cria o que ainda não existe e
# nunca sobrescreve insígnias já criadas.
#
# Preços: o Abysmus é raro (1 por nível), então os valores são baixos.
# Ajuste aqui ou depois com /insignia_editar.
# Para adicionar uma insígnia ao catálogo, copie um bloco e mude o "id".
# ------------------------------------------------------------
INSIGNIAS_INICIAIS = [
    # ---- Comuns: iniciantes e exploradores ----
    {"id": "vigia_da_mare", "nome": "Vigia da Maré", "emoji": "🌊",
     "raridade": "comum", "preco": 1,
     "descricao": "Você aprendeu a reconhecer quando o mar fica quieto demais. Em Maré Morta, isso já é uma habilidade de sobrevivência.",
     "beneficios": "Cargo 🌊 Vigia da Maré."},
    {"id": "andarilho_lunar", "nome": "Andarilho Lunar", "emoji": "🌙",
     "raridade": "comum", "preco": 2,
     "descricao": "Viajante das estradas costeiras, guiado por uma lua que parece mudar de lugar quando ninguém está olhando.",
     "beneficios": "Cargo 🌙 Andarilho Lunar."},
    {"id": "aprendiz_do_oculto", "nome": "Aprendiz do Oculto", "emoji": "🕯️",
     "raridade": "comum", "preco": 2,
     "descricao": "Caderno, lanterna e perguntas demais. Você ainda chama de coincidência aquilo que já começou a responder.",
     "beneficios": "Cargo 🕯️ Aprendiz do Oculto."},
    {"id": "catador_de_reliquias", "nome": "Catador de Relíquias", "emoji": "🗝️",
     "raridade": "comum", "preco": 2,
     "descricao": "Você recolhe objetos perdidos na praia. Alguns têm inscrições anteriores à própria cidade.",
     "beneficios": "Cargo 🗝️ Catador de Relíquias."},
    {"id": "cartografo_do_nevoeiro", "nome": "Cartógrafo do Nevoeiro", "emoji": "🗺️",
     "raridade": "comum", "preco": 3,
     "descricao": "Seus mapas registram vielas, túneis e caminhos que não aparecem em mapa algum depois do amanhecer.",
     "beneficios": "Cargo 🗺️ Cartógrafo do Nevoeiro."},

    # ---- Raras: classes e investigadores ----
    {"id": "investigador_do_olho", "nome": "Investigador do Olho", "emoji": "👁️",
     "raridade": "raro", "preco": 4,
     "descricao": "Você encontrou símbolos repetidos em lugares que não poderiam ter contato. Agora eles parecem reconhecer você.",
     "beneficios": "Cargo 👁️ Investigador do Olho."},
    {"id": "bruxa_da_mare", "nome": "Bruxa da Maré", "emoji": "🌒",
     "raridade": "raro", "preco": 4,
     "descricao": "Conhece os presságios das marés e os nomes que não devem ser ditos quando a lua desaparece.",
     "beneficios": "Cargo 🌒 Bruxa da Maré."},
    {"id": "arqueiro_do_eclipse", "nome": "Arqueiro do Eclipse", "emoji": "🏹",
     "raridade": "raro", "preco": 5,
     "descricao": "Atira contra aquilo que se esconde entre um relâmpago e outro. Nem sempre há certeza de que acertou o alvo certo.",
     "beneficios": "Cargo 🏹 Arqueiro do Eclipse."},
    {"id": "alquimista_de_sal", "nome": "Alquimista de Sal", "emoji": "⚗️",
     "raridade": "raro", "preco": 5,
     "descricao": "Mistura sal, ferrugem e fragmentos de relíquias para testar os limites entre proteção e superstição.",
     "beneficios": "Cargo ⚗️ Alquimista de Sal."},
    {"id": "guardiao_do_pier", "nome": "Guardião do Píer", "emoji": "⚓",
     "raridade": "raro", "preco": 5,
     "descricao": "Você protege o velho píer, embora ninguém saiba exatamente o que está tentando impedir de voltar à costa.",
     "beneficios": "Cargo ⚓ Guardião do Píer."},

    # ---- Épicas: marcados e especialistas ----
    {"id": "marca_de_malachais", "nome": "Marca de Malachais", "emoji": "🔒",
     "raridade": "epico", "preco": 7,
     "descricao": "Um símbolo de olho e fechadura parece ter sido gravado na própria ideia de você. A pele é só a superfície.",
     "beneficios": "Cargo 🔒 Marca de Malachais."},
    {"id": "cavaleiro_da_lua_sangrenta", "nome": "Cavaleiro da Lua Sangrenta", "emoji": "🩸",
     "raridade": "epico", "preco": 8,
     "descricao": "Jurou vigiar as noites em que a lua fica vermelha. Seu juramento não garante que você sobreviva a elas.",
     "beneficios": "Cargo 🩸 Cavaleiro da Lua Sangrenta."},
    {"id": "oraculo_das_ondas", "nome": "Oráculo das Ondas", "emoji": "🔮",
     "raridade": "epico", "preco": 8,
     "descricao": "Ouve nas ondas ecos de acontecimentos que ainda não ocorreram — ou que já ocorreram em outro lugar.",
     "beneficios": "Cargo 🔮 Oráculo das Ondas."},
    {"id": "ladino_do_veu", "nome": "Ladino do Véu", "emoji": "🗡️",
     "raridade": "epico", "preco": 9,
     "descricao": "Entra por portas trancadas e sai por corredores que não estavam ali antes. Nunca conta o que viu do outro lado.",
     "beneficios": "Cargo 🗡️ Ladino do Véu."},
    {"id": "cronista_das_fendas", "nome": "Cronista das Fendas", "emoji": "📜",
     "raridade": "epico", "preco": 9,
     "descricao": "Registra relatos impossíveis sem tentar torná-los coerentes. Algumas páginas aparecem escritas antes de você pegar a caneta.",
     "beneficios": "Cargo 📜 Cronista das Fendas."},
    {"id": "sentinela_da_cripta", "nome": "Sentinela da Cripta", "emoji": "🪦",
     "raridade": "epico", "preco": 10,
     "descricao": "Você conhece os sinais gravados perto da Cripta de Malachais. A cripta, por sua vez, parece conhecer seu nome.",
     "beneficios": "Cargo 🪦 Sentinela da Cripta."},

    # ---- Lendárias: marcas que não deveriam existir ----
    {"id": "rainha_vermelha", "nome": "Favor da Rainha Vermelha", "emoji": "🦇",
     "raridade": "lendario", "preco": 13,
     "descricao": "Um favor da Rainha Vermelha nunca é gratuito. Você ainda não descobriu qual parte de si deixou como garantia.",
     "beneficios": "Cargo 🦇 Favor da Rainha Vermelha."},
    {"id": "olho_entre_os_mundos", "nome": "Olho Entre os Mundos", "emoji": "👁️‍🗨️",
     "raridade": "lendario", "preco": 15,
     "descricao": "Você percebe rachaduras no que chamamos de realidade. Olhar por elas é fácil; voltar a enxergar normalmente, não.",
     "beneficios": "Cargo 👁️‍🗨️ Olho Entre os Mundos."},
    {"id": "herdeiro_do_inominavel", "nome": "Herdeiro do Inominável", "emoji": "🕳️",
     "raridade": "lendario", "preco": 17,
     "descricao": "Uma presença sem rosto deixou sua assinatura no vazio entre duas lembranças. Você não sabe o que herdou.",
     "beneficios": "Cargo 🕳️ Herdeiro do Inominável."},
    {"id": "eclipse_de_drakvuh", "nome": "Eclipse de Drak'vuh", "emoji": "🌌",
     "raridade": "lendario", "preco": 20,
     "descricao": "Além das estrelas, algo antigo sonha. A sua insígnia pulsa quando o céu escurece, mesmo sob um teto fechado.",
     "beneficios": "Cargo 🌌 Eclipse de Drak'vuh, uma das insígnias mais raras da loja."},
]


# ============================================================
# TIPOS E ERROS
# ============================================================

class EconomiaIndisponivel(RuntimeError):
    """O cog XpAndCoins não está carregado ou não tem o patch."""


class _FalhaCargo(Exception):
    """Falha esperada ao entregar/criar um cargo (texto amigável)."""


@dataclass(frozen=True)
class Badge:
    """Uma insígnia do catálogo de um servidor."""
    guild_id: int
    badge_id: str
    name: str
    description: str
    price: int
    rarity: str
    benefits: str
    emoji: str
    role_id: Optional[int]
    auto_role: bool
    enabled: bool
    created_at: str

    @property
    def rotulo(self) -> str:
        return f"{self.emoji} {self.name}"

    @property
    def raridade(self) -> str:
        rotulo, emoji, _ = RARIDADES.get(self.rarity, RARIDADES["comum"])
        return f"{emoji} {rotulo}"


@dataclass
class ResultadoCompra:
    status: str   # ok | inexistente | desativada | ja_possui | saldo_insuficiente
    badge: Optional[Badge] = None
    saldo: Optional[int] = None


@dataclass
class ResultadoCargo:
    ok: bool
    acao: str      # aplicado | ja_tinha | removido | nada | falha
    mensagem: str = ""
    mencao: str = ""


@dataclass(frozen=True)
class ItemFila:
    guild_id: int
    user_id: int
    badge_id: str
    op: str        # add | remove
    tentativas: int


# ============================================================
# UTILIDADES
# ============================================================

def _agora() -> str:
    """Horário atual em UTC (ISO 8601) para gravar no banco."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ts(iso: str, estilo: str = "d") -> str:
    """Converte um horário ISO em marcação de data do Discord."""
    try:
        return f"<t:{int(datetime.fromisoformat(iso).timestamp())}:{estilo}>"
    except ValueError:
        return iso


def _cor(rarity: str) -> discord.Colour:
    return discord.Colour(RARIDADES.get(rarity, RARIDADES["comum"])[2])


# ============================================================
# CAMADA DE BANCO (síncrona; sempre chamada via asyncio.to_thread)
# ============================================================

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS badge_defs (
        guild_id    INTEGER NOT NULL,
        badge_id    TEXT    NOT NULL,
        name        TEXT    NOT NULL,
        description TEXT    NOT NULL DEFAULT '',
        price       INTEGER NOT NULL CHECK (price >= 0),
        rarity      TEXT    NOT NULL DEFAULT 'comum',
        benefits    TEXT    NOT NULL DEFAULT '',
        emoji       TEXT    NOT NULL DEFAULT '🏅',
        role_id     INTEGER,
        auto_role   INTEGER NOT NULL DEFAULT 1,
        enabled     INTEGER NOT NULL DEFAULT 1,
        created_by  INTEGER,
        created_at  TEXT    NOT NULL,
        updated_at  TEXT    NOT NULL,
        PRIMARY KEY (guild_id, badge_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS badge_owned (
        guild_id    INTEGER NOT NULL,
        user_id     INTEGER NOT NULL,
        badge_id    TEXT    NOT NULL,
        acquired_at TEXT    NOT NULL,
        source      TEXT    NOT NULL,
        price_paid  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, badge_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_badge_owned_badge "
    "ON badge_owned (guild_id, badge_id)",
    """
    CREATE TABLE IF NOT EXISTS badge_ledger (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER,
        badge_id   TEXT,
        action     TEXT    NOT NULL,
        amount     INTEGER NOT NULL DEFAULT 0,
        actor_id   INTEGER,
        detail     TEXT    NOT NULL DEFAULT '',
        created_at TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_badge_ledger_guild "
    "ON badge_ledger (guild_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_badge_ledger_user "
    "ON badge_ledger (guild_id, user_id, id DESC)",
    """
    CREATE TABLE IF NOT EXISTS badge_role_queue (
        guild_id     INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        badge_id     TEXT    NOT NULL,
        op           TEXT    NOT NULL CHECK (op IN ('add', 'remove')),
        attempts     INTEGER NOT NULL DEFAULT 0,
        last_error   TEXT    NOT NULL DEFAULT '',
        last_attempt TEXT    NOT NULL DEFAULT '',
        created_at   TEXT    NOT NULL,
        PRIMARY KEY (guild_id, user_id, badge_id)
    )
    """,
)

_COLUNAS = (
    "guild_id, badge_id, name, description, price, rarity, benefits, "
    "emoji, role_id, auto_role, enabled, created_at"
)
_COLUNAS_B = ", ".join("b." + c.strip() for c in _COLUNAS.split(","))

# Campos que /insignia_editar pode alterar (lista fechada, definida aqui).
CAMPOS_EDITAVEIS = ("name", "description", "price", "rarity", "benefits",
                    "emoji")


def _badge(row) -> Badge:
    """Converte uma linha de badge_defs em Badge."""
    return Badge(
        guild_id=row[0], badge_id=row[1], name=row[2], description=row[3],
        price=row[4], rarity=row[5], benefits=row[6], emoji=row[7],
        role_id=row[8], auto_role=bool(row[9]), enabled=bool(row[10]),
        created_at=row[11],
    )


class BadgeStore:
    """
    Acesso ao banco da loja. Toda operação usa a transação do cog de
    economia (XpAndCoins.transacao), garantindo que Abysmus e insígnias
    sejam gravados juntos ou não sejam gravados.

    REGRA: dentro de um bloco "with eco.transacao()", nunca chame métodos
    da economia que abrem a própria transação (obter_dados, alterar_coins):
    eles esperariam o banco liberar e travariam. Use os *_tx.
    """

    def __init__(self, obter_economia: Callable[[], object]):
        self._obter_economia = obter_economia

    def _eco(self):
        eco = self._obter_economia()
        if eco is None:
            raise EconomiaIndisponivel(
                "O cog XpAndCoins não está carregado."
            )
        for nome in ("transacao", "obter_saldo_tx", "alterar_coins_tx"):
            if not hasattr(eco, nome):
                raise EconomiaIndisponivel(
                    f"O XpAndCoins precisa do método '{nome}'. "
                    "Aplique o patch do XpAndCoins.py."
                )
        return eco

    # ---------- esquema ----------

    def iniciar_schema(self) -> None:
        """Cria as tabelas se ainda não existirem (nunca apaga dados)."""
        eco = self._eco()
        with eco.transacao() as db:
            for comando in SCHEMA:
                db.execute(comando)
            legado = db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type = 'table' AND name = 'badges_catalog'"
            ).fetchone()

        if legado:
            log.warning(
                "Tabela antiga 'badges_catalog' encontrada; ela NÃO foi "
                "alterada nem importada (não tem guild_id). "
                "Recrie as insígnias com /insignia_criar."
            )

    # ---------- helpers internos (recebem a transação aberta) ----------

    @staticmethod
    def _ledger(db, guild_id, user_id, badge_id, acao, *, valor=0,
                ator=None, detalhe=""):
        """Grava uma linha no histórico (dentro da transação atual)."""
        db.execute(
            "INSERT INTO badge_ledger (guild_id, user_id, badge_id, action,"
            " amount, actor_id, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, badge_id, acao, valor, ator, detalhe,
             _agora()),
        )

    @staticmethod
    def _obter(db, guild_id: int, badge_id: str) -> Optional[Badge]:
        row = db.execute(
            f"SELECT {_COLUNAS} FROM badge_defs "
            "WHERE guild_id = ? AND badge_id = ?",
            (guild_id, badge_id),
        ).fetchone()
        return _badge(row) if row else None

    @staticmethod
    def _possui(db, guild_id: int, user_id: int, badge_id: str) -> bool:
        return db.execute(
            "SELECT 1 FROM badge_owned "
            "WHERE guild_id = ? AND user_id = ? AND badge_id = ?",
            (guild_id, user_id, badge_id),
        ).fetchone() is not None

    @staticmethod
    def _enfileirar(db, guild_id, user_id, badge_id, op) -> None:
        """Registra uma entrega/remoção de cargo pendente (a última vence)."""
        db.execute(
            "INSERT OR REPLACE INTO badge_role_queue (guild_id, user_id,"
            " badge_id, op, attempts, last_error, last_attempt, created_at) "
            "VALUES (?, ?, ?, ?, 0, '', '', ?)",
            (guild_id, user_id, badge_id, op, _agora()),
        )

    # ---------- consultas ----------

    def listar(self, guild_id: int, somente_ativas: bool = False):
        with self._eco().transacao() as db:
            filtro = " AND enabled = 1" if somente_ativas else ""
            linhas = db.execute(
                f"SELECT {_COLUNAS} FROM badge_defs WHERE guild_id = ?"
                f"{filtro} ORDER BY price, name",
                (guild_id,),
            ).fetchall()
        return [_badge(r) for r in linhas]

    def obter(self, guild_id: int, badge_id: str) -> Optional[Badge]:
        with self._eco().transacao() as db:
            return self._obter(db, guild_id, badge_id)

    def possui(self, guild_id: int, user_id: int, badge_id: str) -> bool:
        with self._eco().transacao() as db:
            return self._possui(db, guild_id, user_id, badge_id)

    def ids_do_membro(self, guild_id: int, user_id: int) -> set[str]:
        with self._eco().transacao() as db:
            linhas = db.execute(
                "SELECT badge_id FROM badge_owned "
                "WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchall()
        return {r[0] for r in linhas}

    def listar_do_membro(self, guild_id: int, user_id: int):
        """Retorna [(Badge, adquirida_em, origem)] do membro."""
        with self._eco().transacao() as db:
            linhas = db.execute(
                f"SELECT {_COLUNAS_B}, o.acquired_at, o.source "
                "FROM badge_owned o JOIN badge_defs b "
                "ON b.guild_id = o.guild_id AND b.badge_id = o.badge_id "
                "WHERE o.guild_id = ? AND o.user_id = ? "
                "ORDER BY o.acquired_at",
                (guild_id, user_id),
            ).fetchall()
        return [(_badge(r[:12]), r[12], r[13]) for r in linhas]

    def donos_do_servidor(self, guild_id: int) -> list[int]:
        with self._eco().transacao() as db:
            linhas = db.execute(
                "SELECT DISTINCT user_id FROM badge_owned WHERE guild_id = ?",
                (guild_id,),
            ).fetchall()
        return [r[0] for r in linhas]

    def contar_donos(self, guild_id: int, badge_id: str) -> int:
        with self._eco().transacao() as db:
            return db.execute(
                "SELECT COUNT(*) FROM badge_owned "
                "WHERE guild_id = ? AND badge_id = ?",
                (guild_id, badge_id),
            ).fetchone()[0]

    def saldo(self, guild_id: int, user_id: int) -> int:
        """Saldo de Abysmus (usa a API pública da economia)."""
        return self._eco().obter_dados(guild_id, user_id)[2]

    # ---------- catálogo (administração) ----------

    def criar(self, guild_id, badge_id, nome, descricao, preco, raridade,
              beneficios, emoji, ator) -> bool:
        """Cria a insígnia. Retorna False se o ID já existir."""
        agora = _agora()
        with self._eco().transacao() as db:
            try:
                db.execute(
                    "INSERT INTO badge_defs (guild_id, badge_id, name,"
                    " description, price, rarity, benefits, emoji, role_id,"
                    " auto_role, enabled, created_by, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, 1, ?, ?, ?)",
                    (guild_id, badge_id, nome, descricao, preco, raridade,
                     beneficios, emoji, ator, agora, agora),
                )
            except sqlite3.IntegrityError:
                return False

            self._ledger(
                db, guild_id, None, badge_id, "create", ator=ator,
                detalhe=f"{nome} · {preco} Abysmus · {raridade}",
            )
        return True

    def editar(self, guild_id, badge_id, ator, **campos) -> Optional[Badge]:
        """Altera campos da insígnia. Retorna a nova versão (ou None)."""
        for chave in campos:
            if chave not in CAMPOS_EDITAVEIS:
                raise ValueError(f"Campo não editável: {chave}")

        with self._eco().transacao() as db:
            antigo = self._obter(db, guild_id, badge_id)
            if antigo is None:
                return None

            mudancas = []
            for chave, valor in campos.items():
                anterior = getattr(antigo, chave)
                if anterior != valor:
                    mudancas.append((chave, anterior, valor))

            if mudancas:
                # Os nomes das colunas vêm de CAMPOS_EDITAVEIS (fixo).
                atribuicoes = ", ".join(f"{c} = ?" for c, _, _ in mudancas)
                db.execute(
                    f"UPDATE badge_defs SET {atribuicoes}, updated_at = ? "
                    "WHERE guild_id = ? AND badge_id = ?",
                    (*[n for _, _, n in mudancas], _agora(),
                     guild_id, badge_id),
                )
                self._ledger(
                    db, guild_id, None, badge_id, "edit", ator=ator,
                    detalhe="; ".join(
                        f"{c}: {a!r} -> {n!r}" for c, a, n in mudancas
                    )[:500],
                )
            return self._obter(db, guild_id, badge_id)

    def definir_ativa(self, guild_id, badge_id, ativa: bool, ator) -> str:
        """Retorna: ok | inexistente | sem_mudanca."""
        with self._eco().transacao() as db:
            badge = self._obter(db, guild_id, badge_id)
            if badge is None:
                return "inexistente"
            if badge.enabled == ativa:
                return "sem_mudanca"

            db.execute(
                "UPDATE badge_defs SET enabled = ?, updated_at = ? "
                "WHERE guild_id = ? AND badge_id = ?",
                (1 if ativa else 0, _agora(), guild_id, badge_id),
            )
            self._ledger(
                db, guild_id, None, badge_id,
                "enable" if ativa else "disable", ator=ator,
            )
        return "ok"

    def definir_cargo(self, guild_id, badge_id, ator, *, role_id=None,
                      auto_role=None, acao="set_role", detalhe=""):
        """
        Grava o cargo e/ou a opção de criação automática.
        Retorna (status, cargo_antigo): ok | inexistente | role_em_uso.
        """
        with self._eco().transacao() as db:
            badge = self._obter(db, guild_id, badge_id)
            if badge is None:
                return "inexistente", None

            if role_id is not None:
                em_uso = db.execute(
                    "SELECT badge_id FROM badge_defs WHERE guild_id = ? "
                    "AND role_id = ? AND badge_id <> ?",
                    (guild_id, role_id, badge_id),
                ).fetchone()
                if em_uso:
                    return "role_em_uso", badge.role_id
                db.execute(
                    "UPDATE badge_defs SET role_id = ?, updated_at = ? "
                    "WHERE guild_id = ? AND badge_id = ?",
                    (role_id, _agora(), guild_id, badge_id),
                )

            if auto_role is not None:
                db.execute(
                    "UPDATE badge_defs SET auto_role = ?, updated_at = ? "
                    "WHERE guild_id = ? AND badge_id = ?",
                    (1 if auto_role else 0, _agora(), guild_id, badge_id),
                )

            self._ledger(
                db, guild_id, None, badge_id, acao, ator=ator,
                detalhe=detalhe or (
                    f"cargo {badge.role_id} -> {role_id}"
                    if role_id is not None else f"auto_criar={auto_role}"
                ),
            )
        return "ok", badge.role_id

    # ---------- compra e administração de posse ----------

    def comprar(self, guild_id: int, user_id: int,
                badge_id: str) -> ResultadoCompra:
        """
        Compra atômica. Ordem: validar -> debitar -> registrar posse ->
        histórico -> enfileirar cargo. Qualquer erro desfaz TUDO.
        O BEGIN IMMEDIATE da transação serializa compras simultâneas, e a
        chave primária de badge_owned é a última barreira contra cobrança
        duplicada.
        """
        eco = self._eco()
        with eco.transacao() as db:
            badge = self._obter(db, guild_id, badge_id)
            if badge is None:
                return ResultadoCompra("inexistente")
            if not badge.enabled:
                return ResultadoCompra("desativada", badge)
            if self._possui(db, guild_id, user_id, badge_id):
                return ResultadoCompra("ja_possui", badge)

            saldo_antes = eco.obter_saldo_tx(db, guild_id, user_id)
            if saldo_antes < badge.price:
                return ResultadoCompra("saldo_insuficiente", badge,
                                       saldo_antes)

            saldo = eco.alterar_coins_tx(db, guild_id, user_id, -badge.price)

            db.execute(
                "INSERT INTO badge_owned (guild_id, user_id, badge_id,"
                " acquired_at, source, price_paid) "
                "VALUES (?, ?, ?, ?, 'purchase', ?)",
                (guild_id, user_id, badge_id, _agora(), badge.price),
            )
            self._ledger(db, guild_id, user_id, badge_id, "purchase",
                         valor=badge.price, ator=user_id)
            self._enfileirar(db, guild_id, user_id, badge_id, "add")

        return ResultadoCompra("ok", badge, saldo)

    def conceder(self, guild_id, user_id, badge_id, ator) -> str:
        """Concessão administrativa (sem cobrança). ok|inexistente|ja_possui"""
        with self._eco().transacao() as db:
            if self._obter(db, guild_id, badge_id) is None:
                return "inexistente"
            if self._possui(db, guild_id, user_id, badge_id):
                return "ja_possui"

            db.execute(
                "INSERT INTO badge_owned (guild_id, user_id, badge_id,"
                " acquired_at, source, price_paid) "
                "VALUES (?, ?, ?, ?, 'admin', 0)",
                (guild_id, user_id, badge_id, _agora()),
            )
            self._ledger(db, guild_id, user_id, badge_id, "admin_grant",
                         ator=ator)
            self._enfileirar(db, guild_id, user_id, badge_id, "add")
        return "ok"

    def revogar(self, guild_id, user_id, badge_id, ator) -> str:
        """Revogação administrativa. ok|inexistente|nao_possui"""
        with self._eco().transacao() as db:
            if self._obter(db, guild_id, badge_id) is None:
                return "inexistente"
            if not self._possui(db, guild_id, user_id, badge_id):
                return "nao_possui"

            db.execute(
                "DELETE FROM badge_owned "
                "WHERE guild_id = ? AND user_id = ? AND badge_id = ?",
                (guild_id, user_id, badge_id),
            )
            self._ledger(db, guild_id, user_id, badge_id, "admin_revoke",
                         ator=ator)
            self._enfileirar(db, guild_id, user_id, badge_id, "remove")
        return "ok"

    # ---------- fila de cargos ----------

    def fila_enfileirar_donos(self, guild_id: int, badge_id: str) -> int:
        """Enfileira a entrega do cargo a todos os donos da insígnia."""
        with self._eco().transacao() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO badge_role_queue (guild_id, user_id,"
                " badge_id, op, attempts, last_error, last_attempt,"
                " created_at) "
                "SELECT guild_id, user_id, badge_id, 'add', 0, '', '', ? "
                "FROM badge_owned WHERE guild_id = ? AND badge_id = ?",
                (_agora(), guild_id, badge_id),
            )
            return cur.rowcount

    def fila_pendentes(self, limite: int, max_tentativas: int,
                       guild_id: Optional[int] = None) -> list[ItemFila]:
        with self._eco().transacao() as db:
            sql = ("SELECT guild_id, user_id, badge_id, op, attempts "
                   "FROM badge_role_queue WHERE attempts < ?")
            params: list = [max_tentativas]
            if guild_id is not None:
                sql += " AND guild_id = ?"
                params.append(guild_id)
            sql += " ORDER BY created_at LIMIT ?"
            params.append(limite)
            linhas = db.execute(sql, params).fetchall()
        return [ItemFila(*r) for r in linhas]

    def fila_concluir(self, guild_id, user_id, badge_id) -> None:
        """Limpa a pendência; registra a recuperação se houve falhas."""
        with self._eco().transacao() as db:
            linha = db.execute(
                "SELECT attempts FROM badge_role_queue "
                "WHERE guild_id = ? AND user_id = ? AND badge_id = ?",
                (guild_id, user_id, badge_id),
            ).fetchone()
            if linha is None:
                return

            db.execute(
                "DELETE FROM badge_role_queue "
                "WHERE guild_id = ? AND user_id = ? AND badge_id = ?",
                (guild_id, user_id, badge_id),
            )
            if linha[0] > 0:
                self._ledger(db, guild_id, user_id, badge_id,
                             "role_recovered",
                             detalhe=f"após {linha[0]} falha(s)")

    def fila_falhou(self, guild_id, user_id, badge_id, op, erro: str,
                    zerar: bool = False) -> int:
        """Registra uma falha de entrega e devolve o nº de tentativas."""
        agora = _agora()
        with self._eco().transacao() as db:
            db.execute(
                "INSERT INTO badge_role_queue (guild_id, user_id, badge_id,"
                " op, attempts, last_error, last_attempt, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?, ?) "
                "ON CONFLICT (guild_id, user_id, badge_id) DO UPDATE SET "
                " op = excluded.op,"
                " attempts = CASE WHEN ? THEN 1 ELSE attempts + 1 END,"
                " last_error = excluded.last_error,"
                " last_attempt = excluded.last_attempt",
                (guild_id, user_id, badge_id, op, erro, agora, agora,
                 1 if zerar else 0),
            )
            tentativas = db.execute(
                "SELECT attempts FROM badge_role_queue "
                "WHERE guild_id = ? AND user_id = ? AND badge_id = ?",
                (guild_id, user_id, badge_id),
            ).fetchone()[0]

            # Só a primeira falha vai ao histórico, para não encher de ruído.
            if tentativas == 1:
                self._ledger(db, guild_id, user_id, badge_id, "role_fail",
                             detalhe=erro[:300])
        return tentativas

    def fila_remover(self, guild_id, user_id, badge_id) -> None:
        """Descarta uma pendência obsoleta (a posse mudou)."""
        with self._eco().transacao() as db:
            db.execute(
                "DELETE FROM badge_role_queue "
                "WHERE guild_id = ? AND user_id = ? AND badge_id = ?",
                (guild_id, user_id, badge_id),
            )

    # ---------- auditoria e estatísticas ----------

    def auditoria(self, guild_id, user_id=None, badge_id=None, acao=None,
                  limite=LIMITE_AUDITORIA):
        """Histórico mais recente primeiro, com filtros opcionais."""
        sql = ("SELECT id, created_at, action, user_id, badge_id, amount,"
               " actor_id, detail FROM badge_ledger WHERE guild_id = ?")
        params: list = [guild_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        if badge_id is not None:
            sql += " AND badge_id = ?"
            params.append(badge_id)
        if acao is not None:
            sql += " AND action = ?"
            params.append(acao)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limite)

        with self._eco().transacao() as db:
            return db.execute(sql, params).fetchall()

    def estatisticas(self, guild_id: int) -> dict:
        with self._eco().transacao() as db:
            q = lambda sql, *p: db.execute(sql, (guild_id, *p)).fetchone()

            total, ativas = q(
                "SELECT COUNT(*), COALESCE(SUM(enabled), 0) "
                "FROM badge_defs WHERE guild_id = ?")
            posses, membros = q(
                "SELECT COUNT(*), COUNT(DISTINCT user_id) "
                "FROM badge_owned WHERE guild_id = ?")
            compras, gasto = q(
                "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM badge_ledger "
                "WHERE guild_id = ? AND action = 'purchase'")
            concessoes = q(
                "SELECT COUNT(*) FROM badge_ledger "
                "WHERE guild_id = ? AND action = 'admin_grant'")[0]
            revogacoes = q(
                "SELECT COUNT(*) FROM badge_ledger "
                "WHERE guild_id = ? AND action = 'admin_revoke'")[0]
            # "Travadas": já esgotaram as tentativas automáticas.
            pendentes, travadas = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(attempts >= ?), 0) "
                "FROM badge_role_queue WHERE guild_id = ?",
                (MAX_TENTATIVAS_AUTO, guild_id),
            ).fetchone()
            top = db.execute(
                "SELECT b.emoji, b.name, COUNT(o.user_id) AS c "
                "FROM badge_defs b LEFT JOIN badge_owned o "
                "ON o.guild_id = b.guild_id AND o.badge_id = b.badge_id "
                "WHERE b.guild_id = ? GROUP BY b.badge_id "
                "ORDER BY c DESC, b.name LIMIT 5",
                (guild_id,),
            ).fetchall()

        return {
            "total": total, "ativas": ativas, "posses": posses,
            "membros": membros, "compras": compras, "gasto": gasto,
            "concessoes": concessoes, "revogacoes": revogacoes,
            "pendentes": pendentes, "travadas": travadas, "top": top,
        }


# ============================================================
# INTERFACE (embeds e views)
# ============================================================

def embed_insignia(b: Badge, possui: bool, donos: Optional[int] = None,
                   admin: bool = False) -> discord.Embed:
    """Embed de detalhes de uma insígnia."""
    emb = discord.Embed(
        title=f"{b.emoji} {b.name}",
        description=b.description or "*Sem descrição.*",
        color=_cor(b.rarity),
    )
    emb.add_field(name="Preço", value=f"🪙 {b.price:,} Abysmus")
    emb.add_field(name="Raridade", value=b.raridade)

    if possui:
        estado = "✅ Você já possui"
    elif b.enabled:
        estado = "🟢 Disponível"
    else:
        estado = "🔒 Indisponível"
    emb.add_field(name="Estado", value=estado)

    emb.add_field(name="Benefícios",
                  value=b.benefits or "Cargo exclusivo no servidor.",
                  inline=False)

    if donos is not None:
        emb.add_field(name="Adquirida por", value=f"{donos:,} membro(s)")
    if b.role_id:
        emb.add_field(name="Cargo", value=f"<@&{b.role_id}>")
    if admin:
        emb.set_footer(
            text=f"ID: {b.badge_id} · criação automática de cargo: "
                 f"{'sim' if b.auto_role else 'não'}"
        )
    else:
        emb.set_footer(text=f"ID: {b.badge_id}")
    return emb


class PaginaView(discord.ui.View):
    """Navegação simples entre embeds já prontos (◀ ▶)."""

    def __init__(self, dono_id: int, paginas: list[discord.Embed]):
        super().__init__(timeout=180)
        self.dono_id = dono_id
        self.paginas = paginas
        self.indice = 0
        self._atualizar()

    def _atualizar(self) -> None:
        self.anterior.disabled = self.indice <= 0
        self.proxima.disabled = self.indice >= len(self.paginas) - 1

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.dono_id:
            await interaction.response.send_message(
                "Esta consulta pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def anterior(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        self.indice -= 1
        self._atualizar()
        await interaction.response.edit_message(
            embed=self.paginas[self.indice], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def proxima(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        self.indice += 1
        self._atualizar()
        await interaction.response.edit_message(
            embed=self.paginas[self.indice], view=self)


def paginar(titulo: str, linhas: list[str], cor, rodape: str = "",
            por_pagina: int = LINHAS_POR_PAGINA) -> list[discord.Embed]:
    """Divide linhas de texto em embeds paginados."""
    blocos = [linhas[i:i + por_pagina]
              for i in range(0, len(linhas), por_pagina)] or [[]]
    paginas = []
    for n, bloco in enumerate(blocos, start=1):
        emb = discord.Embed(
            title=titulo,
            description="\n".join(bloco)[:4000] or "*Nada por aqui.*",
            color=cor,
        )
        emb.set_footer(text=f"{rodape} Página {n}/{len(blocos)}".strip())
        paginas.append(emb)
    return paginas


class LojaView(discord.ui.View):
    """
    Loja interativa: lista paginada -> detalhes -> confirmação de compra.
    Só quem abriu a loja pode usar os botões.
    """

    def __init__(self, cog: "Badges", interaction: discord.Interaction,
                 badges: list[Badge], possuidas: set[str], saldo: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.origem = interaction
        self.dono_id = interaction.user.id
        self.guild_id = interaction.guild_id
        self.badges = badges
        self.possuidas = possuidas
        self.saldo = saldo

        self.pagina = 0
        self.selecionada: Optional[str] = None
        self.modo = "lista"          # lista | detalhe | confirmar
        self.aviso = ""
        self._montar()

    # ---------- estado ----------

    def _atual(self) -> Optional[Badge]:
        return next((b for b in self.badges
                     if b.badge_id == self.selecionada), None)

    def _total_paginas(self) -> int:
        return max(1, -(-len(self.badges) // POR_PAGINA_LOJA))

    def _itens_pagina(self) -> list[Badge]:
        ini = self.pagina * POR_PAGINA_LOJA
        return self.badges[ini:ini + POR_PAGINA_LOJA]

    # ---------- embeds ----------

    def embed(self) -> discord.Embed:
        badge = self._atual()
        if self.modo != "lista" and badge is None:
            self.modo = "lista"

        if self.modo == "lista":
            emb = discord.Embed(
                title="🌙 Arquivo da Maré Morta — Insígnias",
                description=(self.aviso + "\n\n" if self.aviso else "")
                + "Relíquias, juramentos e marcas de coisas que observam do outro lado. Escolha uma insígnia para examinar — e pense bem antes de comprá-la.",
                color=discord.Colour.blurple(),
            )
            for b in self._itens_pagina():
                status = ("✅ Adquirida" if b.badge_id in self.possuidas
                          else f"🪙 {b.price:,}")
                emb.add_field(
                    name=b.rotulo,
                    value=f"{b.raridade} · {status}\n"
                          f"{b.description[:100] or '—'}",
                    inline=False,
                )
            emb.set_footer(
                text=f"Seu saldo: {self.saldo:,} Abysmus · "
                     f"Página {self.pagina + 1}/{self._total_paginas()}"
            )
            return emb

        emb = embed_insignia(badge, badge.badge_id in self.possuidas)

        if self.modo == "confirmar":
            emb.description = (
                f"**Confirmar compra?**\n"
                f"Você pagará **{badge.price:,} Abysmus** por "
                f"**{badge.rotulo}**.\nSaldo atual: {self.saldo:,}."
            )
        elif self.aviso:
            emb.description = f"{self.aviso}\n\n{emb.description}"
        return emb

    # ---------- componentes ----------

    def _montar(self) -> None:
        """Recria botões e menu conforme o modo atual."""
        self.clear_items()

        if self.modo == "lista":
            itens = self._itens_pagina()
            if itens:
                menu = discord.ui.Select(
                    placeholder="Escolha uma insígnia…",
                    options=[
                        discord.SelectOption(
                            label=b.rotulo[:100],
                            value=b.badge_id,
                            description=(f"{b.price:,} Abysmus · "
                                         f"{RARIDADES[b.rarity][0]}")[:100]
                            if b.rarity in RARIDADES else None,
                        )
                        for b in itens
                    ],
                )
                menu.callback = self._ao_escolher
                self.add_item(menu)

            for rotulo, delta in (("◀", -1), ("▶", 1)):
                destino = self.pagina + delta
                botao = discord.ui.Button(
                    label=rotulo, style=discord.ButtonStyle.secondary,
                    disabled=not (0 <= destino < self._total_paginas()),
                )
                botao.callback = self._criar_ao_pagina(delta)
                self.add_item(botao)

        elif self.modo == "detalhe":
            badge = self._atual()
            indisponivel = (badge is None or not badge.enabled
                            or badge.badge_id in self.possuidas)
            comprar = discord.ui.Button(
                label="Comprar", emoji="🛒",
                style=discord.ButtonStyle.success, disabled=indisponivel)
            comprar.callback = self._ao_comprar
            voltar = discord.ui.Button(
                label="Voltar", style=discord.ButtonStyle.secondary)
            voltar.callback = self._ao_voltar
            self.add_item(comprar)
            self.add_item(voltar)

        else:  # confirmar
            confirmar = discord.ui.Button(
                label="Confirmar compra", emoji="✅",
                style=discord.ButtonStyle.success)
            confirmar.callback = self._ao_confirmar
            cancelar = discord.ui.Button(
                label="Cancelar", style=discord.ButtonStyle.danger)
            cancelar.callback = self._ao_cancelar
            self.add_item(confirmar)
            self.add_item(cancelar)

    async def _atualizar(self, interaction: discord.Interaction) -> None:
        self._montar()
        await interaction.response.edit_message(embed=self.embed(),
                                                view=self)

    # ---------- callbacks ----------

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.dono_id:
            await interaction.response.send_message(
                "Esta loja foi aberta por outra pessoa. "
                "Use /insignias para abrir a sua.", ephemeral=True)
            return False
        return True

    async def _ao_escolher(self, interaction: discord.Interaction):
        self.selecionada = interaction.data["values"][0]
        self.modo = "detalhe"
        self.aviso = ""
        await self._atualizar(interaction)

    def _criar_ao_pagina(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.pagina = max(0, min(self._total_paginas() - 1,
                                     self.pagina + delta))
            self.aviso = ""
            await self._atualizar(interaction)
        return callback

    async def _ao_voltar(self, interaction: discord.Interaction):
        self.modo = "lista"
        self.aviso = ""
        await self._atualizar(interaction)

    async def _ao_comprar(self, interaction: discord.Interaction):
        self.modo = "confirmar"
        await self._atualizar(interaction)

    async def _ao_cancelar(self, interaction: discord.Interaction):
        self.modo = "detalhe"
        self.aviso = "Compra cancelada."
        await self._atualizar(interaction)

    async def _ao_confirmar(self, interaction: discord.Interaction):
        # A compra envolve banco + Discord: reconhece a interação primeiro.
        await interaction.response.defer()
        badge_id = self.selecionada

        resultado, cargo = await self.cog.processar_compra(
            interaction.guild, interaction.user, badge_id)
        self.aviso = self.cog.texto_compra(resultado, cargo)

        if resultado.status == "ok":
            self.possuidas.add(badge_id)
            self.saldo = resultado.saldo
        elif resultado.status == "ja_possui":
            self.possuidas.add(badge_id)
        elif resultado.status == "saldo_insuficiente":
            self.saldo = resultado.saldo

        # Recarrega o catálogo (preço/estado podem ter mudado).
        self.badges = await self.cog.db(
            self.cog.store.listar, self.guild_id, True)

        self.modo = "detalhe" if self._atual() else "lista"
        self._montar()
        await interaction.edit_original_response(embed=self.embed(),
                                                 view=self)

    async def on_timeout(self) -> None:
        """Desativa os botões quando a loja expira."""
        try:
            await self.origem.edit_original_response(view=None)
        except discord.HTTPException:
            pass


# ============================================================
# COG
# ============================================================

class Badges(commands.Cog):
    """Loja de insígnias com cargos."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = BadgeStore(lambda: bot.get_cog("XpAndCoins"))

        self._schema_ok = False
        self._schema_lock = asyncio.Lock()

        # Locks em memória: evitam trabalho duplicado em cliques/compras
        # simultâneas. A correção em si é garantida pelo banco.
        self._locks_usuario: defaultdict = defaultdict(asyncio.Lock)
        self._locks_cargo: defaultdict = defaultdict(asyncio.Lock)
        self._tarefas: set[asyncio.Task] = set()

    # ---------- ciclo de vida ----------

    async def cog_load(self) -> None:
        self._loop_fila.start()
        # O catálogo precisa existir no banco antes de /insignias ser usado.
        # Instala automaticamente em cada servidor, sem comando manual.
        self._agendar(self._instalar_catalogo_em_todos_servidores())

    async def _instalar_catalogo_em_todos_servidores(self) -> None:
        """Cadastra o catálogo padrão automaticamente em cada servidor."""
        await self.bot.wait_until_ready()
        # A economia normalmente já está carregada neste ponto. Se a ordem
        # de carregamento estiver diferente, tenta novamente sem derrubar o cog.
        for tentativa in range(6):
            try:
                for guild in list(self.bot.guilds):
                    criadas = 0
                    for item in INSIGNIAS_INICIAIS:
                        nova = await self.db(
                            self.store.criar, guild.id, item["id"],
                            item["nome"], item["descricao"], item["preco"],
                            item["raridade"], item["beneficios"],
                            item["emoji"],
                            self.bot.user.id if self.bot.user else None)
                        if nova:
                            criadas += 1
                    if criadas:
                        log.info(
                            "Catálogo lunar/RPG instalado em guild=%s: %d "
                            "insígnias novas.", guild.id, criadas)
                return
            except EconomiaIndisponivel as exc:
                log.warning("Catálogo automático aguardando economia (%d/6): %s",
                            tentativa + 1, exc)
                await asyncio.sleep(5)
            except Exception:
                log.exception("Falha ao instalar catálogo automaticamente.")
                return

    async def cog_unload(self) -> None:
        self._loop_fila.cancel()
        for tarefa in list(self._tarefas):
            tarefa.cancel()

    async def _pronto(self) -> None:
        """Cria as tabelas uma única vez (na primeira necessidade)."""
        if self._schema_ok:
            return
        async with self._schema_lock:
            if not self._schema_ok:
                await asyncio.to_thread(self.store.iniciar_schema)
                self._schema_ok = True
                log.info("Tabelas da loja de insígnias prontas.")

    async def db(self, funcao, *args):
        """Executa uma função síncrona do banco fora do event loop."""
        await self._pronto()
        return await asyncio.to_thread(funcao, *args)

    # ---------- tratamento de erros dos comandos ----------

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        original = getattr(error, "original", error)

        if isinstance(error, app_commands.CommandOnCooldown):
            texto = (f"⏳ Aguarde {error.retry_after:.0f}s para usar este "
                     "comando de novo.")
        elif isinstance(original, EconomiaIndisponivel):
            log.error("Economia indisponível: %s", original)
            texto = f"❌ {original}"
        elif isinstance(error, app_commands.CheckFailure):
            texto = "❌ Você não pode usar este comando."
        else:
            nome = interaction.command.name if interaction.command else "?"
            log.error("Erro inesperado em /%s", nome, exc_info=error)
            texto = ("❌ Ocorreu um erro inesperado. Nada foi perdido: se "
                     "você pagou, a insígnia está registrada. Tente de novo.")

        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(texto,
                                                        ephemeral=True)
        except discord.HTTPException:
            pass

    async def _exigir_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando só funciona dentro de um servidor.",
                ephemeral=True)
            return False
        if not interaction.permissions.administrator:
            await interaction.response.send_message(
                "Você precisa da permissão de administrador para usar "
                "este comando.", ephemeral=True)
            return False
        return True

    # ========================================================
    # CARGOS DO DISCORD
    # ========================================================

    @staticmethod
    def _checar_cargo(guild: discord.Guild, role) -> Optional[str]:
        """Verifica se o BOT pode entregar/remover este cargo."""
        if role.is_default():
            return "O cargo @everyone não pode ser usado."
        if role.managed:
            return "Este cargo é gerenciado por uma integração."
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return "O bot não tem a permissão Gerenciar Cargos."
        if role.position >= me.top_role.position:
            return ("O cargo está acima (ou igual) ao cargo mais alto do "
                    "bot. Mova o cargo do bot para cima dele.")
        perigosas = [n for n in PERMISSOES_PERIGOSAS
                     if getattr(role.permissions, n, False)]
        if perigosas:
            return ("O cargo tem permissões perigosas "
                    f"({', '.join(perigosas)}). Remova-as para usá-lo.")
        return None

    @staticmethod
    def _checar_autoridade(guild: discord.Guild, quem, role) -> Optional[str]:
        """Verifica se QUEM executa o comando pode administrar o cargo."""
        if guild.owner_id == quem.id:
            return None
        if role.position >= quem.top_role.position:
            return ("Seu cargo mais alto precisa estar acima deste cargo "
                    "para administrá-lo.")
        return None

    async def _criar_cargo(self, guild: discord.Guild, badge: Badge,
                           motivo: str, ator: Optional[int]):
        """Cria o cargo da insígnia e grava o ID. Chamar com o lock do cargo."""
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            raise _FalhaCargo("O bot não tem a permissão Gerenciar Cargos.")

        try:
            role = await guild.create_role(
                name=badge.rotulo[:100],
                colour=_cor(badge.rarity),
                permissions=discord.Permissions.none(),
                hoist=False,
                mentionable=False,
                reason=motivo,
            )
        except discord.Forbidden as exc:
            # Registra o detalhe retornado pelo Discord para diagnosticar
            # casos em que o bot aparenta ter Administrador/Gerenciar Cargos.
            log.warning(
                "Discord negou criação de cargo: guild=%s badge=%s bot_id=%s "
                "http_status=%s discord_code=%s detalhe=%r",
                guild.id, badge.badge_id, getattr(me, "id", None),
                getattr(exc, "status", None), getattr(exc, "code", None),
                getattr(exc, "text", str(exc)),
            )
            raise _FalhaCargo(
                "O Discord recusou criar o cargo (403 / Missing Permissions). "
                "Confira se o cargo do BOT tem Gerenciar Cargos ou Administrador "
                "e veja o log do bot para o código detalhado."
            )
        except discord.HTTPException as exc:
            raise _FalhaCargo(f"O Discord recusou criar o cargo ({exc.status}).")

        await self.db(
            lambda: self.store.definir_cargo(
                guild.id, badge.badge_id, ator, role_id=role.id,
                acao="role_created",
                detalhe=f"cargo {badge.role_id} -> {role.id} (automático)"))
        log.info("Cargo criado guild=%s insígnia=%s role=%s",
                 guild.id, badge.badge_id, role.id)
        return role

    async def _resolver_cargo(self, guild: discord.Guild, badge: Badge,
                              criar: bool):
        """
        Devolve o cargo da insígnia (por ID). Se não existir, cria um novo
        apenas quando permitido. O lock evita cargos duplicados quando
        várias compras acontecem ao mesmo tempo.
        """
        async with self._locks_cargo[(guild.id, badge.badge_id)]:
            # Relê do banco: outra tarefa pode ter criado o cargo agora.
            atual = await self.db(self.store.obter, guild.id, badge.badge_id)
            if atual is None:
                raise _FalhaCargo("A insígnia não existe mais.")

            role = guild.get_role(atual.role_id) if atual.role_id else None

            if role is None:
                if not (criar and atual.auto_role and atual.enabled):
                    raise _FalhaCargo(
                        "O cargo não está configurado ou foi excluído. Um "
                        "administrador precisa usar /insignia_configurar_cargo.")
                role = await self._criar_cargo(
                    guild, atual,
                    "Loja de insígnias: cargo criado automaticamente", None)

            problema = self._checar_cargo(guild, role)
            if problema:
                raise _FalhaCargo(problema)
            return role

    async def _obter_membro(self, guild: discord.Guild, user_id: int):
        """Membro do cache ou da API; None se saiu do servidor."""
        membro = guild.get_member(user_id)
        if membro is not None:
            return membro
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None

    async def _aplicar_cargo(self, guild: discord.Guild, user_id: int,
                             badge_id: str, op: str, membro=None,
                             zerar: bool = False) -> ResultadoCargo:
        """
        Entrega (add) ou remove (remove) o cargo e mantém a fila coerente.
        O chamador deve segurar o lock do usuário.
        Nunca levanta erro esperado: devolve ResultadoCargo.
        """
        try:
            # A fila pode estar velha: confirma a intenção no banco.
            possui = await self.db(self.store.possui, guild.id, user_id,
                                   badge_id)
            if (op == "add") != possui:
                await self.db(self.store.fila_remover, guild.id, user_id,
                              badge_id)
                return ResultadoCargo(True, "nada",
                                      "Pendência obsoleta descartada.")

            badge = await self.db(self.store.obter, guild.id, badge_id)
            if badge is None:
                raise _FalhaCargo("A insígnia não existe.")

            membro = membro or await self._obter_membro(guild, user_id)
            if membro is None:
                raise _FalhaCargo("O membro não está no servidor.")

            if op == "add":
                role = await self._resolver_cargo(guild, badge, criar=True)
                if role in membro.roles:
                    acao = "ja_tinha"
                else:
                    await membro.add_roles(
                        role, reason=f"Insígnia '{badge_id}' adquirida")
                    acao = "aplicado"
            else:
                role = guild.get_role(badge.role_id) if badge.role_id else None
                if role is not None and role in membro.roles:
                    problema = self._checar_cargo(guild, role)
                    if problema:
                        raise _FalhaCargo(problema)
                    await membro.remove_roles(
                        role, reason=f"Insígnia '{badge_id}' revogada")
                    acao = "removido"
                else:
                    acao = "nada"

            await self.db(self.store.fila_concluir, guild.id, user_id,
                          badge_id)
            log.info("Cargo %s guild=%s user=%s insígnia=%s -> %s",
                     op, guild.id, user_id, badge_id, acao)
            return ResultadoCargo(True, acao,
                                  mencao=role.mention if role else "")

        except _FalhaCargo as exc:
            mensagem = str(exc)
        except discord.Forbidden:
            mensagem = ("Sem permissão. Verifique Gerenciar Cargos e a "
                        "posição do cargo do bot.")
        except discord.HTTPException as exc:
            mensagem = f"Erro temporário do Discord ({exc.status})."

        tentativas = await self.db(
            self.store.fila_falhou, guild.id, user_id, badge_id, op,
            mensagem, zerar)
        log.warning("Falha de cargo %s guild=%s user=%s insígnia=%s "
                    "(tentativa %s): %s",
                    op, guild.id, user_id, badge_id, tentativas, mensagem)
        return ResultadoCargo(False, "falha", mensagem)

    # ---------- fila persistente ----------

    @tasks.loop(minutes=INTERVALO_FILA_MIN)
    async def _loop_fila(self) -> None:
        """Reprocessa entregas de cargo pendentes (também após reinício)."""
        try:
            pendentes = await self.db(self.store.fila_pendentes, LOTE_FILA,
                                      MAX_TENTATIVAS_AUTO)
            if pendentes:
                log.info("Fila de cargos: %d pendência(s).", len(pendentes))
            for item in pendentes:
                await self._processar_item(item)
        except EconomiaIndisponivel as exc:
            log.warning("Fila de cargos adiada: %s", exc)
        except Exception:
            log.exception("Erro ao processar a fila de cargos.")

    @_loop_fila.before_loop
    async def _antes_loop_fila(self) -> None:
        # Espera o bot conectar e carregar os servidores/cargos em cache.
        await self.bot.wait_until_ready()

    async def _processar_item(self, item: ItemFila) -> None:
        guild = self.bot.get_guild(item.guild_id)
        if guild is None:
            return  # o bot saiu do servidor; mantém o registro
        async with self._locks_usuario[(item.guild_id, item.user_id)]:
            await self._aplicar_cargo(guild, item.user_id, item.badge_id,
                                      item.op)
        await asyncio.sleep(1)  # respeita o rate limit do Discord

    def _agendar(self, corotina) -> None:
        """Roda uma corrotina em segundo plano mantendo a referência."""
        tarefa = asyncio.create_task(corotina)
        self._tarefas.add(tarefa)
        tarefa.add_done_callback(self._tarefas.discard)

    async def _drenar_guild(self, guild_id: int) -> None:
        """Entrega as pendências de um servidor (usado após mudar cargo)."""
        try:
            itens = await self.db(self.store.fila_pendentes, 1000,
                                  MAX_TENTATIVAS_AUTO, guild_id)
            for item in itens:
                await self._processar_item(item)
        except Exception:
            log.exception("Erro ao drenar a fila do servidor %s.", guild_id)

    # ========================================================
    # COMPRA E SINCRONIZAÇÃO
    # ========================================================

    async def processar_compra(self, guild: discord.Guild, membro,
                               badge_id: str):
        """Compra + entrega do cargo. Devolve (ResultadoCompra, cargo)."""
        async with self._locks_usuario[(guild.id, membro.id)]:
            resultado = await self.db(self.store.comprar, guild.id,
                                      membro.id, badge_id)
            if resultado.status != "ok":
                return resultado, None

            log.info("Compra guild=%s user=%s insígnia=%s preço=%s saldo=%s",
                     guild.id, membro.id, badge_id, resultado.badge.price,
                     resultado.saldo)
            cargo = await self._aplicar_cargo(guild, membro.id, badge_id,
                                              "add", membro=membro)
        return resultado, cargo

    @staticmethod
    def texto_compra(res: ResultadoCompra,
                     cargo: Optional[ResultadoCargo]) -> str:
        """Mensagem amigável para o resultado de uma compra."""
        b = res.badge
        if res.status == "inexistente":
            return "❌ Essa insígnia não existe."
        if res.status == "desativada":
            return f"🔒 **{b.rotulo}** não está disponível no momento."
        if res.status == "ja_possui":
            return (f"✅ Você já possui **{b.rotulo}**. "
                    "Nada foi cobrado.")
        if res.status == "saldo_insuficiente":
            return (f"❌ Saldo insuficiente: você tem {res.saldo:,} Abysmus "
                    f"e **{b.rotulo}** custa {b.price:,}.")

        base = (f"🎉 Você comprou **{b.rotulo}** por {b.price:,} Abysmus. "
                f"Saldo: {res.saldo:,}.")
        if cargo is not None and cargo.ok:
            return base + (f" Cargo {cargo.mencao} entregue." if cargo.mencao
                           else "")
        motivo = cargo.mensagem if cargo else "erro desconhecido"
        return (base + f"\n⚠️ A insígnia é sua, mas o cargo ficou pendente: "
                f"{motivo}\nNada será cobrado de novo; ele será entregue "
                "automaticamente ou use /insignia_sincronizar.")

    async def sincronizar_membro(self, guild: discord.Guild, user_id: int,
                                 membro=None):
        """
        Reentrega os cargos das insígnias que o membro POSSUI no banco.
        Só adiciona; nunca remove cargos. Não cobra nada.
        """
        donas = await self.db(self.store.listar_do_membro, guild.id, user_id)
        resultados = []
        async with self._locks_usuario[(guild.id, user_id)]:
            for badge, _adquirida, _origem in donas:
                r = await self._aplicar_cargo(guild, user_id, badge.badge_id,
                                              "add", membro=membro,
                                              zerar=True)
                resultados.append((badge, r))
        return resultados

    # ========================================================
    # AUTOCOMPLETE
    # ========================================================

    async def _autocomplete(self, interaction: discord.Interaction,
                            current: str, modo: str):
        """Sugere insígnias; modo: comprar | publico | todas."""
        if interaction.guild_id is None:
            return []
        try:
            badges = await self.db(self.store.listar, interaction.guild_id,
                                   False)
            if modo == "comprar":
                possui = await self.db(self.store.ids_do_membro,
                                       interaction.guild_id,
                                       interaction.user.id)
                badges = [b for b in badges
                          if b.enabled and b.badge_id not in possui]
            elif modo == "publico" and not interaction.permissions.administrator:
                badges = [b for b in badges if b.enabled]
        except Exception:
            log.exception("Falha no autocomplete de insígnias.")
            return []

        termo = current.strip().casefold()
        escolhas = []
        for b in badges:
            if termo and termo not in b.badge_id \
                    and termo not in b.name.casefold():
                continue
            marca = "" if b.enabled else " [desativada]"
            escolhas.append(app_commands.Choice(
                name=f"{b.rotulo} — {b.price:,} 🪙 ({b.badge_id}){marca}"[:100],
                value=b.badge_id))
            if len(escolhas) >= 25:
                break
        return escolhas

    # ========================================================
    # COMANDOS DE MEMBROS
    # ========================================================

    @app_commands.command(
        name="insignias", description="Abra a loja de insígnias.")
    @app_commands.guild_only()
    async def insignias(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        badges = await self.db(self.store.listar, interaction.guild_id, True)
        if not badges:
            await interaction.followup.send(
                "A loja ainda não tem insígnias disponíveis.", ephemeral=True)
            return

        possuidas = await self.db(self.store.ids_do_membro,
                                  interaction.guild_id, interaction.user.id)
        saldo = await self.db(self.store.saldo, interaction.guild_id,
                              interaction.user.id)

        view = LojaView(self, interaction, badges, set(possuidas), saldo)
        await interaction.followup.send(embed=view.embed(), view=view,
                                        ephemeral=True)

    @app_commands.command(
        name="insignia_comprar",
        description="Compre uma insígnia com Abysmus.")
    @app_commands.guild_only()
    @app_commands.describe(insignia="Insígnia que deseja comprar.")
    async def insignia_comprar(self, interaction: discord.Interaction,
                               insignia: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        resultado, cargo = await self.processar_compra(
            interaction.guild, interaction.user, insignia.strip().lower())
        await interaction.followup.send(self.texto_compra(resultado, cargo),
                                        ephemeral=True)

    @insignia_comprar.autocomplete("insignia")
    async def _ac_comprar(self, interaction: discord.Interaction,
                          current: str):
        return await self._autocomplete(interaction, current, "comprar")

    @app_commands.command(
        name="minhas_insignias",
        description="Veja as insígnias que você possui.")
    @app_commands.guild_only()
    async def minhas_insignias(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        donas = await self.db(self.store.listar_do_membro,
                              interaction.guild_id, interaction.user.id)
        if not donas:
            await interaction.followup.send(
                "Você ainda não possui insígnias. Use /insignias para "
                "conhecer a loja.", ephemeral=True)
            return

        ids_cargos = {r.id for r in interaction.user.roles}
        linhas = []
        for badge, adquirida, origem in donas:
            if not badge.role_id:
                cargo = "— sem cargo configurado"
            elif badge.role_id in ids_cargos:
                cargo = "✅ cargo ativo"
            else:
                cargo = "⚠️ cargo pendente (use /insignia_sincronizar)"
            origem_txt = "presente da administração" \
                if origem == "admin" else "comprada"
            linhas.append(
                f"{badge.rotulo} · {badge.raridade}\n"
                f"↳ {origem_txt} em {_ts(adquirida)} · {cargo}")

        paginas = paginar("🏅 Suas insígnias", linhas,
                          discord.Colour.gold(),
                          rodape=f"{len(donas)} insígnia(s).")
        # followup.send não aceita view=None: só envia a view se houver.
        extra = ({"view": PaginaView(interaction.user.id, paginas)}
                 if len(paginas) > 1 else {})
        await interaction.followup.send(embed=paginas[0], ephemeral=True,
                                        **extra)

    @app_commands.command(
        name="insignia_detalhes",
        description="Veja os detalhes de uma insígnia.")
    @app_commands.guild_only()
    @app_commands.describe(insignia="Insígnia que deseja consultar.")
    async def insignia_detalhes(self, interaction: discord.Interaction,
                                insignia: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        admin = interaction.permissions.administrator

        badge = await self.db(self.store.obter, interaction.guild_id,
                              insignia.strip().lower())
        if badge is None or (not badge.enabled and not admin):
            await interaction.followup.send("❌ Insígnia não encontrada.",
                                            ephemeral=True)
            return

        possui = await self.db(self.store.possui, interaction.guild_id,
                               interaction.user.id, badge.badge_id)
        donos = await self.db(self.store.contar_donos,
                              interaction.guild_id, badge.badge_id)
        await interaction.followup.send(
            embed=embed_insignia(badge, possui, donos, admin),
            ephemeral=True)

    @insignia_detalhes.autocomplete("insignia")
    async def _ac_detalhes(self, interaction: discord.Interaction,
                           current: str):
        return await self._autocomplete(interaction, current, "publico")

    @app_commands.command(
        name="insignia_sincronizar",
        description="Recupere os cargos das insígnias que você já possui.")
    @app_commands.guild_only()
    @app_commands.describe(
        membro="(Admin) Sincronizar outro membro.",
        todos="(Admin) Sincronizar todos os donos de insígnias.")
    @app_commands.checks.cooldown(
        1, 30.0, key=lambda i: (i.guild_id, i.user.id))
    async def insignia_sincronizar(
            self, interaction: discord.Interaction,
            membro: Optional[discord.Member] = None,
            todos: bool = False):
        if (membro is not None or todos) \
                and not await self._exigir_admin(interaction):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild

        if todos:
            await self._sincronizar_todos(interaction)
            return

        alvo = membro or interaction.user
        resultados = await self.sincronizar_membro(guild, alvo.id, alvo)
        if not resultados:
            await interaction.followup.send(
                f"{alvo.mention} não possui insígnias registradas.",
                ephemeral=True)
            return

        icones = {"aplicado": "✅ cargo restaurado",
                  "ja_tinha": "☑️ já estava correto"}
        linhas = []
        for badge, r in resultados:
            texto = icones.get(r.acao) if r.ok else f"❌ {r.mensagem}"
            linhas.append(f"{badge.rotulo} — {texto or '☑️ ok'}")
        await interaction.followup.send(
            "**Sincronização concluída** (nada foi cobrado):\n"
            + "\n".join(linhas), ephemeral=True)

    async def _sincronizar_todos(self, interaction: discord.Interaction):
        """Sincroniza todos os donos de insígnias do servidor (admin)."""
        guild = interaction.guild
        donos = await self.db(self.store.donos_do_servidor, guild.id)

        restaurados = falhas = 0
        detalhes: list[str] = []
        for user_id in donos:
            for badge, r in await self.sincronizar_membro(guild, user_id):
                if r.ok and r.acao == "aplicado":
                    restaurados += 1
                    await asyncio.sleep(0.5)  # rate limit
                elif not r.ok:
                    falhas += 1
                    if len(detalhes) < 10:
                        detalhes.append(
                            f"<@{user_id}> · {badge.rotulo}: {r.mensagem}")

        texto = (f"**Sincronização geral concluída**\n"
                 f"Membros verificados: {len(donos):,}\n"
                 f"Cargos restaurados: {restaurados:,}\n"
                 f"Falhas: {falhas:,}")
        if detalhes:
            texto += "\n" + "\n".join(detalhes)
        await interaction.followup.send(texto[:1900], ephemeral=True)

    # ========================================================
    # COMANDOS DE ADMINISTRAÇÃO
    # ========================================================

    @staticmethod
    def _validar_campos(nome=None, descricao=None, beneficios=None,
                        emoji=None) -> Optional[str]:
        """Valida textos de insígnia; devolve a mensagem de erro, se houver."""
        if nome is not None and not (1 <= len(nome) <= MAX_NOME):
            return f"O nome deve ter de 1 a {MAX_NOME} caracteres."
        if descricao is not None and len(descricao) > MAX_DESCRICAO:
            return f"A descrição pode ter até {MAX_DESCRICAO} caracteres."
        if beneficios is not None and len(beneficios) > MAX_BENEFICIOS:
            return f"Os benefícios podem ter até {MAX_BENEFICIOS} caracteres."
        if emoji is not None and not (1 <= len(emoji) <= MAX_EMOJI):
            return f"O emoji deve ter de 1 a {MAX_EMOJI} caracteres."
        return None

    @app_commands.command(
        name="insignia_criar",
        description="Crie uma nova insígnia (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        insignia_id="ID único: 2-40 caracteres (a-z, 0-9, _ ou -).",
        nome="Nome exibido da insígnia.",
        preco="Preço em Abysmus.",
        descricao="Descrição da insígnia.",
        raridade="Raridade (padrão: comum).",
        beneficios="Benefícios concedidos (texto exibido na loja).",
        emoji="Emoji da insígnia (padrão: 🏅).")
    @app_commands.choices(raridade=ESCOLHAS_RARIDADE)
    async def insignia_criar(
            self, interaction: discord.Interaction, insignia_id: str,
            nome: str, preco: app_commands.Range[int, 0, 1_000_000],
            descricao: str,
            raridade: Optional[app_commands.Choice[str]] = None,
            beneficios: str = "", emoji: str = "🏅"):
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        badge_id = insignia_id.strip().lower()
        nome, descricao = nome.strip(), descricao.strip()
        beneficios, emoji = beneficios.strip(), emoji.strip() or "🏅"

        if not ID_RE.fullmatch(badge_id):
            await interaction.followup.send(
                "❌ ID inválido. Use de 2 a 40 caracteres: a-z, 0-9, _ ou -.",
                ephemeral=True)
            return
        erro = self._validar_campos(nome, descricao, beneficios, emoji)
        if erro:
            await interaction.followup.send(f"❌ {erro}", ephemeral=True)
            return

        chave_raridade = raridade.value if raridade else "comum"
        criada = await self.db(
            self.store.criar, interaction.guild_id, badge_id, nome,
            descricao, int(preco), chave_raridade, beneficios, emoji,
            interaction.user.id)
        if not criada:
            await interaction.followup.send(
                "❌ Já existe uma insígnia com esse ID.", ephemeral=True)
            return

        log.info("Insígnia criada guild=%s id=%s por=%s preço=%s",
                 interaction.guild_id, badge_id, interaction.user.id, preco)
        await interaction.followup.send(
            f"✅ Insígnia **{emoji} {nome}** criada por **{preco:,} "
            "Abysmus**.\nO cargo será criado automaticamente na primeira "
            "compra (ou use /insignia_configurar_cargo).", ephemeral=True)

    @app_commands.command(
        name="insignia_editar",
        description="Edite uma insígnia (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        insignia="Insígnia que será editada.",
        nome="Novo nome.", descricao="Nova descrição.",
        preco="Novo preço em Abysmus.", raridade="Nova raridade.",
        beneficios="Novos benefícios.", emoji="Novo emoji.")
    @app_commands.choices(raridade=ESCOLHAS_RARIDADE)
    async def insignia_editar(
            self, interaction: discord.Interaction, insignia: str,
            nome: Optional[str] = None, descricao: Optional[str] = None,
            preco: Optional[app_commands.Range[int, 0, 1_000_000]] = None,
            raridade: Optional[app_commands.Choice[str]] = None,
            beneficios: Optional[str] = None, emoji: Optional[str] = None):
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        campos = {}
        if nome is not None:
            campos["name"] = nome.strip()
        if descricao is not None:
            campos["description"] = descricao.strip()
        if preco is not None:
            campos["price"] = int(preco)
        if raridade is not None:
            campos["rarity"] = raridade.value
        if beneficios is not None:
            campos["benefits"] = beneficios.strip()
        if emoji is not None:
            campos["emoji"] = emoji.strip()

        if not campos:
            await interaction.followup.send(
                "❌ Informe pelo menos um campo para editar.",
                ephemeral=True)
            return
        erro = self._validar_campos(
            campos.get("name"), campos.get("description"),
            campos.get("benefits"), campos.get("emoji"))
        if erro:
            await interaction.followup.send(f"❌ {erro}", ephemeral=True)
            return

        novo = await self.db(
            lambda: self.store.editar(
                interaction.guild_id, insignia.strip().lower(),
                interaction.user.id, **campos))
        if novo is None:
            await interaction.followup.send("❌ Insígnia não encontrada.",
                                            ephemeral=True)
            return

        log.info("Insígnia editada guild=%s id=%s por=%s campos=%s",
                 interaction.guild_id, novo.badge_id, interaction.user.id,
                 list(campos))
        await interaction.followup.send(
            "✅ Insígnia atualizada. Quem já a possui não é afetado por "
            "mudanças de preço.",
            embed=embed_insignia(novo, False, admin=True), ephemeral=True)

    async def _alternar_ativa(self, interaction: discord.Interaction,
                              insignia: str, ativa: bool):
        """Lógica comum de /insignia_ativar e /insignia_desativar."""
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        status = await self.db(
            self.store.definir_ativa, interaction.guild_id,
            insignia.strip().lower(), ativa, interaction.user.id)

        if status == "inexistente":
            texto = "❌ Insígnia não encontrada."
        elif status == "sem_mudanca":
            texto = ("ℹ️ A insígnia já estava "
                     f"{'ativada' if ativa else 'desativada'}.")
        else:
            log.info("Insígnia %s guild=%s id=%s por=%s",
                     "ativada" if ativa else "desativada",
                     interaction.guild_id, insignia, interaction.user.id)
            texto = (f"✅ Insígnia `{insignia}` "
                     f"{'ativada' if ativa else 'desativada'}. "
                     "Quem já a possui continua com ela.")
        await interaction.followup.send(texto, ephemeral=True)

    @app_commands.command(
        name="insignia_ativar",
        description="Ative uma insígnia na loja (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(insignia="Insígnia que será ativada.")
    async def insignia_ativar(self, interaction: discord.Interaction,
                              insignia: str):
        await self._alternar_ativa(interaction, insignia, True)

    @app_commands.command(
        name="insignia_desativar",
        description="Retire uma insígnia da venda (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(insignia="Insígnia que será desativada.")
    async def insignia_desativar(self, interaction: discord.Interaction,
                                 insignia: str):
        await self._alternar_ativa(interaction, insignia, False)

    @app_commands.command(
        name="insignia_configurar_cargo",
        description="Defina ou recrie o cargo de uma insígnia (admin).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        insignia="Insígnia a configurar.",
        cargo="Cargo EXISTENTE que será vinculado à insígnia.",
        criar_novo="Criar um cargo novo agora (substitui o vínculo atual).",
        auto_criar="Permitir que o bot crie/recrie o cargo sozinho.")
    async def insignia_configurar_cargo(
            self, interaction: discord.Interaction, insignia: str,
            cargo: Optional[discord.Role] = None, criar_novo: bool = False,
            auto_criar: Optional[bool] = None):
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        badge_id = insignia.strip().lower()

        if cargo is None and not criar_novo and auto_criar is None:
            await interaction.followup.send(
                "❌ Informe um cargo, `criar_novo` ou `auto_criar`.",
                ephemeral=True)
            return
        if cargo is not None and criar_novo:
            await interaction.followup.send(
                "❌ Escolha entre vincular um cargo existente ou criar um "
                "novo, não os dois.", ephemeral=True)
            return

        badge = await self.db(self.store.obter, guild.id, badge_id)
        if badge is None:
            await interaction.followup.send("❌ Insígnia não encontrada.",
                                            ephemeral=True)
            return

        novo_role_id: Optional[int] = None
        if cargo is not None:
            problema = (self._checar_cargo(guild, cargo)
                        or self._checar_autoridade(guild, interaction.user,
                                                   cargo))
            if problema:
                await interaction.followup.send(f"❌ {problema}",
                                                ephemeral=True)
                return
            novo_role_id = cargo.id

        elif criar_novo:
            try:
                async with self._locks_cargo[(guild.id, badge_id)]:
                    role = await self._criar_cargo(
                        guild, badge,
                        f"Cargo da insígnia criado por "
                        f"{interaction.user} (comando)",
                        interaction.user.id)
            except _FalhaCargo as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            novo_role_id = role.id

        # No caso de "criar_novo" o ID já foi gravado por _criar_cargo.
        if cargo is not None or auto_criar is not None:
            status, _antigo = await self.db(
                lambda: self.store.definir_cargo(
                    guild.id, badge_id, interaction.user.id,
                    role_id=cargo.id if cargo is not None else None,
                    auto_role=auto_criar))
            if status == "role_em_uso":
                await interaction.followup.send(
                    "❌ Esse cargo já está vinculado a outra insígnia.",
                    ephemeral=True)
                return

        entregues = 0
        if novo_role_id is not None:
            # Quem já possui a insígnia recebe o novo cargo (em segundo plano).
            entregues = await self.db(self.store.fila_enfileirar_donos,
                                      guild.id, badge_id)
            self._agendar(self._drenar_guild(guild.id))

        log.info("Cargo configurado guild=%s insígnia=%s role=%s por=%s",
                 guild.id, badge_id, novo_role_id, interaction.user.id)
        partes = ["✅ Configuração salva."]
        if novo_role_id is not None:
            partes.append(f"Cargo: <@&{novo_role_id}>.")
        if entregues:
            partes.append(f"Entregando o cargo a {entregues:,} membro(s) "
                          "que já possuem a insígnia.")
        if auto_criar is not None:
            partes.append("Criação automática: "
                          f"{'ligada' if auto_criar else 'desligada'}.")
        await interaction.followup.send(" ".join(partes), ephemeral=True)

    @app_commands.command(
        name="insignia_conceder",
        description="Conceda uma insígnia sem cobrança (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(membro="Quem receberá a insígnia.",
                           insignia="Insígnia a conceder.")
    async def insignia_conceder(self, interaction: discord.Interaction,
                                membro: discord.Member, insignia: str):
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self._conceder_ou_revogar(interaction, membro, insignia, True)

    @app_commands.command(
        name="insignia_revogar",
        description="Remova uma insígnia de um membro (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(membro="Quem perderá a insígnia.",
                           insignia="Insígnia a revogar.")
    async def insignia_revogar(self, interaction: discord.Interaction,
                               membro: discord.Member, insignia: str):
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        await self._conceder_ou_revogar(interaction, membro, insignia, False)

    async def _conceder_ou_revogar(self, interaction, membro, insignia,
                                   conceder: bool):
        """Lógica comum de /insignia_conceder e /insignia_revogar."""
        guild = interaction.guild
        badge_id = insignia.strip().lower()

        if membro.bot:
            await interaction.followup.send(
                "❌ Bots não podem receber insígnias.", ephemeral=True)
            return

        badge = await self.db(self.store.obter, guild.id, badge_id)
        if badge is None:
            await interaction.followup.send("❌ Insígnia não encontrada.",
                                            ephemeral=True)
            return

        # Quem administra precisa ter autoridade sobre o cargo envolvido.
        role = guild.get_role(badge.role_id) if badge.role_id else None
        if role is not None:
            problema = self._checar_autoridade(guild, interaction.user, role)
            if problema:
                await interaction.followup.send(f"❌ {problema}",
                                                ephemeral=True)
                return

        funcao = self.store.conceder if conceder else self.store.revogar
        async with self._locks_usuario[(guild.id, membro.id)]:
            status = await self.db(funcao, guild.id, membro.id, badge_id,
                                   interaction.user.id)
            if status == "ok":
                cargo = await self._aplicar_cargo(
                    guild, membro.id, badge_id,
                    "add" if conceder else "remove", membro=membro)

        if status == "inexistente":
            texto = "❌ Insígnia não encontrada."
        elif status == "ja_possui":
            texto = f"ℹ️ {membro.mention} já possui {badge.rotulo}."
        elif status == "nao_possui":
            texto = f"ℹ️ {membro.mention} não possui {badge.rotulo}."
        else:
            log.info("Insígnia %s guild=%s user=%s insígnia=%s por=%s",
                     "concedida" if conceder else "revogada", guild.id,
                     membro.id, badge_id, interaction.user.id)
            verbo = "concedida a" if conceder else "revogada de"
            texto = f"✅ {badge.rotulo} {verbo} {membro.mention}."
            if not cargo.ok:
                texto += (f"\n⚠️ O cargo ficou pendente: {cargo.mensagem} "
                          "Será tentado de novo automaticamente.")
        await interaction.followup.send(texto, ephemeral=True)

    @app_commands.command(
        name="insignia_auditoria",
        description="Estatísticas e histórico da loja (administradores).")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        membro="Filtrar por membro.", insignia="Filtrar por insígnia.",
        acao="Filtrar por tipo de operação.")
    @app_commands.choices(acao=[
        app_commands.Choice(name=nome, value=chave)
        for chave, nome in ACOES.items()
        if chave in ("purchase", "admin_grant", "admin_revoke", "edit",
                     "role_fail", "role_recovered")
    ])
    async def insignia_auditoria(
            self, interaction: discord.Interaction,
            membro: Optional[discord.Member] = None,
            insignia: Optional[str] = None,
            acao: Optional[app_commands.Choice[str]] = None):
        if not await self._exigir_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        gid = interaction.guild_id
        s = await self.db(self.store.estatisticas, gid)
        registros = await self.db(
            self.store.auditoria, gid,
            membro.id if membro else None,
            insignia.strip().lower() if insignia else None,
            acao.value if acao else None)

        # Página 1: estatísticas gerais da loja.
        stats = discord.Embed(title="📊 Estatísticas da loja",
                              color=discord.Colour.blurple())
        stats.add_field(name="Catálogo",
                        value=f"{s['total']} insígnia(s), {s['ativas']} ativa(s)")
        stats.add_field(name="Compras",
                        value=f"{s['compras']:,} · 🪙 {s['gasto']:,} gastos")
        stats.add_field(name="Posses",
                        value=f"{s['posses']:,} com {s['membros']:,} membro(s)")
        stats.add_field(name="Administração",
                        value=f"{s['concessoes']} concessão(ões), "
                              f"{s['revogacoes']} revogação(ões)")
        stats.add_field(
            name="Cargos pendentes",
            value=f"{s['pendentes']} ({s['travadas']} travada(s))")
        stats.add_field(
            name="Mais populares",
            value="\n".join(f"{e} {n} — {c:,}" for e, n, c in s["top"])
            or "—", inline=False)

        linhas = []
        for rid, criado, acao_, uid, bid, valor, ator, detalhe in registros:
            partes = [f"`#{rid}` {_ts(criado, 'R')} **"
                      f"{ACOES.get(acao_, acao_)}**"]
            if uid:
                partes.append(f"<@{uid}>")
            if bid:
                partes.append(f"`{bid}`")
            if valor:
                partes.append(f"🪙 {valor:,}")
            if ator and ator != uid:
                partes.append(f"por <@{ator}>")
            if detalhe:
                partes.append(f"— {detalhe[:80]}")
            linhas.append(" ".join(partes))

        paginas = [stats] + paginar(
            "🧾 Histórico", linhas, discord.Colour.dark_grey(),
            rodape=f"{len(registros)} registro(s).")
        extra = ({"view": PaginaView(interaction.user.id, paginas)}
                 if len(paginas) > 1 else {})
        await interaction.followup.send(embed=paginas[0], ephemeral=True,
                                        **extra)

    # Autocomplete dos comandos administrativos (lista todas as insígnias).
    async def _ac_todas(self, interaction: discord.Interaction,
                        current: str):
        return await self._autocomplete(interaction, current, "todas")

    @insignia_editar.autocomplete("insignia")
    async def _ac_editar(self, interaction, current: str):
        return await self._ac_todas(interaction, current)

    @insignia_ativar.autocomplete("insignia")
    async def _ac_ativar(self, interaction, current: str):
        return await self._ac_todas(interaction, current)

    @insignia_desativar.autocomplete("insignia")
    async def _ac_desativar(self, interaction, current: str):
        return await self._ac_todas(interaction, current)

    @insignia_configurar_cargo.autocomplete("insignia")
    async def _ac_cargo(self, interaction, current: str):
        return await self._ac_todas(interaction, current)

    @insignia_conceder.autocomplete("insignia")
    async def _ac_conceder(self, interaction, current: str):
        return await self._ac_todas(interaction, current)

    @insignia_revogar.autocomplete("insignia")
    async def _ac_revogar(self, interaction, current: str):
        return await self._ac_todas(interaction, current)

    @insignia_auditoria.autocomplete("insignia")
    async def _ac_auditoria(self, interaction, current: str):
        return await self._ac_todas(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Badges(bot))
