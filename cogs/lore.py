"""
LORE — Universo de Jay Moon (Segredo Floresta Adentro, Maré Morta, Inominável)
==============================================================

Comandos (todos começam com /lore — digite "/lore" para ver a lista):

    /lore livros [livro]      Os três livros: SFA, Maré Morta e Inominável
    /lore cosmologia          Drakvu, Malachais, Marjopyia, Inominável e o selo
    /lore alinhamento [qual]  Caótico, Luminária, Natural, Neutro, Independente
    /lore faccao [qual]       As facções conhecidas
    /lore olho                O Olho Metamorfo
    /lore sistema             O sistema de RPG (3d8, Vida e SAN)
    /lore ruptura             O roguelite Ruptura Temporal
    /lore glossario [termo]   Definição rápida de um termo
    /lore lacunas             O que o autor ainda NÃO definiu
    /lore perguntar <texto>   Pergunta livre respondida pela IA (guardião do cânone)

Os comandos de explicação usam texto FIXO baseado no Prompt-Mestre: não
inventam nada. Só o /lore perguntar usa IA, e ela é instruída a separar
CÂNONE, INFERÊNCIA, PROPOSTA e EM ABERTO.

REQUISITOS
----------
- Cog IA (ia.py) carregado: o /lore perguntar reutiliza a conexão dele.
- Opcional: salve o Prompt-Mestre completo em  data/lore_prompt.txt
  (ou ao lado deste arquivo, como lore_prompt.txt). Se o arquivo existir, a
  IA passa a usar o texto inteiro; senão usa o resumo embutido abaixo.

Para corrigir o lore, edite os dicionários abaixo (uma única fonte: os
comandos E o resumo enviado à IA são gerados a partir deles).
"""

import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands


log = logging.getLogger("shaggy.lore")


# ============================================================
# CONFIGURAÇÕES
# ============================================================

COOLDOWN_PERGUNTAR_SEGUNDOS = 30
TIMEOUT_PERGUNTAR_SEGUNDOS = 180
MAX_TOKENS_PERGUNTAR = 900
MAX_CARACTERES_PERGUNTA = 800

# Onde procurar o Prompt-Mestre completo (opcional).
CAMINHOS_PROMPT = [
    Path(__file__).resolve().parent.parent / "data" / "lore_prompt.txt",
    Path(__file__).resolve().parent / "lore_prompt.txt",
    # nome antigo, caso você já tenha salvo o arquivo assim
    Path(__file__).resolve().parent.parent / "data" / "sfa_prompt.txt",
    Path(__file__).resolve().parent / "sfa_prompt.txt",
]

SEM_MENCOES = discord.AllowedMentions.none()

RODAPE = "Universo SFA • criado por Jay Moon"

# Marcadores usados nos textos.
CANONE = "✅"
ABERTO = "🔎"


# ============================================================
# LORE (fonte única) — baseado no Prompt-Mestre do universo SFA
# ============================================================

# (título do campo, texto)
COSMOLOGIA = [
    (
        "🌳 Drakvu — a origem",
        "A origem de tudo está ligada à árvore primordial Drakvu, da qual "
        "emergiram as entidades fundamentais. Ela antecede a realidade "
        "organizada que os personagens conhecem.\n"
        f"{ABERTO} Sua natureza exata (entidade, princípio ou estrutura "
        "cósmica) ainda não foi definida.",
    ),
    (
        "🪨 Malachais — a matéria",
        "Criou o princípio material: aquilo que pode existir como "
        "substância, corpo ou estrutura.\n"
        "Sua função é cosmológica; não é só uma divindade maligna. "
        "Moralidade e motivações são definidas à parte.",
    ),
    (
        "📜 Marjopyia — o sentido e as regras",
        "Depois da matéria, atribuiu sentido e estabeleceu as regras que "
        "tornam a realidade organizada e compreensível.\n"
        "Não é o \"bem absoluto\": sua função é dar sentido e regras, não "
        "julgar o valor ético de tudo.",
    ),
    (
        "♾️ O Inominável",
        "A junção da matéria de Malachais com o sentido e as regras de "
        "Marjopyia gera um terceiro ser: O Inominável. Ele é uma "
        "consequência ontológica dessa união, não uma simples criatura "
        "poderosa. Seus poderes não são ilimitados; precisam ser "
        "estabelecidos pelo cânone.",
    ),
    (
        "🛡️ Os Ancestrais e o selo",
        "Os Ancestrais (também chamados Guardiões ou Arquitetos) selaram "
        "Malachais e Marjopyia em uma criatura: O Inominável. Selar não é "
        "destruir.\n"
        f"{ABERTO} Por que o fizeram, a natureza do selo e o que houve com "
        "a árvore depois.",
    ),
]

