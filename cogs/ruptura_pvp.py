"""
SEGREDO FLORESTA ADENTRO — RUPTURA TEMPORAL: DUELO (PvP)
=========================================================

Duelo 1v1 por turnos entre dois jogadores, usando as MESMAS classes,
passivas, técnicas, itens da mochila e builds (/build) do ruptura.py.
Este cog IMPORTA o ruptura.py e não altera nada nele.

Carregamento (arquivo cogs/ruptura_pvp.py; o cogs/ruptura.py precisa
estar carregado, pois a build é lida por ele):
    await bot.load_extension("cogs.ruptura")
    await bot.load_extension("cogs.ruptura_pvp")

Comandos:
    s!duelo @membro     desafia alguém (aliases: s!pvp, s!duel)
    s!duelorank         ranking de vitórias do servidor

COMO FUNCIONA
-------------
1. O desafiado aceita o convite.
2. Cada jogador escolhe a classe em segredo (menu único; a escolha só
   é revelada quando os dois escolhem).
3. Itens da mochila e a build da classe escolhida são equipados.
4. Turnos alternados (sorteio decide quem começa; quem começa depois
   ganha +1 Foco de compensação). Ações: Atacar, Guardar, Concentrar,
   Técnica da classe e habilidades ATIVAS da build.
5. Vence quem zerar a vida do outro (ou quem ficar com o oponente
   desistindo / inativo).

COMO O MOTOR É REAPROVEITADO
----------------------------
Cada duelista tem um RunState normal. O oponente é representado, para o
motor do ruptura.py, por uma "sombra" (AlvoPvP, um EnemyState) em
run.inimigo. Antes de cada ação a sombra é sincronizada com o oponente
real (vida + barreira, defesa); depois o dano que a sombra sofreu é
aplicado ao oponente passando pelas defesas dele (esquiva, guarda,
barreira, reduções, espinhos, contra-ataque, último fôlego).

REGRAS PRÓPRIAS DO PvP
----------------------
- Sem criaturas, sem habilidades de criatura, sem XP de run.
- Nível do duelo: NIVEL_BASE_PVP e sobe 1 a cada RODADAS_POR_NIVEL.
- Anti-empate: a partir da rodada LIMITE_COLAPSO+1 a ruptura colapsa e
  causa dano verdadeiro crescente em AMBOS.
- Dano contínuo (queimadura, veneno, sangria) é reduzido por
  FATOR_DOT_PVP. Atordoar: quem foi atordoado fica imune por 2 turnos.
- Esquiva total cancela também os status que o golpe aplicaria.
- Itens NÃO são consumidos no duelo (CONSUMIR_ITENS_PVP = False). Só
  passivos e artefatos entram: consumíveis e estratégicos ficam fora.
- Sem relíquias por padrão (RELIQUIAS_INICIAIS_PVP = 0).
- Sem recompensa de XP por padrão (XP_VITORIA_PVP / XP_DERROTA_PVP = 0).
- Roubo de vida continua exclusivo do Vampiro (vem do ruptura.py).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import sqlite3
import time
from typing import Callable, Optional

import discord
from discord.ext import commands

from cogs.ruptura import (
    CLASSES,
    CUSTO_CONCENTRAR,
    DB_PATH,
    ESPECS,
    FOCO_MAX,
    FOCO_POR_COMBATE,
    FRAQUEZA_PCT,
    ITENS,
    NOS,
    EnemySpec,
    EnemyState,
    RunState,
    award_rewards,
    barra_foco,
    conceder_reliquia,
    configurar_log_terminal,
    consumir_item,
    equipar_item_da_run,
    executar_ativa,
    executar_ataque,
    listar_inventario,
    motivo_indisponivel,
    preparar_tabela_inventario,
    ultimas_linhas,
    verificar_morte,
)

log = logging.getLogger("shaggy.ruptura.pvp")


# ============================================================
# 0. CONFIGURAÇÕES (ajuste sem mexer no motor)
# ============================================================

NIVEL_BASE_PVP = 6            # "nível da run" usado pelas passivas/builds
RODADAS_POR_NIVEL = 4         # o nível do duelo sobe 1 a cada N rodadas

LIMITE_COLAPSO = 14           # depois desta rodada a ruptura colapsa
COLAPSO_DANO = 4              # dano verdadeiro = COLAPSO_DANO * (rodada - limite)
MAX_RODADAS = 40              # teto de segurança (decide por % de vida)

FATOR_DOT_PVP = 0.6           # queimadura/veneno/sangria contra jogadores
FOCO_COMPENSACAO = 1          # Foco extra de quem joga em segundo
PROTECAO_ATORDOAR = 2         # turnos de imunidade após perder um turno

CONSUMIR_ITENS_PVP = False    # True = itens da mochila são gastos no duelo
RELIQUIAS_INICIAIS_PVP = 0    # relíquias aleatórias dadas a cada duelista
XP_VITORIA_PVP = 0            # XP via XpAndCoins para o vencedor
XP_DERROTA_PVP = 0            # XP via XpAndCoins para o perdedor

TIMEOUT_CONVITE = 60
TIMEOUT_ESCOLHA = 120
TIMEOUT_TURNO = 180           # inatividade de quem está na vez = W.O.
LINHAS_LOG_PVP = 10
MAX_LINHAS_GUARDADAS = 80


# ============================================================
# 1. PERSISTÊNCIA DO RANKING (mesmo banco do ruptura.py)
# ============================================================

def preparar_tabela_pvp() -> None:
    """Cria a tabela de placar sem tocar nas demais."""
    preparar_tabela_inventario()          # garante a pasta data/
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS ruptura_pvp (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                vitorias INTEGER NOT NULL DEFAULT 0,
                derrotas INTEGER NOT NULL DEFAULT 0,
                empates  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)


def registrar_resultado_pvp(guild_id: int, a_id: int, b_id: int,
                            vencedor_id: Optional[int]) -> None:
    """Soma vitória/derrota/empate para os dois jogadores (atômico)."""
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        for uid in (a_id, b_id):
            vit = 1 if vencedor_id == uid else 0
            der = 1 if vencedor_id not in (None, uid) else 0
            emp = 1 if vencedor_id is None else 0
            db.execute("""
                INSERT INTO ruptura_pvp
                    (guild_id, user_id, vitorias, derrotas, empates)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    vitorias = vitorias + excluded.vitorias,
                    derrotas = derrotas + excluded.derrotas,
                    empates  = empates  + excluded.empates
            """, (guild_id, uid, vit, der, emp))


def ranking_pvp(guild_id: int, limite: int = 10) -> list[tuple]:
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        return db.execute("""
            SELECT user_id, vitorias, derrotas, empates FROM ruptura_pvp
            WHERE guild_id = ?
            ORDER BY vitorias DESC, derrotas ASC, empates DESC
            LIMIT ?
        """, (guild_id, limite)).fetchall()


# ============================================================
# 2. ESTADO DO DUELO
# ============================================================

class AlvoPvP(EnemyState):
    """Sombra do oponente, no formato que o motor do ruptura.py espera.

    Guarda os status que ESTE jogador aplicou no oponente. A imunidade a
    atordoamento vale por turnos após o oponente perder um turno.
    """

    protecao_atordoar: int = 0

    @property
    def imunidades(self) -> frozenset:
        if self.protecao_atordoar > 0:
            return frozenset({"atordoar"})
        return frozenset()


def criar_alvo(nome: str) -> AlvoPvP:
    spec = EnemySpec(
        nome=nome, era="Duelo", nivel_minimo=1, vida=1, ataque=1, defesa=0,
        xp=0, abysmus=0, habilidade="duelo",   # sem habilidade registrada
        descricao="Um oponente de carne e osso.", categoria="normal",
    )
    return AlvoPvP(spec=spec, nivel=1, vida=1, vida_maxima=1,
                   ataque=1, defesa=0)


class Duelista:
    """Um lado do duelo: RunState + sombra do adversário."""

    def __init__(self, user_id: int, nome: str, run: RunState):
        self.user_id = user_id
        self.nome = nome
        self.run = run
        self.alvo: AlvoPvP = criar_alvo("?")
        self.oponente: "Duelista" = self       # ajustado em ligar_duelistas
        self.alvo_base = 0


class Resultado:
    def __init__(self, vencedor: Optional[Duelista], motivo: str):
        self.vencedor = vencedor
        self.motivo = motivo


class Duelo:
    def __init__(self, guild_id: int, canal_id: int,
                 a: Duelista, b: Duelista):
        self.guild_id = guild_id
        self.canal_id = canal_id
        self.a = a
        self.b = b
        self.primeiro: Duelista = a
        self.ativo: Duelista = a
        self.rodada = 1
        self.turnos = 0
        self.log: list[str] = []
        self.finalizado = False
        self.resultado: Optional[Resultado] = None
        self.inicio = time.monotonic()
        self.lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None

    @property
    def nivel(self) -> int:
        return NIVEL_BASE_PVP + (self.rodada - 1) // RODADAS_POR_NIVEL

    def duelistas(self) -> tuple[Duelista, Duelista]:
        return (self.a, self.b)


def ligar_duelistas(duelo: Duelo) -> None:
    a, b = duelo.a, duelo.b
    a.oponente, b.oponente = b, a
    a.alvo, b.alvo = criar_alvo(b.nome), criar_alvo(a.nome)
    a.run.inimigo, b.run.inimigo = a.alvo, b.alvo


# ============================================================
# 3. MOTOR DO DUELO (síncrono, sem Discord)
# ============================================================

_VOCE = re.compile(r"\b[Vv]ocê\b")

_CAMPOS_STATUS = ("queimadura", "veneno", "veneno_turnos", "sangria",
                  "marca", "fraqueza", "atordoado", "atordoado_usos")


def coletar(duelo: Duelo, d: Duelista) -> None:
    """Move o log do RunState para o log do duelo, trocando 'você' pelo nome."""
    run = d.run
    if not run.log:
        return
    for linha in run.log:
        duelo.log.append(_VOCE.sub(lambda _m: d.nome, linha))
    run.log.clear()
    del duelo.log[:-MAX_LINHAS_GUARDADAS]


def espelhar(d: Duelista) -> None:
    """Sincroniza a sombra de d com o oponente real (vida inclui barreira)."""
    o = d.oponente.run
    alvo = d.alvo
    alvo.vida = o.vida + o.barreira
    alvo.vida_maxima = max(1, o.vida_maxima + o.barreira)
    alvo.ataque = o.ataque
    alvo.defesa = o.defesa
    d.alvo_base = alvo.vida


def colher(d: Duelista) -> int:
    """Dano que a sombra de d sofreu desde o último espelhar()."""
    return max(0, d.alvo_base - d.alvo.vida)


def guardar_status(alvo: AlvoPvP) -> dict:
    return {campo: getattr(alvo, campo) for campo in _CAMPOS_STATUS}


def restaurar_status(alvo: AlvoPvP, foto: dict) -> None:
    for campo, valor in foto.items():
        setattr(alvo, campo, valor)


def dano_com_barreira(duelo: Duelo, d: Duelista, dano: int,
                      texto: str) -> None:
    """Dano que passa pela barreira antes de chegar à vida."""
    run = d.run
    bloqueado = min(run.barreira, dano)
    run.barreira -= bloqueado
    restante = dano - bloqueado
    run.vida = max(0, run.vida - restante)
    duelo.log.append(
        f"{texto} {d.nome}: {restante} de vida"
        + (f" ({bloqueado} absorvido pela barreira)" if bloqueado else "")
        + "."
    )
    verificar_morte(run)
    coletar(duelo, d)


def receber_golpe(duelo: Duelo, defensor: Duelista,
                  dano: int) -> tuple[int, bool]:
    """Resolve um golpe em `defensor` com as defesas dele.

    Ordem do ruptura.py: esquiva -> modificadores -> guarda -> barreira ->
    vida. A defesa (stat) já foi usada pelo atacante (metade dela reduz o
    dano na fórmula do ataque), então não é subtraída de novo aqui.
    Retorna (vida perdida, esquivou).
    """
    run = defensor.run
    nome = defensor.nome
    run.esquivou_agora = False

    if run.esquiva:
        run.esquiva = False
        run.esquivou_agora = True
        duelo.log.append(
            f"🌀 {nome} some entre as fendas e o golpe atravessa o vazio!")
        return 0, True

    original = dano
    for efeito in run.efeitos():
        dano = efeito.modificar_dano_recebido(run, dano)
    coletar(duelo, defensor)

    if original > 0 and dano <= 0:
        run.esquivou_agora = True
        return 0, True

    if run.guarda and dano > 0:
        dano = max(1, int(dano * run.fator_guarda))
        duelo.log.append(
            f"🛡️ A guarda de {nome} reduz o golpe em "
            f"{int((1 - run.fator_guarda) * 100)}%.")

    bloqueado = min(run.barreira, dano)
    run.barreira -= bloqueado
    dano -= bloqueado

    antes = run.vida
    run.vida = max(0, run.vida - dano)
    perdida = antes - run.vida

    if bloqueado > 0:
        duelo.log.append(
            f"🛡️ A barreira de {nome} absorveu {bloqueado} de dano.")
    if perdida > 0:
        duelo.log.append(f"💔 {nome} perdeu {perdida} de vida.")
    else:
        duelo.log.append(f"🛡️ {nome} resistiu completamente ao ataque!")

    for efeito in run.efeitos():
        efeito.ao_golpe_recebido(run, defensor.alvo, perdida)
    coletar(duelo, defensor)
    verificar_morte(run)
    coletar(duelo, defensor)
    return perdida, False


def tick_status(duelo: Duelo, d: Duelista) -> None:
    """Início do turno de d: queimadura, veneno e sangria aplicados nele.

    Os status ficam na sombra que o OPONENTE mantém de d.
    """
    sombra = d.oponente.alvo
    nivel = duelo.nivel
    run = d.run

    def ferir(dano: float, texto: str) -> None:
        valor = max(1, int(dano * FATOR_DOT_PVP))
        run.vida = max(0, run.vida - valor)
        duelo.log.append(texto.replace("{n}", str(valor)))
        verificar_morte(run)
        coletar(duelo, d)

    if sombra.queimadura > 0 and run.vida > 0:
        sombra.queimadura -= 1
        ferir(5 + nivel, f"🔥 A queimadura causa {{n}} de dano a {d.nome}.")

    if sombra.veneno > 0 and run.vida > 0:
        base = sombra.veneno * (2 + nivel // 4)
        ferir(base,
              f"☠️ O veneno ({sombra.veneno}x) causa {{n}} de dano a {d.nome}.")
        sombra.veneno_turnos -= 1
        if sombra.veneno_turnos <= 0:
            sombra.veneno = 0

    if sombra.sangria > 0 and run.vida > 0:
        sombra.sangria -= 1
        ferir(4 + nivel // 2,
              f"🩸 O sangramento causa {{n}} de dano a {d.nome}.")


def colapso(duelo: Duelo) -> None:
    """Dano verdadeiro crescente em ambos depois da rodada-limite."""
    dano = COLAPSO_DANO * (duelo.rodada - LIMITE_COLAPSO)
    duelo.log.append(f"🌀 **A ruptura colapsa!** Ambos sofrem {dano} de dano.")
    for d in duelo.duelistas():
        d.run.vida = max(0, d.run.vida - dano)
        verificar_morte(d.run)
        coletar(duelo, d)


def checar_fim(duelo: Duelo) -> Optional[Resultado]:
    a, b = duelo.a, duelo.b
    a_morto, b_morto = a.run.vida <= 0, b.run.vida <= 0

    if a_morto and b_morto:
        return Resultado(None, "A ruptura devorou os dois ao mesmo tempo.")
    if a_morto:
        return Resultado(b, f"{a.nome} foi consumido pela ruptura.")
    if b_morto:
        return Resultado(a, f"{b.nome} foi consumido pela ruptura.")

    if duelo.rodada > MAX_RODADAS:
        fa = a.run.vida / max(1, a.run.vida_maxima)
        fb = b.run.vida / max(1, b.run.vida_maxima)
        if abs(fa - fb) < 0.01:
            return Resultado(None, "O tempo acabou e ninguém levou vantagem.")
        vencedor = a if fa > fb else b
        return Resultado(vencedor, "O tempo acabou: venceu quem tinha mais vida.")
    return None


def avancar_turno(duelo: Duelo) -> Optional[Resultado]:
    """Passa a vez; resolve início de rodada, status e atordoamento."""
    for tentativa in range(4):
        prox = duelo.ativo.oponente
        duelo.ativo = prox
        duelo.turnos += 1

        if prox is duelo.primeiro:
            duelo.rodada += 1
            for d in duelo.duelistas():
                d.run.nivel = duelo.nivel
            if duelo.rodada > LIMITE_COLAPSO:
                colapso(duelo)
            fim = checar_fim(duelo)
            if fim:
                return fim

        tick_status(duelo, prox)
        fim = checar_fim(duelo)
        if fim:
            return fim

        sombra = prox.oponente.alvo
        if sombra.atordoado and tentativa < 3:
            sombra.atordoado = False
            sombra.protecao_atordoar = PROTECAO_ATORDOAR
            duelo.log.append(
                f"💫 **{prox.nome}** está atordoado e perde o turno.")
            prox.oponente.run.guarda = False
            prox.oponente.run.esquiva = False
            continue
        return None
    return None


def jogar_turno(duelo: Duelo, d: Duelista,
                acao: Callable[[RunState], None]) -> Optional[Resultado]:
    """Turno completo de `d`. Devolve o Resultado se o duelo terminou."""
    o = d.oponente
    run = d.run

    duelo.log.append(f"**▶ {d.nome}**")
    run.turno += 1
    espelhar(d)
    foto = guardar_status(d.alvo)

    acao(run)
    for efeito in run.efeitos():            # ecos, invocações, regeneração
        efeito.ao_fim_turno(run)
    coletar(duelo, d)

    dano = colher(d)
    if dano > 0 and o.run.vida > 0:
        if o.alvo.fraqueza > 0:             # d está enfraquecido por o
            dano = max(1, int(dano * (1 - FRAQUEZA_PCT / 100)))
            o.alvo.fraqueza -= 1
            duelo.log.append(
                f"📉 {d.nome} está enfraquecido (-{FRAQUEZA_PCT}% de dano).")

        espelhar(o)                         # sombra de d vista por o
        _, esquivou = receber_golpe(duelo, o, dano)
        if esquivou:
            restaurar_status(d.alvo, foto)  # sem acerto, sem status

        retorno = colher(o)                 # espinhos / contra-ataque
        if retorno > 0 and run.vida > 0:
            dano_com_barreira(duelo, d, retorno, "↩️ O revide atinge")

    o.run.guarda = False                    # defesas duram até o fim da vez
    o.run.esquiva = False
    o.alvo.protecao_atordoar = max(0, o.alvo.protecao_atordoar - 1)

    fim = checar_fim(duelo)
    if fim:
        return fim
    return avancar_turno(duelo)


# ---------- ações do jogador (mesmas regras do TelaCombate do PvE) ----------

def acao_atacar(run: RunState) -> None:
    executar_ataque(run)
    ganho = run.ganhar_foco(1 + (1 if run.ultimo_critico else 0))
    if ganho > 0:
        run.log.append(f"⚡ +{ganho} Foco.")


def acao_guardar(run: RunState) -> None:
    run.guarda = True
    ganho = run.ganhar_foco(1)
    run.log.append(
        "🛡️ Você assume guarda: o próximo golpe sofrido é reduzido."
        + (f" ⚡ +{ganho} Foco." if ganho else ""))
    for efeito in run.efeitos():
        efeito.ao_defender(run)


def acao_concentrar(run: RunState) -> None:
    mult = 1 + run.conc_bonus() / 100
    cura = run.curar(int((12 + min(8, run.nivel // 2)) * mult))
    barreira = int(5 * mult)
    run.barreira += barreira
    run.log.append(
        f"✨ Você recupera {cura} de vida e ganha {barreira} de barreira.")


def acao_tecnica(run: RunState) -> None:
    run.golpe_tecnica = True
    run.ultimo_dano_real = 0
    try:
        run.classe.tecnica.acao(run)
    finally:
        run.golpe_tecnica = False
    for efeito in run.efeitos():
        efeito.ao_tecnica(run)


def preparar_duelista(duelo: Duelo, d: Duelista) -> None:
    """Equivalente do preparar_combate() do PvE para um duelista."""
    run = d.run
    run.inimigo = d.alvo
    run.nivel = duelo.nivel
    run.turno = 0
    run.marcado = False
    run.ataque_bloqueado = False
    run.guarda = False
    run.esquiva = False
    run.ultimo_critico = False
    run.golpe_tecnica = False
    run.golpe_ativa = False
    run.esquivou_agora = False
    run.golpes_combate = 0
    run.ultimo_dano_real = 0

    run.ganhar_foco(FOCO_POR_COMBATE + run.foco_por_combate)
    if run.barreira < run.barreira_inicial:
        run.barreira = run.barreira_inicial

    espelhar(d)
    for efeito in run.efeitos():
        efeito.ao_iniciar_combate(run, d.alvo)
    coletar(duelo, d)


def preparar_inicio(duelo: Duelo) -> None:
    duelo.primeiro = random.choice(duelo.duelistas())
    duelo.ativo = duelo.primeiro
    segundo = duelo.primeiro.oponente

    duelo.log.append(
        f"⚔️ **A fenda se abre.** {duelo.a.nome} ({duelo.a.run.classe.nome}) "
        f"enfrenta {duelo.b.nome} ({duelo.b.run.classe.nome}).")
    for d in duelo.duelistas():
        preparar_duelista(duelo, d)
    segundo.run.ganhar_foco(FOCO_COMPENSACAO)
    duelo.log.append(
        f"🎲 {duelo.primeiro.nome} começa; {segundo.nome} ganha "
        f"+{FOCO_COMPENSACAO} Foco de compensação.")


# ============================================================
# 4. EMBEDS
# ============================================================

def barra_vida(vida: int, maximo: int, tamanho: int = 10) -> str:
    fracao = max(0.0, min(1.0, vida / max(1, maximo)))
    cheio = round(fracao * tamanho)
    if vida > 0 and cheio == 0:
        cheio = 1
    return "█" * cheio + "░" * (tamanho - cheio)


def status_duelista(d: Duelista) -> str:
    run = d.run
    sombra = d.oponente.alvo      # status que o oponente colocou em d
    partes = []
    if run.guarda:
        partes.append("🛡️ Em guarda")
    if run.esquiva:
        partes.append("🌀 Esquiva armada")
    if sombra.queimadura > 0:
        partes.append(f"🔥 Em chamas ({sombra.queimadura})")
    if sombra.veneno > 0:
        partes.append(f"☠️ Veneno x{sombra.veneno}")
    if sombra.sangria > 0:
        partes.append(f"🩸 Sangrando ({sombra.sangria})")
    if sombra.marca > 0:
        partes.append(f"🎯 Marcado ({sombra.marca})")
    if sombra.fraqueza > 0:
        partes.append(f"📉 Enfraquecido ({sombra.fraqueza})")
    if sombra.atordoado:
        partes.append("💫 Atordoado")
    if run.build is not None:
        if run.build.combo:
            partes.append(f"🔗 Combo x{run.build.combo}")
        if run.build.invocacoes:
            partes.append("⚙️ " + ", ".join(
                f"{i['nome']} ({i['turnos']})" for i in run.build.invocacoes))
    return " · ".join(partes) or "Nenhum"


def texto_duelista(d: Duelista) -> str:
    run = d.run
    linhas = [
        f"❤️ **{run.vida}/{run.vida_maxima}** "
        f"{barra_vida(run.vida, run.vida_maxima)}",
        f"⚡ {barra_foco(run)} ({run.foco}/{FOCO_MAX})",
        f"⚔️ {run.ataque} · 🧱 {run.defesa} · 🛡️ {run.barreira}",
        f"✨ {run.classe.passiva.nome} · 💥 {run.classe.tecnica.nome}",
    ]
    if run.build is not None:
        linhas.append(
            f"🌳 {ESPECS[run.build.spec_id].nome} "
            f"({sum(run.build.nos.values())} nível(is))")
    if run.equipados:
        linhas.append(f"🎒 {len(run.equipados)} item(ns) equipado(s)")
    linhas.append(f"**Status:** {status_duelista(d)}")
    return "\n".join(linhas)


def criar_embed_duelo(duelo: Duelo, titulo: Optional[str] = None) -> discord.Embed:
    ativo = duelo.ativo
    embed = discord.Embed(
        title=titulo or f"⚔️ DUELO — Rodada {duelo.rodada}",
        color=discord.Color.dark_red(),
    )

    if not duelo.finalizado:
        aviso = ""
        if duelo.rodada > LIMITE_COLAPSO:
            aviso = (f"\n🌀 **Colapso ativo:** "
                     f"{COLAPSO_DANO * (duelo.rodada - LIMITE_COLAPSO)} de "
                     "dano verdadeiro por rodada.")
        elif duelo.rodada >= LIMITE_COLAPSO - 2:
            aviso = (f"\n⚠️ A ruptura colapsa depois da rodada "
                     f"{LIMITE_COLAPSO}.")
        embed.description = (
            f"▶ **Vez de {ativo.nome}** ({ativo.run.classe.nome})"
            f" · Nível do duelo {duelo.nivel}{aviso}")

    for d in duelo.duelistas():
        marca = "▶ " if (d is ativo and not duelo.finalizado) else ""
        embed.add_field(
            name=f"{marca}{d.nome} — {d.run.classe.nome}"[:256],
            value=texto_duelista(d)[:1024], inline=False)

    if duelo.log:
        embed.add_field(
            name="Últimos acontecimentos",
            value=ultimas_linhas(duelo.log, LINHAS_LOG_PVP),
            inline=False)

    embed.set_footer(
        text=(f"Atacar/Guardar +1⚡ · Concentrar -{CUSTO_CONCENTRAR}⚡ · "
              f"Técnica e habilidades gastam Foco · "
              f"Colapso após a rodada {LIMITE_COLAPSO}"))
    return embed


# ============================================================
# 5. INTERFACE: CONVITE, ESCOLHA DE CLASSE E TELA DE DUELO
# ============================================================

class ConviteDuelo(discord.ui.View):
    """Convite com Aceitar / Recusar."""

    def __init__(self, cog: "RupturaDuelo", desafiante: discord.Member,
                 desafiado: discord.Member):
        super().__init__(timeout=TIMEOUT_CONVITE)
        self.cog = cog
        self.desafiante = desafiante
        self.desafiado = desafiado
        self.message: Optional[discord.Message] = None
        self.resolvido = False

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="⚔️ Desafio de Duelo — Ruptura Temporal",
            description=(
                f"{self.desafiante.mention} desafiou {self.desafiado.mention}!\n\n"
                "Cada um escolhe uma classe **em segredo**. Valem os itens da "
                "sua mochila (`s!inventario`) e a sua build (`/build`).\n"
                f"O convite expira em {TIMEOUT_CONVITE}s."),
            color=discord.Color.dark_red())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.desafiante.id, self.desafiado.id):
            await interaction.response.send_message(
                "Este convite não é para você.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.success,
                       emoji="⚔️")
    async def aceitar(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        if interaction.user.id != self.desafiado.id:
            await interaction.response.send_message(
                "Só quem foi desafiado pode aceitar.", ephemeral=True)
            return
        if self.resolvido:
            await interaction.response.send_message(
                "Este convite já foi resolvido.", ephemeral=True)
            return

        motivo = self.cog.motivo_indisponivel(self.desafiado, convidado=True)
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
            return

        self.resolvido = True
        self.cog.ocupados.add(self.desafiado.id)
        self.stop()
        tela = EscolhaClasse(self.cog, self.desafiante, self.desafiado)
        await interaction.response.edit_message(
            content=None, embed=tela.embed(), view=tela)
        tela.message = await interaction.original_response()

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger,
                       emoji="✖️")
    async def recusar(self, interaction: discord.Interaction,
                      button: discord.ui.Button):
        if self.resolvido:
            await interaction.response.send_message(
                "Este convite já foi resolvido.", ephemeral=True)
            return
        self.resolvido = True
        self.stop()
        self.cog.liberar(self.desafiante.id)
        quem = ("cancelou o desafio" if interaction.user.id ==
                self.desafiante.id else "recusou o desafio")
        await interaction.response.edit_message(
            content=None, view=None,
            embed=discord.Embed(
                title="⚔️ Duelo cancelado",
                description=f"{interaction.user.mention} {quem}.",
                color=discord.Color.dark_grey()))

    async def on_timeout(self) -> None:
        if self.resolvido:
            return
        self.resolvido = True
        self.cog.liberar(self.desafiante.id)
        if self.message is not None:
            try:
                await self.message.edit(
                    content=None, view=None,
                    embed=discord.Embed(
                        title="⚔️ Convite expirado",
                        description="Ninguém respondeu a tempo.",
                        color=discord.Color.dark_grey()))
            except discord.HTTPException:
                pass


class SelecaoClassePvP(discord.ui.Select):
    """Menu de classe (gerado a partir de CLASSES)."""

    def __init__(self, tela: "EscolhaClasse"):
        self.tela = tela
        opcoes = [
            discord.SelectOption(
                label=classe.nome[:100], value=chave,
                description=(f"{classe.passiva.nome} · "
                             f"{classe.tecnica.nome}")[:100])
            for chave, classe in list(CLASSES.items())[:25]
        ]
        super().__init__(placeholder="Escolha sua classe (em segredo)",
                         min_values=1, max_values=1, options=opcoes)

    async def callback(self, interaction: discord.Interaction):
        await self.tela.escolher(interaction, self.values[0])


class EscolhaClasse(discord.ui.View):
    """Cada jogador escolhe a classe; o duelo começa quando os dois escolhem."""

    def __init__(self, cog: "RupturaDuelo", p1: discord.Member,
                 p2: discord.Member):
        super().__init__(timeout=TIMEOUT_ESCOLHA)
        self.cog = cog
        self.p1 = p1
        self.p2 = p2
        self.picks: dict[int, str] = {}
        self.iniciando = False
        self.lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None
        self.add_item(SelecaoClassePvP(self))

    def embed(self) -> discord.Embed:
        def linha(m: discord.Member) -> str:
            return (f"✅ {m.mention} escolheu" if m.id in self.picks
                    else f"⏳ {m.mention} está escolhendo…")
        return discord.Embed(
            title="⚔️ Escolha sua classe",
            description=(
                f"{linha(self.p1)}\n{linha(self.p2)}\n\n"
                "As escolhas são reveladas só quando os dois escolherem. "
                "Você pode trocar a sua até o oponente escolher.\n"
                "Itens da mochila e a build da classe escolhida serão "
                "equipados automaticamente."),
            color=discord.Color.dark_red())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await interaction.response.send_message(
                "Você não está neste duelo.", ephemeral=True)
            return False
        return True

    async def escolher(self, interaction: discord.Interaction,
                       chave: str) -> None:
        async with self.lock:
            if self.iniciando:
                await interaction.response.send_message(
                    "O duelo já está começando.", ephemeral=True)
                return
            self.picks[interaction.user.id] = chave
            if len(self.picks) < 2:
                await interaction.response.send_message(
                    f"✅ Você escolheu **{CLASSES[chave].nome}**. Aguardando "
                    "o oponente…", ephemeral=True)
                try:
                    await interaction.message.edit(embed=self.embed(),
                                                   view=self)
                except discord.HTTPException:
                    pass
                return
            self.iniciando = True

        await interaction.response.defer()
        self.stop()
        await self.cog.iniciar_duelo(
            interaction, self.p1, self.p2,
            self.picks[self.p1.id], self.picks[self.p2.id])

    async def on_timeout(self) -> None:
        if self.iniciando:
            return
        self.cog.liberar(self.p1.id, self.p2.id)
        if self.message is not None:
            try:
                await self.message.edit(
                    content=None, view=None,
                    embed=discord.Embed(
                        title="⚔️ Duelo cancelado",
                        description="Alguém não escolheu a classe a tempo.",
                        color=discord.Color.dark_grey()))
            except discord.HTTPException:
                pass


class SelecaoAtivaPvP(discord.ui.Select):
    """Habilidades ATIVAS da build de quem está na vez."""

    def __init__(self, tela: "TelaDuelo", d: Duelista):
        self.tela = tela
        opcoes = [
            discord.SelectOption(
                label=f"{no.nome} ({no.ativa.foco}⚡)"[:100], value=no.id,
                description=(motivo_indisponivel(d.run, no, curto=True)
                             or "pronta")[:100])
            for no in d.run.build.ativas
        ]
        super().__init__(placeholder=f"Habilidades de {d.nome}"[:150],
                         min_values=1, max_values=1, options=opcoes, row=1)

    async def callback(self, interaction: discord.Interaction):
        await self.tela.usar_ativa(interaction, self.values[0])


class TelaDuelo(discord.ui.View):
    """Botões do duelo; só quem está na vez pode agir."""

    def __init__(self, cog: "RupturaDuelo", duelo: Duelo):
        super().__init__(timeout=TIMEOUT_TURNO)
        self.cog = cog
        self.duelo = duelo
        self.message: Optional[discord.Message] = None
        self.menu: Optional[SelecaoAtivaPvP] = None
        self.btn_concentrar.label = f"Concentrar ({CUSTO_CONCENTRAR}⚡)"
        self.atualizar_botoes()

    def atualizar_botoes(self) -> None:
        """Ajusta botões e menu ao Foco e à build de quem está na vez."""
        d = self.duelo.ativo
        run = d.run
        custo = run.custo_tecnica()
        self.btn_tecnica.label = f"{run.classe.tecnica.nome} ({custo}⚡)"[:80]
        self.btn_concentrar.disabled = run.foco < CUSTO_CONCENTRAR
        self.btn_tecnica.disabled = run.foco < custo

        if self.menu is not None:
            self.remove_item(self.menu)
            self.menu = None
        if run.build is not None and run.build.ativas:
            self.menu = SelecaoAtivaPvP(self, d)
            self.add_item(self.menu)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        duelo = self.duelo
        if interaction.user.id not in (duelo.a.user_id, duelo.b.user_id):
            await interaction.response.send_message(
                "Você não está neste duelo.", ephemeral=True)
            return False
        if duelo.finalizado:
            await interaction.response.send_message(
                "Este duelo já terminou.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        """Quem estava na vez e sumiu perde por W.O."""
        duelo = self.duelo
        async with duelo.lock:
            if duelo.finalizado:
                return
            ausente = duelo.ativo
            resultado = Resultado(
                ausente.oponente,
                f"{ausente.nome} ficou inativo e perdeu por W.O.")
            embed = await self.cog.finalizar_duelo(duelo, resultado)
            if self.message is not None:
                try:
                    await self.message.edit(content=None, embed=embed,
                                            view=None)
                except discord.HTTPException:
                    log.warning("Não consegui editar a mensagem do duelo.")

    async def _finalizar(self, interaction: discord.Interaction,
                         resultado: Resultado) -> None:
        embed = await self.cog.finalizar_duelo(self.duelo, resultado)
        self.stop()
        await interaction.edit_original_response(
            content=None, embed=embed, view=None)

    async def _executar(self, interaction: discord.Interaction,
                        acao: Callable[[RunState], None],
                        custo: int = 0) -> None:
        duelo = self.duelo
        async with duelo.lock:
            if duelo.finalizado:
                await interaction.response.send_message(
                    "Este duelo já terminou.", ephemeral=True)
                return
            d = duelo.ativo
            if interaction.user.id != d.user_id:
                await interaction.response.send_message(
                    f"Aguarde: é a vez de {d.nome}.", ephemeral=True)
                return
            if d.run.foco < custo:
                await interaction.response.send_message(
                    f"Foco insuficiente ({d.run.foco}/{custo} ⚡). "
                    "Ataque ou use Guardar para recuperar.", ephemeral=True)
                return

            await interaction.response.defer()
            d.run.foco -= custo
            try:
                resultado = jogar_turno(duelo, d, acao)
            except Exception:
                log.exception("Erro no turno do duelo (%s vs %s).",
                              duelo.a.nome, duelo.b.nome)
                await interaction.followup.send(
                    "❌ Ocorreu um erro interno neste turno. Tente de novo "
                    "ou use Desistir.", ephemeral=True)
                return

            if resultado is not None:
                await self._finalizar(interaction, resultado)
                return

            self.atualizar_botoes()
            await interaction.edit_original_response(
                embed=criar_embed_duelo(duelo), view=self)

    @discord.ui.button(label="Atacar", style=discord.ButtonStyle.danger,
                       emoji="⚔️", row=0)
    async def btn_atacar(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await self._executar(interaction, acao_atacar)

    @discord.ui.button(label="Guardar", style=discord.ButtonStyle.secondary,
                       emoji="🛡️", row=0)
    async def btn_guardar(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        await self._executar(interaction, acao_guardar)

    @discord.ui.button(label="Concentrar", style=discord.ButtonStyle.primary,
                       emoji="✨", row=0)
    async def btn_concentrar(self, interaction: discord.Interaction,
                             button: discord.ui.Button):
        await self._executar(interaction, acao_concentrar,
                             custo=CUSTO_CONCENTRAR)

    @discord.ui.button(label="Técnica", style=discord.ButtonStyle.success,
                       emoji="💥", row=0)
    async def btn_tecnica(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        custo = self.duelo.ativo.run.custo_tecnica()
        await self._executar(interaction, acao_tecnica, custo=custo)

    @discord.ui.button(label="Desistir", style=discord.ButtonStyle.secondary,
                       emoji="🏳️", row=0)
    async def btn_desistir(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        duelo = self.duelo
        async with duelo.lock:
            if duelo.finalizado:
                await interaction.response.send_message(
                    "Este duelo já terminou.", ephemeral=True)
                return
            await interaction.response.defer()
            quem = duelo.a if interaction.user.id == duelo.a.user_id else duelo.b
            await self._finalizar(interaction, Resultado(
                quem.oponente, f"{quem.nome} desistiu do duelo."))

    async def usar_ativa(self, interaction: discord.Interaction,
                         node_id: str) -> None:
        d = self.duelo.ativo
        if interaction.user.id != d.user_id:
            await interaction.response.send_message(
                f"Aguarde: é a vez de {d.nome}.", ephemeral=True)
            return
        no = NOS.get(node_id)
        run = d.run
        if (no is None or no.ativa is None or run.build is None
                or no not in run.build.ativas):
            await interaction.response.send_message(
                "Habilidade indisponível.", ephemeral=True)
            return
        motivo = motivo_indisponivel(run, no)
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
            return
        await self._executar(
            interaction, lambda r: executar_ativa(r, no), custo=no.ativa.foco)


# ============================================================
# 6. COG
# ============================================================

class RupturaDuelo(commands.Cog):
    """Duelo PvP da Ruptura Temporal."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        preparar_tabela_pvp()
        self.ocupados: set[int] = set()     # convidando / escolhendo / duelando

    async def cog_unload(self) -> None:
        if self.ocupados:
            log.warning("Cog descarregado com %d jogador(es) ocupado(s).",
                        len(self.ocupados))
        self.ocupados.clear()

    # ---------- utilidades ----------

    def liberar(self, *ids: int) -> None:
        for uid in ids:
            self.ocupados.discard(uid)

    def _ruptura(self):
        return self.bot.get_cog("RupturaTemporal")

    def motivo_indisponivel(self, membro: discord.Member,
                            convidado: bool = False) -> str:
        """Texto do motivo pelo qual `membro` não pode duelar agora ('' = ok)."""
        ruptura = self._ruptura()
        if ruptura is None:
            return "O módulo Ruptura Temporal não está carregado."
        quem = "Você" if convidado else membro.display_name
        if membro.id in self.ocupados:
            return f"{quem} já está em um convite ou duelo."
        if membro.id in ruptura.runs_ativas:
            return (f"{quem} tem uma run ativa de Ruptura. "
                    "Termine-a antes de duelar.")
        return ""

    # ---------- comandos ----------

    @commands.command(name="duelo", aliases=("pvp", "duel"))
    @commands.guild_only()
    async def duelo(self, ctx: commands.Context,
                    oponente: Optional[discord.Member] = None):
        """Desafia alguém para um duelo: `s!duelo @membro`."""
        if oponente is None:
            await ctx.send("Uso: `s!duelo @membro` — desafia alguém para "
                           "um duelo da Ruptura Temporal.")
            return
        if oponente.bot:
            await ctx.send("Bots não duelam. Bem... este aqui não.")
            return
        if oponente.id == ctx.author.id:
            await ctx.send("Você não pode duelar contra si mesmo.")
            return

        for membro in (ctx.author, oponente):
            motivo = self.motivo_indisponivel(membro)
            if motivo:
                await ctx.send(motivo)
                return

        self.ocupados.add(ctx.author.id)
        view = ConviteDuelo(self, ctx.author, oponente)
        try:
            view.message = await ctx.send(
                content=oponente.mention, embed=view.embed(), view=view)
        except Exception:
            self.liberar(ctx.author.id)
            raise

    @commands.command(name="duelorank", aliases=("rankpvp",))
    @commands.guild_only()
    async def duelorank(self, ctx: commands.Context):
        """Ranking de vitórias nos duelos do servidor."""
        linhas = await asyncio.to_thread(ranking_pvp, ctx.guild.id, 10)
        if not linhas:
            await ctx.send("Ninguém duelou neste servidor ainda. "
                           "Use `s!duelo @membro`.")
            return
        medalhas = ["🥇", "🥈", "🥉"]
        texto = "\n".join(
            f"{medalhas[i] if i < 3 else f'`{i + 1}.`'} <@{uid}> — "
            f"**{v}**V · {d}D · {e}E"
            for i, (uid, v, d, e) in enumerate(linhas))
        await ctx.send(embed=discord.Embed(
            title="🏆 Ranking de Duelos — Ruptura Temporal",
            description=texto, color=discord.Color.gold()))

    # ---------- montagem do duelo ----------

    async def equipar_itens(self, run: RunState) -> None:
        """Equipa só passivos/artefatos; só consome se CONSUMIR_ITENS_PVP.

        Consumíveis e estratégicos ficam fora do PvP: a regra do duelo é
        usar apenas itens permanentes (passivos e artefatos).
        """
        inventario = await asyncio.to_thread(
            listar_inventario, run.guild_id, run.user_id)
        for chave, qtd in inventario.items():
            item = ITENS.get(chave)
            if item is None or item.tipo not in ("passivo", "artefato"):
                continue
            usar = min(qtd, item.limite)
            if CONSUMIR_ITENS_PVP:
                ok = await asyncio.to_thread(
                    consumir_item, run.guild_id, run.user_id, chave, usar)
                if not ok:
                    continue
            if not equipar_item_da_run(run, chave, vezes=usar):
                continue
            run.equipados.append(f"{item.nome} ×{usar} — {item.descricao}")

    async def montar_duelista(self, guild_id: int, membro: discord.Member,
                              chave: str) -> Duelista:
        """Mesma ordem do iniciar_run do PvE: passiva -> itens -> build."""
        classe = CLASSES[chave]
        nome = discord.utils.escape_markdown(membro.display_name)
        run = RunState(
            user_id=membro.id, guild_id=guild_id, user_nome=membro.display_name,
            classe=classe, classe_key=chave,
            vida=classe.vida, vida_maxima=classe.vida,
            ataque=classe.ataque, defesa=classe.defesa,
        )
        run.evento(f"Duelo: {classe.nome} | vida={run.vida} "
                   f"ataque={run.ataque} defesa={run.defesa}")

        classe.passiva.ao_obter(run)

        try:
            await self.equipar_itens(run)
        except Exception:
            log.exception("Falha ao equipar itens de %s.", membro.id)

        ruptura = self._ruptura()
        try:
            if ruptura is not None:
                await ruptura.carregar_build_run(run)
        except Exception:
            log.exception("Falha ao carregar a build de %s.", membro.id)

        for _ in range(RELIQUIAS_INICIAIS_PVP):
            conceder_reliquia(run)

        return Duelista(membro.id, nome, run)

    async def iniciar_duelo(self, interaction: discord.Interaction,
                            p1: discord.Member, p2: discord.Member,
                            chave1: str, chave2: str) -> None:
        guild_id = interaction.guild_id or 0
        try:
            d1 = await self.montar_duelista(guild_id, p1, chave1)
            d2 = await self.montar_duelista(guild_id, p2, chave2)
            duelo = Duelo(guild_id, interaction.channel_id or 0, d1, d2)
            ligar_duelistas(duelo)
            preparar_inicio(duelo)

            view = TelaDuelo(self, duelo)
            await interaction.edit_original_response(
                content=None, embed=criar_embed_duelo(duelo), view=view)
            view.message = await interaction.original_response()
            duelo.message = view.message
            log.info("Duelo iniciado | guild=%s | %s (%s) x %s (%s)",
                     guild_id, d1.nome, chave1, d2.nome, chave2)
        except Exception:
            log.exception("Falha ao iniciar o duelo entre %s e %s.",
                          p1.id, p2.id)
            self.liberar(p1.id, p2.id)
            try:
                await interaction.edit_original_response(
                    content="❌ Não consegui iniciar o duelo.",
                    embed=None, view=None)
            except discord.HTTPException:
                pass

    async def finalizar_duelo(self, duelo: Duelo,
                              resultado: Resultado) -> discord.Embed:
        """Encerra o duelo uma única vez e devolve o embed final."""
        if duelo.finalizado:
            return criar_embed_duelo(duelo, "FIM DO DUELO")
        duelo.finalizado = True
        duelo.resultado = resultado
        self.liberar(duelo.a.user_id, duelo.b.user_id)

        vencedor = resultado.vencedor
        duracao = int(time.monotonic() - duelo.inicio)
        log.info(
            "DUELO FINALIZADO | guild=%s | %s (%s) x %s (%s) | vencedor=%s "
            "| rodadas=%d | motivo=%s | duração=%ds",
            duelo.guild_id, duelo.a.nome, duelo.a.run.classe_key,
            duelo.b.nome, duelo.b.run.classe_key,
            vencedor.nome if vencedor else "empate",
            duelo.rodada, resultado.motivo, duracao)

        try:
            await asyncio.to_thread(
                registrar_resultado_pvp, duelo.guild_id, duelo.a.user_id,
                duelo.b.user_id, vencedor.user_id if vencedor else None)
        except Exception:
            log.exception("Falha ao registrar o placar do duelo.")

        recompensa = ""
        if XP_VITORIA_PVP > 0 or XP_DERROTA_PVP > 0:
            for d in duelo.duelistas():
                xp = (XP_VITORIA_PVP if d is vencedor else XP_DERROTA_PVP)
                if xp > 0:
                    await award_rewards(
                        self.bot, duelo.guild_id, d.user_id, xp=xp,
                        origem="duelo_ruptura")
            recompensa = (f"\n🎖️ XP: +{XP_VITORIA_PVP} (vencedor) / "
                          f"+{XP_DERROTA_PVP} (perdedor).")

        self.bot.dispatch("ruptura_pvp_finalizada", {
            "guild_id": duelo.guild_id,
            "a": duelo.a.user_id, "b": duelo.b.user_id,
            "classe_a": duelo.a.run.classe_key,
            "classe_b": duelo.b.run.classe_key,
            "vencedor": vencedor.user_id if vencedor else None,
            "rodadas": duelo.rodada, "duracao": duracao,
            "motivo": resultado.motivo,
        })

        embed = criar_embed_duelo(duelo, "FIM DO DUELO")
        topo = (f"🏆 **Vencedor:** {vencedor.nome} "
                f"({vencedor.run.classe.nome})" if vencedor
                else "🤝 **Empate.**")
        embed.description = (
            f"{topo}\n{resultado.motivo}\n"
            f"Rodadas: {duelo.rodada} · Duração: {duracao}s{recompensa}\n\n"
            "Revanche? Use `s!duelo @oponente` · Ranking: `s!duelorank`")
        embed.color = discord.Color.gold() if vencedor else discord.Color.light_grey()
        return embed


async def setup(bot: commands.Bot):
    """Ponto de entrada do cog (bot.load_extension)."""
    configurar_log_terminal()
    await bot.add_cog(RupturaDuelo(bot))
