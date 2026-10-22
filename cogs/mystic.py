"""
Cog Mystic — comandos místicos do SHAGGY MYSTIC.

Comandos:
    /bola8          Consulta a Bola 8 (a cor muda conforme a resposta)
    /tarot          1 carta ou tiragem de 3 cartas (22 arcanos, com invertidas)
    /runas          Tiragem de runas do Futhark Antigo
    /destino        Mensagem do destino, com número e cor do dia
    /horoscopo      Horóscopo diário por signo (fixo durante o dia)
    /numerologia    Número de expressão e caminho de vida
    /lua            Fase real da Lua, calculada na hora
    /aura           Cor da sua aura no dia
    /compatibilidade  Afinidade mística entre duas pessoas
    /sonho          Interpretação simbólica, detecta símbolos no relato
    /pressagio      Presságio sombrio com prazo e intensidade
    /ritual         Ritual fictício completo para histórias e RPG
    /amuleto        Amuleto fictício com poder e preço
"""

import hashlib
import logging
import math
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

RODAPE = "SHAGGY MYSTIC"
FUSO_BR = timezone(timedelta(hours=-3))


# ════════════════════════════════════════════════════════════════
# Utilidades
# ════════════════════════════════════════════════════════════════

def hoje() -> str:
    """Data atual no horário de Brasília (AAAA-MM-DD)."""
    return datetime.now(FUSO_BR).strftime("%Y-%m-%d")


def rng_do_dia(*partes) -> random.Random:
    """Gerador aleatório fixo para a mesma combinação de partes no mesmo dia."""
    semente = "|".join(str(p) for p in (*partes, hoje()))
    return random.Random(semente)