# nome -> (emoji, texto)
ALINHAMENTOS = {
    "Caótico": (
        "🌀",
        "Associado ao Caos e às forças contrárias à manutenção do selo do "
        "Inominável: os alinhados ao Caos tentam rompê-lo.\n"
        "É uma força metafísica, não só maldade moral. As motivações "
        "variam (fanatismo, ambição, convicção, ou ver a ordem vigente "
        "como prisão) e nem todo Caótico é igual ou irracional.",
    ),
    "Luminária": (
        "✨",
        "Alinhamento ligado à força da Luminária, um dos polos centrais do "
        "conflito cósmico e oposto ao Caos.\n"
        "Não é sinônimo de bondade perfeita ou verdade absoluta: seus "
        "agentes podem ser falíveis e divergir entre si.",
    ),
    "Natural": (
        "🌿",
        "Associado à natureza, com identidade própria entre os polos. "
        "Abrange manifestações que não cabem na oposição Caos x Luminária "
        "e aparece em efeitos defensivos, como escudos e proteções.\n"
        "Não é só benevolente, passivo ou puramente vegetal.",
    ),
    "Neutro": (
        "⚖️",
        "Sem compromisso exclusivo com os demais polos. No sistema de "
        "cartas SFA, interage de forma flexível com as outras categorias.\n"
        f"{ABERTO} Sua função exata na cosmologia ainda não foi definida.",
    ),
    "Independente": (
        "🃏",
        "No sistema de cartas funciona como coringa: repete a carta jogada "
        "anteriormente.\n"
        "Não é um \"Neutro mais forte\": são categorias diferentes.",
    ),
}

ALINHAMENTOS_NOTA = (
    "Alinhamento explica a relação com as forças do universo, não o "
    "caráter de cada indivíduo. Uma criatura não precisa agir como "
    "estereótipo moral só por causa dele."
)

# nome -> (campo associado, texto)
FACCOES = {
    "Fé da Luminária": (
        "✨ Luminária",
        "Facção associada à Luminária e às crenças ligadas a essa força.",
    ),
    "Aurora Templária": (
        "✨ Luminária",
        "Facção associada ao campo de influência da Luminária.",
    ),
    "Filhos do Caos": (
        "🌀 Caos",
        "Facção ligada ao Caos. A relação com a tentativa de romper o "
        "selo é um eixo importante a desenvolver.",
    ),
    "Abismo Eterno": (
        "🌀 Caos",
        "Facção ou organização associada ao Caos e às forças abissais.",
    ),
    "Silvestres": (
        "🌿 Natural",
        "Facção relacionada ao campo Natural.",
    ),
    "Alvorada Rubra": (
        "❔ A confirmar",
        f"Facção existente no cenário. {ABERTO} Sua posição na "
        "cosmologia e nos alinhamentos ainda não foi confirmada.",
    ),
    "Véu Neutral": (
        "⚖️ Neutro",
        "Facção relacionada ao campo Neutro.",
    ),
}

FACCOES_NOTA = (
    "O alinhamento de uma facção não define sozinho suas crenças, métodos "
    "ou objetivos. Doutrina oficial, interesses dos líderes e ações dos "
    "membros podem divergir."
)

