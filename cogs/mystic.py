
import random

import discord
from discord import app_commands
from discord.ext import commands


class Mystic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="bola8",
        description="Consulte a misteriosa Bola 8.",
    )
    @app_commands.describe(
        pergunta="Faça uma pergunta que possa ser respondida com sim ou não."
    )
    async def bola8(
        self,
        interaction: discord.Interaction,
        pergunta: str,
    ):
        respostas = [
            "🔮 Sim.",
            "🔮 Não.",
            "✨ Definitivamente sim!",
            "💀 Definitivamente não!",
            "🌙 Talvez. O futuro ainda está em movimento.",
            "🔮 Os sinais apontam para sim.",
            "🌑 Os sinais apontam para não.",
            "👁️ Não consigo enxergar essa resposta.",
            "🌀 Pergunte novamente mais tarde.",
            "⚡ As chances são maiores do que você imagina.",
            "🕯️ Não conte com isso.",
            "💫 Tudo indica que sim.",
            "☠️ Meu silêncio já é uma resposta.",
            "🔮 O destino ainda não decidiu.",
        ]

        embed = discord.Embed(
            title="🔮 BOLA 8 MÍSTICA",
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="Sua pergunta",
            value=pergunta[:1024],
            inline=False,
        )
        embed.add_field(
            name="Resposta do além",
            value=random.choice(respostas),
            inline=False,
        )
        embed.set_footer(text="SHAGGY MYSTIC • O futuro é incerto.")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="tarot",
        description="Tire uma carta de tarot fictícia.",
    )
    @app_commands.describe(
        pergunta="Pergunta ou assunto para sua leitura."
    )
    async def tarot(
        self,
        interaction: discord.Interaction,
        pergunta: str,
    ):
        cartas = [
            (
                "O Louco",
                "Novos caminhos surgem. Arriscar pode ser necessário, "
                "mas não confunda coragem com imprudência.",
            ),
            (
                "O Mago",
                "Você tem ferramentas para agir. Transforme intenção "
                "em atitude.",
            ),
            (
                "A Sacerdotisa",
                "Nem toda resposta está disponível agora. Observe "
                "os detalhes e escute sua intuição.",
            ),
            (
                "A Torre",
                "Uma estrutura pode precisar ruir para que algo "
                "mais sólido seja construído.",
            ),
            (
                "A Lua",
                "Há dúvidas, ilusões ou informações incompletas. "
                "Evite tirar conclusões precipitadas.",
            ),
            (
                "A Estrela",
                "Esperança, renovação e recuperação. Continue "
                "avançando sem exigir resultados imediatos.",
            ),
            (
                "A Morte",
                "Uma fase se encerra. A mudança pode abrir espaço "
                "para algo novo.",
            ),
            (
                "O Sol",
                "Clareza, energia e crescimento. Aproveite o momento "
                "para agir com confiança.",
            ),
            (
                "O Eremita",
                "Diminua o ruído externo e procure compreender "
                "o que realmente importa para você.",
            ),
            (
                "A Roda da Fortuna",
                "As circunstâncias mudam. Adapte-se em vez de tentar "
                "controlar tudo.",
            ),
            (
                "O Diabo",
                "Observe hábitos, desejos ou dependências que "
                "podem estar limitando suas escolhas.",
            ),
            (
                "O Mundo",
                "Conclusão de ciclo, integração e possibilidade "
                "de começar uma nova etapa.",
            ),
        ]

        nome, significado = random.choice(cartas)

        embed = discord.Embed(
            title=f"🃏 Sua carta: {nome}",
            description=significado,
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="Sua questão",
            value=pergunta[:1024],
            inline=False,
        )
        embed.set_footer(
            text="SHAGGY MYSTIC • Leitura simbólica para entretenimento."
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="destino",
        description="Descubra uma mensagem aleatória do destino.",
    )
    async def destino(self, interaction: discord.Interaction):
        mensagens = [
            "Uma oportunidade pode surgir de onde você menos espera.",
            "Nem toda porta fechada precisa ser aberta.",
            "Hoje é um bom dia para terminar algo que você começou.",
            "Uma conversa pode mudar sua perspectiva.",
            "Não confunda pressa com progresso.",
            "O inesperado também pode ser o começo de algo bom.",
            "Às vezes, recuar é uma forma de se preparar.",
            "Você não precisa resolver tudo de uma vez.",
            "Preste atenção naquilo que você vem ignorando.",
            "Uma escolha pequena pode mudar o rumo do seu dia.",
            "O silêncio também pode trazer respostas.",
            "Talvez seja hora de abandonar uma velha ideia.",
        ]

        embed = discord.Embed(
            title="🌌 MENSAGEM DO DESTINO",
            description=random.choice(mensagens),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="O futuro não está escrito.")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="sonho",
        description="Receba uma interpretação simbólica de um sonho.",
    )
    @app_commands.describe(
        relato="Descreva brevemente o sonho que você teve."
    )
    async def sonho(
        self,
        interaction: discord.Interaction,
        relato: str,
    ):
        interpretacoes = [
            "Pode simbolizar mudanças, transições ou o desejo de "
            "deixar algo para trás.",
            "Pode refletir insegurança, pressão ou a sensação de "
            "estar diante de algo desconhecido.",
            "Talvez represente desejos, lembranças ou emoções que "
            "merecem mais atenção.",
            "Pode estar relacionado à forma como você lida com "
            "controle, liberdade e responsabilidade.",
            "Talvez seja uma maneira de sua mente reorganizar "
            "experiências recentes.",
            "Pode simbolizar um conflito interno ou duas vontades "
            "que parecem incompatíveis.",
            "Talvez represente a necessidade de descanso, segurança "
            "ou reconexão consigo mesmo.",
        ]

        embed = discord.Embed(
            title="🌙 INTERPRETADOR DE SONHOS",
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="Seu sonho",
            value=relato[:1024],
            inline=False,
        )
        embed.add_field(
            name="Interpretação simbólica",
            value=random.choice(interpretacoes),
            inline=False,
        )
        embed.set_footer(
            text="Interpretação criativa, não uma análise psicológica."
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @app_commands.command(
        name="pressagio",
        description="Receba um presságio sombrio e misterioso.",
    )
    async def pressagio(self, interaction: discord.Interaction):
        pressagios = [
            "🕯️ Uma chama se apagará antes que a noite termine.",
            "👁️ Alguém perceberá aquilo que você tentou esconder.",
            "🌫️ Nem todo caminho que desaparece está perdido.",
            "🪞 Cuidado com as respostas que refletem exatamente "
            "aquilo que você deseja ouvir.",
            "🐦 Três sinais passarão despercebidos antes do quarto.",
            "🌑 Quando tudo parecer quieto, preste atenção ao silêncio.",
            "⏳ Algo esquecido voltará à sua memória.",
            "🔔 Você ouvirá algo familiar em um lugar inesperado.",
            "🗝️ Uma pergunta antiga encontrará uma nova fechadura.",
            "🌀 Nem tudo que retorna deseja ser encontrado.",
        ]

        embed = discord.Embed(
            title="👁️ PRESSÁGIO",
            description=random.choice(pressagios),
            color=discord.Color.dark_red(),
        )
        embed.set_footer(text="SHAGGY MYSTIC • As sombras observam.")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="ritual",
        description="Gere um ritual fictício para sua história ou RPG.",
    )
    async def ritual(self, interaction: discord.Interaction):
        objetos = [
            "uma vela roxa",
            "um espelho coberto por um pano",
            "três moedas antigas",
            "um papel com um símbolo inventado",
            "uma pedra encontrada durante uma caminhada",
            "um sino pequeno",
        ]

        locais = [
            "em uma biblioteca abandonada",
            "sob a luz da lua",
            "diante de uma porta fechada",
            "no centro de um círculo desenhado no papel",
            "em uma sala silenciosa",
            "perto de uma janela aberta",
        ]

        etapas = [
            "Escreva uma pergunta e dobre o papel três vezes.",
            "Observe o objeto escolhido e invente uma história para ele.",
            "Dê um nome ao que você deseja encontrar em sua narrativa.",
            "Descreva um sinal que marcaria o início do ritual.",
            "Crie uma frase curta que represente a intenção da cerimônia.",
            "Finalize imaginando como o ambiente mudaria depois do ritual.",
        ]

        embed = discord.Embed(
            title="🕯️ GERADOR DE RITUAIS FICTÍCIOS",
            description=(
                "Um ritual para histórias, campanhas de RPG e "
                "construção de atmosfera."
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="Objeto simbólico",
            value=random.choice(objetos),
            inline=False,
        )
        embed.add_field(
            name="Cenário",
            value=random.choice(locais),
            inline=False,
        )
        embed.add_field(
            name="Etapa narrativa",
            value=random.choice(etapas),
            inline=False,
        )
        embed.set_footer(
            text="Ficção e interpretação narrativa; não é um ritual real."
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Mystic(bot))
