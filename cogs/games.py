
import asyncio
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands


log = logging.getLogger("shaggy.games")


# ============================================================
# RECOMPENSAS (ajuste o equilíbrio aqui)
# ============================================================
# XP é a recompensa comum; Abysmus é RARO (só em vitórias, com chance baixa).
# Cada valor de XP é um intervalo (mín, máx) sorteado a cada recompensa.

# Anti-farm: depois de receber uma recompensa de jogo, o membro precisa
# esperar este tempo (em segundos) para receber outra. Os jogos continuam
# funcionando normalmente; só não pagam durante o intervalo.
RECOMPENSA_COOLDOWN_SEGUNDOS = 45

# jogo -> {resultado: (xp_min, xp_max, chance_de_abysmus)}
RECOMPENSAS_JOGOS = {
    "roleta_russa":        {"vitoria": (4, 8, 0.010), "derrota": (0, 0, 0.0)},
    "moeda":               {"vitoria": (1, 3, 0.003), "derrota": (0, 0, 0.0)},
    "pedra_papel_tesoura": {"vitoria": (6, 12, 0.015), "empate": (2, 3, 0.0), "derrota": (1, 2, 0.0)},
    "par_ou_impar":        {"vitoria": (6, 12, 0.015), "derrota": (1, 2, 0.0)},
    "duelo_numerico":      {"vitoria": (7, 14, 0.020), "empate": (2, 4, 0.0), "derrota": (1, 2, 0.0)},
    "duelo_elemental":     {"vitoria": (6, 12, 0.015), "empate": (2, 3, 0.0), "derrota": (1, 2, 0.0)},
    # Acertar 1 entre 5 é difícil: paga mais.
    "adivinhar_escolha":   {"vitoria": (15, 25, 0.050), "derrota": (1, 2, 0.0)},
    "sorte_ou_caos":       {"vitoria": (5, 10, 0.010), "derrota": (1, 2, 0.0)},
}