OLHO = [
    (
        "👁️ O que é",
        "Ligado à manipulação da realidade, do tempo e do espaço em "
        "benefício de quem o usa. Não é só \"ver melhor\": o que importa "
        "é alterar como a realidade se organiza, se manifesta ou é "
        "percebida.",
    ),
    (
        "🧭 Três dimensões",
        "**Realidade:** mudar a percepção de algo é diferente de mudar o "
        "próprio algo.\n"
        "**Tempo:** sequência de eventos, continuidade e percepção "
        "temporal.\n"
        "**Espaço:** posição, distância e relações entre lugares.",
    ),
    (
        "⚠️ Limites",
        f"{ABERTO} Alcance, custos e consequências ainda não foram "
        "definidos. Não está confirmado que ele permita viajar livremente "
        "no tempo, prever tudo ou reescrever a história.",
    ),
    (
        "🕯️ Ritual do Olho",
        "Aparece em Maré Morta (vela, espelho e percepção alterada). "
        f"{ABERTO} Não está confirmado que seja o mesmo que o Olho "
        "Metamorfo.",
    ),
]

SISTEMA = [
    (
        "🎲 Testes (3d8)",
        "Lance três dados de oito faces, conserve os **dois maiores** "
        "resultados e compare ao atributo correspondente. Sucesso, falha, "
        "dificuldade e modificadores seguem as regras vigentes do sistema.",
    ),
    (
        "❤️ Vida",
        "Representa a integridade física do personagem.",
    ),
    (
        "🧠 SAN (sanidade)",
        "Integridade mental diante de situações perturbadoras e fenômenos "
        "que desafiam a compreensão.\n"
        "**SAN inicial = 12 + modificador de IQ + modificador de HT.**",
    ),
    (
        "📚 Inspirações",
        "Influências de GURPS e Call of Cthulhu, adaptadas ao universo "
        "autoral. O horror não deve virar só uma barra numérica, e números "
        "maiores não vencem qualquer ameaça.",
    ),
]

RUPTURA = [
    (
        "⏳ O que é",
        "Roguelite ligado ao universo SFA, também jogável no Discord. "
        "Atravessa eras e realidades alteradas, com encontros que vão de "
        "criaturas medievais a entidades futuristas.",
    ),
    (
        "🎭 Classes",
        "Mago do Véu • Guardião da Luminária • Errante Temporal • "
        "Vampiro da Noite Carmesim.\n"
        "Cada uma tem identidade mecânica própria, com passivas e "
        "habilidades que mudam o estilo de jogo.",
    ),
    (
        "📈 Progressão",
        "Criaturas, minibosses, bosses e eventos especiais; recompensas em "
        "XP, Abysmus, itens e relíquias que mudam a construção do "
        "personagem.",
    ),
    (
        "🧩 Mecânica x cosmologia",
        "Uma habilidade do jogo pode ser uma versão simplificada de um "
        "fenômeno bem mais complexo na narrativa; as regras do jogo não "
        "são leis universais do cosmos.",
    ),
]

