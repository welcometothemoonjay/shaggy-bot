"""
MISSÕES DIÁRIAS — 3 missões por dia, XP por missão e bônus final
=================================================================

Cog do Shaggy Bot. Requer o cog XpAndCoins carregado (carregue-o antes).

REGRAS
------
- Todo dia (virada à meia-noite de Brasília) o bot sorteia 3 missões de
  TIPOS DIFERENTES. Por padrão são as mesmas 3 para todo o servidor
  (MISSOES_POR_USUARIO = False); com True, cada membro recebe as suas.
- Cada missão concluída paga XP na hora (o valor depende da dificuldade).
- Concluiu as 3 no mesmo dia? Bônus ÚNICO do dia:
    * 1 🌀 Portal de Distorção Temporal
    * 1 x 1d100 Abysmus (ABYSMUS_MULTIPLICADOR x dado de ABYSMUS_FACES)
- O progresso é contado sozinho, ouvindo eventos do bot (mensagens,
  reações e comandos). Não é preciso alterar o main.py.

COMANDO
-------
    /missoes   — mostra as missões de hoje, o progresso e seus portais.

API PARA OUTROS COGS (ex.: Ruptura Temporal)
--------------------------------------------
    missoes = bot.get_cog("Missoes")
    missoes.obter_portais(guild_id, user_id)        # -> int
    missoes.consumir_portal(guild_id, user_id)      # -> saldo; ValueError se 0
    # Dentro de uma transação aberta com xp_cog.transacao():
    missoes.consumir_portal_tx(db, guild_id, user_id)

Lembre: dentro de uma transação, não chame funções que abrem outra
transação (veja o guia do XpAndCoins).
"""

import asyncio
import logging
import random
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


log = logging.getLogger("shaggy.missoes")


# ============================================================
# CONFIGURAÇÕES (ajuste o equilíbrio aqui)
# ============================================================

# Fuso para "virar o dia" (UTC-3, Brasília), igual ao XpAndCoins.
FUSO_HORARIO = timezone(timedelta(hours=-3), "BRT")

# True: cada membro recebe 3 missões próprias. False: todos iguais.
MISSOES_POR_USUARIO = False

QUANTIDADE_MISSOES = 3

# Bônus por completar as 3 missões: 1 portal + (multiplicador x 1dN) Abysmus.
PORTAIS_POR_DIA = 1
ABYSMUS_MULTIPLICADOR = 1
ABYSMUS_FACES = 100

# Anti-spam: intervalo mínimo entre duas ações que contam para missões.
GAP_MENSAGEM_SEGUNDOS = 8
GAP_COMANDO_SEGUNDOS = 3
GAP_REACAO_SEGUNDOS = 3

# Mensagens com menos caracteres que isso não contam como "mensagem".
MENSAGEM_MIN_CARACTERES = 3

# Se True, avisa no canal quando uma missão é concluída.
ANUNCIAR_CONCLUSAO = True

# Comandos que contam como "minijogo".
COMANDOS_JOGOS = {
    "roleta_russa", "moeda", "dado", "pedra_papel_tesoura",
    "par_ou_impar", "duelo_numerico", "duelo_elemental",
    "adivinhar_escolha", "sorte_ou_caos",
}
COMANDOS_CONSULTA = {"xp", "level", "coins"}

# tipo -> (texto com {n}, [(meta, xp), ...] do mais fácil ao mais difícil).
# O sorteio escolhe 3 TIPOS diferentes e um nível de dificuldade de cada.
MODELOS_MISSAO = {
    "jogar": (
        "Jogue {n} minijogos do Shaggy",
        [(3, 30), (5, 45), (8, 60)],
    ),
    "reagir": (
        "Reaja a {n} mensagens",
        [(3, 20), (5, 30), (8, 45)],
    ),
    "consultar": (
        "Consulte seu /xp, /level ou /coins {n} vez(es)",
        [(1, 15), (2, 25)],
    ),
    "ranking": (
        "Espie o /ranking",
        [(1, 20)],
    ),
    "ideia_rpg": (
        "Gere uma aventura com /ideia_rpg",
        [(1, 30)],
    ),
}


# ============================================================
# MODELOS DE DADOS
# ============================================================

@dataclass(frozen=True)
class Missao:
    tipo: str
    texto: str
    meta: int
    xp: int