# /dado: só vale recompensa tirar o número máximo (crítico) em dados grandes.
DADO_FACES_MINIMAS_RECOMPENSA = 20
DADO_CRITICO_XP = (10, 20)
DADO_CRITICO_CHANCE_ABYSMUS = 0.03
DADO_PARTICIPACAO_XP = (1, 2)


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id, user_id) -> instante da última recompensa de jogo.
        self._ultima_recompensa: dict[tuple[int, int], float] = {}

    # =========================
    # RECOMPENSAS (XP e Abysmus raro)
    # =========================

    async def recompensar(
        self,
        interaction: discord.Interaction,
        jogo: str,
        resultado: str,
    ) -> str:
        """
        Concede a recompensa do jogo via cog XpAndCoins e devolve uma linha
        de texto para anexar à resposta ("" se não houve recompensa).
        Nunca lança erro: se o sistema de XP estiver indisponível, o jogo
        simplesmente segue sem recompensa.
        """
        faixa = RECOMPENSAS_JOGOS.get(jogo, {}).get(resultado)
        if faixa is None:
            return ""
        return await self._pagar(interaction, jogo, faixa)

    async def _pagar(
        self,
        interaction: discord.Interaction,
        origem: str,
        faixa: tuple[int, int, float],
    ) -> str:
        xp_min, xp_max, chance_abysmus = faixa

        # Recompensas dependem do servidor (XP e saldo são por servidor).
        if interaction.guild_id is None:
            return ""

        xp = random.randint(xp_min, xp_max) if xp_max > 0 else 0
        abysmus = 1 if random.random() < chance_abysmus else 0
        if xp <= 0 and abysmus <= 0:
            return ""

        chave = (interaction.guild_id, interaction.user.id)
        agora = time.monotonic()
        if agora - self._ultima_recompensa.get(chave, -1e9) < RECOMPENSA_COOLDOWN_SEGUNDOS:
            return ""

        cog = self.bot.get_cog("XpAndCoins")
        if cog is None:
            return ""

        try:
            r = await asyncio.to_thread(
                cog.conceder_recompensas,
                interaction.guild_id,
                interaction.user.id,
                xp=xp,
                coins=abysmus,
                origem=f"games:{origem}",
            )
        except Exception:
            log.exception("Falha ao conceder recompensa do jogo %s.", origem)
            return ""

        self._ultima_recompensa[chave] = agora

        partes = []
        if xp:
            partes.append(f"✨ **+{xp} XP**")
        if abysmus:
            partes.append("🪙 **+1 Abysmus raro!**")
        if r.nivel > r.nivel_antes:
            texto_nivel = f"🏆 **Nível {r.nivel}!**"
            if r.coins_por_nivel:
                texto_nivel += f" (+{r.coins_por_nivel} 🪙)"
            partes.append(texto_nivel)
        return " • ".join(partes)

    @staticmethod
    def anexar(embed: discord.Embed, linha: str) -> discord.Embed:
        """Adiciona a linha de recompensa ao final da descrição do embed."""
        if linha:
            embed.description = f"{embed.description}\n\n{linha}"
        return embed

    # =========================
    # ROLETA RUSSA VIRTUAL
    # =========================

    @app_commands.command(
        name="roleta_russa",
        description="Jogue uma rodada de roleta russa virtual.",
    )
    async def roleta_russa(
        self,
        interaction: discord.Interaction,
    ):
        resultado = random.randint(1, 6)

        if resultado == 1:
            mensagem = "💥 **BANG!** Você perdeu esta rodada!"
            desfecho = "derrota"
        else:
            mensagem = (
                "🔫 *Click...* Você sobreviveu à rodada virtual! "
                f"({resultado}/6)"
            )
            desfecho = "vitoria"

        linha = await self.recompensar(interaction, "roleta_russa", desfecho)
        if linha:
            mensagem += f"\n{linha}"

        await interaction.response.send_message(mensagem)

    # =========================
    # CARA OU COROA
    # =========================

    @app_commands.command(
        name="moeda",
        description="Jogue uma moeda: cara ou coroa.",
    )
    async def moeda(self, interaction: discord.Interaction):
        resultado = random.choice(["Cara", "Coroa"])

        # Cara e coroa são equilíbrio puro: só "cara" rende a pequena
        # recompensa, para o jogo não pagar 100% das vezes.
        desfecho = "vitoria" if resultado == "Cara" else "derrota"
        linha = await self.recompensar(interaction, "moeda", desfecho)

        mensagem = f"🪙 A moeda girou... **{resultado}!**"
        if linha:
            mensagem += f"\n{linha}"

        await interaction.response.send_message(mensagem)

    # =========================
    # DADO PERSONALIZADO
    # =========================

    @staticmethod
    def rolar_dado(faces: int) -> int:
        return random.randint(1, faces)

    @app_commands.command(
        name="dado",
        description="Role um dado com o número de faces que quiser.",
    )
    @app_commands.describe(
        faces="Número de faces do dado (2 a 1000000)"
    )
    @app_commands.checks.cooldown(
        5,
        10,
        key=lambda interaction: interaction.user.id,
    )
    async def dado(
        self,
        interaction: discord.Interaction,
        faces: app_commands.Range[int, 2, 1_000_000],
    ):
        resultado = self.rolar_dado(faces)

        # Só dados grandes pagam, e a recompensa forte é o crítico (tirar o
        # número máximo). Isso impede farmar com d2 / d3.
        linha = ""
        mensagem = f"🎲 **d{faces}**: você tirou **{resultado}**!"
        if faces >= DADO_FACES_MINIMAS_RECOMPENSA:
            if resultado == faces:
                mensagem += " 💥 **CRÍTICO!**"
                linha = await self._pagar(
                    interaction,
                    "dado_critico",
                    (*DADO_CRITICO_XP, DADO_CRITICO_CHANCE_ABYSMUS),
                )
            else:
                linha = await self._pagar(
                    interaction,
                    "dado",
                    (*DADO_PARTICIPACAO_XP, 0.0),
                )
        if linha:
            mensagem += f"\n{linha}"

        await interaction.response.send_message(mensagem)

    @dado.error
    async def dado_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            mensagem = (
                f"Espere {error.retry_after:.1f} segundos "
                "antes de rolar outro dado."
            )
        else:
            logging.error(
                "Erro no comando /dado",
                exc_info=(
                    type(error),
                    error,
                    error.__traceback__,
                ),
            )
            mensagem = "Ocorreu um erro ao rolar o dado."

        if interaction.response.is_done():
            await interaction.followup.send(
                mensagem,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                mensagem,
                ephemeral=True,
            )


    @app_commands.command(
        name="ideia_rpg",
        description="Gere uma aventura de RPG completa com ganchos, NPCs, pistas e reviravoltas.",
    )
    @app_commands.describe(
        tema="Gênero principal da aventura.",
        jogadores="Quantidade de jogadores do grupo.",
        formato="A duração planejada da aventura.",
    )
    @app_commands.choices(
        tema=[
            app_commands.Choice(name="🎲 Aleatório", value="aleatorio"),
            app_commands.Choice(name="Terror cósmico", value="terror cósmico"),
            app_commands.Choice(name="Fantasia sombria", value="fantasia sombria"),
            app_commands.Choice(name="Mistério e investigação", value="mistério"),
            app_commands.Choice(name="Aventura e exploração", value="aventura"),
            app_commands.Choice(name="Sobrevivência", value="sobrevivência"),
            app_commands.Choice(name="Comédia caótica", value="comédia caótica"),
            app_commands.Choice(name="Pós-apocalipse", value="pós-apocalipse"),
            app_commands.Choice(name="Ficção científica", value="ficção científica"),
            app_commands.Choice(name="Horror sobrenatural", value="horror sobrenatural"),
            app_commands.Choice(name="Intriga política", value="intriga política"),
            app_commands.Choice(name="Piratas e mares", value="piratas e mares"),
            app_commands.Choice(name="Faroeste estranho", value="faroeste estranho"),
            app_commands.Choice(name="Folclore brasileiro", value="folclore brasileiro"),
        ],
        formato=[
            app_commands.Choice(name="One-shot (uma sessão)", value="one-shot"),
            app_commands.Choice(name="Mini campanha (3–5 sessões)", value="mini campanha"),
            app_commands.Choice(name="Campanha longa", value="campanha longa"),
        ],
    )
    async def ideia_rpg(
        self,
        interaction: discord.Interaction,
        tema: str = "aleatorio",
        jogadores: app_commands.Range[int, 1, 12] = 4,
        formato: str = "one-shot",
    ):
        ideias = {
            "terror cósmico": {
                "locais": [
                    "uma vila onde ninguém projeta sombra",
                    "um farol que ilumina lugares que ainda não existem",
                    "uma floresta que muda de posição durante a noite",
                    "um navio encontrado navegando sem tripulação",
                    "um observatório que registra estrelas desconhecidas",
                    "um sanatório onde os pacientes sonham a mesma cidade",
                    "uma aldeia construída ao redor de um buraco que sussurra nomes",
                    "uma estação de rádio que transmite vozes de pessoas ainda vivas",
                ],
                "missoes": [
                    "descobrir por que todos os moradores sonham com a mesma criatura",
                    "encontrar uma pessoa apagada da memória de todos",
                    "impedir que uma estrela desapareça do céu",
                    "investigar uma transmissão que prevê a morte de quem a escuta",
                    "recuperar páginas arrancadas de um livro que descreve o futuro",
                    "descobrir por que os mortos começaram a aparecer em fotografias recentes",
                ],
                "ameacas": [
                    "uma entidade que imita perfeitamente pessoas desaparecidas",
                    "um culto que acredita estar impedindo o fim do mundo",
                    "uma presença que altera as lembranças dos personagens",
                    "uma criatura que só existe quando ninguém está olhando",
                    "um pesquisador que abriu algo impossível de fechar",
                    "uma cidade inteira que tenta convencer os visitantes de que eles nasceram ali",
                ],
                "reviravoltas": [
                    "os personagens já estiveram naquele lugar, mas perderam essa memória",
                    "a entidade está tentando fugir de algo ainda pior",
                    "o responsável pelos acontecimentos está morto há décadas",
                    "resolver o mistério pode libertar aquilo que estava preso",
                    "a criatura está repetindo um desastre que ainda não aconteceu",
                    "a pessoa que contratou o grupo é uma lembrança compartilhada",
                ],
            },
            "fantasia sombria": {
                "locais": [
                    "um castelo construído dentro do esqueleto de um gigante",
                    "uma cidade onde a magia é cobrada em anos de vida",
                    "um reino governado por uma rainha sem rosto",
                    "uma catedral enterrada sob um lago negro",
                    "uma fronteira onde a noite dura seis meses",
                    "um mercado que vende nomes, memórias e destinos",
                    "uma fortaleza cujos soldados renascem sem reconhecer uns aos outros",
                    "uma floresta onde cada árvore cresce sobre um túmulo real",
                ],
                "missoes": [
                    "recuperar uma coroa que escolhe quem deve morrer",
                    "escoltar um herdeiro que não pode conhecer sua identidade",
                    "quebrar uma maldição sem revelar quem a lançou",
                    "roubar um livro que reescreve o passado",
                    "encontrar a última pessoa capaz de matar um imortal",
                    "negociar uma trégua entre duas casas que compartilham o mesmo cadáver ancestral",
                ],
                "ameacas": [
                    "cavaleiros que não conseguem morrer",
                    "um santo que transforma fiéis em estátuas",
                    "uma nobreza que se alimenta das lembranças dos pobres",
                    "um dragão que oferece desejos em troca de segredos",
                    "uma ordem de inquisidores que caça qualquer pessoa sem sombra",
                    "um herdeiro que controla os monstros, mas perde uma lembrança a cada ordem",
                ],
                "reviravoltas": [
                    "o vilão está mantendo uma ameaça maior adormecida",
                    "a maldição protege justamente quem parece vítima",
                    "o artefato reconhece um dos personagens como seu antigo dono",
                    "a vitória exige decidir quem ficará com o poder conquistado",
                    "o reino só existe porque alguém está preso sustentando sua realidade",
                    "o monstro tem sido o único guardião de uma população que o teme",
                ],
            },
            "mistério": {
                "locais": [
                    "um hotel onde um quarto aparece apenas às 3h",
                    "uma cidade em que todos negam conhecer o prefeito",
                    "um museu com uma exposição que muda diariamente",
                    "uma estação de trem que não consta em nenhum mapa",
                    "um condomínio onde um apartamento não aparece nas plantas",
                    "uma universidade em que um professor consta como morto há cem anos",
                    "um vilarejo onde todos receberam a mesma carta anônima",
                    "um teatro abandonado que continua vendendo ingressos",
                ],
                "missoes": [
                    "investigar um assassinato sem corpo nem vítima identificável",
                    "descobrir quem está enviando cartas escritas pelos personagens",
                    "encontrar a origem de uma sequência de desaparecimentos",
                    "provar que um crime impossível realmente aconteceu",
                    "reconstruir uma noite da qual cada testemunha se lembra de forma diferente",
                    "descobrir quem lucra com uma série de acidentes aparentemente desconexos",
                ],
                "ameacas": [
                    "uma testemunha que muda de identidade a cada depoimento",
                    "um investigador que destrói qualquer pista encontrada",
                    "uma sociedade secreta infiltrada entre pessoas comuns",
                    "um criminoso que parece prever as decisões do grupo",
                    "um falsificador capaz de fabricar provas convincentes",
                    "um suspeito que está tentando ajudar, mas não pode contar a verdade",
                ],
                "reviravoltas": [
                    "todas as testemunhas dizem a verdade, mas em épocas diferentes",
                    "a vítima está investigando os próprios personagens",
                    "a pista mais importante foi criada para incriminar alguém inocente",
                    "o crime ainda não aconteceu",
                    "duas pessoas diferentes acreditam ser a mesma vítima",
                    "o caso foi resolvido antes, mas alguém apagou a solução dos registros",
                ],
            },
            "aventura": {
                "locais": [
                    "uma ilha que surge uma vez a cada cem anos",
                    "uma cidade suspensa por correntes sobre um abismo",
                    "um deserto repleto de navios petrificados",
                    "uma biblioteca construída sobre as costas de uma criatura",
                    "uma cadeia de montanhas que se move durante tempestades",
                    "uma ruína acessível apenas quando dois rios se encontram",
                    "um jardim colossal no qual as estações mudam a cada sala",
                    "uma estrada antiga que termina em lugares diferentes a cada viagem",
                ],
                "missoes": [
                    "encontrar uma relíquia antes de três expedições rivais",
                    "atravessar um território que muda a cada amanhecer",
                    "recuperar um mapa roubado por um explorador lendário",
                    "levar uma mensagem a uma fortaleza sitiada",
                    "resgatar uma equipe perdida que encontrou algo que não deveria",
                    "escoltar uma criatura rara até o último santuário de sua espécie",
                ],
                "ameacas": [
                    "mercenários que conhecem os pontos fracos do grupo",
                    "uma tempestade que persegue os viajantes",
                    "máquinas antigas que confundem exploradores com invasores",
                    "uma fauna territorial que protege as ruínas",
                    "uma equipe rival disposta a sabotar qualquer concorrente",
                    "um guia que conhece o caminho, mas está fugindo de seu passado",
                ],
                "reviravoltas": [
                    "a relíquia é uma pessoa que perdeu a memória",
                    "o mapa mostra caminhos que só aparecem quando alguém se perde",
                    "o contratante quer destruir o objetivo da expedição",
                    "a fortaleza está sitiada por seus próprios defensores",
                    "a equipe rival está tentando impedir uma catástrofe",
                    "o tesouro é uma chave e alguém já começou a abrir a fechadura",
                ],
            },
            "sobrevivência": {
                "locais": [
                    "uma estação de pesquisa isolada pela neve",
                    "uma floresta coberta por cinzas",
                    "um abrigo subterrâneo com oxigênio limitado",
                    "uma vila cercada por uma névoa que adoece quem a atravessa",
                    "um arquipélago depois de uma maré impossível",
                    "uma cidade sem energia onde os elevadores continuam funcionando",
                    "um comboio preso numa estrada tomada pela vegetação",
                    "uma região em que a água potável provoca sonhos compartilhados",
                ],
                "missoes": [
                    "encontrar água potável antes do próximo amanhecer",
                    "reparar um transmissor sem atrair algo que ronda o abrigo",
                    "escolher quem poderá entrar em um refúgio com poucas vagas",
                    "recuperar medicamentos em uma zona abandonada",
                    "transportar um gerador antes que a última bateria acabe",
                    "descobrir por que os suprimentos estão desaparecendo durante a noite",
                ],
                "ameacas": [
                    "uma criatura que aprende com cada encontro",
                    "um grupo de sobreviventes que esconde seus estoques",
                    "uma doença cujos sintomas desaparecem antes de piorar",
                    "o próprio ambiente, que muda de forma imprevisível",
                    "um líder que controla o acesso aos recursos essenciais",
                    "um sinal de socorro que atrai predadores cada vez mais próximos",
                ],
                "reviravoltas": [
                    "o pedido de socorro veio de dentro do próprio abrigo",
                    "os recursos encontrados pertencem a alguém que ainda está vivo",
                    "o local seguro só permanece seguro enquanto ninguém dorme",
                    "a ameaça está fugindo dos personagens, não os perseguindo",
                    "o abrigo foi construído para manter algo do lado de dentro",
                    "a única rota de fuga exige abandonar o recurso mais valioso do grupo",
                ],
            },
            "comédia caótica": {
                "locais": [
                    "uma taverna administrada por um dragão desempregado",
                    "um reino onde disputas legais são resolvidas em duelos de dança",
                    "uma masmorra que exige ingresso e avaliação dos visitantes",
                    "um vilarejo governado por um pombo com poderes mágicos",
                    "uma guilda que perdeu todos os formulários de suas missões",
                    "uma feira interdimensional com fiscalização extremamente rígida",
                    "um castelo em que todos os móveis têm opiniões políticas",
                    "uma cidade onde a gravidade funciona por votação popular",
                ],
                "missoes": [
                    "devolver um artefato que transforma insultos em profecias",
                    "resgatar um rei que fugiu para não participar de uma reunião",
                    "impedir uma guerra causada por um erro de tradução",
                    "entregar um pacote que ninguém admite ter encomendado",
                    "vencer um concurso culinário para impedir um golpe de Estado",
                    "encontrar o funcionário que carimbou a existência de um deus falso",
                ],
                "ameacas": [
                    "um mago que só consegue conjurar objetos inúteis",
                    "uma guilda de aventureiros extremamente burocrática",
                    "um monstro que exige críticas construtivas antes de lutar",
                    "um impostor que é, por acidente, melhor que o herói original",
                    "um vilão que revela seu plano sempre que alguém o interrompe",
                    "um exército de patos treinados para cobrar pedágio",
                ],
                "reviravoltas": [
                    "o destino do reino depende de uma receita de bolo",
                    "o vilão está tentando devolver o dinheiro que roubou",
                    "o artefato era apenas uma lembrancinha turística",
                    "o grupo foi contratado por engano, mas é a única equipe disponível",
                    "o apocalipse foi agendado para um feriado e ninguém quer trabalhar",
                    "o NPC mais incompetente é o único que leu o manual correto",
                ],
            },
            "pós-apocalipse": {
                "locais": [
                    "um shopping convertido em cidade-estado",
                    "uma metrópole dividida por muralhas feitas de veículos",
                    "uma fazenda que cultiva plantas capazes de filtrar radiação",
                    "um bunker onde o calendário está parado há trinta anos",
                    "uma zona de chuva metálica que cobre as ruínas",
                    "um trem blindado que nunca para na mesma estação",
                ],
                "missoes": [
                    "negociar combustível antes que duas comunidades entrem em guerra",
                    "recuperar dados sobre a origem do colapso",
                    "escoltar uma criança que conhece uma rota segura",
                    "reativar uma torre que pode avisar sobre tempestades tóxicas",
                    "descobrir quem está contaminando os reservatórios",
                    "decidir o destino de uma máquina capaz de restaurar uma região inteira",
                ],
                "ameacas": [
                    "saqueadores que usam sinais falsos de emergência",
                    "uma milícia que controla a água potável",
                    "máquinas autônomas que ainda cumprem ordens antigas",
                    "uma mutação que reage à luz e ao som",
                    "uma comunidade que considera qualquer forasteiro uma ameaça",
                    "um fenômeno ambiental que se aproxima mais rápido do que o previsto",
                ],
                "reviravoltas": [
                    "o colapso foi acelerado para esconder uma descoberta",
                    "a comunidade inimiga protege os últimos especialistas vivos",
                    "a cura exige destruir a fonte de energia da cidade",
                    "o mapa seguro foi alterado para proteger um segredo",
                    "a máquina salvadora depende de uma escolha moral irreversível",
                    "o suposto abrigo é uma instalação de observação abandonada",
                ],
            },
            "ficção científica": {
                "locais": [
                    "uma nave geracional onde ninguém acredita estar no espaço",
                    "uma colônia em que as memórias são armazenadas em cristais",
                    "uma estação orbital que recebe mensagens de si mesma",
                    "um planeta cuja noite dura décadas",
                    "um laboratório onde clones têm direitos legais diferentes",
                    "um elevador espacial tomado por uma greve de robôs",
                ],
                "missoes": [
                    "descobrir por que a inteligência artificial alterou a rota",
                    "recuperar uma amostra antes que a quarentena falhe",
                    "negociar com uma espécie que se comunica por gravidade",
                    "investigar um salto temporal que apagou uma equipe",
                    "impedir que um satélite execute uma ordem obsoleta",
                    "escoltar uma consciência digital até um corpo compatível",
                ],
                "ameacas": [
                    "uma IA que protege a tripulação contra a vontade dela",
                    "um organismo que copia tecnologia e comportamento",
                    "uma corporação que patenteou os corpos de seus funcionários",
                    "um comandante que recebe ordens de uma versão futura de si mesmo",
                    "um enxame de drones que interpreta emoções como ameaças",
                    "uma anomalia que troca causa e consequência",
                ],
                "reviravoltas": [
                    "a missão é uma simulação, mas alguém de fora está interferindo",
                    "a mensagem futura foi enviada por um personagem",
                    "a IA mente para impedir que a tripulação descubra sua mortalidade",
                    "a espécie alienígena está tentando pedir desculpas",
                    "o planeta é artificial e está começando a despertar",
                    "o experimento já aconteceu em milhares de linhas temporais",
                ],
            },
            "horror sobrenatural": {
                "locais": [
                    "uma casa herdada cujos cômodos mudam depois do pôr do sol",
                    "um cemitério onde as lápides registram mortes futuras",
                    "um hospital desativado que mantém um andar iluminado",
                    "uma estrada rural onde o mesmo carro aparece em toda viagem",
                    "um prédio onde todos os espelhos refletem um minuto atrasado",
                    "uma capela onde as velas queimam para baixo",
                ],
                "missoes": [
                    "descobrir a origem de uma voz que chama os moradores pelo nome completo",
                    "encerrar uma sequência de visitas de alguém que já morreu",
                    "encontrar o objeto que mantém uma assombração presa ao local",
                    "proteger uma família durante três noites de manifestações",
                    "investigar um ritual interrompido há gerações",
                    "descobrir por que uma entidade está protegendo uma pessoa específica",
                ],
                "ameacas": [
                    "uma presença que imita a voz de pessoas queridas",
                    "um espírito que não sabe que está morto",
                    "uma maldição ativada por promessas quebradas",
                    "um médium que está escondendo o preço de suas habilidades",
                    "uma entidade que só pode entrar quando é convidada",
                    "um objeto que realiza desejos de maneira literal e cruel",
                ],
                "reviravoltas": [
                    "a assombração está tentando avisar sobre um perigo humano",
                    "o ritual não invocou a entidade: tentou expulsá-la",
                    "o objeto amaldiçoado pertence a um dos personagens",
                    "a família protegeu a entidade por acreditar que ela era um ancestral",
                    "a pessoa desaparecida está mantendo a manifestação sob controle",
                    "o local não é assombrado; é uma prisão sobrenatural",
                ],
            },
            "intriga política": {
                "locais": [
                    "uma corte onde toda promessa vira contrato mágico",
                    "uma cidade-estado prestes a eleger seu primeiro governante popular",
                    "uma embaixada durante um banquete de paz",
                    "um parlamento em que um assento vazio ainda tem voto",
                    "uma fortaleza controlada por três famílias rivais",
                    "um reino em que a sucessão depende de um julgamento público",
                ],
                "missoes": [
                    "impedir um atentado sem revelar a identidade do informante",
                    "provar que um tratado foi adulterado",
                    "escoltar um diplomata que todos querem desacreditar",
                    "descobrir quem financia secretamente os dois lados de uma guerra",
                    "recuperar provas antes da votação decisiva",
                    "negociar uma aliança sem entregar o aliado mais vulnerável",
                ],
                "ameacas": [
                    "um conselheiro que controla os rumores da capital",
                    "uma facção que fabrica crises para justificar o próprio poder",
                    "um espião que trabalha para dois lados e protege um terceiro",
                    "uma família nobre que possui provas contra todos os candidatos",
                    "um líder popular que esconde a origem de sua fortuna",
                    "um acordo que exige sacrificar a reputação de um inocente",
                ],
                "reviravoltas": [
                    "o golpe planejado pretende impedir uma guerra maior",
                    "o informante é a pessoa que mais se beneficia com a investigação",
                    "as provas são autênticas, mas foram obtidas por uma razão falsa",
                    "o candidato favorito quer perder a eleição",
                    "a facção aparentemente unida está dividida em três planos incompatíveis",
                    "a paz depende de tornar pública uma verdade que destruirá o governo",
                ],
            },
            "piratas e mares": {
                "locais": [
                    "um arquipélago que aparece apenas sob lua nova",
                    "um navio fantasma ancorado no meio de um porto movimentado",
                    "uma cidade construída sobre carcaças de leviatãs",
                    "um farol que atrai embarcações para mares impossíveis",
                    "uma ilha onde a maré revela ruínas e esqueletos gigantes",
                    "um mercado flutuante protegido por piratas aposentados",
                ],
                "missoes": [
                    "recuperar um mapa tatuado na pele de um capitão desaparecido",
                    "escoltar um navio sem revelar sua carga",
                    "encontrar uma tripulação perdida em águas proibidas",
                    "roubar uma chave durante um leilão de relíquias",
                    "quebrar uma maldição antes da próxima maré",
                    "impedir que uma frota rival desperte algo no fundo do mar",
                ],
                "ameacas": [
                    "um capitão que não aparece em espelhos",
                    "uma criatura que segue o navio sem jamais emergir",
                    "um almirante que vende proteção aos próprios piratas",
                    "uma tripulação que esquece um membro a cada amanhecer",
                    "uma tempestade que repete as últimas palavras dos afogados",
                    "um motim organizado por alguém que não existe na lista da tripulação",
                ],
                "reviravoltas": [
                    "o tesouro é o selo que mantém uma criatura aprisionada",
                    "o capitão procurado está comandando a frota inimiga",
                    "o mapa muda conforme as mentiras contadas por quem o segura",
                    "a tripulação fantasma está tentando devolver algo roubado",
                    "a carga secreta é uma pessoa que não pode tocar em terra",
                    "a ilha desaparece porque alguém está tentando escondê-la dos deuses",
                ],
            },
            "faroeste estranho": {
                "locais": [
                    "uma cidade de mineração onde o ouro sussurra durante a noite",
                    "uma estação ferroviária que recebe trens sem maquinista",
                    "um saloon onde ninguém envelhece enquanto toca música",
                    "um desfiladeiro que devolve tiros antes de serem disparados",
                    "um rancho cercado por pegadas que chegam, mas nunca saem",
                    "uma cidade fantasma que aparece em mapas recentes",
                ],
                "missoes": [
                    "escoltar uma testemunha até um julgamento que talvez não exista",
                    "descobrir quem está roubando anos de vida dos moradores",
                    "recuperar um artefato de um trem blindado",
                    "proteger a cidade durante uma noite sem lua",
                    "encontrar um xerife desaparecido em território proibido",
                    "investigar uma série de duelos em que ninguém se lembra do vencedor",
                ],
                "ameacas": [
                    "um pistoleiro que sempre chega antes de ser contratado",
                    "uma companhia ferroviária que compra cidades e suas memórias",
                    "um pregador que promete ressuscitar os mortos por um preço",
                    "uma criatura que imita cavalos e chama pelo nome dos viajantes",
                    "um bando que rouba sombras em vez de dinheiro",
                    "um xerife que prende pessoas por crimes que ainda não cometeram",
                ],
                "reviravoltas": [
                    "o fora da lei está protegendo a cidade do verdadeiro criminoso",
                    "o ouro é composto por memórias solidificadas",
                    "o trem transporta a cidade para uma época diferente a cada viagem",
                    "o xerife desaparecido assumiu outra identidade para conter a ameaça",
                    "o duelo decisivo já aconteceu em um ciclo temporal anterior",
                    "a cidade fantasma é a versão futura da cidade atual",
                ],
            },
            "folclore brasileiro": {
                "locais": [
                    "um vilarejo ribeirinho onde os barcos voltam com passageiros a mais",
                    "uma mata em que as trilhas mudam depois do canto dos pássaros",
                    "uma estrada de terra onde faróis seguem os viajantes sem veículo algum",
                    "uma fazenda antiga cercada por árvores marcadas com símbolos",
                    "um mercado noturno que só abre durante tempestades",
                    "uma comunidade onde ninguém pronuncia o nome do rio",
                    "uma estação ferroviária abandonada tomada por neblina vermelha",
                    "um quilombo fictício protegido por um pacto antigo com a mata",
                ],
                "missoes": [
                    "encontrar uma pessoa que seguiu uma luz e voltou sem reconhecer a família",
                    "investigar animais que aparecem com marcas humanas",
                    "recuperar um objeto ritual antes de uma noite de tempestade",
                    "descobrir por que os moradores esqueceram uma antiga celebração",
                    "proteger uma comunidade de uma presença que imita vozes conhecidas",
                    "seguir rastros impossíveis até uma clareira que não consta em mapas",
                ],
                "ameacas": [
                    "uma criatura que confunde caçadores e protetores da mata",
                    "um encantado que cobra uma promessa esquecida",
                    "um grupo que explora um lugar sagrado sem compreender suas consequências",
                    "uma presença que apaga os caminhos por onde passa",
                    "um espírito ligado a um crime antigo nunca reconhecido",
                    "um fenômeno que mistura lembranças, sonho e realidade",
                ],
                "reviravoltas": [
                    "a entidade está defendendo o território de uma ameaça humana",
                    "a pessoa desaparecida escolheu ficar para cumprir uma promessa",
                    "o objeto procurado é uma proteção, não uma arma",
                    "a lenda local foi alterada para esconder um acontecimento real",
                    "o suposto monstro está tentando devolver algo roubado da comunidade",
                    "a solução exige reparar um dano, não derrotar uma criatura",
                ],
            },
        }

        tema_final = tema
        if tema_final == "aleatorio" or tema_final not in ideias:
            tema_final = random.choice(list(ideias.keys()))

        banco = ideias[tema_final]
        local = random.choice(banco["locais"])
        missao = random.choice(banco["missoes"])
        ameaca = random.choice(banco["ameacas"])
        reviravolta = random.choice(banco["reviravoltas"])

        contratantes = [
            "uma cartógrafa que apagou o próprio nome dos registros",
            "um veterano que se recusa a explicar como sobreviveu",
            "uma criança que entrega pagamento em moedas de uma era futura",
            "uma autoridade respeitada com uma testemunha escondida",
            "um desconhecido que sabe o nome de todos os personagens",
            "um comerciante que oferece informação em vez de dinheiro",
            "uma pessoa desaparecida que voltou sem envelhecer",
            "um rival que precisa cooperar, mas não confia no grupo",
            "um mensageiro ferido carregando uma ordem contraditória",
            "um aliado que admite estar mentindo, mas não revela sobre o quê",
        ]
        pistas = [
            "um registro oficial tem uma data impossível",
            "um objeto foi limpo enquanto todo o ambiente está coberto de poeira",
            "duas testemunhas descrevem o mesmo detalhe com palavras idênticas",
            "uma pegada termina no meio de uma superfície intacta",
            "um símbolo aparece em lugares sem qualquer ligação aparente",
            "uma gravação contém uma voz que ninguém ouviu ao vivo",
            "um mapa marca um lugar que não existe mais",
            "uma testemunha lembra de um acontecimento que ainda não ocorreu",
            "um item comum está guardado como se fosse uma relíquia",
            "uma informação verdadeira foi colocada no lugar errado de propósito",
        ]
        complicacoes = [
            "um aliado está escondendo uma informação importante",
            "o prazo é menor do que os personagens imaginavam",
            "uma escolha simples terá consequências públicas",
            "uma pista contradiz tudo o que o grupo descobriu",
            "o objetivo da missão muda antes da conclusão",
            "dois NPCs oferecem versões incompatíveis dos fatos",
            "o recurso mais importante está nas mãos de um rival",
            "um personagem é confundido com alguém procurado",
            "o grupo precisa decidir entre salvar uma pessoa e preservar a prova",
            "a ameaça reage diretamente às estratégias usadas pelo grupo",
            "o contratante não tem autoridade para cumprir a recompensa prometida",
            "uma vitória imediata cria um problema maior para depois",
        ]
        dilemas = [
            "revelar a verdade pode colocar uma comunidade inteira em perigo",
            "salvar um aliado significa deixar o objetivo escapar por enquanto",
            "a pessoa culpada também é a única capaz de impedir a próxima tragédia",
            "a recompensa exige entregar uma prova que inocentaria outra pessoa",
            "o grupo pode encerrar a ameaça, mas perderá uma informação vital",
            "duas facções têm razões legítimas e não existe acordo sem concessões",
            "a solução mais rápida cobra um preço de alguém que não participou do conflito",
            "manter a promessa original pode causar dano maior do que quebrá-la",
        ]
        recompensas = [
            "um contato influente que pode abrir uma porta no futuro",
            "um mapa com uma região ainda não explorada",
            "um artefato útil cujo funcionamento permanece parcialmente desconhecido",
            "uma dívida de favor de uma facção local",
            "acesso a um esconderijo seguro por tempo limitado",
            "uma informação capaz de mudar a interpretação de uma pista antiga",
            "um recurso raro e difícil de substituir",
            "a confiança de alguém que antes tratava o grupo como inimigo",
            "um documento que comprova uma conspiração maior",
            "uma habilidade, técnica ou ritual que exige estudo para ser dominado",
        ]
        cenas_abertura = [
            "o grupo recebe um pedido de ajuda durante uma situação que já saiu do controle",
            "uma pessoa entrega um objeto aos personagens e desaparece na multidão",
            "um acontecimento público é interrompido por um sinal impossível",
            "o grupo chega exatamente quando todos começam a fugir do local",
            "um conhecido é acusado diante de uma multidão e pede ajuda em silêncio",
            "uma porta trancada se abre para um lugar que não deveria existir",
            "os personagens acordam com uma mensagem que nenhum deles escreveu",
            "um pagamento adiantado chega acompanhado de uma prova de que a missão falhou",
        ]
        npcs = [
            "um aliado leal que toma decisões precipitadas",
            "uma rival cordial que nunca revela todas as suas intenções",
            "uma testemunha medrosa que observou mais do que admite",
            "um especialista brilhante que ignora as consequências práticas",
            "uma autoridade que tenta fazer o certo usando métodos questionáveis",
            "um guia carismático que se perde quando está sob pressão",
            "um antagonista educado que realmente acredita estar salvando vidas",
            "um comerciante oportunista que vende informações verdadeiras pela metade",
        ]

        abertura = random.choice(cenas_abertura)
        contratante = random.choice(contratantes)
        pista = random.choice(pistas)
        complicacao = random.choice(complicacoes)
        dilema = random.choice(dilemas)
        recompensa = random.choice(recompensas)
        npc = random.choice(npcs)

        duracoes = {
            "one-shot": "Uma sessão: apresente o problema rapidamente, revele a pista principal no meio e reserve a cena final para uma decisão difícil.",
            "mini campanha": "3–5 sessões: sessão 1 para o gancho; sessões intermediárias para pistas, alianças e consequências; última sessão para a revelação e o confronto final.",
            "campanha longa": "Campanha longa: transforme a ameaça em um arco inicial, plante duas perguntas sem resposta e conecte a recompensa a uma facção ou mistério maior.",
        }
        estrutura = duracoes.get(formato, duracoes["one-shot"])

        embed = discord.Embed(
            title="🎲 GERADOR AVANÇADO DE AVENTURAS RPG",
            description=(
                f"**Gênero:** {tema_final.title()}\n"
                f"**Grupo:** {jogadores} jogador(es)\n"
                f"**Formato:** {formato.title()}\n\n"
                f"*Uma aventura gerada para servir de ponto de partida ao mestre.*"
            ),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(name="📍 Cenário", value=local, inline=False)
        embed.add_field(name="🎬 Cena de abertura", value=abertura, inline=False)
        embed.add_field(name="📜 Objetivo principal", value=missao, inline=False)
        embed.add_field(name="🧑‍💼 Quem puxa o grupo para a trama", value=contratante, inline=False)
        embed.add_field(name="☠️ Ameaça central", value=ameaca, inline=False)
        embed.add_field(name="🔎 Pista importante", value=pista, inline=False)
        embed.add_field(name="🎭 NPC para interpretar", value=npc, inline=False)
        embed.add_field(name="🌀 Reviravolta possível", value=reviravolta, inline=False)
        embed.add_field(name="⚠️ Complicação", value=complicacao, inline=False)
        embed.add_field(name="⚖️ Dilema moral", value=dilema, inline=False)
        embed.add_field(name="🎁 Recompensa possível", value=recompensa, inline=False)
        embed.add_field(name="🗺️ Estrutura sugerida", value=estrutura, inline=False)
        embed.set_footer(text="SHAGGY RPG • O mestre decide o que é verdade, pista ou armadilha.")

        await interaction.response.send_message(embed=embed)


    # =========================
    # JOGOS DE ESCOLHAS ALEATÓRIAS
    # =========================

    @staticmethod
    def embed_jogo(titulo: str, descricao: str, cor: discord.Color = discord.Color.dark_purple()):
        """Cria um embed padronizado para os minijogos do Shaggy."""
        embed = discord.Embed(title=titulo, description=descricao, color=cor)
        embed.set_footer(text="SHAGGY GAMES • A sorte está lançada.")
        return embed

    @app_commands.command(
        name="pedra_papel_tesoura",
        description="Desafie o Shaggy em pedra, papel e tesoura."
    )
    @app_commands.choices(escolha=[
        app_commands.Choice(name="🪨 Pedra", value="pedra"),
        app_commands.Choice(name="📄 Papel", value="papel"),
        app_commands.Choice(name="✂️ Tesoura", value="tesoura"),
    ])
    async def pedra_papel_tesoura(
        self,
        interaction: discord.Interaction,
        escolha: app_commands.Choice[str],
    ):
        opcoes = ["pedra", "papel", "tesoura"]
        emojis = {"pedra": "🪨", "papel": "📄", "tesoura": "✂️"}
        escolha_usuario = escolha.value
        escolha_shaggy = random.choice(opcoes)

        if escolha_usuario == escolha_shaggy:
            resultado = "🤝 **Empate!** Nem você nem eu temos moral para comemorar."
            cor = discord.Color.gold()
            desfecho = "empate"
        elif (
            (escolha_usuario == "pedra" and escolha_shaggy == "tesoura")
            or (escolha_usuario == "papel" and escolha_shaggy == "pedra")
            or (escolha_usuario == "tesoura" and escolha_shaggy == "papel")
        ):
            resultado = "🏆 **Você venceu!** Tá bom, foi sorte. Na próxima eu volto sério."
            cor = discord.Color.green()
            desfecho = "vitoria"
        else:
            resultado = "👻 **Shaggy venceu!** Eu nem precisei usar 1% do meu poder."
            cor = discord.Color.red()
            desfecho = "derrota"

        linha = await self.recompensar(interaction, "pedra_papel_tesoura", desfecho)

        embed = self.embed_jogo(
            "🪨 Pedra, Papel e Tesoura",
            f"**{interaction.user.display_name}:** {emojis[escolha_usuario]} {escolha_usuario.title()}\n"
            f"**Shaggy:** {emojis[escolha_shaggy]} {escolha_shaggy.title()}\n\n"
            f"{resultado}",
            cor,
        )
        self.anexar(embed, linha)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="par_ou_impar",
        description="Escolha par ou ímpar e dispute uma rodada com o Shaggy."
    )
    @app_commands.choices(paridade=[
        app_commands.Choice(name="Par", value="par"),
        app_commands.Choice(name="Ímpar", value="ímpar"),
    ])
    @app_commands.describe(numero="Escolha um número de 0 a 5.")
    async def par_ou_impar(
        self,
        interaction: discord.Interaction,
        paridade: app_commands.Choice[str],
        numero: app_commands.Range[int, 0, 5],
    ):
        numero_shaggy = random.randint(0, 5)
        soma = numero + numero_shaggy
        resultado_real = "par" if soma % 2 == 0 else "ímpar"
        venceu = paridade.value == resultado_real

        if venceu:
            texto = f"🎉 **Você venceu!** A soma deu {resultado_real}."
            cor = discord.Color.green()
        else:
            texto = f"😈 **Shaggy venceu!** A soma deu {resultado_real}."
            cor = discord.Color.red()

        linha = await self.recompensar(
            interaction, "par_ou_impar", "vitoria" if venceu else "derrota"
        )

        embed = self.embed_jogo(
            "🔢 Par ou Ímpar",
            f"**Sua escolha:** {paridade.value.title()}\n"
            f"**Seu número:** {numero}\n"
            f"**Número do Shaggy:** {numero_shaggy}\n"
            f"**Soma:** {numero} + {numero_shaggy} = **{soma}**\n\n"
            f"{texto}",
            cor,
        )
        self.anexar(embed, linha)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="duelo_numerico",
        description="Escolha um número de 1 a 10; quem chegar mais perto do número-alvo vence."
    )
    @app_commands.describe(numero="Seu palpite, de 1 a 10.")
    async def duelo_numerico(
        self,
        interaction: discord.Interaction,
        numero: app_commands.Range[int, 1, 10],
    ):
        alvo = random.randint(1, 10)
        escolha_shaggy = random.randint(1, 10)
        distancia_usuario = abs(numero - alvo)
        distancia_shaggy = abs(escolha_shaggy - alvo)

        if distancia_usuario < distancia_shaggy:
            resultado = "🏆 **Você venceu!** Seu palpite chegou mais perto."
            cor = discord.Color.green()
            desfecho = "vitoria"
        elif distancia_shaggy < distancia_usuario:
            resultado = "👻 **Shaggy venceu!** Meu instinto aleatório é impecável."
            cor = discord.Color.red()
            desfecho = "derrota"
        else:
            resultado = "🤝 **Empate!** Os dois chegaram à mesma distância."
            cor = discord.Color.gold()
            desfecho = "empate"

        linha = await self.recompensar(interaction, "duelo_numerico", desfecho)

        embed = self.embed_jogo(
            "🎯 Duelo Numérico",
            f"**Número-alvo:** {alvo}\n"
            f"**Seu palpite:** {numero} (distância: {distancia_usuario})\n"
            f"**Palpite do Shaggy:** {escolha_shaggy} (distância: {distancia_shaggy})\n\n"
            f"{resultado}",
            cor,
        )
        self.anexar(embed, linha)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="duelo_elemental",
        description="Escolha um elemento e enfrente a escolha aleatória do Shaggy."
    )
    @app_commands.choices(elemento=[
        app_commands.Choice(name="🔥 Fogo", value="fogo"),
        app_commands.Choice(name="💧 Água", value="água"),
        app_commands.Choice(name="🌿 Planta", value="planta"),
    ])
    async def duelo_elemental(
        self,
        interaction: discord.Interaction,
        elemento: app_commands.Choice[str],
    ):
        elementos = ["fogo", "água", "planta"]
        emojis = {"fogo": "🔥", "água": "💧", "planta": "🌿"}
        vence = {"fogo": "planta", "planta": "água", "água": "fogo"}
        usuario = elemento.value
        shaggy = random.choice(elementos)

        if usuario == shaggy:
            resultado = "🤝 **Empate elemental!** As forças se anularam."
            cor = discord.Color.gold()
            desfecho = "empate"
        elif vence[usuario] == shaggy:
            resultado = "🏆 **Você venceu o duelo elemental!**"
            cor = discord.Color.green()
            desfecho = "vitoria"
        else:
            resultado = "💥 **Shaggy venceu!** Seu elemento foi superado."
            cor = discord.Color.red()
            desfecho = "derrota"

        linha = await self.recompensar(interaction, "duelo_elemental", desfecho)

        embed = self.embed_jogo(
            "⚡ Duelo Elemental",
            f"**Você:** {emojis[usuario]} {usuario.title()}\n"
            f"**Shaggy:** {emojis[shaggy]} {shaggy.title()}\n\n"
            f"{resultado}",
            cor,
        )
        self.anexar(embed, linha)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="adivinhar_escolha",
        description="Tente adivinhar qual opção o Shaggy escolheu aleatoriamente."
    )
    @app_commands.choices(escolha=[
        app_commands.Choice(name="🐺 Lobo", value="lobo"),
        app_commands.Choice(name="🐸 Sapo", value="sapo"),
        app_commands.Choice(name="🦇 Morcego", value="morcego"),
        app_commands.Choice(name="🐈 Gato", value="gato"),
        app_commands.Choice(name="🐍 Serpente", value="serpente"),
    ])
    async def adivinhar_escolha(
        self,
        interaction: discord.Interaction,
        escolha: app_commands.Choice[str],
    ):
        opcoes = ["lobo", "sapo", "morcego", "gato", "serpente"]
        emojis = {"lobo": "🐺", "sapo": "🐸", "morcego": "🦇", "gato": "🐈", "serpente": "🐍"}
        shaggy = random.choice(opcoes)
        usuario = escolha.value

        if usuario == shaggy:
            resultado = "🧠 **Acertou!** Você leu a mente do Shaggy."
            cor = discord.Color.green()
            desfecho = "vitoria"
        else:
            resultado = "❌ **Não foi dessa vez!** Tente prever meu caos na próxima."
            cor = discord.Color.red()
            desfecho = "derrota"

        linha = await self.recompensar(interaction, "adivinhar_escolha", desfecho)

        embed = self.embed_jogo(
            "🔮 Adivinhe a Escolha",
            f"**Sua aposta:** {emojis[usuario]} {usuario.title()}\n"
            f"**Shaggy escolheu:** {emojis[shaggy]} {shaggy.title()}\n\n"
            f"{resultado}",
            cor,
        )
        self.anexar(embed, linha)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="sorte_ou_caos",
        description="Escolha sorte ou caos e descubra o que o Shaggy sorteou."
    )
    @app_commands.choices(escolha=[
        app_commands.Choice(name="🍀 Sorte", value="sorte"),
        app_commands.Choice(name="🌀 Caos", value="caos"),
    ])
    async def sorte_ou_caos(
        self,
        interaction: discord.Interaction,
        escolha: app_commands.Choice[str],
    ):
        sorteio = random.choice(["sorte", "caos"])
        frases = {
            "sorte": "🍀 A sorte sorriu para você. Aproveite enquanto dura.",
            "caos": "🌀 O caos venceu. Honestamente, eu esperava isso.",
        }

        if escolha.value == sorteio:
            resultado = f"🎉 **Você acertou!** {frases[sorteio]}"
            cor = discord.Color.green()
            desfecho = "vitoria"
        else:
            resultado = f"💀 **Você errou!** {frases[sorteio]}"
            cor = discord.Color.red()
            desfecho = "derrota"

        linha = await self.recompensar(interaction, "sorte_ou_caos", desfecho)

        embed = self.embed_jogo(
            "🍀 Sorte ou Caos",
            f"**Sua escolha:** {escolha.value.title()}\n"
            f"**Resultado sorteado:** {sorteio.title()}\n\n"
            f"{resultado}",
            cor,
        )
        self.anexar(embed, linha)
        await interaction.response.send_message(embed=embed)



async def setup(bot: commands.Bot):
    await bot.add_cog(Games(bot))
