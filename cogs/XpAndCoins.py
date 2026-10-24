"""
XPANDCOINS — XP por mensagem, níveis e Abysmus (moeda rara)
===========================================================

Cog do Shaggy Bot.

REGRAS
------
- XP por mensagem continua limitado a 1 recompensa por minuto por membro.
- Cada recompensa é a soma de várias fontes (veja calcular_xp_mensagem):
    * XP base aleatório (1 a 15)
    * bônus por mensagem elaborada (+1 a cada 50 caracteres, máx. +4)
    * bônus por anexo (+2)
    * bônus por interação social: responder ou mencionar outro membro (+2)
    * "Inspiração": 7% de chance de dobrar o XP da mensagem
    * bônus diário: a primeira recompensa do dia rende XP extra, que cresce
      com a sequência de dias seguidos (streak)
- Abysmus é RARO: 1 por nível alcançado pela primeira vez. Nenhuma
  mensagem dá Abysmus direto. Outros cogs (ex.: o jogo Ruptura Temporal)
  podem conceder Abysmus de forma rara via conceder_recompensas().
- O nível nunca "devolve" Abysmus: se o XP for removido e depois
  readicionado, níveis já recompensados não pagam de novo.

API PARA OUTROS COGS (ex.: Ruptura Temporal)
--------------------------------------------
    cog = bot.get_cog("XpAndCoins")
    resultado = cog.conceder_recompensas(
        guild_id, user_id, xp=50, coins=1, origem="ruptura_temporal",
    )

IMPORTANTE: o servidor (guild_id) é obrigatório, porque o saldo e o XP
são por servidor. O jogo precisa enviar o guild_id da interação.

COMANDOS DE ADMINISTRADOR (aparecem ao digitar "/" para quem é admin)
--------------------------------------------------------------------
    /xp_gerenciar    membro, ação (Adicionar/Remover/Definir total), quantidade
    /coin_gerenciar  membro, ação (Adicionar/Remover/Definir saldo), quantidade

Proteções: só administradores; resposta imediata (sem "não respondeu");
cada alteração é UMA transação atômica; trava por membro (sem execuções
simultâneas), cooldown por admin e tempo-limite — o comando sempre termina
com uma resposta, nunca fica "pensando" para sempre.

Chamado pelo main.py:
    await bot.get_cog("XpAndCoins").processar_mensagem(message)
"""

import logging
import asyncio
import random
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import discord
from discord import app_commands
from discord.ext import commands


# Logger do sistema; aparece no terminal do Shaggy Bot.
log = logging.getLogger("shaggy.xp")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "shaggy.db"


# ============================================================
# CONFIGURAÇÕES (ajuste o equilíbrio aqui)
# ============================================================

# Intervalo mínimo entre duas recompensas de XP por mensagem.
COOLDOWN_XP_SEGUNDOS = 60

# XP base sorteado a cada mensagem que rende XP.
XP_BASE_MIN = 1
XP_BASE_MAX = 15

# Bônus por mensagem elaborada: +1 a cada N caracteres, até o máximo.
XP_TEXTO_CARACTERES_POR_PONTO = 50
XP_TEXTO_MAX = 4

# Bônus por anexo (imagem, arquivo...) e por interação social
# (responder ou mencionar outro membro).
XP_BONUS_ANEXO = 2
XP_BONUS_SOCIAL = 2

# "Inspiração": chance de multiplicar o XP da mensagem.
CHANCE_INSPIRACAO = 0.07
MULTIPLICADOR_INSPIRACAO = 2

# Teto de XP vindo de UMA mensagem (o bônus diário é somado à parte).
XP_MAX_POR_MENSAGEM = 50

# Bônus diário: base + incremento por dia seguido (streak), com limite.
# Com os valores abaixo o bônus vai de 20 XP (dia 1) até 50 XP (dia 7+).
DIARIO_BASE = 20
DIARIO_POR_DIA = 5
DIARIO_DIAS_MAX_STREAK = 6

# Fuso usado para "virar o dia" do bônus diário (UTC-3, Brasília).
FUSO_HORARIO = timezone(timedelta(hours=-3), "BRT")

# Abysmus concedido por nível alcançado pela primeira vez.
ABYSMUS_POR_NIVEL = 1

