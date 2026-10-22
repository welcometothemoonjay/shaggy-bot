"""
SEGREDO FLORESTA ADENTRO — RUPTURA TEMPORAL
============================================

Roguelite para Discord (discord.py 2.x) feito para rodar como cog do
Shaggy Bot.

Carregamento:
    await bot.load_extension("cogs.RupturaTemporal")

Comandos prefixados:
    s!ruptura      inicia uma run
    s!market       mostra a loja (s!market comprar CHAVE quantidade)
    s!inventario   mostra a mochila

REGRAS
------
- Não existe seleção de habilidades a cada nível.
- A cada 3 níveis da run, uma relíquia é concedida automaticamente.
- Cada criatura derrotada concede XP; Abysmus cai por categoria.
- Ao finalizar a run: bônus de XP = nível da run * randint(1, 5).
- Cada classe tem atributos próprios, UMA passiva e UMA técnica exclusivas.
- Roubo de vida existe SOMENTE na classe Vampiro (nenhuma relíquia dá isso).
- Criaturas possuem habilidades próprias e mostram sua INTENÇÃO no turno.
- Recompensas passam por award_rewards() (integração com XpAndCoins).
- Cada run gera logs no terminal do bot (logger "shaggy.ruptura").

COMBATE (turnos de decisão)
---------------------------
O combate usa um recurso, o FOCO (⚡, máximo 5), que dá ritmo às decisões:

    ⚔️ Atacar       gera +1 Foco (+1 extra num crítico)
    🛡️ Guardar      gera +1 Foco; o próximo golpe inimigo causa metade
    ✨ Concentrar   custa 2 Foco: recupera vida e ganha barreira
    💥 Técnica      custa 3 Foco: golpe especial da sua classe
    🏁 Encerrar     termina a run

Curar deixou de ser grátis: você precisa ganhar Foco batendo ou guardando.
A criatura mostra o que vai fazer ("👁️ Intenção"): marcar, distorcer o
tempo, emboscar... Ler a intenção e escolher a ação certa é o jogo.

MERCADO E MOCHILA
-----------------
- O mercado vende SOMENTE itens passivos de build (ataque, defesa, vida,
  barreira inicial, crítico e foco).
- Itens comprados são equipados automaticamente quando a próxima run
  começa e duram aquela run. Há um limite de cópias equipadas por item
  (o excedente continua na mochila para as runs seguintes).
- Abysmus ganho nas runs financia a build da próxima run.

COMO EXPANDIR (resumo)
----------------------
1) NOVA CLASSE      -> registrar_classe("chave", ClassSpec(..., tecnica=Tecnica(...)))
2) NOVA RELÍQUIA    -> subclasse de Efeito + @registrar_reliquia
3) NOVA CRIATURA    -> registrar_criatura(EnemySpec(...))
4) NOVA HABILIDADE  -> subclasse de HabilidadeInimiga + @registrar_habilidade
5) NOVO ITEM        -> registrar_item("chave", ItemSpec(...))

As seções 1 a 4 é onde você adiciona conteúdo. O motor de combate
(seção 5 em diante) não precisa ser alterado.

Instalação:
    pip install -U discord.py python-dotenv
"""

from __future__ import annotations

import asyncio
import logging
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import discord
from discord.ext import commands


# ============================================================
# 0. CONFIGURAÇÕES GERAIS E LOG
# ============================================================

log = logging.getLogger("shaggy.ruptura")

# A cada quantos níveis da run uma relíquia é concedida.
RELIQUIA_A_CADA = 3

# Chance base de crítico (em %) e multiplicador de dano do crítico.
CHANCE_CRITICO_BASE = 8
MULTIPLICADOR_CRITICO = 1.8

# Quantas linhas do log de combate aparecem no embed.
LINHAS_LOG_VISIVEIS = 8

# Segundos de inatividade até a run ser encerrada automaticamente.
TIMEOUT_RUN_SEGUNDOS = 600

# Foco: recurso de combate.
FOCO_MAX = 5
FOCO_INICIAL = 1
FOCO_POR_COMBATE = 1      # ganho automático ao começar cada combate
CUSTO_CONCENTRAR = 2
CUSTO_TECNICA = 3

# Balanceamento global. Ajuste estes valores sem reescrever o motor.
CHANCE_DEUS = 0.015              # 1,5% em encontros comuns
CHANCE_MOEDA_NORMAL = 0.25
CHANCE_MOEDA_MINICHEFE = 0.60
CHANCE_MOEDA_CHEFE = 0.90
CHANCE_MOEDA_DEUS = 1.00


def configurar_log_terminal() -> None:
    """Garante que os logs do jogo apareçam no terminal."""
    if log.handlers or logging.getLogger().handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(handler)
    log.setLevel(logging.INFO)


# ============================================================
# 1. MOTOR DE EFEITOS (BASE DE PASSIVAS E RELÍQUIAS)
# ============================================================

@dataclass
class Ataque:
    """Contexto de um ataque do jogador, passado pelos hooks de dano."""
    dano: int
    critico: bool
    chance_critico: int


class Efeito:
    """Classe base de qualquer efeito (passiva de classe ou relíquia)."""

    nome: str = "Efeito"
    descricao: str = ""

    def ao_obter(self, run: "RunState") -> None:
        """Chamado uma vez quando a relíquia é obtida / a run começa."""

    def ao_iniciar_combate(
        self, run: "RunState", inimigo: "EnemyState"
    ) -> None:
        """Chamado sempre que uma nova criatura aparece."""

    def bonus_critico(self, run: "RunState") -> int:
        """Pontos percentuais somados à chance de crítico."""
        return 0

    def modificar_dano_causado(
        self, run: "RunState", ataque: Ataque
    ) -> int:
        """Recebe o ataque e devolve o dano (já alterado) a ser causado."""
        return ataque.dano

    def ao_causar_dano(self, run: "RunState", dano_real: int) -> None:
        """Chamado depois que o dano foi aplicado ao inimigo."""

    def modificar_dano_recebido(self, run: "RunState", dano: int) -> int:
        """Recebe o dano que o jogador vai sofrer e devolve o novo valor."""
        return dano

    def ao_inimigo_derrotado(
        self, run: "RunState", inimigo: "EnemyState"
    ) -> None:
        """Chamado quando uma criatura é derrotada."""


# ============================================================
# 2. CLASSES, TÉCNICAS, PASSIVAS E CATÁLOGO DA LOJA
# ============================================================

@dataclass(frozen=True)
class Tecnica:
    """Golpe especial de uma classe, gasto com Foco."""
    nome: str
    descricao: str
    acao: Callable[["RunState"], None]
    custo: int = CUSTO_TECNICA


def _tecnica_padrao(run: "RunState") -> None:
    executar_ataque(run, mult=1.5, nunca_erra=True, nome_golpe="Golpe Concentrado")


TECNICA_PADRAO = Tecnica(
    "Golpe Concentrado",
    "Ataque que nunca erra e causa 50% a mais de dano.",
    _tecnica_padrao,
)


@dataclass(frozen=True)
class ClassSpec:
    """Ficha base de uma classe jogável."""
    nome: str
    descricao: str
    vida: int
    ataque: int
    defesa: int
    passiva: Efeito
    tecnica: Optional[Tecnica] = None


CLASSES: dict[str, ClassSpec] = {}


def registrar_classe(chave: str, spec: ClassSpec) -> ClassSpec:
    """Registra uma classe no catálogo."""
    chave = chave.strip().lower()

    if not chave:
        raise ValueError("A chave da classe não pode ser vazia.")

    if chave in CLASSES:
        raise ValueError(f"A classe '{chave}' já está registrada.")

    if spec.tecnica is None:
        spec = replace(spec, tecnica=TECNICA_PADRAO)

    CLASSES[chave] = spec
    return spec


# ============================================================
# ITENS PASSIVOS: CATÁLOGO USADO PELA LOJA E PELO INVENTÁRIO
# Todos são equipados automaticamente ao iniciar a run.
# ============================================================

EFEITOS_ITEM = {"ataque", "defesa", "vida", "barreira", "critico", "foco"}


@dataclass(frozen=True)
class ItemSpec:
    """Definição de um item passivo de build."""
    nome: str
    descricao: str
    efeito: str
    poder: int
    preco: int = 0
    limite: int = 3   # máximo de cópias equipadas por run


ITENS: dict[str, ItemSpec] = {}


def registrar_item(chave: str, spec: ItemSpec) -> ItemSpec:
    """Registra um item no catálogo expansível."""
    chave = chave.strip().lower()

    if not chave:
        raise ValueError("A chave do item não pode ser vazia.")

    if spec.efeito not in EFEITOS_ITEM:
        raise ValueError(f"Efeito de item não reconhecido: {spec.efeito}")

    if spec.preco < 0:
        raise ValueError("O preço do item não pode ser negativo.")

    if spec.limite < 1:
        raise ValueError("O limite de cópias precisa ser pelo menos 1.")

    if chave in ITENS:
        raise ValueError(f"O item '{chave}' já está registrado.")

    ITENS[chave] = spec
    return spec


# As chaves "tonico_menor", "selo_barreira" e "fragmento_agressivo" são
# mantidas: quem já as comprou continua com elas, agora como itens passivos.
registrar_item("fragmento_agressivo", ItemSpec(
    nome="Fragmento Agressivo",
    descricao="Ataque +2 durante a run.",
    efeito="ataque", poder=2, preco=15,
))
registrar_item("lamina_rachada", ItemSpec(
    nome="Lâmina Rachada",
    descricao="Ataque +4 durante a run.",
    efeito="ataque", poder=4, preco=32,
))
registrar_item("placa_de_fuligem", ItemSpec(
    nome="Placa de Fuligem",
    descricao="Defesa +1 durante a run.",
    efeito="defesa", poder=1, preco=14,
))
registrar_item("couraca_de_cobre", ItemSpec(
    nome="Couraça de Cobre",
    descricao="Defesa +2 durante a run.",
    efeito="defesa", poder=2, preco=28,
))
registrar_item("tonico_menor", ItemSpec(
    nome="Tônico Menor",
    descricao="Vida máxima +10 durante a run.",
    efeito="vida", poder=10, preco=10,
))
registrar_item("coracao_de_ferro", ItemSpec(
    nome="Coração de Ferro",
    descricao="Vida máxima +25 durante a run.",
    efeito="vida", poder=25, preco=24,
))
registrar_item("selo_barreira", ItemSpec(
    nome="Selo de Barreira",
    descricao="Começa cada combate com pelo menos 8 de barreira.",
    efeito="barreira", poder=8, preco=18,
))
registrar_item("lente_rachada", ItemSpec(
    nome="Lente Rachada",
    descricao="Chance de crítico +5 pontos percentuais.",
    efeito="critico", poder=5, preco=20,
))
registrar_item("pedra_de_foco", ItemSpec(
    nome="Pedra de Foco",
    descricao="+1 Foco no início de cada combate.",
    efeito="foco", poder=1, preco=26, limite=2,
))


# ============================================================
# PASSIVAS DAS CLASSES
# ============================================================

