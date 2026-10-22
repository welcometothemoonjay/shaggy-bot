"""
UTILITY — Ajuda, status, moderação, cargos e ferramentas de canal
=================================================================

Cog do Shaggy Bot (discord.py 2.x). Salve como  cogs/ultility.py
(mesmo nome do arquivo antigo, para substituí-lo; se o nome mudar, o bot
carregaria dois /help e daria erro).

COMANDOS
--------
Para todos
  /help [comando]      ajuda interativa por categoria (só mostra o que você
                       pode usar; detalha um comando se você informar o nome)
  /ping                teste de latência: gateway, API, edição e banco
  /status              painel do bot: uptime, recursos, servidores, cogs
  /servidor            informações do servidor
  /usuario [membro]    informações de um membro
  /avatar [membro]     avatar em alta resolução

Moderação de membros  (/membro ...)
  expulsar, banir, desbanir, silenciar, liberar, apelido,
  avisar, avisos, limpar_avisos

Cargos  (/cargo ...)
  dar, remover, criar, editar, deletar, lista, info

Canais
  /limpar        apaga mensagens (com filtros)
  /slowmode      modo lento
  /trancar  /destrancar   impede/permite @everyone de falar
  /anunciar      envia um anúncio em embed

Desenvolvedor (somente dono do bot)  (/dev ...)
  recarregar, sincronizar

SEGURANÇA
---------
  * Todo comando exige a permissão correspondente de QUEM usa e do BOT.
  * Hierarquia respeitada: ninguém age sobre o dono, sobre si mesmo, sobre
    o próprio bot nem sobre cargos iguais ou acima do seu (ou do bot).
  * Cargos com permissão de Administrador só podem ser dados por
    administradores.
  * Ações destrutivas (deletar cargo) pedem confirmação.
  * Toda ação de moderação vai para o registro de auditoria do Discord
    (com quem executou e o motivo) e para o terminal do bot.

COMO EXPANDIR
-------------
  * Novo cog? Aparece sozinho no /help. Para dar nome e emoji à categoria,
    adicione uma linha em CATEGORIAS.
  * Novo comando de moderação: copie um de /membro e use o decorador
    @permissoes(...); o /help passa a esconder o comando de quem não pode
    usá-lo.
"""

import asyncio
import logging
import math
import platform
import re
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands

# psutil é opcional: com ele o /status mostra memória e CPU reais.
try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

# resource (só Linux/macOS) serve de alternativa para a memória.
try:
    import resource
except ImportError:  # pragma: no cover
    resource = None


# Logger do cog; aparece no terminal do Shaggy Bot.
log = logging.getLogger("shaggy.util")


# ============================================================
# CONFIGURAÇÕES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "shaggy.db"

MAX_TIMEOUT = timedelta(days=28)    # limite do Discord para silenciar
MAX_LIMPAR = 200                    # mensagens por /limpar
LIMITE_CHARS_PAGINA = 3500          # tamanho máximo de uma página do /help
TIMEOUT_VIEWS = 180                 # segundos até os botões expirarem

# Nome e emoji de cada categoria do /help (chave = nome da classe do cog).
# Cogs que não estiverem aqui aparecem automaticamente com 📦.
CATEGORIAS = {
    "Games": ("🎮", "Jogos"),
    "GameSFA": ("🃏", "SFA — Duelo de cartas"),
    "RupturaTemporal": ("🌀", "Ruptura Temporal"),
    "XpAndCoins": ("✨", "XP e Abysmus"),
    "Badges": ("🏅", "Insígnias"),
    "Social": ("💞", "Social"),
    "Mystic": ("🔮", "Místico"),
    "Utility": ("🛠️", "Utilidades e moderação"),
}

# Nomes das permissões em português (para mensagens de erro e /help).
PERMISSOES_PT = {
    "administrator": "Administrador",
    "manage_guild": "Gerenciar Servidor",
    "manage_roles": "Gerenciar Cargos",
    "manage_channels": "Gerenciar Canais",
    "manage_messages": "Gerenciar Mensagens",
    "manage_nicknames": "Gerenciar Apelidos",
    "kick_members": "Expulsar Membros",
    "ban_members": "Banir Membros",
    "moderate_members": "Silenciar Membros",
    "send_messages": "Enviar Mensagens",
    "embed_links": "Inserir Links",
    "read_message_history": "Ver Histórico de Mensagens",
}


# ============================================================
# 1. FUNÇÕES AUXILIARES PURAS (fáceis de testar)
# ============================================================

_DURACAO_RE = re.compile(
    r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
)


def parse_duracao(texto: str) -> timedelta:
    """
    Converte textos como '30s', '10m', '2h', '3d', '1h30m', '1d12h' em
    timedelta. Um número sozinho ('15') vale minutos.
    Levanta ValueError se o texto for inválido ou passar de 28 dias.
    """
    limpo = texto.strip().lower().replace(" ", "")
    if not limpo:
        raise ValueError("Informe uma duração, como 10m, 2h ou 1d.")

    if limpo.isdigit():
        total = timedelta(minutes=int(limpo))
    else:
        achado = _DURACAO_RE.fullmatch(limpo)
        if not achado or not any(achado.groups()):
            raise ValueError("Duração inválida. Use 30s, 10m, 2h, 1d12h...")
        d, h, m, s = (int(g or 0) for g in achado.groups())
        total = timedelta(days=d, hours=h, minutes=m, seconds=s)

    if total < timedelta(seconds=1):
        raise ValueError("A duração precisa ser de pelo menos 1 segundo.")
    if total > MAX_TIMEOUT:
        raise ValueError("A duração máxima é de 28 dias.")
    return total


def formatar_duracao(valor) -> str:
    """Formata segundos (ou timedelta) como '1d 2h 3min 4s'."""
    if isinstance(valor, timedelta):
        valor = valor.total_seconds()
    restante = int(valor)
    dias, restante = divmod(restante, 86400)
    horas, restante = divmod(restante, 3600)
    minutos, segundos = divmod(restante, 60)

    partes = []
    if dias:
        partes.append(f"{dias}d")
    if horas:
        partes.append(f"{horas}h")
    if minutos:
        partes.append(f"{minutos}min")
    if segundos or not partes:
        partes.append(f"{segundos}s")
    return " ".join(partes)


def qualidade_latencia(ms: Optional[float]) -> str:
    """Emoji e rótulo conforme a latência em milissegundos."""
    if ms is None or not math.isfinite(ms):
        return "⚪ indisponível"
    if ms < 100:
        return f"🟢 {ms:.0f} ms"
    if ms < 250:
        return f"🟡 {ms:.0f} ms"
    if ms < 500:
        return f"🟠 {ms:.0f} ms"
    return f"🔴 {ms:.0f} ms"


def parse_cor(texto: str) -> discord.Colour:
    """Converte '#ff8800' ou 'ff8800' em cor. Levanta ValueError."""
    limpo = texto.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", limpo):
        raise ValueError("Cor inválida. Use o formato hexadecimal: #ff8800.")
    return discord.Colour(int(limpo, 16))


def motivo_auditoria(ator, motivo: Optional[str]) -> str:
    """Texto do registro de auditoria (limite do Discord: 512)."""
    return f"{ator} ({ator.id}): {motivo or 'Sem motivo informado'}"[:512]


def uso_memoria_mb() -> tuple[Optional[float], str]:
    """Memória do processo em MB e o rótulo (atual ou pico)."""
    if psutil is not None:
        return psutil.Process().memory_info().rss / 1_048_576, "Memória"
    if resource is not None:
        bruto = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux informa em KB; macOS, em bytes.
        mb = bruto / 1_048_576 if sys.platform == "darwin" else bruto / 1024
        return mb, "Memória (pico)"
    return None, "Memória"


def checar_alvo_membro(guild, ator, alvo, bot_membro,
                       verbo: str) -> Optional[str]:
    """
    Valida se 'ator' pode agir sobre o membro 'alvo' (e se o bot pode).
    Devolve a mensagem de erro, ou None se estiver tudo certo.
    """
    if alvo.id == ator.id:
        return f"Você não pode {verbo} a si mesmo."
    if alvo.id == bot_membro.id:
        return f"Eu não posso {verbo} a mim mesmo."
    if alvo.id == guild.owner_id:
        return f"Não é possível {verbo} o dono do servidor."
    if (ator.id != guild.owner_id
            and alvo.top_role.position >= ator.top_role.position):
        return (f"O cargo mais alto de {alvo.mention} é igual ou superior "
                "ao seu.")
    if alvo.top_role.position >= bot_membro.top_role.position:
        return (f"O cargo mais alto de {alvo.mention} é igual ou superior "
                "ao meu. Mova meu cargo para cima.")
    return None