# chave -> (título, estado, resumo, [(campo, texto)])
LIVROS = {
    "sfa": (
        "📕 Livro I — Segredo Floresta Adentro (SFA)",
        "Base mitológica do universo",
        "Cenário de RPG e horror sobrenatural sobre forças cósmicas, "
        "entidades ancestrais, alinhamentos metafísicos, mistérios ocultos "
        "e a fragilidade da percepção humana. Sua cosmologia permite "
        "questionar as próprias condições de existência.",
        [
            (
                "Contém",
                "Drakvu, Malachais e Marjopyia • os Ancestrais • O "
                "Inominável • Caos x Luminária • os 5 alinhamentos • os "
                "Olhos Metamorfos • o arquipélago de Da’kor e Tenebra • "
                "facções, criaturas, relíquias, magia, sanidade e "
                "investigação.",
            ),
        ],
    ),
    "mare": (
        "📘 Livro II — Maré Morta",
        "Em construção",
        "Terror sobrenatural, mistério e investigação numa pequena cidade "
        "litorânea decadente.",
        [
            (
                "Protagonista",
                "Theo Vincent Almeida, 22 anos, estudante de Filosofia, "
                "funcionário de uma livraria e interessado em ocultismo. "
                "Analítico, racional e obcecado por padrões. Seu melhor "
                "amigo é Noah.",
            ),
            (
                "Temas",
                "Conhecimento x ignorância • curiosidade x autopreservação "
                "• percepção x realidade • obsessão e paranoia • segredo e "
                "isolamento • o preço de enxergar o que deveria ficar "
                "oculto.",
            ),
            (
                "Conexão com SFA",
                f"{ABERTO} Nomes como Noctharis, Olho, Arquiteto, "
                "Malachais, Merjin, Inominável, Drak’vuh e Marjopyia "
                "aparecem no conjunto do universo, mas seus significados "
                "em Maré Morta ainda não foram definidos. Os conceitos de "
                "SFA não valem automaticamente aqui.",
            ),
        ],
    ),
    "inominavel": (
        "📗 Livro III — Inominável",
        "Livro final planejado",
        "Encerramento planejado da estrutura dos três livros. O título "
        "remete à entidade O Inominável, de SFA.",
        [
            (
                "Em aberto",
                f"{ABERTO} A trama completa, a identidade exata entre "
                "título, entidade e acontecimentos finais, e o desfecho "
                "ainda não foram estabelecidos pelo autor.",
            ),
            (
                "Direção",
                "Deve considerar a convergência entre os mistérios, "
                "fenômenos e princípios metafísicos dos dois primeiros "
                "livros, construída por pistas e consequências, não por "
                "coincidências arbitrárias.",
            ),
        ],
    ),
}

# Perguntas que o autor ainda não respondeu.
LACUNAS = [
    "**Drakvu x Drak’vuh:** são o mesmo? Qual a relação entre a árvore e "
    "o nome Drak’vuh?",
    "**A terceira entidade:** quem é a terceira entidade que emergiu da "
    "árvore e qual sua relação com o Inominável?",
    "**O selo:** é material, metafísico, temporal ou uma combinação? O "
    "que aconteceu com a árvore depois?",
    "**Os Ancestrais:** por que selaram Malachais e Marjopyia? O Inominável "
    "foi prisão deliberada ou consequência?",
    "**Merjin:** natureza, posição e relação com Malachais, Marjopyia, os "
    "Ancestrais e o Inominável.",
    "**Neutro:** qual sua função exata na cosmologia?",
    "**Alvorada Rubra:** onde se encaixa nos alinhamentos?",
    "**Olho Metamorfo:** alcance, custos, limites e se afeta a realidade "
    "ou só a percepção.",
    "**Ritual do Olho x Olho Metamorfo:** são a mesma coisa?",
    "**Maré Morta:** o significado de Noctharis, Olho, Arquiteto, Merjin "
    "etc. dentro do livro.",
    "**Inominável (livro):** trama, desfecho e relação com a entidade.",
]