class PassivaArcano(Efeito):
    """A cada terceiro turno, causa dano arcano adicional."""

    nome = "Magia do Véu"
    descricao = "A cada 3º turno, causa dano arcano extra."

    def modificar_dano_causado(self, run, ataque):
        if run.turno > 0 and run.turno % 3 == 0:
            extra = random.randint(5, 10) + run.nivel
            run.log.append(
                f"🔮 Magia do Véu acrescenta {extra} de dano arcano."
            )
            return ataque.dano + extra

        return ataque.dano


class PassivaBarreira(Efeito):
    """Começa cada combate com pelo menos 10 de barreira."""

    nome = "Luz da Luminária"
    descricao = "Começa cada combate com pelo menos 10 de barreira."

    def ao_iniciar_combate(self, run, inimigo):
        if run.barreira < 10:
            run.barreira = 10
            run.log.append(
                "🛡️ A Luminária ergue uma barreira de 10 pontos."
            )


class PassivaCritico(Efeito):
    """Aumenta a chance de crítico e fortalece golpes críticos."""

    nome = "Fenda do Instante"
    descricao = "+20% de chance de crítico; críticos somam metade da defesa inimiga."

    def bonus_critico(self, run):
        return 20

    def modificar_dano_causado(self, run, ataque):
        inimigo = run.inimigo

        if ataque.critico and inimigo is not None:
            bonus = inimigo.defesa // 2
            run.log.append(
                f"⏳ Fenda do Instante acrescenta {bonus} de dano."
            )
            return ataque.dano + bonus

        return ataque.dano


class PassivaVampiro(Efeito):
    """Rouba vida ao causar dano; fica mais resistente com pouca vida."""

    nome = "Fome Carmesim"
    descricao = (
        "Recupera 25% do dano causado, ou 40% com vida baixa. "
        "Com vida baixa, sofre 15% menos dano."
    )

    def vida_baixa(self, run):
        return run.vida <= run.vida_maxima * 0.30

    def ao_causar_dano(self, run, dano_real):
        if dano_real <= 0:
            return

        percentual = 0.40 if self.vida_baixa(run) else 0.25
        cura = run.curar(max(1, int(dano_real * percentual)))

        if cura > 0:
            run.log.append(
                f"🩸 Fome Carmesim recupera {cura} de vida."
            )

    def modificar_dano_recebido(self, run, dano):
        if dano > 0 and self.vida_baixa(run):
            return max(1, int(dano * 0.85))

        return dano


class PassivaBastiao(Efeito):
    """Reduz o dano recebido e começa o combate protegido."""

    nome = "Muralha Ancestral"
    descricao = "Começa com 15 de barreira e reduz o dano recebido em 2."

    def ao_iniciar_combate(self, run, inimigo):
        if run.barreira < 15:
            run.barreira = 15
            run.log.append(
                "🪨 Muralha Ancestral concede 15 de barreira."
            )

    def modificar_dano_recebido(self, run, dano):
        return max(0, dano - 2)


class PassivaCeifador(Efeito):
    """Causa mais dano contra inimigos feridos."""

    nome = "Sentença Carmesim"
    descricao = "Causa 25% mais dano contra inimigos com 50% de vida ou menos."

    def modificar_dano_causado(self, run, ataque):
        inimigo = run.inimigo

        if inimigo is None:
            return ataque.dano

        if inimigo.vida <= inimigo.vida_maxima * 0.50:
            bonus = max(1, int(ataque.dano * 0.25))
            run.log.append(
                f"☠️ Sentença Carmesim acrescenta {bonus} de dano."
            )
            return ataque.dano + bonus

        return ataque.dano


class PassivaAlquimista(Efeito):
    """Acumula poder ao atingir o inimigo."""

    nome = "Reação em Cadeia"
    descricao = "Cada acerto acumula 2 de dano extra, até 5 cargas."

    def modificar_dano_causado(self, run, ataque):
        bonus = run.alquimista_cargas * 2

        if bonus:
            run.log.append(
                f"⚗️ Reação em Cadeia acrescenta {bonus} de dano."
            )

        return ataque.dano + bonus

    def ao_causar_dano(self, run, dano_real):
        if dano_real <= 0:
            return

        run.alquimista_cargas = min(5, run.alquimista_cargas + 1)

        run.log.append(
            f"⚗️ Reação em Cadeia: {run.alquimista_cargas}/5 cargas."
        )

    def ao_inimigo_derrotado(self, run, inimigo):
        run.alquimista_cargas = 0


class PassivaAndarilho(Efeito):
    """Tem chance de evitar completamente um ataque."""

    nome = "Passo Entre Fendas"
    descricao = "Tem 20% de chance de esquivar completamente de um ataque."

    def modificar_dano_recebido(self, run, dano):
        if dano > 0 and random.random() < 0.20:
            run.log.append(
                "🌀 Passo Entre Fendas: você esquivou do ataque!"
            )
            return 0

        return dano


class PassivaSilvestre(Efeito):
    """Recupera vida ao iniciar cada combate."""

    nome = "Seiva Profana"
    descricao = "Recupera 8% da vida máxima no início de cada combate."

    def ao_iniciar_combate(self, run, inimigo):
        cura_potencial = max(1, int(run.vida_maxima * 0.08))
        cura = run.curar(cura_potencial)

        if cura > 0:
            run.log.append(
                f"🌿 Seiva Profana recupera {cura} de vida."
            )


class PassivaEngenhoqueiro(Efeito):
    """A cada terceiro turno, ativa uma descarga mecânica."""

    nome = "Sobrecarga Mecânica"
    descricao = "A cada 3º turno, acrescenta 8 + nível ao dano."

    def modificar_dano_causado(self, run, ataque):
        if run.turno > 0 and run.turno % 3 == 0:
            extra = 8 + run.nivel
            run.log.append(
                f"⚙️ Sobrecarga Mecânica acrescenta {extra} de dano."
            )
            return ataque.dano + extra

        return ataque.dano


# ============================================================
# TÉCNICAS DAS CLASSES (custam Foco; usam só mecânicas existentes)
# ============================================================

def tec_mago(run):
    executar_ataque(run, mult=1.5, nunca_erra=True, ignora_defesa=True,
                    nome_golpe="Rajada do Véu")


def tec_guardiao(run):
    run.barreira += 20
    run.guarda = True
    run.log.append(
        "🛡️ Muralha de Luz: +20 de barreira e guarda erguida "
        "(o próximo golpe causa metade)."
    )


def tec_errante(run):
    executar_ataque(run, mult=1.2, forcar_critico=True, nunca_erra=True,
                    nome_golpe="Instante Fendido")


def tec_vampiro(run):
    executar_ataque(run, mult=1.3, nunca_erra=True,
                    nome_golpe="Mordida Carmesim")


def tec_bastiao(run):
    executar_ataque(run, nunca_erra=True, bonus_fixo=run.defesa * 2,
                    nome_golpe="Quebra-Baluarte")


def tec_ceifador(run):
    inimigo = run.inimigo
    ferido = inimigo is not None and inimigo.vida <= inimigo.vida_maxima * 0.50
    executar_ataque(run, mult=2.0 if ferido else 1.3, nunca_erra=True,
                    nome_golpe="Execução")


def tec_alquimista(run):
    cargas = run.alquimista_cargas
    run.alquimista_cargas = 0
    executar_ataque(run, mult=1.2, nunca_erra=True,
                    bonus_fixo=8 + cargas * 6, nome_golpe="Detonação")
    inimigo = run.inimigo
    if inimigo is not None and inimigo.vida > 0:
        inimigo.queimadura = max(inimigo.queimadura, 2)
        run.log.append("🔥 A detonação deixa o inimigo em chamas por 2 turnos.")


def tec_andarilho(run):
    run.esquiva = True
    run.log.append("🌀 Dança entre Fendas: o próximo golpe inimigo vai atravessar você.")
    executar_ataque(run, mult=1.1, nome_golpe="Dança entre Fendas")


def tec_silvestre(run):
    executar_ataque(run, mult=1.1, nunca_erra=True,
                    nome_golpe="Florescer Profano")
    cura = run.curar(max(1, int(run.vida_maxima * 0.12)))
    if cura > 0:
        run.log.append(f"🌿 A floresta devolve {cura} de vida a você.")


def tec_engenhoqueiro(run):
    executar_ataque(run, nunca_erra=True, bonus_fixo=10 + run.nivel,
                    nome_golpe="Descarga Instável")


# ============================================================
# REGISTRO DAS CLASSES
# ============================================================

registrar_classe("mago", ClassSpec(
    nome="Mago do Véu",
    descricao="Manipula as falhas da realidade com magia arcana.",
    vida=85, ataque=15, defesa=3,
    passiva=PassivaArcano(),
    tecnica=Tecnica("Rajada do Véu",
                    "Golpe arcano que nunca erra e ignora a defesa inimiga.",
                    tec_mago),
))

registrar_classe("guardiao", ClassSpec(
    nome="Guardião da Luminária",
    descricao="Resiste aos ataques e ergue uma barreira protetora.",
    vida=115, ataque=12, defesa=6,
    passiva=PassivaBarreira(),
    tecnica=Tecnica("Muralha de Luz",
                    "+20 de barreira e guarda erguida para o próximo golpe.",
                    tec_guardiao),
))

registrar_classe("errante", ClassSpec(
    nome="Errante Temporal",
    descricao="Um combatente imprevisível, especialista em críticos.",
    vida=95, ataque=14, defesa=4,
    passiva=PassivaCritico(),
    tecnica=Tecnica("Instante Fendido",
                    "Ataque que nunca erra e é sempre crítico.",
                    tec_errante),
))

registrar_classe("vampiro", ClassSpec(
    nome="Vampiro da Noite Carmesim",
    descricao="Drena a vida dos inimigos e resiste quando está ferido.",
    vida=120, ataque=10, defesa=8,
    passiva=PassivaVampiro(),
    tecnica=Tecnica("Mordida Carmesim",
                    "Golpe que nunca erra (+30% de dano); a Fome Carmesim cura.",
                    tec_vampiro),
))

registrar_classe("bastiao", ClassSpec(
    nome="Bastião de Drak'vuh",
    descricao="Uma fortaleza viva que suporta golpes devastadores.",
    vida=140, ataque=8, defesa=10,
    passiva=PassivaBastiao(),
    tecnica=Tecnica("Quebra-Baluarte",
                    "Golpe certeiro que converte sua defesa em dano (2× defesa).",
                    tec_bastiao),
))

registrar_classe("ceifador", ClassSpec(
    nome="Ceifador Carmesim",
    descricao="Executa inimigos feridos com ataques brutais.",
    vida=100, ataque=16, defesa=4,
    passiva=PassivaCeifador(),
    tecnica=Tecnica("Execução",
                    "Nunca erra; causa o dobro de dano em inimigos com 50% de vida ou menos.",
                    tec_ceifador),
))