@dataclass
class ResultadoProgresso:
    """O que aconteceu ao registrar progresso (devolvido ao handler)."""
    ja_concluida: bool = False
    concluida: bool = False
    missao: Optional[Missao] = None
    total_concluidas: int = 0
    portais: int = 0
    abysmus_bonus: int = 0
    nivel_novo: Optional[int] = None
    coins_por_nivel: int = 0


def sortear_missoes(semente: str) -> list[Missao]:
    """
    Sorteia as missões do dia de forma determinística pela semente
    (mesma semente = mesmas missões, mesmo se o bot reiniciar).
    """
    rng = random.Random(semente)
    tipos = rng.sample(list(MODELOS_MISSAO), QUANTIDADE_MISSOES)

    missoes = []
    for tipo in tipos:
        texto, niveis = MODELOS_MISSAO[tipo]
        meta, xp = rng.choice(niveis)
        missoes.append(
            Missao(tipo=tipo, texto=texto.format(n=meta), meta=meta, xp=xp)
        )
    return missoes


def barra_progresso(atual: int, meta: int, tamanho: int = 10) -> str:
    preenchidos = min(tamanho, int((atual / meta) * tamanho)) if meta else 0
    return "█" * preenchidos + "░" * (tamanho - preenchidos)


# ============================================================
# COG
# ============================================================

