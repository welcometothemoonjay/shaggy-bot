"""
SALÃO DA RUPTURA — CASSINO DO SHAGGY BOT (SFA: Segredo Floresta Adentro)
=========================================================================

Cog independente: coloque em  projeto/cogs/cassino.py
O main.py já carrega automaticamente todo *.py de /cogs (nenhuma alteração
é necessária). Requer o cog XpAndCoins carregado (ele guarda o Abysmus).

AVISO DE CÂNONE
---------------
O Salão, seus NPCs (Sineta, Ostrovan, Tarkhal, a Crupiê Sem Ponteiros, o
Autômato Lúcido, o Agenciador de Dedos Longos, o Oráculo Vesga, o
Colecionador Vesperal e o Fiscal Olho-de-Sal) e os nomes dos degraus da
Travessia são PROPOSTA DE EXPANSÃO, ainda não estabelecida no cânone de SFA.
Nenhuma força cósmica aparece como personagem; o texto só cita lugares e
conceitos já usados no projeto (Da'kor, Véu, Era a Vapor, Futuro Distorcido,
Abysmus, Ruptura Temporal).

ECONOMIA (resumo)
-----------------
- O saldo vive SOMENTE em XpAndCoins (user_stats.coins). O cassino usa a API
  existente: transacao(), obter_saldo_tx() e alterar_coins_tx().
- Toda mudança de saldo + registro da partida + estatísticas acontece na
  MESMA transação SQLite (tudo ou nada).
- Jogos instantâneos: cobrança e prêmio numa única transação.
- Jogos interativos (Blackjack, Travessia): a aposta é debitada ao abrir a
  partida (estado 'aberta'); o prêmio só é pago uma vez, por UPDATE
  condicional ('aberta' -> 'paga'). Partidas órfãs (queda do bot) são
  estornadas na próxima inicialização/descarga do cog.
- Como o Abysmus é raro (1 por nível), as apostas padrão são pequenas
  (APOSTA_MIN/APOSTA_MAX). Ajuste na seção 1.

RETORNO TEÓRICO AO JOGADOR (RTP) — calculado por enumeração nos testes
----------------------------------------------------------------------
Roleta (37 casas)      36/37 = 97,30% em todas as modalidades
Cara ou Coroa          98,00% (2% das vezes a moeda cai em pé: a casa vence)
Dados: soma exata      83,3% a 97,2% (tabela exibida no jogo)
Dados: Alto/Baixo      94,44% (o 7 devolve a aposta; 2 e 12 são da casa)
Dados: Face 6          91,67%
Caça-Níquel            ver SLOT_* (calculado em rtp_slots())
Blackjack              sem dobrar/dividir; banca para no 17; natural 3:2
                       (arredondado para baixo): vantagem da banca > 0
Travessia das Fendas   no máximo 96% com a melhor estratégia possível
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from typing import Callable, NamedTuple, Optional, Sequence

import discord
from discord import app_commands
from discord.ext import commands


log = logging.getLogger("shaggy.cassino")


# ============================================================
# 1. CONFIGURAÇÕES CENTRAIS (ajuste o equilíbrio aqui)
# ============================================================

# Apostas em Abysmus (inteiros). Padrão conservador: o Abysmus é raro.
APOSTA_MIN = 1
APOSTA_MAX = 10

# Sobrescritas por jogo: {"chave_do_jogo": (minimo, maximo)}
LIMITES_APOSTA: dict[str, tuple[int, int]] = {}

# Intervalo mínimo entre o início de duas partidas do mesmo jogador.
COOLDOWN_JOGADA_SEGUNDOS = 2.0

# Inatividade (segundos) antes dos controles expirarem.
TIMEOUT_MENU = 180
TIMEOUT_PARTIDA = 120

# Lucro líquido a partir do qual o salão comenta o feito no canal.
ANUNCIAR_LUCRO_MINIMO = 20

# Trava de segurança contra bugs: nenhum prêmio pode passar disto × aposta.
MULTIPLICADOR_MAXIMO_ABSOLUTO = 500

# Linhas do histórico nas estatísticas.
HISTORICO_LINHAS = 5

# Gerador criptograficamente seguro (resultado sempre decidido no servidor).
RNG = random.SystemRandom()

# --- Roleta ---
ROLETA_VERMELHOS = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)
# chave: (rótulo, multiplicador bruto, casos favoráveis em 37)
ROLETA_TIPOS: dict[str, tuple[str, int, int]] = {
    "numero": ("Número exato", 36, 1),
    "vermelho": ("Carmesim (vermelho)", 2, 18),
    "preto": ("Fuligem (preto)", 2, 18),
    "par": ("Par", 2, 18),
    "impar": ("Ímpar", 2, 18),
    "baixo": ("Baixos (1–18)", 2, 18),
    "alto": ("Altos (19–36)", 2, 18),
    "duzia1": ("1ª dúzia (1–12)", 3, 12),
    "duzia2": ("2ª dúzia (13–24)", 3, 12),
    "duzia3": ("3ª dúzia (25–36)", 3, 12),
}

# --- Cara ou Coroa do Abismo ---
MOEDA_BORDA_EM_100 = 2      # chance (em 100) de a moeda cair em pé
MOEDA_MULTIPLICADOR = 2

# --- Dados Amaldiçoados (2d6) ---
DADOS_RTP_SOMA_PCT = 98     # teto de RTP usado para a tabela de soma exata
DADOS_MULT_ALTO_BAIXO = 2
DADOS_MULT_FACE6 = 3

# --- Caça-Níquel Temporal (3 rolos iguais, 20 posições por rolo) ---
SLOT_SIMBOLOS: dict[str, tuple[str, int]] = {
    "engrenagem": ("⚙️", 8),
    "chama": ("🔥", 5),
    "olho": ("👁️", 3),
    "reliquia": ("🗝️", 3),
    "anomalia": ("🌀", 1),
}
SLOT_TRIPLO = {"engrenagem": 5, "chama": 10, "olho": 25,
               "reliquia": 40, "anomalia": 100}
# Dois símbolos iguais nos DOIS PRIMEIROS rolos (e terceiro diferente).
SLOT_PAR_ESQUERDA = {"engrenagem": 1, "chama": 1, "olho": 2,
                     "reliquia": 2, "anomalia": 3}

# --- Blackjack das Almas ---
BLACKJACK_BARALHOS = 6
BLACKJACK_BANCA_PARA_EM = 17
BLACKJACK_NATURAL = (3, 2)   # arredondado para baixo (moeda inteira)

# --- Travessia das Fendas (jogo exclusivo de SFA) ---
# (multiplicador bruto ao recolher naquele degrau, nome do degrau)
TRAVESSIA_DEGRAUS: tuple[tuple[int, str], ...] = (
    (1, "Soleira do Salão"),
    (2, "Orla de Da'kor"),
    (3, "Trilhos da Era a Vapor"),
    (4, "Corredor do Futuro Distorcido"),
    (6, "Além da Névoa"),
    (8, "Galeria Deslocada"),
    (12, "O Cofre Fora do Tempo"),
)
# Cada opção de passo tem chance = floor(96% × valor atual / valor destino).
TRAVESSIA_RTP_PCT = 96


# ============================================================
# 2. EXCEÇÕES E MODELOS
# ============================================================

class ErroCassino(Exception):
    """Base dos erros do cassino."""


class EconomiaIndisponivel(ErroCassino):
    """XpAndCoins não está carregado."""


class ApostaInvalida(ErroCassino):
    pass


class SaldoInsuficiente(ErroCassino):
    def __init__(self, saldo: int, necessario: int):
        super().__init__(f"Saldo {saldo} < aposta {necessario}")
        self.saldo = saldo
        self.necessario = necessario


class PartidaEmAndamento(ErroCassino):
    pass


class PartidaJaEncerrada(ErroCassino):
    pass


class PartidaInvalida(ErroCassino):
    pass


def limites_aposta(jogo: str) -> tuple[int, int]:
    return LIMITES_APOSTA.get(jogo, (APOSTA_MIN, APOSTA_MAX))


def fmt(n: int) -> str:
    """Número com separador de milhar no padrão brasileiro."""
    return f"{n:,}".replace(",", ".")


@dataclass
class Jogada:
    """Resultado já sorteado de uma rodada instantânea (ainda não paga)."""
    premio: int                 # prêmio BRUTO (0 = perdeu tudo)
    resumo: str                 # texto do que foi sorteado
    detalhe: str                # texto curto para o histórico/log
    flags: tuple[str, ...] = ()


# ============================================================
# 3. NPCs (PROPOSTA DE EXPANSÃO — não é cânone)
# ============================================================

@dataclass(frozen=True)
class Npc:
    chave: str
    nome: str
    cargo: str
    emoji: str
    cor: int
    apresentacao: str
    falas: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def fala(self, situacao: str) -> str:
        opcoes = self.falas.get(situacao) or self.falas.get("geral") or ("...",)
        return random.choice(opcoes)


NPCS: dict[str, Npc] = {}


def registrar_npc(npc: Npc) -> Npc:
    NPCS[npc.chave] = npc
    return npc


registrar_npc(Npc(
    "sineta", "Sineta", "Recepcionista", "🔔", 0x6A4C93,
    "Um sino de bronze que flutua sobre o balcão e fala com a voz da última "
    "pessoa que você ouviu.",
    {"geral": (
        "Bem-vindo ao Salão. A porta pela qual você entrou não existia "
        "ontem. Nem amanhã.",
        "Fichas, não. Aqui só se aposta Abysmus. Troco em silêncio.",
        "Sente-se onde a luz parecer menos honesta.",
    )},
))
registrar_npc(Npc(
    "ostrovan", "Ostrovan Cobre-e-Cinza", "Banqueiro", "🏦", 0xB87333,
    "Um escriturário de cobre e vapor que confere cada moeda duas vezes e "
    "desconfia de todas.",
    {"geral": (
        "Seu saldo é o que o cofre diz. O cofre não erra, apenas atrasa.",
        "Nada de crédito. O tempo aqui é caro demais para ser emprestado.",
    )},
))
registrar_npc(Npc(
    "tarkhal", "Mestre Tarkhal", "Mestre das Apostas", "🎩", 0x8B1E3F,
    "Veste um casaco de fuligem e anuncia as probabilidades como quem lê "
    "sentenças.",
    {
        "boas_vindas": (
            "Todas as chances estão escritas. Poucos leem.",
            "A roda não é cruel. É exata.",
        ),
        "vitoria": ("A Ruptura sorriu. Raro. Aproveite.",
                    "Contabilizado. Não se acostume."),
        "derrota": ("A casa agradece sua contribuição ao Véu.",
                    "O acaso não tem rancor. Só memória curta."),
        "empate": ("Nem ganho, nem perda. O tempo apenas passou.",),
    },
))
registrar_npc(Npc(
    "crupie", "A Crupiê Sem Ponteiros", "Crupiê", "🕰️", 0x2E4057,
    "Seu rosto é um relógio sem ponteiros. Ela embaralha almas e chama isso "
    "de cartas.",
    {
        "boas_vindas": ("Peça uma carta ou aceite a que já tem. "
                        "Ambas custam alguma coisa.",),
        "vitoria": ("Vinte e um instantes a seu favor. Quanta sorte.",
                    "Você me derrotou. Eu estava distraída com o tempo."),
        "derrota": ("A banca sempre cobra.", "Mais um nome para o baralho."),
        "empate": ("Um instante empatado não pertence a ninguém.",),
    },
))
registrar_npc(Npc(
    "automato", "O Autômato Lúcido", "Operador dos Rolos", "⚙️", 0x5C6B73,
    "Uma máquina a vapor que enxerga demais. Seus rolos giram com símbolos "
    "recolhidos de eras diferentes.",
    {
        "boas_vindas": ("Rolos aquecidos. Eras alinhadas. Quase.",),
        "vitoria": ("Os símbolos se alinharam. Eu avisei: lúcido.",),
        "derrota": ("Ruído de engrenagens. Nada além disso.",),
    },
))
registrar_npc(Npc(
    "agenciador", "O Agenciador de Dedos Longos", "Agenciador de Riscos",
    "🕯️", 0x3D348B,
    "Magro demais para estar inteiro. Vende caminhos entre eras e cobra pela "
    "possibilidade de voltar.",
    {
        "boas_vindas": ("Toda fenda tem um preço. A minha é honesta: "
                        "mostro as chances antes.",),
        "vitoria": ("Você atravessou. Poucos conseguem recolher a tempo.",),
        "derrota": ("A fenda se fechou. Ela não gosta de plateia.",),
    },
))
registrar_npc(Npc(
    "oraculo", "Oráculo Vesga", "Oráculo da Ruptura", "👁️", 0x7B2CBF,
    "Olha para dois lugares ao mesmo tempo, nenhum deles é o presente.",
    {"geral": ("Eu vejo o que ainda não foi sorteado. Não posso dizer. "
               "Posso insinuar.",)},
))
registrar_npc(Npc(
    "colecionador", "O Colecionador Vesperal", "Colecionador de Relíquias",
    "🗝️", 0xC9A227,
    "Guarda títulos como outros guardam moedas. Nunca vende nada.",
    {"geral": ("Cada título é uma lembrança que o Salão decidiu manter.",)},
))
registrar_npc(Npc(
    "fiscal", "Fiscal Olho-de-Sal", "Fiscal do Abismo", "🧂", 0xA61C1C,
    "Observa tudo com um único olho cristalizado. Não pisca. Não perdoa "
    "duas vezes.",
    {
        "intruso": ("Esta mesa não é sua. Vá procurar a sua.",),
        "cooldown": ("Devagar. A Ruptura não gosta de pressa.",
                     "Uma mesa por vez. O tempo precisa respirar."),
        "saldo": ("Sem Abysmus, sem aposta. O Salão não aceita promessas.",),
        "erro": ("Algo vacilou nas engrenagens. Seu saldo está protegido.",),
        "partida": ("Você já tem uma partida aberta. Termine-a primeiro.",),
    },
))

PRESSAGIOS = (
    "A névoa violeta recuou três passos hoje. Dizem que é bom sinal.",
    "Os relógios do Salão discordam entre si. Nada de anormal.",
    "Um corvo de névoa pousou na roleta e saiu sem apostar.",
    "As engrenagens estão quentes. Ou alguém as aqueceu por dentro.",
    "A Luminária tremeu uma vez. Só uma.",
    "Há um degrau a mais na escada hoje. Ninguém o contou.",
    "O Véu está fino em algum lugar perto da mesa de cartas.",
)


def pressagio_do_dia(hoje: Optional[date] = None) -> str:
    """Flavor puramente cosmético: NÃO altera nenhuma probabilidade."""
    hoje = hoje or date.today()
    return PRESSAGIOS[hoje.toordinal() % len(PRESSAGIOS)]


# ============================================================
# 4. LÓGICA PURA DOS JOGOS (sem Discord, sem banco; testável)
# ============================================================

# ---------- Roleta ----------

def roleta_cor(numero: int) -> str:
    if numero == 0:
        return "verde"
    return "vermelho" if numero in ROLETA_VERMELHOS else "preto"


def roleta_vence(tipo: str, sorteado: int, escolha: Optional[int] = None) -> bool:
    if tipo == "numero":
        return escolha is not None and sorteado == escolha
    if sorteado == 0:           # a Fenda: só paga o número exato
        return False
    if tipo == "vermelho":
        return roleta_cor(sorteado) == "vermelho"
    if tipo == "preto":
        return roleta_cor(sorteado) == "preto"
    if tipo == "par":
        return sorteado % 2 == 0
    if tipo == "impar":
        return sorteado % 2 == 1
    if tipo == "baixo":
        return 1 <= sorteado <= 18
    if tipo == "alto":
        return 19 <= sorteado <= 36
    if tipo == "duzia1":
        return 1 <= sorteado <= 12
    if tipo == "duzia2":
        return 13 <= sorteado <= 24
    if tipo == "duzia3":
        return 25 <= sorteado <= 36
    raise ValueError(f"Tipo de aposta desconhecido: {tipo}")


def multiplicador_roleta(tipo: str, sorteado: int,
                         escolha: Optional[int] = None) -> int:
    if tipo not in ROLETA_TIPOS:
        raise ValueError(f"Tipo de aposta desconhecido: {tipo}")
    return ROLETA_TIPOS[tipo][1] if roleta_vence(tipo, sorteado, escolha) else 0


def rtp_roleta(tipo: str) -> Fraction:
    _, mult, casos = ROLETA_TIPOS[tipo]
    return Fraction(casos * mult, 37)


# ---------- Cara ou Coroa ----------

def lancar_moeda(rng=RNG) -> str:
    """'cara', 'coroa' ou 'borda' (moeda em pé; a casa vence)."""
    r = rng.randrange(100)
    metade = (100 - MOEDA_BORDA_EM_100) // 2
    if r < MOEDA_BORDA_EM_100:
        return "borda"
    return "cara" if r < MOEDA_BORDA_EM_100 + metade else "coroa"


def rtp_moeda() -> Fraction:
    metade = (100 - MOEDA_BORDA_EM_100) // 2
    return Fraction(metade * MOEDA_MULTIPLICADOR, 100)


# ---------- Dados ----------

def formas_soma(soma: int) -> int:
    """Combinações de 2d6 que resultam na soma (em 36)."""
    return 6 - abs(soma - 7) if 2 <= soma <= 12 else 0


def multiplicador_soma(soma: int) -> int:
    formas = formas_soma(soma)
    return (36 * DADOS_RTP_SOMA_PCT) // (100 * formas)


def multiplicador_dados(modalidade: str, d1: int, d2: int) -> int:
    soma = d1 + d2
    if modalidade.startswith("soma_"):
        alvo = int(modalidade.split("_")[1])
        return multiplicador_soma(alvo) if soma == alvo else 0
    if modalidade == "alto":      # 8–11 paga; 7 devolve; 12 e ≤6 perdem
        if 8 <= soma <= 11:
            return DADOS_MULT_ALTO_BAIXO
        return 1 if soma == 7 else 0
    if modalidade == "baixo":     # 3–6 paga; 7 devolve; 2 e ≥8 perdem
        if 3 <= soma <= 6:
            return DADOS_MULT_ALTO_BAIXO
        return 1 if soma == 7 else 0
    if modalidade == "face6":
        return DADOS_MULT_FACE6 if 6 in (d1, d2) else 0
    raise ValueError(f"Modalidade desconhecida: {modalidade}")


def rtp_dados(modalidade: str) -> Fraction:
    total = sum(
        multiplicador_dados(modalidade, a, b)
        for a in range(1, 7) for b in range(1, 7)
    )
    return Fraction(total, 36)


def modalidades_dados() -> list[str]:
    return [f"soma_{n}" for n in range(2, 13)] + ["alto", "baixo", "face6"]


# ---------- Caça-Níquel ----------

def girar_slots(rng=RNG) -> tuple[str, str, str]:
    chaves = list(SLOT_SIMBOLOS)
    pesos = [SLOT_SIMBOLOS[c][1] for c in chaves]
    a, b, c = rng.choices(chaves, weights=pesos, k=3)
    return a, b, c


def multiplicador_slots(rolos: Sequence[str]) -> int:
    a, b, c = rolos
    if a == b == c:
        return SLOT_TRIPLO[a]
    if a == b:
        return SLOT_PAR_ESQUERDA[a]
    return 0


def rtp_slots() -> Fraction:
    chaves = list(SLOT_SIMBOLOS)
    total_pesos = sum(SLOT_SIMBOLOS[c][1] for c in chaves)
    soma = Fraction(0)
    for a in chaves:
        for b in chaves:
            for c in chaves:
                p = Fraction(
                    SLOT_SIMBOLOS[a][1] * SLOT_SIMBOLOS[b][1]
                    * SLOT_SIMBOLOS[c][1], total_pesos ** 3,
                )
                soma += p * multiplicador_slots((a, b, c))
    return soma


# ---------- Blackjack ----------

class Carta(NamedTuple):
    face: str
    naipe: str

    @property
    def pontos(self) -> int:
        if self.face == "A":
            return 11
        if self.face in ("J", "Q", "K"):
            return 10
        return int(self.face)

    def __str__(self) -> str:
        return f"{self.face}{self.naipe}"


FACES = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
NAIPES = ("♠", "♥", "♦", "♣")


def pontos_mao(cartas: Sequence[Carta]) -> tuple[int, bool]:
    """(total, mão_é_soft). Ás vale 11 e cai para 1 quando necessário."""
    total = sum(c.pontos for c in cartas)
    ases = sum(1 for c in cartas if c.face == "A")
    while total > 21 and ases:
        total -= 10
        ases -= 1
    return total, ases > 0


def eh_natural(cartas: Sequence[Carta]) -> bool:
    return len(cartas) == 2 and pontos_mao(cartas)[0] == 21


class BlackjackPartida:
    """
    Regras: 6 baralhos embaralhados a cada mão; banca revela e compra até
    17 (para em todo 17, inclusive soft 17); natural paga 3:2 (arredondado
    para baixo); empate devolve a aposta; sem dobrar, dividir ou render.

    Para testes, `baralho` pode ser injetado: as cartas saem do FIM da lista.
    """

    def __init__(self, rng=RNG, baralho: Optional[Sequence[Carta]] = None):
        self.rng = rng
        if baralho is not None:
            self.baralho = list(baralho)
        else:
            self.baralho = [
                Carta(f, n)
                for _ in range(BLACKJACK_BARALHOS)
                for f in FACES for n in NAIPES
            ]
            rng.shuffle(self.baralho)
        self.jogador: list[Carta] = []
        self.banca: list[Carta] = []
        self.terminou = False
        self.resultado: Optional[str] = None   # blackjack|vitoria|empate|derrota
        self.motivo = ""

    def _puxar(self) -> Carta:
        return self.baralho.pop()

    def iniciar(self) -> None:
        self.jogador = [self._puxar()]
        self.banca = [self._puxar()]
        self.jogador.append(self._puxar())
        self.banca.append(self._puxar())

        nat_j, nat_b = eh_natural(self.jogador), eh_natural(self.banca)
        if nat_j and nat_b:
            self._encerrar("empate", "Dois naturais: empate.")
        elif nat_j:
            self._encerrar("blackjack", "Blackjack natural!")
        elif nat_b:
            self._encerrar("derrota", "A banca tinha um natural.")

    def _encerrar(self, resultado: str, motivo: str) -> None:
        self.terminou = True
        self.resultado = resultado
        self.motivo = motivo

    def comprar(self) -> None:
        if self.terminou:
            raise ValueError("A mão já terminou.")
        self.jogador.append(self._puxar())
        total, _ = pontos_mao(self.jogador)
        if total > 21:
            self._encerrar("derrota", "Você estourou.")
        elif total == 21:
            self.parar()

    def parar(self) -> None:
        if self.terminou:
            raise ValueError("A mão já terminou.")
        while pontos_mao(self.banca)[0] < BLACKJACK_BANCA_PARA_EM:
            self.banca.append(self._puxar())
        tj = pontos_mao(self.jogador)[0]
        tb = pontos_mao(self.banca)[0]
        if tb > 21:
            self._encerrar("vitoria", "A banca estourou.")
        elif tj > tb:
            self._encerrar("vitoria", f"{tj} contra {tb}.")
        elif tj < tb:
            self._encerrar("derrota", f"{tj} contra {tb}.")
        else:
            self._encerrar("empate", f"Empate em {tj}.")

    def premio_bruto(self, aposta: int) -> int:
        if not self.terminou:
            raise ValueError("A mão ainda está em andamento.")
        if self.resultado == "blackjack":
            num, den = BLACKJACK_NATURAL
            return aposta + (aposta * num) // den
        if self.resultado == "vitoria":
            return aposta * 2
        if self.resultado == "empate":
            return aposta
        return 0


# ---------- Travessia das Fendas ----------

def travessia_destino(degrau: int, salto: bool) -> Optional[int]:
    destino = degrau + (2 if salto else 1)
    # Não se salta direto para o fim se não houver degrau: limita ao topo.
    if destino >= len(TRAVESSIA_DEGRAUS):
        return None
    return destino


def travessia_chance(degrau: int, salto: bool) -> Optional[int]:
    """Chance de sobreviver ao passo, em % inteiros (None = passo inexistente).

    chance = floor(RTP × valor_atual / valor_destino): o valor esperado de
    qualquer passo nunca passa de TRAVESSIA_RTP_PCT% do valor atual.
    """
    destino = travessia_destino(degrau, salto)
    if destino is None:
        return None
    atual = TRAVESSIA_DEGRAUS[degrau][0]
    alvo = TRAVESSIA_DEGRAUS[destino][0]
    return (TRAVESSIA_RTP_PCT * atual) // alvo


def travessia_rtp_maximo() -> Fraction:
    """RTP com a estratégia ÓTIMA (programação dinâmica sobre os degraus)."""
    n = len(TRAVESSIA_DEGRAUS)
    valor = [Fraction(0)] * n
    valor[n - 1] = Fraction(TRAVESSIA_DEGRAUS[n - 1][0])
    for k in range(n - 2, -1, -1):
        melhor = Fraction(TRAVESSIA_DEGRAUS[k][0]) if k > 0 else Fraction(0)
        for salto in (False, True):
            p = travessia_chance(k, salto)
            destino = travessia_destino(k, salto)
            if p is not None and destino is not None:
                melhor = max(melhor, Fraction(p, 100) * valor[destino])
        valor[k] = melhor
    return valor[0] / TRAVESSIA_DEGRAUS[0][0]


# ============================================================
# 5. CONQUISTAS E TÍTULOS (cosméticos; não pagam Abysmus)
# ============================================================

@dataclass
class ContextoConquista:
    jogo: str
    partidas: int
    jogos_distintos: int
    vitorias: int
    maior_premio: int
    flags: frozenset


@dataclass(frozen=True)
class Conquista:
    chave: str
    titulo: str
    nome: str
    descricao: str
    condicao: Callable[[ContextoConquista], bool]
    secreta: bool = False


CONQUISTAS: list[Conquista] = []


def registrar_conquista(c: Conquista) -> Conquista:
    CONQUISTAS.append(c)
    return c


registrar_conquista(Conquista(
    "primeira_ficha", "Visitante do Salão", "Primeira Aposta",
    "Faça sua primeira aposta no Salão.", lambda c: c.partidas >= 1))
registrar_conquista(Conquista(
    "todas_as_mesas", "Andarilho das Mesas", "Todas as Mesas",
    "Jogue todas as modalidades do Salão.",
    lambda c: c.jogos_distintos >= len(JOGOS)))
registrar_conquista(Conquista(
    "veterano", "Veterano do Salão", "Cinquenta Rodadas",
    "Complete 50 partidas.", lambda c: c.partidas >= 50))
registrar_conquista(Conquista(
    "mao_cheia", "Mão Cheia de Abysmus", "Grande Prêmio",
    "Receba um prêmio bruto de 50 Abysmus ou mais numa partida.",
    lambda c: c.maior_premio >= 50))
registrar_conquista(Conquista(
    "pleno", "Favorecido pela Fenda", "Pleno na Roleta",
    "Acerte um número exato na Roleta da Ruptura.",
    lambda c: "roleta_pleno" in c.flags))
registrar_conquista(Conquista(
    "vinte_e_um", "Alma de Vinte e Um", "Natural",
    "Receba um blackjack natural.",
    lambda c: "blackjack_natural" in c.flags))
registrar_conquista(Conquista(
    "cruzador", "Cruzador de Eras", "Cofre Fora do Tempo",
    "Alcance o último degrau da Travessia das Fendas.",
    lambda c: "travessia_topo" in c.flags))
registrar_conquista(Conquista(
    "borda", "Testemunha da Borda", "A Moeda em Pé",
    "Veja a moeda do Abismo cair em pé.",
    lambda c: "moeda_borda" in c.flags, secreta=True))
registrar_conquista(Conquista(
    "anomalia", "Olho da Anomalia", "Três Anomalias",
    "Alinhe três Anomalias no Caça-Níquel Temporal.",
    lambda c: "slot_jackpot" in c.flags, secreta=True))


# ============================================================
# 6. CAMADA FINANCEIRA E PERSISTÊNCIA
# Usa a API REAL do XpAndCoins: transacao(), obter_saldo_tx(),
# alterar_coins_tx() e obter_dados(). Nunca altera user_stats por SQL próprio.
# ============================================================

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS cassino_partidas (
        id TEXT PRIMARY KEY,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        jogo TEXT NOT NULL,
        aposta INTEGER NOT NULL,
        premio INTEGER NOT NULL DEFAULT 0,
        estado TEXT NOT NULL,
        detalhe TEXT NOT NULL DEFAULT '',
        criado REAL NOT NULL,
        fechado REAL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_cassino_partidas_usuario
    ON cassino_partidas (guild_id, user_id, estado)
    """,
    """
    CREATE TABLE IF NOT EXISTS cassino_stats (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        jogo TEXT NOT NULL,
        partidas INTEGER NOT NULL DEFAULT 0,
        vitorias INTEGER NOT NULL DEFAULT 0,
        derrotas INTEGER NOT NULL DEFAULT 0,
        empates INTEGER NOT NULL DEFAULT 0,
        apostado INTEGER NOT NULL DEFAULT 0,
        premios INTEGER NOT NULL DEFAULT 0,
        maior_premio INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, jogo)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cassino_conquistas (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        chave TEXT NOT NULL,
        desbloqueada REAL NOT NULL,
        PRIMARY KEY (guild_id, user_id, chave)
    )
    """,
)