registrar_classe("alquimista", ClassSpec(
    nome="Alquimista do Abismo",
    descricao="Acumula energia destrutiva a cada golpe bem-sucedido.",
    vida=95, ataque=12, defesa=5,
    passiva=PassivaAlquimista(),
    tecnica=Tecnica("Detonação",
                    "Consome as cargas: +6 de dano por carga e incendeia o inimigo.",
                    tec_alquimista),
))

registrar_classe("andarilho", ClassSpec(
    nome="Andarilho da Fenda",
    descricao="Usa rupturas temporais para evitar ataques.",
    vida=85, ataque=16, defesa=2,
    passiva=PassivaAndarilho(),
    tecnica=Tecnica("Dança entre Fendas",
                    "Ataca e garante a esquiva do próximo golpe inimigo.",
                    tec_andarilho),
))

registrar_classe("silvestre", ClassSpec(
    nome="Silvestre Corrompido",
    descricao="Extrai vitalidade da floresta para sobreviver.",
    vida=105, ataque=12, defesa=6,
    passiva=PassivaSilvestre(),
    tecnica=Tecnica("Florescer Profano",
                    "Golpe certeiro que ainda recupera 12% da vida máxima.",
                    tec_silvestre),
))

registrar_classe("engenhoqueiro", ClassSpec(
    nome="Engenhoqueiro de Da'kor",
    descricao="Constrói armas instáveis que liberam descargas periódicas.",
    vida=95, ataque=14, defesa=4,
    passiva=PassivaEngenhoqueiro(),
    tecnica=Tecnica("Descarga Instável",
                    "Golpe certeiro com +10 de dano e +1 por nível da run.",
                    tec_engenhoqueiro),
))


# ============================================================
# 3. RELÍQUIAS (ITENS)
# Nenhuma relíquia concede roubo de vida (exclusivo do Vampiro).
# ============================================================

RELIQUIAS: list[Efeito] = []


def registrar_reliquia(cls: type[Efeito]) -> type[Efeito]:
    """Decorator: instancia a relíquia e a adiciona ao catálogo."""
    RELIQUIAS.append(cls())
    return cls


@registrar_reliquia
class DenteDeCristal(Efeito):
    nome = "Dente de Cristal"
    descricao = "Criaturas já começam o combate com 10% a menos de vida."

    def ao_iniciar_combate(self, run, inimigo):
        corte = max(1, int(inimigo.vida_maxima * 0.10))
        inimigo.vida = max(1, inimigo.vida - corte)


@registrar_reliquia
class LenteInstantePartido(Efeito):
    nome = "Lente do Instante Partido"
    descricao = "Aumenta a chance de crítico em 12 pontos percentuais."

    def bonus_critico(self, run):
        return 12


@registrar_reliquia
class BrasaDeMalachais(Efeito):
    nome = "Brasa de Malachais"
    descricao = "Seus ataques queimam o inimigo por 3 turnos."

    def ao_causar_dano(self, run, dano_real):
        if run.inimigo is not None and dano_real > 0:
            run.inimigo.queimadura = max(run.inimigo.queimadura, 3)


@registrar_reliquia
class CasuloDoVeu(Efeito):
    nome = "Casulo do Véu"
    descricao = "Concede 20 pontos de barreira ao ser obtido."

    def ao_obter(self, run):
        run.barreira += 20


@registrar_reliquia
class FragmentoDeDrakvuh(Efeito):
    nome = "Fragmento de Drak'vuh"
    descricao = "Aumenta permanentemente o ataque em 4."

    def ao_obter(self, run):
        run.ataque += 4


@registrar_reliquia
class CascaAncestral(Efeito):
    nome = "Casca Ancestral"
    descricao = "Aumenta a defesa em 2 e a vida máxima em 10."

    def ao_obter(self, run):
        run.defesa += 2
        run.vida_maxima += 10
        run.curar(10)


@registrar_reliquia
class GraoDeMerjin(Efeito):
    nome = "Grão de Merjin"
    descricao = "A cada 4 turnos, causa dano temporal adicional."

    def modificar_dano_causado(self, run, ataque):
        if run.turno > 0 and run.turno % 4 == 0:
            extra = 10 + run.nivel
            run.log.append(
                f"⏳ O Grão de Merjin acrescenta {extra} de dano temporal."
            )
            return ataque.dano + extra
        return ataque.dano


@registrar_reliquia
class OlhoDaMaoInvisivel(Efeito):
    nome = "Olho da Mão Invisível"
    descricao = "Reduz em 15% o dano recebido."

    def modificar_dano_recebido(self, run, dano):
        if dano <= 0:   # esquiva anterior não pode ser desfeita
            return dano
        return max(1, int(dano * 0.85))


@registrar_reliquia
class CoracaoDeFuligem(Efeito):
    nome = "Coração de Fuligem"
    descricao = "Aumenta a vida máxima em 20 e recupera 20 de vida."

    def ao_obter(self, run):
        run.vida_maxima += 20
        run.curar(20)


@registrar_reliquia
class CinzasDeDakor(Efeito):
    nome = "Cinzas de Da'kor"
    descricao = "Começa cada combate com pelo menos 8 de barreira."

    MINIMO = 8

    def ao_iniciar_combate(self, run, inimigo):
        if run.barreira < self.MINIMO:
            run.barreira = self.MINIMO
            run.log.append(f"🛡️ As cinzas formam {self.MINIMO} de barreira.")


@registrar_reliquia
class LanternaRubra(Efeito):
    nome = "Lanterna Rubra"
    descricao = "Ao derrotar uma criatura, ganha 8 pontos de barreira."

    def ao_inimigo_derrotado(self, run, inimigo):
        run.barreira += 8
        run.log.append("🏮 A Lanterna Rubra concede 8 de barreira.")


@registrar_reliquia
class PavioEterno(Efeito):
    nome = "Pavio Eterno"
    descricao = "Críticos incendeiam o inimigo por 4 turnos."

    def ao_causar_dano(self, run, dano_real):
        if run.inimigo is not None and run.ultimo_critico:
            run.inimigo.queimadura = max(run.inimigo.queimadura, 4)


# ============================================================
# 4. CRIATURAS E HABILIDADES DE CRIATURAS
# ============================================================

@dataclass(frozen=True)
class EnemySpec:
    """Ficha base de uma criatura (valores no nível mínimo dela)."""
    nome: str
    era: str
    nivel_minimo: int
    vida: int
    ataque: int
    defesa: int
    xp: int
    abysmus: int
    habilidade: str   # chave em HABILIDADES
    descricao: str
    categoria: str = "normal"  # normal, mini_chefe, chefe ou deus


class HabilidadeInimiga:
    """Classe base das habilidades de criaturas. Hooks opcionais."""

    nome: str = "Nenhuma"
    descricao: str = ""

    def ao_iniciar_combate(self, run, inimigo) -> None:
        """Chamado quando a criatura entra em combate."""

    def ao_turno(self, run, inimigo) -> bool:
        """Retorne True se a habilidade CONSUMIU o turno."""
        return False

    def modificar_ataque(self, run, inimigo, dano: int) -> int:
        return dano

    def penetracao_defesa(self, run, inimigo) -> int:
        return 0

    def reduzir_dano_recebido(self, run, inimigo, dano: int) -> int:
        return dano

    def apos_golpe(self, run, inimigo, vida_perdida: int) -> None:
        """Chamado depois que o ataque da criatura atingiu o jogador."""

    def intencao(self, run, inimigo) -> str:
        """Texto curto do que a criatura fará no PRÓXIMO turno dela."""
        return "Golpe direto."


HABILIDADES: dict[str, HabilidadeInimiga] = {}
_SEM_HABILIDADE = HabilidadeInimiga()


def registrar_habilidade(chave: str):
    """Decorator: registra uma habilidade de criatura com a chave dada."""
    def decorador(cls: type[HabilidadeInimiga]):
        HABILIDADES[chave] = cls()
        return cls
    return decorador


@registrar_habilidade("corroer")
class Corroer(HabilidadeInimiga):
    nome = "Corroer"
    descricao = "Ignora 2 de defesa e causa +2 de dano."

    def penetracao_defesa(self, run, inimigo):
        return 2

    def modificar_ataque(self, run, inimigo, dano):
        run.log.append("☠️ A corrosão enfraquece sua defesa neste ataque.")
        return dano + 2

    def intencao(self, run, inimigo):
        return "Golpe corrosivo: ignora 2 de defesa. Barreira e Guarda funcionam bem."


@registrar_habilidade("emboscada")
class Emboscada(HabilidadeInimiga):
    nome = "Emboscada"
    descricao = "O primeiro ataque do combate causa +5 de dano."

    def modificar_ataque(self, run, inimigo, dano):
        if inimigo.turnos == 1:
            run.log.append("🌫️ O inimigo ataca de dentro da névoa!")
            return dano + 5
        return dano

    def intencao(self, run, inimigo):
        if inimigo.turnos == 0:
            return "Emboscada: o primeiro golpe causa +5. Guardar corta pela metade."
        return "Golpe direto."


@registrar_habilidade("regenerar")
class Regenerar(HabilidadeInimiga):
    nome = "Regenerar"
    descricao = "Recupera 5 de vida no início de cada turno."

    def ao_turno(self, run, inimigo):
        cura = min(5, inimigo.vida_maxima - inimigo.vida)
        if cura > 0:
            inimigo.vida += cura
            run.log.append(f"{inimigo.spec.nome} regenera {cura} de vida.")
        return False

    def intencao(self, run, inimigo):
        return "Vai regenerar 5 de vida antes de atacar. Use Técnicas para dar dano de uma vez."


@registrar_habilidade("blindagem")
class Blindagem(HabilidadeInimiga):
    nome = "Blindagem"
    descricao = "Reduz em 2 o dano recebido de cada golpe."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        return max(1, dano - 2)

    def intencao(self, run, inimigo):
        return "Golpe direto. Golpes fracos rendem pouco: prefira Técnicas e críticos."


@registrar_habilidade("marcar")
class Marcar(HabilidadeInimiga):
    nome = "Marcar"
    descricao = "Gasta um turno marcando você; o próximo golpe causa +5."

    def ao_turno(self, run, inimigo):
        if not run.marcado:
            run.marcado = True
            run.log.append(
                f"{inimigo.spec.nome} marca você. "
                "O próximo golpe será mais forte."
            )
            return True
        return False

    def modificar_ataque(self, run, inimigo, dano):
        if run.marcado:
            run.marcado = False
            run.log.append("🎯 O ataque marcado causa dano adicional.")
            return dano + 5
        return dano

    def intencao(self, run, inimigo):
        if not run.marcado:
            return "Vai gastar o turno marcando você. Ótimo momento para Concentrar ou usar Técnica."
        return "Golpe marcado: +5 de dano! Guardar ou barreira valem muito agora."


@registrar_habilidade("sangramento")
class Sangramento(HabilidadeInimiga):
    nome = "Sangramento"
    descricao = "Golpes que ferem deixam você sangrando por 2 turnos."

    def apos_golpe(self, run, inimigo, vida_perdida):
        if vida_perdida > 0:
            run.sangramento = max(run.sangramento, 2)

    def intencao(self, run, inimigo):
        return "Golpe que sangra se ferir você. Barreira e Guarda evitam o sangramento."


