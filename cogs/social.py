
import random

import discord
from discord import app_commands
from discord.ext import commands


class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ola",
        description="Dê um oi para o Shaggy.",
    )
    async def ola(self, interaction: discord.Interaction):
        respostas = [
            "E aí! 👻 O Shaggy chegou!",
            "Opa! Como você está? ✨",
            "Salve! Que bom ver você por aqui! 👋",
            "Oi, criatura da internet! 👁️",
            "Alô, alô! O servidor está vivo! 🎉",
        ]
        await interaction.response.send_message(
            random.choice(respostas)
        )

    @app_commands.command(
        name="abracar",
        description="Dê um abraço em alguém.",
    )
    @app_commands.describe(
        membro="Quem vai receber o abraço?"
    )
    async def abracar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
    ):
        if membro.id == interaction.user.id:
            mensagem = (
                f"🫂 {interaction.user.mention} se abraçou. "
                "Amor-próprio também conta!"
            )
        elif membro.bot:
            mensagem = (
                f"🤖 {interaction.user.mention} abraçou "
                f"{membro.mention}. O Shaggy retribui o abraço!"
            )
        else:
            mensagens = [
                "enviou um abraço quentinho para",
                "deu um abraço apertado em",
                "ofereceu um abraço virtual para",
                "abraçou com carinho",
            ]
            mensagem = (
                f"🫂 {interaction.user.mention} "
                f"{random.choice(mensagens)} {membro.mention}!"
            )

        await interaction.response.send_message(mensagem)

    @app_commands.command(
        name="beijar",
        description="Envie um beijo virtual para alguém.",
    )
    @app_commands.describe(
        membro="Quem vai receber o beijo?"
    )
    async def beijar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
    ):
        if membro.id == interaction.user.id:
            mensagem = (
                f"💋 {interaction.user.mention} mandou um beijo "
                "para si mesmo. Autoconfiança!"
            )
        else:
            mensagem = (
                f"💋 {interaction.user.mention} mandou um beijo "
                f"virtual para {membro.mention}!"
            )

        await interaction.response.send_message(mensagem)

    @app_commands.command(
        name="elogiar",
        description="Envie um elogio para alguém.",
    )
    @app_commands.describe(
        membro="Quem merece um elogio?"
    )
    async def elogiar(
        self,
        interaction: discord.Interaction,
        membro: discord.Member,
    ):
        elogios = [
            "tem uma energia incrível! ✨",
            "deixa qualquer conversa mais interessante! 💫",
            "merece reconhecimento pelo que faz! 🌟",
            "tem um ótimo senso de humor! 😂",
            "é uma pessoa especial neste servidor! 💜",
            "tem estilo de protagonista! 🎬",
            "merece um dia cheio de coisas boas! 🌈",
            "faz diferença por aqui! 👻",
        ]

        await interaction.response.send_message(
            f"💌 {interaction.user.mention} disse que "
            f"{membro.mention} {random.choice(elogios)}"
        )

    @app_commands.command(
        name="shippar",
        description="Descubra a compatibilidade fictícia de duas pessoas.",
    )
    @app_commands.describe(
        pessoa1="Primeira pessoa.",
        pessoa2="Segunda pessoa.",
    )
    async def shippar(
        self,
        interaction: discord.Interaction,
        pessoa1: discord.Member,
        pessoa2: discord.Member,
    ):
        porcentagem = random.randint(0, 100)

        if porcentagem < 20:
            resultado = "🌧️ Uma dupla improvável..."
        elif porcentagem < 40:
            resultado = "🌱 Talvez exista uma conexão."
        elif porcentagem < 60:
            resultado = "✨ Uma amizade pode florescer!"
        elif porcentagem < 80:
            resultado = "💖 A química fictícia está aumentando!"
        else:
            resultado = "💘 O fandom já está fazendo edits!"

        barra_cheia = porcentagem // 10
        barra = "❤️" * barra_cheia + "🖤" * (10 - barra_cheia)

        embed = discord.Embed(
            title="💞 SHAGGY SHIP METER",
            description=(
                f"{pessoa1.mention} + {pessoa2.mention}\n\n"
                f"**Compatibilidade fictícia: {porcentagem}%**\n"
                f"{barra}\n\n{resultado}"
            ),
            color=discord.Color.magenta(),
        )
        embed.set_footer(
            text="Só uma brincadeira; não mede sentimentos reais."
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="escolher",
        description="Escolha aleatoriamente alguém do servidor.",
    )
    async def escolher(self, interaction: discord.Interaction):
        membros = [
            membro
            for membro in interaction.guild.members
            if not membro.bot
        ] if interaction.guild else []

        if not membros:
            await interaction.response.send_message(
                "Não consegui encontrar membros para escolher.",
                ephemeral=True,
            )
            return

        escolhido = random.choice(membros)

        await interaction.response.send_message(
            f"🎯 A pessoa escolhida foi {escolhido.mention}!"
        )

    @app_commands.command(
        name="reagir",
        description="Reaja à mensagem com um emoji aleatório.",
    )
    async def reagir(self, interaction: discord.Interaction):
        emojis = [
            "👻", "💀", "❤️", "😂", "🔥",
            "👁️", "✨", "🫂", "🤡", "🌀",
        ]

        await interaction.response.send_message(
            f"{interaction.user.mention}, sua reação é {random.choice(emojis)}!"
        )

    @app_commands.command(
        name="moletom",
        description="Descubra qual seria seu estilo de moletom.",
    )
    async def moletom(self, interaction: discord.Interaction):
        estilos = [
            "🖤 Gótico: preto, correntes e mistério.",
            "🌈 Colorido: impossível passar despercebido.",
            "👻 Sobrenatural: fantasmas e símbolos estranhos.",
            "🎧 Musical: estampas de bandas e estética underground.",
            "🌀 Experimental: glitch, ruído e caos visual.",
            "🐸 Caótico: uma estampa que ninguém consegue explicar.",
        ]

        await interaction.response.send_message(
            f"👕 {interaction.user.mention}, seu estilo seria:\n"
            f"**{random.choice(estilos)}**"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Social(bot))