# termo -> definição curta
GLOSSARIO = {
    "Drakvu": "Árvore primordial, origem metafísica do universo. Natureza "
              f"exata em aberto {ABERTO}.",
    "Drak’vuh": "Nome associado ao universo (criaturas e fantasia sombria). "
                f"Não é confirmado como sinônimo de Drakvu {ABERTO}.",
    "Malachais": "Criou a matéria. Selado junto com Marjopyia no Inominável.",
    "Marjopyia": "Atribuiu sentido e regras à matéria. Selada junto com "
                 "Malachais no Inominável.",
    "Inominável": "Ser nascido da junção de matéria e sentido; prisão de "
                  "Malachais e Marjopyia. Também título do Livro III.",
    "Ancestrais": "Guardiões ou Arquitetos que selaram Malachais e "
                  "Marjopyia no Inominável.",
    "Selo": "O que mantém Malachais e Marjopyia presos no Inominável. "
            "Os Caóticos tentam rompê-lo.",
    "Caos": "Polo metafísico oposto à Luminária; força associada à "
            "tentativa de romper o selo.",
    "Luminária": "Polo metafísico oposto ao Caos; não é bondade absoluta.",
    "Olho Metamorfo": "Manipulação de realidade, tempo e espaço em "
                      "benefício de quem o usa.",
    "Ritual do Olho": "Ritual de Maré Morta com vela e espelho que altera "
                      "a percepção de Theo. Relação com o Olho Metamorfo "
                      f"em aberto {ABERTO}.",
    "Tenebra": "Região da ambientação de SFA.",
    "Da’kor": "Arquipélago da ambientação de SFA.",
    "Merjin": f"Nome relevante do universo; natureza e posição em aberto "
              f"{ABERTO}.",
    "SAN": "Sanidade do personagem no RPG. Inicial = 12 + mod IQ + mod HT.",
    "3d8": "Teste do RPG SFA: três d8, conserva os dois maiores.",
    "Abysmus": "Recompensa de progressão no Ruptura Temporal (junto com XP, "
               "itens e relíquias).",
    "Ruptura Temporal": "Roguelite do universo SFA, jogável no Discord.",
    "Theo Vincent Almeida": "Protagonista de Maré Morta, 22 anos, "
                            "estudante de Filosofia.",
    "Noah": "Melhor amigo de Theo em Maré Morta.",
}


# ============================================================
# PROMPT DA IA
# ============================================================

REGRAS_IA = """\
Você é o guardião do cânone do universo ficcional de Jay Moon (livros: \
Segredo Floresta Adentro (SFA), Maré Morta e Inominável). Você é um \
colaborador, não o dono do universo.

REGRAS OBRIGATÓRIAS
- Não confunda fatos estabelecidos com hipóteses. Quando algo não estiver \
definido, diga que está EM ABERTO em vez de inventar.
- Rotule quando relevante: CÂNONE (estabelecido), INFERÊNCIA \
(interpretação fundamentada), PROPOSTA (ideia nova, depende do autor), \
EM ABERTO (não definido), CONTRADIÇÃO.
- Preserve os nomes e grafias (Drakvu x Drak’vuh NÃO são sinônimos \
confirmados).
- Não invente o final de Inominável, não trate Maré Morta como concluído e \
não revele mistérios que o autor ainda vai desenvolver.
- Não transforme os alinhamentos em bem x mal simplista e não dê poderes \
ilimitados às entidades primordiais.
- Não presuma que Ritual do Olho e Olho Metamorfo são a mesma coisa.
- Mantenha a diferença entre a explicação metafísica de algo e sua \
representação nas regras de RPG ou no roguelite.
- Se houver ambiguidade importante, faça UMA pergunta objetiva.

FORMATO (Discord): responda em português, direto e claro, em até cerca de \
1500 caracteres, sem encher de títulos.
"""