class Missoes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tabelas_ok = False

        # Anti-spam em memória: (guild, user, categoria) -> instante.
        self._ultima_acao: dict[tuple, float] = {}

        # Cache das missões do dia e das já concluídas (evita ir ao banco).
        self._dia_cache: str = ""
        self._cache_missoes: dict[tuple, list[Missao]] = {}
        self._cache_concluidas: set[tuple] = set()

    # ---------- Infra ----------

    def _hoje(self) -> date:
        """Data atual no fuso configurado (isolado para facilitar testes)."""
        return datetime.now(FUSO_HORARIO).date()

    def _preparar(self):
        """Devolve o cog XpAndCoins e garante as tabelas deste cog."""
        xp_cog = self.bot.get_cog("XpAndCoins")
        if xp_cog is None:
            raise RuntimeError("Cog XpAndCoins não está carregado.")

        if not self._tabelas_ok:
            with xp_cog.transacao() as db:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS missoes_progresso (
                        guild_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        dia TEXT NOT NULL,
                        tipo TEXT NOT NULL,
                        progresso INTEGER NOT NULL DEFAULT 0,
                        concluida INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id, dia, tipo)
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS missoes_bonus (
                        guild_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        dia TEXT NOT NULL,
                        abysmus INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id, dia)
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS portais (
                        guild_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        quantidade INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (guild_id, user_id)
                    )
                """)
            self._tabelas_ok = True

        return xp_cog

    def missoes_do_dia(
        self, guild_id: int, user_id: int, hoje: Optional[date] = None
    ) -> list[Missao]:
        """As missões de hoje (compartilhadas ou por usuário)."""
        hoje = hoje or self._hoje()
        dia = hoje.isoformat()

        if dia != self._dia_cache:
            self._dia_cache = dia
            self._cache_missoes.clear()
            self._cache_concluidas.clear()
            self._ultima_acao.clear()

        chave = (guild_id, user_id if MISSOES_POR_USUARIO else 0)
        if chave not in self._cache_missoes:
            semente = f"{dia}:{guild_id}"
            if MISSOES_POR_USUARIO:
                semente += f":{user_id}"
            self._cache_missoes[chave] = sortear_missoes(semente)

        return self._cache_missoes[chave]

    # ---------- Portais (API para outros cogs) ----------

    def obter_portais(self, guild_id: int, user_id: int) -> int:
        xp_cog = self._preparar()
        with closing(xp_cog.conectar()) as db:
            linha = db.execute("""
                SELECT quantidade FROM portais
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id)).fetchone()
        return linha[0] if linha else 0

    def consumir_portal_tx(self, db, guild_id: int, user_id: int) -> int:
        """
        Gasta 1 portal DENTRO de uma transação já aberta
        (xp_cog.transacao()). Levanta ValueError se não houver portal.
        Retorna a quantidade restante.
        """
        linha = db.execute("""
            SELECT quantidade FROM portais
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()

        if not linha or linha[0] <= 0:
            raise ValueError("Sem Portal de Distorção Temporal.")

        db.execute("""
            UPDATE portais SET quantidade = quantidade - 1
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id))
        return linha[0] - 1

    def consumir_portal(self, guild_id: int, user_id: int) -> int:
        xp_cog = self._preparar()
        with xp_cog.transacao() as db:
            return self.consumir_portal_tx(db, guild_id, user_id)

    # ---------- Núcleo: registrar progresso ----------

    def registrar_progresso(
        self,
        guild_id: int,
        user_id: int,
        tipo: str,
        quantidade: int = 1,
    ) -> Optional[ResultadoProgresso]:
        """
        Soma progresso à missão do tipo informado (se ela existir hoje).

        Tudo acontece em UMA transação: progresso, XP, Abysmus, portal e
        marca de bônus. Se algo falhar, nada é gravado.
        """
        hoje = self._hoje()
        dia = hoje.isoformat()
        missoes = self.missoes_do_dia(guild_id, user_id, hoje)
        missao = next((m for m in missoes if m.tipo == tipo), None)
        if missao is None:
            return None

        xp_cog = self._preparar()
        resultado = ResultadoProgresso(missao=missao)

        with xp_cog.transacao() as db:
            db.execute("""
                INSERT OR IGNORE INTO missoes_progresso
                    (guild_id, user_id, dia, tipo)
                VALUES (?, ?, ?, ?)
            """, (guild_id, user_id, dia, tipo))

            progresso, concluida = db.execute("""
                SELECT progresso, concluida FROM missoes_progresso
                WHERE guild_id = ? AND user_id = ? AND dia = ? AND tipo = ?
            """, (guild_id, user_id, dia, tipo)).fetchone()

            if concluida:
                resultado.ja_concluida = True
                return resultado

            novo = min(missao.meta, progresso + quantidade)
            concluiu = novo >= missao.meta

            db.execute("""
                UPDATE missoes_progresso
                SET progresso = ?, concluida = ?
                WHERE guild_id = ? AND user_id = ? AND dia = ? AND tipo = ?
            """, (novo, int(concluiu), guild_id, user_id, dia, tipo))

            if not concluiu:
                return resultado

            resultado.concluida = True
            xp_ganho = missao.xp
            abysmus = 0

            total = db.execute("""
                SELECT COUNT(*) FROM missoes_progresso
                WHERE guild_id = ? AND user_id = ? AND dia = ?
                  AND concluida = 1
            """, (guild_id, user_id, dia)).fetchone()[0]
            resultado.total_concluidas = total

            # Bônus final: uma única vez por dia (a chave primária garante).
            if total >= len(missoes):
                abysmus = ABYSMUS_MULTIPLICADOR * random.randint(
                    1, ABYSMUS_FACES
                )
                novo_bonus = db.execute("""
                    INSERT OR IGNORE INTO missoes_bonus
                        (guild_id, user_id, dia, abysmus)
                    VALUES (?, ?, ?, ?)
                """, (guild_id, user_id, dia, abysmus)).rowcount

                if novo_bonus:
                    db.execute("""
                        INSERT OR IGNORE INTO portais
                            (guild_id, user_id, quantidade)
                        VALUES (?, ?, 0)
                    """, (guild_id, user_id))
                    db.execute("""
                        UPDATE portais SET quantidade = quantidade + ?
                        WHERE guild_id = ? AND user_id = ?
                    """, (PORTAIS_POR_DIA, guild_id, user_id))
                    resultado.portais = PORTAIS_POR_DIA
                    resultado.abysmus_bonus = abysmus
                else:
                    abysmus = 0

            # Único ponto que altera XP/nível/Abysmus (do XpAndCoins),
            # usado dentro desta mesma transação para ser atômico.
            r = xp_cog._gravar(
                db, guild_id, user_id,
                lambda atual: atual + xp_ganho,
                coins_extra=abysmus,
            )
            resultado.coins_por_nivel = r.coins_por_nivel
            if r.nivel > r.nivel_antes:
                resultado.nivel_novo = r.nivel

        log.info(
            "Missão concluída guild=%s user=%s tipo=%s +%s XP | "
            "total=%s/%s | portais=%s abysmus_bonus=%s",
            guild_id, user_id, tipo, missao.xp, resultado.total_concluidas,
            len(missoes), resultado.portais, resultado.abysmus_bonus,
        )
        return resultado

    def obter_status(self, guild_id: int, user_id: int):
        """Retorna (lista de (missao, progresso, concluida), bônus pago, portais)."""
        xp_cog = self._preparar()
        hoje = self._hoje()
        dia = hoje.isoformat()
        missoes = self.missoes_do_dia(guild_id, user_id, hoje)

        with closing(xp_cog.conectar()) as db:
            linhas = {
                tipo: (progresso, bool(concluida))
                for tipo, progresso, concluida in db.execute("""
                    SELECT tipo, progresso, concluida FROM missoes_progresso
                    WHERE guild_id = ? AND user_id = ? AND dia = ?
                """, (guild_id, user_id, dia))
            }
            bonus = db.execute("""
                SELECT abysmus FROM missoes_bonus
                WHERE guild_id = ? AND user_id = ? AND dia = ?
            """, (guild_id, user_id, dia)).fetchone()
            portais = db.execute("""
                SELECT quantidade FROM portais
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id)).fetchone()

        status = [(m, *linhas.get(m.tipo, (0, False))) for m in missoes]
        return status, (bonus[0] if bonus else None), (portais[0] if portais else 0)

    # ---------- Eventos que alimentam as missões ----------

    def _permitido(self, chave: tuple, gap: float) -> bool:
        """Anti-spam: True se já passou o intervalo mínimo."""
        agora = time.monotonic()
        if agora - self._ultima_acao.get(chave, -1e9) < gap:
            return False
        self._ultima_acao[chave] = agora
        return True

    async def _contar(
        self,
        guild_id: int,
        user,
        canal,
        tipo: str,
        quantidade: int = 1,
    ):
        missoes = self.missoes_do_dia(guild_id, user.id)
        if not any(m.tipo == tipo for m in missoes):
            return

        chave_cache = (self._dia_cache, guild_id, user.id, tipo)
        if chave_cache in self._cache_concluidas:
            return

        try:
            resultado = await asyncio.to_thread(
                self.registrar_progresso, guild_id, user.id, tipo, quantidade
            )
        except Exception:
            log.exception("Falha ao registrar progresso de missão (%s).", tipo)
            return

        if resultado is None:
            return

        if resultado.ja_concluida or resultado.concluida:
            self._cache_concluidas.add(chave_cache)

        if resultado.concluida:
            await self._anunciar(canal, user, resultado)

    async def _anunciar(self, canal, user, r: ResultadoProgresso):
        if not ANUNCIAR_CONCLUSAO or canal is None:
            return

        total_missoes = QUANTIDADE_MISSOES
        texto = (
            f"📜 {user.mention} concluiu a missão **{r.missao.texto}** "
            f"(✨ +{r.missao.xp} XP) • {r.total_concluidas}/{total_missoes}"
        )

        if r.portais:
            texto += (
                f"\n🎉 Todas as missões de hoje foram concluídas! "
                f"🌀 **+{r.portais} Portal de Distorção Temporal** • "
                f"🎲 1d{ABYSMUS_FACES}: **+{r.abysmus_bonus} 🪙 Abysmus**"
            )

        if r.nivel_novo:
            texto += f"\n🏆 {user.mention} chegou ao **nível {r.nivel_novo}**!"
            if r.coins_por_nivel:
                texto += f" 🪙 +{r.coins_por_nivel} Abysmus"

        try:
            await canal.send(texto)
        except discord.HTTPException:
            log.warning("Não foi possível avisar a missão no canal.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return

        chave = (message.guild.id, message.author.id, "msg")
        if not self._permitido(chave, GAP_MENSAGEM_SEGUNDOS):
            return

        gid, autor, canal = message.guild.id, message.author, message.channel

        if len(message.content.strip()) >= MENSAGEM_MIN_CARACTERES:
            await self._contar(gid, autor, canal, "mensagens")

        if message.attachments:
            await self._contar(gid, autor, canal, "anexo")

        # Responder a OUTRO membro (não bot, não a si mesmo).
        ref = message.reference
        if ref is not None:
            alvo = ref.resolved or ref.cached_message
            if (
                isinstance(alvo, discord.Message)
                and not alvo.author.bot
                and alvo.author.id != autor.id
            ):
                await self._contar(gid, autor, canal, "responder")

        # Mencionar OUTRO membro.
        if any(
            not m.bot and m.id != autor.id for m in message.mentions
        ):
            await self._contar(gid, autor, canal, "mencionar")

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ):
        if payload.guild_id is None:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        if payload.member is not None and payload.member.bot:
            return

        chave = (payload.guild_id, payload.user_id, "reacao")
        if not self._permitido(chave, GAP_REACAO_SEGUNDOS):
            return

        usuario = payload.member or _UsuarioSimples(payload.user_id)

        canal = self.bot.get_channel(payload.channel_id)
        await self._contar(
            payload.guild_id, usuario, canal, "reagir"
        )

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command,
    ):
        if interaction.guild_id is None:
            return

        nome = command.qualified_name
        if nome in COMANDOS_JOGOS:
            tipo = "jogar"
        elif nome in COMANDOS_CONSULTA:
            tipo = "consultar"
        elif nome == "ranking":
            tipo = "ranking"
        elif nome == "ideia_rpg":
            tipo = "ideia_rpg"
        else:
            return

        chave = (interaction.guild_id, interaction.user.id, "cmd")
        if not self._permitido(chave, GAP_COMANDO_SEGUNDOS):
            return

        await self._contar(
            interaction.guild_id, interaction.user,
            interaction.channel, tipo,
        )

    # ---------- Comando ----------

    @app_commands.command(
        name="missoes",
        description="Veja suas missões diárias e seus Portais de Distorção.",
    )
    @app_commands.guild_only()
    async def missoes(self, interaction: discord.Interaction):
        # Reconhece a interação antes de consultar SQLite (evita 10062).
        await interaction.response.defer(thinking=True)

        try:
            status, bonus, portais = await asyncio.to_thread(
                self.obter_status, interaction.guild_id, interaction.user.id
            )
        except Exception:
            log.exception("Falha ao carregar as missões.")
            await interaction.followup.send(
                "❌ Não consegui carregar as missões agora. "
                "Tente novamente.",
                ephemeral=True,
            )
            return

        concluidas = sum(1 for _, _, ok in status if ok)

        embed = discord.Embed(
            title="📜 Missões do dia",
            description=(
                f"**{concluidas}/{len(status)}** concluídas • "
                f"reinicia em **{self._tempo_ate_virada()}**"
            ),
            color=discord.Color.gold(),
        )
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url,
        )

        for indice, (m, progresso, ok) in enumerate(status, start=1):
            icone = "✅" if ok else "🔸"
            embed.add_field(
                name=f"{icone} {indice}. {m.texto}",
                value=(
                    f"`{barra_progresso(progresso, m.meta)}` "
                    f"{progresso}/{m.meta} • ✨ {m.xp} XP"
                ),
                inline=False,
            )

        if bonus is not None:
            recompensa = (
                f"✅ Coletada: 🌀 +{PORTAIS_POR_DIA} portal e "
                f"🪙 +{bonus} Abysmus"
            )
        else:
            recompensa = (
                f"Conclua as {len(status)} missões para ganhar "
                f"🌀 {PORTAIS_POR_DIA} Portal de Distorção Temporal e "
                f"🪙 {ABYSMUS_MULTIPLICADOR} x 1d{ABYSMUS_FACES} Abysmus."
            )
        embed.add_field(name="🎁 Recompensa final", value=recompensa, inline=False)
        embed.set_footer(text=f"🌀 Seus portais: {portais}")

        await interaction.followup.send(embed=embed)

    def _tempo_ate_virada(self) -> str:
        agora = datetime.now(FUSO_HORARIO)
        proxima = datetime.combine(
            agora.date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=FUSO_HORARIO,
        )
        segundos = int((proxima - agora).total_seconds())
        horas, resto = divmod(segundos, 3600)
        minutos = resto // 60
        return f"{horas}h {minutos:02d}min"


class _UsuarioSimples:
    """Substituto mínimo de um membro quando só temos o ID (reações)."""

    def __init__(self, user_id: int):
        self.id = user_id
        self.mention = f"<@{user_id}>"


async def setup(bot: commands.Bot):
    await bot.add_cog(Missoes(bot))