# Se True, o bot avisa no canal quando alguém sobe de nível.
ANUNCIAR_LEVEL_UP = True

# --- Comandos de administrador (/xp_gerenciar e /coin_gerenciar) ---
# Tempo máximo esperando o banco; passou disso, o comando avisa e termina.
GERENCIAR_TIMEOUT_SEGUNDOS = 8
# Intervalo mínimo entre dois usos por administrador (anti duplo clique).
GERENCIAR_COOLDOWN_SEGUNDOS = 3
# Limite por operação (também aplicado nos campos do slash).
GERENCIAR_MAX_QUANTIDADE = 1_000_000


# ============================================================
# PROGRESSÃO DE NÍVEL
# ============================================================

def xp_para_proximo_nivel(nivel: int) -> int:
    """Progressão: nível 0 -> 1 custa 100 XP; depois, 110 * nível atual."""
    if nivel <= 0:
        return 100
    return 110 * nivel


def calcular_nivel(xp_total: int):
    """Retorna nível, XP dentro do nível e XP necessário."""
    xp_restante = max(0, xp_total)
    nivel = 0

    while True:
        custo = xp_para_proximo_nivel(nivel)

        if xp_restante < custo:
            return nivel, xp_restante, custo

        xp_restante -= custo
        nivel += 1


# ============================================================
# CÁLCULO DO XP DE UMA MENSAGEM
# ============================================================

@dataclass
class GanhoMensagem:
    """Detalhamento do XP ganho em uma mensagem (sem o bônus diário)."""
    base: int
    texto: int
    anexo: int
    social: int
    inspirado: bool
    total: int


def _interacao_social(message: discord.Message) -> bool:
    """
    True se a mensagem responde ou menciona OUTRO membro (não bot).
    Responder a si mesmo ou mencionar a si mesmo não conta.
    """
    referencia = message.reference
    if referencia is not None and isinstance(
        referencia.resolved, discord.Message
    ):
        alvo = referencia.resolved.author
        if not alvo.bot and alvo.id != message.author.id:
            return True

    for mencionado in message.mentions:
        if not mencionado.bot and mencionado.id != message.author.id:
            return True

    return False