def checar_cargo(guild, ator, cargo, bot_membro) -> Optional[str]:
    """Valida se 'ator' e o bot podem dar/remover/editar este cargo."""
    if cargo.is_default():
        return "O cargo @everyone não pode ser usado nesta ação."
    if cargo.managed:
        return "Este cargo é gerenciado por uma integração ou bot."
    if (ator.id != guild.owner_id
            and cargo.position >= ator.top_role.position):
        return "Seu cargo mais alto precisa estar acima deste cargo."
    if cargo.position >= bot_membro.top_role.position:
        return ("Este cargo está acima (ou igual) ao meu cargo mais alto. "
                "Mova meu cargo para cima.")
    if (cargo.permissions.administrator
            and not ator.guild_permissions.administrator):
        return ("Cargos com permissão de Administrador só podem ser "
                "atribuídos por administradores.")
    return None


_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def criar_filtro_limpeza(membro_id: Optional[int],
                         tipo: str) -> Callable:
    """
    Cria o filtro usado pelo /limpar. Mensagens fixadas nunca são apagadas.
    tipo: todas | bots | humanos | anexos | links
    """
    def filtro(mensagem) -> bool:
        if mensagem.pinned:
            return False
        if membro_id is not None and mensagem.author.id != membro_id:
            return False
        if tipo == "bots":
            return bool(mensagem.author.bot)
        if tipo == "humanos":
            return not mensagem.author.bot
        if tipo == "anexos":
            return bool(mensagem.attachments)
        if tipo == "links":
            return bool(_URL_RE.search(mensagem.content or ""))
        return True
    return filtro


# ---------- requisitos de comandos (usados pelo /help) ----------

def permissoes(**exigidas):
    """
    Decorador de comando: exige as permissões de quem usa E registra os
    requisitos para o /help esconder o comando de quem não pode usá-lo.
    """
    def decorador(func):
        atuais = dict(getattr(func, "__permissoes__", {}))
        atuais.update(exigidas)
        func.__permissoes__ = atuais
        return app_commands.checks.has_permissions(**exigidas)(func)
    return decorador


class SomenteDono(app_commands.CheckFailure):
    """Comando restrito ao dono do bot."""


def somente_dono(func):
    """Decorador: só o dono do bot (conta do desenvolvedor) pode usar."""
    async def predicado(interaction: discord.Interaction) -> bool:
        if await interaction.client.is_owner(interaction.user):
            return True
        raise SomenteDono()

    func.__somente_dono__ = True
    return app_commands.check(predicado)(func)


def requisitos_comando(cmd) -> tuple[dict, bool]:
    """
    Devolve ({permissão: True}, somente_dono) exigidos por um comando,
    somando os requisitos do comando e as permissões padrão do grupo.
    """
    exigidas: dict = {}
    callback = getattr(cmd, "callback", None)
    exigidas.update(getattr(callback, "__permissoes__", {}))

    raiz = getattr(cmd, "root_parent", None) or cmd
    padrao = getattr(raiz, "default_permissions", None)
    if padrao is not None:
        for nome, valor in padrao:
            if valor:
                exigidas[nome] = True

    return exigidas, bool(getattr(callback, "__somente_dono__", False))


def comando_visivel(cmd, permissoes_usuario, eh_dono: bool) -> bool:
    """True se quem pergunta pode usar o comando (para filtrar o /help)."""
    exigidas, dono = requisitos_comando(cmd)
    if dono and not eh_dono:
        return False
    return all(getattr(permissoes_usuario, nome, False) for nome in exigidas)


def uso_comando(cmd) -> str:
    """Monta '/comando <obrigatório> [opcional]'."""
    partes = [f"/{cmd.qualified_name}"]
    for p in getattr(cmd, "parameters", []):
        nome = getattr(p, "display_name", p.name)
        partes.append(f"<{nome}>" if p.required else f"[{nome}]")
    return " ".join(partes)


@dataclass
class Entrada:
    """Um comando listado no /help (slash ou de prefixo)."""
    nome: str          # nome completo, sem barra
    uso: str
    descricao: str
    categoria: str     # nome da classe do cog
    prefixo: bool = False
    objeto: object = None


def nome_categoria(chave: str) -> tuple[str, str]:
    """(emoji, rótulo) de uma categoria; cogs novos recebem 📦."""
    return CATEGORIAS.get(chave, ("📦", chave))


def coletar_entradas(bot: commands.Bot, permissoes_usuario,
                     eh_dono: bool) -> dict[str, list[Entrada]]:
    """
    Reúne os comandos slash (incluindo subcomandos) e de prefixo que o
    usuário pode usar, agrupados pela classe do cog.
    """
    grupos: dict[str, list[Entrada]] = {}

    for cmd in bot.tree.walk_commands():
        # Grupos aparecem pelos seus subcomandos.
        if not isinstance(cmd, app_commands.Command):
            continue
        if not comando_visivel(cmd, permissoes_usuario, eh_dono):
            continue

        binding = getattr(cmd, "binding", None)
        categoria = (getattr(binding, "qualified_name", None)
                     or type(binding).__name__ if binding else "Outros")
        grupos.setdefault(categoria, []).append(Entrada(
            nome=cmd.qualified_name, uso=uso_comando(cmd),
            descricao=cmd.description or "Sem descrição.",
            categoria=categoria, objeto=cmd))

    prefixo = bot.command_prefix if isinstance(bot.command_prefix, str) \
        else "s!"
    for cmd in bot.commands:
        if cmd.hidden or cmd.cog_name is None:
            continue
        aliases = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases \
            else ""
        grupos.setdefault(cmd.cog_name, []).append(Entrada(
            nome=cmd.qualified_name,
            uso=f"{prefixo}{cmd.qualified_name} {cmd.signature}".strip(),
            descricao=((cmd.short_doc or cmd.brief or "Comando de prefixo.")
                       + aliases),
            categoria=cmd.cog_name, prefixo=True, objeto=cmd))

    for lista in grupos.values():
        lista.sort(key=lambda e: (e.prefixo, e.nome))
    return grupos


def paginar_linhas(linhas: list[str],
                   limite: int = LIMITE_CHARS_PAGINA) -> list[str]:
    """Agrupa linhas em blocos que cabem na descrição de um embed."""
    paginas, atual, tamanho = [], [], 0
    for linha in linhas:
        if atual and tamanho + len(linha) + 1 > limite:
            paginas.append("\n".join(atual))
            atual, tamanho = [], 0
        atual.append(linha)
        tamanho += len(linha) + 1
    if atual:
        paginas.append("\n".join(atual))
    return paginas or ["Nada por aqui."]


# ============================================================
# 2. AVISOS (única tabela do cog)
# ============================================================

