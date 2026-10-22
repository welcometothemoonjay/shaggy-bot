"""
CASSINO MALDITO — Shaggy Bot
============================

Jogos:
- Roleta da Ruptura
- Cara ou Coroa do Abismo
- Dados Amaldiçoados
- Blackjack das Almas
- Caça-Níquel Temporal
- Escolha do Destino (SFA)

Integração:
- discord.py 2.x
- Cog de economia: XpAndCoins
- Moeda: Abysmus
- Banco independente de estatísticas em data/cassino.db

Comando:
    /cassino

O usuário escolhe o jogo e a aposta pela interface.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("shaggy.cassino")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "cassino.db"

MIN_APOSTA = 1
MAX_APOSTA = 100_000
COOLDOWN_SEGUNDOS = 3

# Pagamentos totais, incluindo a aposta original quando aplicável.
# Multiplicadores inteiros reduzem erros de arredondamento.
JOGOS = {
    "roleta": "Roleta da Ruptura",
    "moeda": "Cara ou Coroa do Abismo",
    "dados": "Dados Amaldiçoados",
    "blackjack": "Blackjack das Almas",
    "slot": "Caça-Níquel Temporal",
    "destino": "Escolha do Destino — SFA",
}

NPCS = {
    "roleta": ("O Cronometrista", "O tempo sempre cobra sua parte."),
    "moeda": ("A Moedeira do Abismo", "Dois lados. Nenhuma promessa."),
    "dados": ("O Cubista Cego", "Os dados já sabem o resultado."),
    "blackjack": ("Madame Última", "A casa nunca esquece uma alma."),
    "slot": ("O Mecânico Temporal", "Puxe a alavanca. Se o tempo deixar."),
    "destino": ("O Mensageiro", "Escolha rápido. A realidade não espera."),
}


def conectar() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def inicializar_banco() -> None:
    with conectar() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cassino_stats (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                partidas INTEGER NOT NULL DEFAULT 0,
                vitorias INTEGER NOT NULL DEFAULT 0,
                derrotas INTEGER NOT NULL DEFAULT 0,
                empates INTEGER NOT NULL DEFAULT 0,
                apostado INTEGER NOT NULL DEFAULT 0,
                recebido INTEGER NOT NULL DEFAULT 0,
                maior_premio INTEGER NOT NULL DEFAULT 0,
                lucro_liquido INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS cassino_historico (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                jogo TEXT NOT NULL,
                aposta INTEGER NOT NULL,
                retorno INTEGER NOT NULL,
                resultado TEXT NOT NULL,
                lucro INTEGER NOT NULL,
                criado_em REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cassino_historico_user
            ON cassino_historico(guild_id, user_id, id DESC);
        """
        )


@dataclass
class Resultado:
    titulo: str
    descricao: str
    retorno: int
    estado: str  # vitoria, derrota, empate


class EconomiaIndisponivel(Exception):
    """A economia não pôde confirmar uma operação com segurança."""