@registrar_habilidade("drenar")
class Drenar(HabilidadeInimiga):
    nome = "Drenar"
    descricao = "Causa +3 de dano e recupera 4 de vida ao ferir você."

    def modificar_ataque(self, run, inimigo, dano):
        return dano + 3

    def apos_golpe(self, run, inimigo, vida_perdida):
        if vida_perdida <= 0:
            return
        cura = min(4, inimigo.vida_maxima - inimigo.vida)
        if cura > 0:
            inimigo.vida += cura
            run.log.append(
                f"O {inimigo.spec.nome} drena vigor e recupera {cura} de vida."
            )

    def intencao(self, run, inimigo):
        return "Golpe +3 que cura a criatura se ferir você. Barreira nega a cura."


@registrar_habilidade("salto_temporal")
class SaltoTemporal(HabilidadeInimiga):
    nome = "Salto Temporal"
    descricao = "A cada 3 turnos, interrompe seu próximo ataque."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 3 == 0:
            run.ataque_bloqueado = True
            run.log.append(
                f"{inimigo.spec.nome} distorce o tempo e "
                "interrompe seu próximo ataque."
            )
            return True
        return False

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai distorcer o tempo: seu PRÓXIMO ataque falha. Use Concentrar agora."
        restantes = ((proximo + 2) // 3) * 3 - inimigo.turnos
        return f"Golpe direto. Distorção do tempo em {restantes} turno(s)."


@registrar_habilidade("maldicao")
class Maldicao(HabilidadeInimiga):
    nome = "Maldição"
    descricao = "Causa +5 de dano e deixa queimadura temporal por 2 turnos se ferir você."

    def modificar_ataque(self, run, inimigo, dano):
        return dano + 5

    def apos_golpe(self, run, inimigo, vida_perdida):
        if vida_perdida <= 0:
            return
        run.queimadura = max(run.queimadura, 2)
        run.log.append("A maldição deixa uma queimadura temporal.")

    def intencao(self, run, inimigo):
        return "Golpe +5 que queima se ferir você. Barreira e Guarda anulam a maldição."


CRIATURAS: list[EnemySpec] = []


def registrar_criatura(spec: EnemySpec) -> EnemySpec:
    """Adiciona uma criatura ao catálogo."""
    CRIATURAS.append(spec)
    return spec


# eras: Da'kor, Era a Vapor e Futuro Distorcido.
registrar_criatura(EnemySpec(
    "Lodo Faminto", "Da'kor", 1, 32, 7, 1, 12, 5, "corroer",
    "Uma massa viva que corrói a proteção de suas vítimas.",
))
registrar_criatura(EnemySpec(
    "Corvo de Névoa", "Da'kor", 1, 29, 9, 0, 14, 6, "emboscada",
    "Ataca de dentro da névoa violeta.",
))
registrar_criatura(EnemySpec(
    "Silvestre Desfigurado", "Da'kor", 2, 48, 11, 3, 22, 9, "regenerar",
    "A floresta recompõe sua carne deformada.",
))
registrar_criatura(EnemySpec(
    "Autômato de Fuligem", "Era a Vapor", 3, 62, 12, 5, 28, 12, "blindagem",
    "Uma máquina de guerra alimentada por vapor negro.",
))
registrar_criatura(EnemySpec(
    "Caçador de Cobre", "Era a Vapor", 4, 54, 16, 2, 31, 14, "marcar",
    "Marca sua presa antes de disparar.",
))
registrar_criatura(EnemySpec(
    "Cão de Engrenagens", "Era a Vapor", 5, 70, 15, 4, 36, 16,
    "sangramento",
    "Suas mandíbulas deixam feridas mecânicas.",
))
registrar_criatura(EnemySpec(
    "Eco de um Futuro Morto", "Futuro Distorcido", 6, 76, 17, 3, 43, 20,
    "drenar",
    "Rouba o vigor de uma possibilidade que ainda não ocorreu.",
))
registrar_criatura(EnemySpec(
    "Anomalia Cronófaga", "Futuro Distorcido", 8, 92, 19, 5, 52, 24,
    "salto_temporal",
    "Devora segundos e rompe o ritmo do combate.",
))
registrar_criatura(EnemySpec(
    "Arauto do Inominável", "Futuro Distorcido", 10, 118, 22, 6, 68, 32,
    "maldicao",
    "Uma silhueta que a realidade não deveria comportar.",
))

# Mini-chefes: a cada 3º encontro (exceto múltiplos de 5).
registrar_criatura(EnemySpec(
    "Carrasco da Névoa", "Da'kor", 3, 58, 10, 2, 42, 3, "emboscada",
    "Uma criatura que caça quem tenta atravessar a névoa sem oferendas.",
    categoria="mini_chefe",
))
registrar_criatura(EnemySpec(
    "Engenheiro de Carne", "Era a Vapor", 6, 78, 12, 3, 58, 4, "regenerar",
    "Remenda a própria carne com peças de autômatos destruídos.",
    categoria="mini_chefe",
))
registrar_criatura(EnemySpec(
    "Cavaleiro do Segundo Perdido", "Futuro Distorcido", 9, 92, 14, 3, 75, 4,
    "salto_temporal",
    "Ataca nos intervalos entre um instante e o próximo.",
    categoria="mini_chefe",
))

# Chefes garantidos nos encontros 5, 10, 15, 20, 25 e a cada cinco depois.
registrar_criatura(EnemySpec(
    "O Faroleiro Sem Rosto", "Da'kor", 5, 105, 13, 3, 100, 5, "marcar",
    "O farol acende por dentro de uma figura que não possui rosto.",
    categoria="chefe",
))
registrar_criatura(EnemySpec(
    "Locomotiva de Fuligem", "Era a Vapor", 10, 145, 15, 4, 145, 6,
    "blindagem",
    "Uma máquina viva que tritura trilhos e memórias.",
    categoria="chefe",
))
registrar_criatura(EnemySpec(
    "A Testemunha Reversa", "Futuro Distorcido", 15, 175, 17, 4, 190, 7,
    "drenar",
    "Ela se lembra de todas as vezes em que você morreu.",
    categoria="chefe",
))
registrar_criatura(EnemySpec(
    "O Santo de Cobre", "Era a Vapor", 20, 205, 18, 5, 230, 8, "corroer",
    "Uma divindade industrial que exige combustível feito de sangue.",
    categoria="chefe",
))
registrar_criatura(EnemySpec(
    "A Boca Entre os Mundos", "Futuro Distorcido", 25, 245, 20, 5, 280, 9,
    "maldicao",
    "Uma abertura que aprendeu a falar com vozes de pessoas inexistentes.",
    categoria="chefe",
))

# Deuses: extremamente raros; só substituem encontros comuns.
registrar_criatura(EnemySpec(
    "Malachais, Reflexo Faminto", "Além da Névoa", 1, 260, 19, 5, 350, 12,
    "maldicao",
    "Um reflexo incompleto de algo que jamais deveria despertar.",
    categoria="deus",
))
registrar_criatura(EnemySpec(
    "O Inominável em Silêncio", "Além da Névoa", 1, 320, 22, 6, 500, 15,
    "salto_temporal",
    "A ausência de um nome abre uma ferida na realidade.",
    categoria="deus",
))


def validar_catalogos() -> None:
    """Confere os catálogos ao carregar o cog e avisa sobre erros."""
    for criatura in CRIATURAS:
        if criatura.habilidade not in HABILIDADES:
            log.warning(
                "Criatura '%s' usa habilidade inexistente '%s'.",
                criatura.nome, criatura.habilidade,
            )

    for chave, classe in CLASSES.items():
        if classe.tecnica is None or not callable(classe.tecnica.acao):
            log.warning("Classe '%s' está sem técnica válida.", chave)

    log.info(
        "Catálogos carregados: %d classes, %d relíquias, "
        "%d criaturas, %d habilidades, %d itens.",
        len(CLASSES), len(RELIQUIAS), len(CRIATURAS), len(HABILIDADES),
        len(ITENS),
    )


# ============================================================
# 5. ESTADO DA RUN
# ============================================================

@dataclass
class EnemyState:
    """Criatura em combate (cópia escalada da EnemySpec)."""
    spec: EnemySpec
    nivel: int
    vida: int
    vida_maxima: int
    ataque: int
    defesa: int
    queimadura: int = 0
    turnos: int = 0

    @property
    def habilidade(self) -> HabilidadeInimiga:
        return HABILIDADES.get(self.spec.habilidade, _SEM_HABILIDADE)


@dataclass
class RunState:
    """Tudo que pertence a uma run em andamento, isolada por jogador."""
    user_id: int
    guild_id: int
    user_nome: str
    classe: ClassSpec

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:6])
    inicio: float = field(default_factory=time.monotonic)

    # Progresso
    nivel: int = 1
    xp: int = 0
    abysmus: int = 0
    abates: int = 0

    # Atributos do jogador
    vida: int = 0
    vida_maxima: int = 0
    ataque: int = 0
    defesa: int = 0
    barreira: int = 0

    # Recurso de combate
    foco: int = FOCO_INICIAL

    # Bônus vindos de itens passivos equipados
    barreira_inicial: int = 0
    bonus_critico_itens: int = 0
    foco_por_combate: int = 0

    # Estado de combate
    turno: int = 0
    queimadura: int = 0
    sangramento: int = 0
    marcado: bool = False
    ataque_bloqueado: bool = False
    ultimo_critico: bool = False
    guarda: bool = False
    esquiva: bool = False
    alquimista_cargas: int = 0

    reliquias: list[Efeito] = field(default_factory=list)
    equipados: list[str] = field(default_factory=list)  # itens passivos
    inimigo: Optional[EnemyState] = None

    finalizada: bool = False
    log: list[str] = field(default_factory=list)
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def efeitos(self) -> list[Efeito]:
        """Passiva da classe + todas as relíquias, na ordem de aplicação."""
        return [self.classe.passiva, *self.reliquias]

    def curar(self, quantidade: int) -> int:
        """Cura o jogador sem passar da vida máxima. Retorna cura real."""
        antes = self.vida
        self.vida = min(self.vida_maxima, self.vida + max(0, quantidade))
        return self.vida - antes

    def ganhar_foco(self, quantidade: int) -> int:
        """Soma Foco até o máximo. Retorna o ganho real."""
        antes = self.foco
        self.foco = max(0, min(FOCO_MAX, self.foco + quantidade))
        return self.foco - antes

    def evento(self, mensagem: str) -> None:
        """Escreve um evento da run no terminal do bot."""
        log.info("[run %s | %s] %s", self.run_id, self.user_nome, mensagem)