def resumo_canonico() -> str:
    """Gera o resumo do cânone a partir dos dicionários acima."""
    linhas = ["CÂNONE ESTABELECIDO (resumo):"]

    for titulo, texto in COSMOLOGIA:
        linhas.append(f"- {titulo}: {texto}")

    linhas.append("ALINHAMENTOS:")
    for nome, (_emoji, texto) in ALINHAMENTOS.items():
        linhas.append(f"- {nome}: {texto}")
    linhas.append(f"- {ALINHAMENTOS_NOTA}")

    linhas.append("FACÇÕES:")
    for nome, (campo, texto) in FACCOES.items():
        linhas.append(f"- {nome} ({campo}): {texto}")
    linhas.append(f"- {FACCOES_NOTA}")

    linhas.append("OLHO METAMORFO:")
    for titulo, texto in OLHO:
        linhas.append(f"- {titulo}: {texto}")

    linhas.append("SISTEMA DE RPG:")
    for titulo, texto in SISTEMA:
        linhas.append(f"- {titulo}: {texto}")

    linhas.append("RUPTURA TEMPORAL:")
    for titulo, texto in RUPTURA:
        linhas.append(f"- {titulo}: {texto}")

    linhas.append("LIVROS:")
    for titulo, estado, resumo, campos in LIVROS.values():
        linhas.append(f"- {titulo} ({estado}): {resumo}")
        for campo, texto in campos:
            linhas.append(f"  {campo}: {texto}")

    linhas.append("LACUNAS (ainda não definidas pelo autor):")
    linhas.extend(f"- {item}" for item in LACUNAS)

    return "\n".join(linhas)


def carregar_prompt_sfa() -> str:
    """Usa o Prompt-Mestre completo se existir; senão, o resumo embutido."""
    for caminho in CAMINHOS_PROMPT:
        try:
            if caminho.is_file():
                texto = caminho.read_text(encoding="utf-8").strip()
                if texto:
                    log.info("Prompt-Mestre carregado de %s", caminho)
                    return f"{texto}\n\n---\n{REGRAS_IA}"
        except OSError:
            log.exception("Não consegui ler %s", caminho)

    log.info("Usando o resumo embutido do cânone (sem lore_prompt.txt).")
    return f"{REGRAS_IA}\n{resumo_canonico()}"


# ============================================================
# EMBEDS
# ============================================================

def _cortar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def montar_embed(
    titulo: str,
    descricao: str = "",
    campos: list[tuple[str, str]] | None = None,
    cor: discord.Color | None = None,
    rodape: str = RODAPE,
) -> discord.Embed:
    embed = discord.Embed(
        title=_cortar(titulo, 256),
        description=_cortar(descricao, 4000) if descricao else None,
        color=cor or discord.Color.dark_purple(),
    )
    for nome, valor in campos or []:
        embed.add_field(
            name=_cortar(nome, 256),
            value=_cortar(valor, 1024),
            inline=False,
        )
    embed.set_footer(text=rodape)
    return embed


def dividir_mensagem(texto: str, limite: int = 1900) -> list[str]:
    """Divide preferindo parágrafos, depois linhas, depois espaços."""
    partes = []
    restante = texto.strip()

    while len(restante) > limite:
        corte = -1
        for separador in ("\n\n", "\n", " "):
            corte = restante.rfind(separador, 0, limite)
            if corte >= limite // 2:
                break
            corte = -1
        if corte == -1:
            corte = limite
        partes.append(restante[:corte].rstrip())
        restante = restante[corte:].lstrip()

    if restante:
        partes.append(restante)
    return partes


# ============================================================
# COG
# ============================================================