def cortar(texto: str, limite: int = 1024) -> str:
    """Limpa menções e respeita o limite de campos de embed."""
    texto = discord.utils.escape_mentions(texto.strip())
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1] + "…"


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para buscar palavras-chave."""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.lower()


def barra(valor: int, total: int) -> str:
    return "▰" * valor + "▱" * (total - valor)


def criar_embed(
    titulo: str,
    descricao: Optional[str] = None,
    cor: Optional[discord.Color] = None,
    rodape: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=titulo,
        description=descricao,
        color=cor or discord.Color.purple(),
    )
    embed.set_footer(text=f"{RODAPE} • {rodape}" if rodape else RODAPE)
    return embed


def espera():
    """Cooldown individual de 5s por usuário (um por comando)."""
    return app_commands.checks.cooldown(
        1, 5.0, key=lambda i: (i.guild_id, i.user.id)
    )


# ════════════════════════════════════════════════════════════════
# Dados — Bola 8
# ════════════════════════════════════════════════════════════════

BOLA8 = {
    "positiva": (
        discord.Color.green(),
        45,
        [
            "🔮 Sim.",
            "✨ Definitivamente sim!",
            "🔮 Os sinais apontam para sim.",
            "💫 Tudo indica que sim.",
            "⚡ As chances são maiores do que você imagina.",
            "🌟 Sem dúvida alguma.",
            "🌕 As estrelas estão alinhadas a seu favor.",
            "🔮 Pode contar com isso.",
        ],
    ),
    "neutra": (
        discord.Color.gold(),
        25,
        [
            "🌙 Talvez. O futuro ainda está em movimento.",
            "🌀 Pergunte novamente mais tarde.",
            "👁️ Não consigo enxergar essa resposta.",
            "🔮 O destino ainda não decidiu.",
            "🌫️ A névoa está densa demais agora.",
            "⏳ Algumas respostas só nascem com o tempo.",
        ],
    ),
    "negativa": (
        discord.Color.dark_red(),
        30,
        [
            "🔮 Não.",
            "💀 Definitivamente não!",
            "🌑 Os sinais apontam para não.",
            "🕯️ Não conte com isso.",
            "☠️ Meu silêncio já é uma resposta.",
            "🥀 As vozes do além dizem que não.",
            "🌪️ Melhor repensar esse caminho.",
        ],
    ),
}


# ════════════════════════════════════════════════════════════════
# Dados — Tarot (nome, significado direito, significado invertido)
# ════════════════════════════════════════════════════════════════

ARCANOS = [
    ("O Louco",
     "Novos caminhos surgem. Arriscar pode ser necessário, mas não confunda coragem com imprudência.",
     "Pressa e descuido. Olhe antes de saltar e revise o que você está ignorando."),
    ("O Mago",
     "Você tem ferramentas para agir. Transforme intenção em atitude.",
     "Talento desperdiçado ou promessas vazias. Alinhe o que diz com o que faz."),
    ("A Sacerdotisa",
     "Nem toda resposta está disponível agora. Observe os detalhes e escute sua intuição.",
     "Intuição ignorada ou segredos mal guardados. Você já sabe mais do que admite."),
    ("A Imperatriz",
     "Criatividade, cuidado e abundância. O que foi plantado com carinho tende a florescer.",
     "Excesso, dependência ou bloqueio criativo. Cuide de si antes de cuidar de tudo."),
    ("O Imperador",
     "Estrutura, disciplina e liderança. Hora de organizar e assumir responsabilidade.",
     "Rigidez ou controle em excesso. Nem toda autoridade precisa ser dura."),
    ("O Hierofante",
     "Tradição, aprendizado e conselhos de quem já percorreu o caminho.",
     "Regras que já não servem. Questione o que você aceita apenas por hábito."),
    ("Os Enamorados",
     "Escolhas do coração, vínculos e alinhamento de valores.",
     "Dúvida, desencontro ou escolha adiada. Seja honesto sobre o que você quer."),
    ("O Carro",
     "Determinação e avanço. Direcione sua força para um único objetivo.",
     "Falta de rumo ou disputa interna. Sem direção, velocidade vira desgaste."),
    ("A Força",
     "Coragem serena. A gentileza também é uma forma de poder.",
     "Insegurança e energia esgotada. Recupere o fôlego antes de insistir."),
    ("O Eremita",
     "Diminua o ruído externo e procure compreender o que realmente importa para você.",
     "Isolamento demais. O silêncio ajuda, mas não precisa virar muro."),
    ("A Roda da Fortuna",
     "As circunstâncias mudam. Adapte-se em vez de tentar controlar tudo.",
     "Resistência à mudança. Ciclos se repetem até a lição ser aprendida."),
    ("A Justiça",
     "Equilíbrio, verdade e consequências. Seja justo, inclusive consigo mesmo.",
     "Parcialidade ou decisão apressada. Reveja um julgamento antes de mantê-lo."),
    ("O Enforcado",
     "Pausa necessária e novo ponto de vista. Esperar também é uma forma de agir.",
     "Sacrifício inútil ou impaciência. Pergunte o que você adia por medo."),
    ("A Morte",
     "Uma fase se encerra. A mudança pode abrir espaço para algo novo.",
     "Apego ao que já acabou. Soltar costuma doer menos do que segurar."),
    ("A Temperança",
     "Moderação, paciência e harmonia. Misture as coisas com calma.",
     "Excessos e desequilíbrio. Volte ao meio-termo."),
    ("O Diabo",
     "Observe hábitos, desejos ou dependências que podem estar limitando suas escolhas.",
     "As correntes afrouxam. Você começa a perceber o que o prende e pode agir."),
    ("A Torre",
     "Uma estrutura pode precisar ruir para que algo mais sólido seja construído.",
     "Crise adiada ou mudança resistida. Evitar o desabamento não conserta a fundação."),
    ("A Estrela",
     "Esperança, renovação e recuperação. Continue avançando sem exigir resultados imediatos.",
     "Desânimo e fé abalada. A luz continua lá, apenas mais distante."),
    ("A Lua",
     "Há dúvidas, ilusões ou informações incompletas. Evite tirar conclusões precipitadas.",
     "A névoa começa a se dissipar. Medos perdem força quando são nomeados."),
    ("O Sol",
     "Clareza, energia e crescimento. Aproveite o momento para agir com confiança.",
     "Alegria encoberta. O brilho existe, mas precisa de um motivo para aparecer."),
    ("O Julgamento",
     "Chamado, balanço e renovação. Reavalie o passado e responda ao que te chama.",
     "Autocrítica excessiva. Perdoar-se também faz parte de seguir adiante."),
    ("O Mundo",
     "Conclusão de ciclo, integração e possibilidade de começar uma nova etapa.",
     "Ciclo quase completo. Falta um último passo, não desista na reta final."),
]

POSICOES_TAROT = ("⏪ Passado", "⏺️ Presente", "⏩ Futuro")


# ════════════════════════════════════════════════════════════════
# Dados — Runas (símbolo, nome, significado)
# ════════════════════════════════════════════════════════════════

RUNAS = [
    ("ᚠ", "Fehu", "Riqueza, recursos e energia que precisa circular."),
    ("ᚢ", "Uruz", "Força bruta, saúde e vontade de seguir em frente."),
    ("ᚦ", "Thurisaz", "Conflito e proteção: um limite que pode ferir ou defender."),
    ("ᚨ", "Ansuz", "Mensagem, palavra e sabedoria recebida."),
    ("ᚱ", "Raidho", "Jornada, ritmo e o caminho certo no momento certo."),
    ("ᚲ", "Kenaz", "Tocha acesa: conhecimento, criatividade e clareza."),
    ("ᚷ", "Gebo", "Presente, troca justa e parceria."),
    ("ᚹ", "Wunjo", "Alegria, harmonia e realização."),
    ("ᚺ", "Hagalaz", "Tempestade, ruptura e um caos que limpa o terreno."),
    ("ᚾ", "Nauthiz", "Necessidade e restrição: paciência sob pressão."),
    ("ᛁ", "Isa", "Gelo, pausa e estagnação. Nem tudo precisa se mover agora."),
    ("ᛃ", "Jera", "Colheita, ciclo e a recompensa do tempo."),
    ("ᛇ", "Eihwaz", "Resistência, eixo e transição entre fases."),
    ("ᛈ", "Perthro", "Mistério, destino e o que ainda está oculto."),
    ("ᛉ", "Algiz", "Proteção, alerta e conexão com algo maior."),
    ("ᛊ", "Sowilo", "Sol, vitória e orientação."),
    ("ᛏ", "Tiwaz", "Justiça, coragem e sacrifício por um princípio."),
    ("ᛒ", "Berkano", "Nascimento, cuidado e crescimento."),
    ("ᛖ", "Ehwaz", "Confiança e parceria em movimento."),
    ("ᛗ", "Mannaz", "Humanidade, o eu e o outro, comunidade."),
    ("ᛚ", "Laguz", "Água, intuição e fluxo emocional."),
    ("ᛜ", "Ingwaz", "Semente, potencial e descanso antes de florescer."),
    ("ᛞ", "Dagaz", "Amanhecer, virada e despertar."),
    ("ᛟ", "Othala", "Herança, lar e raízes."),
]


# ════════════════════════════════════════════════════════════════
# Dados — Destino, horóscopo, aura
# ════════════════════════════════════════════════════════════════

MENSAGENS_DESTINO = [
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
    "Alguém pensa em você mais do que você imagina.",
    "O que você evita hoje volta amanhã com juros.",
    "Um recomeço não pede permissão, só coragem.",
    "A resposta que você procura já passou por você uma vez.",
    "Quem cuida do detalhe cuida do destino.",
    "Um ciclo se fecha em silêncio; perceba antes que ele termine.",
    "Há força em pedir ajuda no momento certo.",
    "O caminho mais longo pode ser o que ensina mais.",
]

CORES_DO_DIA = [
    "Roxo", "Prata", "Dourado", "Vermelho-sangue", "Azul-noite", "Verde-musgo",
    "Branco", "Preto", "Âmbar", "Turquesa", "Carmim", "Lilás",
]

SIGNOS = [
    ("♈", "Áries", "Fogo"), ("♉", "Touro", "Terra"), ("♊", "Gêmeos", "Ar"),
    ("♋", "Câncer", "Água"), ("♌", "Leão", "Fogo"), ("♍", "Virgem", "Terra"),
    ("♎", "Libra", "Ar"), ("♏", "Escorpião", "Água"),
    ("♐", "Sagitário", "Fogo"), ("♑", "Capricórnio", "Terra"),
    ("♒", "Aquário", "Ar"), ("♓", "Peixes", "Água"),
]

HOROSCOPO_GERAL = [
    "O dia favorece quem observa antes de agir.",
    "Sua energia está alta; use-a com propósito, não com pressa.",
    "Algo que parecia travado começa a se mover.",
    "Evite discussões desnecessárias: nem toda batalha merece sua força.",
    "Uma lembrança antiga pode trazer clareza para uma decisão atual.",
    "Dia ideal para organizar, limpar e recomeçar em pequena escala.",
    "Sua intuição está afiada. Confie nela, mas confirme os fatos.",
    "Pequenos gestos terão um peso maior que o esperado.",
]
HOROSCOPO_AMOR = [
    "Diálogo honesto fortalece laços importantes.",
    "Alguém pode se aproximar de forma inesperada.",
    "Cuide para não esperar que os outros adivinhem o que você sente.",
    "Hoje, presença vale mais que promessa.",
    "Bom momento para reparar um mal-entendido.",
    "Amor-próprio é o assunto central do dia.",
    "Uma amizade pode revelar mais do que aparenta.",
]
HOROSCOPO_TRABALHO = [
    "Foco em uma tarefa por vez rende mais que multitarefa.",
    "Uma ideia sua pode ser notada. Apresente-a com calma.",
    "Revise antes de enviar: detalhes fazem diferença.",
    "Colaboração destrava o que o esforço solitário não resolve.",
    "Evite assumir compromissos só para agradar.",
    "Um prazo pode apertar, mas você dá conta se priorizar.",
    "Hora de aprender algo novo que complemente suas habilidades.",
]

AURAS = [
    ("Vermelha", 0xE74C3C, "Vitalidade, coragem e impulso. Você está pronto para agir."),
    ("Laranja", 0xE67E22, "Criatividade e sociabilidade. Boas ideias pedem companhia."),
    ("Amarela", 0xF1C40F, "Otimismo e mente aberta. Ótimo dia para aprender."),
    ("Verde", 0x2ECC71, "Equilíbrio, cura e crescimento. Cuide do que importa."),
    ("Azul", 0x3498DB, "Calma e comunicação. Diga o que precisa ser dito."),
    ("Índigo", 0x4B0082, "Intuição profunda. Observe sinais que costuma ignorar."),
    ("Violeta", 0x9B59B6, "Espiritualidade e imaginação. Deixe a mente vagar."),
    ("Branca", 0xECF0F1, "Renovação e clareza. Um ótimo dia para recomeçar."),
    ("Dourada", 0xF39C12, "Confiança e brilho. Sua presença inspira os outros."),
    ("Prata", 0xBDC3C7, "Reflexo e mistério. Nem tudo precisa ser explicado."),
]


# ════════════════════════════════════════════════════════════════
# Dados — Numerologia
# ════════════════════════════════════════════════════════════════

TABELA_PITAGORICA = {
    letra: valor
    for valor, letras in enumerate(
        ["ajs", "bkt", "clu", "dmv", "enw", "fox", "gpy", "hqz", "ir"], start=1
    )
    for letra in letras
}

SIGNIFICADO_NUMEROS = {
    1: "Liderança, iniciativa e independência.",
    2: "Cooperação, sensibilidade e equilíbrio.",
    3: "Expressão, criatividade e alegria.",
    4: "Estrutura, disciplina e constância.",
    5: "Mudança, liberdade e curiosidade.",
    6: "Cuidado, responsabilidade e harmonia.",
    7: "Introspecção, estudo e busca de sentido.",
    8: "Ambição, poder pessoal e realização material.",
    9: "Compaixão, encerramento e visão ampla.",
    11: "Número mestre: intuição elevada e inspiração.",
    22: "Número mestre: construtor de grandes projetos.",
    33: "Número mestre: serviço, ensino e cuidado profundo.",
}


def reduzir(numero: int) -> int:
    """Reduz até um dígito, preservando os números mestres 11, 22 e 33."""
    while numero > 9 and numero not in (11, 22, 33):
        numero = sum(int(d) for d in str(numero))
    return numero


# ════════════════════════════════════════════════════════════════
# Dados — Lua
# ════════════════════════════════════════════════════════════════

CICLO_LUNAR = 29.530588853
LUA_NOVA_REFERENCIA = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

FASES_LUA = [
    ("Lua Nova", "🌑", "Tempo de plantar intenções em silêncio."),
    ("Lua Crescente", "🌒", "Energia de começo: dê forma ao que você planejou."),
    ("Quarto Crescente", "🌓", "Surgem obstáculos. Decida e aja com firmeza."),
    ("Crescente Gibosa", "🌔", "Refine e ajuste. Falta pouco para o brilho."),
    ("Lua Cheia", "🌕", "Tudo fica visível: celebre, conclua, revele."),
    ("Minguante Gibosa", "🌖", "Hora de agradecer e compartilhar o que aprendeu."),
    ("Quarto Minguante", "🌗", "Solte o que pesa; revise e perdoe."),
    ("Lua Minguante", "🌘", "Descanso, limpeza e preparação para o recomeço."),
]


def calcular_lua(agora: datetime):
    idade = ((agora - LUA_NOVA_REFERENCIA).total_seconds() / 86400) % CICLO_LUNAR
    iluminacao = (1 - math.cos(2 * math.pi * idade / CICLO_LUNAR)) / 2
    indice = int(idade / CICLO_LUNAR * 8 + 0.5) % 8
    ate_cheia = (CICLO_LUNAR / 2 - idade) % CICLO_LUNAR
    ate_nova = (CICLO_LUNAR - idade) % CICLO_LUNAR
    return indice, idade, iluminacao, ate_cheia, ate_nova


# ════════════════════════════════════════════════════════════════
# Dados — Sonhos
# ════════════════════════════════════════════════════════════════

SIMBOLOS_SONHO = [
    ("Água",
     r"\b(agua|mar|rio|chuva|oceano|onda|ondas|enchente|piscina|lago)\b",
     "Costuma se ligar às emoções. Água calma sugere paz; agitada, sentimentos em movimento."),
    ("Voar",
     r"\b(voar|voando|voei|voava|voo)\b",
     "Pode simbolizar liberdade, ambição ou vontade de se afastar de algo que pesa."),
    ("Queda",
     r"\b(cair|caindo|caiu|queda|despencar|despencando)\b",
     "Pode refletir perda de controle ou medo de falhar diante de algo importante."),
    ("Cobra",
     r"\b(cobra|cobras|serpente|serpentes)\b",
     "Simboliza transformação, alerta ou algo que você prefere não encarar."),
    ("Dentes",
     r"\b(dente|dentes)\b",
     "Muitas tradições ligam a ansiedade, a imagem pessoal e o medo de perder algo."),
    ("Perseguição",
     r"\b(perseguido|perseguida|perseguicao|fugindo|fugir|correndo)\b",
     "Pode indicar que há algo que você evita enfrentar, uma tarefa, uma conversa ou um sentimento."),
    ("Morte ou fim",
     r"\b(morte|morrer|morrendo|morri|morreu|funeral|velorio)\b",
     "Simbolicamente, aponta para encerramentos e transformação, raramente algo literal."),
    ("Casa ou portas",
     r"\b(casa|casas|quarto|porta|portas|janela|janelas)\b",
     "Representa o seu mundo interno: partes de você que pedem atenção ou espaço."),
    ("Escola ou prova",
     r"\b(escola|prova|faculdade|exame|professor|professora)\b",
     "Costuma refletir autoavaliação e medo de não estar preparado."),
    ("Fogo",
     r"\b(fogo|chamas|incendio|queimando)\b",
     "Pode representar paixão, raiva ou uma purificação necessária."),
    ("Espelho",
     r"\b(espelho|espelhos|reflexo)\b",
     "Convida a olhar para a própria imagem e para o que você mostra aos outros."),
    ("Escuridão",
     r"\b(escuro|escuridao|trevas|sombra|sombras|noite)\b",
     "Sugere incerteza ou algo ainda não compreendido, não necessariamente ruim."),
    ("Animais",
     r"\b(gato|gatos|cachorro|cachorros|lobo|lobos|passaro|passaros|cavalo|cavalos|aranha|aranhas)\b",
     "Animais costumam representar instintos e aspectos da sua personalidade."),
    ("Viagem",
     r"\b(viagem|viajando|aviao|trem|onibus|estrada|carro)\b",
     "Indica transição de fase e a direção que sua vida está tomando."),
    ("Estar sem roupa",
     r"\b(nu|nua|pelado|pelada)\b",
     "Costuma ligar-se à vulnerabilidade e ao medo de ser julgado."),
    ("Atraso ou perda",
     r"\b(atrasado|atrasada|atraso|perdido|perdida|perdendo)\b",
     "Pode refletir pressão de tempo ou receio de perder uma oportunidade."),
]

INTERPRETACOES_SONHO = [
    "Pode simbolizar mudanças, transições ou o desejo de deixar algo para trás.",
    "Pode refletir insegurança, pressão ou a sensação de estar diante de algo desconhecido.",
    "Talvez represente desejos, lembranças ou emoções que merecem mais atenção.",
    "Pode estar relacionado à forma como você lida com controle, liberdade e responsabilidade.",
    "Talvez seja uma maneira de sua mente reorganizar experiências recentes.",
    "Pode simbolizar um conflito interno ou duas vontades que parecem incompatíveis.",
    "Talvez represente a necessidade de descanso, segurança ou reconexão consigo mesmo.",
]


# ════════════════════════════════════════════════════════════════
# Dados — Presságios, rituais, amuletos
# ════════════════════════════════════════════════════════════════

PRESSAGIOS = [
    "🕯️ Uma chama se apagará antes que a noite termine.",
    "👁️ Alguém perceberá aquilo que você tentou esconder.",
    "🌫️ Nem todo caminho que desaparece está perdido.",
    "🪞 Cuidado com as respostas que refletem exatamente aquilo que você deseja ouvir.",
    "🐦 Três sinais passarão despercebidos antes do quarto.",
    "🌑 Quando tudo parecer quieto, preste atenção ao silêncio.",
    "⏳ Algo esquecido voltará à sua memória.",
    "🔔 Você ouvirá algo familiar em um lugar inesperado.",
    "🗝️ Uma pergunta antiga encontrará uma nova fechadura.",
    "🌀 Nem tudo que retorna deseja ser encontrado.",
    "🦉 Uma testemunha silenciosa guarda mais do que você imagina.",
    "🕸️ Um fio solto puxará toda a trama.",
    "🌒 A sombra de alguém chegará antes dele.",
    "📜 Uma carta nunca enviada mudará de dono.",
    "🥀 O que murchou em segredo florescerá à vista de todos.",
    "🌊 A maré levará algo que você julgava firme.",
    "🔥 Uma promessa dita em voz baixa será cobrada em voz alta.",
    "🪦 O que foi enterrado sem cerimônia pedirá um nome.",
]

PRAZOS_PRESSAGIO = [
    "Antes do próximo amanhecer",
    "Nos próximos três dias",
    "Antes do fim da semana",
    "Na próxima lua cheia",
    "Quando você menos esperar",
    "Antes que o mês termine",
]
INTENSIDADES_PRESSAGIO = ["Sussurro", "Aviso", "Alerta", "Prenúncio", "Sentença"]

RITUAL_OBJETOS = [
    "uma vela roxa", "um espelho coberto por um pano", "três moedas antigas",
    "um papel com um símbolo inventado", "uma pedra encontrada durante uma caminhada",
    "um sino pequeno", "uma chave sem fechadura", "um punhado de sal grosso",
    "uma pena escura", "um relógio parado", "um fio vermelho", "um frasco de água da chuva",
]
RITUAL_LOCAIS = [
    "em uma biblioteca abandonada", "sob a luz da lua", "diante de uma porta fechada",
    "no centro de um círculo desenhado no papel", "em uma sala silenciosa",
    "perto de uma janela aberta", "no último degrau de uma escada antiga",
    "em uma encruzilhada vazia", "no topo de uma torre esquecida",
    "à beira de um lago imóvel",
]
RITUAL_ETAPAS = [
    "Escreva uma pergunta e dobre o papel três vezes.",
    "Observe o objeto escolhido e invente uma história para ele.",
    "Dê um nome ao que você deseja encontrar em sua narrativa.",
    "Descreva um sinal que marcaria o início do ritual.",
    "Crie uma frase curta que represente a intenção da cerimônia.",
    "Finalize imaginando como o ambiente mudaria depois do ritual.",
    "Escolha um som que anuncie a abertura do ritual.",
    "Defina quem está proibido de entrar na cena e por quê.",
    "Decida o que precisa ser deixado para trás antes de continuar.",
    "Descreva o que o personagem sente ao completar o último gesto.",
]
RITUAL_ABERTURAS = [
    "Sombras que escutam,", "Chama que não queima,", "Guardiões do limiar,",
    "Silêncio antigo,", "Vento que carrega nomes,", "Noite que guarda segredos,",
]
RITUAL_FECHOS = [
    "mostrem o que está oculto.", "abram o caminho que a noite esconde.",
    "testemunhem esta promessa.", "deixem a história avançar.",
    "respondam sem mentir.", "lembrem-se de quem chama.",
]
RITUAL_EFEITOS = [
    "As velas tremem e uma resposta vaga surge na mente do personagem.",
    "Um símbolo aparece na parede e desaparece em seguida.",
    "O ambiente fica frio, como se algo tivesse acabado de sair.",
    "Um objeto da cena muda de lugar sem que ninguém perceba.",
    "Um som distante confirma que o ritual foi ouvido.",
    "Nada acontece de imediato, mas todos sentem que algo foi iniciado.",
]
RITUAL_COMPLICACOES = [
    "O ritual funciona, mas chama a atenção de alguém que não deveria saber dele.",
    "A resposta vem incompleta e só faz sentido mais tarde.",
    "Um participante esconde um segredo que enfraquece o ritual.",
    "O objeto usado se quebra e precisa ser substituído.",
    "O efeito dura pouco: ao amanhecer, tudo volta ao que era.",
    "O ritual revela algo que o grupo preferia não saber.",
]

AMULETO_NOMES = [
    "Olho de Corvo", "Lágrima de Prata", "Chave do Crepúsculo", "Escama de Névoa",
    "Pena do Último Aviso", "Moeda do Barqueiro", "Fio da Meia-Noite",
    "Espelho de Bolso", "Osso Polido", "Sino do Limiar", "Pedra do Eremita",
]
AMULETO_PODERES = [
    "Avisa quem o carrega quando uma mentira é dita por perto.",
    "Torna passos silenciosos por alguns instantes.",
    "Aquece quando há perigo à espreita.",
    "Faz lembrar um detalhe importante esquecido.",
    "Mostra o caminho de volta, mesmo no escuro.",
    "Atrai sorte pequena, mas constante.",
    "Abafa sons e impede que segredos escapem.",
]
AMULETO_PRECOS = [
    "Nunca funciona se estiver sendo observado.",
    "Pede um segredo novo a cada lua cheia.",
    "Esfria nas mãos de quem mente para si mesmo.",
    "Só funciona uma vez por dia.",
    "Some por alguns dias quando é usado em excesso.",
    "Exige que seu dono diga a verdade em voz alta uma vez por semana.",
]


# ════════════════════════════════════════════════════════════════
# Cog
# ════════════════════════════════════════════════════════════════

class Mystic(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Tratamento de erros do cog ─────────────────────────────
    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = (
                "🌫️ As energias precisam descansar. "
                f"Tente novamente em {error.retry_after:.0f}s."
            )
        else:
            log.error("Erro no comando místico", exc_info=error)
            msg = "🌑 Algo interferiu na conexão com o além. Tente novamente."

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # ── /bola8 ─────────────────────────────────────────────────
    @app_commands.command(
        name="bola8",
        description="Consulte a misteriosa Bola 8.",
    )
    @espera()
    @app_commands.describe(
        pergunta="Faça uma pergunta que possa ser respondida com sim ou não."
    )
    async def bola8(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 1, 300],
    ):
        tipo = random.choices(
            list(BOLA8), weights=[v[1] for v in BOLA8.values()]
        )[0]
        cor, _, respostas = BOLA8[tipo]

        embed = criar_embed("🔮 BOLA 8 MÍSTICA", cor=cor, rodape="O futuro é incerto.")
        embed.add_field(name="Sua pergunta", value=cortar(pergunta), inline=False)
        embed.add_field(
            name="Resposta do além", value=random.choice(respostas), inline=False
        )
        await interaction.response.send_message(embed=embed)

    # ── /tarot ─────────────────────────────────────────────────
    @app_commands.command(
        name="tarot",
        description="Tire cartas de tarot para sua pergunta.",
    )
    @espera()
    @app_commands.describe(
        pergunta="Pergunta ou assunto para sua leitura.",
        tipo="Uma carta ou tiragem de três cartas.",
    )
    @app_commands.choices(
        tipo=[
            app_commands.Choice(name="Uma carta", value=1),
            app_commands.Choice(name="Três cartas (passado, presente, futuro)", value=3),
        ]
    )
    async def tarot(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 1, 300],
        tipo: int = 1,
    ):
        cartas = random.sample(ARCANOS, k=tipo)

        if tipo == 1:
            nome, direito, invertido = cartas[0]
            invertida = random.random() < 0.3
            embed = criar_embed(
                f"🃏 Sua carta: {nome}" + (" (invertida)" if invertida else ""),
                invertido if invertida else direito,
                discord.Color.dark_purple(),
                "Leitura simbólica para entretenimento.",
            )
            embed.add_field(name="Sua questão", value=cortar(pergunta), inline=False)
        else:
            embed = criar_embed(
                "🃏 TIRAGEM DE TRÊS CARTAS",
                f"**Sua questão:** {cortar(pergunta, 300)}",
                discord.Color.dark_purple(),
                "Leitura simbólica para entretenimento.",
            )
            for posicao, (nome, direito, invertido) in zip(POSICOES_TAROT, cartas):
                invertida = random.random() < 0.3
                embed.add_field(
                    name=f"{posicao}: {nome}" + (" ↺" if invertida else ""),
                    value=invertido if invertida else direito,
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)

    # ── /runas ─────────────────────────────────────────────────
    @app_commands.command(
        name="runas",
        description="Lance runas do Futhark Antigo.",
    )
    @espera()
    @app_commands.describe(
        pergunta="Pergunta ou assunto para as runas.",
        quantidade="Quantas runas lançar (1 a 3).",
    )
    async def runas(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 1, 300],
        quantidade: app_commands.Range[int, 1, 3] = 1,
    ):
        sorteadas = random.sample(RUNAS, k=quantidade)

        embed = criar_embed(
            "ᚠ LANÇAMENTO DE RUNAS",
            f"**Sua questão:** {cortar(pergunta, 300)}",
            discord.Color.dark_gold(),
            "Leitura simbólica para entretenimento.",
        )
        for simbolo, nome, significado in sorteadas:
            embed.add_field(
                name=f"{simbolo} {nome}", value=significado, inline=False
            )
        await interaction.response.send_message(embed=embed)

    # ── /destino ───────────────────────────────────────────────
    @app_commands.command(
        name="destino",
        description="Descubra uma mensagem aleatória do destino.",
    )
    @espera()
    async def destino(self, interaction: discord.Interaction):
        embed = criar_embed(
            "🌌 MENSAGEM DO DESTINO",
            random.choice(MENSAGENS_DESTINO),
            discord.Color.blurple(),
            "O futuro não está escrito.",
        )
        embed.add_field(name="🔢 Número", value=str(random.randint(1, 60)), inline=True)
        embed.add_field(name="🎨 Cor", value=random.choice(CORES_DO_DIA), inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /horoscopo ─────────────────────────────────────────────
    @app_commands.command(
        name="horoscopo",
        description="Receba o horóscopo místico do dia para seu signo.",
    )
    @espera()
    @app_commands.describe(signo="Escolha seu signo.")
    @app_commands.choices(
        signo=[
            app_commands.Choice(name=f"{emoji} {nome}", value=nome)
            for emoji, nome, _ in SIGNOS
        ]
    )
    async def horoscopo(self, interaction: discord.Interaction, signo: str):
        emoji, nome, elemento = next(s for s in SIGNOS if s[1] == signo)
        rng = rng_do_dia("horoscopo", nome)

        embed = criar_embed(
            f"{emoji} {nome.upper()} • {elemento}",
            rng.choice(HOROSCOPO_GERAL),
            discord.Color.dark_magenta(),
            "O mesmo signo recebe o mesmo horóscopo durante o dia.",
        )
        embed.add_field(name="💞 Amor", value=rng.choice(HOROSCOPO_AMOR), inline=False)
        embed.add_field(
            name="💼 Trabalho", value=rng.choice(HOROSCOPO_TRABALHO), inline=False
        )
        embed.add_field(name="🔢 Número", value=str(rng.randint(1, 60)), inline=True)
        embed.add_field(name="🎨 Cor", value=rng.choice(CORES_DO_DIA), inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /numerologia ───────────────────────────────────────────
    @app_commands.command(
        name="numerologia",
        description="Descubra seu número de expressão e caminho de vida.",
    )
    @espera()
    @app_commands.describe(
        nome="Nome completo (sem números).",
        nascimento="Data de nascimento no formato DD/MM/AAAA (opcional).",
    )
    async def numerologia(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 2, 60],
        nascimento: Optional[str] = None,
    ):
        letras = [c for c in normalizar(nome) if c in TABELA_PITAGORICA]
        if not letras:
            await interaction.response.send_message(
                "🌫️ Não encontrei letras válidas nesse nome.", ephemeral=True
            )
            return

        expressao = reduzir(sum(TABELA_PITAGORICA[c] for c in letras))

        caminho = None
        if nascimento:
            try:
                data = datetime.strptime(nascimento.strip(), "%d/%m/%Y")
            except ValueError:
                await interaction.response.send_message(
                    "🌫️ Use a data no formato DD/MM/AAAA, por exemplo 25/12/1998.",
                    ephemeral=True,
                )
                return
            caminho = reduzir(sum(int(d) for d in data.strftime("%d%m%Y")))

        embed = criar_embed(
            "🔢 NUMEROLOGIA",
            f"**Nome:** {cortar(nome, 100)}",
            discord.Color.teal(),
            "Simbolismo para entretenimento.",
        )
        embed.add_field(
            name=f"Expressão: {expressao}",
            value=SIGNIFICADO_NUMEROS[expressao],
            inline=False,
        )
        if caminho is not None:
            embed.add_field(
                name=f"Caminho de vida: {caminho}",
                value=SIGNIFICADO_NUMEROS[caminho],
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    # ── /lua ───────────────────────────────────────────────────
    @app_commands.command(
        name="lua",
        description="Veja a fase atual da Lua e o que ela inspira.",
    )
    @espera()
    async def lua(self, interaction: discord.Interaction):
        indice, idade, iluminacao, ate_cheia, ate_nova = calcular_lua(
            datetime.now(timezone.utc)
        )
        nome, emoji, mensagem = FASES_LUA[indice]

        embed = criar_embed(
            f"{emoji} {nome.upper()}",
            mensagem,
            discord.Color.light_grey(),
            "Cálculo aproximado.",
        )
        embed.add_field(name="Iluminação", value=f"{iluminacao * 100:.0f}%", inline=True)
        embed.add_field(name="Idade da Lua", value=f"{idade:.1f} dias", inline=True)
        embed.add_field(
            name="Próximas fases",
            value=(
                f"🌕 Cheia em ~{ate_cheia:.0f} dia(s)\n"
                f"🌑 Nova em ~{ate_nova:.0f} dia(s)"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ── /aura ──────────────────────────────────────────────────
    @app_commands.command(
        name="aura",
        description="Descubra a cor da aura de alguém hoje.",
    )
    @espera()
    @app_commands.describe(pessoa="Quem terá a aura lida (padrão: você).")
    async def aura(
        self,
        interaction: discord.Interaction,
        pessoa: Optional[discord.Member] = None,
    ):
        alvo = pessoa or interaction.user
        nome, cor, significado = rng_do_dia("aura", alvo.id).choice(AURAS)

        embed = criar_embed(
            f"✨ AURA {nome.upper()}",
            f"{alvo.mention}: {significado}",
            discord.Color(cor),
            "A aura muda a cada dia.",
        )
        await interaction.response.send_message(embed=embed)

    # ── /compatibilidade ───────────────────────────────────────
    @app_commands.command(
        name="compatibilidade",
        description="Meça a afinidade mística entre você e outra pessoa.",
    )
    @espera()
    @app_commands.describe(pessoa="Com quem você quer comparar sua energia.")
    async def compatibilidade(
        self,
        interaction: discord.Interaction,
        pessoa: discord.Member,
    ):
        if pessoa.id == interaction.user.id:
            await interaction.response.send_message(
                "🪞 Você consigo mesmo: 100%. O espelho não discorda.",
                ephemeral=True,
            )
            return

        ids = "-".join(str(i) for i in sorted((interaction.user.id, pessoa.id)))
        porcentagem = int(hashlib.sha256(ids.encode()).hexdigest(), 16) % 101

        if porcentagem >= 90:
            leitura = "Conexão rara. Os astros mal conseguem esconder o entusiasmo."
        elif porcentagem >= 70:
            leitura = "Boa sintonia. As energias se completam."
        elif porcentagem >= 50:
            leitura = "Afinidade moderada. Diálogo e paciência fazem a diferença."
        elif porcentagem >= 30:
            leitura = "Energias diferentes, o que também pode ensinar muito."
        else:
            leitura = "Caminhos opostos, mas até os opostos às vezes se cruzam."

        embed = criar_embed(
            "💞 COMPATIBILIDADE MÍSTICA",
            f"{interaction.user.mention} ✦ {pessoa.mention}",
            discord.Color.magenta(),
            "Resultado fixo para a mesma dupla. Só diversão.",
        )
        embed.add_field(
            name=f"{porcentagem}%",
            value=f"{barra(porcentagem // 10, 10)}\n{leitura}",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ── /sonho ─────────────────────────────────────────────────
    @app_commands.command(
        name="sonho",
        description="Receba uma interpretação simbólica de um sonho.",
    )
    @espera()
    @app_commands.describe(
        relato="Descreva brevemente o sonho que você teve.",
        privado="Mostrar a resposta só para você (padrão: sim).",
    )
    async def sonho(
        self,
        interaction: discord.Interaction,
        relato: app_commands.Range[str, 3, 800],
        privado: bool = True,
    ):
        texto = normalizar(relato)
        encontrados = [
            (nome, interp)
            for nome, padrao, interp in SIMBOLOS_SONHO
            if re.search(padrao, texto)
        ][:3]

        embed = criar_embed(
            "🌙 INTERPRETADOR DE SONHOS",
            cor=discord.Color.dark_purple(),
            rodape="Interpretação criativa, não uma análise psicológica.",
        )
        embed.add_field(name="Seu sonho", value=cortar(relato), inline=False)

        if encontrados:
            embed.add_field(
                name="Símbolos encontrados",
                value="\n".join(f"**{n}**: {i}" for n, i in encontrados),
                inline=False,
            )
        embed.add_field(
            name="Leitura geral",
            value=random.choice(INTERPRETACOES_SONHO),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=privado)

    # ── /pressagio ─────────────────────────────────────────────
    @app_commands.command(
        name="pressagio",
        description="Receba um presságio sombrio e misterioso.",
    )
    @espera()
    async def pressagio(self, interaction: discord.Interaction):
        nivel = random.randint(1, 5)

        embed = criar_embed(
            "👁️ PRESSÁGIO",
            random.choice(PRESSAGIOS),
            discord.Color.dark_red(),
            "As sombras observam.",
        )
        embed.add_field(
            name="⏳ Prazo", value=random.choice(PRAZOS_PRESSAGIO), inline=True
        )
        embed.add_field(
            name="🕯️ Intensidade",
            value=f"{barra(nivel, 5)} {INTENSIDADES_PRESSAGIO[nivel - 1]}",
            inline=True,
        )
        await interaction.response.send_message(embed=embed)

    # ── /ritual ────────────────────────────────────────────────
    @app_commands.command(
        name="ritual",
        description="Gere um ritual fictício para sua história ou RPG.",
    )
    @espera()
    async def ritual(self, interaction: discord.Interaction):
        etapas = random.sample(RITUAL_ETAPAS, k=3)
        invocacao = f"{random.choice(RITUAL_ABERTURAS)} {random.choice(RITUAL_FECHOS)}"

        embed = criar_embed(
            "🕯️ GERADOR DE RITUAIS FICTÍCIOS",
            "Um ritual para histórias, campanhas de RPG e construção de atmosfera.",
            discord.Color.dark_red(),
            "Ficção e interpretação narrativa; não é um ritual real.",
        )
        embed.add_field(
            name="🕯️ Objeto simbólico", value=random.choice(RITUAL_OBJETOS), inline=True
        )
        embed.add_field(
            name="🌒 Cenário", value=random.choice(RITUAL_LOCAIS), inline=True
        )
        embed.add_field(
            name="📜 Etapas",
            value="\n".join(f"{n}. {e}" for n, e in enumerate(etapas, start=1)),
            inline=False,
        )
        embed.add_field(name="🗣️ Invocação", value=f"*“{invocacao}”*", inline=False)
        embed.add_field(
            name="✨ Efeito narrativo", value=random.choice(RITUAL_EFEITOS), inline=False
        )
        embed.add_field(
            name="⚠️ Complicação (para RPG)",
            value=random.choice(RITUAL_COMPLICACOES),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    # ── /amuleto ───────────────────────────────────────────────
    @app_commands.command(
        name="amuleto",
        description="Gere um amuleto fictício com poder e preço.",
    )
    @espera()
    async def amuleto(self, interaction: discord.Interaction):
        embed = criar_embed(
            f"🧿 {random.choice(AMULETO_NOMES).upper()}",
            cor=discord.Color.dark_teal(),
            rodape="Item fictício para histórias e RPG.",
        )
        embed.add_field(
            name="✨ Poder", value=random.choice(AMULETO_PODERES), inline=False
        )
        embed.add_field(
            name="⚖️ Preço", value=random.choice(AMULETO_PRECOS), inline=False
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Mystic(bot))