def usar_item(run: RunState, chave: str, vezes: int = 1) -> bool:
    """Aplica o efeito PASSIVO de um item registrado (vezes = cópias).

    Não mexe no inventário: quem chama é responsável por consumir o item.
    """
    item = ITENS.get(chave)
    if item is None:
        run.log.append(f"O item '{chave}' não existe no catálogo.")
        return False

    total = item.poder * max(1, vezes)

    if item.efeito == "ataque":
        run.ataque += total
    elif item.efeito == "defesa":
        run.defesa += total
    elif item.efeito == "vida":
        run.vida_maxima += total
        run.curar(total)
    elif item.efeito == "barreira":
        run.barreira_inicial = max(run.barreira_inicial, total)
    elif item.efeito == "critico":
        run.bonus_critico_itens += total
    elif item.efeito == "foco":
        run.foco_por_combate += total
    else:
        return False

    run.evento(f"Item equipado: {item.nome} ({chave}) x{vezes}.")
    return True


# ============================================================
# INVENTÁRIO PERSISTENTE (mesmo banco do XpAndCoins)
# projeto/cogs/RupturaTemporal.py -> projeto/data/shaggy.db
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "shaggy.db"


def preparar_tabela_inventario() -> None:
    """Cria a tabela sem modificar as tabelas de XP/Abysmus existentes."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS ruptura_inventario (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, item_key)
            )
        """)


def listar_inventario(guild_id: int, user_id: int) -> dict[str, int]:
    """Retorna apenas itens com quantidade positiva."""
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        rows = db.execute("""
            SELECT item_key, quantidade FROM ruptura_inventario
            WHERE guild_id = ? AND user_id = ? AND quantidade > 0
        """, (guild_id, user_id)).fetchall()
    return {chave: quantidade for chave, quantidade in rows}


def guardar_item(
    guild_id: int, user_id: int, chave: str, quantidade: int = 1
) -> None:
    """Adiciona itens ao inventário de um membro."""
    if quantidade <= 0:
        raise ValueError("A quantidade precisa ser positiva.")
    with sqlite3.connect(DB_PATH, timeout=10) as db:
        db.execute("""
            INSERT INTO ruptura_inventario (guild_id, user_id, item_key, quantidade)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_key)
            DO UPDATE SET quantidade = quantidade + excluded.quantidade
        """, (guild_id, user_id, chave, quantidade))