class AvisosStore:
    """Persistência dos avisos de moderação (SQLite, data/shaggy.db)."""

    def __init__(self, caminho: Path):
        self.caminho = caminho

    def _conectar(self):
        return closing(sqlite3.connect(self.caminho, timeout=10))

    def iniciar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as con, con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS util_warnings (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id     INTEGER NOT NULL,
                    user_id      INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason       TEXT    NOT NULL,
                    created_at   TEXT    NOT NULL
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_util_warnings_user "
                "ON util_warnings (guild_id, user_id)"
            )

    def adicionar(self, guild_id, user_id, moderador_id, motivo):
        """Registra um aviso. Devolve (id do aviso, total do membro)."""
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conectar() as con, con:
            cur = con.execute(
                "INSERT INTO util_warnings (guild_id, user_id,"
                " moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, moderador_id, motivo, agora))
            total = con.execute(
                "SELECT COUNT(*) FROM util_warnings "
                "WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)).fetchone()[0]
            return cur.lastrowid, total

    def listar(self, guild_id, user_id):
        with self._conectar() as con:
            return con.execute(
                "SELECT id, moderator_id, reason, created_at "
                "FROM util_warnings WHERE guild_id = ? AND user_id = ? "
                "ORDER BY id DESC",
                (guild_id, user_id)).fetchall()

    def contar(self, guild_id, user_id) -> int:
        with self._conectar() as con:
            return con.execute(
                "SELECT COUNT(*) FROM util_warnings "
                "WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)).fetchone()[0]

    def remover(self, guild_id, user_id,
                aviso_id: Optional[int] = None) -> int:
        """Remove um aviso (ou todos, se aviso_id for None)."""
        with self._conectar() as con, con:
            if aviso_id is None:
                cur = con.execute(
                    "DELETE FROM util_warnings "
                    "WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id))
            else:
                cur = con.execute(
                    "DELETE FROM util_warnings "
                    "WHERE guild_id = ? AND user_id = ? AND id = ?",
                    (guild_id, user_id, aviso_id))
            return cur.rowcount


# ============================================================
# 3. INTERFACE (views)
# ============================================================

class AjudaView(discord.ui.View):
    """
    /help interativo: menu de categorias + botões ◀ ▶ para as páginas.
    Só quem abriu o menu pode usá-lo.
    """

    VISAO_GERAL = "__geral__"

    def __init__(self, dono_id: int, grupos: dict[str, list[Entrada]],
                 interaction: discord.Interaction):
        super().__init__(timeout=TIMEOUT_VIEWS)
        self.dono_id = dono_id
        self.grupos = grupos
        self.origem = interaction
        self.categoria = self.VISAO_GERAL
        self.pagina = 0
        self._montar()

    # ---------- conteúdo ----------

    def _chaves(self) -> list[str]:
        """Categorias ordenadas pelo rótulo."""
        return sorted(self.grupos, key=lambda c: nome_categoria(c)[1].lower())

    def _paginas(self) -> list[str]:
        """Páginas de texto da categoria atual."""
        linhas = []
        for e in self.grupos[self.categoria]:
            tipo = "🔹" if not e.prefixo else "▫️"
            linhas.append(f"{tipo} `{e.uso}`\n└ {e.descricao}")
        return paginar_linhas(linhas)

    def embed(self) -> discord.Embed:
        total = sum(len(v) for v in self.grupos.values())

        if self.categoria == self.VISAO_GERAL:
            emb = discord.Embed(
                title="🔎 SHAGGY // COMMAND SCANNER",
                description=(
                    f"Varredura concluída: **{total} comandos** disponíveis "
                    "para você.\nEscolha uma categoria no menu abaixo.\n"
                    "Para detalhes de um comando: `/help comando:<nome>`."),
                color=discord.Color.dark_green())
            for chave in self._chaves():
                emoji, rotulo = nome_categoria(chave)
                emb.add_field(
                    name=f"{emoji} {rotulo}",
                    value=f"{len(self.grupos[chave])} comando(s)")
            emb.set_footer(text="🔹 comando slash · ▫️ comando de prefixo")
            return emb

        emoji, rotulo = nome_categoria(self.categoria)
        paginas = self._paginas()
        self.pagina = min(self.pagina, len(paginas) - 1)
        emb = discord.Embed(
            title=f"{emoji} {rotulo}",
            description=paginas[self.pagina],
            color=discord.Color.dark_green())
        emb.set_footer(
            text=f"Página {self.pagina + 1}/{len(paginas)} · "
                 "<obrigatório> [opcional]")
        return emb

    # ---------- componentes ----------

    def _montar(self) -> None:
        self.clear_items()

        opcoes = [discord.SelectOption(
            label="Visão geral", value=self.VISAO_GERAL, emoji="📖",
            default=self.categoria == self.VISAO_GERAL)]
        for chave in self._chaves()[:24]:
            emoji, rotulo = nome_categoria(chave)
            opcoes.append(discord.SelectOption(
                label=rotulo[:100], value=chave,
                description=f"{len(self.grupos[chave])} comando(s)",
                default=chave == self.categoria))
        menu = discord.ui.Select(placeholder="Escolha uma categoria…",
                                 options=opcoes)
        menu.callback = self._ao_escolher
        self.add_item(menu)

        if self.categoria != self.VISAO_GERAL:
            total = len(self._paginas())
            for rotulo, delta in (("◀", -1), ("▶", 1)):
                destino = self.pagina + delta
                botao = discord.ui.Button(
                    label=rotulo, style=discord.ButtonStyle.secondary,
                    disabled=not (0 <= destino < total))
                botao.callback = self._criar_pagina(delta)
                self.add_item(botao)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.dono_id:
            await interaction.response.send_message(
                "Este menu pertence a outra pessoa. Use /help para abrir "
                "o seu.", ephemeral=True)
            return False
        return True

    async def _ao_escolher(self, interaction: discord.Interaction):
        self.categoria = interaction.data["values"][0]
        self.pagina = 0
        self._montar()
        await interaction.response.edit_message(embed=self.embed(),
                                                view=self)

    def _criar_pagina(self, delta: int):
        async def callback(interaction: discord.Interaction):
            self.pagina += delta
            self._montar()
            await interaction.response.edit_message(embed=self.embed(),
                                                    view=self)
        return callback

    async def on_timeout(self) -> None:
        try:
            await self.origem.edit_original_response(view=None)
        except discord.HTTPException:
            pass


class ConfirmarView(discord.ui.View):
    """Botões Confirmar/Cancelar para ações destrutivas."""

    def __init__(self, dono_id: int):
        super().__init__(timeout=30)
        self.dono_id = dono_id
        self.confirmado: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.dono_id:
            await interaction.response.send_message(
                "Apenas quem executou o comando pode confirmar.",
                ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar", emoji="✅",
                       style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        self.confirmado = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancelar",
                       style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        self.confirmado = False
        await interaction.response.defer()
        self.stop()


class PaginaView(discord.ui.View):
    """Navegação ◀ ▶ entre embeds prontos (listas de cargos, avisos...)."""

    def __init__(self, dono_id: int, paginas: list[discord.Embed]):
        super().__init__(timeout=TIMEOUT_VIEWS)
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


def embeds_paginados(titulo: str, linhas: list[str], cor,
                     por_pagina: int = 10) -> list[discord.Embed]:
    """Divide linhas em embeds de até 'por_pagina' itens."""
    blocos = [linhas[i:i + por_pagina]
              for i in range(0, len(linhas), por_pagina)] or [[]]
    paginas = []
    for n, bloco in enumerate(blocos, start=1):
        emb = discord.Embed(
            title=titulo,
            description="\n".join(bloco)[:4000] or "*Nada por aqui.*",
            color=cor)
        emb.set_footer(text=f"Página {n}/{len(blocos)}")
        paginas.append(emb)
    return paginas


# ============================================================
# 4. COG
# ============================================================

class Utility(commands.Cog):
    """Ajuda, status, moderação, cargos e ferramentas de canal."""

    # Grupos de subcomandos (aparecem como /membro ..., /cargo ..., /dev ...).
    membro = app_commands.Group(
        name="membro", description="Moderação de membros.",
        guild_only=True)
    cargo = app_commands.Group(
        name="cargo", description="Gerenciamento de cargos.",
        guild_only=True,
        default_permissions=discord.Permissions(manage_roles=True))
    dev = app_commands.Group(
        name="dev", description="Ferramentas do desenvolvedor.",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True))

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.avisos = AvisosStore(DB_PATH)
        self.iniciado_em = time.time()   # usado se o psutil não existir
        if psutil is not None:
            # A 1ª leitura de CPU sempre devolve 0: "aquece" aqui.
            psutil.cpu_percent(interval=None)

    async def cog_load(self) -> None:
        await asyncio.to_thread(self.avisos.iniciar)
        log.info("Cog Utility carregado (tabela de avisos pronta).")

    # ---------- tratamento de erros ----------

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        original = getattr(error, "original", error)

        if isinstance(error, app_commands.MissingPermissions):
            nomes = ", ".join(PERMISSOES_PT.get(p, p)
                              for p in error.missing_permissions)
            texto = f"❌ Você precisa da(s) permissão(ões): **{nomes}**."
        elif isinstance(error, app_commands.BotMissingPermissions):
            nomes = ", ".join(PERMISSOES_PT.get(p, p)
                              for p in error.missing_permissions)
            texto = f"❌ Eu preciso da(s) permissão(ões): **{nomes}**."
        elif isinstance(error, SomenteDono):
            texto = "❌ Este comando é exclusivo do dono do bot."
        elif isinstance(error, app_commands.CommandOnCooldown):
            texto = (f"⏳ Aguarde {error.retry_after:.0f}s para usar este "
                     "comando de novo.")
        elif isinstance(error, app_commands.CheckFailure):
            texto = "❌ Você não pode usar este comando aqui."
        elif isinstance(original, discord.Forbidden):
            texto = ("❌ O Discord recusou a ação. Verifique minhas "
                     "permissões e a posição do meu cargo.")
        else:
            nome = interaction.command.qualified_name \
                if interaction.command else "?"
            log.error("Erro inesperado em /%s", nome, exc_info=error)
            texto = "❌ Ocorreu um erro inesperado. Tente novamente."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(texto,
                                                        ephemeral=True)
        except discord.HTTPException:
            pass

    # ---------- utilidades internas ----------

    @staticmethod
    def _embed_acao(titulo: str, cor, linhas: list[tuple[str, str]],
                    motivo: Optional[str] = None) -> discord.Embed:
        """Embed padrão de resultado de ação de moderação."""
        emb = discord.Embed(title=titulo, color=cor)
        for nome, valor in linhas:
            emb.add_field(name=nome, value=valor)
        if motivo is not None:
            emb.add_field(name="Motivo", value=motivo[:1024] or "—",
                          inline=False)
        return emb

    @staticmethod
    async def _avisar_por_dm(usuario, guild: discord.Guild, titulo: str,
                             motivo: Optional[str], extra: str = "") -> bool:
        """Tenta avisar o usuário por DM. Devolve se conseguiu."""
        try:
            await usuario.send(embed=discord.Embed(
                title=f"{titulo} — {guild.name}",
                description=f"**Motivo:** {motivo or 'Não informado'}"
                            f"{extra}",
                color=discord.Color.dark_red()))
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    @staticmethod
    def _txt_dm(enviada: bool) -> str:
        return "✅ enviada" if enviada else "⚠️ não foi possível enviar"

    # ========================================================
    # GERAL: /help /ping /status /servidor /usuario /avatar
    # ========================================================

    @app_commands.command(
        name="help",
        description="Veja os comandos do Shaggy (ou detalhes de um deles).")
    @app_commands.describe(
        comando="Nome de um comando para ver os detalhes (opcional).")
    async def help_shaggy(self, interaction: discord.Interaction,
                          comando: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        eh_dono = await self.bot.is_owner(interaction.user)
        grupos = coletar_entradas(self.bot, interaction.permissions,
                                  eh_dono)

        if comando:
            await self._ajuda_detalhada(interaction, grupos, comando)
            return

        if not grupos:
            await interaction.followup.send("Nenhum comando encontrado.",
                                            ephemeral=True)
            return

        view = AjudaView(interaction.user.id, grupos, interaction)
        await interaction.followup.send(embed=view.embed(), view=view,
                                        ephemeral=True)

    async def _ajuda_detalhada(self, interaction, grupos, texto: str):
        """Detalha um comando: uso, parâmetros, permissões e categoria."""
        busca = texto.strip().lstrip("/").casefold()
        busca = busca.removeprefix("s!")

        alvo = None
        for lista in grupos.values():
            for e in lista:
                aliases = getattr(e.objeto, "aliases", ()) if e.prefixo \
                    else ()
                if busca == e.nome.casefold() or busca in aliases:
                    alvo = e
                    break
            if alvo:
                break

        if alvo is None:
            await interaction.followup.send(
                f"❌ Não encontrei o comando `{texto}`. Use `/help` para "
                "ver a lista.", ephemeral=True)
            return

        emoji, rotulo = nome_categoria(alvo.categoria)
        emb = discord.Embed(title=alvo.uso, description=alvo.descricao,
                            color=discord.Color.dark_green())
        emb.add_field(name="Categoria", value=f"{emoji} {rotulo}")
        emb.add_field(name="Tipo",
                      value="Prefixo" if alvo.prefixo else "Slash")

        if not alvo.prefixo:
            parametros = [
                f"`{getattr(p, 'display_name', p.name)}` "
                f"({'obrigatório' if p.required else 'opcional'}): "
                f"{p.description or '—'}"
                for p in getattr(alvo.objeto, "parameters", [])]
            if parametros:
                emb.add_field(name="Parâmetros",
                              value="\n".join(parametros)[:1024],
                              inline=False)

            exigidas, dono = requisitos_comando(alvo.objeto)
            reqs = [PERMISSOES_PT.get(p, p) for p in exigidas]
            if dono:
                reqs.append("dono do bot")
            if reqs:
                emb.add_field(name="Requer", value=", ".join(reqs),
                              inline=False)
        await interaction.followup.send(embed=emb, ephemeral=True)

    @help_shaggy.autocomplete("comando")
    async def _ac_help(self, interaction: discord.Interaction,
                       current: str):
        eh_dono = await self.bot.is_owner(interaction.user)
        grupos = coletar_entradas(self.bot, interaction.permissions,
                                  eh_dono)
        termo = current.strip().lstrip("/").casefold()
        nomes = sorted({e.nome for lista in grupos.values()
                        for e in lista if termo in e.nome.casefold()})
        return [app_commands.Choice(name=n, value=n) for n in nomes[:25]]

    @app_commands.command(
        name="ping", description="Teste de latência do Shaggy.")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def ping(self, interaction: discord.Interaction):
        # 1) ida e volta da resposta inicial (REST).
        t0 = time.perf_counter()
        await interaction.response.send_message("🏓 Medindo…")
        resposta_ms = (time.perf_counter() - t0) * 1000

        # 2) ida e volta de uma edição.
        t1 = time.perf_counter()
        await interaction.edit_original_response(content="🏓 Medindo…")
        edicao_ms = (time.perf_counter() - t1) * 1000

        # 3) latência do WebSocket (heartbeat do gateway).
        gateway = self.bot.latency
        gateway_ms = gateway * 1000 if math.isfinite(gateway) else None

        # 4) banco de dados.
        try:
            banco_ms = await asyncio.to_thread(self._testar_banco)
        except Exception:
            log.exception("Falha ao testar o banco no /ping.")
            banco_ms = None

        emb = discord.Embed(title="🏓 PONG // LATÊNCIA",
                            color=discord.Color.dark_green())
        emb.add_field(name="Gateway (WebSocket)",
                      value=qualidade_latencia(gateway_ms))
        emb.add_field(name="API (resposta)",
                      value=qualidade_latencia(resposta_ms))
        emb.add_field(name="API (edição)",
                      value=qualidade_latencia(edicao_ms))
        emb.add_field(name="Banco de dados",
                      value=qualidade_latencia(banco_ms)
                      if banco_ms is not None else "🔴 erro")
        emb.set_footer(text="🟢 <100ms · 🟡 <250ms · 🟠 <500ms · 🔴 lento")
        await interaction.edit_original_response(content=None, embed=emb)

    @staticmethod
    def _testar_banco() -> float:
        """Mede uma consulta simples ao SQLite (em milissegundos)."""
        inicio = time.perf_counter()
        with closing(sqlite3.connect(DB_PATH, timeout=5)) as con:
            con.execute("SELECT 1").fetchone()
        return (time.perf_counter() - inicio) * 1000

    @app_commands.command(
        name="status", description="Painel de status do Shaggy.")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = self.bot

        # Uptime do processo (psutil) ou do carregamento do cog.
        if psutil is not None:
            inicio = psutil.Process().create_time()
        else:
            inicio = self.iniciado_em
        uptime = formatar_duracao(time.time() - inicio)

        memoria, rotulo_memoria = uso_memoria_mb()
        gateway = bot.latency
        gateway_ms = gateway * 1000 if math.isfinite(gateway) else None

        slash = sum(1 for c in bot.tree.walk_commands()
                    if isinstance(c, app_commands.Command))
        usuarios = sum(g.member_count or 0 for g in bot.guilds)
        canais = sum(len(g.channels) for g in bot.guilds)

        try:
            tamanho_db = DB_PATH.stat().st_size / 1_048_576
            db_txt = f"{tamanho_db:.2f} MB"
        except OSError:
            db_txt = "indisponível"

        emb = discord.Embed(title="📡 SHAGGY // STATUS",
                            color=discord.Color.dark_green())
        emb.add_field(name="Estado", value="🟢 Online")
        emb.add_field(name="Tempo ativo", value=uptime)
        emb.add_field(name="Gateway", value=qualidade_latencia(gateway_ms))
        emb.add_field(name="Servidores", value=f"{len(bot.guilds):,}")
        emb.add_field(name="Membros (soma)", value=f"{usuarios:,}")
        emb.add_field(name="Canais", value=f"{canais:,}")
        emb.add_field(name="Comandos",
                      value=f"{slash} slash · {len(bot.commands)} prefixo")
        emb.add_field(
            name=rotulo_memoria,
            value=f"{memoria:.1f} MB" if memoria is not None else "—")
        if psutil is not None:
            emb.add_field(name="CPU",
                          value=f"{psutil.cpu_percent(interval=None):.0f}%")
        emb.add_field(name="Banco de dados", value=db_txt)
        emb.add_field(
            name=f"Módulos carregados ({len(bot.cogs)})",
            value=", ".join(sorted(bot.cogs))[:1024] or "—",
            inline=False)
        emb.set_footer(
            text=f"Python {platform.python_version()} · "
                 f"discord.py {discord.__version__} · "
                 f"{platform.system()}")
        await interaction.followup.send(embed=emb)

    @app_commands.command(
        name="servidor", description="Informações do servidor.")
    @app_commands.guild_only()
    async def servidor(self, interaction: discord.Interaction):
        g = interaction.guild
        emb = discord.Embed(title=f"🏰 {g.name}",
                            color=discord.Color.blurple())
        if g.icon:
            emb.set_thumbnail(url=g.icon.url)

        emb.add_field(name="ID", value=str(g.id))
        emb.add_field(name="Dono", value=f"<@{g.owner_id}>")
        emb.add_field(name="Criado em",
                      value=discord.utils.format_dt(g.created_at, "D"))
        emb.add_field(name="Membros", value=f"{g.member_count or 0:,}")
        emb.add_field(
            name="Canais",
            value=(f"💬 {len(g.text_channels)} · 🔊 "
                   f"{len(g.voice_channels)} · 📁 {len(g.categories)}"))
        emb.add_field(name="Cargos", value=str(len(g.roles) - 1))
        emb.add_field(name="Emojis", value=str(len(g.emojis)))
        emb.add_field(
            name="Impulsos",
            value=f"Nível {g.premium_tier} ({g.premium_subscription_count})")
        emb.add_field(name="Verificação",
                      value=str(g.verification_level).title())
        await interaction.response.send_message(embed=emb)

    @app_commands.command(
        name="usuario", description="Informações de um membro.")
    @app_commands.guild_only()
    @app_commands.describe(membro="Membro a consultar (padrão: você).")
    async def usuario(self, interaction: discord.Interaction,
                      membro: Optional[discord.Member] = None):
        alvo = membro or interaction.user
        emb = discord.Embed(title=f"👤 {alvo.display_name}",
                            color=alvo.colour)
        emb.set_thumbnail(url=alvo.display_avatar.url)

        emb.add_field(name="Conta", value=f"{alvo} · `{alvo.id}`",
                      inline=False)
        emb.add_field(
            name="Conta criada",
            value=discord.utils.format_dt(alvo.created_at, "D"))
        if alvo.joined_at:
            emb.add_field(
                name="Entrou no servidor",
                value=discord.utils.format_dt(alvo.joined_at, "D"))
        if alvo.premium_since:
            emb.add_field(
                name="Impulsiona desde",
                value=discord.utils.format_dt(alvo.premium_since, "D"))
        if alvo.is_timed_out():
            emb.add_field(
                name="Silenciado até",
                value=discord.utils.format_dt(alvo.timed_out_until, "R"))

        cargos = [r.mention for r in reversed(alvo.roles[1:])]
        emb.add_field(
            name=f"Cargos ({len(cargos)})",
            value=(" ".join(cargos[:12])
                   + (f" … +{len(cargos) - 12}" if len(cargos) > 12 else ""))
            or "Nenhum", inline=False)

        # Só moderadores veem a contagem de avisos.
        if interaction.permissions.moderate_members:
            total = await asyncio.to_thread(
                self.avisos.contar, interaction.guild_id, alvo.id)
            emb.add_field(name="⚠️ Avisos", value=str(total))
        await interaction.response.send_message(embed=emb)

    @app_commands.command(
        name="avatar", description="Mostre o avatar de alguém.")
    @app_commands.describe(membro="Membro a consultar (padrão: você).")
    async def avatar(self, interaction: discord.Interaction,
                     membro: Optional[discord.Member] = None):
        alvo = membro or interaction.user
        arquivo = alvo.display_avatar

        emb = discord.Embed(title=f"🖼️ Avatar de {alvo.display_name}",
                            color=discord.Color.blurple())
        emb.set_image(url=arquivo.with_size(1024).url)

        view = discord.ui.View()
        formatos = ["png", "jpg", "webp"] + (
            ["gif"] if arquivo.is_animated() else [])
        for formato in formatos:
            view.add_item(discord.ui.Button(
                label=formato.upper(), style=discord.ButtonStyle.link,
                url=arquivo.replace(size=1024, format=formato).url))
        await interaction.response.send_message(embed=emb, view=view)

    # ========================================================
    # MODERAÇÃO DE MEMBROS  (/membro ...)
    # ========================================================

    @membro.command(name="expulsar",
                    description="Expulsa um membro do servidor.")
    @app_commands.describe(membro="Quem será expulso.",
                           motivo="Motivo (vai para o registro de auditoria).")
    @permissoes(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def membro_expulsar(self, interaction: discord.Interaction,
                              membro: discord.Member,
                              motivo: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        problema = checar_alvo_membro(g, interaction.user, membro, g.me,
                                      "expulsar")
        if problema:
            await interaction.followup.send(f"❌ {problema}", ephemeral=True)
            return

        dm = await self._avisar_por_dm(membro, g, "Você foi expulso", motivo)
        await membro.kick(reason=motivo_auditoria(interaction.user, motivo))

        log.info("KICK guild=%s alvo=%s por=%s motivo=%s",
                 g.id, membro.id, interaction.user.id, motivo)
        await interaction.followup.send(embed=self._embed_acao(
            "👢 Membro expulso", discord.Color.orange(),
            [("Membro", f"{membro} (`{membro.id}`)"),
             ("DM", self._txt_dm(dm))], motivo), ephemeral=True)

    @membro.command(name="banir", description="Bane um usuário do servidor.")
    @app_commands.describe(
        usuario="Quem será banido (pode estar fora do servidor).",
        motivo="Motivo (vai para o registro de auditoria).",
        apagar_dias="Apagar mensagens dos últimos X dias (0 a 7).")
    @permissoes(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def membro_banir(
            self, interaction: discord.Interaction, usuario: discord.User,
            motivo: Optional[str] = None,
            apagar_dias: app_commands.Range[int, 0, 7] = 0):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        # Se a pessoa está no servidor, valida a hierarquia.
        presente = g.get_member(usuario.id)
        if presente is not None:
            problema = checar_alvo_membro(g, interaction.user, presente,
                                          g.me, "banir")
            if problema:
                await interaction.followup.send(f"❌ {problema}",
                                                ephemeral=True)
                return
        elif usuario.id in (interaction.user.id, g.me.id, g.owner_id):
            await interaction.followup.send(
                "❌ Você não pode banir este usuário.", ephemeral=True)
            return

        dm = False
        if presente is not None:
            dm = await self._avisar_por_dm(usuario, g, "Você foi banido",
                                           motivo)
        await g.ban(usuario, reason=motivo_auditoria(interaction.user,
                                                     motivo),
                    delete_message_seconds=apagar_dias * 86400)

        log.info("BAN guild=%s alvo=%s por=%s motivo=%s",
                 g.id, usuario.id, interaction.user.id, motivo)
        await interaction.followup.send(embed=self._embed_acao(
            "🔨 Usuário banido", discord.Color.red(),
            [("Usuário", f"{usuario} (`{usuario.id}`)"),
             ("Mensagens apagadas", f"{apagar_dias} dia(s)"),
             ("DM", self._txt_dm(dm) if presente else "— (fora do servidor)")],
            motivo), ephemeral=True)

    @membro.command(name="desbanir", description="Remove o banimento.")
    @app_commands.describe(
        usuario="Usuário banido (escolha na lista ou informe o ID).",
        motivo="Motivo do desbanimento.")
    @permissoes(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def membro_desbanir(self, interaction: discord.Interaction,
                              usuario: str, motivo: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        try:
            user_id = int(usuario.strip())
        except ValueError:
            await interaction.followup.send(
                "❌ Informe o ID numérico do usuário (use a lista).",
                ephemeral=True)
            return

        try:
            await interaction.guild.unban(
                discord.Object(id=user_id),
                reason=motivo_auditoria(interaction.user, motivo))
        except discord.NotFound:
            await interaction.followup.send(
                "❌ Este usuário não está banido.", ephemeral=True)
            return

        log.info("UNBAN guild=%s alvo=%s por=%s",
                 interaction.guild_id, user_id, interaction.user.id)
        await interaction.followup.send(
            f"✅ Banimento de `{user_id}` removido.", ephemeral=True)

    @membro_desbanir.autocomplete("usuario")
    async def _ac_desbanir(self, interaction: discord.Interaction,
                           current: str):
        termo = current.strip().casefold()
        escolhas = []
        try:
            async for entrada in interaction.guild.bans(limit=200):
                nome = f"{entrada.user} ({entrada.user.id})"
                if termo and termo not in nome.casefold():
                    continue
                escolhas.append(app_commands.Choice(
                    name=nome[:100], value=str(entrada.user.id)))
                if len(escolhas) >= 25:
                    break
        except discord.HTTPException:
            return []
        return escolhas

    @membro.command(name="silenciar",
                    description="Silencia um membro por um tempo.")
    @app_commands.describe(
        membro="Quem será silenciado.",
        duracao="Ex.: 30s, 10m, 2h, 1d12h (máx. 28 dias).",
        motivo="Motivo (vai para o registro de auditoria).")
    @permissoes(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def membro_silenciar(self, interaction: discord.Interaction,
                               membro: discord.Member, duracao: str,
                               motivo: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        try:
            tempo = parse_duracao(duracao)
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        problema = checar_alvo_membro(g, interaction.user, membro, g.me,
                                      "silenciar")
        if problema:
            await interaction.followup.send(f"❌ {problema}", ephemeral=True)
            return
        if membro.guild_permissions.administrator:
            await interaction.followup.send(
                "❌ O Discord não permite silenciar administradores.",
                ephemeral=True)
            return

        await membro.timeout(tempo,
                             reason=motivo_auditoria(interaction.user,
                                                     motivo))
        dm = await self._avisar_por_dm(
            membro, g, "Você foi silenciado", motivo,
            f"\n**Duração:** {formatar_duracao(tempo)}")

        log.info("TIMEOUT guild=%s alvo=%s por=%s duração=%s motivo=%s",
                 g.id, membro.id, interaction.user.id, tempo, motivo)
        await interaction.followup.send(embed=self._embed_acao(
            "🔇 Membro silenciado", discord.Color.orange(),
            [("Membro", f"{membro} (`{membro.id}`)"),
             ("Duração", formatar_duracao(tempo)),
             ("DM", self._txt_dm(dm))], motivo), ephemeral=True)

    @membro_silenciar.autocomplete("duracao")
    async def _ac_duracao(self, interaction: discord.Interaction,
                          current: str):
        sugestoes = ["1m", "5m", "10m", "30m", "1h", "6h", "12h", "1d",
                     "3d", "7d", "28d"]
        return [app_commands.Choice(name=s, value=s) for s in sugestoes
                if current.lower() in s]

    @membro.command(name="liberar",
                    description="Remove o silenciamento de um membro.")
    @app_commands.describe(membro="Quem será liberado.",
                           motivo="Motivo da liberação.")
    @permissoes(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def membro_liberar(self, interaction: discord.Interaction,
                             membro: discord.Member,
                             motivo: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)

        if not membro.is_timed_out():
            await interaction.followup.send(
                f"ℹ️ {membro.mention} não está silenciado.", ephemeral=True)
            return

        await membro.timeout(None, reason=motivo_auditoria(
            interaction.user, motivo))
        log.info("UNTIMEOUT guild=%s alvo=%s por=%s",
                 interaction.guild_id, membro.id, interaction.user.id)
        await interaction.followup.send(
            f"🔊 {membro.mention} foi liberado.", ephemeral=True)

    @membro.command(name="apelido",
                    description="Altera ou remove o apelido de um membro.")
    @app_commands.describe(
        membro="Quem terá o apelido alterado.",
        novo="Novo apelido (vazio remove o apelido).")
    @permissoes(manage_nicknames=True)
    @app_commands.checks.bot_has_permissions(manage_nicknames=True)
    async def membro_apelido(self, interaction: discord.Interaction,
                             membro: discord.Member,
                             novo: Optional[app_commands.Range[str, 1, 32]]
                             = None):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        # Mudar o próprio apelido é permitido; os outros seguem a hierarquia.
        if membro.id != interaction.user.id:
            problema = checar_alvo_membro(g, interaction.user, membro, g.me,
                                          "alterar o apelido de")
            if problema:
                await interaction.followup.send(f"❌ {problema}",
                                                ephemeral=True)
                return
        elif membro.id == g.owner_id:
            await interaction.followup.send(
                "❌ Não consigo alterar o apelido do dono do servidor.",
                ephemeral=True)
            return

        await membro.edit(nick=novo, reason=motivo_auditoria(
            interaction.user, "alteração de apelido"))
        await interaction.followup.send(
            f"✅ Apelido de {membro.mention}: "
            f"**{novo or 'removido'}**.", ephemeral=True)

    @membro.command(name="avisar",
                    description="Registra um aviso para um membro.")
    @app_commands.describe(membro="Quem receberá o aviso.",
                           motivo="Motivo do aviso.")
    @permissoes(moderate_members=True)
    async def membro_avisar(self, interaction: discord.Interaction,
                            membro: discord.Member, motivo: str):
        await interaction.response.defer(ephemeral=True)

        if membro.bot or membro.id == interaction.user.id:
            await interaction.followup.send(
                "❌ Escolha outro membro (não vale bot nem você).",
                ephemeral=True)
            return

        aviso_id, total = await asyncio.to_thread(
            self.avisos.adicionar, interaction.guild_id, membro.id,
            interaction.user.id, motivo[:500])
        dm = await self._avisar_por_dm(
            membro, interaction.guild, "Você recebeu um aviso", motivo,
            f"\n**Total de avisos:** {total}")

        log.info("WARN guild=%s alvo=%s por=%s id=%s total=%s",
                 interaction.guild_id, membro.id, interaction.user.id,
                 aviso_id, total)
        await interaction.followup.send(embed=self._embed_acao(
            "⚠️ Aviso registrado", discord.Color.gold(),
            [("Membro", f"{membro} (`{membro.id}`)"),
             ("Aviso", f"#{aviso_id}"), ("Total", str(total)),
             ("DM", self._txt_dm(dm))], motivo), ephemeral=True)

    @membro.command(name="avisos",
                    description="Lista os avisos de um membro.")
    @app_commands.describe(membro="Membro a consultar.")
    @permissoes(moderate_members=True)
    async def membro_avisos(self, interaction: discord.Interaction,
                            membro: discord.Member):
        await interaction.response.defer(ephemeral=True)
        registros = await asyncio.to_thread(
            self.avisos.listar, interaction.guild_id, membro.id)

        if not registros:
            await interaction.followup.send(
                f"✅ {membro.mention} não tem avisos.", ephemeral=True)
            return

        linhas = []
        for aviso_id, mod_id, motivo, criado in registros:
            quando = discord.utils.format_dt(
                datetime.fromisoformat(criado), "R")
            linhas.append(f"**#{aviso_id}** {quando} por <@{mod_id}>\n"
                          f"└ {motivo[:150]}")
        paginas = embeds_paginados(
            f"⚠️ Avisos de {membro.display_name} ({len(registros)})",
            linhas, discord.Color.gold(), por_pagina=6)
        extra = ({"view": PaginaView(interaction.user.id, paginas)}
                 if len(paginas) > 1 else {})
        await interaction.followup.send(embed=paginas[0], ephemeral=True,
                                        **extra)

    @membro.command(name="limpar_avisos",
                    description="Remove um aviso (ou todos) de um membro.")
    @app_commands.describe(
        membro="Membro a limpar.",
        aviso_id="Número do aviso (vazio remove todos).")
    @permissoes(moderate_members=True)
    async def membro_limpar_avisos(self, interaction: discord.Interaction,
                                   membro: discord.Member,
                                   aviso_id: Optional[int] = None):
        await interaction.response.defer(ephemeral=True)
        removidos = await asyncio.to_thread(
            self.avisos.remover, interaction.guild_id, membro.id, aviso_id)

        log.info("WARN-CLEAR guild=%s alvo=%s por=%s removidos=%s",
                 interaction.guild_id, membro.id, interaction.user.id,
                 removidos)
        await interaction.followup.send(
            f"🧹 {removidos} aviso(s) removido(s) de {membro.mention}."
            if removidos else "ℹ️ Nenhum aviso encontrado.",
            ephemeral=True)

    # ========================================================
    # CARGOS  (/cargo ...)
    # ========================================================

    @cargo.command(name="dar", description="Dá um cargo a um membro.")
    @app_commands.describe(membro="Quem receberá o cargo.",
                           cargo="Cargo a ser dado.",
                           motivo="Motivo (registro de auditoria).")
    @permissoes(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def cargo_dar(self, interaction: discord.Interaction,
                        membro: discord.Member, cargo: discord.Role,
                        motivo: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        problema = checar_cargo(g, interaction.user, cargo, g.me)
        if problema:
            await interaction.followup.send(f"❌ {problema}", ephemeral=True)
            return
        if cargo in membro.roles:
            await interaction.followup.send(
                f"ℹ️ {membro.mention} já tem {cargo.mention}.",
                ephemeral=True)
            return

        await membro.add_roles(cargo, reason=motivo_auditoria(
            interaction.user, motivo))
        log.info("ROLE-ADD guild=%s alvo=%s cargo=%s por=%s",
                 g.id, membro.id, cargo.id, interaction.user.id)
        await interaction.followup.send(
            f"✅ {cargo.mention} dado a {membro.mention}.", ephemeral=True)

    @cargo.command(name="remover", description="Remove um cargo de um membro.")
    @app_commands.describe(membro="Quem perderá o cargo.",
                           cargo="Cargo a ser removido.",
                           motivo="Motivo (registro de auditoria).")
    @permissoes(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def cargo_remover(self, interaction: discord.Interaction,
                            membro: discord.Member, cargo: discord.Role,
                            motivo: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        problema = checar_cargo(g, interaction.user, cargo, g.me)
        if problema:
            await interaction.followup.send(f"❌ {problema}", ephemeral=True)
            return
        if cargo not in membro.roles:
            await interaction.followup.send(
                f"ℹ️ {membro.mention} não tem {cargo.mention}.",
                ephemeral=True)
            return

        await membro.remove_roles(cargo, reason=motivo_auditoria(
            interaction.user, motivo))
        log.info("ROLE-REMOVE guild=%s alvo=%s cargo=%s por=%s",
                 g.id, membro.id, cargo.id, interaction.user.id)
        await interaction.followup.send(
            f"✅ {cargo.mention} removido de {membro.mention}.",
            ephemeral=True)

    @cargo.command(name="criar", description="Cria um cargo sem permissões.")
    @app_commands.describe(
        nome="Nome do cargo.", cor="Cor em hexadecimal, ex.: #8e44ad.",
        separado="Exibir os membros do cargo separados na lista.",
        mencionavel="Permitir que qualquer um mencione o cargo.")
    @permissoes(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def cargo_criar(
            self, interaction: discord.Interaction,
            nome: app_commands.Range[str, 1, 100],
            cor: Optional[str] = None, separado: bool = False,
            mencionavel: bool = False):
        await interaction.response.defer(ephemeral=True)

        try:
            colour = parse_cor(cor) if cor else discord.Colour.default()
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        # O cargo nasce SEM permissões: segurança por padrão.
        novo = await interaction.guild.create_role(
            name=nome, colour=colour, hoist=separado,
            mentionable=mencionavel,
            permissions=discord.Permissions.none(),
            reason=motivo_auditoria(interaction.user, "criação de cargo"))
        log.info("ROLE-CREATE guild=%s cargo=%s por=%s",
                 interaction.guild_id, novo.id, interaction.user.id)
        await interaction.followup.send(
            f"✅ Cargo {novo.mention} criado (sem permissões).",
            ephemeral=True)

    @cargo.command(name="editar", description="Edita nome, cor ou exibição.")
    @app_commands.describe(
        cargo="Cargo a editar.", nome="Novo nome.",
        cor="Nova cor em hexadecimal.",
        separado="Exibir os membros separados na lista.",
        mencionavel="Permitir que qualquer um mencione o cargo.")
    @permissoes(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def cargo_editar(
            self, interaction: discord.Interaction, cargo: discord.Role,
            nome: Optional[app_commands.Range[str, 1, 100]] = None,
            cor: Optional[str] = None, separado: Optional[bool] = None,
            mencionavel: Optional[bool] = None):
        await interaction.response.defer(ephemeral=True)
        g = interaction.guild

        problema = checar_cargo(g, interaction.user, cargo, g.me)
        if problema:
            await interaction.followup.send(f"❌ {problema}", ephemeral=True)
            return

        mudancas = {}
        if nome is not None:
            mudancas["name"] = nome
        if cor is not None:
            try:
                mudancas["colour"] = parse_cor(cor)
            except ValueError as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        if separado is not None:
            mudancas["hoist"] = separado
        if mencionavel is not None:
            mudancas["mentionable"] = mencionavel

        if not mudancas:
            await interaction.followup.send(
                "❌ Informe pelo menos uma alteração.", ephemeral=True)
            return

        await cargo.edit(reason=motivo_auditoria(
            interaction.user, "edição de cargo"), **mudancas)
        log.info("ROLE-EDIT guild=%s cargo=%s por=%s campos=%s",
                 g.id, cargo.id, interaction.user.id, list(mudancas))
        await interaction.followup.send(
            f"✅ Cargo {cargo.mention} atualizado.", ephemeral=True)

    @cargo.command(name="deletar", description="Exclui um cargo (pede confirmação).")
    @app_commands.describe(cargo="Cargo a excluir.")
    @permissoes(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def cargo_deletar(self, interaction: discord.Interaction,
                            cargo: discord.Role):
        g = interaction.guild
        problema = checar_cargo(g, interaction.user, cargo, g.me)
        if problema:
            await interaction.response.send_message(f"❌ {problema}",
                                                    ephemeral=True)
            return

        view = ConfirmarView(interaction.user.id)
        await interaction.response.send_message(
            f"⚠️ Excluir o cargo **{cargo.name}**? Isso remove o cargo de "
            "todos os membros e não pode ser desfeito.",
            view=view, ephemeral=True)
        await view.wait()

        if not view.confirmado:
            await interaction.edit_original_response(
                content="Exclusão cancelada.", view=None)
            return

        nome = cargo.name
        await cargo.delete(reason=motivo_auditoria(
            interaction.user, "exclusão de cargo"))
        log.info("ROLE-DELETE guild=%s cargo=%s (%s) por=%s",
                 g.id, cargo.id, nome, interaction.user.id)
        await interaction.edit_original_response(
            content=f"🗑️ Cargo **{nome}** excluído.", view=None)

    @cargo.command(name="lista", description="Lista os cargos do servidor.")
    @permissoes(manage_roles=True)
    async def cargo_lista(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cargos = [r for r in reversed(interaction.guild.roles)
                  if not r.is_default()]
        linhas = [f"`{r.position:>3}` {r.mention}"
                  f"{' 🤖' if r.managed else ''}" for r in cargos]
        paginas = embeds_paginados(
            f"🎭 Cargos ({len(cargos)})", linhas,
            discord.Color.blurple(), por_pagina=15)
        extra = ({"view": PaginaView(interaction.user.id, paginas)}
                 if len(paginas) > 1 else {})
        await interaction.followup.send(embed=paginas[0], ephemeral=True,
                                        **extra)

    @cargo.command(name="info", description="Detalhes de um cargo.")
    @app_commands.describe(cargo="Cargo a consultar.")
    @permissoes(manage_roles=True)
    async def cargo_info(self, interaction: discord.Interaction,
                         cargo: discord.Role):
        perigosas = [PERMISSOES_PT[n] for n in PERMISSOES_PT
                     if getattr(cargo.permissions, n, False)
                     and n not in ("send_messages", "embed_links",
                                   "read_message_history")]
        emb = discord.Embed(title=f"🎭 {cargo.name}", color=cargo.colour)
        emb.add_field(name="ID", value=str(cargo.id))
        emb.add_field(name="Posição", value=str(cargo.position))
        emb.add_field(name="Cor", value=str(cargo.colour))
        emb.add_field(name="Criado em",
                      value=discord.utils.format_dt(cargo.created_at, "D"))
        emb.add_field(name="Separado", value="Sim" if cargo.hoist else "Não")
        emb.add_field(name="Mencionável",
                      value="Sim" if cargo.mentionable else "Não")
        emb.add_field(name="Gerenciado por integração",
                      value="Sim" if cargo.managed else "Não")
        emb.add_field(
            name="Permissões de gestão",
            value=", ".join(perigosas) or "Nenhuma", inline=False)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    # ========================================================
    # CANAIS  (/limpar /slowmode /trancar /destrancar /anunciar)
    # ========================================================

    @app_commands.command(
        name="limpar", description="Apaga mensagens do canal atual.")
    @app_commands.guild_only()
    @app_commands.describe(
        quantidade=f"Quantas mensagens verificar (1 a {MAX_LIMPAR}).",
        membro="Apagar só as mensagens deste membro.",
        tipo="Filtrar por tipo de mensagem.")
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Todas", value="todas"),
        app_commands.Choice(name="Só de bots", value="bots"),
        app_commands.Choice(name="Só de humanos", value="humanos"),
        app_commands.Choice(name="Com anexos", value="anexos"),
        app_commands.Choice(name="Com links", value="links"),
    ])
    @permissoes(manage_messages=True)
    @app_commands.checks.bot_has_permissions(
        manage_messages=True, read_message_history=True)
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def limpar(
            self, interaction: discord.Interaction,
            quantidade: app_commands.Range[int, 1, MAX_LIMPAR],
            membro: Optional[discord.Member] = None,
            tipo: Optional[app_commands.Choice[str]] = None):
        canal = interaction.channel
        if not hasattr(canal, "purge"):
            await interaction.response.send_message(
                "❌ Não consigo limpar este tipo de canal.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        filtro = criar_filtro_limpeza(
            membro.id if membro else None, tipo.value if tipo else "todas")

        apagadas = await canal.purge(
            limit=quantidade, check=filtro, bulk=True,
            reason=motivo_auditoria(interaction.user, "limpeza de canal"))

        log.info("PURGE guild=%s canal=%s por=%s verificadas=%s apagadas=%s",
                 interaction.guild_id, canal.id, interaction.user.id,
                 quantidade, len(apagadas))
        await interaction.followup.send(
            f"🧹 {len(apagadas)} mensagem(ns) apagada(s). "
            "Mensagens fixadas são preservadas.", ephemeral=True)

    @app_commands.command(
        name="slowmode", description="Define o modo lento de um canal.")
    @app_commands.guild_only()
    @app_commands.describe(
        segundos="Intervalo entre mensagens (0 desativa; máx. 21600).",
        canal="Canal de texto (padrão: o atual).")
    @permissoes(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slowmode(
            self, interaction: discord.Interaction,
            segundos: app_commands.Range[int, 0, 21600],
            canal: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        alvo = canal or interaction.channel
        if not isinstance(alvo, discord.TextChannel):
            await interaction.followup.send(
                "❌ Escolha um canal de texto.", ephemeral=True)
            return

        await alvo.edit(slowmode_delay=segundos, reason=motivo_auditoria(
            interaction.user, "modo lento"))
        log.info("SLOWMODE guild=%s canal=%s por=%s segundos=%s",
                 interaction.guild_id, alvo.id, interaction.user.id,
                 segundos)
        await interaction.followup.send(
            f"🐌 Modo lento de {alvo.mention}: **{segundos}s**."
            if segundos else f"⚡ Modo lento desativado em {alvo.mention}.",
            ephemeral=True)

    async def _alternar_tranca(self, interaction: discord.Interaction,
                               canal: Optional[discord.TextChannel],
                               trancar: bool, motivo: Optional[str]):
        """Lógica comum de /trancar e /destrancar."""
        await interaction.response.defer(ephemeral=True)
        alvo = canal or interaction.channel
        if not isinstance(alvo, discord.TextChannel):
            await interaction.followup.send(
                "❌ Escolha um canal de texto.", ephemeral=True)
            return

        everyone = interaction.guild.default_role
        regra = alvo.overwrites_for(everyone)
        # False bloqueia; None volta ao padrão herdado da categoria/servidor.
        regra.send_messages = False if trancar else None
        await alvo.set_permissions(
            everyone, overwrite=regra,
            reason=motivo_auditoria(interaction.user, motivo))

        log.info("%s guild=%s canal=%s por=%s",
                 "LOCK" if trancar else "UNLOCK", interaction.guild_id,
                 alvo.id, interaction.user.id)
        await interaction.followup.send(
            f"🔒 {alvo.mention} trancado." if trancar
            else f"🔓 {alvo.mention} destrancado.", ephemeral=True)
        if trancar:
            try:
                await alvo.send(embed=discord.Embed(
                    description=f"🔒 Canal trancado por "
                                f"{interaction.user.mention}."
                                + (f"\n**Motivo:** {motivo}" if motivo
                                   else ""),
                    color=discord.Color.dark_red()))
            except discord.HTTPException:
                pass

    @app_commands.command(
        name="trancar", description="Impede @everyone de falar no canal.")
    @app_commands.guild_only()
    @app_commands.describe(canal="Canal de texto (padrão: o atual).",
                           motivo="Motivo do bloqueio.")
    @permissoes(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def trancar(self, interaction: discord.Interaction,
                      canal: Optional[discord.TextChannel] = None,
                      motivo: Optional[str] = None):
        await self._alternar_tranca(interaction, canal, True, motivo)

    @app_commands.command(
        name="destrancar", description="Permite @everyone falar no canal.")
    @app_commands.guild_only()
    @app_commands.describe(canal="Canal de texto (padrão: o atual).")
    @permissoes(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def destrancar(self, interaction: discord.Interaction,
                         canal: Optional[discord.TextChannel] = None):
        await self._alternar_tranca(interaction, canal, False, None)

    @app_commands.command(
        name="anunciar", description="Envia um anúncio em um canal.")
    @app_commands.guild_only()
    @app_commands.describe(
        canal="Onde publicar o anúncio.", titulo="Título do anúncio.",
        mensagem="Texto (use \\n para quebrar linha).",
        cor="Cor em hexadecimal (opcional).",
        mencionar="Cargo a mencionar (opcional).")
    @permissoes(manage_guild=True)
    async def anunciar(
            self, interaction: discord.Interaction,
            canal: discord.TextChannel,
            titulo: app_commands.Range[str, 1, 256], mensagem: str,
            cor: Optional[str] = None,
            mencionar: Optional[discord.Role] = None):
        await interaction.response.defer(ephemeral=True)

        try:
            colour = parse_cor(cor) if cor else discord.Color.dark_purple()
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        meu = canal.permissions_for(interaction.guild.me)
        if not (meu.send_messages and meu.embed_links):
            await interaction.followup.send(
                "❌ Eu preciso de Enviar Mensagens e Inserir Links nesse "
                "canal.", ephemeral=True)
            return

        texto = mensagem.replace("\\n", "\n")[:4000]
        emb = discord.Embed(title=titulo, description=texto, color=colour)
        emb.set_footer(text=f"Anúncio de {interaction.user.display_name}")

        # Só o cargo escolhido pode ser mencionado (nunca @everyone).
        await canal.send(
            content=mencionar.mention if mencionar else None, embed=emb,
            allowed_mentions=discord.AllowedMentions(
                everyone=False, users=False,
                roles=[mencionar] if mencionar else False))
        log.info("ANNOUNCE guild=%s canal=%s por=%s",
                 interaction.guild_id, canal.id, interaction.user.id)
        await interaction.followup.send(
            f"📣 Anúncio enviado em {canal.mention}.", ephemeral=True)

    # ========================================================
    # DESENVOLVEDOR  (/dev ...)  — somente o dono do bot
    # ========================================================

    @dev.command(name="recarregar",
                 description="Recarrega um módulo (cog) sem reiniciar.")
    @app_commands.describe(
        modulo="Módulo a recarregar, ou 'todos'.")
    @somente_dono
    async def dev_recarregar(self, interaction: discord.Interaction,
                             modulo: str):
        await interaction.response.defer(ephemeral=True)

        alvos = (list(self.bot.extensions) if modulo == "todos"
                 else [modulo])
        sucesso, falhas = [], []
        for nome in alvos:
            try:
                await self.bot.reload_extension(nome)
                sucesso.append(nome)
            except Exception as exc:
                log.exception("Falha ao recarregar %s", nome)
                falhas.append(f"{nome}: {type(exc).__name__}: {exc}")

        # Recarregar altera os comandos: sincroniza este servidor.
        sincronizados = 0
        try:
            self.bot.tree.copy_global_to(guild=interaction.guild)
            sincronizados = len(
                await self.bot.tree.sync(guild=interaction.guild))
        except discord.HTTPException:
            log.exception("Falha ao sincronizar após recarregar.")

        texto = f"🔄 Recarregados: {', '.join(sucesso) or 'nenhum'}."
        if falhas:
            texto += "\n❌ Falhas:\n" + "\n".join(falhas)
        texto += f"\n📡 {sincronizados} comando(s) sincronizado(s)."
        log.info("RELOAD por=%s módulos=%s falhas=%s",
                 interaction.user.id, sucesso, len(falhas))
        await interaction.followup.send(texto[:1900], ephemeral=True)

    @dev_recarregar.autocomplete("modulo")
    async def _ac_modulo(self, interaction: discord.Interaction,
                         current: str):
        nomes = ["todos"] + sorted(self.bot.extensions)
        return [app_commands.Choice(name=n, value=n) for n in nomes
                if current.lower() in n.lower()][:25]

    @dev.command(name="sincronizar",
                 description="Sincroniza os comandos slash neste servidor.")
    @somente_dono
    async def dev_sincronizar(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.bot.tree.copy_global_to(guild=interaction.guild)
        sincronizados = await self.bot.tree.sync(guild=interaction.guild)
        log.info("SYNC por=%s guild=%s comandos=%s", interaction.user.id,
                 interaction.guild_id, len(sincronizados))
        await interaction.followup.send(
            f"📡 {len(sincronizados)} comando(s) sincronizado(s).",
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))