def calcular_xp_mensagem(message: discord.Message) -> GanhoMensagem:
    """Soma todas as fontes de XP de uma mensagem."""
    base = random.randint(XP_BASE_MIN, XP_BASE_MAX)

    # Mensagens mais elaboradas rendem um pouco mais (com teto).
    tamanho = len(message.content.strip())
    texto = min(XP_TEXTO_MAX, tamanho // XP_TEXTO_CARACTERES_POR_PONTO)

    anexo = XP_BONUS_ANEXO if message.attachments else 0
    social = XP_BONUS_SOCIAL if _interacao_social(message) else 0

    subtotal = base + texto + anexo + social

    # Inspiração: pequena chance de dobrar o XP da mensagem.
    inspirado = random.random() < CHANCE_INSPIRACAO
    if inspirado:
        subtotal *= MULTIPLICADOR_INSPIRACAO

    return GanhoMensagem(
        base=base,
        texto=texto,
        anexo=anexo,
        social=social,
        inspirado=inspirado,
        total=min(XP_MAX_POR_MENSAGEM, subtotal),
    )


# ============================================================
# BÔNUS DIÁRIO E SEQUÊNCIA (STREAK)
# ============================================================

def calcular_diario(
    ultimo_dia: str,
    streak: int,
    hoje: date,
) -> tuple[int, int, bool]:
    """
    Calcula o bônus diário.

    Retorna (bônus_de_xp, nova_streak, disponível).
    - disponível=False: o bônus de hoje já foi coletado (bônus = 0).
    - A streak continua se o último dia coletado foi ontem; senão volta a 1.
    """
    if ultimo_dia == hoje.isoformat():
        return 0, streak, False

    try:
        ultimo = date.fromisoformat(ultimo_dia)
    except ValueError:
        ultimo = None  # nunca coletou (campo vazio)

    if ultimo == hoje - timedelta(days=1):
        nova_streak = streak + 1
    else:
        nova_streak = 1

    bonus = DIARIO_BASE + DIARIO_POR_DIA * min(
        nova_streak - 1, DIARIO_DIAS_MAX_STREAK
    )
    return bonus, nova_streak, True


def streak_ativa(ultimo_dia: str, streak: int, hoje: date) -> int:
    """Streak exibida: zera se o membro já passou de um dia sem coletar."""
    if ultimo_dia in (
        hoje.isoformat(),
        (hoje - timedelta(days=1)).isoformat(),
    ):
        return streak
    return 0


# ============================================================
# RESULTADO DE UMA GRAVAÇÃO DE XP
# ============================================================

@dataclass
class ResultadoXp:
    """O que mudou após uma gravação de XP/Abysmus."""
    xp_antes: int
    xp_total: int
    nivel_antes: int
    nivel: int
    coins_total: int
    coins_por_nivel: int   # Abysmus recebido por níveis inéditos
    coins_extra: int       # Abysmus concedido diretamente (ex.: drop)


# ============================================================
# COG
# ============================================================

class SaldoInsuficienteError(ValueError):
    """Tentativa de remover mais Abysmus do que o membro possui."""

    def __init__(self, saldo: int):
        super().__init__("Saldo insuficiente.")
        self.saldo = saldo


class XpAndCoins(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Travas dos comandos de administrador: uma operação por vez em cada
        # membro. Se já houver uma em andamento, a nova é recusada na hora
        # (nada de fila de comandos empilhando).
        self._travas_gerenciar: dict[tuple[int, int], asyncio.Lock] = {}

        # Cache em memória do último XP recebido: evita consultar o banco
        # a cada mensagem enquanto o membro ainda está no cooldown.
        self._cache_ultimo_xp: dict[tuple[int, int], float] = {}

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.criar_tabelas()

    # ---------- Banco de dados ----------

    def conectar(self):
        return sqlite3.connect(DB_PATH, timeout=10)

    @contextmanager
    def transacao(self):
        """
        Abre uma transação única: confirma ao final com sucesso e desfaz
        tudo se qualquer erro ocorrer. A conexão sempre é fechada.
        """
        db = self.conectar()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def criar_tabelas(self):
        with self.transacao() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS user_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    xp INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 0,
                    coins INTEGER NOT NULL DEFAULT 0,
                    last_xp REAL NOT NULL DEFAULT 0,
                    highest_rewarded_level INTEGER NOT NULL DEFAULT 0,
                    last_daily TEXT NOT NULL DEFAULT '',
                    daily_streak INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

            # Migração: bancos criados antes do bônus diário não têm as
            # colunas novas. Elas são adicionadas sem perder nenhum dado.
            colunas = {
                linha[1]
                for linha in db.execute("PRAGMA table_info(user_stats)")
            }
            if "last_daily" not in colunas:
                db.execute(
                    "ALTER TABLE user_stats "
                    "ADD COLUMN last_daily TEXT NOT NULL DEFAULT ''"
                )
                log.info("Migração: coluna last_daily adicionada.")
            if "daily_streak" not in colunas:
                db.execute(
                    "ALTER TABLE user_stats "
                    "ADD COLUMN daily_streak INTEGER NOT NULL DEFAULT 0"
                )
                log.info("Migração: coluna daily_streak adicionada.")

    def garantir_usuario(self, db, guild_id: int, user_id: int):
        db.execute("""
            INSERT OR IGNORE INTO user_stats
                (guild_id, user_id)
            VALUES (?, ?)
        """, (guild_id, user_id))

    def obter_dados(self, guild_id: int, user_id: int):
        """Retorna (xp, level, coins, last_xp, highest_rewarded_level)."""
        with self.transacao() as db:
            self.garantir_usuario(db, guild_id, user_id)
            return db.execute("""
                SELECT xp, level, coins, last_xp,
                       highest_rewarded_level
                FROM user_stats
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id)).fetchone()

    def obter_diario(self, guild_id: int, user_id: int):
        """Retorna (último dia coletado, streak) do bônus diário."""
        with self.transacao() as db:
            self.garantir_usuario(db, guild_id, user_id)
            return db.execute("""
                SELECT last_daily, daily_streak
                FROM user_stats
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id)).fetchone()

    def _hoje(self) -> date:
        """Data atual no fuso configurado (isolado para facilitar testes)."""
        return datetime.now(FUSO_HORARIO).date()

    # ---------- Núcleo de gravação ----------

    def _gravar(
        self,
        db,
        guild_id: int,
        user_id: int,
        novo_xp: Callable[[int], int],
        *,
        coins_extra: int = 0,
        campos_extra: Optional[dict] = None,
    ) -> ResultadoXp:
        """
        ÚNICO ponto que altera XP, nível e Abysmus de nível.

        Deve ser chamado dentro de uma transação (self.transacao()).
        - novo_xp: função que recebe o XP atual e devolve o novo XP.
        - coins_extra: Abysmus concedido diretamente (ex.: drop de jogo).
        - campos_extra: outras colunas a gravar na mesma operação
          (chaves definidas pelo código, nunca por entrada do usuário).
        """
        self.garantir_usuario(db, guild_id, user_id)

        xp_antes, nivel_antes, coins, maior_recompensado = db.execute("""
            SELECT xp, level, coins, highest_rewarded_level
            FROM user_stats
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()

        xp_final = max(0, novo_xp(xp_antes))
        nivel_final, _, _ = calcular_nivel(xp_final)

        # Abysmus por nível inédito: raro e impossível de farmar subindo e
        # descendo de nível.
        coins_por_nivel = (
            max(0, nivel_final - maior_recompensado) * ABYSMUS_POR_NIVEL
        )
        coins += coins_por_nivel + coins_extra
        maior_recompensado = max(maior_recompensado, nivel_final)

        campos = {
            "xp": xp_final,
            "level": nivel_final,
            "coins": coins,
            "highest_rewarded_level": maior_recompensado,
        }
        if campos_extra:
            campos.update(campos_extra)

        atribuicoes = ", ".join(f"{coluna} = ?" for coluna in campos)
        db.execute(
            f"UPDATE user_stats SET {atribuicoes} "
            "WHERE guild_id = ? AND user_id = ?",
            (*campos.values(), guild_id, user_id),
        )

        return ResultadoXp(
            xp_antes=xp_antes,
            xp_total=xp_final,
            nivel_antes=nivel_antes,
            nivel=nivel_final,
            coins_total=coins,
            coins_por_nivel=coins_por_nivel,
            coins_extra=coins_extra,
        )

    # ---------- API pública (compatível com o código anterior) ----------

    def atualizar_xp(
        self,
        guild_id: int,
        user_id: int,
        novo_xp: int,
        *,
        last_xp: float | None = None,
    ):
        """
        Define o XP total; recompensa níveis inéditos com Abysmus.
        Retorna (xp, nível, coins, coins ganhos por nível).
        """
        campos = {"last_xp": last_xp} if last_xp is not None else None

        with self.transacao() as db:
            r = self._gravar(
                db, guild_id, user_id,
                lambda _atual: novo_xp,
                campos_extra=campos,
            )

        return r.xp_total, r.nivel, r.coins_total, r.coins_por_nivel

    def obter_saldo_tx(self, db, guild_id: int, user_id: int) -> int:
        """
        Lê o saldo de Abysmus DENTRO de uma transação já aberta
        (self.transacao()). Use em vez de obter_dados() quando já houver
        uma transação em andamento: abrir outra travaria o banco.
        """
        self.garantir_usuario(db, guild_id, user_id)

        return db.execute("""
            SELECT coins FROM user_stats
            WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()[0]

    def alterar_coins_tx(
        self,
        db,
        guild_id: int,
        user_id: int,
        diferenca: int,
    ) -> int:
        """
        Altera o saldo DENTRO de uma transação já aberta. Permite que
        outros cogs (ex.: loja de insígnias) debitem Abysmus e gravem suas
        próprias tabelas de forma atômica: se algo falhar, tudo é desfeito.
        Nunca permite saldo negativo (levanta ValueError).
        """
        saldo = self.obter_saldo_tx(db, guild_id, user_id)
        novo_saldo = saldo + diferenca

        if novo_saldo < 0:
            raise ValueError("Saldo insuficiente.")

        db.execute("""
            UPDATE user_stats
            SET coins = ?
            WHERE guild_id = ? AND user_id = ?
        """, (novo_saldo, guild_id, user_id))

        return novo_saldo

    def alterar_coins(
        self,
        guild_id: int,
        user_id: int,
        diferenca: int,
    ) -> int:
        """Altera o saldo. Nunca permite saldo negativo."""
        with self.transacao() as db:
            return self.alterar_coins_tx(db, guild_id, user_id, diferenca)

    # ---------- API para outros cogs ----------

    def conceder_recompensas(
        self,
        guild_id: int,
        user_id: int,
        xp: int = 0,
        coins: int = 0,
        origem: str = "externo",
    ) -> ResultadoXp:
        """
        Concede XP e/ou Abysmus vindos de outro sistema (ex.: jogo).

        - xp: XP somado ao total (níveis inéditos ainda pagam Abysmus).
        - coins: Abysmus concedido diretamente. Deve ser RARO (ex.: um
          drop de chance baixa), já que o Abysmus é a moeda rara.
        - origem: texto usado só no log do terminal.
        """
        if xp < 0 or coins < 0:
            raise ValueError("xp e coins devem ser valores positivos.")

        with self.transacao() as db:
            r = self._gravar(
                db, guild_id, user_id,
                lambda atual: atual + xp,
                coins_extra=coins,
            )

        log.info(
            "Recompensa [%s] guild=%s user=%s | +%s XP, +%s Abysmus direto, "
            "+%s por nível | nível %s -> %s | saldo=%s",
            origem, guild_id, user_id, xp, coins, r.coins_por_nivel,
            r.nivel_antes, r.nivel, r.coins_total,
        )
        return r

    # ---------- Gerenciamento por administradores (atômico) ----------

    def gerenciar_xp(
        self,
        guild_id: int,
        user_id: int,
        acao: str,
        quantidade: int,
    ) -> ResultadoXp:
        """
        Adiciona, remove ou define o XP em UMA transação (ler + gravar sem
        brecha para corrida com o XP de mensagens). O XP nunca fica
        negativo; níveis inéditos pagam Abysmus como sempre.
        """
        if quantidade < 0:
            raise ValueError("A quantidade não pode ser negativa.")

        if acao == "adicionar":
            calculo = lambda atual: atual + quantidade
        elif acao == "remover":
            calculo = lambda atual: max(0, atual - quantidade)
        elif acao == "definir":
            calculo = lambda _atual: quantidade
        else:
            raise ValueError(f"Ação inválida: {acao!r}.")

        with self.transacao() as db:
            return self._gravar(db, guild_id, user_id, calculo)

    def gerenciar_coins(
        self,
        guild_id: int,
        user_id: int,
        acao: str,
        quantidade: int,
    ) -> tuple[int, int]:
        """
        Adiciona, remove ou define o saldo de Abysmus em UMA transação.
        Retorna (saldo antes, saldo depois).
        Levanta SaldoInsuficienteError se a remoção deixaria o saldo < 0.
        """
        if quantidade < 0:
            raise ValueError("A quantidade não pode ser negativa.")
        if acao not in ("adicionar", "remover", "definir"):
            raise ValueError(f"Ação inválida: {acao!r}.")

        with self.transacao() as db:
            antes = self.obter_saldo_tx(db, guild_id, user_id)

            if acao == "adicionar":
                diferenca = quantidade
            elif acao == "remover":
                if quantidade > antes:
                    raise SaldoInsuficienteError(antes)
                diferenca = -quantidade
            else:
                diferenca = quantidade - antes

            depois = self.alterar_coins_tx(db, guild_id, user_id, diferenca)

        return antes, depois

    # ---------- XP por mensagem ----------

    async def processar_mensagem(self, message: discord.Message):
        """Chamado pelo evento on_message do main.py."""
        if message.guild is None:
            return

        if message.author.bot or not message.content.strip():
            return

        guild_id = message.guild.id
        user_id = message.author.id
        chave = (guild_id, user_id)
        agora = time.time()

        # Atalho barato: ainda em cooldown conforme o cache em memória.
        if agora - self._cache_ultimo_xp.get(chave, 0.0) < COOLDOWN_XP_SEGUNDOS:
            return

        ganho = calcular_xp_mensagem(message)
        hoje = self._hoje()

        # Leitura do cooldown, bônus diário e gravação: tudo na MESMA
        # transação, sem janela para ganhos duplicados.
        with self.transacao() as db:
            self.garantir_usuario(db, guild_id, user_id)

            ultimo_xp, ultimo_dia, streak = db.execute("""
                SELECT last_xp, last_daily, daily_streak
                FROM user_stats
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id)).fetchone()

            # O cache pode estar vazio (bot reiniciou): confirma no banco.
            if agora - ultimo_xp < COOLDOWN_XP_SEGUNDOS:
                self._cache_ultimo_xp[chave] = ultimo_xp
                return

            bonus_diario, nova_streak, coletou = calcular_diario(
                ultimo_dia, streak, hoje
            )

            campos = {"last_xp": agora}
            if coletou:
                campos["last_daily"] = hoje.isoformat()
                campos["daily_streak"] = nova_streak

            total = ganho.total + bonus_diario
            r = self._gravar(
                db, guild_id, user_id,
                lambda atual: atual + total,
                campos_extra=campos,
            )

        self._cache_ultimo_xp[chave] = agora

        log.debug(
            "XP msg guild=%s user=%s | base=%s texto=%s anexo=%s social=%s "
            "inspirado=%s diário=%s (streak %s) | total=+%s",
            guild_id, user_id, ganho.base, ganho.texto, ganho.anexo,
            ganho.social, ganho.inspirado, bonus_diario, nova_streak,
            total,
        )

        if r.nivel > r.nivel_antes:
            log.info(
                "Level up guild=%s user=%s | nível %s -> %s | "
                "+%s Abysmus | saldo=%s",
                guild_id, user_id, r.nivel_antes, r.nivel,
                r.coins_por_nivel, r.coins_total,
            )
            await self._anunciar_level_up(message, r)

    async def _anunciar_level_up(
        self,
        message: discord.Message,
        r: ResultadoXp,
    ):
        """Avisa no canal quando o membro sobe de nível."""
        if not ANUNCIAR_LEVEL_UP:
            return

        texto = f"🏆 {message.author.mention} chegou ao **nível {r.nivel}**!"
        if r.coins_por_nivel:
            texto += f" 🪙 +{r.coins_por_nivel} Abysmus"

        try:
            await message.channel.send(texto)
        except discord.HTTPException:
            # Sem permissão para falar no canal: o XP já foi salvo.
            log.warning(
                "Não foi possível anunciar o level up no canal %s.",
                getattr(message.channel, "id", "?"),
            )

    # ---------- Comandos ----------

    async def exigir_administrador(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando só pode ser usado em um servidor.",
                ephemeral=True,
            )
            return False

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Você precisa ser administrador para usar este comando.",
                ephemeral=True,
            )
            return False

        return True

    @app_commands.command(
        name="xp",
        description="Consulte o XP de um membro.",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        membro="Membro que deseja consultar; vazio para consultar você."
    )
    async def xp(
        self,
        interaction: discord.Interaction,
        membro: discord.Member | None = None,
    ):
        # Reconhece a interação antes de consultar SQLite, evitando 10062.
        await interaction.response.defer(thinking=True)
        alvo = membro or interaction.user
        total, _, coins, _, _ = await asyncio.to_thread(
            self.obter_dados, interaction.guild_id, alvo.id
        )
        nivel, progresso, necessario = calcular_nivel(total)

        # Situação do bônus diário.
        ultimo_dia, streak = await asyncio.to_thread(
            self.obter_diario, interaction.guild_id, alvo.id
        )
        hoje = self._hoje()
        bonus, _, disponivel = calcular_diario(ultimo_dia, streak, hoje)
        dias = streak_ativa(ultimo_dia, streak, hoje)

        embed = discord.Embed(
            title="✨ EXPERIÊNCIA",
            color=discord.Color.blurple(),
        )
        embed.set_author(
            name=alvo.display_name,
            icon_url=alvo.display_avatar.url,
        )
        embed.add_field(name="XP total", value=f"{total:,}")
        embed.add_field(name="Nível", value=str(nivel))
        embed.add_field(
            name="Progresso",
            value=f"{progresso:,}/{necessario:,} XP",
        )
        embed.add_field(name="🪙 Abysmus", value=f"{coins:,}")
        embed.add_field(name="🔥 Sequência diária", value=f"{dias} dia(s)")
        embed.add_field(
            name="Bônus de hoje",
            value=(
                f"⏳ +{bonus} XP na próxima mensagem"
                if disponivel
                else "✅ Já coletado"
            ),
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="level",
        description="Veja seu nível e progresso.",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        membro="Membro que deseja consultar; vazio para consultar você."
    )
    async def level(
        self,
        interaction: discord.Interaction,
        membro: discord.Member | None = None,
    ):
        alvo = membro or interaction.user
        total, _, coins, _, _ = self.obter_dados(
            interaction.guild_id, alvo.id
        )
        nivel, progresso, necessario = calcular_nivel(total)

        preenchidos = min(
            10, int((progresso / necessario) * 10)
        )
        barra = "🟩" * preenchidos + "⬛" * (10 - preenchidos)

        embed = discord.Embed(
            title=f"🏆 NÍVEL {nivel}",
            description=(
                f"**{alvo.display_name}**\n\n"
                f"{barra}\n"
                f"**{progresso:,}/{necessario:,} XP** "
                "para o próximo nível."
            ),
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=alvo.display_avatar.url)
        embed.add_field(name="XP total", value=f"{total:,}")
        embed.add_field(name="🪙 Abysmus", value=f"{coins:,}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="coins",
        description="Consulte seu saldo de Abysmus.",
    )
    @app_commands.guild_only()
    @app_commands.describe(
        membro="Membro que deseja consultar; vazio para consultar você."
    )
    async def coins(
        self,
        interaction: discord.Interaction,
        membro: discord.Member | None = None,
    ):
        alvo = membro or interaction.user
        _, _, saldo, _, _ = self.obter_dados(
            interaction.guild_id, alvo.id
        )

        await interaction.response.send_message(
            f"🪙 **{alvo.display_name}** possui **{saldo:,} Abysmus**."
        )

    # ---------- Comandos de administrador ----------

    async def _executar_gerenciar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        operacao,
    ):
        """
        Esqueleto seguro dos comandos de gerenciar. Garante que:
        - só administradores usam;
        - a interação é reconhecida na hora (sem erro de "não respondeu");
        - não há duas operações ao mesmo tempo no mesmo membro;
        - o banco roda em thread com tempo-limite;
        - SEMPRE existe uma resposta final (sucesso ou erro), sem loop.

        `operacao` é uma função sem argumentos (síncrona) que mexe no banco
        e devolve o texto da resposta de sucesso.
        """
        if not await self.exigir_administrador(interaction):
            return

        if membro.bot:
            await interaction.response.send_message(
                "❌ Bots não possuem XP nem Abysmus.", ephemeral=True
            )
            return

        chave = (interaction.guild_id, membro.id)
        trava = self._travas_gerenciar.setdefault(chave, asyncio.Lock())

        # Operação em andamento neste membro: recusa em vez de enfileirar.
        if trava.locked():
            await interaction.response.send_message(
                "⏳ Já existe uma alteração em andamento para este membro. "
                "Aguarde um instante.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        async with trava:
            try:
                texto = await asyncio.wait_for(
                    asyncio.to_thread(operacao),
                    timeout=GERENCIAR_TIMEOUT_SEGUNDOS,
                )
            except SaldoInsuficienteError as erro:
                texto = (
                    f"❌ {membro.mention} possui apenas "
                    f"**{erro.saldo:,} Abysmus**; não dá para remover mais "
                    "do que isso."
                )
            except asyncio.TimeoutError:
                log.error(
                    "Tempo esgotado ao gerenciar %s em guild=%s.",
                    membro.id, interaction.guild_id,
                )
                texto = (
                    "⌛ O banco demorou demais para responder. Verifique o "
                    "valor com /xp ou /coins antes de tentar de novo."
                )
            except sqlite3.Error:
                log.exception("Erro no banco ao gerenciar %s.", membro.id)
                texto = "❌ Erro ao atualizar o banco de dados."
            except ValueError as erro:
                texto = f"❌ {erro}"
            except Exception:
                log.exception("Erro inesperado ao gerenciar %s.", membro.id)
                texto = "❌ Erro inesperado. Veja o log do bot."

        try:
            await interaction.followup.send(texto, ephemeral=True)
        except discord.HTTPException:
            log.warning("Não foi possível enviar a resposta do gerenciar.")

        # Limpa a trava para não acumular entradas na memória.
        if not trava.locked():
            self._travas_gerenciar.pop(chave, None)

    @app_commands.command(
        name="xp_gerenciar",
        description="Adicione, remova ou defina o XP de um membro (admin).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.cooldown(
        1, GERENCIAR_COOLDOWN_SEGUNDOS,
        key=lambda i: (i.guild_id, i.user.id),
    )
    @app_commands.describe(
        membro="Membro que será alterado.",
        acao="Operação de XP.",
        quantidade="Quantidade de XP.",
    )
    @app_commands.choices(acao=[
        app_commands.Choice(name="Adicionar", value="adicionar"),
        app_commands.Choice(name="Remover", value="remover"),
        app_commands.Choice(name="Definir total", value="definir"),
    ])
    async def xp_gerenciar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        acao: app_commands.Choice[str],
        quantidade: app_commands.Range[int, 0, GERENCIAR_MAX_QUANTIDADE],
    ):
        guild_id, admin_id = interaction.guild_id, interaction.user.id

        def operacao() -> str:
            r = self.gerenciar_xp(guild_id, membro.id, acao.value, quantidade)

            log.info(
                "Admin %s alterou XP de %s (%s %s) -> xp=%s nível=%s",
                admin_id, membro.id, acao.value, quantidade,
                r.xp_total, r.nivel,
            )

            texto = (
                f"✅ XP atualizado para {membro.mention}.\n"
                f"**XP:** {r.xp_antes:,} → {r.xp_total:,}\n"
                f"**Nível:** {r.nivel_antes} → {r.nivel}\n"
                f"**Abysmus:** {r.coins_total:,}"
            )
            if r.coins_por_nivel:
                texto += (
                    "\n🏆 Recompensa por nível inédito: "
                    f"+{r.coins_por_nivel} Abysmus."
                )
            return texto

        await self._executar_gerenciar(interaction, membro, operacao)

    @app_commands.command(
        name="coin_gerenciar",
        description="Adicione, remova ou defina Abysmus de um membro (admin).",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.cooldown(
        1, GERENCIAR_COOLDOWN_SEGUNDOS,
        key=lambda i: (i.guild_id, i.user.id),
    )
    @app_commands.describe(
        membro="Membro que será alterado.",
        acao="Operação de moedas.",
        quantidade="Quantidade de Abysmus.",
    )
    @app_commands.choices(acao=[
        app_commands.Choice(name="Adicionar", value="adicionar"),
        app_commands.Choice(name="Remover", value="remover"),
        app_commands.Choice(name="Definir saldo", value="definir"),
    ])
    async def coin_gerenciar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
        acao: app_commands.Choice[str],
        quantidade: app_commands.Range[int, 0, GERENCIAR_MAX_QUANTIDADE],
    ):
        guild_id, admin_id = interaction.guild_id, interaction.user.id

        def operacao() -> str:
            antes, depois = self.gerenciar_coins(
                guild_id, membro.id, acao.value, quantidade
            )

            log.info(
                "Admin %s alterou Abysmus de %s (%s %s) -> %s => %s",
                admin_id, membro.id, acao.value, quantidade, antes, depois,
            )

            return (
                f"🪙 Saldo de {membro.mention} atualizado.\n"
                f"**Abysmus:** {antes:,} → {depois:,}"
            )

        await self._executar_gerenciar(interaction, membro, operacao)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        """
        Garante resposta mesmo quando uma verificação falha (permissão,
        cooldown) ou algo escapa: o comando nunca fica sem resposta.
        """
        if isinstance(error, app_commands.MissingPermissions):
            texto = "Você precisa ser administrador para usar este comando."
        elif isinstance(error, app_commands.CommandOnCooldown):
            texto = (
                f"⏳ Aguarde {error.retry_after:.0f}s para usar de novo."
            )
        elif isinstance(error, app_commands.NoPrivateMessage):
            texto = "Este comando só pode ser usado em um servidor."
        else:
            log.exception(
                "Erro não tratado em /%s.",
                interaction.command.qualified_name
                if interaction.command else "?",
                exc_info=error,
            )
            texto = "❌ Ocorreu um erro ao executar o comando."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(
                    texto, ephemeral=True
                )
        except discord.HTTPException:
            pass

    async def cog_load(self):
        # Ajuda a diagnosticar "o slash não aparece": mostra no terminal
        # quais comandos este cog registrou na árvore do bot.
        nomes = sorted(c.qualified_name for c in self.get_app_commands())
        log.info("Comandos de XP registrados: %s", ", ".join(nomes))


async def setup(bot: commands.Bot):
    await bot.add_cog(XpAndCoins(bot))