class Lore(
    commands.GroupCog,
    name="lore",
    description="Explore o universo de Segredo Floresta Adentro.",
):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()
        self.prompt_ia = carregar_prompt_sfa()

    # ---------- Livros ----------

    @app_commands.command(
        name="livros",
        description="Os três livros do universo: SFA, Maré Morta e Inominável.",
    )
    @app_commands.describe(livro="Qual livro detalhar (vazio = visão geral).")
    @app_commands.choices(livro=[
        app_commands.Choice(name="📕 Segredo Floresta Adentro", value="sfa"),
        app_commands.Choice(name="📘 Maré Morta", value="mare"),
        app_commands.Choice(name="📗 Inominável", value="inominavel"),
    ])
    async def livros(
        self,
        interaction: discord.Interaction,
        livro: app_commands.Choice[str] | None = None,
    ):
        if livro is None:
            campos = [
                (titulo, f"*{estado}*\n{resumo}")
                for titulo, estado, resumo, _ in LIVROS.values()
            ]
            embed = montar_embed(
                "📚 Os três livros",
                "O universo é uma mitologia maior dividida em três livros "
                "relacionados. Use `/lore livros` escolhendo um livro para "
                "ver os detalhes.",
                campos,
                discord.Color.gold(),
            )
        else:
            titulo, estado, resumo, campos = LIVROS[livro.value]
            embed = montar_embed(
                titulo, f"*{estado}*\n\n{resumo}", campos,
                discord.Color.gold(),
            )

        await interaction.response.send_message(embed=embed)

    # ---------- Cosmologia ----------

    @app_commands.command(
        name="cosmologia",
        description="A origem: Drakvu, Malachais, Marjopyia e o Inominável.",
    )
    async def cosmologia(self, interaction: discord.Interaction):
        embed = montar_embed(
            "🌌 Cosmologia primordial",
            f"{CANONE} = estabelecido • {ABERTO} = ainda em aberto",
            COSMOLOGIA,
            discord.Color.dark_purple(),
        )
        await interaction.response.send_message(embed=embed)

    # ---------- Alinhamentos ----------

    @app_commands.command(
        name="alinhamento",
        description="Explica os alinhamentos metafísicos de SFA.",
    )
    @app_commands.describe(qual="Qual alinhamento (vazio = todos).")
    @app_commands.choices(qual=[
        app_commands.Choice(name=f"{emoji} {nome}", value=nome)
        for nome, (emoji, _) in ALINHAMENTOS.items()
    ])
    async def alinhamento(
        self,
        interaction: discord.Interaction,
        qual: app_commands.Choice[str] | None = None,
    ):
        if qual is None:
            campos = [
                (f"{emoji} {nome}", texto)
                for nome, (emoji, texto) in ALINHAMENTOS.items()
            ]
            embed = montar_embed(
                "🧭 Os 5 alinhamentos",
                ALINHAMENTOS_NOTA,
                campos,
                discord.Color.blurple(),
            )
        else:
            emoji, texto = ALINHAMENTOS[qual.value]
            embed = montar_embed(
                f"{emoji} {qual.value}",
                f"{texto}\n\n*{ALINHAMENTOS_NOTA}*",
                None,
                discord.Color.blurple(),
            )

        await interaction.response.send_message(embed=embed)

    # ---------- Facções ----------

    @app_commands.command(
        name="faccao",
        description="Explica as facções conhecidas do universo.",
    )
    @app_commands.describe(qual="Qual facção (vazio = todas).")
    @app_commands.choices(qual=[
        app_commands.Choice(name=nome, value=nome) for nome in FACCOES
    ])
    async def faccao(
        self,
        interaction: discord.Interaction,
        qual: app_commands.Choice[str] | None = None,
    ):
        if qual is None:
            campos = [
                (f"{nome} — {campo}", texto)
                for nome, (campo, texto) in FACCOES.items()
            ]
            embed = montar_embed(
                "⚔️ Facções", FACCOES_NOTA, campos, discord.Color.red()
            )
        else:
            campo, texto = FACCOES[qual.value]
            embed = montar_embed(
                f"⚔️ {qual.value}",
                f"**Campo:** {campo}\n\n{texto}\n\n*{FACCOES_NOTA}*",
                None,
                discord.Color.red(),
            )

        await interaction.response.send_message(embed=embed)

    # ---------- Olho Metamorfo ----------

    @app_commands.command(
        name="olho",
        description="Explica o Olho Metamorfo e o Ritual do Olho.",
    )
    async def olho(self, interaction: discord.Interaction):
        embed = montar_embed(
            "👁️ O Olho Metamorfo", "", OLHO, discord.Color.dark_teal()
        )
        await interaction.response.send_message(embed=embed)

    # ---------- Sistema e jogo ----------

    @app_commands.command(
        name="sistema",
        description="O sistema de RPG de SFA (3d8, Vida e SAN).",
    )
    async def sistema(self, interaction: discord.Interaction):
        embed = montar_embed(
            "🎲 Sistema de RPG de SFA", "", SISTEMA, discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="ruptura",
        description="O roguelite Ruptura Temporal.",
    )
    async def ruptura(self, interaction: discord.Interaction):
        embed = montar_embed(
            "⏳ Ruptura Temporal", "", RUPTURA, discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

    # ---------- Glossário e lacunas ----------

    @app_commands.command(
        name="glossario",
        description="Definição rápida de um termo do universo.",
    )
    @app_commands.describe(termo="O termo que você quer entender.")
    @app_commands.choices(termo=[
        app_commands.Choice(name=nome, value=nome)
        for nome in list(GLOSSARIO)[:25]
    ])
    async def glossario(
        self,
        interaction: discord.Interaction,
        termo: app_commands.Choice[str],
    ):
        embed = montar_embed(
            f"📖 {termo.value}",
            GLOSSARIO[termo.value],
            None,
            discord.Color.light_grey(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="lacunas",
        description="O que o autor ainda não definiu no universo.",
    )
    async def lacunas(self, interaction: discord.Interaction):
        embed = montar_embed(
            f"{ABERTO} Lacunas do cânone",
            "Perguntas ainda sem resposta oficial. Até o autor decidir, "
            "tudo isto é **em aberto**; qualquer resposta é só hipótese.\n\n"
            + "\n".join(f"• {item}" for item in LACUNAS),
            None,
            discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    # ---------- IA ----------

    @app_commands.command(
        name="perguntar",
        description="Pergunte qualquer coisa sobre o universo SFA (IA).",
    )
    @app_commands.checks.cooldown(
        1, COOLDOWN_PERGUNTAR_SEGUNDOS,
        key=lambda i: (i.guild_id, i.user.id),
    )
    @app_commands.describe(pergunta="O que você quer saber sobre o universo.")
    async def perguntar(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 3, MAX_CARACTERES_PERGUNTA],
    ):
        ia_cog = self.bot.get_cog("IA")
        gerar = getattr(ia_cog, "gerar_resposta", None)

        if not callable(gerar) or not getattr(ia_cog, "client", None):
            await interaction.response.send_message(
                "A IA não está disponível agora. Enquanto isso, use "
                "`/lore cosmologia`, `/lore alinhamento` e os outros "
                "comandos do `/lore`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        mensagens = [
            {"role": "system", "content": self.prompt_ia},
            {"role": "user", "content": pergunta.strip()},
        ]

        try:
            resposta = await asyncio.wait_for(
                gerar(mensagens, max_tokens=MAX_TOKENS_PERGUNTAR),
                timeout=TIMEOUT_PERGUNTAR_SEGUNDOS,
            )
        except Exception:
            log.exception("Falha no /lore perguntar.")
            await interaction.followup.send(
                "A IA não conseguiu responder agora. Tente de novo em "
                "instantes ou use os outros comandos do `/lore`."
            )
            return

        partes = dividir_mensagem(resposta)
        partes[-1] += (
            "\n\n-# 🧠 Resposta da IA. O cânone oficial é o definido pelo "
            "autor; veja `/lore lacunas`."
        )

        for parte in partes:
            await interaction.followup.send(
                parte, allowed_mentions=SEM_MENCOES
            )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            texto = f"⏳ Aguarde {error.retry_after:.0f}s para perguntar de novo."
        else:
            log.exception(
                "Erro em /lore.", exc_info=error
            )
            texto = "❌ Ocorreu um erro ao executar o comando."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(texto, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    # Evita derrubar o bot inteiro se outro cog já usa o nome "lore".
    if bot.tree.get_command("lore") is not None:
        log.error(
            "Já existe um comando /lore registrado por outro cog. "
            "Renomeie o grupo em cogs/lore.py (name=\"lore\") ou o outro."
        )
        raise commands.ExtensionError(
            "Comando /lore já registrado por outro cog.", name=__name__
        )

    await bot.add_cog(Lore(bot))