class AdaptadorEconomia:
    """
    Adaptador para o Cog XpAndCoins.

    Interface esperada da versão conhecida:
      - obter_dados(guild_id, user_id), com saldo em [2]
      - alterar_coins(guild_id, user_id, diferenca)

    O saldo não é alterado diretamente neste banco de cassino.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _cog(self):
        cog = self.bot.get_cog("XpAndCoins")
        if cog is None:
            raise EconomiaIndisponivel(
                "Não encontrei o Cog XpAndCoins. "
                "Confira se ele foi carregado no main.py."
            )
        return cog

    async def saldo(self, guild_id: int, user_id: int) -> int:
        cog = self._cog()
        metodo = getattr(cog, "obter_dados", None)
        if metodo is None:
            raise EconomiaIndisponivel("O Cog XpAndCoins não possui obter_dados().")

        dados = await asyncio.to_thread(metodo, guild_id, user_id)
        try:
            return int(dados[2])
        except (TypeError, IndexError, KeyError, ValueError):
            raise EconomiaIndisponivel(
                "Não consegui identificar o saldo em obter_dados()[2]."
            )

    async def alterar(self, guild_id: int, user_id: int, valor: int) -> None:
        if valor == 0:
            return

        cog = self._cog()
        metodo = getattr(cog, "alterar_coins", None)
        if metodo is None:
            raise EconomiaIndisponivel("O Cog XpAndCoins não possui alterar_coins().")

        resultado = await asyncio.to_thread(metodo, guild_id, user_id, valor)
        # Algumas implementações retornam False quando a operação falha.
        if resultado is False:
            raise EconomiaIndisponivel("A economia recusou a movimentação de Abysmus.")

    async def apostar(self, guild_id: int, user_id: int, valor: int) -> None:
        saldo_atual = await self.saldo(guild_id, user_id)
        if saldo_atual < valor:
            raise EconomiaIndisponivel(
                f"Saldo insuficiente. Você tem {saldo_atual:,} Abysmus."
            )
        await self.alterar(guild_id, user_id, -valor)

    async def pagar(self, guild_id: int, user_id: int, valor: int) -> None:
        if valor > 0:
            await self.alterar(guild_id, user_id, valor)


class CassinoMaldito(commands.Cog):
    """Jogos de azar fictícios do Shaggy Bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.economia = AdaptadorEconomia(bot)
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._ultimo_jogo: dict[tuple[int, int], float] = {}
        inicializar_banco()

    def lock_usuario(self, guild_id: int, user_id: int) -> asyncio.Lock:
        chave = (guild_id, user_id)
        if chave not in self._locks:
            self._locks[chave] = asyncio.Lock()
        return self._locks[chave]

    @staticmethod
    def embed(
        titulo: str,
        descricao: str,
        cor: discord.Color = discord.Color.dark_purple(),
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎰 {titulo}",
            description=descricao,
            color=cor,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Cassino Maldito • Shaggy Bot")
        return embed

    async def registrar(
        self,
        guild_id: int,
        user_id: int,
        jogo: str,
        aposta: int,
        retorno: int,
        resultado: str,
    ) -> None:
        lucro = retorno - aposta
        with conectar() as db:
            db.execute(
                """
                INSERT INTO cassino_stats (
                    guild_id, user_id, partidas, vitorias, derrotas,
                    empates, apostado, recebido, maior_premio, lucro_liquido
                )
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    partidas = partidas + 1,
                    vitorias = vitorias + excluded.vitorias,
                    derrotas = derrotas + excluded.derrotas,
                    empates = empates + excluded.empates,
                    apostado = apostado + excluded.apostado,
                    recebido = recebido + excluded.recebido,
                    maior_premio = MAX(maior_premio, excluded.maior_premio),
                    lucro_liquido = lucro_liquido + excluded.lucro_liquido
            """,
                (
                    guild_id,
                    user_id,
                    int(resultado == "vitoria"),
                    int(resultado == "derrota"),
                    int(resultado == "empate"),
                    aposta,
                    retorno,
                    retorno,
                    lucro,
                ),
            )
            db.execute(
                """
                INSERT INTO cassino_historico (
                    guild_id, user_id, jogo, aposta, retorno,
                    resultado, lucro, criado_em
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    guild_id,
                    user_id,
                    jogo,
                    aposta,
                    retorno,
                    resultado,
                    lucro,
                    time.time(),
                ),
            )

    async def executar_partida(
        self,
        interaction: discord.Interaction,
        jogo: str,
        aposta: int,
        jogada: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "O Cassino Maldito só funciona dentro de um servidor.",
                ephemeral=True,
            )
            return

        if aposta < MIN_APOSTA or aposta > MAX_APOSTA:
            await interaction.response.send_message(
                f"A aposta deve ficar entre {MIN_APOSTA:,} e "
                f"{MAX_APOSTA:,} Abysmus.",
                ephemeral=True,
            )
            return

        guild_id = interaction.guild_id
        user_id = interaction.user.id
        chave = (guild_id, user_id)
        lock = self.lock_usuario(guild_id, user_id)

        if lock.locked():
            await interaction.response.send_message(
                "⏳ Você já tem uma partida sendo processada.",
                ephemeral=True,
            )
            return

        async with lock:
            agora = time.monotonic()
            restante = COOLDOWN_SEGUNDOS - (agora - self._ultimo_jogo.get(chave, 0))
            if restante > 0:
                await interaction.response.send_message(
                    f"Espere {restante:.1f}s antes de jogar novamente.",
                    ephemeral=True,
                )
                return

            self._ultimo_jogo[chave] = agora

            try:
                await self.economia.apostar(guild_id, user_id, aposta)
            except EconomiaIndisponivel as exc:
                await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
                return
            except Exception:
                log.exception("Falha ao debitar aposta")
                await interaction.response.send_message(
                    "Não consegui confirmar sua aposta. "
                    "Nenhuma partida foi iniciada.",
                    ephemeral=True,
                )
                return

            try:
                resultado = self.calcular(jogo, aposta, jogada)
            except Exception:
                # Se o jogo falhar depois do débito, tenta devolver a aposta.
                try:
                    await self.economia.pagar(guild_id, user_id, aposta)
                except Exception:
                    log.exception("ERRO CRÍTICO: falha ao devolver aposta")
                log.exception("Falha calculando partida")
                await interaction.response.send_message(
                    "A partida falhou e tentei devolver sua aposta. "
                    "Se o saldo não voltar, avise a administração.",
                    ephemeral=True,
                )
                return

            try:
                await self.economia.pagar(guild_id, user_id, resultado.retorno)
            except Exception:
                # O resultado fica registrado para auditoria; não fingimos
                # que o pagamento ocorreu.
                log.exception("Pagamento de prêmio falhou")
                await interaction.response.send_message(
                    "A partida foi calculada, mas o pagamento falhou. "
                    "Avise a administração com este horário para conferência.",
                    ephemeral=True,
                )
                return

            await self.registrar(
                guild_id,
                user_id,
                jogo,
                aposta,
                resultado.retorno,
                resultado.estado,
            )

            lucro = resultado.retorno - aposta
            cor = (
                discord.Color.green()
                if lucro > 0
                else discord.Color.gold() if lucro == 0 else discord.Color.red()
            )
            nome_npc, fala_npc = NPCS[jogo]
            embed = self.embed(
                resultado.titulo,
                resultado.descricao,
                cor,
            )
            embed.add_field(
                name="Aposta",
                value=f"{aposta:,} Abysmus",
                inline=True,
            )
            embed.add_field(
                name="Retorno",
                value=f"{resultado.retorno:,} Abysmus",
                inline=True,
            )
            embed.add_field(
                name="Lucro/prejuízo",
                value=f"{lucro:+,} Abysmus",
                inline=True,
            )
            embed.add_field(
                name=f"💀 {nome_npc}",
                value=f"*{fala_npc}*",
                inline=False,
            )
            embed.set_author(
                name=interaction.user.display_name,
                icon_url=interaction.user.display_avatar.url,
            )

            if not interaction.response.is_done():
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.followup.send(embed=embed)

    @staticmethod
    def calcular(jogo: str, aposta: int, jogada: str) -> Resultado:
        """Resolve uma partida sem acessar Discord ou banco."""

        if jogo == "roleta":
            # 0–36: apostar em uma cor paga 2x no total; verde paga 14x.
            numero = random.randint(0, 36)
            cor = "verde" if numero == 0 else "vermelho" if numero % 2 == 1 else "preto"
            if jogada == cor:
                retorno = aposta * (14 if cor == "verde" else 2)
                return Resultado(
                    "A Ruptura escolheu você!",
                    f"A roleta parou em **{numero} — {cor}**. "
                    "O tempo abriu uma fenda a seu favor.",
                    retorno,
                    "vitoria",
                )
            return Resultado(
                "A roleta devorou sua aposta",
                f"Saiu **{numero} — {cor}**. " "A Ruptura fechou a passagem.",
                0,
                "derrota",
            )

        if jogo == "moeda":
            lado = random.choice(("cara", "coroa"))
            if jogada == lado:
                return Resultado(
                    "O Abismo respondeu",
                    f"A moeda caiu em **{lado.upper()}**. "
                    "Por um instante, você enganou o destino.",
                    aposta * 2,
                    "vitoria",
                )
            return Resultado(
                "A moeda caiu",
                f"Deu **{lado.upper()}**. " "O Abismo guarda seus Abysmus.",
                0,
                "derrota",
            )

        if jogo == "dados":
            jogador = random.randint(1, 6) + random.randint(1, 6)
            casa = random.randint(1, 6) + random.randint(1, 6)
            if jogador > casa:
                return Resultado(
                    "Os dados amaldiçoados",
                    f"Seus dados: **{jogador}**. "
                    f"Dados da casa: **{casa}**. Você venceu.",
                    aposta * 2,
                    "vitoria",
                )
            if jogador == casa:
                return Resultado(
                    "Empate impossível",
                    f"Você: **{jogador}** | Casa: **{casa}**. "
                    "A maldição mantém a aposta.",
                    aposta,
                    "empate",
                )
            return Resultado(
                "A casa lançou mais alto",
                f"Você: **{jogador}** | Casa: **{casa}**. "
                "Os dados sussurram seu nome.",
                0,
                "derrota",
            )

        if jogo == "blackjack":
            # Versão simplificada: jogador contra uma mão fixa da casa.
            # Aposta vencedora retorna 2x; empate devolve 1x.
            def carta() -> int:
                return random.choice([2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 11])

            jogador = carta() + carta()
            casa = carta() + carta()

            while jogador < 17 and random.random() < 0.75:
                jogador += carta()
            while casa < 17:
                casa += carta()

            if jogador > 21:
                estado, retorno = "derrota", 0
                msg = "Você passou de 21 e perdeu."
            elif casa > 21 or jogador > casa:
                estado, retorno = "vitoria", aposta * 2
                msg = "Madame Última perdeu a mão."
            elif jogador == casa:
                estado, retorno = "empate", aposta
                msg = "As almas ficam em equilíbrio; aposta devolvida."
            else:
                estado, retorno = "derrota", 0
                msg = "A casa ficou mais perto de 21."

            return Resultado(
                "Blackjack das Almas",
                f"Sua mão: **{jogador}** | Casa: **{casa}**. {msg}",
                retorno,
                estado,
            )

        if jogo == "slot":
            simbolos = ["⏳", "🌀", "💀", "🔔", "🌑", "🪙"]
            rolos = [random.choice(simbolos) for _ in range(3)]
            if rolos[0] == rolos[1] == rolos[2]:
                retorno, estado = aposta * 8, "vitoria"
                texto = "Três símbolos iguais! O tempo se dobrou."
            elif len(set(rolos)) == 2:
                retorno, estado = aposta * 2, "vitoria"
                texto = "Dois símbolos combinaram. A fenda pagou."
            else:
                retorno, estado = 0, "derrota"
                texto = "Os rolos não combinaram."
            return Resultado(
                "Caça-Níquel Temporal",
                f"{' | '.join(rolos)}\n\n{texto}",
                retorno,
                estado,
            )

        if jogo == "destino":
            # Risco SFA: escolha entre estabilidade e ruptura.
            # Seguro: 50% de chance de retorno 2x.
            # Ruptura: 25% de chance de retorno 4x.
            sorte = random.random()
            if jogada == "estabilidade":
                if sorte < 0.50:
                    return Resultado(
                        "A floresta permitiu",
                        "Você escolheu a estabilidade e encontrou "
                        "um caminho de volta.",
                        aposta * 2,
                        "vitoria",
                    )
                return Resultado(
                    "A floresta fechou o caminho",
                    "A estabilidade era apenas uma ilusão.",
                    0,
                    "derrota",
                )
            if sorte < 0.25:
                return Resultado(
                    "A realidade se partiu",
                    "A Ruptura Temporal abriu um caminho impossível. "
                    "Você voltou com o prêmio multiplicado.",
                    aposta * 4,
                    "vitoria",
                )
            return Resultado(
                "O preço da ruptura",
                "A floresta apagou seus rastros e ficou com a aposta.",
                0,
                "derrota",
            )

        raise ValueError(f"Jogo desconhecido: {jogo}")

    @app_commands.command(
        name="cassino",
        description="Entre no Cassino Maldito e aposte Abysmus.",
    )
    async def cassino(self, interaction: discord.Interaction):
        embed = self.embed(
            "Cassino Maldito",
            "Seis jogos. Uma moeda amaldiçoada. "
            "O destino não aceita reclamações.\n\n"
            "**Escolha seu jogo abaixo.**",
        )
        embed.add_field(
            name="Aposta permitida",
            value=f"{MIN_APOSTA:,}–{MAX_APOSTA:,} Abysmus",
            inline=False,
        )
        embed.add_field(
            name="Aviso",
            value="Aposte apenas Abysmus fictícios do bot. "
            "As partidas não envolvem dinheiro real.",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed,
            view=MenuCassino(self),
            ephemeral=True,
        )

    @app_commands.command(
        name="cassino_stats",
        description="Veja suas estatísticas no Cassino Maldito.",
    )
    async def cassino_stats(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Use este comando dentro de um servidor.",
                ephemeral=True,
            )
            return

        with conectar() as db:
            stats = db.execute(
                """
                SELECT * FROM cassino_stats
                WHERE guild_id = ? AND user_id = ?
            """,
                (interaction.guild_id, interaction.user.id),
            ).fetchone()

        if not stats:
            await interaction.response.send_message(
                "Você ainda não jogou no Cassino Maldito.",
                ephemeral=True,
            )
            return

        embed = self.embed(
            f"Histórico de {interaction.user.display_name}",
            "Os registros do destino não mentem.",
        )
        embed.add_field(name="Partidas", value=f"{stats['partidas']:,}")
        embed.add_field(name="Vitórias", value=f"{stats['vitorias']:,}")
        embed.add_field(name="Derrotas", value=f"{stats['derrotas']:,}")
        embed.add_field(name="Empates", value=f"{stats['empates']:,}")
        embed.add_field(
            name="Total apostado",
            value=f"{stats['apostado']:,} Abysmus",
            inline=False,
        )
        embed.add_field(
            name="Total recebido",
            value=f"{stats['recebido']:,} Abysmus",
            inline=False,
        )
        embed.add_field(
            name="Lucro/prejuízo líquido",
            value=f"{stats['lucro_liquido']:+,} Abysmus",
            inline=False,
        )
        embed.add_field(
            name="Maior retorno",
            value=f"{stats['maior_premio']:,} Abysmus",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MenuCassino(discord.ui.View):
    def __init__(self, cog: CassinoMaldito):
        super().__init__(timeout=180)
        self.cog = cog

    async def escolher(
        self,
        interaction: discord.Interaction,
        jogo: str,
    ) -> None:
        await interaction.response.send_message(
            embed=self.cog.embed(
                JOGOS[jogo],
                "Escolha sua aposta e confirme a jogada. "
                "A aposta só é debitada ao iniciar a partida.",
            ),
            view=PainelJogo(self.cog, interaction.user.id, jogo),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Roleta da Ruptura",
        emoji="🎡",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def roleta(self, interaction, button):
        await self.escolher(interaction, "roleta")

    @discord.ui.button(
        label="Cara ou Coroa",
        emoji="🪙",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def moeda(self, interaction, button):
        await self.escolher(interaction, "moeda")

    @discord.ui.button(
        label="Dados Amaldiçoados",
        emoji="🎲",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def dados(self, interaction, button):
        await self.escolher(interaction, "dados")

    @discord.ui.button(
        label="Blackjack das Almas",
        emoji="🃏",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def blackjack(self, interaction, button):
        await self.escolher(interaction, "blackjack")

    @discord.ui.button(
        label="Caça-Níquel Temporal",
        emoji="🎰",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def slot(self, interaction, button):
        await self.escolher(interaction, "slot")

    @discord.ui.button(
        label="Escolha do Destino (SFA)",
        emoji="🌲",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def destino(self, interaction, button):
        await self.escolher(interaction, "destino")


class PainelJogo(discord.ui.View):
    def __init__(
        self,
        cog: CassinoMaldito,
        dono_id: int,
        jogo: str,
    ):
        super().__init__(timeout=180)
        self.cog = cog
        self.dono_id = dono_id
        self.jogo = jogo
        self.aposta = 10
        self.jogada: Optional[str] = None

        if jogo == "roleta":
            opcoes = [
                ("Vermelho", "vermelho", discord.ButtonStyle.danger),
                ("Preto", "preto", discord.ButtonStyle.secondary),
                ("Verde (0)", "verde", discord.ButtonStyle.success),
            ]
        elif jogo == "moeda":
            opcoes = [
                ("Cara", "cara", discord.ButtonStyle.primary),
                ("Coroa", "coroa", discord.ButtonStyle.secondary),
            ]
        elif jogo == "destino":
            opcoes = [
                ("Estabilidade (2x)", "estabilidade", discord.ButtonStyle.success),
                ("Ruptura (4x)", "ruptura", discord.ButtonStyle.danger),
            ]
        else:
            opcoes = [("Jogar", "jogar", discord.ButtonStyle.primary)]

        for label, valor, estilo in opcoes:
            botao = discord.ui.Button(
                label=label,
                style=estilo,
                row=0,
            )
            botao.callback = self._criar_callback(valor)
            self.add_item(botao)

        self.add_item(BotaoAposta(self))

    def _criar_callback(self, escolha: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.dono_id:
                await interaction.response.send_message(
                    "Este painel pertence a outra pessoa.",
                    ephemeral=True,
                )
                return

            if escolha == "jogar":
                self.jogada = "jogar"
            else:
                self.jogada = escolha

            await interaction.response.send_modal(ModalAposta(self, self.jogada))

        return callback


class BotaoAposta(discord.ui.Button):
    def __init__(self, painel: PainelJogo):
        super().__init__(
            label="Definir aposta",
            emoji="💰",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        self.painel = painel

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.painel.dono_id:
            await interaction.response.send_message(
                "Este painel pertence a outra pessoa.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            ModalAposta(self.painel, self.painel.jogada)
        )


class ModalAposta(discord.ui.Modal, title="Aposta do Cassino Maldito"):
    valor = discord.ui.TextInput(
        label="Quantos Abysmus deseja apostar?",
        placeholder="Ex.: 100",
        default="100",
        min_length=1,
        max_length=9,
        required=True,
    )

    def __init__(self, painel: PainelJogo, jogada: Optional[str]):
        super().__init__()
        self.painel = painel
        self.jogada = jogada

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.painel.dono_id:
            await interaction.response.send_message(
                "Este painel pertence a outra pessoa.",
                ephemeral=True,
            )
            return

        try:
            aposta = int(str(self.valor.value).strip())
        except ValueError:
            await interaction.response.send_message(
                "Digite um número inteiro válido.",
                ephemeral=True,
            )
            return

        if not MIN_APOSTA <= aposta <= MAX_APOSTA:
            await interaction.response.send_message(
                f"A aposta deve ficar entre {MIN_APOSTA:,} e "
                f"{MAX_APOSTA:,} Abysmus.",
                ephemeral=True,
            )
            return

        jogo = self.painel.jogo
        jogada = self.jogada

        if jogo in {"roleta", "moeda", "destino"} and not jogada:
            await interaction.response.send_message(
                "Escolha uma opção antes de apostar.",
                ephemeral=True,
            )
            return

        if jogo in {"blackjack", "dados", "slot"}:
            jogada = "jogar"

        await self.painel.cog.executar_partida(
            interaction, jogo, aposta, jogada or "jogar"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(CassinoMaldito(bot))