@dataclass
class Liquidacao:
    partida_id: str
    jogo: str
    aposta: int
    premio: int
    saldo_final: int
    conquistas: list[Conquista] = field(default_factory=list)

    @property
    def lucro(self) -> int:
        return self.premio - self.aposta


class Tesouraria:
    """Toda operação financeira do cassino. Métodos SÍNCRONOS: chame com
    asyncio.to_thread() para não bloquear o loop do bot."""

    def __init__(self, obter_economia: Callable[[], object]):
        self._obter_economia = obter_economia
        self._tabelas_ok = False

    # ---------- infraestrutura ----------

    def _economia(self):
        eco = self._obter_economia()
        if eco is None:
            raise EconomiaIndisponivel("XpAndCoins não está carregado.")
        if not self._tabelas_ok:
            with eco.transacao() as db:
                for comando in SCHEMA:
                    db.execute(comando)
            self._tabelas_ok = True
        return eco

    @staticmethod
    def _validar_aposta(jogo: str, aposta: int) -> None:
        if isinstance(aposta, bool) or not isinstance(aposta, int):
            raise ApostaInvalida("A aposta precisa ser um número inteiro.")
        minimo, maximo = limites_aposta(jogo)
        if aposta < minimo or aposta > maximo:
            raise ApostaInvalida(
                f"A aposta deve ficar entre {minimo} e {maximo} Abysmus."
            )

    @staticmethod
    def _validar_premio(aposta: int, premio: int) -> None:
        if isinstance(premio, bool) or not isinstance(premio, int):
            raise ValueError("Prêmio inválido.")
        if premio < 0 or premio > aposta * MULTIPLICADOR_MAXIMO_ABSOLUTO:
            raise ValueError(
                f"Prêmio {premio} fora dos limites para a aposta {aposta}."
            )

    # ---------- consultas ----------

    def saldo(self, guild_id: int, user_id: int) -> int:
        eco = self._economia()
        return int(eco.obter_dados(guild_id, user_id)[2])

    # ---------- estatísticas e conquistas (dentro da transação) ----------

    def _registrar(self, db, guild_id, user_id, jogo, aposta, premio,
                   flags) -> list[Conquista]:
        vit = 1 if premio > aposta else 0
        emp = 1 if premio == aposta else 0
        der = 1 if premio < aposta else 0
        db.execute("""
            INSERT INTO cassino_stats
                (guild_id, user_id, jogo, partidas, vitorias, derrotas,
                 empates, apostado, premios, maior_premio)
            VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, jogo) DO UPDATE SET
                partidas = partidas + 1,
                vitorias = vitorias + excluded.vitorias,
                derrotas = derrotas + excluded.derrotas,
                empates = empates + excluded.empates,
                apostado = apostado + excluded.apostado,
                premios = premios + excluded.premios,
                maior_premio = MAX(maior_premio, excluded.maior_premio)
        """, (guild_id, user_id, jogo, vit, der, emp, aposta, premio, premio))

        partidas, jogos, vitorias, maior = db.execute("""
            SELECT COALESCE(SUM(partidas), 0), COUNT(*),
                   COALESCE(SUM(vitorias), 0), COALESCE(MAX(maior_premio), 0)
            FROM cassino_stats WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()

        ctx = ContextoConquista(jogo, partidas, jogos, vitorias, maior,
                                frozenset(flags))
        novas = []
        for conquista in CONQUISTAS:
            try:
                atingiu = conquista.condicao(ctx)
            except Exception:
                log.exception("Condição de conquista falhou: %s", conquista.chave)
                continue
            if not atingiu:
                continue
            cur = db.execute("""
                INSERT OR IGNORE INTO cassino_conquistas
                    (guild_id, user_id, chave, desbloqueada)
                VALUES (?, ?, ?, ?)
            """, (guild_id, user_id, conquista.chave, time.time()))
            if cur.rowcount == 1:
                novas.append(conquista)
        return novas

    # ---------- jogos instantâneos ----------

    def jogada_instantanea(self, guild_id: int, user_id: int, jogo: str,
                           aposta: int, premio: int, detalhe: str = "",
                           flags: Sequence[str] = ()) -> Liquidacao:
        """Cobra a aposta e paga o prêmio em UMA transação atômica."""
        self._validar_aposta(jogo, aposta)
        self._validar_premio(aposta, premio)
        eco = self._economia()
        pid = uuid.uuid4().hex
        agora = time.time()

        with eco.transacao() as db:
            saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            if saldo < aposta:
                raise SaldoInsuficiente(saldo, aposta)
            novo = eco.alterar_coins_tx(db, guild_id, user_id, premio - aposta)
            db.execute("""
                INSERT INTO cassino_partidas
                    (id, guild_id, user_id, jogo, aposta, premio, estado,
                     detalhe, criado, fechado)
                VALUES (?, ?, ?, ?, ?, ?, 'paga', ?, ?, ?)
            """, (pid, guild_id, user_id, jogo, aposta, premio,
                  detalhe[:200], agora, agora))
            novas = self._registrar(db, guild_id, user_id, jogo, aposta,
                                    premio, flags)

        log.info("Rodada [%s] %s guild=%s user=%s aposta=%s prêmio=%s "
                 "saldo=%s | %s", pid[:8], jogo, guild_id, user_id, aposta,
                 premio, novo, detalhe)
        return Liquidacao(pid, jogo, aposta, premio, novo, novas)

    # ---------- jogos interativos ----------

    def abrir_partida(self, guild_id: int, user_id: int, jogo: str,
                      aposta: int) -> tuple[str, int]:
        """Debita a aposta e abre a partida. Retorna (id, saldo restante)."""
        self._validar_aposta(jogo, aposta)
        eco = self._economia()
        pid = uuid.uuid4().hex
        agora = time.time()

        with eco.transacao() as db:
            aberta = db.execute("""
                SELECT 1 FROM cassino_partidas
                WHERE guild_id = ? AND user_id = ? AND estado = 'aberta'
            """, (guild_id, user_id)).fetchone()
            if aberta:
                raise PartidaEmAndamento("Já existe uma partida aberta.")
            saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            if saldo < aposta:
                raise SaldoInsuficiente(saldo, aposta)
            restante = eco.alterar_coins_tx(db, guild_id, user_id, -aposta)
            db.execute("""
                INSERT INTO cassino_partidas
                    (id, guild_id, user_id, jogo, aposta, premio, estado,
                     detalhe, criado)
                VALUES (?, ?, ?, ?, ?, 0, 'aberta', '', ?)
            """, (pid, guild_id, user_id, jogo, aposta, agora))

        log.info("Partida aberta [%s] %s guild=%s user=%s aposta=%s",
                 pid[:8], jogo, guild_id, user_id, aposta)
        return pid, restante

    def liquidar_partida(self, partida_id: str, premio: int,
                         detalhe: str = "",
                         flags: Sequence[str] = ()) -> Liquidacao:
        """Paga o prêmio UMA única vez ('aberta' -> 'paga')."""
        eco = self._economia()
        with eco.transacao() as db:
            linha = db.execute("""
                SELECT guild_id, user_id, jogo, aposta, estado
                FROM cassino_partidas WHERE id = ?
            """, (partida_id,)).fetchone()
            if linha is None:
                raise PartidaInvalida("Partida inexistente.")
            guild_id, user_id, jogo, aposta, estado = linha
            if estado != "aberta":
                raise PartidaJaEncerrada(f"Partida já {estado}.")
            self._validar_premio(aposta, premio)

            cur = db.execute("""
                UPDATE cassino_partidas
                SET estado = 'paga', premio = ?, detalhe = ?, fechado = ?
                WHERE id = ? AND estado = 'aberta'
            """, (premio, detalhe[:200], time.time(), partida_id))
            if cur.rowcount != 1:
                raise PartidaJaEncerrada("Partida já encerrada.")

            if premio > 0:
                saldo = eco.alterar_coins_tx(db, guild_id, user_id, premio)
            else:
                saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            novas = self._registrar(db, guild_id, user_id, jogo, aposta,
                                    premio, flags)

        log.info("Partida paga [%s] %s guild=%s user=%s aposta=%s prêmio=%s "
                 "saldo=%s | %s", partida_id[:8], jogo, guild_id, user_id,
                 aposta, premio, saldo, detalhe)
        return Liquidacao(partida_id, jogo, aposta, premio, saldo, novas)

    def estornar_partida(self, partida_id: str) -> Optional[int]:
        """Devolve a aposta de uma partida aberta. Retorna o valor devolvido
        (None se a partida já estava encerrada)."""
        eco = self._economia()
        with eco.transacao() as db:
            linha = db.execute("""
                SELECT guild_id, user_id, aposta FROM cassino_partidas
                WHERE id = ? AND estado = 'aberta'
            """, (partida_id,)).fetchone()
            if linha is None:
                return None
            guild_id, user_id, aposta = linha
            cur = db.execute("""
                UPDATE cassino_partidas
                SET estado = 'estornada', premio = ?, fechado = ?
                WHERE id = ? AND estado = 'aberta'
            """, (aposta, time.time(), partida_id))
            if cur.rowcount != 1:
                return None
            eco.alterar_coins_tx(db, guild_id, user_id, aposta)
        log.warning("Partida estornada [%s] guild=%s user=%s valor=%s",
                    partida_id[:8], guild_id, user_id, aposta)
        return aposta

    def estornar_abertas(self, ignorar: Sequence[str] = ()) -> int:
        """Estorna partidas abertas órfãs (queda do bot, cog descarregado)."""
        eco = self._economia()
        with eco.transacao() as db:
            ids = [r[0] for r in db.execute(
                "SELECT id FROM cassino_partidas WHERE estado = 'aberta'"
            ).fetchall()]
        total = 0
        for pid in ids:
            if pid in ignorar:
                continue
            if self.estornar_partida(pid) is not None:
                total += 1
        return total

    # ---------- relatórios ----------

    def estatisticas(self, guild_id: int, user_id: int) -> dict:
        eco = self._economia()
        with eco.transacao() as db:
            por_jogo = db.execute("""
                SELECT jogo, partidas, vitorias, derrotas, empates,
                       apostado, premios, maior_premio
                FROM cassino_stats WHERE guild_id = ? AND user_id = ?
                ORDER BY partidas DESC
            """, (guild_id, user_id)).fetchall()
            historico = db.execute("""
                SELECT jogo, aposta, premio, estado, detalhe
                FROM cassino_partidas
                WHERE guild_id = ? AND user_id = ? AND estado != 'aberta'
                ORDER BY criado DESC LIMIT ?
            """, (guild_id, user_id, HISTORICO_LINHAS)).fetchall()
            conquistas = {r[0] for r in db.execute("""
                SELECT chave FROM cassino_conquistas
                WHERE guild_id = ? AND user_id = ?
            """, (guild_id, user_id)).fetchall()}
        return {"por_jogo": por_jogo, "historico": historico,
                "conquistas": conquistas}


# ============================================================
# 7. REGISTRO DE JOGOS
# ============================================================

@dataclass
class JogoSpec:
    chave: str
    nome: str
    emoji: str
    npc: str
    descricao: str
    regras: str
    criar_view: Callable[..., "ViewBase"]


JOGOS: dict[str, JogoSpec] = {}


def registrar_jogo(spec: JogoSpec) -> JogoSpec:
    if spec.npc not in NPCS:
        raise ValueError(f"NPC inexistente: {spec.npc}")
    JOGOS[spec.chave] = spec
    return spec


# ============================================================
# 8. INTERFACE DO DISCORD
# ============================================================

COR_VITORIA = 0x2ECC71
COR_DERROTA = 0xC0392B
COR_EMPATE = 0x95A5A6


def embed_npc(npc: Npc, titulo: str, descricao: str = "",
              cor: Optional[int] = None) -> discord.Embed:
    embed = discord.Embed(title=titulo, description=descricao,
                          color=cor if cor is not None else npc.cor)
    embed.set_author(name=f"{npc.emoji} {npc.nome} — {npc.cargo}")
    return embed


def linha_financeira(aposta: int, premio: int, saldo: int) -> str:
    lucro = premio - aposta
    sinal = "+" if lucro > 0 else ("−" if lucro < 0 else "±")
    return (f"**Aposta:** {fmt(aposta)} 🪙 · **Prêmio bruto:** {fmt(premio)} 🪙\n"
            f"**Resultado líquido:** {sinal}{fmt(abs(lucro))} 🪙 · "
            f"**Saldo:** {fmt(saldo)} 🪙")


def opcoes_aposta(minimo: int, maximo: int, atual: int) -> list[discord.SelectOption]:
    if maximo - minimo + 1 <= 25:
        valores = list(range(minimo, maximo + 1))
    else:
        base = {minimo, maximo}
        base.update(v for v in (2, 5, 10, 20, 50, 100, 200, 500, 1000)
                    if minimo <= v <= maximo)
        valores = sorted(base)[:25]
    return [
        discord.SelectOption(label=f"{v} Abysmus", value=str(v),
                             default=(v == atual))
        for v in valores
    ]


def botao(rotulo: str, emoji: str, estilo, callback,
          desabilitado: bool = False) -> discord.ui.Button:
    b = discord.ui.Button(label=rotulo, emoji=emoji, style=estilo,
                          disabled=desabilitado)
    b.callback = callback
    return b


class SelecaoCampo(discord.ui.Select):
    """Select genérico: chama `ao_escolher(interaction, valor)`."""

    def __init__(self, placeholder: str, opcoes: list, ao_escolher):
        super().__init__(placeholder=placeholder, min_values=1,
                         max_values=1, options=opcoes)
        self._ao_escolher = ao_escolher

    async def callback(self, interaction: discord.Interaction):
        await self._ao_escolher(interaction, self.values[0])


class ViewBase(discord.ui.View):
    """Base: só o dono usa os controles; trata timeout e erros."""

    def __init__(self, cassino: "Cassino", dono_id: int, *, timeout: float,
                 ultima: Optional[discord.Interaction] = None):
        super().__init__(timeout=timeout)
        self.cassino = cassino
        self.dono_id = dono_id
        self._ultima = ultima
        self._mensagem: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.dono_id:
            fiscal = NPCS["fiscal"]
            await interaction.response.send_message(
                f"{fiscal.emoji} {fiscal.fala('intruso')}", ephemeral=True)
            return False
        self._ultima = interaction
        return True

    def desabilitar(self) -> None:
        for item in self.children:
            item.disabled = True

    async def _editar_sem_interacao(self, **kwargs) -> None:
        """Edita a mensagem fora de um clique (usado no timeout)."""
        try:
            if self._ultima is not None:
                await self._ultima.edit_original_response(**kwargs)
            elif self._mensagem is not None:
                await self._mensagem.edit(**kwargs)
        except discord.HTTPException:
            log.debug("Não foi possível editar a mensagem expirada.")

    async def on_timeout(self) -> None:
        self.desabilitar()
        await self._editar_sem_interacao(view=self)

    async def on_error(self, interaction: discord.Interaction,
                       error: Exception, item) -> None:
        log.exception("Erro numa interação do cassino", exc_info=error)
        texto = f"{NPCS['fiscal'].emoji} {NPCS['fiscal'].fala('erro')}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(texto, ephemeral=True)
        except discord.HTTPException:
            pass


# ---------- Lobby ----------

class SelecaoJogo(discord.ui.Select):
    def __init__(self, lobby: "ViewLobby"):
        opcoes = [
            discord.SelectOption(label=j.nome, value=j.chave,
                                 description=j.descricao[:100], emoji=j.emoji)
            for j in JOGOS.values()
        ]
        super().__init__(placeholder="Escolha uma mesa…", min_values=1,
                         max_values=1, options=opcoes)
        self.lobby = lobby

    async def callback(self, interaction: discord.Interaction):
        await self.lobby.abrir_jogo(interaction, self.values[0])


class ViewLobby(ViewBase):
    def __init__(self, cassino, dono_id, ultima=None):
        super().__init__(cassino, dono_id, timeout=TIMEOUT_MENU, ultima=ultima)
        self.add_item(SelecaoJogo(self))
        self.add_item(botao("Banco", "🏦", discord.ButtonStyle.secondary,
                            self._banco))
        self.add_item(botao("Minhas estatísticas", "📊",
                            discord.ButtonStyle.secondary, self._stats))
        self.add_item(botao("Títulos", "🗝️", discord.ButtonStyle.secondary,
                            self._titulos))

    async def abrir_jogo(self, interaction, chave: str):
        await interaction.response.defer()
        saldo = await self.cassino.saldo_ou_aviso(interaction)
        if saldo is None:
            return
        spec = JOGOS[chave]
        view = spec.criar_view(self.cassino, self.dono_id, saldo, interaction)
        await interaction.edit_original_response(embed=view.embed_mesa(), view=view)

    async def _banco(self, interaction):
        await interaction.response.defer(ephemeral=True)
        saldo = await self.cassino.saldo_ou_aviso(interaction)
        if saldo is None:
            return
        npc = NPCS["ostrovan"]
        embed = embed_npc(npc, "Cofre do Salão",
                          f"{npc.fala('geral')}\n\n**Seu saldo:** {fmt(saldo)} 🪙 Abysmus")
        linhas = [f"• {j.emoji} {j.nome}: {limites_aposta(j.chave)[0]}–"
                  f"{limites_aposta(j.chave)[1]} 🪙" for j in JOGOS.values()]
        embed.add_field(name="Apostas permitidas", value="\n".join(linhas))
        embed.set_footer(text="O Abysmus é raro. O Salão sabe disso.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _stats(self, interaction):
        await interaction.response.defer(ephemeral=True)
        embed = await self.cassino.montar_estatisticas(
            interaction.guild_id, interaction.user)
        if embed is None:
            await self.cassino.avisar_economia(interaction)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _titulos(self, interaction):
        await interaction.response.defer(ephemeral=True)
        embed = await self.cassino.montar_titulos(
            interaction.guild_id, interaction.user)
        if embed is None:
            await self.cassino.avisar_economia(interaction)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)


# ---------- Base das mesas ----------

class ViewMesa(ViewBase):
    """Elementos comuns de uma mesa: aposta, regras, voltar."""

    jogo_chave = ""

    def __init__(self, cassino, dono_id, saldo: int, ultima=None):
        super().__init__(cassino, dono_id, timeout=TIMEOUT_MENU, ultima=ultima)
        self.spec = JOGOS[self.jogo_chave]
        self.npc = NPCS[self.spec.npc]
        self.saldo = saldo
        self.aposta = limites_aposta(self.jogo_chave)[0]
        self.ocupado = False

    # -- helpers --
    def _controle_aposta(self) -> SelecaoCampo:
        minimo, maximo = limites_aposta(self.jogo_chave)
        return SelecaoCampo("Aposta (Abysmus)",
                            opcoes_aposta(minimo, maximo, self.aposta),
                            self._escolheu_aposta)

    async def _escolheu_aposta(self, interaction, valor: str):
        self.aposta = int(valor)
        self.montar()
        await interaction.response.edit_message(embed=self.embed_mesa(), view=self)

    async def _regras(self, interaction):
        embed = embed_npc(self.npc, f"Regras — {self.spec.nome}", self.spec.regras)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _voltar(self, interaction):
        await self.cassino.exibir_lobby(interaction)

    def _cabecalho(self) -> str:
        minimo, maximo = limites_aposta(self.jogo_chave)
        return (f"*{self.npc.fala('boas_vindas')}*\n\n"
                f"**Aposta atual:** {fmt(self.aposta)} 🪙 "
                f"(permitido {minimo}–{maximo})\n"
                f"**Seu saldo:** {fmt(self.saldo)} 🪙")

    def montar(self) -> None:  # implementado pelas subclasses
        raise NotImplementedError

    def embed_mesa(self) -> discord.Embed:
        raise NotImplementedError


# ---------- Mesas instantâneas ----------

class ViewInstantanea(ViewMesa):
    """Mesa de rodada única: sorteia, cobra/paga numa transação, anima."""

    rotulo_jogar = "Jogar"

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        super().__init__(cassino, dono_id, saldo, ultima)
        self.montar()

    # -- a definir nas subclasses --
    def controles_especificos(self) -> list:
        return []

    def botoes_extras(self) -> list:
        return []

    def descricao_escolha(self) -> str:
        return ""

    def validar(self) -> Optional[str]:
        return None

    def resolver(self) -> Jogada:
        raise NotImplementedError

    def quadros(self, jogada: Jogada) -> list[str]:
        return []

    # -- montagem --
    def montar(self) -> None:
        self.clear_items()
        for item in self.controles_especificos():
            self.add_item(item)
        self.add_item(self._controle_aposta())
        self.add_item(botao(self.rotulo_jogar, "🎲",
                            discord.ButtonStyle.success, self._jogar))
        for extra in self.botoes_extras():
            self.add_item(extra)
        self.add_item(botao("Regras", "📜", discord.ButtonStyle.secondary,
                            self._regras))
        self.add_item(botao("Voltar", "🚪", discord.ButtonStyle.secondary,
                            self._voltar))

    def embed_mesa(self) -> discord.Embed:
        escolha = self.descricao_escolha()
        texto = self._cabecalho() + (f"\n**Sua escolha:** {escolha}" if escolha else "")
        return embed_npc(self.npc, f"{self.spec.emoji} {self.spec.nome}", texto)

    def embed_resultado(self, jogada: Jogada, liq: Liquidacao) -> discord.Embed:
        if liq.lucro > 0:
            situacao, cor, titulo = "vitoria", COR_VITORIA, "Vitória"
        elif liq.lucro == 0:
            situacao, cor, titulo = "empate", COR_EMPATE, "Empate"
        else:
            situacao, cor, titulo = "derrota", COR_DERROTA, "Derrota"
        texto = (f"{jogada.resumo}\n\n*{self.npc.fala(situacao)}*\n\n"
                 + linha_financeira(liq.aposta, liq.premio, liq.saldo_final))
        embed = embed_npc(self.npc, f"{self.spec.emoji} {self.spec.nome} — {titulo}",
                          texto, cor)
        if liq.conquistas:
            col = NPCS["colecionador"]
            embed.add_field(
                name=f"{col.emoji} Novo título!",
                value="\n".join(f"**{c.titulo}** — {c.nome}" for c in liq.conquistas),
                inline=False)
        embed.set_footer(text=f"Rodada {liq.partida_id[:8]}")
        return embed

    # -- ação principal --
    async def _jogar(self, interaction: discord.Interaction):
        if self.ocupado:
            await interaction.response.send_message(
                "A rodada anterior ainda está sendo resolvida.", ephemeral=True)
            return
        self.ocupado = True
        try:
            await interaction.response.defer()
            erro = self.validar()
            if erro:
                await interaction.followup.send(erro, ephemeral=True)
                return
            if await self.cassino.barrar_por_cooldown(interaction):
                return

            jogada = self.resolver()
            try:
                liq = await asyncio.to_thread(
                    self.cassino.tesouraria.jogada_instantanea,
                    interaction.guild_id, interaction.user.id,
                    self.jogo_chave, self.aposta, jogada.premio,
                    jogada.detalhe, jogada.flags)
            except SaldoInsuficiente as e:
                self.saldo = e.saldo
                await self.cassino.avisar_saldo(interaction, e)
                return
            except ApostaInvalida as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return
            except EconomiaIndisponivel:
                await self.cassino.avisar_economia(interaction)
                return
            except Exception:
                log.exception("Falha ao processar a rodada (nada foi cobrado).")
                await interaction.followup.send(
                    f"{NPCS['fiscal'].emoji} {NPCS['fiscal'].fala('erro')}",
                    ephemeral=True)
                return

            self.saldo = liq.saldo_final
            await self._exibir(interaction, jogada, liq)
            await self.cassino.anunciar_se_grande(interaction, liq, self.spec)
        finally:
            self.ocupado = False

    async def _exibir(self, interaction, jogada: Jogada, liq: Liquidacao):
        """Animação curta + resultado final. O prêmio JÁ foi pago."""
        try:
            self.desabilitar()
            for quadro in self.quadros(jogada):
                embed = embed_npc(self.npc,
                                  f"{self.spec.emoji} {self.spec.nome}", quadro)
                await interaction.edit_original_response(embed=embed, view=self)
                await asyncio.sleep(0.9)
            self.montar()
            await interaction.edit_original_response(
                embed=self.embed_resultado(jogada, liq), view=self)
        except discord.HTTPException:
            log.warning("Falha ao exibir o resultado da rodada %s.", liq.partida_id[:8])
            try:
                await interaction.followup.send(
                    embed=self.embed_resultado(jogada, liq), ephemeral=True)
            except discord.HTTPException:
                pass


# ---- Roleta da Ruptura ----

EMOJI_COR = {"vermelho": "🔴", "preto": "⚫", "verde": "🟢"}


class ModalNumero(discord.ui.Modal, title="Número da Roleta"):
    entrada = discord.ui.TextInput(label="Número (0 a 36)", min_length=1,
                                   max_length=2)

    def __init__(self, mesa: "ViewRoleta"):
        super().__init__()
        self.mesa = mesa

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(str(self.entrada.value).strip())
            if not 0 <= n <= 36:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Escolha um número inteiro entre 0 e 36.", ephemeral=True)
            return
        self.mesa.numero = n
        self.mesa.montar()
        await interaction.response.edit_message(
            embed=self.mesa.embed_mesa(), view=self.mesa)


class ViewRoleta(ViewInstantanea):
    jogo_chave = "roleta"
    rotulo_jogar = "Girar a roda"

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        self.tipo = "vermelho"
        self.numero: Optional[int] = None
        super().__init__(cassino, dono_id, saldo, ultima)

    def controles_especificos(self):
        opcoes = [discord.SelectOption(label=r, value=k, default=(k == self.tipo))
                  for k, (r, _, _) in ROLETA_TIPOS.items()]
        return [SelecaoCampo("Aposte em…", opcoes, self._escolheu_tipo)]

    async def _escolheu_tipo(self, interaction, valor):
        self.tipo = valor
        self.montar()
        await interaction.response.edit_message(embed=self.embed_mesa(), view=self)

    def botoes_extras(self):
        if self.tipo != "numero":
            return []
        return [botao("Escolher número", "🔢", discord.ButtonStyle.primary,
                      self._pedir_numero)]

    async def _pedir_numero(self, interaction):
        await interaction.response.send_modal(ModalNumero(self))

    def descricao_escolha(self):
        rotulo, mult, _ = ROLETA_TIPOS[self.tipo]
        extra = ""
        if self.tipo == "numero":
            extra = f" — nº {self.numero}" if self.numero is not None else " — (escolha o número)"
        return f"{rotulo}{extra} · paga {mult}× (bruto)"

    def validar(self):
        if self.tipo == "numero" and self.numero is None:
            return "Escolha o número antes de girar a roda."
        return None

    def resolver(self) -> Jogada:
        sorteado = RNG.randrange(37)
        mult = multiplicador_roleta(self.tipo, sorteado, self.numero)
        cor = roleta_cor(sorteado)
        nome_cor = {"vermelho": "Carmesim", "preto": "Fuligem", "verde": "a Fenda"}[cor]
        flags = []
        if self.tipo == "numero" and mult:
            flags.append("roleta_pleno")
        resumo = (f"A bola caiu em **{sorteado}** {EMOJI_COR[cor]} {nome_cor}."
                  + (" A Fenda engole tudo, exceto quem apostou nela."
                     if sorteado == 0 else ""))
        return Jogada(self.aposta * mult, resumo,
                      f"roleta {self.tipo} -> {sorteado}", tuple(flags))

    def quadros(self, jogada):
        return ["🎡 A roda gira e a névoa violeta acompanha…",
                "⏳ A bola ricocheteia entre dois instantes…"]


# ---- Cara ou Coroa do Abismo ----

class ViewMoeda(ViewInstantanea):
    jogo_chave = "moeda"
    rotulo_jogar = "Lançar a moeda"

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        self.escolha = "cara"
        super().__init__(cassino, dono_id, saldo, ultima)

    def controles_especificos(self):
        opcoes = [discord.SelectOption(label="Cara", value="cara",
                                       default=self.escolha == "cara"),
                  discord.SelectOption(label="Coroa", value="coroa",
                                       default=self.escolha == "coroa")]
        return [SelecaoCampo("Seu lado", opcoes, self._escolheu_lado)]

    async def _escolheu_lado(self, interaction, valor):
        self.escolha = valor
        self.montar()
        await interaction.response.edit_message(embed=self.embed_mesa(), view=self)

    def descricao_escolha(self):
        return f"{self.escolha.capitalize()} · paga {MOEDA_MULTIPLICADOR}× (bruto)"

    def resolver(self) -> Jogada:
        lado = lancar_moeda(RNG)
        if lado == "borda":
            resumo = ("A moeda gira… e cai **em pé**, equilibrada na borda "
                      "entre dois instantes. A casa vence.")
            return Jogada(0, resumo, "moeda borda", ("moeda_borda",))
        venceu = lado == self.escolha
        resumo = f"A moeda caiu em **{lado.upper()}**."
        return Jogada(self.aposta * MOEDA_MULTIPLICADOR if venceu else 0,
                      resumo, f"moeda {lado} (escolha {self.escolha})")

    def quadros(self, jogada):
        return ["🪙 O Mestre lança a moeda para dentro do Abismo…",
                "🌀 Ela ainda não terminou de cair…"]


# ---- Dados Amaldiçoados ----

def rotulo_modalidade_dados(m: str) -> str:
    if m.startswith("soma_"):
        n = int(m.split("_")[1])
        return f"Soma exata {n} (paga {multiplicador_soma(n)}×)"
    return {"alto": "Alto 8–11 (paga 2×; 7 devolve)",
            "baixo": "Baixo 3–6 (paga 2×; 7 devolve)",
            "face6": "Pelo menos um 6 (paga 3×)"}[m]


class ViewDados(ViewInstantanea):
    jogo_chave = "dados"
    rotulo_jogar = "Rolar os dados"

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        self.modalidade = "face6"
        super().__init__(cassino, dono_id, saldo, ultima)

    def controles_especificos(self):
        opcoes = [discord.SelectOption(label=rotulo_modalidade_dados(m)[:100],
                                       value=m, default=(m == self.modalidade))
                  for m in modalidades_dados()]
        return [SelecaoCampo("Modalidade", opcoes, self._escolheu)]

    async def _escolheu(self, interaction, valor):
        self.modalidade = valor
        self.montar()
        await interaction.response.edit_message(embed=self.embed_mesa(), view=self)

    def descricao_escolha(self):
        rtp = float(rtp_dados(self.modalidade)) * 100
        return f"{rotulo_modalidade_dados(self.modalidade)} · RTP {rtp:.2f}%"

    def resolver(self) -> Jogada:
        d1, d2 = RNG.randint(1, 6), RNG.randint(1, 6)
        mult = multiplicador_dados(self.modalidade, d1, d2)
        resumo = f"🎲 **{d1}** + 🎲 **{d2}** = **{d1 + d2}**."
        if mult == 1:
            resumo += " O Sete devolve a aposta."
        return Jogada(self.aposta * mult, resumo,
                      f"dados {self.modalidade} -> {d1}+{d2}")

    def quadros(self, jogada):
        return ["🎲 Os dados amaldiçoados rolam sobre o feltro…",
                "🎲 Um deles parou. O outro ainda hesita…"]


# ---- Caça-Níquel Temporal ----

class ViewSlots(ViewInstantanea):
    jogo_chave = "slots"
    rotulo_jogar = "Puxar a alavanca"

    def descricao_escolha(self):
        return "3 rolos · veja a tabela em Regras"

    def resolver(self) -> Jogada:
        rolos = girar_slots(RNG)
        mult = multiplicador_slots(rolos)
        simbolos = " ".join(SLOT_SIMBOLOS[r][0] for r in rolos)
        flags = ("slot_jackpot",) if rolos[0] == rolos[1] == rolos[2] == "anomalia" else ()
        return Jogada(self.aposta * mult, f"**[ {simbolos} ]**",
                      f"slots {'-'.join(rolos)}", flags)

    def quadros(self, jogada):
        return ["🎰 **[ ❔ ❔ ❔ ]** Os rolos aquecem…",
                "🎰 **[ ⚙️ ❔ ❔ ]** Eras se alinham, uma por uma…"]


# ---------- Mesas interativas (partida aberta) ----------

class ViewPartida(ViewMesa):
    """Base de mesas com partida aberta no banco (Blackjack, Travessia)."""

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        super().__init__(cassino, dono_id, saldo, ultima)
        self.timeout = TIMEOUT_PARTIDA
        self.fase = "aposta"        # aposta | jogando | fim
        self.partida_id: Optional[str] = None
        self.trava = asyncio.Lock()
        self.ultima_liq: Optional[Liquidacao] = None
        self.montar()

    async def _abrir(self, interaction) -> bool:
        """Debita a aposta e abre a partida. False se algo impediu."""
        try:
            pid, restante = await asyncio.to_thread(
                self.cassino.tesouraria.abrir_partida,
                interaction.guild_id, interaction.user.id,
                self.jogo_chave, self.aposta)
        except SaldoInsuficiente as e:
            self.saldo = e.saldo
            await self.cassino.avisar_saldo(interaction, e)
            return False
        except PartidaEmAndamento:
            await interaction.followup.send(
                f"{NPCS['fiscal'].emoji} {NPCS['fiscal'].fala('partida')}",
                ephemeral=True)
            return False
        except ApostaInvalida as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return False
        except EconomiaIndisponivel:
            await self.cassino.avisar_economia(interaction)
            return False
        except Exception:
            log.exception("Falha ao abrir a partida (nada foi cobrado).")
            await interaction.followup.send(
                f"{NPCS['fiscal'].emoji} {NPCS['fiscal'].fala('erro')}",
                ephemeral=True)
            return False
        self.partida_id = pid
        self.saldo = restante
        self.cassino.partidas_ativas.add(pid)
        return True

    async def _liquidar(self, premio: int, detalhe: str,
                        flags: Sequence[str] = ()) -> Optional[Liquidacao]:
        """Paga a partida uma única vez, com retentativas."""
        for tentativa in range(3):
            try:
                liq = await asyncio.to_thread(
                    self.cassino.tesouraria.liquidar_partida,
                    self.partida_id, premio, detalhe, flags)
                self.cassino.partidas_ativas.discard(self.partida_id)
                self.saldo = liq.saldo_final
                self.ultima_liq = liq
                return liq
            except PartidaJaEncerrada:
                self.cassino.partidas_ativas.discard(self.partida_id)
                return None
            except Exception:
                log.exception("Falha ao liquidar a partida %s (tentativa %s).",
                              self.partida_id, tentativa + 1)
                await asyncio.sleep(0.5 * (tentativa + 1))
        log.error("Partida %s NÃO liquidada; será estornada na recuperação.",
                  self.partida_id)
        return None

    def _aviso_falha(self) -> str:
        return ("⚠️ Não consegui confirmar o pagamento agora. Sua aposta está "
                "registrada e será estornada automaticamente se a partida "
                "não puder ser concluída.")

    async def _estornar(self) -> Optional[int]:
        try:
            valor = await asyncio.to_thread(
                self.cassino.tesouraria.estornar_partida, self.partida_id)
            self.cassino.partidas_ativas.discard(self.partida_id)
            if valor:
                self.saldo += valor
            return valor
        except Exception:
            log.exception("Falha ao estornar a partida %s.", self.partida_id)
            return None


# ---- Blackjack das Almas ----

def fmt_mao(cartas: Sequence[Carta], esconder_segunda: bool = False) -> str:
    if esconder_segunda and len(cartas) >= 2:
        return f"`{cartas[0]}` `🂠`"
    return " ".join(f"`{c}`" for c in cartas)


class ViewBlackjack(ViewPartida):
    jogo_chave = "blackjack"

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        self.mesa: Optional[BlackjackPartida] = None
        super().__init__(cassino, dono_id, saldo, ultima)

    def montar(self) -> None:
        self.clear_items()
        if self.fase == "jogando":
            self.add_item(botao("Comprar", "🃏", discord.ButtonStyle.primary,
                                self._comprar))
            self.add_item(botao("Parar", "✋", discord.ButtonStyle.danger,
                                self._parar))
            return
        self.add_item(self._controle_aposta())
        rotulo = "Jogar de novo" if self.fase == "fim" else "Sentar à mesa"
        self.add_item(botao(rotulo, "🃏", discord.ButtonStyle.success,
                            self._sentar))
        self.add_item(botao("Regras", "📜", discord.ButtonStyle.secondary,
                            self._regras))
        self.add_item(botao("Voltar", "🚪", discord.ButtonStyle.secondary,
                            self._voltar))

    def embed_mesa(self) -> discord.Embed:
        if self.fase == "aposta":
            return embed_npc(self.npc, f"{self.spec.emoji} {self.spec.nome}",
                             self._cabecalho())
        mesa = self.mesa
        em_jogo = self.fase == "jogando"
        tj, _ = pontos_mao(mesa.jogador)
        descricao = (f"**Sua mão ({tj}):** {fmt_mao(mesa.jogador)}\n"
                     f"**Banca"
                     + ("" if em_jogo else f" ({pontos_mao(mesa.banca)[0]})")
                     + f":** {fmt_mao(mesa.banca, esconder_segunda=em_jogo)}\n\n")
        if em_jogo:
            embed = embed_npc(self.npc, f"{self.spec.emoji} {self.spec.nome}",
                              descricao + f"**Aposta em jogo:** {fmt(self.aposta)} 🪙\n"
                              "Comprar ou parar?")
            return embed
        situacao = {"blackjack": "vitoria", "vitoria": "vitoria",
                    "empate": "empate", "derrota": "derrota"}[mesa.resultado]
        titulo = {"blackjack": "BLACKJACK!", "vitoria": "Vitória",
                  "empate": "Empate", "derrota": "Derrota"}[mesa.resultado]
        cor = {"vitoria": COR_VITORIA, "empate": COR_EMPATE,
               "derrota": COR_DERROTA}[situacao]
        liq = self.ultima_liq
        corpo = descricao + f"{mesa.motivo}\n*{self.npc.fala(situacao)}*\n\n"
        if liq is not None:
            corpo += linha_financeira(liq.aposta, liq.premio, liq.saldo_final)
        else:
            corpo += self._aviso_falha()
        embed = embed_npc(self.npc, f"{self.spec.emoji} {self.spec.nome} — {titulo}",
                          corpo, cor)
        if liq is not None and liq.conquistas:
            col = NPCS["colecionador"]
            embed.add_field(name=f"{col.emoji} Novo título!", inline=False,
                            value="\n".join(f"**{c.titulo}** — {c.nome}"
                                            for c in liq.conquistas))
        return embed

    async def _sentar(self, interaction):
        async with self.trava:
            if self.fase == "jogando":
                await interaction.response.send_message(
                    "Há uma mão em andamento.", ephemeral=True)
                return
            await interaction.response.defer()
            if await self.cassino.barrar_por_cooldown(interaction):
                return
            if not await self._abrir(interaction):
                return
            self.mesa = BlackjackPartida(RNG)
            self.mesa.iniciar()
            self.fase = "jogando"
            if self.mesa.terminou:
                await self._concluir(interaction)
                return
            self.montar()
            await interaction.edit_original_response(embed=self.embed_mesa(), view=self)

    async def _comprar(self, interaction):
        async with self.trava:
            if self.fase != "jogando":
                await interaction.response.send_message(
                    "Esta mão já terminou.", ephemeral=True)
                return
            await interaction.response.defer()
            self.mesa.comprar()
            if self.mesa.terminou:
                await self._concluir(interaction)
            else:
                await interaction.edit_original_response(
                    embed=self.embed_mesa(), view=self)

    async def _parar(self, interaction):
        async with self.trava:
            if self.fase != "jogando":
                await interaction.response.send_message(
                    "Esta mão já terminou.", ephemeral=True)
                return
            await interaction.response.defer()
            self.mesa.parar()
            await self._concluir(interaction)

    async def _concluir(self, interaction):
        premio = self.mesa.premio_bruto(self.aposta)
        flags = ("blackjack_natural",) if self.mesa.resultado == "blackjack" else ()
        liq = await self._liquidar(
            premio, f"blackjack {self.mesa.resultado} "
                    f"{pontos_mao(self.mesa.jogador)[0]}x{pontos_mao(self.mesa.banca)[0]}",
            flags)
        self.fase = "fim"
        self.montar()
        await interaction.edit_original_response(embed=self.embed_mesa(), view=self)
        if liq is not None:
            await self.cassino.anunciar_se_grande(interaction, liq, self.spec)

    async def on_timeout(self) -> None:
        async with self.trava:
            if self.fase == "jogando" and self.mesa is not None:
                # Inatividade = parar (nunca vira vantagem para o jogador).
                self.mesa.parar()
                premio = self.mesa.premio_bruto(self.aposta)
                await self._liquidar(
                    premio, f"blackjack {self.mesa.resultado} (timeout)")
                self.fase = "fim"
            self.desabilitar()
            await self._editar_sem_interacao(embed=self.embed_mesa(), view=self)


# ---- Travessia das Fendas ----

class ViewTravessia(ViewPartida):
    jogo_chave = "travessia"

    def __init__(self, cassino, dono_id, saldo, ultima=None):
        self.degrau = 0
        self.historico: list[str] = []
        self.perdeu = False
        super().__init__(cassino, dono_id, saldo, ultima)

    def _escada(self) -> str:
        linhas = []
        for i in range(len(TRAVESSIA_DEGRAUS) - 1, -1, -1):
            mult, nome = TRAVESSIA_DEGRAUS[i]
            marca = "🔹" if (i == self.degrau and self.fase == "jogando") else (
                "✅" if i < self.degrau else "▫️")
            linhas.append(f"{marca} **{mult}×** {nome}")
        return "\n".join(linhas)

    def montar(self) -> None:
        self.clear_items()
        if self.fase == "jogando":
            p1 = travessia_chance(self.degrau, False)
            p2 = travessia_chance(self.degrau, True)
            if p1 is not None:
                self.add_item(botao(f"Passo cauteloso ({p1}%)", "🚶",
                                    discord.ButtonStyle.primary,
                                    self._cauteloso))
            if p2 is not None:
                self.add_item(botao(f"Salto arriscado ({p2}%)", "🦘",
                                    discord.ButtonStyle.danger, self._salto))
            if self.degrau > 0:
                valor = TRAVESSIA_DEGRAUS[self.degrau][0] * self.aposta
                self.add_item(botao(f"Recolher {fmt(valor)} 🪙", "💰",
                                    discord.ButtonStyle.success, self._recolher))
            else:
                self.add_item(botao("Desistir (estorno)", "↩️",
                                    discord.ButtonStyle.secondary, self._desistir))
            return
        self.add_item(self._controle_aposta())
        rotulo = "Atravessar de novo" if self.fase == "fim" else "Entrar na Travessia"
        self.add_item(botao(rotulo, "🕯️", discord.ButtonStyle.success,
                            self._entrar))
        self.add_item(botao("Regras", "📜", discord.ButtonStyle.secondary,
                            self._regras))
        self.add_item(botao("Voltar", "🚪", discord.ButtonStyle.secondary,
                            self._voltar))

    def embed_mesa(self) -> discord.Embed:
        titulo = f"{self.spec.emoji} {self.spec.nome}"
        if self.fase == "aposta":
            return embed_npc(self.npc, titulo,
                             self._cabecalho() + "\n\n" + self._escada())
        if self.fase == "jogando":
            mult, nome = TRAVESSIA_DEGRAUS[self.degrau]
            texto = (f"**Você está em:** {nome}\n"
                     f"**Aposta em jogo:** {fmt(self.aposta)} 🪙\n\n"
                     f"{self._escada()}\n\n")
            if self.historico:
                texto += "\n".join(self.historico[-3:]) + "\n\n"
            texto += ("Escolha o próximo passo. Cada opção mostra a chance "
                      "real de sobreviver.")
            return embed_npc(self.npc, titulo, texto)
        liq = self.ultima_liq
        if self.perdeu:
            situacao, cor, rotulo = "derrota", COR_DERROTA, "A fenda se fechou"
        else:
            situacao, cor, rotulo = "vitoria", COR_VITORIA, "Travessia concluída"
        texto = "\n".join(self.historico[-3:]) + f"\n\n*{self.npc.fala(situacao)}*\n\n"
        texto += (linha_financeira(liq.aposta, liq.premio, liq.saldo_final)
                  if liq is not None else self._aviso_falha())
        embed = embed_npc(self.npc, f"{titulo} — {rotulo}", texto, cor)
        if liq is not None and liq.conquistas:
            col = NPCS["colecionador"]
            embed.add_field(name=f"{col.emoji} Novo título!", inline=False,
                            value="\n".join(f"**{c.titulo}** — {c.nome}"
                                            for c in liq.conquistas))
        return embed

    async def _entrar(self, interaction):
        async with self.trava:
            if self.fase == "jogando":
                await interaction.response.send_message(
                    "A travessia já começou.", ephemeral=True)
                return
            await interaction.response.defer()
            if await self.cassino.barrar_por_cooldown(interaction):
                return
            if not await self._abrir(interaction):
                return
            self.fase = "jogando"
            self.degrau = 0
            self.historico = []
            self.perdeu = False
            self.montar()
            await interaction.edit_original_response(embed=self.embed_mesa(), view=self)

    async def _desistir(self, interaction):
        async with self.trava:
            if self.fase != "jogando" or self.degrau != 0:
                await interaction.response.send_message(
                    "Agora só é possível recolher.", ephemeral=True)
                return
            await interaction.response.defer()
            await self._estornar()
            self.fase = "aposta"
            self.montar()
            await interaction.edit_original_response(embed=self.embed_mesa(), view=self)

    async def _cauteloso(self, interaction):
        await self._passo(interaction, salto=False)

    async def _salto(self, interaction):
        await self._passo(interaction, salto=True)

    async def _passo(self, interaction, salto: bool):
        async with self.trava:
            if self.fase != "jogando":
                await interaction.response.send_message(
                    "A travessia já terminou.", ephemeral=True)
                return
            await interaction.response.defer()
            chance = travessia_chance(self.degrau, salto)
            destino = travessia_destino(self.degrau, salto)
            if chance is None or destino is None:
                await interaction.followup.send("Esse passo não existe aqui.",
                                                ephemeral=True)
                return
            nome_destino = TRAVESSIA_DEGRAUS[destino][1]
            if RNG.randrange(100) < chance:
                self.degrau = destino
                self.historico.append(
                    f"✅ Você atravessou até **{nome_destino}** ({chance}%).")
                if self.degrau == len(TRAVESSIA_DEGRAUS) - 1:
                    await self._encerrar(interaction, "travessia topo",
                                         ("travessia_topo",))
                    return
                self.montar()
                await interaction.edit_original_response(
                    embed=self.embed_mesa(), view=self)
            else:
                self.historico.append(
                    f"💀 A fenda para **{nome_destino}** se fechou ({chance}%).")
                self.perdeu = True
                self.degrau_perda = self.degrau
                await self._encerrar_perda(interaction)

    async def _recolher(self, interaction):
        async with self.trava:
            if self.fase != "jogando" or self.degrau == 0:
                await interaction.response.send_message(
                    "Nada a recolher agora.", ephemeral=True)
                return
            await interaction.response.defer()
            self.historico.append("💰 Você recolheu o prêmio a tempo.")
            await self._encerrar(interaction, f"travessia recolheu d{self.degrau}")

    async def _encerrar(self, interaction, detalhe: str, flags=()):
        premio = TRAVESSIA_DEGRAUS[self.degrau][0] * self.aposta
        liq = await self._liquidar(premio, detalhe, flags)
        self.fase = "fim"
        self.montar()
        await interaction.edit_original_response(embed=self.embed_mesa(), view=self)
        if liq is not None:
            await self.cassino.anunciar_se_grande(interaction, liq, self.spec)

    async def _encerrar_perda(self, interaction):
        await self._liquidar(0, f"travessia perdeu d{self.degrau}")
        self.fase = "fim"
        self.montar()
        await interaction.edit_original_response(embed=self.embed_mesa(), view=self)

    async def on_timeout(self) -> None:
        async with self.trava:
            if self.fase == "jogando":
                if self.degrau == 0:
                    await self._estornar()
                    self.fase = "aposta"
                else:
                    self.historico.append("⌛ Inatividade: prêmio recolhido.")
                    premio = TRAVESSIA_DEGRAUS[self.degrau][0] * self.aposta
                    await self._liquidar(premio,
                                         f"travessia recolheu d{self.degrau} (timeout)")
                    self.fase = "fim"
            self.desabilitar()
            await self._editar_sem_interacao(embed=self.embed_mesa(), view=self)


# ---------- Registro dos jogos (textos de regras) ----------

def _regras_roleta() -> str:
    linhas = ["37 casas (0–36). O **0 é a Fenda**: só paga quem apostou nele.",
              "**Pagamentos (prêmio bruto):**"]
    for k, (rotulo, mult, casos) in ROLETA_TIPOS.items():
        linhas.append(f"• {rotulo}: {mult}× — chance {casos}/37")
    linhas.append(f"\nRTP: **{float(rtp_roleta('numero')) * 100:.2f}%** em todas "
                  "as modalidades (vantagem da casa 2,70%).")
    return "\n".join(linhas)


def _regras_moeda() -> str:
    metade = (100 - MOEDA_BORDA_EM_100) // 2
    return (f"Escolha cara ou coroa. Acertou: paga {MOEDA_MULTIPLICADOR}× (bruto).\n"
            f"Chance de acerto: {metade}%. Em {MOEDA_BORDA_EM_100}% das vezes a "
            f"moeda cai **em pé** e a casa vence.\n"
            f"RTP: **{float(rtp_moeda()) * 100:.2f}%**.")


def _regras_dados() -> str:
    linhas = ["Dois dados de seis faces (2d6).", "**Soma exata** (bruto):"]
    for n in range(2, 13):
        linhas.append(f"• {n}: {multiplicador_soma(n)}× — chance {formas_soma(n)}/36 "
                      f"— RTP {float(rtp_dados(f'soma_{n}')) * 100:.1f}%")
    linhas.append(
        f"**Alto (8–11)** / **Baixo (3–6)**: 2×; o **7 devolve** a aposta; 2 e 12 "
        f"são da casa. RTP {float(rtp_dados('alto')) * 100:.2f}%.")
    linhas.append(f"**Pelo menos um 6**: 3× — 11/36 — RTP "
                  f"{float(rtp_dados('face6')) * 100:.2f}%.")
    return "\n".join(linhas)


def _regras_slots() -> str:
    linhas = ["Três rolos independentes. Peso de cada símbolo (em 20):"]
    for chave, (emoji, peso) in SLOT_SIMBOLOS.items():
        linhas.append(f"{emoji} peso {peso} — 3 iguais: **{SLOT_TRIPLO[chave]}×** · "
                      f"2 iguais à esquerda: {SLOT_PAR_ESQUERDA[chave]}×")
    linhas.append(f"\nRTP: **{float(rtp_slots()) * 100:.2f}%**. Prêmios brutos; "
                  "1× devolve a aposta.")
    return "\n".join(linhas)


REGRAS_BLACKJACK = (
    "Chegue o mais perto de 21 sem estourar. Ás vale 11 ou 1; figuras valem 10.\n"
    f"• A banca compra até {BLACKJACK_BANCA_PARA_EM} e **para em todo 17**.\n"
    "• **Vitória:** paga 1:1 (prêmio bruto = 2× a aposta).\n"
    "• **Blackjack natural** (21 com duas cartas): paga 3:2, arredondado para "
    "baixo (aposta 1 → +1; aposta 3 → +4).\n"
    "• **Empate:** a aposta é devolvida. Dois naturais também empatam.\n"
    "• Se a banca tem natural, você perde na hora.\n"
    "• Sem dobrar, dividir ou render. 6 baralhos embaralhados a cada mão.\n"
    "• Inatividade equivale a **parar**."
)


def _regras_travessia() -> str:
    linhas = ["Você paga a aposta e entra no primeiro degrau. A cada passo escolhe:",
              "• **Passo cauteloso:** sobe 1 degrau, chance maior.",
              "• **Salto arriscado:** sobe 2 degraus, chance menor.",
              "• **Recolher:** leva o valor do degrau atual (exceto no início, "
              "onde só é possível desistir com estorno).\n",
              "**Degraus (prêmio bruto ao recolher):**"]
    for i, (mult, nome) in enumerate(TRAVESSIA_DEGRAUS):
        linhas.append(f"{i}. {nome} — {mult}×")
    linhas.append(
        f"\nChance de cada passo = {TRAVESSIA_RTP_PCT}% × valor atual ÷ valor "
        "destino (arredondado para baixo), mostrada nos botões. Com a melhor "
        f"estratégia possível o RTP é no máximo "
        f"**{float(travessia_rtp_maximo()) * 100:.2f}%**. Falhou: perde a "
        "aposta. Inatividade recolhe o prêmio (ou estorna, no início).")
    return "\n".join(linhas)


registrar_jogo(JogoSpec(
    "roleta", "Roleta da Ruptura", "🎡", "tarkhal",
    "Número, cor, paridade ou dúzia. A casa 0 é a Fenda.", _regras_roleta(),
    lambda c, d, s, i: ViewRoleta(c, d, s, i)))
registrar_jogo(JogoSpec(
    "moeda", "Cara ou Coroa do Abismo", "🪙", "tarkhal",
    "Dois lados… e uma borda que ninguém vê.", _regras_moeda(),
    lambda c, d, s, i: ViewMoeda(c, d, s, i)))
registrar_jogo(JogoSpec(
    "dados", "Dados Amaldiçoados", "🎲", "tarkhal",
    "2d6: soma exata, alto, baixo ou face 6.", _regras_dados(),
    lambda c, d, s, i: ViewDados(c, d, s, i)))
registrar_jogo(JogoSpec(
    "blackjack", "Blackjack das Almas", "🃏", "crupie",
    "Vinte e um contra a Crupiê Sem Ponteiros.", REGRAS_BLACKJACK,
    lambda c, d, s, i: ViewBlackjack(c, d, s, i)))
registrar_jogo(JogoSpec(
    "slots", "Caça-Níquel Temporal", "🎰", "automato",
    "Símbolos de eras diferentes em três rolos.", _regras_slots(),
    lambda c, d, s, i: ViewSlots(c, d, s, i)))
registrar_jogo(JogoSpec(
    "travessia", "Travessia das Fendas", "🕯️", "agenciador",
    "Escolha o risco a cada degrau. Recolher ou arriscar?",
    _regras_travessia(),
    lambda c, d, s, i: ViewTravessia(c, d, s, i)))


# ============================================================
# 9. COG PRINCIPAL
# ============================================================

class Cassino(commands.Cog):
    """Salão da Ruptura: cassino integrado ao Abysmus do XpAndCoins."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tesouraria = Tesouraria(lambda: bot.get_cog("XpAndCoins"))
        self.partidas_ativas: set[str] = set()
        self._ultima_jogada: dict[tuple[int, int], float] = {}
        self._tarefa_recuperacao: Optional[asyncio.Task] = None

    # ---------- ciclo de vida ----------

    async def cog_load(self) -> None:
        self._tarefa_recuperacao = asyncio.create_task(self._recuperar_orfas())

    async def _recuperar_orfas(self) -> None:
        """Estorna partidas abertas deixadas por uma queda anterior."""
        try:
            await self.bot.wait_until_ready()
            n = await asyncio.to_thread(
                self.tesouraria.estornar_abertas, tuple(self.partidas_ativas))
            if n:
                log.warning("Recuperação: %s partida(s) órfã(s) estornada(s).", n)
        except EconomiaIndisponivel:
            log.error("Recuperação adiada: XpAndCoins não está carregado.")
        except Exception:
            log.exception("Falha na recuperação de partidas órfãs.")

    async def cog_unload(self) -> None:
        if self._tarefa_recuperacao is not None:
            self._tarefa_recuperacao.cancel()
        for pid in list(self.partidas_ativas):
            try:
                await asyncio.to_thread(self.tesouraria.estornar_partida, pid)
            except Exception:
                log.exception("Falha ao estornar %s ao descarregar.", pid)
        self.partidas_ativas.clear()

    # ---------- utilidades usadas pelas views ----------

    def cooldown_restante(self, guild_id: int, user_id: int) -> float:
        chave = (guild_id, user_id)
        agora = time.monotonic()
        restante = COOLDOWN_JOGADA_SEGUNDOS - (agora - self._ultima_jogada.get(chave, 0.0))
        if restante > 0:
            return restante
        self._ultima_jogada[chave] = agora
        return 0.0

    async def barrar_por_cooldown(self, interaction) -> bool:
        restante = self.cooldown_restante(interaction.guild_id, interaction.user.id)
        if restante <= 0:
            return False
        fiscal = NPCS["fiscal"]
        await interaction.followup.send(
            f"{fiscal.emoji} {fiscal.fala('cooldown')} (aguarde {restante:.1f}s)",
            ephemeral=True)
        return True

    async def avisar_saldo(self, interaction, erro: SaldoInsuficiente) -> None:
        fiscal = NPCS["fiscal"]
        await interaction.followup.send(
            f"{fiscal.emoji} {fiscal.fala('saldo')}\n"
            f"Saldo: **{fmt(erro.saldo)}** 🪙 · necessário: "
            f"**{fmt(erro.necessario)}** 🪙", ephemeral=True)

    async def avisar_economia(self, interaction) -> None:
        npc = NPCS["ostrovan"]
        try:
            await interaction.followup.send(
                f"{npc.emoji} O cofre está fechado: o sistema de Abysmus "
                "(XpAndCoins) não está carregado.", ephemeral=True)
        except discord.HTTPException:
            pass

    async def saldo_ou_aviso(self, interaction) -> Optional[int]:
        try:
            return await asyncio.to_thread(
                self.tesouraria.saldo, interaction.guild_id, interaction.user.id)
        except EconomiaIndisponivel:
            await self.avisar_economia(interaction)
        except Exception:
            log.exception("Falha ao consultar o saldo.")
            await interaction.followup.send(
                f"{NPCS['fiscal'].emoji} {NPCS['fiscal'].fala('erro')}",
                ephemeral=True)
        return None

    async def anunciar_se_grande(self, interaction, liq: Liquidacao,
                                 spec: JogoSpec) -> None:
        if liq.lucro < ANUNCIAR_LUCRO_MINIMO or interaction.channel is None:
            return
        npc = NPCS[spec.npc]
        try:
            await interaction.channel.send(
                f"{npc.emoji} **{npc.nome}:** {interaction.user.mention} arrancou "
                f"**+{fmt(liq.lucro)} 🪙** de {spec.emoji} {spec.nome}. "
                "O Salão anotou o nome.")
        except discord.HTTPException:
            log.debug("Sem permissão para anunciar o prêmio.")

    # ---------- telas ----------

    def embed_lobby(self, saldo: int) -> discord.Embed:
        sineta = NPCS["sineta"]
        oraculo = NPCS["oraculo"]
        embed = embed_npc(
            sineta, "🌌 Salão da Ruptura",
            f"*{sineta.fala('geral')}*\n\n"
            "Um salão que surgiu entre eras. Aqui se aposta **Abysmus**.\n"
            f"**Seu saldo:** {fmt(saldo)} 🪙")
        linhas = []
        for j in JOGOS.values():
            npc = NPCS[j.npc]
            mn, mx = limites_aposta(j.chave)
            linhas.append(f"{j.emoji} **{j.nome}** — {npc.nome} · {mn}–{mx} 🪙")
        embed.add_field(name="Mesas", value="\n".join(linhas), inline=False)
        embed.add_field(
            name=f"{oraculo.emoji} Presságio do dia ({oraculo.nome})",
            value=f"*{pressagio_do_dia()}*\n(Apenas atmosfera: não altera "
                  "nenhuma probabilidade.)", inline=False)
        embed.set_footer(text="Jogue com moderação: o Abysmus é raro.")
        return embed

    async def exibir_lobby(self, interaction: discord.Interaction) -> None:
        """Volta ao salão a partir de qualquer mesa."""
        await interaction.response.defer()
        saldo = await self.saldo_ou_aviso(interaction)
        if saldo is None:
            return
        view = ViewLobby(self, interaction.user.id, ultima=interaction)
        await interaction.edit_original_response(
            embed=self.embed_lobby(saldo), view=view)

    async def montar_estatisticas(self, guild_id, membro) -> Optional[discord.Embed]:
        try:
            dados = await asyncio.to_thread(
                self.tesouraria.estatisticas, guild_id, membro.id)
        except EconomiaIndisponivel:
            return None
        npc = NPCS["ostrovan"]
        embed = embed_npc(npc, f"Livro-caixa de {membro.display_name}")
        if not dados["por_jogo"]:
            embed.description = "Nenhuma rodada registrada ainda."
            return embed
        total = [0, 0, 0, 0, 0, 0]
        for (jogo, p, v, d, e, apostado, premios, maior) in dados["por_jogo"]:
            nome = JOGOS[jogo].nome if jogo in JOGOS else jogo
            emoji = JOGOS[jogo].emoji if jogo in JOGOS else "🎴"
            embed.add_field(
                name=f"{emoji} {nome}",
                value=(f"{p} partidas · {v}V/{d}D/{e}E\n"
                       f"Apostado {fmt(apostado)} · prêmios {fmt(premios)}\n"
                       f"Maior prêmio: {fmt(maior)} 🪙"))
            for i, valor in enumerate((p, v, d, e, apostado, premios)):
                total[i] += valor
        liquido = total[5] - total[4]
        embed.description = (
            f"**Total:** {total[0]} partidas · {total[1]}V/{total[2]}D/{total[3]}E\n"
            f"**Apostado:** {fmt(total[4])} 🪙 · **Prêmios:** {fmt(total[5])} 🪙\n"
            f"**Balanço líquido:** {'+' if liquido >= 0 else '−'}{fmt(abs(liquido))} 🪙")
        if dados["historico"]:
            linhas = []
            for jogo, aposta, premio, estado, detalhe in dados["historico"]:
                nome = JOGOS[jogo].nome if jogo in JOGOS else jogo
                tag = "↩️" if estado == "estornada" else (
                    "✅" if premio > aposta else ("➖" if premio == aposta else "❌"))
                linhas.append(f"{tag} {nome}: {aposta} → {premio}")
            embed.add_field(name="Últimas rodadas", value="\n".join(linhas),
                            inline=False)
        return embed

    async def montar_titulos(self, guild_id, membro) -> Optional[discord.Embed]:
        try:
            dados = await asyncio.to_thread(
                self.tesouraria.estatisticas, guild_id, membro.id)
        except EconomiaIndisponivel:
            return None
        npc = NPCS["colecionador"]
        embed = embed_npc(npc, f"Títulos de {membro.display_name}",
                          f"*{npc.fala('geral')}*")
        for c in CONQUISTAS:
            tem = c.chave in dados["conquistas"]
            if tem:
                valor = f"✅ **{c.titulo}** — {c.descricao}"
            elif c.secreta:
                valor = "❔ Segredo do Salão."
            else:
                valor = f"🔒 {c.descricao}"
            embed.add_field(name=c.nome, value=valor, inline=False)
        embed.set_footer(text="Títulos são cosméticos: não pagam Abysmus.")
        return embed

    # ---------- comandos ----------

    @app_commands.command(name="cassino",
                          description="Entre no Salão da Ruptura e aposte Abysmus.")
    @app_commands.guild_only()
    async def cassino_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        saldo = await self.saldo_ou_aviso(interaction)
        if saldo is None:
            return
        view = ViewLobby(self, interaction.user.id, ultima=interaction)
        await interaction.followup.send(
            embed=self.embed_lobby(saldo), view=view, ephemeral=True)

    @app_commands.command(name="cassino_stats",
                          description="Veja suas estatísticas no Salão da Ruptura.")
    @app_commands.guild_only()
    @app_commands.describe(membro="Membro a consultar; vazio para você.")
    async def cassino_stats(self, interaction: discord.Interaction,
                            membro: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        alvo = membro or interaction.user
        embed = await self.montar_estatisticas(interaction.guild_id, alvo)
        if embed is None:
            await self.avisar_economia(interaction)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="cassino_titulos",
                          description="Veja os títulos do Salão da Ruptura.")
    @app_commands.guild_only()
    async def cassino_titulos(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = await self.montar_titulos(interaction.guild_id, interaction.user)
        if embed is None:
            await self.avisar_economia(interaction)
            return
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="cassino", aliases=("casino",))
    @commands.guild_only()
    async def cassino_prefixo(self, ctx: commands.Context):
        """Abre o Salão com s!cassino (mensagem pública)."""
        try:
            saldo = await asyncio.to_thread(
                self.tesouraria.saldo, ctx.guild.id, ctx.author.id)
        except EconomiaIndisponivel:
            await ctx.send("🏦 O cofre está fechado: XpAndCoins não está carregado.")
            return
        view = ViewLobby(self, ctx.author.id)
        view._mensagem = await ctx.send(embed=self.embed_lobby(saldo), view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Cassino(bot))