def consumir_item(
    guild_id: int, user_id: int, chave: str, quantidade: int = 1
) -> bool:
    """Consome item apenas se houver estoque; a operação é transacional."""
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""
            SELECT quantidade FROM ruptura_inventario
            WHERE guild_id = ? AND user_id = ? AND item_key = ?
        """, (guild_id, user_id, chave)).fetchone()
        if row is None or row[0] < quantidade:
            db.execute("ROLLBACK")
            return False
        restante = row[0] - quantidade
        if restante:
            db.execute("""
                UPDATE ruptura_inventario SET quantidade = ?
                WHERE guild_id = ? AND user_id = ? AND item_key = ?
            """, (restante, guild_id, user_id, chave))
        else:
            db.execute("""
                DELETE FROM ruptura_inventario
                WHERE guild_id = ? AND user_id = ? AND item_key = ?
            """, (guild_id, user_id, chave))
        db.execute("COMMIT")
        return True
    finally:
        db.close()


# ============================================================
# 6. ADAPTADOR XPANDCOINS
# ============================================================

async def award_rewards(
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    xp: int = 0,
    abysmus: int = 0,
    origem: str = "ruptura_temporal",
) -> bool:
    """Integra com XpAndCoins.conceder_recompensas(guild_id, user_id, xp, coins, origem)."""
    if xp <= 0 and abysmus <= 0:
        return True  # nada a gravar

    cog = bot.get_cog("XpAndCoins")
    if cog is None:
        log.error("XpAndCoins não está carregado; recompensa não persistida.")
        return False

    conceder = getattr(cog, "conceder_recompensas", None)
    if not callable(conceder):
        log.error("XpAndCoins não expõe conceder_recompensas().")
        return False

    try:
        await asyncio.to_thread(
            conceder,
            guild_id=guild_id,
            user_id=user_id,
            xp=max(0, int(xp)),
            coins=max(0, int(abysmus)),
            origem=origem,
        )
        log.info(
            "Recompensa persistida | guild=%s user=%s +%s XP +%s Abysmus (%s)",
            guild_id, user_id, xp, abysmus, origem,
        )
        return True
    except Exception:
        log.exception(
            "Falha ao persistir recompensa | guild=%s user=%s",
            guild_id, user_id,
        )
        return False


# ============================================================
# 7. MOTOR DE COMBATE
# ============================================================

def categoria_encontro(nivel: int) -> str:
    """Chefe no 5º, 10º...; mini-chefe no 3º, 6º... (exceto múltiplos de 5);
    deus só pode substituir encontro normal."""
    if nivel > 0 and nivel % 5 == 0:
        return "chefe"
    if nivel > 0 and nivel % 3 == 0:
        return "mini_chefe"
    if random.random() < CHANCE_DEUS:
        return "deus"
    return "normal"


def criar_inimigo(nivel: int) -> EnemyState:
    """Escolhe um inimigo do tipo correto e aplica escala moderada."""
    categoria = categoria_encontro(nivel)
    disponiveis = [c for c in CRIATURAS if c.categoria == categoria]

    if not disponiveis:
        categoria = "normal"
        disponiveis = [c for c in CRIATURAS if c.categoria == "normal"]

    elegiveis = [c for c in disponiveis if c.nivel_minimo <= nivel]
    if elegiveis:
        recentes = [c for c in elegiveis if c.nivel_minimo >= nivel - 6]
        spec = random.choice(recentes or elegiveis)
    else:
        spec = min(disponiveis, key=lambda c: c.nivel_minimo)

    escala = max(0, nivel - spec.nivel_minimo)
    if categoria == "normal":
        vida = spec.vida + escala * 4
        ataque = spec.ataque + escala
        defesa = spec.defesa + escala // 4
    elif categoria in ("mini_chefe", "chefe"):
        vida = spec.vida + escala * 5
        ataque = spec.ataque + escala
        defesa = spec.defesa + escala // 5
    else:  # deus
        vida = spec.vida + escala * 3
        ataque = spec.ataque + escala // 2
        defesa = spec.defesa + escala // 6

    return EnemyState(
        spec=spec, nivel=nivel,
        vida=vida, vida_maxima=vida,
        ataque=ataque, defesa=defesa,
    )


@dataclass(frozen=True)
class EventoSpec:
    """Evento ambiental expansível; não altera os atributos de combate."""
    chave: str
    nome: str
    descricao: str
    chance: float = 0.03
    periodo: str = "sempre"  # sempre, halloween, natal


EVENTOS: dict[str, EventoSpec] = {}


def registrar_evento(evento: EventoSpec) -> EventoSpec:
    if not 0 <= evento.chance <= 1:
        raise ValueError("A chance do evento deve estar entre 0 e 1.")
    EVENTOS[evento.chave] = evento
    return evento


registrar_evento(EventoSpec(
    "lua_sangrenta", "Lua Sangrenta",
    "A lua se abre como uma ferida sobre Da'kor. A névoa fica vermelha.",
    0.035,
))
registrar_evento(EventoSpec(
    "noite_alien", "Noite Alienígena",
    "Luzes desconhecidas atravessam o céu e desaparecem dentro da névoa.",
    0.025,
))
registrar_evento(EventoSpec(
    "halloween", "Vigília de Halloween",
    "Vozes mascaradas ecoam entre as árvores. Só surge entre 20 de outubro e 2 de novembro.",
    0.08, "halloween",
))
registrar_evento(EventoSpec(
    "natal", "Natal em Da'kor",
    "Pequenas luzes surgem na névoa, embora não exista nenhuma casa por perto. Só surge entre 15 de dezembro e 5 de janeiro.",
    0.08, "natal",
))


def evento_disponivel(evento: EventoSpec, hoje: date | None = None) -> bool:
    """Restringe Halloween e Natal às suas janelas sazonais."""
    hoje = hoje or date.today()
    if evento.periodo == "halloween":
        return (hoje.month == 10 and hoje.day >= 20) or (
            hoje.month == 11 and hoje.day <= 2
        )
    if evento.periodo == "natal":
        return (hoje.month == 12 and hoje.day >= 15) or (
            hoje.month == 1 and hoje.day <= 5
        )
    return True


def sortear_evento() -> EventoSpec | None:
    """Sorteia no máximo um evento por encontro."""
    disponiveis = [e for e in EVENTOS.values() if evento_disponivel(e)]
    random.shuffle(disponiveis)
    for evento in disponiveis:
        if random.random() < evento.chance:
            return evento
    return None


def preparar_combate(run: RunState) -> None:
    """Gera a próxima criatura, sorteia evento e dispara os hooks."""
    run.inimigo = criar_inimigo(run.nivel)
    inimigo = run.inimigo

    # Estado de combate zerado: cada luta começa limpa e previsível.
    run.turno = 0
    run.marcado = False
    run.ataque_bloqueado = False
    run.guarda = False
    run.esquiva = False
    run.ultimo_critico = False

    ganho = run.ganhar_foco(FOCO_POR_COMBATE + run.foco_por_combate)
    if ganho > 0:
        run.log.append(f"⚡ +{ganho} Foco ao encarar a criatura.")

    if run.barreira < run.barreira_inicial:
        run.barreira = run.barreira_inicial
        run.log.append(
            f"🛡️ Seus itens formam {run.barreira_inicial} de barreira."
        )

    evento = sortear_evento()
    if evento is not None:
        run.log.append(f"🌌 **EVENTO: {evento.nome}** — {evento.descricao}")
        run.evento(f"Evento temporal: {evento.nome} | {evento.descricao}")

    run.evento(
        f"Combate iniciado contra {inimigo.spec.nome} "
        f"(nível {inimigo.nivel}, vida {inimigo.vida}, "
        f"ataque {inimigo.ataque}, defesa {inimigo.defesa}, "
        f"habilidade {inimigo.spec.habilidade})."
    )

    for efeito in run.efeitos():
        efeito.ao_iniciar_combate(run, inimigo)
    inimigo.habilidade.ao_iniciar_combate(run, inimigo)


def conceder_reliquia(run: RunState) -> Efeito:
    """Sorteia uma relíquia (sem repetir) e aplica o efeito imediato."""
    obtidas = {r.nome for r in run.reliquias}
    disponiveis = [r for r in RELIQUIAS if r.nome not in obtidas]

    relic = random.choice(disponiveis or RELIQUIAS)
    run.reliquias.append(relic)
    relic.ao_obter(run)

    run.log.append(f"✨ **Nova relíquia:** {relic.nome} — {relic.descricao}")
    run.evento(f"Relíquia obtida: {relic.nome}.")
    return relic


def executar_ataque(
    run: RunState,
    mult: float = 1.0,
    forcar_critico: bool = False,
    nunca_erra: bool = False,
    ignora_defesa: bool = False,
    bonus_fixo: int = 0,
    nome_golpe: str | None = None,
) -> int:
    """Resolve ataque (normal ou técnica) com dano variável e efeitos.

    Os parâmetros opcionais existem para as técnicas de classe; o ataque
    básico chama sem nenhum e se comporta exatamente como antes.
    """
    inimigo = run.inimigo
    run.ultimo_critico = False
    if inimigo is None or inimigo.vida <= 0:
        return 0

    ataque_base = max(1, run.ataque)

    if not nunca_erra:
        chance_erro = max(4, min(18, 9 + (inimigo.defesa - ataque_base)))
        if random.randint(1, 100) <= chance_erro:
            run.log.append(
                f"💨 Você errou o ataque (chance de erro: {chance_erro}%)."
            )
            return 0

    reducao = 0 if ignora_defesa else inimigo.defesa // 2
    dano = max(2, ataque_base + random.randint(-2, 5) - reducao)
    dano = int(dano * mult) + bonus_fixo

    chance = CHANCE_CRITICO_BASE + run.bonus_critico_itens + sum(
        efeito.bonus_critico(run) for efeito in run.efeitos()
    )
    chance = max(0, min(60, chance))
    critico = forcar_critico or random.randint(1, 100) <= chance
    run.ultimo_critico = critico
    if critico:
        dano = int(dano * MULTIPLICADOR_CRITICO) + random.randint(1, 3)
        run.log.append(
            "💥 GOLPE CRÍTICO! O golpe atravessa uma falha na realidade."
        )

    ataque = Ataque(dano=dano, critico=critico, chance_critico=chance)
    for efeito in run.efeitos():
        ataque.dano = efeito.modificar_dano_causado(run, ataque)

    dano_final = inimigo.habilidade.reduzir_dano_recebido(
        run, inimigo, max(1, ataque.dano)
    )
    dano_real = min(max(1, dano_final), inimigo.vida)
    inimigo.vida = max(0, inimigo.vida - dano_real)

    prefixo = f"{nome_golpe}: " if nome_golpe else ""
    run.log.append(
        f"⚔️ {prefixo}você causa **{dano_real}** de dano"
        + (" — **CRÍTICO!**" if critico else "") + "."
    )

    for efeito in run.efeitos():
        efeito.ao_causar_dano(run, dano_real)

    return dano_real


def receber_dano(run: RunState, inimigo: EnemyState, dano: int) -> int:
    """Golpe da criatura: esquiva -> modificadores -> guarda -> barreira -> defesa."""
    if run.esquiva:
        run.esquiva = False
        run.log.append(
            "🌀 Você some entre as fendas e o golpe atravessa o vazio!"
        )
        return 0

    penetracao = inimigo.habilidade.penetracao_defesa(run, inimigo)
    defesa = max(0, run.defesa - penetracao)

    for efeito in run.efeitos():
        dano = efeito.modificar_dano_recebido(run, dano)

    if run.guarda and dano > 0:
        dano = max(1, dano // 2)
        run.log.append("🛡️ Sua guarda reduz o golpe pela metade.")

    bloqueado = min(run.barreira, dano)
    run.barreira -= bloqueado
    dano -= bloqueado

    dano_final = max(0, dano - defesa)

    antes = run.vida
    run.vida = max(0, run.vida - dano_final)
    perdida = antes - run.vida

    if bloqueado > 0:
        run.log.append(f"🛡️ Sua barreira absorveu {bloqueado} de dano.")

    if perdida > 0:
        run.log.append(f"💔 Você perdeu {perdida} de vida.")
    else:
        run.log.append("🛡️ Você resistiu completamente ao ataque!")

    return perdida


def processar_status_jogador(run: RunState) -> None:
    """Aplica sangramento e queimadura no jogador (fim do turno)."""
    if run.sangramento > 0:
        run.vida = max(0, run.vida - 3)
        run.sangramento -= 1
        run.log.append("🩸 O sangramento causa mais 3 de dano.")

    if run.queimadura > 0:
        run.vida = max(0, run.vida - 4)
        run.queimadura -= 1
        run.log.append("🔥 A queimadura temporal causa mais 4 de dano.")


def turno_inimigo(run: RunState) -> None:
    """Executa o turno completo da criatura atual."""
    inimigo = run.inimigo
    if inimigo is None or inimigo.vida <= 0:
        return

    inimigo.turnos += 1
    spec = inimigo.spec

    if inimigo.queimadura > 0:
        dano = 5 + run.nivel
        inimigo.vida = max(0, inimigo.vida - dano)
        inimigo.queimadura -= 1
        run.log.append(f"🔥 A queimadura causa {dano} de dano a {spec.nome}.")
        if inimigo.vida <= 0:
            return

    if inimigo.habilidade.ao_turno(run, inimigo):
        run.guarda = False
        processar_status_jogador(run)
        return

    dano = inimigo.ataque + random.randint(-3, 2)
    dano = inimigo.habilidade.modificar_ataque(run, inimigo, dano)

    perdida = receber_dano(run, inimigo, max(1, dano))
    run.log.append(
        f"{spec.nome} ataca e causa {perdida} de dano após suas defesas."
    )

    inimigo.habilidade.apos_golpe(run, inimigo, perdida)
    run.guarda = False
    processar_status_jogador(run)


# ============================================================
# 8. INTERFACE DO DISCORD
# ============================================================

def rotulo_categoria(categoria: str) -> str:
    return {
        "normal": "Criatura",
        "mini_chefe": "MINI-CHEFE",
        "chefe": "CHEFE",
        "deus": "DEUS — encontro raríssimo",
    }.get(categoria, categoria.title())


# Texto de cada categoria de item (loja, inventário).
TITULOS_ITEM = {
    "ataque": "⚔️ Ataque — equipado automaticamente ao iniciar a run",
    "defesa": "🧱 Defesa — equipada automaticamente ao iniciar a run",
    "vida": "❤️ Vitalidade — equipada automaticamente ao iniciar a run",
    "barreira": "🛡️ Barreira — equipada automaticamente ao iniciar a run",
    "critico": "💥 Crítico — equipado automaticamente ao iniciar a run",
    "foco": "⚡ Foco — equipado automaticamente ao iniciar a run",
}


def barra_foco(run: RunState) -> str:
    return "⚡" * run.foco + "▫️" * (FOCO_MAX - run.foco)


def ultimas_linhas(linhas: list[str], limite: int, tamanho: int = 1000) -> str:
    """Últimas linhas do log, sem estourar o limite do campo do embed."""
    escolhidas: list[str] = []
    total = 0
    for linha in reversed(linhas[-limite:]):
        if total + len(linha) + 1 > tamanho:
            break
        escolhidas.append(linha)
        total += len(linha) + 1
    return "\n".join(reversed(escolhidas))


def texto_status(run: RunState) -> str:
    """Status ativos no jogador, para o embed."""
    partes = []
    if run.barreira > 0:
        partes.append(f"🛡️ Barreira ({run.barreira})")
    if run.guarda:
        partes.append("🛡️ Em guarda")
    if run.esquiva:
        partes.append("🌀 Esquiva garantida")
    if run.sangramento > 0:
        partes.append(f"🩸 Sangramento ({run.sangramento})")
    if run.queimadura > 0:
        partes.append(f"🔥 Queimadura temporal ({run.queimadura})")
    if run.marcado:
        partes.append("🎯 Marcado")
    if run.ataque_bloqueado:
        partes.append("⏳ Próximo ataque interrompido")
    return " · ".join(partes) or "Nenhum"


def texto_intencao(run: RunState, inimigo: EnemyState) -> str:
    """O que a criatura pretende fazer, para o jogador decidir."""
    baixo = max(1, inimigo.ataque - 3)
    alto = max(1, inimigo.ataque + 2)
    return (
        f"👁️ **Intenção:** {inimigo.habilidade.intencao(run, inimigo)}\n"
        f"Golpe de ~{baixo}–{alto} antes de barreira e defesa."
    )


def criar_embed(
    run: RunState,
    titulo: str = "Ruptura Temporal",
) -> discord.Embed:
    """Monta o embed principal com o estado atual da run."""
    inimigo = run.inimigo
    tecnica = run.classe.tecnica

    embed = discord.Embed(
        title=titulo,
        description=(
            f"**Classe:** {run.classe.nome}\n"
            f"**Passiva:** {run.classe.passiva.nome}\n"
            f"**Técnica:** {tecnica.nome} ({tecnica.custo}⚡)\n"
            f"**Nível da run:** {run.nivel} · **Abates:** {run.abates}\n"
            f"**Vida:** {run.vida}/{run.vida_maxima}\n"
            f"**Foco:** {barra_foco(run)} ({run.foco}/{FOCO_MAX})\n"
            f"**Ataque:** {run.ataque} · **Defesa:** {run.defesa}\n"
            f"**Status:** {texto_status(run)}\n"
            f"**XP da run:** {run.xp} · **Abysmus:** {run.abysmus}"
        ),
        color=discord.Color.dark_purple(),
    )

    if inimigo:
        habilidade = inimigo.habilidade
        chamas = (
            f"\n🔥 **Em chamas** ({inimigo.queimadura})"
            if inimigo.queimadura > 0 else ""
        )
        embed.add_field(
            name=f"INIMIGO: {inimigo.spec.nome}"[:256],
            value=(
                f"*Era:* {inimigo.spec.era} · "
                f"*Categoria:* {rotulo_categoria(inimigo.spec.categoria)}\n"
                f"{inimigo.spec.descricao}\n"
                f"**Vida:** {inimigo.vida}/{inimigo.vida_maxima}\n"
                f"**Ataque:** {inimigo.ataque} · "
                f"**Defesa:** {inimigo.defesa}\n"
                f"**Habilidade:** {habilidade.nome} — {habilidade.descricao}"
                f"{chamas}\n"
                f"{texto_intencao(run, inimigo)}"
            )[:1024],
            inline=False,
        )

    reliquias = "\n".join(
        f"• {r.nome}: {r.descricao}" for r in run.reliquias
    ) or "Nenhuma relíquia encontrada."
    embed.add_field(name="Relíquias", value=reliquias[:1024], inline=False)

    if run.equipados:
        embed.add_field(
            name="Equipado da mochila (esta run)",
            value="\n".join(f"• {e}" for e in run.equipados)[:1024],
            inline=False,
        )

    if run.log:
        embed.add_field(
            name="Últimos acontecimentos",
            value=ultimas_linhas(run.log, LINHAS_LOG_VISIVEIS),
            inline=False,
        )

    embed.set_footer(
        text=(
            f"Run {run.run_id} · Atacar/Guardar +1⚡ · "
            f"Concentrar -{CUSTO_CONCENTRAR}⚡ · Técnica -{CUSTO_TECNICA}⚡"
        )
    )
    return embed


def criar_embed_mercado() -> discord.Embed:
    """Loja de itens passivos, organizada por tipo e do mais barato ao mais caro."""
    embed = discord.Embed(
        title="🛒 Mercado da Ruptura",
        description=(
            "Preços em **Abysmus**. Todos os itens são **passivos de build**: "
            "são equipados sozinhos quando a próxima run começa e valem "
            "só para aquela run."
        ),
        color=discord.Color.gold(),
    )
    for efeito, titulo in TITULOS_ITEM.items():
        itens = sorted(
            ((k, i) for k, i in ITENS.items() if i.efeito == efeito),
            key=lambda par: par[1].preco,
        )
        if not itens:
            continue
        linhas = [
            f"`{k}` **{i.nome}** — {i.preco} 🪙 (máx. {i.limite} por run)\n"
            f"{i.descricao}"
            for k, i in itens
        ]
        embed.add_field(name=titulo[:256], value="\n".join(linhas)[:1024],
                        inline=False)
    embed.set_footer(
        text="Comprar: s!market comprar CHAVE quantidade · Mochila: s!inventario"
    )
    return embed


class SelecaoClasse(discord.ui.Select):
    """Menu de seleção de classe (gerado a partir do catálogo CLASSES)."""

    def __init__(self, cog: "RupturaTemporal"):
        self.cog = cog
        opcoes = [
            discord.SelectOption(
                label=classe.nome[:100],
                value=chave,
                description=f"{classe.passiva.nome} · {classe.tecnica.nome}"[:100],
            )
            for chave, classe in list(CLASSES.items())[:25]
        ]
        super().__init__(
            placeholder="Escolha sua classe inicial",
            min_values=1,
            max_values=1,
            options=opcoes,
        )

    async def callback(self, interaction: discord.Interaction):
        await self.cog.iniciar_run(interaction, CLASSES[self.values[0]])


class TelaClasse(discord.ui.View):
    """Tela de escolha de classe. Só quem usou o comando pode escolher."""

    def __init__(self, cog: "RupturaTemporal", autor_id: int):
        super().__init__(timeout=120)
        self.autor_id = autor_id
        self.add_item(SelecaoClasse(cog))

    async def interaction_check(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                "Apenas quem iniciou o comando pode escolher a classe.",
                ephemeral=True,
            )
            return False
        return True


class TelaCombate(discord.ui.View):
    """Botões de combate: Atacar / Guardar / Concentrar / Técnica / Encerrar."""

    def __init__(self, cog: "RupturaTemporal", run: RunState):
        super().__init__(timeout=TIMEOUT_RUN_SEGUNDOS)
        self.cog = cog
        self.run = run
        self.message: Optional[discord.Message] = None
        tecnica = run.classe.tecnica
        self.btn_tecnica.label = f"{tecnica.nome} ({tecnica.custo}⚡)"[:80]
        self.btn_concentrar.label = f"Concentrar ({CUSTO_CONCENTRAR}⚡)"
        self.atualizar_botoes()

    def atualizar_botoes(self) -> None:
        """Desabilita ações que o Foco atual não paga."""
        self.btn_concentrar.disabled = self.run.foco < CUSTO_CONCENTRAR
        self.btn_tecnica.disabled = self.run.foco < self.run.classe.tecnica.custo

    async def interaction_check(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.run.user_id:
            await interaction.response.send_message(
                "Esta run pertence a outro jogador.", ephemeral=True
            )
            return False
        if self.run.finalizada:
            await interaction.response.send_message(
                "Esta run já terminou.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        """Encerra a run por inatividade sem competir com uma ação em curso."""
        async with self.run.action_lock:
            if self.run.finalizada:
                return
            embed = await self.cog.finalizar_run(
                self.run, "Run abandonada por inatividade."
            )
            if self.message is not None:
                try:
                    await self.message.edit(
                        content=None, embed=embed, view=None
                    )
                except discord.HTTPException:
                    log.warning(
                        "Não foi possível editar a mensagem da run %s.",
                        self.run.run_id,
                    )

    async def _concluir_acao(self, interaction: discord.Interaction) -> None:
        """Turno do inimigo, vitória/derrota e atualização da mensagem."""
        run = self.run
        inimigo = run.inimigo

        if inimigo is not None and inimigo.vida > 0:
            turno_inimigo(run)

        if run.vida <= 0:
            await self._finalizar(
                interaction, "Você foi consumido pela chama negra."
            )
            return

        if inimigo is not None and inimigo.vida <= 0:
            await self.cog.registrar_vitoria(run)

        self.atualizar_botoes()
        await interaction.edit_original_response(
            embed=criar_embed(run), view=self
        )

    async def _finalizar(
        self, interaction: discord.Interaction, motivo: str
    ) -> None:
        embed = await self.cog.finalizar_run(self.run, motivo)
        self.stop()
        await interaction.edit_original_response(
            content=None, embed=embed, view=None
        )

    async def _executar(
        self,
        interaction: discord.Interaction,
        acao: Callable[[RunState], None],
        custo: int = 0,
    ) -> None:
        """Fluxo comum de uma ação: trava, checa Foco, gasta, resolve, inimigo age."""
        run = self.run
        async with run.action_lock:
            if run.finalizada:
                await interaction.response.send_message(
                    "Esta run já terminou.", ephemeral=True
                )
                return
            if run.foco < custo:
                await interaction.response.send_message(
                    f"Foco insuficiente ({run.foco}/{custo} ⚡). "
                    "Ataque ou use Guardar para recuperar.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer()
            run.log.clear()
            run.turno += 1
            run.foco -= custo
            acao(run)
            await self._concluir_acao(interaction)

    @discord.ui.button(label="Atacar", style=discord.ButtonStyle.danger,
                       emoji="⚔️", row=0)
    async def btn_atacar(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        def acao(run: RunState) -> None:
            if run.ataque_bloqueado:
                run.ataque_bloqueado = False
                run.log.append(
                    "⏳ O tempo falha. Você perde esta oportunidade de atacar."
                )
                return
            executar_ataque(run)
            ganho = run.ganhar_foco(1 + (1 if run.ultimo_critico else 0))
            if ganho > 0:
                run.log.append(f"⚡ +{ganho} Foco.")
        await self._executar(interaction, acao)

    @discord.ui.button(label="Guardar", style=discord.ButtonStyle.secondary,
                       emoji="🛡️", row=0)
    async def btn_guardar(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        def acao(run: RunState) -> None:
            run.guarda = True
            ganho = run.ganhar_foco(1)
            run.log.append(
                "🛡️ Você assume guarda: o próximo golpe causa metade do dano."
                + (f" ⚡ +{ganho} Foco." if ganho else "")
            )
        await self._executar(interaction, acao)

    @discord.ui.button(label="Concentrar", style=discord.ButtonStyle.primary,
                       emoji="✨", row=0)
    async def btn_concentrar(self, interaction: discord.Interaction,
                             button: discord.ui.Button):
        def acao(run: RunState) -> None:
            cura = run.curar(12 + min(8, run.nivel // 2))
            run.barreira += 5
            run.log.append(
                f"✨ Você recupera {cura} de vida e ganha 5 de barreira."
            )
        await self._executar(interaction, acao, custo=CUSTO_CONCENTRAR)

    @discord.ui.button(label="Técnica", style=discord.ButtonStyle.success,
                       emoji="💥", row=0)
    async def btn_tecnica(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        custo = self.run.classe.tecnica.custo

        def acao(run: RunState) -> None:
            if run.ataque_bloqueado:
                run.ataque_bloqueado = False
                run.ganhar_foco(custo)  # a distorção anula a técnica; Foco devolvido
                run.log.append(
                    "⏳ O tempo falha e sua técnica se desfaz. O Foco é devolvido."
                )
                return
            run.classe.tecnica.acao(run)
        await self._executar(interaction, acao, custo=custo)

    @discord.ui.button(label="Encerrar", style=discord.ButtonStyle.secondary,
                       emoji="🏁", row=0)
    async def btn_encerrar(self, interaction: discord.Interaction,
                           button: discord.ui.Button):
        async with self.run.action_lock:
            if self.run.finalizada:
                await interaction.response.send_message(
                    "Esta run já terminou.", ephemeral=True
                )
                return
            await interaction.response.defer()
            await self._finalizar(interaction, "Run encerrada voluntariamente.")


# ============================================================
# 9. COG PRINCIPAL
# ============================================================

class RupturaTemporal(commands.Cog):
    """Cog do roguelite Ruptura Temporal."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        preparar_tabela_inventario()
        self.runs_ativas: dict[int, RunState] = {}

    async def cog_unload(self) -> None:
        if self.runs_ativas:
            log.warning(
                "Cog descarregado com %d run(s) ativa(s); descartadas.",
                len(self.runs_ativas),
            )
        self.runs_ativas.clear()

    def _embed_selecao(self, mochila: str) -> discord.Embed:
        """Tela de escolha de classe. Usa embed para caber as 10+ classes
        (uma mensagem comum estoura o limite de 2000 caracteres)."""
        embed = discord.Embed(
            title="RUPTURA TEMPORAL",
            description=(
                "A realidade de Da'kor está se desfazendo.\n\n"
                "**Como lutar:** Atacar e Guardar geram **Foco ⚡**. "
                f"Concentrar ({CUSTO_CONCENTRAR}⚡) cura; a **Técnica** da sua "
                f"classe ({CUSTO_TECNICA}⚡) é seu golpe especial. Leia a "
                "**👁️ Intenção** da criatura e escolha a ação certa.\n"
                "Mini-chefes a cada 3 encontros, chefes a cada 5; deuses "
                "podem surgir raramente. Cada criatura dá XP e pode dropar "
                f"Abysmus.{mochila}"
            ),
            color=discord.Color.dark_purple(),
        )
        for classe in CLASSES.values():
            embed.add_field(
                name=classe.nome[:256],
                value=(
                    f"❤️ {classe.vida} · ⚔️ {classe.ataque} · 🧱 {classe.defesa}\n"
                    f"**{classe.passiva.nome}:** {classe.passiva.descricao}\n"
                    f"**💥 {classe.tecnica.nome}:** {classe.tecnica.descricao}"
                )[:1024],
                inline=False,
            )
        if len(embed) > 5800:   # catálogo enorme: versão compacta
            embed.clear_fields()
            for classe in CLASSES.values():
                embed.add_field(
                    name=classe.nome[:256],
                    value=(
                        f"❤️ {classe.vida} ⚔️ {classe.ataque} 🧱 {classe.defesa} · "
                        f"{classe.passiva.nome} · 💥 {classe.tecnica.nome}"
                    )[:1024],
                    inline=False,
                )
        return embed

    @commands.command(name="ruptura", aliases=("rt", "rupturatemporal"))
    @commands.guild_only()
    async def ruptura(self, ctx: commands.Context):
        """Inicia uma run com s!ruptura; cada jogador tem uma sessão própria."""
        uid = ctx.author.id
        if uid in self.runs_ativas:
            await ctx.send("Você já tem uma run ativa. Continue a batalha atual.")
            return

        inventario = await asyncio.to_thread(
            listar_inventario, ctx.guild.id, uid
        )
        passivos = [
            f"{ITENS[k].nome} ×{min(q, ITENS[k].limite)}"
            for k, q in inventario.items() if k in ITENS
        ]
        if passivos:
            mochila = ("\n\n⚙️ **Será equipado nesta run:** "
                       + ", ".join(passivos))
        else:
            mochila = ("\n\n🛒 Você não tem itens. Use `s!market` para ver "
                       "itens passivos que fortalecem a próxima run.")

        await ctx.send(
            embed=self._embed_selecao(mochila),
            view=TelaClasse(self, uid),
        )

    async def equipar_itens_passivos(self, run: RunState) -> None:
        """Equipa itens passivos da mochila (consumindo-os), respeitando o limite."""
        inventario = await asyncio.to_thread(
            listar_inventario, run.guild_id, run.user_id
        )
        for chave, qtd in inventario.items():
            item = ITENS.get(chave)
            if item is None:
                continue
            usar = min(qtd, item.limite)
            ok = await asyncio.to_thread(
                consumir_item, run.guild_id, run.user_id, chave, usar
            )
            if not ok:
                continue
            usar_item(run, chave, vezes=usar)
            run.equipados.append(f"{item.nome} ×{usar} — {item.descricao}")

    async def iniciar_run(
        self,
        interaction: discord.Interaction,
        classe: ClassSpec,
    ):
        """Cria o estado da run, equipa a mochila, gera o 1º inimigo."""
        uid = interaction.user.id

        if uid in self.runs_ativas:
            await interaction.response.send_message(
                "Você já possui uma run ativa.", ephemeral=True
            )
            return

        run = RunState(
            user_id=uid,
            guild_id=interaction.guild_id or 0,
            user_nome=interaction.user.display_name,
            classe=classe,
            vida=classe.vida,
            vida_maxima=classe.vida,
            ataque=classe.ataque,
            defesa=classe.defesa,
        )
        # Reserva a vaga antes de qualquer await (evita duas runs).
        self.runs_ativas[uid] = run

        try:
            run.evento(
                f"Run iniciada | classe={classe.nome} | passiva="
                f"{classe.passiva.nome} | técnica={classe.tecnica.nome} | "
                f"vida={run.vida} ataque={run.ataque} defesa={run.defesa}"
            )

            classe.passiva.ao_obter(run)

            try:
                await self.equipar_itens_passivos(run)
            except Exception:
                log.exception("Falha ao equipar itens passivos da run %s.",
                              run.run_id)

            preparar_combate(run)
            view = TelaCombate(self, run)

            await interaction.response.edit_message(
                content="A ruptura começou. Sobreviva.",
                embed=criar_embed(run),
                view=view,
            )
            view.message = await interaction.original_response()
        except Exception:
            # Nunca deixa o jogador preso com uma run "fantasma".
            self.runs_ativas.pop(uid, None)
            log.exception("Falha ao iniciar a run %s.", run.run_id)
            raise

    async def registrar_vitoria(self, run: RunState) -> None:
        """Entrega XP por abate, chance de moeda e avança o encontro."""
        inimigo = run.inimigo
        if inimigo is None:
            return

        spec = inimigo.spec
        categoria = spec.categoria
        multiplicador_xp = {
            "normal": 1.0, "mini_chefe": 1.8, "chefe": 2.7, "deus": 4.5,
        }.get(categoria, 1.0)
        xp_ganho = max(1, int(spec.xp * multiplicador_xp))

        chance_moeda = {
            "normal": CHANCE_MOEDA_NORMAL,
            "mini_chefe": CHANCE_MOEDA_MINICHEFE,
            "chefe": CHANCE_MOEDA_CHEFE,
            "deus": CHANCE_MOEDA_DEUS,
        }.get(categoria, CHANCE_MOEDA_NORMAL)
        moedas = 0
        if random.random() < chance_moeda:
            limites = {
                "normal": (1, 2), "mini_chefe": (1, 3),
                "chefe": (2, 4), "deus": (3, 6),
            }
            minimo, maximo = limites.get(categoria, (1, 2))
            moedas = random.randint(minimo, maximo)

        run.abates += 1
        run.xp += xp_ganho
        run.abysmus += moedas

        drop_texto = (
            f"🪙 +{moedas} Abysmus" if moedas else "🪙 nenhum Abysmus desta vez"
        )
        run.log.append(
            f"**{rotulo_categoria(categoria)} derrotado: {spec.nome}!** "
            f"+{xp_ganho} XP · {drop_texto}."
        )
        run.evento(
            f"Vitória [{categoria}] {spec.nome} | +{xp_ganho} XP "
            f"+{moedas} Abysmus | vida={run.vida}/{run.vida_maxima}"
        )

        for efeito in run.efeitos():
            efeito.ao_inimigo_derrotado(run, inimigo)

        await award_rewards(
            self.bot, run.guild_id, run.user_id,
            xp=xp_ganho, abysmus=moedas,
            origem=f"ruptura_{categoria}",
        )

        run.nivel += 1
        run.evento(f"Próximo encontro: {run.nivel}")

        if run.nivel % RELIQUIA_A_CADA == 0:
            conceder_reliquia(run)

        preparar_combate(run)
        proximo = run.inimigo
        run.log.append(
            f"A ruptura avança. Próximo encontro: "
            f"{rotulo_categoria(proximo.spec.categoria)} — {proximo.spec.nome}."
        )

    async def finalizar_run(
        self, run: RunState, motivo: str
    ) -> discord.Embed:
        """Encerra a run uma única vez e retorna o embed final."""
        if run.finalizada:
            return criar_embed(run, "FIM DA RUPTURA")
        run.finalizada = True
        self.runs_ativas.pop(run.user_id, None)

        multiplicador = random.randint(1, 5)
        bonus_xp = run.nivel * multiplicador
        run.xp += bonus_xp

        persistido = await award_rewards(
            self.bot, run.guild_id, run.user_id,
            xp=bonus_xp, abysmus=0, origem="bonus_final_ruptura",
        )

        duracao = int(time.monotonic() - run.inicio)
        run.evento(
            f"RUN FINALIZADA | motivo={motivo} | classe={run.classe.nome} "
            f"| nível={run.nivel} | abates={run.abates} | xp_total={run.xp} "
            f"| abysmus={run.abysmus} | bônus={run.nivel}x{multiplicador}"
            f"={bonus_xp} | relíquias="
            f"{[r.nome for r in run.reliquias]} | equipados={run.equipados} "
            f"| duração={duracao}s | recompensa_salva={persistido}"
        )

        embed = criar_embed(run, "FIM DA RUPTURA")
        embed.description = (
            f"**Resultado:** {motivo}\n\n"
            f"**Classe:** {run.classe.nome}\n"
            f"**Nível alcançado:** {run.nivel}\n"
            f"**Criaturas derrotadas:** {run.abates}\n"
            f"**XP acumulado nesta run:** {run.xp}\n"
            f"**Abysmus obtido nesta run:** {run.abysmus}\n"
            f"**Bônus de conclusão:** {run.nivel} × {multiplicador} "
            f"= +{bonus_xp} XP\n\n"
            + (
                "Recompensa final enviada ao XpAndCoins."
                if persistido
                else "O bônus final não foi confirmado pelo XpAndCoins. "
                     "Verifique a integração do adaptador."
            )
            + "\n\n🛒 Gaste seus Abysmus em `s!market`, monte sua build e "
            "volte mais forte com `s!ruptura`."
        )
        return embed

    @commands.command(name="inventario", aliases=("inv",))
    @commands.guild_only()
    async def inventario(self, ctx: commands.Context):
        """Mostra os itens passivos comprados para a Ruptura."""
        itens = await asyncio.to_thread(
            listar_inventario, ctx.guild.id, ctx.author.id
        )
        if not itens:
            await ctx.send(
                "🎒 Seu inventário da Ruptura está vazio. "
                "Use `s!market` para ver a loja."
            )
            return

        embed = discord.Embed(
            title="🎒 Inventário da Ruptura",
            description=(
                "Estes itens são equipados automaticamente quando você "
                "inicia a próxima run."
            ),
            color=discord.Color.dark_gold(),
        )
        for efeito, titulo in TITULOS_ITEM.items():
            linhas = [
                f"• **{ITENS[k].nome}** ×{q} (`{k}`) — {ITENS[k].descricao}"
                for k, q in itens.items()
                if k in ITENS and ITENS[k].efeito == efeito
            ]
            if linhas:
                embed.add_field(name=titulo[:256],
                                value="\n".join(linhas)[:1024],
                                inline=False)

        desconhecidos = [f"• `{k}` ×{q}" for k, q in itens.items()
                         if k not in ITENS]
        if desconhecidos:
            embed.add_field(name="Itens fora do catálogo",
                            value="\n".join(desconhecidos)[:1024],
                            inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="market", aliases=("loja",))
    @commands.guild_only()
    async def market(
        self,
        ctx: commands.Context,
        acao: str | None = None,
        item_chave: str | None = None,
        quantidade: int = 1,
    ):
        """`s!market` lista; `s!market comprar CHAVE 2` compra."""
        if acao is None:
            await ctx.send(embed=criar_embed_mercado())
            return

        if acao.lower() not in {"comprar", "buy"} or not item_chave:
            await ctx.send("Uso: `s!market` ou `s!market comprar CHAVE quantidade`.")
            return

        chave = item_chave.lower()
        item = ITENS.get(chave)
        if item is None:
            await ctx.send("Esse item não existe. Use `s!market` para ver o catálogo.")
            return
        if quantidade < 1 or quantidade > 99:
            await ctx.send("A quantidade precisa ficar entre 1 e 99.")
            return

        xp_cog = self.bot.get_cog("XpAndCoins")
        alterar = getattr(xp_cog, "alterar_coins", None) if xp_cog else None
        if not callable(alterar):
            await ctx.send(
                "Não consegui acessar o sistema de Abysmus "
                "(XpAndCoins não carregado)."
            )
            return

        custo = item.preco * quantidade
        cobrado = False
        try:
            saldo = await asyncio.to_thread(
                alterar, ctx.guild.id, ctx.author.id, -custo
            )
            cobrado = True
            await asyncio.to_thread(
                guardar_item, ctx.guild.id, ctx.author.id, chave, quantidade
            )
        except ValueError:
            if not cobrado:
                await ctx.send(
                    f"Abysmus insuficiente. Você precisa de **{custo}** Abysmus."
                )
                return
            raise
        except Exception:
            if cobrado:
                try:
                    await asyncio.to_thread(
                        alterar, ctx.guild.id, ctx.author.id, custo
                    )
                except Exception:
                    log.exception("Falha ao estornar compra interrompida.")
            log.exception(
                "Falha ao comprar item | guild=%s user=%s item=%s",
                ctx.guild.id, ctx.author.id, chave,
            )
            await ctx.send(
                "A compra falhou. Tente novamente; o bot tentou proteger "
                "seu saldo."
            )
            return

        extra = ""
        if quantidade > item.limite:
            extra = (f"\nAtenção: só {item.limite} cópias são equipadas por "
                     "run; o resto fica guardado para as próximas.")
        await ctx.send(
            f"✅ Comprou **{quantidade}× {item.nome}** por **{custo} Abysmus**. "
            f"Saldo após a compra: **{saldo} Abysmus**.\n"
            f"Será equipado automaticamente no início da próxima run.{extra}"
        )


async def setup(bot: commands.Bot):
    """Ponto de entrada do cog (bot.load_extension)."""
    configurar_log_terminal()
    validar_catalogos()
    await bot.add_cog(RupturaTemporal(bot))
