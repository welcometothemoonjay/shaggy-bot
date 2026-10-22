"""
RANKING — quem tem mais nível e mais Abysmus no Shaggy
=======================================================

Cog somente de LEITURA: usa o banco do XpAndCoins e nunca altera nada.

Comando:
    /ranking categoria:[Nível | Abysmus]

- Nível: ordenado pelo XP total (desempate pelo ID, para ficar estável).
- Abysmus: ordenado pelo saldo (desempate pelo XP).
- 10 membros por página, com botões ◀ ▶ (só quem usou o comando navega).
- Mostra a posição de quem consultou no rodapé.
- Membros que saíram do servidor são ocultados quando o cache de membros
  está completo (guild.chunked).

Requer o cog XpAndCoins carregado (carregue-o antes deste).
"""

import asyncio
import logging
from contextlib import closing

import discord
from discord import app_commands
from discord.ext import commands


log = logging.getLogger("shaggy.ranking")

POR_PAGINA = 10
TIMEOUT_VIEW_SEGUNDOS = 120

MEDALHAS = {1: "🥇", 2: "🥈", 3: "🥉"}

CATEGORIAS = {
    "nivel": {
        "titulo": "🏆 Ranking de Nível",
        "cor": discord.Color.gold(),
        "vazio": "Ninguém ganhou XP neste servidor ainda.",
        # Ordena pelo XP total: o nível é derivado dele.
        "sql": """
            SELECT user_id, xp, level, coins
            FROM user_stats
            WHERE guild_id = ? AND xp > 0
            ORDER BY xp DESC, user_id ASC
        """,
    },
    "abysmus": {
        "titulo": "🪙 Ranking de Abysmus",
        "cor": discord.Color.dark_purple(),
        "vazio": "Ninguém possui Abysmus neste servidor ainda.",
        "sql": """
            SELECT user_id, xp, level, coins
            FROM user_stats
            WHERE guild_id = ? AND coins > 0
            ORDER BY coins DESC, xp DESC, user_id ASC
        """,
    },
}


def formatar_linha(posicao: int, categoria: str, linha: tuple) -> str:
    user_id, xp, nivel, coins = linha
    marcador = MEDALHAS.get(posicao, f"`{posicao:>2}.`")

    if categoria == "nivel":
        detalhe = f"**Nível {nivel}** • {xp:,} XP"
    else:
        detalhe = f"**{coins:,} 🪙** • Nível {nivel}"

    return f"{marcador} <@{user_id}> — {detalhe}"


class RankingView(discord.ui.View):
    """Paginação do ranking; só quem pediu pode usar os botões."""

    def __init__(
        self,
        autor_id: int,
        categoria: str,
        linhas: list[tuple],
        posicao_autor: int | None,
    ):
        super().__init__(timeout=TIMEOUT_VIEW_SEGUNDOS)
        self.autor_id = autor_id
        self.categoria = categoria
        self.linhas = linhas
        self.posicao_autor = posicao_autor
        self.pagina = 0
        self.mensagem_original: discord.Interaction | None = None
        self._atualizar_botoes()

    @property
    def total_paginas(self) -> int:
        return max(1, -(-len(self.linhas) // POR_PAGINA))

    def _atualizar_botoes(self):
        self.anterior.disabled = self.pagina <= 0
        self.proxima.disabled = self.pagina >= self.total_paginas - 1

    def montar_embed(self) -> discord.Embed:
        config = CATEGORIAS[self.categoria]
        inicio = self.pagina * POR_PAGINA
        fatia = self.linhas[inicio:inicio + POR_PAGINA]

        descricao = "\n".join(
            formatar_linha(inicio + i + 1, self.categoria, linha)
            for i, linha in enumerate(fatia)
        )

        embed = discord.Embed(
            title=config["titulo"],
            description=descricao,
            color=config["cor"],
        )

        rodape = f"Página {self.pagina + 1}/{self.total_paginas}"
        if self.posicao_autor:
            rodape += f" • Sua posição: #{self.posicao_autor}"
        embed.set_footer(text=rodape)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "Use /ranking para abrir o seu próprio ranking.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def anterior(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.pagina = max(0, self.pagina - 1)
        self._atualizar_botoes()
        await interaction.response.edit_message(
            embed=self.montar_embed(), view=self
        )

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def proxima(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.pagina = min(self.total_paginas - 1, self.pagina + 1)
        self._atualizar_botoes()
        await interaction.response.edit_message(
            embed=self.montar_embed(), view=self
        )

    async def on_timeout(self):
        # Remove os botões quando o tempo acaba.
        if self.mensagem_original is None:
            return
        try:
            await self.mensagem_original.edit_original_response(view=None)
        except discord.HTTPException:
            pass


class Ranking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _buscar_linhas(self, categoria: str, guild_id: int) -> list[tuple]:
        """Lê o ranking no banco do XpAndCoins (somente leitura)."""
        xp_cog = self.bot.get_cog("XpAndCoins")
        if xp_cog is None:
            raise RuntimeError("Cog XpAndCoins não está carregado.")

        with closing(xp_cog.conectar()) as db:
            return db.execute(
                CATEGORIAS[categoria]["sql"], (guild_id,)
            ).fetchall()

    @app_commands.command(
        name="ranking",
        description="Veja quem tem mais nível ou mais Abysmus no servidor.",
    )
    @app_commands.guild_only()
    @app_commands.describe(categoria="O que você quer ver no ranking.")
    @app_commands.choices(categoria=[
        app_commands.Choice(name="🏆 Nível", value="nivel"),
        app_commands.Choice(name="🪙 Abysmus", value="abysmus"),
    ])
    async def ranking(
        self,
        interaction: discord.Interaction,
        categoria: app_commands.Choice[str] | None = None,
    ):
        # Reconhece a interação antes de consultar o SQLite (evita 10062).
        await interaction.response.defer(thinking=True)

        chave = categoria.value if categoria else "nivel"

        try:
            linhas = await asyncio.to_thread(
                self._buscar_linhas, chave, interaction.guild_id
            )
        except Exception:
            log.exception("Falha ao montar o ranking (%s).", chave)
            await interaction.followup.send(
                "❌ Não consegui carregar o ranking agora. Tente novamente.",
                ephemeral=True,
            )
            return

        # Oculta quem saiu do servidor (só confiável com cache completo).
        guild = interaction.guild
        if guild is not None and guild.chunked:
            linhas = [
                linha for linha in linhas
                if guild.get_member(linha[0]) is not None
            ]

        if not linhas:
            await interaction.followup.send(CATEGORIAS[chave]["vazio"])
            return

        posicao_autor = next(
            (
                indice + 1
                for indice, linha in enumerate(linhas)
                if linha[0] == interaction.user.id
            ),
            None,
        )

        view = RankingView(
            interaction.user.id, chave, linhas, posicao_autor
        )
        view.mensagem_original = interaction

        # Sem botões quando cabe tudo em uma página.
        if view.total_paginas == 1:
            await interaction.followup.send(embed=view.montar_embed())
            return

        await interaction.followup.send(embed=view.montar_embed(), view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ranking(bot))
