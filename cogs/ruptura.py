"""
SEGREDO FLORESTA ADENTRO — RUPTURA TEMPORAL
============================================

Roguelite para Discord (discord.py 2.x) feito para rodar como cog do
Shaggy Bot.

Carregamento (arquivo cogs/ruptura.py; REMOVA o RupturaTemporal.py antigo,
senão os comandos e o cog ficam duplicados):
    await bot.load_extension("cogs.ruptura")

Comandos prefixados:
    s!ruptura      inicia uma run
    s!market       mostra a loja (s!market comprar CHAVE quantidade)
    s!inventario   mostra a mochila

Comandos slash da BUILD (gastam Abysmus):
    /build           central: especialização, árvore, compra, comparação
    /build_resetar   paga a taxa e devolve os pontos gastos de uma classe

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

BUILD (ÁRVORES DE ESPECIALIZAÇÃO)
---------------------------------
- 10 classes x 3 especializações x 5 nós (seção 7B). Os nós custam
  Abysmus e exigem nível de conta; a especialização vem no nível 3.
- A build é lida do banco ao iniciar a run e muda o combate de verdade:
  passivas, modificadores da técnica e habilidades ATIVAS (menu na run).
- /build_resetar: taxa de 100 Abysmus; os pontos gastos voltam como
  "pontos de build" e pagam os próximos nós antes do seu saldo.

EVENTOS TEMPORAIS (COM EFEITO REAL)
-----------------------------------
- Cada era tem o seu evento (Lua Sangrenta, Maré de Fuligem, Noite
  Alienígena); Halloween e Natal são sazonais e trazem criaturas
  exclusivas. Quatro eventos sazonais adicionais (Equinócio de Cinzas,
  Solstício Rachado, Colheita de Ecos e Semana dos Mortos) usam janelas
  próprias. Três eventos dinâmicos (Mercador do Intervalo, Fenda de Dois
  Caminhos e Voz na Névoa) só surgem no nível 4+ e oferecem escolhas.
  Eles alteram criaturas, jogador e recompensas e duram 1 ou 2
  encontros. O embed da run mostra o evento enquanto vale.

MERCADO E MOCHILA
-----------------
- O mercado vende quatro tipos de item: passivos de build (ataque,
  defesa, vida, barreira inicial, crítico e foco), artefatos com efeito
  especial, consumíveis e itens estratégicos.
- Passivos e artefatos são equipados automaticamente quando a próxima
  run começa e duram aquela run. Há um limite de cópias equipadas por
  item (o excedente continua na mochila para as runs seguintes).
- Consumíveis e estratégicos entram na mochila de combate da run. Usar
  um deles gasta a ação do turno; estratégicos têm limite de 1 uso por
  run. Eles NÃO entram no PvP, que usa apenas passivos e artefatos.
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
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import discord
from discord import app_commands
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

    # --- hooks acrescentados pelo sistema de BUILD (todos opcionais) ---

    def ao_fim_turno(self, run: "RunState") -> None:
        """Fim de cada turno (depois da criatura agir)."""

    def ao_golpe_recebido(
        self, run: "RunState", inimigo: "EnemyState", perdida: int
    ) -> None:
        """Depois de um golpe inimigo que NÃO foi esquivado."""

    def ao_tecnica(self, run: "RunState") -> None:
        """Depois de a técnica da classe ser usada."""

    def ao_defender(self, run: "RunState") -> None:
        """Quando o jogador usa Guardar."""

    def ao_morte(self, run: "RunState") -> bool:
        """Antes da derrota: devolva True para impedir a morte."""
        return False


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

# Tipos de item:
#   passivo     -> equipado no início da run, efeito permanente na run;
#   artefato    -> equipado no início da run, efeito especial via Efeito;
#   consumivel  -> usado na mochila durante o combate, gasta o turno;
#   estrategico -> usado na mochila, 1x por run, também gasta o turno.
TIPOS_ITEM = ("passivo", "consumivel", "artefato", "estrategico")
USOS_ITEM = ("run", "combate")


@dataclass(frozen=True)
class ItemSpec:
    """Definição de um item do mercado e da mochila."""
    nome: str
    descricao: str
    efeito: str
    poder: int
    preco: int = 0
    limite: int = 3   # máximo de cópias equipadas por run
    tipo: str = "passivo"
    uso: str = "run"
    aplicar: Optional[Callable[["RunState"], str]] = None
    efeito_factory: Optional[Callable[[], Efeito]] = None
    limite_run: int = 0   # 0 = sem limite extra além do estoque
    gasta_turno: bool = True


ITENS: dict[str, ItemSpec] = {}


def registrar_item(chave: str, spec: ItemSpec) -> ItemSpec:
    """Registra um item no catálogo expansível."""
    chave = chave.strip().lower()

    if not chave:
        raise ValueError("A chave do item não pode ser vazia.")

    if spec.tipo not in TIPOS_ITEM:
        raise ValueError(f"Tipo de item não reconhecido: {spec.tipo}")

    if spec.uso not in USOS_ITEM:
        raise ValueError(f"Uso de item não reconhecido: {spec.uso}")

    if spec.tipo == "passivo" and spec.efeito not in EFEITOS_ITEM:
        raise ValueError(f"Efeito de item não reconhecido: {spec.efeito}")

    if spec.tipo == "passivo" and spec.uso != "run":
        raise ValueError("Passivo precisa de uso 'run'.")

    if spec.tipo == "artefato":
        if spec.uso != "run" or spec.efeito_factory is None:
            raise ValueError("Artefato precisa de efeito_factory e uso 'run'.")

    if spec.tipo in ("consumivel", "estrategico"):
        if spec.uso != "combate" or spec.aplicar is None:
            raise ValueError(
                f"{spec.tipo.title()} precisa de aplicar() e uso 'combate'.")

    if spec.preco < 0:
        raise ValueError("O preço do item não pode ser negativo.")

    if spec.limite < 1:
        raise ValueError("O limite de cópias precisa ser pelo menos 1.")

    if spec.limite_run < 0:
        raise ValueError("O limite por run não pode ser negativo.")

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
        if run.turno > 0 and run.turno % run.ciclo_passiva == 0:
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
        bonus = run.alquimista_cargas * (2 + run.alq_extra)

        if bonus:
            run.log.append(
                f"⚗️ Reação em Cadeia acrescenta {bonus} de dano."
            )

        return ataque.dano + bonus

    def ao_causar_dano(self, run, dano_real):
        if dano_real <= 0:
            return

        run.alquimista_cargas = min(run.alquimista_max,
                                    run.alquimista_cargas + 1)

        run.log.append(
            f"⚗️ Reação em Cadeia: {run.alquimista_cargas}/{run.alquimista_max} cargas."
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
        if run.turno > 0 and run.turno % run.ciclo_passiva == 0:
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
                    bonus_fixo=8 + cargas * (6 + 2 * run.alq_extra),
                    nome_golpe="Detonação")
    inimigo = run.inimigo
    if inimigo is not None and inimigo.vida > 0:
        turnos = 2 + run.alq_queima_extra
        inimigo.queimadura = max(inimigo.queimadura, turnos)
        run.log.append(
            f"🔥 A detonação deixa o inimigo em chamas por {turnos} turnos.")


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
    evento: str = ""           # chave de um evento: só surge durante ele


@dataclass(frozen=True)
class AcaoInimiga:
    """Ação tática que uma criatura pode escolher em vez do golpe básico.

    Ações com ``prepara=True`` são telegrafadas: o primeiro turno só avisa
    o jogador e a ação resolve no turno seguinte. ``interrompivel`` permite
    cancelá-la com Guarda ou atordoamento, sem dano.
    """

    chave: str
    nome: str
    descricao: str
    tipo: str = "ataque"          # ataque | defesa | controle | cura
    prepara: bool = False
    interrompivel: bool = False
    dano_pct: float = 1.0         # só para ações de ataque sem aplicar()
    aplicar: Optional[Callable[["RunState", "EnemyState"], str]] = None


class HabilidadeInimiga:
    """Classe base das habilidades de criaturas. Hooks opcionais."""

    nome: str = "Nenhuma"
    descricao: str = ""

    def ao_iniciar_combate(self, run, inimigo) -> None:
        """Chamado quando a criatura entra em combate."""

    def ao_turno(self, run, inimigo) -> bool:
        """Retorne True se a habilidade CONSUMIU o turno."""
        return False

    def escolher_acao(self, run, inimigo) -> Optional[AcaoInimiga]:
        """Ação tática opcional. None mantém o golpe básico de sempre.

        A implementação padrão só age em chefes/deuses (veja
        escolher_acao_chefe). Criaturas comuns continuam exatamente como
        antes; uma habilidade pode sobrescrever este hook para ter uma
        decisão própria.
        """
        return escolher_acao_chefe(run, inimigo)

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


# ------------------------------------------------------------
# NOVAS HABILIDADES DE CRIATURAS (veja o tutorial acima do catálogo)
# ------------------------------------------------------------

@registrar_habilidade("espinhos")
class Espinhos(HabilidadeInimiga):
    nome = "Casca Farpada"
    descricao = "Cada golpe seu devolve 2 de dano (+1 a cada 6 níveis). Nunca mata."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        if dano <= 0:
            return dano
        retorno = min(6, 2 + run.nivel // 6)
        # A barreira absorve o retorno antes da vida; a vida nunca cai de 1.
        absorvido = min(run.barreira, retorno)
        run.barreira -= absorvido
        perda = min(retorno - absorvido, max(0, run.vida - 1))
        run.vida -= perda
        run.log.append(
            f"🌵 A casca de {inimigo.spec.nome} devolve {retorno} de dano"
            + (f" (barreira absorveu {absorvido})." if absorvido else ".")
        )
        return dano

    def intencao(self, run, inimigo):
        retorno = min(6, 2 + run.nivel // 6)
        return (f"Cada golpe seu devolve {retorno} de dano (a barreira absorve; "
                "nunca deixa você abaixo de 1 de vida). Poucos golpes fortes compensam.")


@registrar_habilidade("furia")
class Furia(HabilidadeInimiga):
    nome = "Fúria Crescente"
    descricao = "Causa até +6 de dano (+1 a cada 8 níveis) conforme perde vida."

    def modificar_ataque(self, run, inimigo, dano):
        perdido = 1 - inimigo.vida / max(1, inimigo.vida_maxima)
        extra = int((6 + run.nivel // 8) * perdido)
        if extra > 0:
            run.log.append(f"🔥 {inimigo.spec.nome} enfurece: +{extra} de dano.")
        return dano + max(0, extra)

    def intencao(self, run, inimigo):
        return "Quanto mais ferida, mais forte o golpe. Acabe rápido ou aguente em guarda."


@registrar_habilidade("ultimo_suspiro")
class UltimoSuspiro(HabilidadeInimiga):
    nome = "Último Suspiro"
    descricao = "Sobrevive 1x a um golpe fatal com 1 de vida e recupera 20% da vida no turno seguinte."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        if getattr(inimigo, "_suspiro", False) or dano < inimigo.vida:
            return dano
        inimigo._suspiro = True
        run.log.append(f"💀 {inimigo.spec.nome} resiste ao golpe fatal com 1 de vida!")
        return max(0, inimigo.vida - 1)

    def ao_turno(self, run, inimigo):
        if getattr(inimigo, "_suspiro", False) and not getattr(inimigo, "_suspiro_curou", False):
            inimigo._suspiro_curou = True
            cura = min(int(inimigo.vida_maxima * 0.20), inimigo.vida_maxima - inimigo.vida)
            if cura > 0:
                inimigo.vida += cura
                run.log.append(f"💀 {inimigo.spec.nome} recupera {cura} de vida.")
        return False

    def intencao(self, run, inimigo):
        if getattr(inimigo, "_suspiro", False):
            return "Já usou o Último Suspiro: agora cai de vez."
        return "Sobrevive uma vez a um golpe fatal e se recupera. Prepare um segundo golpe."


# ------------------------------------------------------------
# HABILIDADES EXCLUSIVAS DA EXPANSÃO (uma por criatura nova)
# ------------------------------------------------------------
# As habilidades são instanciadas UMA vez no catálogo; qualquer estado
# de combate precisa ficar no EnemyState (inimigo._algo), nunca em self.

@registrar_habilidade("lodo_primordial")
class LodoPrimordial(HabilidadeInimiga):
    nome = "Lodo Primordial"
    descricao = "Reduz 1 de dano enquanto está saudável; abaixo de 50% causa +2."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        if inimigo.vida > inimigo.vida_maxima * 0.5:
            return max(1, dano - 1)
        return dano

    def modificar_ataque(self, run, inimigo, dano):
        if inimigo.vida <= inimigo.vida_maxima * 0.5:
            if not getattr(inimigo, "_lodo_furia", False):
                inimigo._lodo_furia = True
                run.log.append("🟢 O lodo ancestral ferve ao ser ferido: +2 de dano.")
            return dano + 2
        return dano

    def intencao(self, run, inimigo):
        if inimigo.vida > inimigo.vida_maxima * 0.5:
            return "O lodo está saudável e absorve 1 de cada golpe. Abaixo de 50% ele enfurece (+2)."
        return "O lodo está abaixo de 50%: cada golpe causa +2."


@registrar_habilidade("raizes_prendem")
class RaizesPrendem(HabilidadeInimiga):
    nome = "Raízes Prendem"
    descricao = "A cada 4 turnos, prende você e faz você perder o próximo ataque."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 4 == 0:
            run.ataque_bloqueado = True
            run.log.append("🌿 Raízes emergem e prendem seus braços: o próximo ataque falha.")
            return True
        return False

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 4 == 0:
            return "Vai prender você: seu PRÓXIMO ataque falha. Use Concentrar ou Guardar."
        return f"Golpe direto. As raízes voltam em {4 - (inimigo.turnos % 4)} turno(s)."


@registrar_habilidade("colheita_fria")
class ColheitaFria(HabilidadeInimiga):
    nome = "Colheita Fria"
    descricao = "Causa +2 de dano por efeito negativo ativo em você (máx. +6)."

    def modificar_ataque(self, run, inimigo, dano):
        ativos = sum(1 for ativo in (
            run.sangramento > 0, run.queimadura > 0, run.marcado) if ativo)
        extra = min(6, ativos * 2)
        if extra:
            run.log.append(f"🌾 A colheita fria se alimenta de {ativos} ferida(s): +{extra}.")
        return dano + extra

    def intencao(self, run, inimigo):
        ativos = sum(1 for ativo in (
            run.sangramento > 0, run.queimadura > 0, run.marcado) if ativo)
        return (f"Golpe +{min(6, ativos * 2)} por seus efeitos negativos. "
                "Curar-se e limpar status reduz o dano.")


@registrar_habilidade("passo_duplo")
class PassoDuplo(HabilidadeInimiga):
    nome = "Passo Duplo"
    descricao = "A cada 3 turnos, o golpe é seguido por um segundo passo (+50%)."

    def modificar_ataque(self, run, inimigo, dano):
        if inimigo.turnos % 3 == 0:
            run.log.append("👣 Dois passos no mesmo instante: o segundo golpe chega junto.")
            return int(dano * 1.5)
        return dano

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai dar dois passos: golpe +50%. Guardar ou barreira seguram."
        return "Golpe direto. O passo duplo volta em breve."


@registrar_habilidade("eco_roubado")
class EcoRoubado(HabilidadeInimiga):
    nome = "Eco Roubado"
    descricao = "A cada 3 turnos, rouba 1 Foco seu."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 3 == 0:
            antes = run.foco
            run.foco = max(0, run.foco - 1)
            if antes:
                run.log.append("🔁 O Devorador de Ecos rouba 1 Foco seu.")
            else:
                run.log.append("🔁 O Devorador de Ecos tenta roubar Foco, mas você está vazio.")
        return False

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai roubar 1 Foco seu. Gaste o Foco antes ou aceite a perda."
        return "Golpe direto. O roubo de Foco volta em breve."


@registrar_habilidade("teia_ossea")
class TeiaOssea(HabilidadeInimiga):
    nome = "Teia Óssea"
    descricao = "A cada 3 turnos, quebra sua guarda e causa +3 de dano."

    def modificar_ataque(self, run, inimigo, dano):
        if inimigo.turnos % 3 == 0 and run.guarda:
            run.guarda = False
            run.log.append("🕸️ A teia óssea prende seu escudo e rasga a guarda.")
            return dano + 3
        return dano

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai quebrar sua guarda e causar +3. Barreira ainda funciona."
        return "Golpe direto."


@registrar_habilidade("pressao_crescente")
class PressaoCrescente(HabilidadeInimiga):
    nome = "Pressão Crescente"
    descricao = "Cada ataque aumenta o próximo em +1 (até +6)."

    def modificar_ataque(self, run, inimigo, dano):
        extra = min(6, getattr(inimigo, "_pressao", 0))
        inimigo._pressao = extra + 1
        if extra:
            run.log.append(f"♨️ A caldeira acumula pressão: +{extra} de dano.")
        return dano + extra

    def intencao(self, run, inimigo):
        extra = min(6, getattr(inimigo, "_pressao", 0))
        return f"O próximo golpe já tem +{extra} e sobe +1 a cada ataque. Acabe rápido."


@registrar_habilidade("vapor_escaldante")
class VaporEscaldante(HabilidadeInimiga):
    nome = "Vapor Escaldante"
    descricao = "Causa +1 de dano; golpes que ferem podem deixar você em chamas."

    def modificar_ataque(self, run, inimigo, dano):
        return dano + 1

    def apos_golpe(self, run, inimigo, vida_perdida):
        if vida_perdida > 0 and random.random() < 0.5:
            run.queimadura = max(run.queimadura, 1)
            run.log.append("♨️ O vapor escaldante gruda na sua pele: queimadura.")

    def intencao(self, run, inimigo):
        return "Golpe +1 com 50% de chance de queimadura. Barreira e Guarda evitam."


@registrar_habilidade("postura_de_latao")
class PosturaDeLatao(HabilidadeInimiga):
    nome = "Postura de Latão"
    descricao = "Os 3 primeiros golpes recebidos causam 3 a menos."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        usos = getattr(inimigo, "_latao", 0)
        if usos < 3 and dano > 0:
            inimigo._latao = usos + 1
            run.log.append("🔩 A postura de latão absorve 3 de dano.")
            return max(1, dano - 3)
        return dano

    def intencao(self, run, inimigo):
        usos = getattr(inimigo, "_latao", 0)
        if usos < 3:
            return f"A armadura ainda absorve 3 de dano ({3 - usos} golpe(s)). Use Técnicas."
        return "A armadura de latão já cedeu. Golpes normais bastam."


@registrar_habilidade("golpe_cego")
class GolpeCego(HabilidadeInimiga):
    nome = "Golpe Cego"
    descricao = "25% de chance de errar; quando acerta, causa +4."

    def ao_turno(self, run, inimigo):
        if random.random() < 0.25:
            run.log.append("🌀 O Maquinista Cego golpeia o vazio e perde o turno.")
            return True
        inimigo._cego_bonus = True
        return False

    def modificar_ataque(self, run, inimigo, dano):
        if getattr(inimigo, "_cego_bonus", False):
            inimigo._cego_bonus = False
            run.log.append("🔧 O golpe cego encontra você por acidente: +4.")
            return dano + 4
        return dano

    def intencao(self, run, inimigo):
        return "25% de errar; se acertar, causa +4. Barreira é mais confiável que sorte."


@registrar_habilidade("calor_abrasador")
class CalorAbrasador(HabilidadeInimiga):
    nome = "Calor Abrasador"
    descricao = "A cada 2 turnos, o ar incendeia e aplica 1 queimadura."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 2 == 0 and run.queimadura == 0:
            run.queimadura = 1
            run.log.append("🔥 A fornalha ambulante incendeia o ar: queimadura.")
        return False

    def intencao(self, run, inimigo):
        if run.queimadura == 0:
            return "O calor vai reacender a queimadura a cada 2 turnos. Guardar ajuda."
        return "A queimadura está ativa; o calor ainda ataca."


@registrar_habilidade("engrenagem_reversa")
class EngrenagemReversa(HabilidadeInimiga):
    nome = "Engrenagem Reversa"
    descricao = "A cada 4 turnos, gasta o turno para recuperar 8 de vida."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 4 == 0:
            cura = min(8, inimigo.vida_maxima - inimigo.vida)
            if cura > 0:
                inimigo.vida += cura
                run.log.append(f"⚙️ A engrenagem reversa remenda {cura} de vida.")
            return True
        return False

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 4 == 0:
            return "Vai gastar o turno se remendando (+8). Aproveite para atacar."
        return "Golpe direto. A engrenagem reversa volta em breve."


@registrar_habilidade("grito_primordial")
class GritoPrimordial(HabilidadeInimiga):
    nome = "Grito Primordial"
    descricao = "O primeiro golpe do combate causa +8."

    def modificar_ataque(self, run, inimigo, dano):
        if inimigo.turnos == 1:
            run.log.append("📢 O primeiro grito atravessa o tempo: +8 de dano.")
            return dano + 8
        return dano

    def intencao(self, run, inimigo):
        if inimigo.turnos == 0:
            return "O primeiro golpe causa +8. Guardar corta pela metade."
        return "Golpe direto."


@registrar_habilidade("marca_paradoxal")
class MarcaParadoxal(HabilidadeInimiga):
    nome = "Marca Paradoxal"
    descricao = "A cada 3 turnos, marca você; o golpe seguinte causa +6."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 3 == 0 and not run.marcado:
            run.marcado = True
            run.log.append("🎯 O Caçador de Paradoxos marca uma versão sua. O próximo golpe será mais forte.")
            return True
        return False

    def modificar_ataque(self, run, inimigo, dano):
        if run.marcado:
            run.marcado = False
            run.log.append("🎯 O golpe paradoxal encontra a versão marcada: +6.")
            return dano + 6
        return dano

    def intencao(self, run, inimigo):
        if run.marcado:
            return "Golpe marcado: +6! Guardar ou barreira valem muito agora."
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai gastar o turno marcando você. Bom momento para Concentrar."
        return "Golpe direto. A marca paradoxal volta em breve."


@registrar_habilidade("fio_alternativo")
class FioAlternativo(HabilidadeInimiga):
    nome = "Fio Alternativo"
    descricao = "25% de chance de desfazer o golpe, deixando só 1 de dano."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        if dano > 1 and random.random() < 0.25:
            run.log.append("🧵 A Tecelã puxa um fio alternativo: seu golpe quase não existe.")
            return 1
        return dano

    def intencao(self, run, inimigo):
        return "25% de chance de reduzir qualquer golpe a 1. Golpes múltiplos compensam."


@registrar_habilidade("sentenca")
class Sentenca(HabilidadeInimiga):
    nome = "Sentença"
    descricao = "Causa +1; se você estiver abaixo de 35% de vida, causa +8."

    def modificar_ataque(self, run, inimigo, dano):
        if run.vida <= run.vida_maxima * 0.35:
            run.log.append("⚖️ O Juiz do Fim lê sua sentença: +8 de dano.")
            return dano + 8
        return dano + 1

    def intencao(self, run, inimigo):
        if run.vida <= run.vida_maxima * 0.35:
            return "Você está abaixo de 35%: o próximo golpe causa +8. Guarde ou cure agora."
        return "Golpe +1. Abaixo de 35% de vida ele vira +8."


@registrar_habilidade("nome_roubado")
class NomeRoubado(HabilidadeInimiga):
    nome = "Nome Roubado"
    descricao = "A cada 3 turnos, rouba 2 Foco e recupera 3 de vida."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 3 == 0:
            antes = run.foco
            run.foco = max(0, run.foco - 2)
            cura = min(3, inimigo.vida_maxima - inimigo.vida)
            if cura:
                inimigo.vida += cura
            run.log.append(
                f"🏷️ O Devorador de Nomes rouba {antes - run.foco} Foco"
                + (f" e recupera {cura} de vida." if cura else "."))
        return False

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai roubar 2 Foco e recuperar 3 de vida. Gaste o Foco antes."
        return "Golpe direto. O roubo de nomes volta em breve."


@registrar_habilidade("reflexo_de_vidro")
class ReflexoDeVidro(HabilidadeInimiga):
    nome = "Reflexo de Vidro"
    descricao = "O primeiro golpe recebido é reduzido em 5 e devolve 3 de dano."

    def reduzir_dano_recebido(self, run, inimigo, dano):
        if getattr(inimigo, "_vidro", False) or dano <= 0:
            return dano
        inimigo._vidro = True
        absorvido = min(run.barreira, 3)
        run.barreira -= absorvido
        perda = min(3 - absorvido, max(0, run.vida - 1))
        run.vida -= perda
        run.log.append(
            f"🪞 O espelho de vidro racha e devolve 3 de dano"
            + (f" (barreira absorveu {absorvido})." if absorvido else "."))
        return max(1, dano - 5)

    def intencao(self, run, inimigo):
        if getattr(inimigo, "_vidro", False):
            return "O espelho já rachou. Golpes normais bastam."
        return "O primeiro golpe é reduzido em 5 e devolve 3. A barreira absorve o retorno."


@registrar_habilidade("foice_da_colheita")
class FoiceDaColheita(HabilidadeInimiga):
    nome = "Foice da Colheita"
    descricao = "Causa +3; contra você abaixo de 50% de vida, causa +6."

    def modificar_ataque(self, run, inimigo, dano):
        if run.vida <= run.vida_maxima * 0.5:
            run.log.append("🌾 A foice encontra a colheita madura: +6 de dano.")
            return dano + 6
        return dano + 3

    def intencao(self, run, inimigo):
        if run.vida <= run.vida_maxima * 0.5:
            return "Você está abaixo de 50%: a foice causa +6. Guarde ou cure."
        return "Golpe +3; abaixo de 50% de vida vira +6."


@registrar_habilidade("veu_de_cinzas")
class VeuDeCinzas(HabilidadeInimiga):
    nome = "Véu de Cinzas"
    descricao = "A cada 3 turnos, aplica queimadura e causa +2 no mesmo golpe."

    def ao_turno(self, run, inimigo):
        if inimigo.turnos % 3 == 0:
            run.queimadura = max(run.queimadura, 1)
            inimigo._veu_bonus = True
            run.log.append("⚱️ O véu de cinzas envolve você: queimadura e +2 de dano.")
        return False

    def modificar_ataque(self, run, inimigo, dano):
        if getattr(inimigo, "_veu_bonus", False):
            inimigo._veu_bonus = False
            return dano + 2
        return dano

    def intencao(self, run, inimigo):
        proximo = inimigo.turnos + 1
        if proximo % 3 == 0:
            return "Vai aplicar queimadura e causar +2. Guardar reduz o golpe."
        return "Golpe direto."


CRIATURAS: list[EnemySpec] = []


def registrar_criatura(spec: EnemySpec) -> EnemySpec:
    """Adiciona uma criatura ao catálogo."""
    CRIATURAS.append(spec)
    return spec


# ------------------------------------------------------------
# COMO ADICIONAR UMA CRIATURA (resumo; o guia completo está no tutorial)
# ------------------------------------------------------------
# 1. Escolha a era ("Da'kor", "Era a Vapor" ou "Futuro Distorcido") e a
#    categoria: normal | mini_chefe | chefe | deus.
# 2. Escolha uma habilidade que já existe em HABILIDADES (ou crie uma
#    nova com @registrar_habilidade("chave")).
# 3. Copie um registrar_criatura(EnemySpec(...)) e ajuste:
#      nome, era, nivel_minimo, vida, ataque, defesa, xp, abysmus,
#      habilidade, descricao, categoria=..., evento="" (ou a chave de um evento)
#    Siga a curva dos vizinhos de mesmo nível (veja o tutorial).
# 4. O campo 'abysmus' é LEGADO: hoje a moeda depende só da categoria
#    (CHANCE_MOEDA_*). Mantenha um valor coerente, mas ele não altera o drop.
# 5. Rode `python test_ruptura.py`: o validador acusa habilidade, era ou
#    evento inexistentes.

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


# ============================================================
# EXPANSÃO DO BESTIÁRIO — uma leva por era (proposta, não cânone)
# ============================================================
# Nomes, origens e comportamentos abaixo são EXPANSÃO SUGERIDA para SFA,
# ainda não estabelecida no cânone da Bíblia do Universo.

# ---------- Da'kor ----------
registrar_criatura(EnemySpec(
    "Raiz Sussurrante", "Da'kor", 2, 46, 10, 3, 20, 8, "espinhos",
    "Raízes que sussurram o nome de quem passa; a casca devolve cada golpe em farpas.",
))
registrar_criatura(EnemySpec(
    "Pária Afogado", "Da'kor", 3, 52, 11, 2, 24, 9, "ultimo_suspiro",
    "Alguém que a névoa levou ao fundo e devolveu. Insiste em terminar uma travessia.",
))
registrar_criatura(EnemySpec(
    "A Costureira de Neblina", "Da'kor", 3, 62, 10, 2, 44, 14, "espinhos",
    "Cose a névoa em mortalhas com agulhas que nunca terminam.",
    categoria="mini_chefe",
))
registrar_criatura(EnemySpec(
    "O Pastor de Raízes", "Da'kor", 10, 150, 14, 4, 140, 40, "espinhos",
    "Guia rebanhos de troncos pela névoa. Ninguém viu o rebanho voltar.",
    categoria="chefe",
))

# ---------- Era a Vapor ----------
registrar_criatura(EnemySpec(
    "Foguista Oco", "Era a Vapor", 4, 58, 15, 3, 30, 12, "furia",
    "Armadura de fornalha sem ninguém dentro. Quanto mais amassada, mais quente.",
))
registrar_criatura(EnemySpec(
    "Aranha de Pistões", "Era a Vapor", 6, 68, 14, 5, 36, 14, "sangramento",
    "Oito patas de pistão que tecem trilhos onde não havia chão.",
))
registrar_criatura(EnemySpec(
    "Relojoeiro Encarnado", "Era a Vapor", 6, 84, 12, 4, 60, 18, "furia",
    "Conserta relógios com as próprias engrenagens. Os relógios nunca batem a mesma hora.",
    categoria="mini_chefe",
))
registrar_criatura(EnemySpec(
    "O Maestro das Caldeiras", "Era a Vapor", 15, 180, 17, 5, 185, 50, "furia",
    "Rege uma orquestra de válvulas. Quando a música acelera, a sala inteira pulsa.",
    categoria="chefe",
))

# ---------- Futuro Distorcido ----------
registrar_criatura(EnemySpec(
    "Sombra do Ainda-Não", "Futuro Distorcido", 7, 72, 17, 3, 46, 20, "ultimo_suspiro",
    "A sombra de algo que ainda não existe e já chegou atrasada.",
))
registrar_criatura(EnemySpec(
    "Coro Sem Boca", "Futuro Distorcido", 9, 86, 18, 4, 55, 22, "furia",
    "Vozes que cantam em uníssono sem garganta. Cada baixa deixa o coro mais alto.",
))
registrar_criatura(EnemySpec(
    "Vigia do Intervalo", "Futuro Distorcido", 9, 98, 14, 3, 78, 24, "ultimo_suspiro",
    "Guarda o instante entre dois segundos. Nunca deixou ninguém passar por ele inteiro.",
    categoria="mini_chefe",
))
registrar_criatura(EnemySpec(
    "O Arquivista do Amanhã", "Futuro Distorcido", 20, 215, 18, 5, 225, 60, "ultimo_suspiro",
    "Cataloga fins que ainda não ocorreram. Se a sua ficha está incompleta, ele a completa.",
    categoria="chefe",
))

# ---------- Criaturas EXCLUSIVAS de eventos ----------
registrar_criatura(EnemySpec(
    "Máscara Sussurrante", "Da'kor", 1, 38, 10, 2, 24, 8, "emboscada",
    "Uma máscara sem rosto que chega por trás da vigília e repete o que você pensou.",
    evento="halloween",
))
registrar_criatura(EnemySpec(
    "Dançarino de Papel", "Era a Vapor", 5, 60, 14, 3, 34, 12, "sangramento",
    "Recortes que dançam sozinhos nos fios da vigília. As bordas cortam.",
    evento="halloween",
))
registrar_criatura(EnemySpec(
    "Luz sem Casa", "Da'kor", 1, 34, 8, 1, 22, 6, "regenerar",
    "Uma luz de janela sem janela. Reacende sempre que alguém tenta apagá-la.",
    evento="natal",
))
registrar_criatura(EnemySpec(
    "Presente sem Remetente", "Era a Vapor", 3, 66, 10, 6, 38, 12, "espinhos",
    "Embrulho que ninguém deixou na névoa. Quem tenta abri-lo apanha.",
    evento="natal",
))


# ============================================================
# EXPANSÃO 2 — 18 CRIATURAS NOVAS (6 POR ERA) + 2 SAZONAIS
# ============================================================
# Todas são 'normais' para entrarem no sorteio comum sem alterar as
# categorias de mini-chefe, chefe e deus. As habilidades são exclusivas
# de cada criatura e foram calibradas pela curva das vizinhas.

# ---------- Da'kor ----------
registrar_criatura(EnemySpec(
    "Lodo Ancestral", "Da'kor", 1, 34, 7, 2, 13, 5, "lodo_primordial",
    "O primeiro lodo que aprendeu a lembrar. Endurece quando está inteiro.",
))
registrar_criatura(EnemySpec(
    "Mãe das Raízes", "Da'kor", 4, 58, 11, 4, 27, 11, "raizes_prendem",
    "As raízes se movem para protegê-la. Ela nunca precisou caminhar.",
))
registrar_criatura(EnemySpec(
    "Ceifador de Névoa", "Da'kor", 5, 64, 13, 3, 31, 13, "colheita_fria",
    "Colhe ferimentos como quem colhe trigo: quanto mais ferido você está, mais forte ele fica.",
))
registrar_criatura(EnemySpec(
    "Sombra do Peregrino", "Da'kor", 7, 72, 15, 3, 40, 17, "passo_duplo",
    "Um peregrino que chegou dois passos antes de si mesmo.",
))
registrar_criatura(EnemySpec(
    "Devorador de Ecos", "Da'kor", 9, 88, 17, 4, 50, 21, "eco_roubado",
    "Alimenta-se do que você quase disse. O Foco que desaparece é o rastro dele.",
))
registrar_criatura(EnemySpec(
    "Aranha de Ossos", "Da'kor", 10, 96, 18, 5, 56, 24, "teia_ossea",
    "Uma teia de vértebras antigas que odeia escudos.",
))

# ---------- Era a Vapor ----------
registrar_criatura(EnemySpec(
    "Caldeireiro Possuído", "Era a Vapor", 2, 48, 10, 2, 19, 7, "pressao_crescente",
    "A caldeira ainda respira. Cada golpe abre mais uma válvula.",
))
registrar_criatura(EnemySpec(
    "Boneco de Válvulas", "Era a Vapor", 4, 60, 12, 4, 28, 11, "vapor_escaldante",
    "Um manequim de latão que solta vapor pelas juntas quando é golpeado.",
))
registrar_criatura(EnemySpec(
    "Sentinela de Latão", "Era a Vapor", 6, 74, 13, 6, 37, 15, "postura_de_latao",
    "Não foi construída para atacar. Foi construída para durar.",
))
registrar_criatura(EnemySpec(
    "Maquinista Cego", "Era a Vapor", 8, 84, 17, 3, 46, 19, "golpe_cego",
    "Trabalha pelo som das engrenagens. Acerta por acidente com força suficiente.",
))
registrar_criatura(EnemySpec(
    "Fornalha Ambulante", "Era a Vapor", 11, 104, 19, 5, 60, 26, "calor_abrasador",
    "Uma fornalha com pernas. O ar ao redor dela já queima.",
))
registrar_criatura(EnemySpec(
    "Relojoeiro de Carne", "Era a Vapor", 13, 122, 20, 5, 72, 31, "engrenagem_reversa",
    "Conserta o próprio corpo com as peças dos relógios que quebrou.",
))

# ---------- Futuro Distorcido ----------
registrar_criatura(EnemySpec(
    "Eco do Primeiro Grito", "Futuro Distorcido", 7, 70, 16, 3, 41, 18, "grito_primordial",
    "O primeiro som depois do fim ainda está chegando.",
))
registrar_criatura(EnemySpec(
    "Caçador de Paradoxos", "Futuro Distorcido", 9, 86, 17, 4, 49, 22, "marca_paradoxal",
    "Caça versões suas que ainda não cometeram o erro.",
))
registrar_criatura(EnemySpec(
    "Tecelã de Possibilidades", "Futuro Distorcido", 11, 100, 18, 5, 58, 26, "fio_alternativo",
    "Escolhe o fio em que seu golpe não aconteceu.",
))
registrar_criatura(EnemySpec(
    "Juiz do Fim", "Futuro Distorcido", 13, 115, 20, 5, 70, 30, "sentenca",
    "Já leu o veredito. Só espera você chegar ao ponto da sentença.",
))
registrar_criatura(EnemySpec(
    "Devorador de Nomes", "Futuro Distorcido", 15, 132, 21, 6, 82, 34, "nome_roubado",
    "Come o nome das coisas; o que sobra não consegue mais ser chamado.",
))
registrar_criatura(EnemySpec(
    "Anjo de Vidro Rachado", "Futuro Distorcido", 17, 148, 23, 6, 95, 38, "reflexo_de_vidro",
    "Uma asa de vidro que reflete um céu que não existe mais.",
))

# ---------- Sazonais (só aparecem em suas janelas) ----------
registrar_criatura(EnemySpec(
    "Cavaleiro da Última Colheita", "Da'kor", 6, 78, 14, 4, 42, 16,
    "foice_da_colheita",
    "Colhe o que restou dos peregrinos. A foice sabe quando você está fraco.",
    evento="colheita_de_ecos",
))
registrar_criatura(EnemySpec(
    "Noiva de Cinzas", "Futuro Distorcido", 8, 86, 16, 4, 48, 20,
    "veu_de_cinzas",
    "Uma noiva feita daquilo que sobra depois que o fogo termina.",
    evento="semana_dos_mortos",
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

    for problema in validar_eventos():
        log.warning("Evento/criatura inválido: %s", problema)

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
class MemoriaChefe:
    """Padrões observados pelo chefe DENTRO deste combate.

    Fica em EnemyState: por construção, não vaza entre chefe, run ou
    jogador. Nenhuma tabela nova é criada.
    """

    observacoes: list[str] = field(default_factory=list)
    adaptado: bool = False
    padrao: str = ""

    def registrar(self, chave: str) -> None:
        if not chave:
            return
        self.observacoes.append(chave)
        del self.observacoes[:-5]       # janela curta: memória tática recente

    def padrao_detectado(self, minimo: int = 3) -> Optional[str]:
        """Retorna a ação dominante (>=60%) após evidência suficiente."""
        if len(self.observacoes) < minimo:
            return None
        recentes = self.observacoes[-5:]
        chave, vezes = Counter(recentes).most_common(1)[0]
        if vezes / len(recentes) >= 0.6:
            return chave
        return None


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

    # Status acrescentados pelas builds (veja a seção 7B).
    veneno: int = 0            # acúmulos
    veneno_turnos: int = 0
    sangria: int = 0           # turnos
    marca: int = 0             # golpes restantes
    fraqueza: int = 0          # turnos
    atordoado: bool = False    # perde o próximo turno
    atordoado_usos: int = 0    # limite para mini-chefes

    # Combate tático e memória do chefe (defaults mantêm o PvP compatível).
    acao_pendente: Optional[AcaoInimiga] = None
    protecao: int = 0          # turnos de postura defensiva
    memoria: MemoriaChefe = field(default_factory=MemoriaChefe)

    @property
    def habilidade(self) -> HabilidadeInimiga:
        return HABILIDADES.get(self.spec.habilidade, _SEM_HABILIDADE)

    @property
    def imunidades(self) -> frozenset:
        """Status a que esta criatura é imune (categoria + criatura)."""
        return (IMUNIDADES_CATEGORIA.get(self.spec.categoria, frozenset())
                | IMUNIDADES_CRIATURA.get(self.spec.nome, frozenset()))

    def status_ativos(self) -> int:
        """Quantos efeitos negativos a criatura sofre agora."""
        return sum(1 for ativo in (
            self.queimadura > 0, self.veneno > 0, self.sangria > 0,
            self.marca > 0, self.fraqueza > 0, self.atordoado) if ativo)


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
    abatidos: dict[str, int] = field(default_factory=dict)  # "categoria|Criatura" -> total (ranking)

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

    # Parâmetros que a BUILD pode alterar (padrões = jogo original).
    classe_key: str = ""
    ciclo_passiva: int = 3          # Magia do Véu / Sobrecarga Mecânica
    alquimista_max: int = 5
    alq_extra: int = 0
    alq_queima_extra: int = 0
    fator_guarda: float = 0.5       # fração do golpe que passa em guarda
    mult_crit_extra: float = 0.0
    build: Optional["BuildAtivo"] = None
    build_efeito: Optional[Efeito] = None

    # Evento temporal em andamento (veja a seção de eventos).
    evento_ativo: Optional["EventoSpec"] = None
    evento_restante: int = 0          # encontros que ainda faltam depois deste
    evento_efeito: Optional[Efeito] = None
    evento_escolha_feita: bool = False
    eventos_dinamicos: set[str] = field(default_factory=set)

    # Estado de golpe/combate usado pelos efeitos da build.
    golpe_tecnica: bool = False
    golpe_ativa: bool = False
    ignorou_defesa: bool = False
    esquivou_agora: bool = False
    golpes_combate: int = 0
    ultimo_dano_real: int = 0

    reliquias: list[Efeito] = field(default_factory=list)
    equipados: list[str] = field(default_factory=list)  # itens passivos
    itens_efeitos: list[Efeito] = field(default_factory=list)  # artefatos
    consumiveis: dict[str, int] = field(default_factory=dict)
    consumiveis_usados: dict[str, int] = field(default_factory=dict)
    ataque_bonus: int = 0          # bônus temporário de consumíveis
    inimigo: Optional[EnemyState] = None

    # Mercador antes de chefe/deus e forja vinculada a esta run.
    mercador: Optional["Mercador"] = None
    mercador_visto: set[int] = field(default_factory=set)
    categoria_pendente: str = ""
    forja: dict[str, int] = field(default_factory=dict)
    forja_usos: int = 0

    finalizada: bool = False
    log: list[str] = field(default_factory=list)
    action_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def efeitos(self) -> list[Efeito]:
        """Passiva da classe + build + evento + relíquias + artefatos."""
        build = [self.build_efeito] if self.build_efeito else []
        evento = [self.evento_efeito] if self.evento_efeito else []
        return [
            self.classe.passiva, *build, *evento, *self.reliquias,
            *self.itens_efeitos,
        ]

    def custo_tecnica(self) -> int:
        """Custo de Foco da técnica (a build pode reduzir em 1; mínimo 1)."""
        reducao = 0
        if self.build is not None:
            reducao = min(1, int(self.build.agg.get("tec_custo", 0)))
        return max(1, self.classe.tecnica.custo - reducao)

    def mult_critico(self) -> float:
        """Multiplicador de dano dos críticos (base + build)."""
        return MULTIPLICADOR_CRITICO + self.mult_crit_extra

    def conc_bonus(self) -> float:
        """Bônus percentual de Concentrar vindo da build."""
        return self.build.agg.get("conc_bonus", 0.0) if self.build else 0.0

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


# ------------------------------------------------------------
# MERCADOR DE CHEFE E FORJA (válidos apenas dentro da run)
# ------------------------------------------------------------

MERCADOR_CATEGORIAS = ("consumivel", "estrategico", "artefato", "forja")
FORJA_LIMITE = 2                 # aprimoramentos por run
FORJA_CAP = {"ataque": 2, "defesa": 2, "vida": 20}
FORJA_INCREMENTO = {"ataque": 1, "defesa": 1, "vida": 10}
FORJA_PRECO = {"ataque": 12, "defesa": 12, "vida": 10}
FORJA_CUSTO_CRESCENTE = 4        # +4 Abysmus por aprimoramento já feito


@dataclass
class MercadorOferta:
    """Uma oferta do mercador. Consumíveis/estratégicos são persistentes;
    artefatos e forja valem somente nesta run e são aplicados na compra."""
    chave: str
    categoria: str
    nome: str
    descricao: str
    preco: int
    comprado: bool = False


@dataclass
class Mercador:
    nivel: int
    ofertas: list[MercadorOferta] = field(default_factory=list)
    saldo: int = 0


def preco_oferta(run: RunState, oferta: MercadorOferta) -> int:
    """Preço atual; a forja fica mais cara a cada uso na mesma run."""
    if oferta.categoria == "forja":
        base = FORJA_PRECO.get(oferta.chave.removeprefix("forja_"), 10)
        return base + FORJA_CUSTO_CRESCENTE * run.forja_usos
    return oferta.preco


def criar_mercador(run: RunState, saldo: int = 0) -> Mercador:
    """Monta a oferta com as quatro categorias, sem duplicar itens."""
    ofertas: list[MercadorOferta] = []

    def adicionar(itens: list[tuple[str, "ItemSpec"]]) -> None:
        for chave, item in itens:
            ofertas.append(MercadorOferta(
                chave=chave, categoria=item.tipo, nome=item.nome,
                descricao=item.descricao, preco=item.preco,
            ))

    consumiveis = [(k, i) for k, i in ITENS.items() if i.tipo == "consumivel"]
    estrategicos = [(k, i) for k, i in ITENS.items() if i.tipo == "estrategico"]
    equipados = {efeito.nome for efeito in run.itens_efeitos}
    artefatos = [(k, i) for k, i in ITENS.items()
                 if i.tipo == "artefato" and i.nome not in equipados]

    adicionar(random.sample(consumiveis, min(2, len(consumiveis))))
    adicionar(random.sample(estrategicos, min(2, len(estrategicos))))
    adicionar(random.sample(artefatos, min(1, len(artefatos))))

    for tipo in ("ataque", "defesa", "vida"):
        ofertas.append(MercadorOferta(
            chave=f"forja_{tipo}",
            categoria="forja",
            nome=f"Forja: +{FORJA_INCREMENTO[tipo]} {tipo}"
                 if tipo != "vida" else "Forja: +10 vida máxima",
            descricao=(
                f"Aprimoramento desta run (máx. {FORJA_CAP[tipo]} por "
                f"atributo; {FORJA_LIMITE} no total)."
            ),
            preco=FORJA_PRECO[tipo],
        ))

    return Mercador(nivel=run.nivel, ofertas=ofertas, saldo=saldo)


def abrir_mercador(
    run: RunState, categoria: str, saldo: int = 0
) -> bool:
    """Cria o mercador no máximo uma vez por nível elegível.

    Retorna True quando uma nova vitrine foi aberta. A checagem de
    ``run.mercador`` impede duplicação mesmo se o hook for chamado duas
    vezes (por exemplo, por um evento ou por um retry).
    """
    if categoria not in ("chefe", "deus"):
        return False
    if run.mercador is not None or run.nivel in run.mercador_visto:
        return False
    run.mercador_visto.add(run.nivel)
    run.mercador = criar_mercador(run, saldo=saldo)
    return True


def motivo_bloqueio_oferta(run: RunState, oferta: MercadorOferta) -> str:
    """Retorna o motivo para não comprar; vazio quando a oferta é válida."""
    if oferta.comprado:
        return "Essa oferta já foi comprada."
    if oferta.categoria == "forja":
        tipo = oferta.chave.removeprefix("forja_")
        if run.forja_usos >= FORJA_LIMITE:
            return f"A forja aceita no máximo {FORJA_LIMITE} aprimoramentos por run."
        if run.forja.get(tipo, 0) >= FORJA_CAP.get(tipo, 0):
            return f"{tipo.title()} já atingiu o teto desta run."
        return ""
    item = ITENS.get(oferta.chave)
    if item is None:
        return "Oferta inválida."
    if item.tipo == "artefato" and any(
            e.nome == item.nome for e in run.itens_efeitos):
        return "Você já equipou esse artefato nesta run."
    return ""


def aplicar_oferta_mercador(run: RunState, oferta: MercadorOferta) -> str:
    """Aplica uma oferta já paga. A validação ocorre antes do débito."""
    oferta.comprado = True
    if oferta.categoria == "forja":
        tipo = oferta.chave.removeprefix("forja_")
        ganho = FORJA_INCREMENTO[tipo]
        run.forja[tipo] = run.forja.get(tipo, 0) + ganho
        run.forja_usos += 1
        if tipo == "vida":
            run.vida_maxima += ganho
            run.curar(ganho)
        elif tipo == "ataque":
            run.ataque += ganho
        else:
            run.defesa += ganho
        return f"🔥 A forja cresce: +{ganho} {tipo} nesta run."

    item = ITENS[oferta.chave]
    if item.tipo in ("consumivel", "estrategico"):
        run.consumiveis[oferta.chave] = run.consumiveis.get(oferta.chave, 0) + 1
        return f"🎒 {item.nome} entrou na mochila de combate."
    equipar_item_da_run(run, oferta.chave)
    return f"🔮 {item.nome} foi equipado nesta run."


def usar_item(run: RunState, chave: str, vezes: int = 1) -> bool:
    """Aplica o efeito PASSIVO de um item registrado (vezes = cópias).

    Não mexe no inventário: quem chama é responsável por consumir o item.
    """
    item = ITENS.get(chave)
    if item is None:
        run.log.append(f"O item '{chave}' não existe no catálogo.")
        return False

    if item.tipo != "passivo":
        run.log.append(f"O item '{item.nome}' não é passivo.")
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
# 2B. ARTEFATOS, CONSUMÍVEIS E ITENS ESTRATÉGICOS
# ============================================================
# Os artefatos são equipados no início da run e usam os mesmos hooks das
# relíquias. Consumíveis e estratégicos ficam na mochila de combate: usam
# uma ação (o inimigo age em seguida) e são gastos do inventário.

class OlhoDeVidro(Efeito):
    nome = "Olho de Vidro"
    descricao = "O primeiro golpe de cada combate causa +3 de dano."

    def ao_iniciar_combate(self, run, inimigo) -> None:
        self._usado = False

    def modificar_dano_causado(self, run, ataque) -> int:
        if getattr(self, "_usado", False):
            return ataque.dano
        self._usado = True
        run.log.append("🔮 O Olho de Vidro enxerga a falha: +3 de dano.")
        return ataque.dano + 3


class MantoDeNevoa(Efeito):
    nome = "Manto de Névoa"
    descricao = "O primeiro golpe recebido em cada combate causa 4 a menos."

    def ao_iniciar_combate(self, run, inimigo) -> None:
        self._usado = False

    def modificar_dano_recebido(self, run, dano: int) -> int:
        if getattr(self, "_usado", False) or dano <= 0:
            return dano
        self._usado = True
        run.log.append("🌫️ O Manto de Névoa amortece o primeiro golpe (-4).")
        return max(1, dano - 4)


class CoracaoDeCristal(Efeito):
    nome = "Coração de Cristal"
    descricao = "Uma vez por combate, cura 4 quando você cai a 50% da vida."

    def ao_iniciar_combate(self, run, inimigo) -> None:
        self._usado = False

    def ao_fim_turno(self, run) -> None:
        if (getattr(self, "_usado", False)
                or run.vida <= 0
                or run.vida > run.vida_maxima * 0.5):
            return
        self._usado = True
        cura = run.curar(4)
        run.log.append(f"💎 O Coração de Cristal pulsa e cura {cura} de vida.")


class SineteDoCarrasco(Efeito):
    nome = "Sinete do Carrasco"
    descricao = "Causa +15% de dano contra criaturas com 35% de vida ou menos."

    def ao_iniciar_combate(self, run, inimigo) -> None:
        self._avisou = False

    def modificar_dano_causado(self, run, ataque) -> int:
        inimigo = run.inimigo
        if (inimigo is None or inimigo.vida <= 0
                or inimigo.vida > inimigo.vida_maxima * EXECUCAO_LIMITE):
            return ataque.dano
        if not getattr(self, "_avisou", False):
            self._avisou = True
            run.log.append("☠️ O Sinete do Carrasco sente o fim próximo (+15%).")
        return int(ataque.dano * 1.15)


class RelogioQuebrado(Efeito):
    nome = "Relógio Quebrado"
    descricao = "Ao derrotar uma criatura, devolve +1 Foco."

    def ao_inimigo_derrotado(self, run, inimigo) -> None:
        ganho = run.ganhar_foco(1)
        if ganho:
            run.log.append("⏱️ O Relógio Quebrado gira ao contrário: +1 Foco.")


def _aplicar_pocao_vida(run: RunState) -> str:
    cura = run.curar(max(1, int(run.vida_maxima * 0.35)))
    return f"🧪 Você recupera {cura} de vida."


def _aplicar_pocao_foco(run: RunState) -> str:
    ganho = run.ganhar_foco(2)
    return f"⚡ A poção dissolve-se em luz: +{ganho} Foco."


def _aplicar_bomba_fuligem(run: RunState) -> str:
    if run.inimigo is None or run.inimigo.vida <= 0:
        return "💨 A bomba explode no vazio."
    dano = 18 + run.nivel * 2
    executar_ataque(
        run, mult=0.0, nunca_erra=True, ignora_defesa=True,
        bonus_fixo=dano, nome_golpe="Bomba de Fuligem",
    )
    return "💣 A Bomba de Fuligem explode sem pedir licença."


def _aplicar_oleo(run: RunState) -> str:
    if run.inimigo is None:
        return "🛢️ O óleo escorre pelo chão vazio."
    aplicar_status(run, run.inimigo, "queimar", 3)
    return "🛢️ O óleo pega fogo: a criatura vai queimar por 3 turnos."


def _aplicar_veneno(run: RunState) -> str:
    if run.inimigo is None:
        return "☠️ O frasco se quebra sem alvo."
    aplicar_status(run, run.inimigo, "veneno", 3)
    return "☠️ O Veneno do Véu entra na carne da criatura."


def _aplicar_escudo(run: RunState) -> str:
    run.barreira = min(run.vida_maxima, run.barreira + 18)
    run.guarda = True
    return "🛡️ O escudo se abre: +18 de barreira e guarda erguida."


def _aplicar_kit(run: RunState) -> str:
    cura = run.curar(max(1, int(run.vida_maxima * 0.20)))
    tinha = run.sangramento + run.queimadura
    run.sangramento = 0
    run.queimadura = 0
    extra = " e limpa seus ferimentos" if tinha else ""
    return f"🩹 Você recupera {cura} de vida{extra}."


def _aplicar_lamina(run: RunState) -> str:
    run.ataque_bonus += 6
    return "🗡️ A Lâmina de Aluguel brilha: +6 de ataque até o fim do combate."


def _aplicar_fumaca(run: RunState) -> str:
    run.esquiva = True
    return "💨 A fumaça cobre sua próxima esquiva: o próximo golpe erra."


def _aplicar_distorcao(run: RunState) -> str:
    if run.build is None:
        run.ganhar_foco(1)
        return "⏳ Sem build ativa, a distorção devolve +1 Foco."
    run.build.cd.clear()
    run.build.usos.clear()
    return "⏳ A Distorção Temporal rearma todas as habilidades da build."


def _aplicar_pacto(run: RunState) -> str:
    perda = min(max(1, int(run.vida_maxima * 0.15)), max(0, run.vida - 1))
    run.vida -= perda
    ganho = run.ganhar_foco(3)
    return (f"🩸 O pacto cobra {perda} de vida e devolve +{ganho} Foco.")


def _aplicar_isca(run: RunState) -> str:
    if run.inimigo is None:
        return "🥩 A isca cai no chão vazio."
    run.inimigo.fraqueza = max(run.inimigo.fraqueza, 3)
    return "🥩 A criatura morde a isca e fica enfraquecida por 3 turnos."


def _aplicar_selo(run: RunState) -> str:
    if run.inimigo is None:
        return "🔇 O selo não encontra voz."
    if run.inimigo.spec.categoria in ("chefe", "deus"):
        run.inimigo.fraqueza = max(run.inimigo.fraqueza, 2)
        return ("🔇 O selo não cala chefes e deuses, mas os enfraquece "
                "por 2 turnos.")
    run.inimigo.atordoado = True
    return "🔇 O Selo de Silêncio cala a criatura: ela perde o próximo turno."


def equipar_item_da_run(run: RunState, chave: str, vezes: int = 1) -> bool:
    """Equipa um item de uso 'run' (passivo ou artefato)."""
    item = ITENS.get(chave)
    if item is None:
        return False
    if item.tipo == "passivo":
        return usar_item(run, chave, vezes)
    if item.tipo != "artefato" or item.efeito_factory is None:
        return False
    for _ in range(max(1, vezes)):
        run.itens_efeitos.append(item.efeito_factory())
    run.evento(f"Artefato equipado: {item.nome} ({chave}) x{vezes}.")
    return True


def usar_consumivel(run: RunState, chave: str) -> tuple[bool, str]:
    """Aplica um consumível/estratégico já validado e desconta do snapshot.

    O estoque persistente é consumido por quem chama (com consumir_item).
    """
    item = ITENS.get(chave)
    if item is None:
        return False, "Esse item não existe."
    if item.tipo not in ("consumivel", "estrategico") or item.aplicar is None:
        return False, "Esse item não pode ser usado em combate."
    if run.consumiveis.get(chave, 0) <= 0:
        return False, "Você não tem esse item na mochila."
    if item.limite_run and run.consumiveis_usados.get(chave, 0) >= item.limite_run:
        return False, (f"{item.nome} só pode ser usado "
                       f"{item.limite_run}x por run.")

    mensagem = item.aplicar(run)
    run.consumiveis[chave] = run.consumiveis.get(chave, 0) - 1
    run.consumiveis_usados[chave] = run.consumiveis_usados.get(chave, 0) + 1
    if mensagem:
        run.log.append(mensagem)
    run.evento(f"Item de combate usado: {item.nome} ({chave}).")
    return True, mensagem


# ---------- catálogo: 5 artefatos, 8 consumíveis, 5 estratégicos ----------

registrar_item("olho_de_vidro", ItemSpec(
    nome="Olho de Vidro", descricao=OlhoDeVidro.descricao, efeito="",
    poder=0, preco=42, limite=1, tipo="artefato", uso="run",
    efeito_factory=OlhoDeVidro,
))
registrar_item("manto_de_nevoa", ItemSpec(
    nome="Manto de Névoa", descricao=MantoDeNevoa.descricao, efeito="",
    poder=0, preco=38, limite=1, tipo="artefato", uso="run",
    efeito_factory=MantoDeNevoa,
))
registrar_item("coracao_de_cristal", ItemSpec(
    nome="Coração de Cristal", descricao=CoracaoDeCristal.descricao, efeito="",
    poder=0, preco=45, limite=1, tipo="artefato", uso="run",
    efeito_factory=CoracaoDeCristal,
))
registrar_item("sinete_do_carrasco", ItemSpec(
    nome="Sinete do Carrasco", descricao=SineteDoCarrasco.descricao, efeito="",
    poder=0, preco=50, limite=1, tipo="artefato", uso="run",
    efeito_factory=SineteDoCarrasco,
))
registrar_item("relogio_quebrado", ItemSpec(
    nome="Relógio Quebrado", descricao=RelogioQuebrado.descricao, efeito="",
    poder=0, preco=36, limite=1, tipo="artefato", uso="run",
    efeito_factory=RelogioQuebrado,
))

registrar_item("pocao_de_vida", ItemSpec(
    nome="Poção de Vida", descricao="Recupera 35% da vida máxima.",
    efeito="", poder=0, preco=12, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_pocao_vida,
))
registrar_item("pocao_de_foco", ItemSpec(
    nome="Poção de Foco", descricao="Devolve +2 Foco.",
    efeito="", poder=0, preco=14, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_pocao_foco,
))
registrar_item("bomba_de_fuligem", ItemSpec(
    nome="Bomba de Fuligem",
    descricao="Causa 18 + 2×nível de dano, sem errar e ignorando defesa.",
    efeito="", poder=0, preco=18, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_bomba_fuligem,
))
registrar_item("oleo_pegajoso", ItemSpec(
    nome="Óleo Pegajoso", descricao="Deixa a criatura em chamas por 3 turnos.",
    efeito="", poder=0, preco=15, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_oleo,
))
registrar_item("veneno_do_veu", ItemSpec(
    nome="Veneno do Véu", descricao="Envenena a criatura por 3 turnos.",
    efeito="", poder=0, preco=16, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_veneno,
))
registrar_item("escudo_de_campanha", ItemSpec(
    nome="Escudo de Campanha",
    descricao="Concede +18 de barreira e ergue a guarda.",
    efeito="", poder=0, preco=20, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_escudo,
))
registrar_item("kit_de_emergencia", ItemSpec(
    nome="Kit de Emergência",
    descricao="Cura 20% da vida e limpa sangramento/queimadura.",
    efeito="", poder=0, preco=22, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_kit,
))
registrar_item("lamina_de_aluguel", ItemSpec(
    nome="Lâmina de Aluguel",
    descricao="+6 de ataque até o fim do combate atual.",
    efeito="", poder=0, preco=19, limite=99, tipo="consumivel",
    uso="combate", aplicar=_aplicar_lamina,
))

registrar_item("bomba_de_fumaca", ItemSpec(
    nome="Bomba de Fumaça",
    descricao="Garante esquiva do próximo golpe inimigo.",
    efeito="", poder=0, preco=28, limite=99, tipo="estrategico",
    uso="combate", aplicar=_aplicar_fumaca, limite_run=1,
))
registrar_item("distorcao_temporal", ItemSpec(
    nome="Distorção Temporal",
    descricao="Rearma as recargas e os usos das habilidades da build.",
    efeito="", poder=0, preco=34, limite=99, tipo="estrategico",
    uso="combate", aplicar=_aplicar_distorcao, limite_run=1,
))
registrar_item("pacto_de_sangue", ItemSpec(
    nome="Pacto de Sangue",
    descricao="Perde 15% da vida máxima (nunca abaixo de 1) por +3 Foco.",
    efeito="", poder=0, preco=26, limite=99, tipo="estrategico",
    uso="combate", aplicar=_aplicar_pacto, limite_run=1,
))
registrar_item("isca_de_carne", ItemSpec(
    nome="Isca de Carne",
    descricao="Enfraquece a criatura por 3 turnos (-20% de ataque).",
    efeito="", poder=0, preco=24, limite=99, tipo="estrategico",
    uso="combate", aplicar=_aplicar_isca, limite_run=1,
))
registrar_item("selo_de_silencio", ItemSpec(
    nome="Selo de Silêncio",
    descricao="Faz criaturas comuns perderem o próximo turno; chefes resistem.",
    efeito="", poder=0, preco=32, limite=99, tipo="estrategico",
    uso="combate", aplicar=_aplicar_selo, limite_run=1,
))


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
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS ruptura_inventario (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, item_key)
            )
        """)
        db.commit()


def listar_inventario(guild_id: int, user_id: int) -> dict[str, int]:
    """Retorna apenas itens com quantidade positiva."""
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as db:
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
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as db:
        db.execute("""
            INSERT INTO ruptura_inventario (guild_id, user_id, item_key, quantidade)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_key)
            DO UPDATE SET quantidade = quantidade + excluded.quantidade
        """, (guild_id, user_id, chave, quantidade))
        db.commit()


def guardar_item_tx(
    db: sqlite3.Connection, guild_id: int, user_id: int,
    chave: str, quantidade: int = 1,
) -> None:
    """Versão de guardar_item() para uma transação aberta pela economia."""
    if quantidade <= 0:
        raise ValueError("A quantidade precisa ser positiva.")
    db.execute("""
        INSERT INTO ruptura_inventario (guild_id, user_id, item_key, quantidade)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, item_key)
        DO UPDATE SET quantidade = quantidade + excluded.quantidade
    """, (guild_id, user_id, chave, quantidade))


def consumir_item_tx(
    db: sqlite3.Connection, guild_id: int, user_id: int,
    chave: str, quantidade: int = 1,
) -> bool:
    """Consome estoque dentro de uma transação já aberta (sem COMMIT)."""
    row = db.execute("""
        SELECT quantidade FROM ruptura_inventario
        WHERE guild_id = ? AND user_id = ? AND item_key = ?
    """, (guild_id, user_id, chave)).fetchone()
    if row is None or row[0] < quantidade:
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
    return True


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


def criar_inimigo(
    nivel: int, evento: "EventoSpec | None" = None,
    categoria: str | None = None,
) -> EnemyState:
    """
    Escolhe um inimigo do tipo correto e aplica escala moderada.

    Criaturas com 'evento' preenchido só existem durante esse evento. O
    evento ainda pode favorecer uma era e trazer exclusivas (chance própria).
    ``categoria`` permite reaproveitar o sorteio já feito pelo mercador,
    evitando que o deus seja sorteado duas vezes.
    """
    categoria = categoria or categoria_encontro(nivel)
    chave_evento = evento.chave if evento else ""
    base = [c for c in CRIATURAS if c.evento in ("", chave_evento)]
    disponiveis = [c for c in base if c.categoria == categoria]

    if not disponiveis:
        categoria = "normal"
        disponiveis = [c for c in base if c.categoria == "normal"]

    elegiveis = [c for c in disponiveis if c.nivel_minimo <= nivel]
    if elegiveis:
        recentes = [c for c in elegiveis if c.nivel_minimo >= nivel - 6]
        pool = recentes or elegiveis
        if evento is not None:
            exclusivas = [c for c in pool if c.evento == evento.chave]
            if exclusivas and random.random() < evento.chance_exclusiva:
                pool = exclusivas
            elif evento.era_favorita and random.random() < evento.chance_era:
                favoritas = [c for c in pool if c.era == evento.era_favorita]
                pool = favoritas or pool
        spec = random.choice(pool)
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


# ------------------------------------------------------------
# EVENTOS TEMPORAIS (com efeitos reais)
# ------------------------------------------------------------
# Um evento é sorteado no início de um encontro e dura 'duracao'
# encontros. Ele NÃO é só texto: cada chave de 'efeitos' altera o jogo.
#
#   Lado da criatura (aplicado 1x ao gerar o inimigo; chefes e deuses
#   sentem só parte, veja FATOR_EVENTO_CATEGORIA):
#     inimigo_atq_pct   +% de ataque          inimigo_vida_pct  +% de vida
#     inimigo_def       +defesa
#   Lado do jogador (vale enquanto o evento durar):
#     crit      +pontos de chance de crítico   dano_pct   +% de dano causado
#     red_pct   -% de dano recebido
#     foco      +Foco ao iniciar o combate     cura_pct   cura % da vida máx.
#     barreira  +barreira ao iniciar o combate (respeita o teto da build)
#   Recompensas:
#     xp_pct        +% de XP por criatura
#     moeda_chance  +pontos percentuais na chance de Abysmus (máx. +10,
#                   o Abysmus continua raro)
#
# Além dos números, um evento pode: favorecer uma ERA (era_favorita +
# chance_era) e trazer CRIATURAS EXCLUSIVAS (EnemySpec.evento == chave do
# evento; aparecem com chance_exclusiva em encontros comuns).
# Para criar um evento novo, copie um registrar_evento(...) abaixo.

ERAS = ("Da'kor", "Era a Vapor", "Futuro Distorcido")

# Limite de cada efeito (o registro recusa valores acima).
CAPS_EVENTO = {
    "inimigo_atq_pct": 30, "inimigo_vida_pct": 30, "inimigo_def": 3,
    "crit": 15, "dano_pct": 20, "red_pct": 15, "foco": 1, "cura_pct": 15,
    "barreira": 15, "xp_pct": 50, "moeda_chance": 10,
}
# Quanto de cada efeito "do lado da criatura" cada categoria sente.
FATOR_EVENTO_CATEGORIA = {
    "normal": 1.0, "mini_chefe": 0.75, "chefe": 0.5, "deus": 0.25,
}

_TEXTO_EVENTO = {
    "inimigo_atq_pct": lambda v: f"criaturas causam +{v:g}% de dano",
    "inimigo_vida_pct": lambda v: f"criaturas têm +{v:g}% de vida",
    "inimigo_def": lambda v: f"criaturas têm +{v:g} de defesa",
    "crit": lambda v: f"você tem +{v:g}% de chance de crítico",
    "dano_pct": lambda v: f"você causa +{v:g}% de dano",
    "red_pct": lambda v: f"você sofre -{v:g}% de dano",
    "foco": lambda v: f"+{v:g} Foco ao iniciar cada combate",
    "cura_pct": lambda v: f"você recupera {v:g}% da vida ao iniciar cada combate",
    "barreira": lambda v: f"você começa o combate com +{v:g} de barreira",
    "xp_pct": lambda v: f"+{v:g}% de XP",
    "moeda_chance": lambda v: f"+{v:g} pontos de chance de Abysmus",
}


@dataclass(frozen=True)
class EscolhaEvento:
    """Uma escolha de evento dinâmico, com efeito imediato na run."""
    rotulo: str
    descricao: str
    aplicar: Callable[["RunState"], str]


@dataclass(frozen=True)
class EventoSpec:
    """Evento ambiental expansível, com efeitos reais no combate."""
    chave: str
    nome: str
    descricao: str
    chance: float = 0.03
    periodo: str = "sempre"  # sempre, halloween, natal, equinocio...
    efeitos: tuple[tuple[str, float], ...] = ()
    duracao: int = 1                 # encontros que o evento dura
    era_favorita: str = ""           # favorece criaturas desta era
    chance_era: float = 0.7          # chance de o favorecimento valer
    chance_exclusiva: float = 0.0    # chance de surgir criatura exclusiva
    dinamico: bool = False           # só aparece em encontros de nível 4+
    escolhas: tuple[EscolhaEvento, ...] = ()


EVENTOS: dict[str, EventoSpec] = {}

# Janelas sazonais. Cada item é uma lista de pares (início, fim), no
# formato (mês, dia). Janelas que viram o ano são aceitas (início > fim).
JANELAS_SAZONAIS = {
    "halloween": (((10, 20), (11, 2)),),
    "natal": (((12, 15), (1, 5)),),
    "equinocio": (((3, 18), (3, 25)), ((9, 18), (9, 25))),
    "solsticio": (((6, 18), (6, 25)),),
    "colheita": (((4, 10), (4, 30)),),
    "mortos": (((11, 3), (11, 10)),),
}


def registrar_evento(evento: EventoSpec) -> EventoSpec:
    """Registra um evento validando chance, duração e efeitos."""
    if not 0 <= evento.chance <= 1:
        raise ValueError("A chance do evento deve estar entre 0 e 1.")
    if evento.duracao < 1:
        raise ValueError("A duração do evento deve ser de pelo menos 1 encontro.")
    if evento.era_favorita and evento.era_favorita not in ERAS:
        raise ValueError(f"Era desconhecida: {evento.era_favorita}")
    for chave, valor in evento.efeitos:
        if chave not in CAPS_EVENTO:
            raise ValueError(f"Efeito de evento desconhecido: {chave}")
        if not 0 < valor <= CAPS_EVENTO[chave]:
            raise ValueError(
                f"{chave}: o valor deve estar entre 0 e {CAPS_EVENTO[chave]}.")
    if evento.periodo not in ("sempre", *JANELAS_SAZONAIS):
        raise ValueError(f"Período sazonal desconhecido: {evento.periodo}")
    if evento.escolhas:
        if len(evento.escolhas) < 2:
            raise ValueError("Evento com escolhas precisa de ao menos 2 opções.")
        if not all(callable(e.aplicar) for e in evento.escolhas):
            raise ValueError("Toda escolha de evento precisa de aplicar().")
    EVENTOS[evento.chave] = evento
    return evento


def texto_evento(evento: EventoSpec) -> str:
    """Resumo legível dos efeitos (usado no aviso e no embed da run)."""
    partes = [_TEXTO_EVENTO[c](v) for c, v in evento.efeitos]
    if evento.era_favorita:
        partes.append(f"favorece criaturas de {evento.era_favorita}")
    if evento.chance_exclusiva:
        partes.append("criaturas exclusivas podem surgir")
    if evento.escolhas:
        partes.append("uma escolha se abre")
    return "; ".join(partes) or "sem efeitos"


registrar_evento(EventoSpec(
    "lua_sangrenta", "Lua Sangrenta",
    "A lua se abre como uma ferida sobre Da'kor. A névoa fica vermelha.",
    0.035, duracao=2, era_favorita="Da'kor", chance_era=0.6,
    efeitos=(("inimigo_atq_pct", 15), ("crit", 8), ("xp_pct", 30),
             ("moeda_chance", 5)),
))
registrar_evento(EventoSpec(
    "mare_de_fuligem", "Maré de Fuligem",
    "As chaminés de uma era que ainda não terminou cospem cinzas sobre a névoa.",
    0.03, duracao=2, era_favorita="Era a Vapor", chance_era=0.7,
    efeitos=(("inimigo_def", 2), ("barreira", 8), ("xp_pct", 20)),
))
registrar_evento(EventoSpec(
    "noite_alien", "Noite Alienígena",
    "Luzes desconhecidas atravessam o céu e desaparecem dentro da névoa.",
    0.025, era_favorita="Futuro Distorcido", chance_era=0.7,
    efeitos=(("foco", 1), ("inimigo_vida_pct", 10), ("xp_pct", 20)),
))
registrar_evento(EventoSpec(
    "halloween", "Vigília de Halloween",
    "Vozes mascaradas ecoam entre as árvores. Só surge entre 20 de outubro e 2 de novembro.",
    0.08, "halloween", chance_exclusiva=0.5,
    efeitos=(("xp_pct", 25), ("moeda_chance", 8), ("dano_pct", 5)),
))
registrar_evento(EventoSpec(
    "natal", "Natal em Da'kor",
    "Pequenas luzes surgem na névoa, embora não exista nenhuma casa por perto. Só surge entre 15 de dezembro e 5 de janeiro.",
    0.08, "natal", chance_exclusiva=0.5,
    efeitos=(("cura_pct", 12), ("foco", 1), ("inimigo_atq_pct", 10)),
))

# ---------- eventos sazonais adicionais ----------
# As janelas são independentes das de Halloween/Natal: fora delas esses
# eventos nem entram no sorteio, então não diluem os eventos base.
registrar_evento(EventoSpec(
    "equinocio_de_cinzas", "Equinócio de Cinzas",
    "O dia e a noite se igualam, e a névoa devolve cinzas de um mundo paralelo. "
    "Surge entre 18 e 25 de março e entre 18 e 25 de setembro.",
    0.04, "equinocio", duracao=2, era_favorita="Da'kor", chance_era=0.6,
    efeitos=(("crit", 8), ("red_pct", 8), ("xp_pct", 25),
             ("inimigo_atq_pct", 10)),
))
registrar_evento(EventoSpec(
    "solsticio_rachado", "Solstício Rachado",
    "O dia mais longo racha ao meio e o futuro vaza pela fenda. "
    "Surge entre 18 e 25 de junho.",
    0.04, "solsticio", duracao=2, era_favorita="Futuro Distorcido",
    chance_era=0.7,
    efeitos=(("foco", 1), ("dano_pct", 12), ("inimigo_vida_pct", 10),
             ("xp_pct", 20)),
))
registrar_evento(EventoSpec(
    "colheita_de_ecos", "Colheita de Ecos",
    "O que foi plantado em outras linhas do tempo amadurece de uma vez. "
    "Surge entre 10 e 30 de abril.",
    0.045, "colheita", duracao=2, era_favorita="Era a Vapor", chance_era=0.7,
    chance_exclusiva=0.5,
    efeitos=(("cura_pct", 10), ("xp_pct", 30), ("moeda_chance", 4)),
))
registrar_evento(EventoSpec(
    "semana_dos_mortos", "Semana dos Mortos",
    "Depois da vigília, os nomes dos que ficaram na névoa voltam para cobrar "
    "presença. Surge entre 3 e 10 de novembro.",
    0.045, "mortos", duracao=2, era_favorita="Da'kor", chance_era=0.6,
    chance_exclusiva=0.5,
    efeitos=(("crit", 10), ("dano_pct", 10), ("inimigo_def", 2),
             ("xp_pct", 20)),
))


# ---------- eventos dinâmicos com escolhas ----------
# Eles só entram quando nenhum evento normal foi sorteado e o encontro é
# de nível 4+. Assim, não reduzem a chance dos eventos já existentes.

def _escolha_mercador_agua(run: RunState) -> str:
    cura = run.curar(max(1, int(run.vida_maxima * 0.30)))
    return f"💧 A água é gelada e limpa: você recupera {cura} de vida."


def _escolha_mercador_memoria(run: RunState) -> str:
    run.ataque += 2
    run.vida_maxima = max(1, run.vida_maxima - 6)
    run.vida = min(run.vida, run.vida_maxima)
    return ("🧠 Você entrega uma lembrança: +2 de ataque permanente, "
            "-6 de vida máxima.")


def _escolha_fenda_atravessar(run: RunState) -> str:
    ganho = run.ganhar_foco(2)
    return f"🌀 Você atravessa a fenda e volta com +{ganho} Foco."


def _escolha_fenda_contornar(run: RunState) -> str:
    cura = run.curar(max(1, int(run.vida_maxima * 0.20)))
    run.barreira = min(run.vida_maxima, run.barreira + 8)
    return f"🛤️ O desvio é seguro: +{cura} de vida e +8 de barreira."


def _escolha_voz_responder(run: RunState) -> str:
    if random.random() < 0.5:
        run.ataque += 3
        return "🗣️ A voz aceita sua resposta: +3 de ataque permanente."
    dano = min(max(1, int(run.vida_maxima * 0.10)), max(0, run.vida - 1))
    run.vida -= dano
    return f"🗣️ A voz morde de volta: você perde {dano} de vida."


def _escolha_voz_silenciar(run: RunState) -> str:
    run.defesa += 2
    return "🤐 Você silencia a voz: +2 de defesa permanente."


registrar_evento(EventoSpec(
    "mercador_do_intervalo", "Mercador do Intervalo",
    "Entre dois segundos, uma barraca existe. O mercador não tem rosto, "
    "mas tem sede de histórias.",
    0.06, dinamico=True,
    escolhas=(
        EscolhaEvento("Aceitar a água", "Recupera 30% da vida máxima.",
                      _escolha_mercador_agua),
        EscolhaEvento("Trocar uma memória",
                      "+2 de ataque permanente, -6 de vida máxima.",
                      _escolha_mercador_memoria),
    ),
))
registrar_evento(EventoSpec(
    "fenda_de_dois_caminhos", "Fenda de Dois Caminhos",
    "A névoa se abre em duas direções ao mesmo tempo. As duas levam ao "
    "mesmo lugar, mas só uma lembra de você.",
    0.05, dinamico=True,
    escolhas=(
        EscolhaEvento("Atravessar a fenda", "Ganha +2 Foco imediatamente.",
                      _escolha_fenda_atravessar),
        EscolhaEvento("Contornar pelo desvio",
                      "Cura 20% da vida e ganha +8 de barreira.",
                      _escolha_fenda_contornar),
    ),
))
registrar_evento(EventoSpec(
    "voz_na_nevoa", "Voz na Névoa",
    "Alguém chama pelo seu nome com a sua própria voz. A névoa espera.",
    0.05, dinamico=True,
    escolhas=(
        EscolhaEvento("Responder à voz",
                      "50%: +3 de ataque permanente; 50%: perde 10% da vida.",
                      _escolha_voz_responder),
        EscolhaEvento("Silenciar a voz", "+2 de defesa permanente.",
                      _escolha_voz_silenciar),
    ),
))


def evento_disponivel(evento: EventoSpec, hoje: date | None = None) -> bool:
    """Restringe eventos sazonais às suas janelas (mês/dia)."""
    if evento.periodo == "sempre":
        return True
    hoje = hoje or date.today()
    atual = (hoje.month, hoje.day)
    for inicio, fim in JANELAS_SAZONAIS.get(evento.periodo, ()):
        if inicio <= fim:
            if inicio <= atual <= fim:
                return True
        elif atual >= inicio or atual <= fim:   # janela que vira o ano
            return True
    return False


def sortear_evento(run: RunState | None = None) -> EventoSpec | None:
    """Sorteia no máximo um evento por encontro.

    Os eventos dinâmicos só são considerados se nenhum evento normal saiu
    e a run já chegou ao nível 4; assim os eventos base não são diluídos.
    """
    disponiveis = [e for e in EVENTOS.values()
                   if not e.dinamico and evento_disponivel(e)]
    random.shuffle(disponiveis)
    for evento in disponiveis:
        if random.random() < evento.chance:
            return evento
    if run is None or run.nivel < 4:
        return None
    dinamicos = [e for e in EVENTOS.values()
                 if e.dinamico and e.escolhas
                 and e.chave not in run.eventos_dinamicos]
    random.shuffle(dinamicos)
    for evento in dinamicos:
        if random.random() < evento.chance:
            run.eventos_dinamicos.add(evento.chave)
            return evento
    return None


def aplicar_evento_inimigo(evento: EventoSpec, inimigo: "EnemyState") -> None:
    """Aplica 1x os efeitos do evento à criatura (chefes sentem menos)."""
    fator = FATOR_EVENTO_CATEGORIA.get(inimigo.spec.categoria, 1.0)
    for chave, valor in evento.efeitos:
        if chave == "inimigo_atq_pct":
            inimigo.ataque = max(1, int(inimigo.ataque * (1 + valor * fator / 100)))
        elif chave == "inimigo_vida_pct":
            vida = max(1, int(inimigo.vida_maxima * (1 + valor * fator / 100)))
            inimigo.vida = inimigo.vida_maxima = vida
        elif chave == "inimigo_def":
            inimigo.defesa += int(round(valor * fator))


def bonus_evento(run: "RunState") -> tuple[float, float]:
    """(xp_pct, moeda_pontos) do evento ativo; (0, 0) sem evento."""
    if run.evento_ativo is None:
        return 0.0, 0.0
    efeitos = dict(run.evento_ativo.efeitos)
    return efeitos.get("xp_pct", 0.0), efeitos.get("moeda_chance", 0.0)


class EfeitoEvento(Efeito):
    """Parte do evento que atua no JOGADOR, pelos mesmos hooks do motor."""

    nome = "Evento"
    descricao = "Efeitos do evento temporal em andamento."

    def __init__(self, evento: EventoSpec):
        self.evento = evento
        self.v = dict(evento.efeitos)

    def bonus_critico(self, run) -> int:
        return int(self.v.get("crit", 0))

    def modificar_dano_causado(self, run, ataque) -> int:
        pct = self.v.get("dano_pct", 0)
        return int(ataque.dano * (1 + pct / 100)) if pct else ataque.dano

    def modificar_dano_recebido(self, run, dano: int) -> int:
        red = self.v.get("red_pct", 0)
        if red and dano > 0:
            return max(1, int(dano * (1 - red / 100)))
        return dano

    def ao_iniciar_combate(self, run, inimigo) -> None:
        foco = int(self.v.get("foco", 0))
        if foco and run.ganhar_foco(foco):
            run.log.append(f"🌌 {self.evento.nome}: +{foco} Foco.")
        cura = self.v.get("cura_pct", 0)
        if cura:
            real = run.curar(max(1, int(run.vida_maxima * cura / 100)))
            if real:
                run.log.append(f"🌌 {self.evento.nome}: você recupera {real} de vida.")
        barreira = int(self.v.get("barreira", 0))
        if barreira:
            ganho = adicionar_barreira(run, barreira)
            if ganho:
                run.log.append(f"🌌 {self.evento.nome}: +{ganho} de barreira.")


def validar_eventos() -> list[str]:
    """Confere eventos e criaturas exclusivas (roda ao carregar o cog)."""
    problemas = []
    for evento in EVENTOS.values():
        exclusivas = [c for c in CRIATURAS if c.evento == evento.chave]
        if evento.chance_exclusiva and not exclusivas:
            problemas.append(f"Evento '{evento.chave}' prevê exclusivas, mas não há criaturas.")
        if evento.era_favorita and not any(
                c.era == evento.era_favorita and c.categoria == "normal"
                for c in CRIATURAS):
            problemas.append(f"Evento '{evento.chave}': era sem criaturas comuns.")
    for criatura in CRIATURAS:
        if criatura.evento and criatura.evento not in EVENTOS:
            problemas.append(f"Criatura '{criatura.nome}' usa evento inexistente '{criatura.evento}'.")
        if criatura.era not in ERAS + ("Além da Névoa",):
            problemas.append(f"Criatura '{criatura.nome}': era desconhecida '{criatura.era}'.")
    return problemas


def preparar_combate(run: RunState, categoria: str | None = None) -> None:
    """Sorteia o evento, gera a próxima criatura e dispara os hooks."""
    # Evento: continua o atual (duracao > 1) ou sorteia um novo.
    anuncio = ""
    if run.evento_ativo is not None and run.evento_restante > 0:
        run.evento_restante -= 1
        anuncio = "continua"
    else:
        run.evento_ativo = sortear_evento(run)
        run.evento_restante = (run.evento_ativo.duracao - 1
                               if run.evento_ativo else 0)
        anuncio = "novo" if run.evento_ativo else ""
        run.evento_escolha_feita = False
    evento = run.evento_ativo
    run.evento_efeito = EfeitoEvento(evento) if evento else None

    categoria = categoria or run.categoria_pendente or None
    run.categoria_pendente = ""
    run.inimigo = criar_inimigo(run.nivel, evento, categoria=categoria)
    inimigo = run.inimigo
    if evento is not None:
        aplicar_evento_inimigo(evento, inimigo)

    # Estado de combate zerado: cada luta começa limpa e previsível.
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
    run.ataque_bonus = 0

    ganho = run.ganhar_foco(FOCO_POR_COMBATE + run.foco_por_combate)
    if ganho > 0:
        run.log.append(f"⚡ +{ganho} Foco ao encarar a criatura.")

    if run.barreira < run.barreira_inicial:
        run.barreira = run.barreira_inicial
        run.log.append(
            f"🛡️ Seus itens formam {run.barreira_inicial} de barreira."
        )

    if evento is not None:
        if anuncio == "novo":
            run.log.append(
                f"🌌 **EVENTO: {evento.nome}** — {evento.descricao}\n"
                f"↳ Efeitos: {texto_evento(evento)}.")
        else:
            run.log.append(f"🌌 O evento **{evento.nome}** continua.")
        if evento.escolhas and not run.evento_escolha_feita:
            run.log.append("🌌 Uma escolha se abre: use o botão **Evento**.")
        run.evento(f"Evento temporal ({anuncio}): {evento.nome} | "
                   f"restam {run.evento_restante} encontro(s) | {texto_evento(evento)}")

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
    run.ignorou_defesa = ignora_defesa
    if inimigo is None or inimigo.vida <= 0:
        return 0

    ataque_base = max(1, run.ataque + run.ataque_bonus)

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
        dano = int(dano * run.mult_critico()) + random.randint(1, 3)
        run.log.append(
            "💥 GOLPE CRÍTICO! O golpe atravessa uma falha na realidade."
        )

    ataque = Ataque(dano=dano, critico=critico, chance_critico=chance)
    for efeito in run.efeitos():
        ataque.dano = efeito.modificar_dano_causado(run, ataque)

    # Marca da build: o alvo marcado sofre mais com cada golpe.
    if inimigo.marca > 0:
        ataque.dano = int(ataque.dano * (1 + MARCA_PCT / 100))
        inimigo.marca -= 1
        run.log.append(f"🎯 O alvo marcado sofre +{MARCA_PCT}% de dano.")

    dano_final = inimigo.habilidade.reduzir_dano_recebido(
        run, inimigo, max(1, ataque.dano)
    )
    if inimigo.protecao > 0:
        dano_final = max(1, int(dano_final * 0.5))
        run.log.append(
            "🛡️ A postura defensiva do inimigo absorve metade do golpe."
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
    run.esquivou_agora = False
    if run.esquiva:
        run.esquiva = False
        run.log.append(
            "🌀 Você some entre as fendas e o golpe atravessa o vazio!"
        )
        return 0

    penetracao = inimigo.habilidade.penetracao_defesa(run, inimigo)
    defesa = max(0, run.defesa - penetracao)

    dano_original = dano
    for efeito in run.efeitos():
        dano = efeito.modificar_dano_recebido(run, dano)
    if dano_original > 0 and dano <= 0:
        run.esquivou_agora = True      # alguma passiva/build esquivou

    if run.guarda and dano > 0:
        dano = max(1, int(dano * run.fator_guarda))
        run.log.append(
            "🛡️ Sua guarda reduz o golpe pela metade."
            if run.fator_guarda >= 0.5 else
            f"🛡️ Sua guarda reduz o golpe em {int((1 - run.fator_guarda) * 100)}%.")

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

    for efeito in run.efeitos():
        efeito.ao_golpe_recebido(run, inimigo, perdida)
    verificar_morte(run)
    return perdida


def verificar_morte(run: RunState) -> None:
    """Dá aos efeitos (ex.: último fôlego) a chance de evitar a derrota."""
    if run.vida <= 0:
        for efeito in run.efeitos():
            if efeito.ao_morte(run):
                break


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

    verificar_morte(run)


# ------------------------------------------------------------
# COMBATE TÁTICO: AÇÕES TELEGRAFADAS E MEMÓRIA DE CHEFE
# ------------------------------------------------------------
# As ações abaixo NÃO mudam atributos, dano base, escalas, chances ou
# recompensas. Elas apenas trocam a decisão do chefe naquele turno, e o
# jogador recebe um turno de aviso para reagir com Guarda ou atordoamento.

GOLPE_PESADO = AcaoInimiga(
    "golpe_pesado", "Golpe Pesado",
    "Ataque telegrafado: causa +55% se não for interrompido.",
    prepara=True, interrompivel=True, dano_pct=1.55,
)
POSTURA_DEFENSIVA = AcaoInimiga(
    "postura_defensiva", "Postura Defensiva",
    "Assume postura: reduz pela metade o próximo golpe recebido.",
    tipo="defesa",
)
CONTRA_GOLPE = AcaoInimiga(
    "contra_golpe", "Contra-Golpe",
    "Responde à pressão com um golpe rápido (+30%).",
    dano_pct=1.3,
)

# Como cada padrão do jogador é respondido (uma única vez por chefe).
CONTRA_PADRAO = {
    "atacar": POSTURA_DEFENSIVA,
    "guardar": GOLPE_PESADO,
    "concentrar": GOLPE_PESADO,
    "tecnica": CONTRA_GOLPE,
    "ativa": CONTRA_GOLPE,
    "item": GOLPE_PESADO,
}


def _aplicar_postura_defensiva(run: RunState, inimigo: EnemyState) -> str:
    inimigo.protecao = 1
    return (f"🛡️ {inimigo.spec.nome} assume uma postura defensiva. "
            "O próximo golpe causa metade do dano.")


def selecionar_acao_chefe(run: RunState, inimigo: EnemyState) -> Optional[AcaoInimiga]:
    """Decisão tática de chefe/deus conforme estado e memória do combate."""
    if inimigo.spec.categoria not in ("chefe", "deus"):
        return None

    padrao = inimigo.memoria.padrao_detectado()
    if padrao and not inimigo.memoria.adaptado:
        acao = CONTRA_PADRAO.get(padrao, GOLPE_PESADO)
        inimigo.memoria.adaptado = True
        inimigo.memoria.padrao = padrao
        run.log.append(
            f"🧠 {inimigo.spec.nome} aprendeu seu padrão "
            f"(**{padrao}**) e prepara **{acao.nome}**."
        )
        run.evento(f"Chefe {inimigo.spec.nome} adaptou-se ao padrão {padrao}.")
        return acao

    # Sem padrão dominante: a cada 3 turnos, um golpe telegrafado.
    if inimigo.turnos % 3 == 0:
        return GOLPE_PESADO
    return None


def escolher_acao_chefe(run: RunState, inimigo: EnemyState) -> Optional[AcaoInimiga]:
    """Alias público usado pelo hook padrão de HabilidadeInimiga."""
    return selecionar_acao_chefe(run, inimigo)


def registrar_acao_jogador(run: RunState, chave: str) -> None:
    """Registra a última ação do jogador na memória do chefe atual."""
    inimigo = run.inimigo
    if inimigo is None or inimigo.vida <= 0:
        return
    if inimigo.spec.categoria not in ("chefe", "deus"):
        return
    inimigo.memoria.registrar(chave)


def preparar_acao_inimiga(
    run: RunState, inimigo: EnemyState, acao: AcaoInimiga
) -> None:
    """Telegrafa uma ação; ela resolve no próximo turno da criatura."""
    inimigo.acao_pendente = acao
    run.log.append(
        f"⚠️ **{inimigo.spec.nome} prepara {acao.nome}.** "
        f"{acao.descricao} Guarde ou atordoe para interromper."
    )
    run.evento(f"Ação telegrafada: {acao.chave} ({acao.nome}).")


def interromper_acao_inimiga(
    run: RunState, inimigo: EnemyState, motivo: str
) -> bool:
    """Cancela a ação pendente sem dano. Retorna True se havia o que cancelar."""
    acao = inimigo.acao_pendente
    if acao is None:
        return False
    inimigo.acao_pendente = None
    run.log.append(
        f"🛑 A ação **{acao.nome}** de {inimigo.spec.nome} foi "
        f"interrompida ({motivo})."
    )
    run.evento(f"Ação interrompida: {acao.chave} | motivo={motivo}.")
    return True


def expirar_efeitos_inimigo(run: RunState, inimigo: EnemyState) -> None:
    """Expira proteções temporárias no início do turno da criatura."""
    if inimigo.protecao > 0:
        inimigo.protecao -= 1
        if inimigo.protecao == 0:
            run.log.append(
                f"🛡️ A postura defensiva de {inimigo.spec.nome} termina."
            )


def _golpe_inimigo(
    run: RunState, inimigo: EnemyState,
    dano_pct: float = 1.0, rotulo: str = "ataca",
) -> int:
    """Golpe do inimigo (básico ou tático), com os mesmos modificadores."""
    spec = inimigo.spec
    dano = inimigo.ataque + random.randint(-3, 2)
    if dano_pct != 1.0:
        dano = max(1, int(dano * dano_pct))
    dano = inimigo.habilidade.modificar_ataque(run, inimigo, dano)

    if inimigo.fraqueza > 0:
        corte = FRAQUEZA_PCT / (2 if spec.categoria in ("chefe", "deus") else 1)
        dano = int(dano * (1 - corte / 100))
        inimigo.fraqueza -= 1
        run.log.append(f"📉 {spec.nome} está enfraquecida (-{corte:g}% de dano).")

    perdida = receber_dano(run, inimigo, max(1, dano))
    run.log.append(
        f"{spec.nome} {rotulo} e causa {perdida} de dano após suas defesas."
    )
    inimigo.habilidade.apos_golpe(run, inimigo, perdida)
    return perdida


def resolver_acao_inimiga(
    run: RunState, inimigo: EnemyState, acao: AcaoInimiga
) -> None:
    """Executa a ação pendente. Ação interrompível só chega aqui se o
    jogador não a cancelou."""
    if acao.aplicar is not None:
        mensagem = acao.aplicar(run, inimigo)
        if mensagem:
            run.log.append(mensagem)
        return
    _golpe_inimigo(
        run, inimigo, acao.dano_pct, rotulo=f"usa **{acao.nome}**"
    )


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

    processar_dots_inimigo(run, inimigo)   # veneno e sangria (build)
    if inimigo.vida <= 0:
        return

    expirar_efeitos_inimigo(run, inimigo)

    if inimigo.atordoado:
        inimigo.atordoado = False
        interromper_acao_inimiga(run, inimigo, "atordoamento")
        run.log.append(f"💫 {spec.nome} está atordoada e perde o turno.")
        run.guarda = False
        processar_status_jogador(run)
        return

    # Ação pendente tem prioridade: ela foi telegrafada no turno anterior.
    if inimigo.acao_pendente is not None:
        acao = inimigo.acao_pendente
        if run.guarda and acao.interrompivel:
            interromper_acao_inimiga(run, inimigo, "sua Guarda")
            run.guarda = False
            processar_status_jogador(run)
            return
        inimigo.acao_pendente = None
        resolver_acao_inimiga(run, inimigo, acao)
        run.guarda = False
        processar_status_jogador(run)
        return

    # Habilidades antigas continuam tendo prioridade (regenerar, marcar...).
    if inimigo.habilidade.ao_turno(run, inimigo):
        run.guarda = False
        processar_status_jogador(run)
        return

    acao = inimigo.habilidade.escolher_acao(run, inimigo)
    if acao is not None:
        if acao.prepara:
            preparar_acao_inimiga(run, inimigo, acao)
        else:
            resolver_acao_inimiga(run, inimigo, acao)
        run.guarda = False
        processar_status_jogador(run)
        return

    _golpe_inimigo(run, inimigo)
    run.guarda = False
    processar_status_jogador(run)


# ============================================================
# 7B. BUILDS — ÁRVORES DE ESPECIALIZAÇÃO (gastam Abysmus)
# ============================================================
#
# VISÃO GERAL
# -----------
# Cada classe tem 3 especializações; cada especialização tem 5 nós:
#
#     n1 habilidade inicial ──► n2 aprimoramento (2 níveis) ──┐
#        └────────────────────► n3 nova habilidade ► n4 mod. ─┴► n5 suprema
#
# * Os nós custam ABYSMUS (a moeda rara do XpAndCoins). Cada nó exige
#   um nível mínimo de conta e os pré-requisitos do desenho acima.
# * A especialização é escolhida no nível 3 (grátis; pode trocar enquanto
#   não comprar nenhum nó). Cada classe tem a sua própria build.
# * /build_resetar devolve os PONTOS gastos (como pontos de build, que
#   pagam os próximos nós antes do seu saldo) mediante a taxa
#   CUSTO_RESET_ABYSMUS. Nada é reembolsado em Abysmus.
# * O banco é a fonte oficial: a run lê os nós do banco ao começar.
#
# EFEITOS EM DADOS
# ----------------
# Cada nó é DADOS (NoSpec): uma lista de pares (chave, valor) e, para
# habilidades ativas, um AtivaSpec. O motor (EfeitoBuild + executar_ativa)
# interpreta as chaves nos pontos certos do ciclo de combate. Para criar
# conteúdo novo basta registrar_especializacao(...) usando chaves que já
# existem em CHAVES_BASE; só uma chave NOVA exige código.
#
# ORDEM DE APLICAÇÃO DO DANO CAUSADO (cada ataque)
# ------------------------------------------------
#   1. dano base do jogo (ataque, variação, defesa inimiga, mult)
#   2. crítico (chance base + itens + passiva + build; mult. 1,8 + build)
#   3. passiva da CLASSE e relíquias (hooks originais, na ordem original)
#   4. EfeitoBuild: soma das regras condicionais (limite global +100%),
#      depois bônus fixos (defesa, barreira, perfuração)
#   5. marca no inimigo (+25%) e habilidade defensiva da criatura
#   6. dano aplicado -> hooks "ao causar dano" (status, foco, barreira,
#      eco, roubo de vida do Vampiro)
# Bônus da classe e da build entram UMA vez cada: a build nunca repete
# o que a passiva já faz (ela só modifica os parâmetros da passiva).
#
# REGRAS DE EQUILÍBRIO (todas configuráveis abaixo)
# -------------------------------------------------
#   * Esquiva da build: máx. 15% e nunca em dois golpes seguidos.
#   * Cura da build: no máximo 30% da vida máxima por combate.
#   * Barreira da build: gatilhos até 35% da vida máx. por combate e o
#     total nunca passa de 50% da vida máx. (não acumula pela run toda).
#   * Combo: no máximo 5 acúmulos, zera ao ser atingido.
#   * Não existe turno extra: ecos e paradoxo são golpes de fim de turno
#     que não se repetem; invocações duram 3 turnos e há no máximo 2.
#   * Chefes e deuses são imunes a atordoamento; deuses ignoram veneno e
#     sangria; mini-chefes só são atordoados uma vez por combate.
#   * Roubo de vida: SOMENTE no Vampiro (o registro recusa o contrário).
#
# Os nomes e textos das habilidades são EXPANSÃO SUGERIDA para SFA, ainda
# não estabelecida no cânone da Bíblia do Universo.

# ---------- configuração ----------

CUSTO_RESET_ABYSMUS = 100        # taxa do /build_resetar
ESCALA_CUSTO_BUILD = 1.0         # multiplica todos os custos de nós
NIVEL_ESPECIALIZACAO = 3         # nível de conta para escolher especialização

# Modelo dos 5 nós de TODA especialização (ordem: custo, nível, req, ranks).
MODELO_NOS = {
    1: dict(custo=3, nivel=5, req=(), rank=1),
    2: dict(custo=4, nivel=8, req=(1,), rank=2),
    3: dict(custo=5, nivel=12, req=(1,), rank=1),
    4: dict(custo=7, nivel=16, req=(3,), rank=1),
    5: dict(custo=12, nivel=20, req=(2, 4), rank=1),
}

CAP_DANO_PCT = 100               # bônus % máximo somado por golpe

# Botões de ajuste de equilíbrio. São aplicados UMA vez, ao registrar os
# nós, então os textos do /build já mostram os números finais. Mexa aqui
# (e rode a simulação de equilíbrio) em vez de editar nó por nó.
ESCALA_OFENSIVA = 1.8            # dano, crítico, perfuração, ecos, combos...
ESCALA_DEFENSIVA = 0.5           # redução, barreira, cura, esquiva, espinhos...
ESCALA_ATIVAS = 1.25              # multiplicador de dano das habilidades ativas
CHAVES_OFENSIVAS = ("dano_se:", "dano_def", "dano_barr", "dano_falta",
                    "combo", "crit", "crit_mult", "perf", "tec_extra", "eco",
                    "paradoxo", "aposta", "prep", "invoc", "acerto_foco",
                    "alq_carga")
CHAVES_DEFENSIVAS = ("red", "red_flat", "esq", "barr_golpe", "barr_ini",
                     "regen", "tec_cura", "abate_cura", "conc_bonus",
                     "espinho", "espinho_def", "contra", "acerto_barr",
                     "crit_barr", "tec_barr", "rewind", "roubo",
                     "roubo_barr")
CAP_CURA_COMBATE = 0.30          # fração da vida máx. curável pela build/combate
CAP_BARREIRA_COMBATE = 0.35      # barreira de gatilhos por combate (x vida máx.)
CAP_BARREIRA_TOTAL = 0.50        # a build nunca eleva a barreira acima disto (x vida máx.)
CAP_COMBO = 5
CAP_VENENO = 5
MAX_INVOCACOES = 2
FOLEGO_MAX_RUN = 1               # "último fôlego" no máximo 1x por run
FOLEGO_MAX_COMBATE = 1
CONTRA_MAX_COMBATE = 3
MARCA_PCT = 25                   # dano extra contra alvo marcado
FRAQUEZA_PCT = 20                # redução do ataque do inimigo enfraquecido
EXECUCAO_LIMITE = 0.35           # "exec": bônus extra abaixo disso
EXECUCAO_MULT = 1.5

# Limite do valor SOMADO de cada chave (depois de somar todos os nós).
CAPS = {
    "atq": 6, "def": 4, "vida": 40, "barr_ini": 40, "foco_ini": 1,
    "ciclo": 1, "alq_max": 3, "alq_carga": 3, "alq_queima": 3,
    "guarda_red": 15, "crit": 35, "crit_mult": 60, "crit_foco": 1,
    "crit_barr": 5, "perf": 100, "combo": 12, "dano_falta": 60,
    "dano_def": 100, "dano_barr": 60, "tec_cura": 12, "tec_foco": 35,
    "tec_custo": 1, "tec_barr": 12, "tec_extra": 30, "acerto_barr": 4,
    "acerto_foco": 25, "abate_cura": 20, "abate_foco": 2, "red": 25,
    "red_flat": 4, "esq": 12, "barr_golpe": 5, "espinho": 8,
    "espinho_def": 80, "contra": 30, "folego": 1, "regen": 3,
    "conc_bonus": 60, "rewind": 50, "eco": 40, "paradoxo": 20,
    "aposta": 30, "prep": 60, "roubo": 20, "roubo_barr": 100,
    "foco_guarda": 1, "invoc": 60,
}
CAP_REGRA_DANO = 40              # cada regra dano_se:* individual
CAP_STATUS_CHANCE = 60           # cada st:* / tec_st:* (chance em %)

STATUS = ("queimar", "veneno", "sangria", "marca", "fraco", "atordoar")

# Condições aceitas por "dano_se:<condição>" e o texto de cada uma.
CONDICOES = {
    "critico": "em golpes críticos",
    "tecnica": "com a técnica da classe",
    "basico": "em ataques básicos",
    "ferido": "contra inimigos com 50% de vida ou menos",
    "saudavel": "contra inimigos com 75% de vida ou mais",
    "queimando": "contra inimigos em chamas",
    "envenenado": "contra inimigos envenenados",
    "sangrando": "contra inimigos sangrando",
    "marcado": "contra inimigos marcados",
    "atordoado": "contra inimigos atordoados",
    "debil": "contra inimigos com algum efeito negativo",
    "vida_baixa": "com você abaixo de 40% de vida",
    "vida_cheia": "com você acima de 80% de vida",
    "barreira": "enquanto tiver barreira",
    "guarda": "enquanto estiver em guarda",
    "esquiva": "com a esquiva armada",
    "foco_cheio": "com o Foco cheio",
    "primeiro": "no primeiro golpe do combate",
    "chefe": "contra mini-chefes, chefes e deuses",
}

# Imunidades a efeitos de build (nomes dos status acima).
IMUNIDADES_CATEGORIA = {
    "normal": frozenset(),
    "mini_chefe": frozenset(),
    "chefe": frozenset({"atordoar"}),
    "deus": frozenset({"atordoar", "veneno", "sangria"}),
}
# Criaturas específicas (proposta de lore: máquinas não sangram nem se
# envenenam; a Anomalia Cronófaga devora o tempo e não pode ser "parada").
IMUNIDADES_CRIATURA = {
    "Autômato de Fuligem": frozenset({"veneno", "sangria"}),
    "Cão de Engrenagens": frozenset({"veneno", "sangria"}),
    "Anomalia Cronófaga": frozenset({"atordoar"}),
}
# Quanto do dano contínuo (veneno/sangria) cada categoria sofre.
FATOR_DOT = {"normal": 1.0, "mini_chefe": 0.75, "chefe": 0.5, "deus": 0.0}


# ---------- vocabulário de efeitos (chave -> texto) ----------

def _s(v: float) -> str:
    return f"{v:g}"


_TEXTO_BASE = {
    "atq": lambda v: f"+{_s(v)} de ataque",
    "def": lambda v: f"+{_s(v)} de defesa",
    "vida": lambda v: f"+{_s(v)} de vida máxima",
    "barr_ini": lambda v: f"começa cada combate com ao menos {_s(v)} de barreira",
    "foco_ini": lambda v: f"+{_s(v)} Foco ao iniciar cada combate (máx. +1)",
    "ciclo": lambda v: "sua passiva periódica ativa a cada 2º turno (em vez do 3º)",
    "alq_max": lambda v: f"+{_s(v)} carga máxima de Reação em Cadeia",
    "alq_carga": lambda v: f"+{_s(v)} de dano por carga (+{_s(v * 2)} na Detonação)",
    "alq_queima": lambda v: f"a Detonação queima {_s(v)} turno(s) a mais",
    "guarda_red": lambda v: f"Guardar reduz {_s(v)}% a mais do golpe (mín. 35% passa)",
    "crit": lambda v: f"+{_s(v)}% de chance de crítico",
    "crit_mult": lambda v: f"+{_s(v)}% de dano nos críticos",
    "crit_foco": lambda v: f"crítico dá +{_s(v)} Foco (1× por turno)",
    "crit_barr": lambda v: f"crítico dá {_s(v)} de barreira",
    "perf": lambda v: f"ignora {_s(v)}% da redução de defesa inimiga",
    "combo": lambda v: f"+{_s(v)}% de dano por golpe seguido (até {CAP_COMBO}; zera ao ser atingido)",
    "dano_falta": lambda v: f"até +{_s(v)}% de dano conforme a vida que você perdeu",
    "dano_def": lambda v: f"soma {_s(v)}% da sua defesa ao dano",
    "dano_barr": lambda v: f"soma {_s(v)}% da sua barreira atual ao dano",
    "tec_cura": lambda v: f"a técnica cura {_s(v)}% da vida máxima",
    "tec_foco": lambda v: f"{_s(v)}% de chance de a técnica devolver 1 Foco",
    "tec_custo": lambda v: "a técnica custa 1 Foco a menos",
    "tec_barr": lambda v: f"a técnica concede {_s(v)} de barreira",
    "tec_extra": lambda v: f"{_s(v)}% de chance de a técnica dar um 2º golpe de 50%",
    "acerto_barr": lambda v: f"cada golpe dá {_s(v)} de barreira",
    "acerto_foco": lambda v: f"{_s(v)}% de chance de ganhar +1 Foco ao acertar",
    "abate_cura": lambda v: f"derrotar uma criatura cura {_s(v)}% da vida máxima",
    "abate_foco": lambda v: f"derrotar uma criatura dá +{_s(v)} Foco",
    "red": lambda v: f"reduz {_s(v)}% do dano recebido",
    "red_flat": lambda v: f"reduz {_s(v)} do dano de cada golpe recebido",
    "esq": lambda v: f"{_s(v)}% de chance de esquivar (nunca 2 golpes seguidos)",
    "barr_golpe": lambda v: f"ao ser atingido, ganha {_s(v)} de barreira",
    "espinho": lambda v: f"devolve {_s(v)} de dano a quem o atinge",
    "espinho_def": lambda v: f"devolve {_s(v)}% da sua defesa como dano a quem o atinge",
    "contra": lambda v: f"{_s(v)}% de chance de contra-atacar ao ser atingido (máx. {CONTRA_MAX_COMBATE}/combate)",
    "folego": lambda v: "sobrevive a um golpe fatal com 1 de vida (1×/run)",
    "regen": lambda v: f"recupera {_s(v)}% da vida máxima no fim de cada turno",
    "conc_bonus": lambda v: f"Concentrar rende {_s(v)}% a mais",
    "rewind": lambda v: f"abaixo de 30% de vida, recupera {_s(v)}% do que perdeu no combate (1×)",
    "eco": lambda v: f"{_s(v)}% do dano de cada golpe volta como eco no fim do turno",
    "paradoxo": lambda v: f"{_s(v)}% de chance de um golpe se repetir (60%) no fim do turno",
    "aposta": lambda v: f"{_s(v)}% de chance de golpe sortudo (+60% e +1 Foco); metade disso de azar (-25%)",
    "prep": lambda v: f"o primeiro golpe de cada combate causa +{_s(v)}%",
    "roubo": lambda v: f"+{_s(v)}% de roubo de vida (só Vampiro)",
    "roubo_barr": lambda v: f"com a vida cheia, {_s(v)}% do roubo vira barreira",
    "foco_guarda": lambda v: f"Guardar dá +{_s(v)} Foco extra",
    "invoc": lambda v: f"+{_s(v)}% de dano das invocações",
}
CHAVES_BASE = frozenset(_TEXTO_BASE)

# Chaves que só fazem sentido para certas classes (validado no registro).
CHAVES_EXCLUSIVAS = {
    "roubo": {"vampiro"}, "roubo_barr": {"vampiro"},
    "ciclo": {"mago", "engenhoqueiro"},
    "alq_max": {"alquimista"}, "alq_carga": {"alquimista"},
    "alq_queima": {"alquimista"},
    "invoc": {"engenhoqueiro"},
}


def chave_valida(chave: str) -> bool:
    """True se a chave de efeito existe no vocabulário."""
    if chave in CHAVES_BASE:
        return True
    prefixo, _, resto = chave.partition(":")
    if prefixo == "dano_se":
        return resto in CONDICOES
    if prefixo == "st":
        return resto in STATUS and resto != "atordoar"
    if prefixo == "tec_st":
        return resto in STATUS
    return False


def texto_efeito(chave: str, valor: float) -> str:
    """Descrição legível de um efeito."""
    if chave in _TEXTO_BASE:
        return _TEXTO_BASE[chave](valor)
    prefixo, _, resto = chave.partition(":")
    if prefixo == "dano_se":
        return f"+{_s(valor)}% de dano {CONDICOES[resto]}"
    if prefixo == "st":
        return f"{_s(valor)}% de chance de {resto_status(resto)} ao acertar"
    if prefixo == "tec_st":
        return f"a técnica tem {_s(valor)}% de chance de {resto_status(resto)}"
    return chave


def resto_status(st: str) -> str:
    return {"queimar": "queimar", "veneno": "envenenar", "sangria": "causar sangramento",
            "marca": "marcar", "fraco": "enfraquecer", "atordoar": "atordoar"}[st]


# ---------- tipos do registro ----------

@dataclass(frozen=True)
class AtivaSpec:
    """Parâmetros de uma habilidade ATIVA (botão no combate)."""
    foco: int = 2                 # custo em Foco
    cd: int = 3                   # recarga (em turnos seus)
    uso: int = 0                  # usos por combate (0 = ilimitado)
    mult: Optional[float] = None  # None = a habilidade não ataca
    fixo: int = 0
    fixo_def: int = 0             # % da defesa somado ao dano
    nunca_erra: bool = False
    ignora_def: bool = False
    crit: bool = False            # crítico garantido
    exec: bool = False            # x1,5 contra inimigo com <=35% de vida
    carga: int = 0                # dano por carga (consome as cargas)
    cura: int = 0                 # % da vida máxima
    barr: int = 0
    guarda: bool = False
    esq: bool = False
    ganho_foco: int = 0
    ganho_cargas: int = 0
    hp_custo: int = 0             # % da vida máxima (nunca mata)
    queimar: int = 0              # turnos
    veneno: int = 0               # acúmulos
    sangria: int = 0
    marca: int = 0                # golpes
    fraco: int = 0                # turnos
    atordoar: bool = False
    invocar: float = 0.0          # multiplicador do ataque da invocação
    invocar_turnos: int = 3
    dado: bool = False            # resultado aleatório (Apostador)
    eco_armar: int = 0            # % de eco nos próximos 2 golpes


@dataclass(frozen=True)
class NoSpec:
    """Um nó da árvore. Todo o comportamento vem de 'efeitos' e 'ativa'."""
    id: str
    classe: str
    spec: str
    ordem: int
    nome: str
    lore: str
    tipo: str                      # ativa | passiva | modificador
    custo: int
    nivel_min: int
    prereqs: tuple[str, ...]
    max_rank: int
    efeitos: tuple[tuple[str, float], ...]
    ativa: Optional[AtivaSpec]
    suprema: bool = False


@dataclass(frozen=True)
class EspecSpec:
    """Uma especialização (3 por classe)."""
    id: str                        # "classe.spec"
    classe: str
    chave: str
    nome: str
    descricao: str
    nos: tuple[str, ...]


NOS: dict[str, NoSpec] = {}
ESPECS: dict[str, EspecSpec] = {}


def A(**parametros) -> AtivaSpec:
    """Atalho para declarar uma ativa nos dados."""
    return AtivaSpec(**parametros)


def N(nome: str, lore: str, tipo: str, ef=(), at: Optional[AtivaSpec] = None):
    """Atalho para declarar um nó nos dados."""
    return (nome, lore, tipo, tuple(ef), at)


def _escalar(chave: str, valor: float) -> float:
    """Aplica ESCALA_OFENSIVA/DEFENSIVA a um valor de efeito (arredondado)."""
    if chave.startswith(CHAVES_OFENSIVAS):
        escala = ESCALA_OFENSIVA
    elif chave.startswith(CHAVES_DEFENSIVAS):
        escala = ESCALA_DEFENSIVA
    else:
        return valor
    if escala == 1.0:
        return valor
    return max(1, round(valor * escala))


def custo_no(no: NoSpec) -> int:
    """Custo em Abysmus de UM nível do nó (com a escala global)."""
    return max(0, int(round(no.custo * ESCALA_CUSTO_BUILD)))


def registrar_especializacao(classe: str, chave: str, nome: str,
                             descricao: str, nos: list) -> EspecSpec:
    """Registra uma especialização com 5 nós seguindo MODELO_NOS."""
    if classe not in CLASSES:
        raise ValueError(f"Classe desconhecida: {classe}")
    if len(nos) != 5:
        raise ValueError(f"{classe}.{chave}: são necessários 5 nós.")
    espec_id = f"{classe}.{chave}"
    if espec_id in ESPECS:
        raise ValueError(f"Especialização duplicada: {espec_id}")

    ids = [f"{espec_id}.n{i}" for i in range(1, 6)]
    for i, (n_nome, lore, tipo, ef, at) in enumerate(nos, start=1):
        modelo = MODELO_NOS[i]
        ef = tuple((k, _escalar(k, v)) for k, v in ef)
        if at is not None and at.mult is not None:
            at = replace(at, mult=round(at.mult * ESCALA_ATIVAS, 2))
        no = NoSpec(
            id=ids[i - 1], classe=classe, spec=espec_id, ordem=i,
            nome=n_nome, lore=lore, tipo=tipo, custo=modelo["custo"],
            nivel_min=modelo["nivel"],
            prereqs=tuple(ids[j - 1] for j in modelo["req"]),
            max_rank=modelo["rank"], efeitos=ef, ativa=at, suprema=(i == 5),
        )
        if no.id in NOS:
            raise ValueError(f"Nó duplicado: {no.id}")
        NOS[no.id] = no

    spec = EspecSpec(espec_id, classe, chave, nome, descricao, tuple(ids))
    ESPECS[espec_id] = spec
    return spec


def especs_da_classe(classe: str) -> list[EspecSpec]:
    return [e for e in ESPECS.values() if e.classe == classe]


def validar_arvores() -> list[str]:
    """
    Verificações de saúde da árvore (rodam ao carregar o cog).
    Devolve a lista de problemas; vazia = tudo certo.
    """
    problemas: list[str] = []

    for no in NOS.values():
        if no.classe not in CLASSES:
            problemas.append(f"{no.id}: classe inexistente.")
        if no.tipo not in ("ativa", "passiva", "modificador"):
            problemas.append(f"{no.id}: tipo inválido '{no.tipo}'.")
        if (no.tipo == "ativa") != (no.ativa is not None):
            problemas.append(f"{no.id}: 'ativa' e AtivaSpec não combinam.")
        if no.custo < 0 or no.max_rank < 1 or no.nivel_min < 1:
            problemas.append(f"{no.id}: custo/rank/nível inválido.")
        for pre in no.prereqs:
            if pre not in NOS:
                problemas.append(f"{no.id}: pré-requisito inexistente {pre}.")
            elif NOS[pre].spec != no.spec:
                problemas.append(f"{no.id}: pré-requisito de outra especialização.")
        for chave, valor in no.efeitos:
            if not chave_valida(chave):
                problemas.append(f"{no.id}: chave de efeito inválida '{chave}'.")
                continue
            base = chave.split(":")[0]
            permitidas = CHAVES_EXCLUSIVAS.get(base)
            if permitidas and no.classe not in permitidas:
                problemas.append(
                    f"{no.id}: '{base}' só é permitido em {sorted(permitidas)}.")
            if valor <= 0:
                problemas.append(f"{no.id}: valor não positivo em '{chave}'.")

    # Grafo sem ciclos (busca em profundidade).
    cor: dict[str, int] = {}

    def visitar(nid: str) -> bool:
        if cor.get(nid) == 1:
            return False          # ciclo
        if cor.get(nid) == 2:
            return True
        cor[nid] = 1
        for pre in NOS[nid].prereqs:
            if pre in NOS and not visitar(pre):
                return False
        cor[nid] = 2
        return True

    for nid in NOS:
        if not visitar(nid):
            problemas.append(f"Ciclo de pré-requisitos envolvendo {nid}.")
            break

    for espec in ESPECS.values():
        if len(espec.nos) != 5:
            problemas.append(f"{espec.id}: não tem 5 nós.")
    return problemas


# ============================================================
# DADOS: 10 CLASSES x 3 ESPECIALIZAÇÕES x 5 NÓS
# (expansão sugerida para SFA; custo/nível/pré-requisitos vêm de
#  MODELO_NOS; só nome, texto, tipo, efeitos e ativa são escritos aqui)
# ============================================================

# ---------------- MAGO DO VÉU ----------------
registrar_especializacao("mago", "rupturista", "Rupturista Arcano",
    "Explosão de dano e manipulação da realidade: rasga o Véu até a falha cobrar seu preço do alvo.", [
    N("Fenda Instável", "Uma costura do Véu cede onde você aponta.", "ativa",
      at=A(foco=2, cd=3, mult=1.4, nunca_erra=True, ignora_def=True)),
    N("Estilhaços do Véu", "Pedaços de realidade ficam cortantes.", "passiva",
      ef=[("crit", 4), ("dano_se:critico", 8)]),
    N("Brecha Calculada", "Você aprendeu onde a realidade é mais fina.", "passiva",
      ef=[("perf", 60), ("dano_se:saudavel", 12)]),
    N("Ciclo Acelerado", "A Magia do Véu deixa de esperar o terceiro compasso.", "modificador",
      ef=[("ciclo", 1), ("tec_extra", 15)]),
    N("Colapso da Realidade", "Por um instante, o plano material dobra sobre si mesmo.", "ativa",
      at=A(foco=4, cd=0, uso=1, mult=2.6, nunca_erra=True, ignora_def=True, queimar=2)),
])
registrar_especializacao("mago", "oraculo", "Oráculo do Véu",
    "Previsão, controle e respostas aos ataques inimigos: quem vê o golpe antes dele existir.", [
    N("Visão Antecipada", "O golpe já aconteceu para você; só falta o corpo chegar.", "ativa",
      at=A(foco=2, cd=4, esq=True)),
    N("Leitura de Intenção", "Cada gesto da criatura deixa um rastro no Véu.", "passiva",
      ef=[("red", 4), ("barr_golpe", 3)]),
    N("Fio do Destino", "Puxe o fio certo e o inimigo hesita.", "passiva",
      ef=[("st:fraco", 25), ("st:marca", 15)]),
    N("Profecia Cumprida", "O que você previu agora é uma ordem.", "modificador",
      ef=[("tec_st:marca", 100), ("tec_foco", 20)]),
    N("Véu do Pressentimento", "Nada o surpreende; poucas coisas o alcançam.", "passiva",
      ef=[("esq", 10), ("contra", 20), ("folego", 1)]),
])
registrar_especializacao("mago", "ocultista", "Ocultista do Véu Neutral",
    "Magia proibida, sacrifícios e efeitos de alto risco: poder que cobra em carne.", [
    N("Pacto de Sangue", "O Véu Neutral aceita pagamento em vida.", "ativa",
      at=A(foco=1, cd=2, mult=2.2, nunca_erra=True, hp_custo=12)),
    N("Preço do Proibido", "Quanto mais você paga, mais a magia obedece.", "passiva",
      ef=[("dano_falta", 20)]),
    N("Ritual Neutro", "Cada morte alimenta o próximo encantamento.", "passiva",
      ef=[("abate_cura", 8), ("abate_foco", 1)]),
    N("Magia Sem Nome", "Um feitiço que ninguém ousou registrar.", "modificador",
      ef=[("tec_custo", 1), ("dano_se:tecnica", 25), ("dano_se:vida_baixa", 20)]),
    N("Rito do Véu Neutral", "Marjopyia observa em silêncio enquanto você paga.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=3.4, nunca_erra=True, ignora_def=True, hp_custo=30)),
])

# ---------------- GUARDIÃO DA LUMINÁRIA ----------------
registrar_especializacao("guardiao", "paladino", "Paladino da Aurora",
    "Proteção, recuperação e contra-ataques: a luz que fecha feridas e devolve o golpe.", [
    N("Aurora Restauradora", "A Luminária responde a quem a mantém acesa.", "ativa",
      at=A(foco=2, cd=4, cura=14, barr=8)),
    N("Bênção da Alvorada", "Um calor constante sob a armadura.", "passiva",
      ef=[("regen", 1), ("conc_bonus", 20)]),
    N("Juramento de Retaliação", "Quem fere o guardião é lembrado da luz.", "passiva",
      ef=[("contra", 20), ("barr_golpe", 3)]),
    N("Luz que Responde", "A Muralha de Luz agora cura e reforça.", "modificador",
      ef=[("tec_cura", 8), ("tec_barr", 8)]),
    N("Aurora Inquebrável", "Enquanto houver luz, há mais um passo.", "passiva",
      ef=[("folego", 1), ("abate_cura", 5), ("red", 5)]),
])
registrar_especializacao("guardiao", "baluarte", "Baluarte Templário",
    "Resistência, mitigação e sobrevivência: a ordem que se recusa a ceder.", [
    N("Postura de Muralha", "Os pés fincados; o escudo, uma promessa.", "ativa",
      at=A(foco=2, cd=3, guarda=True, barr=10)),
    N("Armadura Consagrada", "Cada placa foi benzida por quem já caiu.", "passiva",
      ef=[("red", 4), ("def", 1)]),
    N("Escudo Vivo", "A barreira nasce antes do golpe.", "passiva",
      ef=[("barr_ini", 12), ("barr_golpe", 4)]),
    N("Muralha Duradoura", "Guardar passa a render mais do que gasta.", "modificador",
      ef=[("guarda_red", 10), ("foco_guarda", 1)]),
    N("Último Bastião", "Quando tudo recua, a ordem permanece.", "passiva",
      ef=[("red", 8), ("folego", 1), ("red_flat", 2)]),
])
registrar_especializacao("guardiao", "inquisidor", "Inquisidor da Luminária",
    "Marcas, punições e dano contra inimigos debilitados: a luz que também julga.", [
    N("Marca da Luminária", "Um sinal que só a culpa consegue ver.", "ativa",
      at=A(foco=1, cd=3, mult=0.8, marca=3)),
    N("Sentença Iluminada", "O marcado é julgado a cada golpe.", "passiva",
      ef=[("dano_se:marcado", 10)]),
    N("Punição Exemplar", "A fraqueza do réu é a sua vantagem.", "passiva",
      ef=[("dano_se:debil", 14), ("st:marca", 20)]),
    N("Veredito", "A técnica agora é uma sentença.", "modificador",
      ef=[("tec_st:marca", 100), ("dano_se:tecnica", 15)]),
    N("Inquisição Plena", "A luz exige confissão.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=2.2, nunca_erra=True, marca=4, fraco=3)),
])

# ---------------- ERRANTE TEMPORAL ----------------
registrar_especializacao("errante", "duelista", "Duelista do Segundo Perdido",
    "Críticos e sequências ofensivas: o golpe que acontece entre dois instantes.", [
    N("Estocada Perdida", "Um ataque que só existiu no segundo que faltou.", "ativa",
      at=A(foco=2, cd=3, mult=1.1, crit=True)),
    N("Ritmo do Duelo", "Cada golpe acerta o compasso do próximo.", "passiva",
      ef=[("combo", 4)]),
    N("Segundo Perdido", "Você vive um instante a mais que o oponente.", "passiva",
      ef=[("crit", 6), ("crit_foco", 1)]),
    N("Lâmina Sincronizada", "O Instante Fendido corta mais fundo.", "modificador",
      ef=[("crit_mult", 20), ("tec_foco", 20)]),
    N("Duelo Eterno", "A luta se repete até você acertar.", "passiva",
      ef=[("dano_se:critico", 25), ("crit_barr", 4), ("combo", 3)]),
])
registrar_especializacao("errante", "cronomante", "Cronomante Errante",
    "Ecos de ataques, previsão e manipulação de turnos: o tempo dobrado a seu favor.", [
    N("Reverberar", "O golpe ainda ressoa quando o próximo começa.", "ativa",
      at=A(foco=2, cd=4, mult=0.8, nunca_erra=True, eco_armar=80)),
    N("Eco de Ataque", "Seus golpes deixam sombras de si.", "passiva",
      ef=[("eco", 20)]),
    N("Previsão de Turnos", "Você chega ao combate já preparado.", "passiva",
      ef=[("prep", 40), ("foco_ini", 1), ("vida", 10)]),
    N("Tempo Dobrado", "Às vezes o inimigo perde um instante inteiro.", "modificador",
      ef=[("tec_st:atordoar", 50), ("tec_foco", 15)]),
    N("Ampulheta Quebrada", "A areia cai para os dois lados.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=1.6, nunca_erra=True, atordoar=True, eco_armar=80)),
])
registrar_especializacao("errante", "apostador", "Apostador do Paradoxo",
    "Resultados imprevisíveis, com risco e recompensa: a sorte de quem desafia a causalidade.", [
    N("Lance do Destino", "Role o dado; o paradoxo decide.", "ativa",
      at=A(foco=1, cd=2, dado=True)),
    N("Sorte Torta", "Às vezes ela acerta. Às vezes ela tropeça.", "passiva",
      ef=[("aposta", 8)]),
    N("Paradoxo Menor", "Um golpe que talvez já tenha acontecido.", "passiva",
      ef=[("paradoxo", 15), ("crit", 4), ("vida", 10)]),
    N("Aposta Dobrada", "Tudo no primeiro lance.", "modificador",
      ef=[("tec_extra", 20), ("dano_se:primeiro", 30)]),
    N("Cartada do Paradoxo", "A última carta contradiz o baralho inteiro.", "passiva",
      ef=[("aposta", 10), ("paradoxo", 10), ("crit_foco", 1)]),
])

# ---------------- VAMPIRO DA NOITE CARMESIM ----------------
registrar_especializacao("vampiro", "sanguinario", "Sanguinário",
    "Drenagem e recuperação de vida: a Fome Carmesim, finalmente alimentada.", [
    N("Sede Despertada", "A Fome responde antes de você.", "ativa",
      at=A(foco=2, cd=3, mult=1.2, nunca_erra=True, sangria=3)),
    N("Gosto de Sangue", "Cada gole ensina o próximo.", "passiva",
      ef=[("roubo", 4)]),
    N("Hemorragia", "As feridas que você abre não fecham.", "passiva",
      ef=[("st:sangria", 30), ("dano_se:sangrando", 15)]),
    N("Banquete Carmesim", "A Mordida agora sacia de verdade.", "modificador",
      ef=[("tec_cura", 6), ("roubo_barr", 50)]),
    N("Rio Carmesim", "O sangue dos outros corre por dentro de você.", "passiva",
      ef=[("roubo", 8), ("abate_cura", 10), ("dano_se:vida_baixa", 20)]),
])
registrar_especializacao("vampiro", "nobre", "Nobre da Noite",
    "Resistência, barreiras e domínio defensivo: a etiqueta de quem não precisa se apressar.", [
    N("Véu de Sangue", "Sangue condensado em seda.", "ativa",
      at=A(foco=2, cd=4, barr=14, guarda=True)),
    N("Etiqueta Letal", "Modos impecáveis; golpes, nem tanto.", "passiva",
      ef=[("red", 4), ("def", 1)]),
    N("Capa de Veludo", "Nada o toca sem permissão.", "passiva",
      ef=[("barr_ini", 10), ("barr_golpe", 4)]),
    N("Domínio da Noite", "O excedente da Fome vira armadura.", "modificador",
      ef=[("roubo_barr", 100), ("tec_barr", 10)]),
    N("Soberano Carmesim", "A noite o reconhece como seu.", "passiva",
      ef=[("red", 8), ("folego", 1), ("roubo", 5)]),
])
registrar_especializacao("vampiro", "predador", "Predador Hemático",
    "Caça de inimigos feridos e execução: quem cheira a fraqueza não erra.", [
    N("Farejar Fraqueza", "A presa denuncia a si mesma.", "ativa",
      at=A(foco=1, cd=3, mult=0.9, marca=2)),
    N("Instinto de Caça", "Você sabe quando é a hora.", "passiva",
      ef=[("dano_se:ferido", 10)]),
    N("Golpe de Misericórdia", "O marcado não vê o fim chegar.", "passiva",
      ef=[("dano_se:marcado", 12), ("abate_foco", 1)]),
    N("Mordida Letal", "A Mordida deixa uma ferida aberta.", "modificador",
      ef=[("dano_se:tecnica", 15), ("tec_st:sangria", 100)]),
    N("Última Presa", "Toda caçada tem um final.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=2.0, nunca_erra=True, exec=True)),
])

# ---------------- BASTIÃO DE DRAK'VUH ----------------
registrar_especializacao("bastiao", "muralha", "Muralha de Drak'vuh",
    "Vida, barreiras e resistência: raiz e pedra contra o fim.", [
    N("Raízes de Pedra", "O chão o segura; você segura o resto.", "ativa",
      at=A(foco=2, cd=4, barr=18, guarda=True)),
    N("Seiva de Pedra", "A árvore primordial ainda corre pelas rachaduras.", "passiva",
      ef=[("vida", 8), ("barr_ini", 4)]),
    N("Casca Primordial", "Camadas de eras mais antigas que o medo.", "passiva",
      ef=[("red_flat", 1), ("red", 4), ("barr_golpe", 3)]),
    N("Baluarte Enraizado", "O Quebra-Baluarte protege quem o usa.", "modificador",
      ef=[("tec_barr", 14), ("guarda_red", 8)]),
    N("Muralha Eterna", "Nada atravessa o que já estava aqui antes.", "passiva",
      ef=[("red", 8), ("barr_ini", 20), ("folego", 1)]),
])
registrar_especializacao("bastiao", "punho", "Punho de Pedra",
    "Conversão de defesa em dano e retaliação: a muralha que também golpeia.", [
    N("Soco Tectônico", "O peso da armadura vira o peso do golpe.", "ativa",
      at=A(foco=2, cd=3, mult=1.2, nunca_erra=True, fixo_def=100)),
    N("Pele de Granito", "Quanto mais firme, mais forte.", "passiva",
      ef=[("dano_def", 20), ("def", 1)]),
    N("Retorno de Impacto", "O golpe recebido volta com juros.", "passiva",
      ef=[("espinho_def", 40), ("contra", 15)]),
    N("Quebra Ampliada", "A rachadura se espalha pelo alvo.", "modificador",
      ef=[("dano_se:tecnica", 20), ("tec_st:fraco", 100)]),
    N("Colosso de Drak'vuh", "Uma estátua que lembrou como se mexer.", "passiva",
      ef=[("dano_def", 40), ("dano_barr", 25), ("espinho", 4)]),
])
registrar_especializacao("bastiao", "raizes", "Guardião das Raízes",
    "Recuperação e sobrevivência prolongada: o que cresce sob a pedra não morre.", [
    N("Brotar", "Algo verde insiste em nascer das fendas.", "ativa",
      at=A(foco=2, cd=4, cura=15)),
    N("Seiva Constante", "Um fluxo lento, sem pressa.", "passiva",
      ef=[("regen", 1)]),
    N("Raiz Profunda", "Cada vitória alimenta as raízes.", "passiva",
      ef=[("abate_cura", 8), ("conc_bonus", 30)]),
    N("Ciclo das Estações", "Guardar e curar viram o mesmo gesto.", "modificador",
      ef=[("tec_cura", 8), ("foco_guarda", 1)]),
    N("Árvore Viva", "Há quem jure que ela respira.", "passiva",
      ef=[("regen", 2), ("folego", 1), ("red", 6)]),
])

# ---------------- CEIFADOR CARMESIM ----------------
registrar_especializacao("ceifador", "executor", "Executor Carmesim",
    "Execução e dano contra alvos feridos: a sentença só precisa de uma brecha.", [
    N("Golpe de Misericórdia", "Rápido, limpo, definitivo.", "ativa",
      at=A(foco=2, cd=3, mult=1.6, nunca_erra=True, exec=True)),
    N("Olhar de Sentença", "Você enxerga onde a lâmina vai pousar.", "passiva",
      ef=[("dano_se:ferido", 10)]),
    N("Fio da Lâmina", "O gume procura a falha na armadura.", "passiva",
      ef=[("crit", 6), ("perf", 40)]),
    N("Execução Aperfeiçoada", "A técnica não desperdiça nada.", "modificador",
      ef=[("dano_se:tecnica", 20), ("tec_foco", 20)]),
    N("Sentença Final", "Não há apelação.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=2.4, nunca_erra=True, ignora_def=True, exec=True)),
])
registrar_especializacao("ceifador", "almas", "Ceifador das Almas",
    "Cargas, recuperação e colheita de recursos: cada fim alimenta o seguinte.", [
    N("Colher Alma", "Um fragmento volta com o golpe.", "ativa",
      at=A(foco=1, cd=3, mult=1.0, nunca_erra=True, ganho_foco=1)),
    N("Colheita", "Nada se perde, tudo se recolhe.", "passiva",
      ef=[("abate_cura", 5), ("abate_foco", 1)]),
    N("Fome das Almas", "Cada acerto dá mais vontade de acertar.", "passiva",
      ef=[("acerto_foco", 20), ("dano_se:foco_cheio", 15)]),
    N("Foice Faminta", "A Execução devolve parte do que toma.", "modificador",
      ef=[("tec_foco", 25), ("tec_cura", 5)]),
    N("Ceifa Total", "Onde ela passa, o campo fica vazio.", "passiva",
      ef=[("abate_cura", 10), ("abate_foco", 1), ("dano_se:ferido", 15)]),
])
registrar_especializacao("ceifador", "dancarino", "Dançarino da Morte",
    "Sequências de ataques, críticos e combos controlados: a morte tem compasso.", [
    N("Passo Mortal", "O golpe termina no meio de um giro.", "ativa",
      at=A(foco=2, cd=3, mult=1.2, esq=True)),
    N("Ritmo Macabro", "Quem erra o passo, cai.", "passiva",
      ef=[("combo", 6)]),
    N("Giro Fatal", "Todo giro termina em corte.", "passiva",
      ef=[("crit", 6), ("crit_foco", 1)]),
    N("Valsa de Lâminas", "A Execução ganha um segundo movimento.", "modificador",
      ef=[("tec_extra", 25), ("dano_se:critico", 15)]),
    N("Dança Final", "O último compasso nunca termina onde começou.", "passiva",
      ef=[("combo", 5), ("crit_mult", 25), ("paradoxo", 12)]),
])

# ---------------- ALQUIMISTA DO ABISMO ----------------
registrar_especializacao("alquimista", "piromante", "Piromante Alquímico",
    "Fogo, combustão e explosões: a Reação em Cadeia levada ao limite.", [
    N("Frasco Incendiário", "Vidro fino, conteúdo instável.", "ativa",
      at=A(foco=2, cd=3, mult=1.2, queimar=4)),
    N("Brasa Viva", "O fogo aprende a se espalhar.", "passiva",
      ef=[("st:queimar", 35), ("dano_se:queimando", 14)]),
    N("Combustão", "Cada carga acumula mais calor.", "passiva",
      ef=[("alq_carga", 2), ("dano_se:queimando", 18), ("vida", 12)]),
    N("Detonação Aprimorada", "A Detonação cabe mais, queima mais, dura mais.", "modificador",
      ef=[("alq_queima", 2), ("alq_max", 1), ("dano_se:tecnica", 15)]),
    N("Inferno do Abismo", "Algo muito antigo acende junto com a chama.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=2.0, nunca_erra=True, queimar=4, carga=6)),
])
registrar_especializacao("alquimista", "toxico", "Toxicologista do Abismo",
    "Venenos, deterioração e efeitos persistentes: paciência destilada.", [
    N("Frasco de Peçonha", "Duas gotas bastam.", "ativa",
      at=A(foco=2, cd=3, mult=1.0, veneno=3)),
    N("Gota Persistente", "O veneno não tem pressa.", "passiva",
      ef=[("st:veneno", 40)]),
    N("Deterioração", "O alvo desfaz-se por dentro.", "passiva",
      ef=[("dano_se:envenenado", 20), ("st:fraco", 15), ("vida", 12)]),
    N("Destilado Letal", "A Detonação carrega uma segunda intenção.", "modificador",
      ef=[("tec_st:veneno", 100), ("alq_max", 1)]),
    N("Praga do Abismo", "Algo respira dentro da sua dose.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=1.4, nunca_erra=True, veneno=5, fraco=3)),
])
registrar_especializacao("alquimista", "transmutador", "Transmutador Instável",
    "Cargas, conversões de recursos e reações de alto risco: a fórmula nunca é a mesma.", [
    N("Transmutação Instável", "Vida vira reagente; reagente vira poder.", "ativa",
      at=A(foco=1, cd=2, mult=1.0, nunca_erra=True, ganho_cargas=3, hp_custo=8)),
    N("Reagente Volátil", "Acumula mais, estoura mais forte.", "passiva",
      ef=[("alq_carga", 1), ("alq_max", 1)]),
    N("Conversão de Foco", "Tudo é matéria-prima.", "passiva",
      ef=[("acerto_foco", 30), ("abate_foco", 1), ("vida", 12)]),
    N("Reação Descontrolada", "A Detonação passa a aceitar riscos.", "modificador",
      ef=[("alq_max", 1), ("tec_extra", 20), ("dano_se:vida_baixa", 15)]),
    N("Opus Magnum", "A Grande Obra, incompleta, mas devastadora.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=1.8, nunca_erra=True, carga=10, hp_custo=15)),
])

# ---------------- ANDARILHO DA FENDA ----------------
registrar_especializacao("andarilho", "espectro", "Espectro Dimensional",
    "Evasão e mitigação: estar e não estar ao mesmo tempo.", [
    N("Passo Fantasma", "Um passo para onde o golpe não chega.", "ativa",
      at=A(foco=2, cd=4, esq=True, barr=6)),
    N("Corpo Incerto", "Parte de você está sempre em outro lugar.", "passiva",
      ef=[("esq", 4), ("red", 3)]),
    N("Névoa da Fenda", "A névoa o dobra ao redor dos golpes.", "passiva",
      ef=[("red", 5), ("barr_golpe", 4)]),
    N("Fenda Prolongada", "A Dança entre Fendas deixa um rastro protetor.", "modificador",
      ef=[("tec_barr", 10), ("tec_foco", 20)]),
    N("Existência Parcial", "Você é mais uma hipótese do que um alvo.", "passiva",
      ef=[("esq", 6), ("red", 8), ("contra", 15)]),
])
registrar_especializacao("andarilho", "assassino", "Assassino Entre Fendas",
    "Ataques oportunistas e perfuração defensiva: a brecha que ninguém viu.", [
    N("Golpe pelas Costas", "Você aparece onde a guarda não existe.", "ativa",
      at=A(foco=2, cd=3, mult=1.5, nunca_erra=True, ignora_def=True)),
    N("Brecha na Guarda", "Toda armadura tem uma costura.", "passiva",
      ef=[("perf", 30), ("dano_se:primeiro", 10)]),
    N("Oportunista", "Fraqueza e esquiva abrem o caminho.", "passiva",
      ef=[("dano_se:debil", 14), ("dano_se:esquiva", 25), ("vida", 10)]),
    N("Lâmina Interdimensional", "A Dança entre Fendas corta duas vezes.", "modificador",
      ef=[("tec_extra", 20), ("dano_se:tecnica", 15)]),
    N("Execução Dimensional", "O golpe sai de um lugar que não existe.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=2.3, nunca_erra=True, ignora_def=True, exec=True)),
])
registrar_especializacao("andarilho", "peregrino", "Peregrino Temporal",
    "Manipulação de turnos, preparação e reposicionamento temporal: chegar antes, recuar depois.", [
    N("Recuo Temporal", "Dê um passo para trás no próprio instante.", "ativa",
      at=A(foco=2, cd=5, guarda=True, esq=True)),
    N("Preparação", "Quem já esteve ali sabe o que fazer.", "passiva",
      ef=[("prep", 20), ("foco_ini", 1)]),
    N("Rewind Curto", "Alguns segundos desfeitos.", "passiva",
      ef=[("rewind", 25), ("vida", 10)]),
    N("Fenda de Espera", "O inimigo perde um fôlego, às vezes.", "modificador",
      ef=[("tec_st:atordoar", 30), ("tec_foco", 15)]),
    N("Peregrino do Fim dos Tempos", "Você já viu como isto termina.", "passiva",
      ef=[("prep", 40), ("rewind", 15), ("esq", 5)]),
])

# ---------------- SILVESTRE CORROMPIDO ----------------
registrar_especializacao("silvestre", "druida", "Druida da Seiva Negra",
    "Recuperação e barreiras naturais: a floresta cura do seu jeito.", [
    N("Casca de Seiva", "A pele endurece e fecha sozinha.", "ativa",
      at=A(foco=2, cd=4, barr=12, cura=8)),
    N("Seiva Fluente", "Algo escuro e vivo corre sob a casca.", "passiva",
      ef=[("regen", 1), ("barr_ini", 4)]),
    N("Raízes Protetoras", "O chão responde a cada golpe.", "passiva",
      ef=[("barr_golpe", 4), ("conc_bonus", 30)]),
    N("Florescer Ampliado", "O Florescer Profano alcança mais fundo.", "modificador",
      ef=[("tec_cura", 6), ("tec_barr", 10)]),
    N("Coração da Floresta", "Há algo pulsando dentro da mata.", "passiva",
      ef=[("regen", 1), ("abate_cura", 8), ("folego", 1)]),
])
registrar_especializacao("silvestre", "espinheiro", "Espinheiro Corrompido",
    "Retaliação, enfraquecimento e deterioração: quem encosta, sangra.", [
    N("Espinhos Negros", "A casca se eriça e escurece.", "ativa",
      at=A(foco=2, cd=3, guarda=True, fraco=2)),
    N("Pele de Espinhos", "Cada golpe recebido é uma lição.", "passiva",
      ef=[("espinho", 2), ("espinho_def", 20)]),
    N("Seiva Venenosa", "O que escorre dos espinhos adoece.", "passiva",
      ef=[("st:veneno", 20), ("st:fraco", 20)]),
    N("Florescer Espinhoso", "A flor traz o que a raiz esconde.", "modificador",
      ef=[("tec_st:fraco", 100), ("tec_st:veneno", 50)]),
    N("Coroa de Espinhos", "Quem a vê decide não chegar mais perto.", "passiva",
      ef=[("espinho", 4), ("contra", 20), ("dano_se:envenenado", 15)]),
])
registrar_especializacao("silvestre", "fungo", "Arauto do Fungo",
    "Esporos, efeitos persistentes e sinergias com criaturas afetadas: a floresta que se alimenta do que cai.", [
    N("Nuvem de Esporos", "O ar fica espesso e vivo.", "ativa",
      at=A(foco=2, cd=3, mult=0.7, veneno=2, fraco=2)),
    N("Micélio", "Uma rede invisível sob o campo de batalha.", "passiva",
      ef=[("st:veneno", 20), ("dano_se:envenenado", 8)]),
    N("Frutificação", "Onde algo cai, algo cresce.", "passiva",
      ef=[("abate_cura", 8), ("abate_foco", 1)]),
    N("Simbiose Fúngica", "O Florescer carrega esporos consigo.", "modificador",
      ef=[("tec_st:veneno", 100), ("tec_cura", 5)]),
    N("Arauto da Podridão Viva", "A decomposição também é uma forma de vida.", "passiva",
      ef=[("dano_se:debil", 20), ("st:sangria", 20), ("regen", 1)]),
])

# ---------------- ENGENHOQUEIRO DE DA'KOR ----------------
registrar_especializacao("engenhoqueiro", "artilheiro", "Artilheiro de Da'kor",
    "Armas pesadas, perfuração e explosões: calibre grosso para um mundo que não coopera.", [
    N("Canhão de Mão", "Cabe na mochila; não cabe no inimigo.", "ativa",
      at=A(foco=2, cd=3, mult=1.5, nunca_erra=True)),
    N("Munição Perfurante", "Feita para atravessar o que for.", "passiva",
      ef=[("perf", 30), ("atq", 1)]),
    N("Carga Explosiva", "O primeiro tiro de cada combate faz barulho.", "passiva",
      ef=[("dano_se:primeiro", 25), ("st:queimar", 15), ("vida", 10)]),
    N("Descarga Reforçada", "A Sobrecarga Mecânica dispara mais vezes.", "modificador",
      ef=[("ciclo", 1), ("dano_se:tecnica", 15)]),
    N("Bombardeio de Da'kor", "Cada vez que a névoa responde, o céu cai.", "ativa",
      at=A(foco=4, cd=0, uso=1, mult=2.4, nunca_erra=True, queimar=2)),
])
registrar_especializacao("engenhoqueiro", "automatos", "Engenheiro de Autômatos",
    "Invocações mecânicas com duração limitada: peças que lutam por você, por pouco tempo.", [
    N("Autômato Sentinela", "Um boneco de latão que odeia a névoa.", "ativa",
      at=A(foco=2, cd=4, mult=0.7, nunca_erra=True, invocar=0.9, invocar_turnos=3)),
    N("Engrenagens Afiadas", "Dentes novos, má vontade antiga.", "passiva",
      ef=[("invoc", 20)]),
    N("Oficina Portátil", "Cada golpe deixa sobras úteis.", "passiva",
      ef=[("barr_ini", 8), ("acerto_barr", 2), ("vida", 8)]),
    N("Protocolo de Defesa", "A Descarga também carrega os escudos.", "modificador",
      ef=[("tec_barr", 10), ("tec_foco", 20)]),
    N("Legião de Fuligem", "Há mais peças do que explicação.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=1.0, nunca_erra=True, invocar=1.0, invocar_turnos=3)),
])
registrar_especializacao("engenhoqueiro", "inventor", "Inventor do Paradoxo",
    "Energia acumulada, sobrecarga e instabilidade: a máquina que não deveria funcionar.", [
    N("Capacitor Instável", "Um pouco de você vai na bateria.", "ativa",
      at=A(foco=1, cd=3, mult=0.8, nunca_erra=True, ganho_foco=2, hp_custo=6)),
    N("Energia Acumulada", "O excesso volta como golpe.", "passiva",
      ef=[("acerto_foco", 20), ("dano_se:foco_cheio", 18)]),
    N("Sobrecarga Controlada", "Quase controlada.", "passiva",
      ef=[("ciclo", 1), ("crit", 6), ("vida", 12)]),
    N("Instabilidade Útil", "A Descarga custa menos e às vezes dobra.", "modificador",
      ef=[("tec_extra", 20), ("tec_custo", 1)]),
    N("Paradoxo Mecânico", "O mecanismo só funciona porque ninguém olha.", "ativa",
      at=A(foco=3, cd=0, uso=1, mult=2.4, nunca_erra=True, ganho_foco=2, hp_custo=12)),
])


# ============================================================
# MOTOR DE EFEITOS DA BUILD
# ============================================================

NOME_STATUS = {
    "queimar": "em chamas", "veneno": "envenenado", "sangria": "sangrando",
    "marca": "marcado", "fraco": "enfraquecido", "atordoar": "atordoado",
}


def agregar_build(nos: dict[str, int]) -> dict[str, float]:
    """
    Soma os efeitos de todos os nós comprados (valor x rank) e aplica os
    limites de CAPS. É a ÚNICA fonte dos números usados em combate, o que
    impede acúmulo ilimitado, venha de onde vier.
    """
    soma: dict[str, float] = {}
    for nid, rank in nos.items():
        no = NOS.get(nid)
        if no is None:
            continue
        r = max(1, min(int(rank), no.max_rank))
        for chave, valor in no.efeitos:
            soma[chave] = soma.get(chave, 0.0) + valor * r

    for chave in list(soma):
        base = chave.partition(":")[0]
        if base == "dano_se":
            limite = CAP_REGRA_DANO
        elif base == "st":
            limite = CAP_STATUS_CHANCE
        elif base == "tec_st":
            limite = 100
        else:
            limite = CAPS.get(chave)
        if limite is not None:
            soma[chave] = min(soma[chave], limite)
    return soma


def adicionar_barreira(run, quantidade: int) -> int:
    """Soma barreira respeitando o teto da build (CAP_BARREIRA_TOTAL)."""
    teto = max(1, int(run.vida_maxima * CAP_BARREIRA_TOTAL))
    real = max(0, min(int(quantidade), teto - run.barreira))
    run.barreira += real
    return real


@dataclass
class BuildAtivo:
    """Build carregada do banco para UMA run, com o estado de combate."""
    classe_key: str
    spec_id: str
    nos: dict[str, int]
    agg: dict[str, float]
    ativas: list[NoSpec]

    # estado por combate (zerado em resetar_combate)
    cd: dict[str, int] = field(default_factory=dict)
    usos: dict[str, int] = field(default_factory=dict)
    combo: int = 0
    cura_combate: int = 0
    barr_combate: int = 0
    contra_combate: int = 0
    folego_combate: bool = False
    esq_anterior: bool = False
    perdida_combate: int = 0
    rewind_usado: bool = False
    prep_pronto: bool = False
    eco_pendente: int = 0
    eco_armado_pct: int = 0
    eco_armado_hits: int = 0
    foco_acerto_turno: bool = False
    foco_crit_turno: bool = False
    paradoxo_turno: bool = False
    invocacoes: list[dict] = field(default_factory=list)

    # estado por run
    folego_run: int = 0

    def resetar_combate(self) -> None:
        """Cada combate começa limpo: recargas, usos e contadores."""
        self.cd.clear()
        self.usos.clear()
        self.combo = 0
        self.cura_combate = 0
        self.barr_combate = 0
        self.contra_combate = 0
        self.folego_combate = False
        self.esq_anterior = False
        self.perdida_combate = 0
        self.rewind_usado = False
        self.prep_pronto = self.agg.get("prep", 0) > 0
        self.eco_pendente = 0
        self.eco_armado_pct = 0
        self.eco_armado_hits = 0
        self.foco_acerto_turno = False
        self.foco_crit_turno = False
        self.paradoxo_turno = False
        self.invocacoes.clear()

    def curar(self, run, quantidade: int) -> int:
        """Cura vinda da build, limitada a CAP_CURA_COMBATE por combate."""
        livre = int(run.vida_maxima * CAP_CURA_COMBATE) - self.cura_combate
        if livre <= 0 or quantidade <= 0:
            return 0
        real = run.curar(min(quantidade, livre))
        self.cura_combate += real
        return real


def montar_build(classe_key: str, spec_id: Optional[str],
                 nos: dict[str, int]) -> Optional[BuildAtivo]:
    """Cria a BuildAtivo a partir do que está salvo (None se não houver)."""
    if not spec_id or spec_id not in ESPECS or not nos:
        return None
    espec = ESPECS[spec_id]
    if espec.classe != classe_key:
        return None
    validos = {nid: rank for nid, rank in nos.items()
               if nid in NOS and NOS[nid].spec == spec_id}
    if not validos:
        return None
    ativas = sorted((NOS[n] for n in validos if NOS[n].ativa is not None),
                    key=lambda n: n.ordem)
    return BuildAtivo(classe_key, spec_id, validos, agregar_build(validos),
                      ativas)


# Condições de "dano_se:*": (run, inimigo, ataque) -> bool.
COND = {
    "critico": lambda r, i, a: a.critico,
    "tecnica": lambda r, i, a: r.golpe_tecnica,
    "basico": lambda r, i, a: not r.golpe_tecnica and not r.golpe_ativa,
    "ferido": lambda r, i, a: i.vida <= i.vida_maxima * 0.5,
    "saudavel": lambda r, i, a: i.vida >= i.vida_maxima * 0.75,
    "queimando": lambda r, i, a: i.queimadura > 0,
    "envenenado": lambda r, i, a: i.veneno > 0,
    "sangrando": lambda r, i, a: i.sangria > 0,
    "marcado": lambda r, i, a: i.marca > 0,
    "atordoado": lambda r, i, a: i.atordoado,
    "debil": lambda r, i, a: i.status_ativos() > 0,
    "vida_baixa": lambda r, i, a: r.vida <= r.vida_maxima * 0.4,
    "vida_cheia": lambda r, i, a: r.vida >= r.vida_maxima * 0.8,
    "barreira": lambda r, i, a: r.barreira > 0,
    "guarda": lambda r, i, a: r.guarda,
    "esquiva": lambda r, i, a: r.esquiva,
    "foco_cheio": lambda r, i, a: r.foco >= FOCO_MAX,
    "primeiro": lambda r, i, a: r.golpes_combate == 0,
    "chefe": lambda r, i, a: i.spec.categoria in ("mini_chefe", "chefe", "deus"),
}


def aplicar_status(run, inimigo, st: str, magnitude: int = 0) -> bool:
    """
    Aplica um status à criatura respeitando imunidades e limites.
    Devolve True se o efeito foi aplicado.
    """
    nome = inimigo.spec.nome
    if st in inimigo.imunidades:
        run.log.append(f"🛡️ {nome} é imune a esse efeito.")
        return False

    if st == "atordoar":
        if inimigo.spec.categoria == "mini_chefe" and inimigo.atordoado_usos >= 1:
            run.log.append(f"💪 {nome} resiste a um novo atordoamento.")
            return False
        inimigo.atordoado = True
        inimigo.atordoado_usos += 1
    elif st == "queimar":
        inimigo.queimadura = max(inimigo.queimadura, magnitude or 2)
    elif st == "veneno":
        inimigo.veneno = min(CAP_VENENO, inimigo.veneno + (magnitude or 1))
        inimigo.veneno_turnos = 3
    elif st == "sangria":
        inimigo.sangria = max(inimigo.sangria, magnitude or 3)
    elif st == "marca":
        inimigo.marca = max(inimigo.marca, magnitude or 2)
    elif st == "fraco":
        inimigo.fraqueza = max(inimigo.fraqueza, magnitude or 2)
    else:
        return False

    run.log.append(f"🧪 {nome} fica {NOME_STATUS[st]}.")
    return True


def processar_dots_inimigo(run, inimigo) -> None:
    """Veneno e sangria da build no início do turno da criatura."""
    fator = FATOR_DOT.get(inimigo.spec.categoria, 1.0)

    if inimigo.veneno > 0:
        dano = int(inimigo.veneno * (2 + run.nivel // 4) * fator)
        if dano > 0:
            inimigo.vida = max(0, inimigo.vida - max(1, dano))
            run.log.append(
                f"☠️ O veneno ({inimigo.veneno}x) causa {max(1, dano)} de "
                f"dano a {inimigo.spec.nome}.")
        inimigo.veneno_turnos -= 1
        if inimigo.veneno_turnos <= 0:
            inimigo.veneno = 0

    if inimigo.vida > 0 and inimigo.sangria > 0:
        dano = int((4 + run.nivel // 2) * fator)
        if dano > 0:
            inimigo.vida = max(0, inimigo.vida - max(1, dano))
            run.log.append(
                f"🩸 O sangramento causa {max(1, dano)} de dano a "
                f"{inimigo.spec.nome}.")
        inimigo.sangria -= 1


class EfeitoBuild(Efeito):
    """
    Efeito ÚNICO por run que aplica a build inteira (todas as chaves
    agregadas). Entra em run.efeitos() logo depois da passiva da classe,
    então usa os mesmos hooks do motor, sem criar um segundo combate.
    """

    nome = "Build"
    descricao = "Efeitos da sua especialização."

    def __init__(self, build: BuildAtivo):
        self.b = build
        self._aplicado = False

    # ---------- início da run / do combate ----------

    def ao_obter(self, run) -> None:
        """Atributos e parâmetros de passivas: aplicados UMA vez por run."""
        if self._aplicado:
            return
        self._aplicado = True
        a = self.b.agg

        run.ataque += int(a.get("atq", 0))
        run.defesa += int(a.get("def", 0))
        vida = int(a.get("vida", 0))
        if vida:
            run.vida_maxima += vida
            run.curar(vida)
        run.barreira_inicial = max(run.barreira_inicial,
                                   int(a.get("barr_ini", 0)))
        run.foco_por_combate = min(
            3, run.foco_por_combate + int(a.get("foco_ini", 0)))
        # Parâmetros lidos pelas passivas originais (sem duplicar bônus).
        run.ciclo_passiva = max(2, 3 - int(a.get("ciclo", 0)))
        run.alquimista_max = 5 + int(a.get("alq_max", 0))
        run.alq_extra = int(a.get("alq_carga", 0))
        run.alq_queima_extra = int(a.get("alq_queima", 0))
        run.fator_guarda = max(0.35, 0.5 - a.get("guarda_red", 0) / 100)
        run.mult_crit_extra = a.get("crit_mult", 0) / 100

    def ao_iniciar_combate(self, run, inimigo) -> None:
        self.b.resetar_combate()

    # ---------- dano causado ----------

    def bonus_critico(self, run) -> int:
        return int(self.b.agg.get("crit", 0))

    def modificar_dano_causado(self, run, ataque) -> int:
        a, b, ini = self.b.agg, self.b, run.inimigo
        pct = 0.0

        for chave, valor in a.items():
            if chave.startswith("dano_se:") and \
                    COND[chave[8:]](run, ini, ataque):
                pct += valor
        if a.get("combo"):
            pct += b.combo * a["combo"]
        if a.get("dano_falta"):
            pct += a["dano_falta"] * (
                1 - run.vida / max(1, run.vida_maxima))
        if b.prep_pronto:
            b.prep_pronto = False
            pct += a.get("prep", 0)

        aposta = a.get("aposta", 0)
        if aposta:
            sorte = random.random() * 100
            if sorte < aposta:
                pct += 60
                run.ganhar_foco(1)
                run.log.append("🎲 Sorte torta: o paradoxo joga a seu favor!")
            elif sorte < aposta * 1.5:
                pct -= 25
                run.log.append("🎲 Azar: o paradoxo cobra a conta.")

        pct = max(-50.0, min(float(CAP_DANO_PCT), pct))
        dano = int(ataque.dano * (1 + pct / 100))

        dano += int(run.defesa * a.get("dano_def", 0) / 100)
        dano += int(run.barreira * a.get("dano_barr", 0) / 100)
        if a.get("perf") and not run.ignorou_defesa:
            dano += int((ini.defesa // 2) * min(100, a["perf"]) / 100)

        if abs(pct) >= 1:
            run.log.append(f"🧩 Build: {pct:+.0f}% de dano.")
        return dano

    def ao_causar_dano(self, run, dano_real: int) -> None:
        if dano_real <= 0:
            return
        a, b, ini = self.b.agg, self.b, run.inimigo

        run.golpes_combate += 1
        run.ultimo_dano_real = dano_real
        b.combo = min(CAP_COMBO, b.combo + 1) if a.get("combo") else 0

        if ini is not None and ini.vida > 0:
            for st in ("queimar", "veneno", "sangria", "marca", "fraco"):
                chance = a.get("st:" + st, 0)
                if chance and random.random() * 100 < chance:
                    aplicar_status(run, ini, st)

        if a.get("acerto_barr"):
            self.barreira_build(run, int(a["acerto_barr"]))
        if (a.get("acerto_foco") and not b.foco_acerto_turno
                and random.random() * 100 < a["acerto_foco"]):
            if run.ganhar_foco(1):
                b.foco_acerto_turno = True
                run.log.append("⚡ Energia acumulada: +1 Foco.")

        if run.ultimo_critico:
            if a.get("crit_foco") and not b.foco_crit_turno:
                if run.ganhar_foco(int(a["crit_foco"])):
                    b.foco_crit_turno = True
                    run.log.append("⚡ O crítico devolve Foco.")
            if a.get("crit_barr"):
                self.barreira_build(run, int(a["crit_barr"]))

        # Roubo de vida: SOMENTE o Vampiro (a passiva dele já cura a base).
        if b.classe_key == "vampiro":
            if a.get("roubo"):
                cura = b.curar(run, max(1, int(dano_real * a["roubo"] / 100)))
                if cura:
                    run.log.append(f"🩸 Gosto de sangue: +{cura} de vida.")
            if a.get("roubo_barr") and run.vida >= run.vida_maxima:
                potencial = int(dano_real * (0.25 + a.get("roubo", 0) / 100))
                extra = self.barreira_build(
                    run, int(potencial * a["roubo_barr"] / 100))
                if extra:
                    run.log.append(f"🩸 O excesso vira {extra} de barreira.")

        # Ecos e paradoxo: golpes de FIM DE TURNO (nunca geram turno extra).
        if a.get("eco"):
            b.eco_pendente += int(dano_real * a["eco"] / 100)
        if b.eco_armado_hits > 0:
            b.eco_pendente += int(dano_real * b.eco_armado_pct / 100)
            b.eco_armado_hits -= 1
        if (a.get("paradoxo") and not b.paradoxo_turno
                and random.random() * 100 < a["paradoxo"]):
            b.paradoxo_turno = True
            b.eco_pendente += int(dano_real * 0.6)
            run.log.append("🌀 Paradoxo: o golpe vai se repetir.")

    def barreira_build(self, run, quantidade: int) -> int:
        """Barreira de gatilhos: limite por combate e teto total."""
        livre = int(run.vida_maxima * CAP_BARREIRA_COMBATE) - self.b.barr_combate
        real = adicionar_barreira(run, max(0, min(int(quantidade), livre)))
        self.b.barr_combate += real
        return real

    # ---------- dano recebido ----------

    def modificar_dano_recebido(self, run, dano: int) -> int:
        if dano <= 0:
            return dano
        a, b = self.b.agg, self.b

        esq = a.get("esq", 0)
        if esq:
            pode = not b.esq_anterior      # nunca 2 esquivas seguidas
            b.esq_anterior = False
            if pode and random.random() * 100 < esq:
                b.esq_anterior = True
                run.esquivou_agora = True
                run.log.append("🌫️ Build: você esquiva do golpe!")
                return 0

        if a.get("red"):
            dano = int(dano * (1 - min(a["red"], 40) / 100))
        if a.get("red_flat"):
            dano -= int(min(a["red_flat"], 6))
        return max(1, dano)

    def ao_golpe_recebido(self, run, inimigo, perdida: int) -> None:
        if run.esquivou_agora:
            return
        a, b = self.b.agg, self.b

        b.perdida_combate += perdida
        if perdida > 0:
            b.combo = 0
        if a.get("barr_golpe"):
            self.barreira_build(run, int(a["barr_golpe"]))

        espinho = int(a.get("espinho", 0)
                      + run.defesa * a.get("espinho_def", 0) / 100)
        if espinho > 0 and inimigo.vida > 0:
            espinho = min(espinho, max(3, int(inimigo.vida_maxima * 0.10)))
            inimigo.vida = max(0, inimigo.vida - espinho)
            run.log.append(f"🌵 Espinhos: {espinho} de dano a {inimigo.spec.nome}.")

        if (a.get("contra") and inimigo.vida > 0
                and b.contra_combate < CONTRA_MAX_COMBATE
                and random.random() * 100 < a["contra"]):
            b.contra_combate += 1
            dano = max(1, int(run.ataque * 0.5) - inimigo.defesa // 2)
            inimigo.vida = max(0, inimigo.vida - dano)
            run.log.append(f"↩️ Contra-ataque: {dano} de dano.")

    def ao_morte(self, run) -> bool:
        """Último fôlego: 1x por combate, no máximo FOLEGO_MAX_RUN por run."""
        b = self.b
        if (b.agg.get("folego") and not b.folego_combate
                and b.folego_run < FOLEGO_MAX_RUN):
            b.folego_combate = True
            b.folego_run += 1
            run.vida = 1
            adicionar_barreira(run, 8)
            run.log.append("💠 Último fôlego: você resiste com 1 de vida!")
            return True
        return False

    # ---------- turnos, técnica e defesa ----------

    def ao_fim_turno(self, run) -> None:
        a, b, ini = self.b.agg, self.b, run.inimigo

        if ini is not None and ini.vida > 0:
            if b.eco_pendente > 0:
                dano = min(ini.vida, max(1, b.eco_pendente))
                ini.vida -= dano
                b.eco_pendente = 0
                run.log.append(f"🔁 Eco: {dano} de dano a {ini.spec.nome}.")
            for inv in list(b.invocacoes):
                if ini.vida <= 0:
                    break
                dano = max(2, int(run.ataque * inv["mult"]
                                  * (1 + a.get("invoc", 0) / 100))
                           - ini.defesa // 2)
                ini.vida = max(0, ini.vida - dano)
                inv["turnos"] -= 1
                run.log.append(f"⚙️ {inv['nome']} ataca: {dano} de dano.")
                if inv["turnos"] <= 0:
                    b.invocacoes.remove(inv)
                    run.log.append(f"⚙️ {inv['nome']} se desmonta.")

        if a.get("regen"):
            cura = b.curar(run, max(1, int(run.vida_maxima * a["regen"] / 100)))
            if cura:
                run.log.append(f"🌿 Regeneração: +{cura} de vida.")

        if (a.get("rewind") and not b.rewind_usado
                and run.vida <= run.vida_maxima * 0.30
                and b.perdida_combate > 0):
            b.rewind_usado = True
            cura = b.curar(run, min(int(run.vida_maxima * 0.25),
                                    int(b.perdida_combate * a["rewind"] / 100)))
            if cura:
                run.log.append(f"⏪ Rewind: o tempo devolve {cura} de vida.")

        for chave in list(b.cd):
            b.cd[chave] = max(0, b.cd[chave] - 1)
        b.foco_acerto_turno = b.foco_crit_turno = b.paradoxo_turno = False

    def ao_tecnica(self, run) -> None:
        a, b, ini = self.b.agg, self.b, run.inimigo

        if a.get("tec_cura"):
            cura = b.curar(run, max(1, int(run.vida_maxima * a["tec_cura"] / 100)))
            if cura:
                run.log.append(f"✨ A técnica cura {cura} de vida.")
        if a.get("tec_barr"):
            ganho = self.barreira_build(run, int(a["tec_barr"]))
            if ganho:
                run.log.append(f"🛡️ A técnica concede {ganho} de barreira.")
        if a.get("tec_foco") and random.random() * 100 < a["tec_foco"]:
            if run.ganhar_foco(1):
                run.log.append("⚡ A técnica devolve 1 Foco.")

        if ini is not None and ini.vida > 0:
            for st in STATUS:
                chance = a.get("tec_st:" + st, 0)
                if chance and random.random() * 100 < chance:
                    aplicar_status(run, ini, st)
            if (a.get("tec_extra") and run.ultimo_dano_real > 0
                    and random.random() * 100 < a["tec_extra"]):
                dano = min(ini.vida, max(1, int(run.ultimo_dano_real * 0.5)))
                ini.vida -= dano
                run.log.append(f"💥 Segundo golpe da técnica: {dano} de dano.")

    def ao_defender(self, run) -> None:
        if self.b.agg.get("foco_guarda"):
            if run.ganhar_foco(int(self.b.agg["foco_guarda"])):
                run.log.append("⚡ Postura firme: +1 Foco ao guardar.")

    def ao_inimigo_derrotado(self, run, inimigo) -> None:
        a, b = self.b.agg, self.b
        if a.get("abate_cura"):
            cura = b.curar(run, max(1, int(run.vida_maxima * a["abate_cura"] / 100)))
            if cura:
                run.log.append(f"🌱 Colheita: +{cura} de vida.")
        if a.get("abate_foco"):
            run.ganhar_foco(int(a["abate_foco"]))
        b.invocacoes.clear()


# ============================================================
# HABILIDADES ATIVAS
# ============================================================

def executar_ativa(run, no: NoSpec) -> None:
    """
    Executa uma habilidade ativa da build. O Foco já foi gasto pelo botão;
    se algo impedir o uso, o Foco é devolvido. Reaproveita executar_ataque,
    então todos os efeitos de passivas, relíquias e build continuam valendo.
    """
    p, b, ini = no.ativa, run.build, run.inimigo
    if p is None or b is None or ini is None:
        return

    if b.cd.get(no.id, 0) > 0 or (p.uso and b.usos.get(no.id, 0) >= p.uso):
        run.ganhar_foco(p.foco)
        run.log.append("⏳ A habilidade ainda não está pronta.")
        return
    if run.ataque_bloqueado and p.mult is not None:
        run.ataque_bloqueado = False
        run.ganhar_foco(p.foco)
        run.log.append("⏳ O tempo falha: a habilidade se perde e o Foco volta.")
        return

    b.cd[no.id] = p.cd + 1          # +1: o fim deste turno já desconta 1
    b.usos[no.id] = b.usos.get(no.id, 0) + 1
    run.log.append(f"🌀 **{no.nome}**")

    run.golpe_ativa = True
    try:
        if p.hp_custo:
            perda = min(max(1, int(run.vida_maxima * p.hp_custo / 100)),
                        run.vida - 1)
            if perda > 0:
                run.vida -= perda
                run.log.append(f"🩸 O preço: você perde {perda} de vida.")

        if p.mult is not None:
            mult = p.mult
            if p.exec and ini.vida <= ini.vida_maxima * EXECUCAO_LIMITE:
                mult *= EXECUCAO_MULT
                run.log.append("☠️ O alvo está à beira do fim: a execução se agrava.")
            bonus = p.fixo + int(run.defesa * p.fixo_def / 100)
            if p.carga and run.alquimista_cargas > 0:
                bonus += run.alquimista_cargas * p.carga
                run.log.append(
                    f"⚗️ {run.alquimista_cargas} carga(s) consumida(s).")
                run.alquimista_cargas = 0
            executar_ataque(
                run, mult=mult, forcar_critico=p.crit,
                nunca_erra=p.nunca_erra, ignora_defesa=p.ignora_def,
                bonus_fixo=bonus, nome_golpe=no.nome)
    finally:
        run.golpe_ativa = False

    if ini.vida > 0:
        for st, valor in (("queimar", p.queimar), ("veneno", p.veneno),
                          ("sangria", p.sangria), ("marca", p.marca),
                          ("fraco", p.fraco)):
            if valor:
                aplicar_status(run, ini, st, valor)
        if p.atordoar:
            aplicar_status(run, ini, "atordoar")

    if p.cura:
        cura = b.curar(run, max(1, int(run.vida_maxima * p.cura / 100)))
        run.log.append(f"✨ Você recupera {cura} de vida.")
    if p.barr:
        ganho = adicionar_barreira(run, p.barr)
        run.log.append(f"🛡️ +{ganho} de barreira.")
    if p.guarda:
        run.guarda = True
        run.log.append("🛡️ Guarda erguida para o próximo golpe.")
    if p.esq:
        run.esquiva = True
        run.log.append("🌀 Esquiva armada para o próximo golpe.")
    if p.ganho_foco:
        run.ganhar_foco(p.ganho_foco)
        run.log.append(f"⚡ +{p.ganho_foco} Foco.")
    if p.ganho_cargas:
        run.alquimista_cargas = min(run.alquimista_max,
                                    run.alquimista_cargas + p.ganho_cargas)
        run.log.append(f"⚗️ Cargas: {run.alquimista_cargas}/{run.alquimista_max}.")
    if p.invocar:
        if len(b.invocacoes) >= MAX_INVOCACOES:
            antiga = b.invocacoes.pop(0)
            run.log.append(f"⚙️ {antiga['nome']} é substituído.")
        b.invocacoes.append({"nome": no.nome, "mult": p.invocar,
                             "turnos": p.invocar_turnos})
        run.log.append(f"⚙️ {no.nome} entra em campo por {p.invocar_turnos} turnos.")
    if p.eco_armar:
        b.eco_armado_pct = p.eco_armar
        b.eco_armado_hits = 2
        run.log.append("🔁 Os próximos 2 golpes vão ecoar.")
    if p.dado:
        _rolar_dado(run, no)


def _rolar_dado(run, no: NoSpec) -> None:
    """Resultado aleatório do Lance do Destino (média favorável, risco real)."""
    b, sorte = run.build, random.random()
    if sorte < 0.25:
        run.log.append("🎲 Face dourada: o paradoxo ataca por você!")
        run.golpe_ativa = True
        try:
            executar_ataque(run, mult=1.8, nunca_erra=True, nome_golpe=no.nome)
        finally:
            run.golpe_ativa = False
    elif sorte < 0.50:
        run.ganhar_foco(2)
        run.log.append("🎲 Face prateada: +2 Foco.")
    elif sorte < 0.70:
        cura = b.curar(run, max(1, int(run.vida_maxima * 0.12)))
        run.log.append(f"🎲 Face verde: +{cura} de vida.")
    elif sorte < 0.90:
        adicionar_barreira(run, 14)
        run.guarda = True
        run.log.append("🎲 Face azul: barreira e guarda erguida.")
    else:
        perda = min(max(1, int(run.vida_maxima * 0.06)), run.vida - 1)
        if perda > 0:
            run.vida -= perda
        run.log.append(f"🎲 Face rachada: o paradoxo cobra {max(perda, 0)} de vida.")


# ============================================================
# TEXTOS E ESTADO DOS NÓS (usados pelo /build e pela API)
# ============================================================

def texto_ativa(p: AtivaSpec) -> str:
    """Descrição mecânica de uma habilidade ativa."""
    partes = []
    if p.mult is not None:
        base = f"ataca com {int(p.mult * 100)}% do dano"
        marcas = [t for t, ok in (("nunca erra", p.nunca_erra),
                                  ("ignora a defesa", p.ignora_def),
                                  ("crítico garantido", p.crit)) if ok]
        partes.append(base + (f" ({', '.join(marcas)})" if marcas else ""))
    if p.fixo_def:
        partes.append(f"+{p.fixo_def}% da sua defesa como dano")
    if p.carga:
        partes.append(f"consome as cargas (+{p.carga} de dano cada)")
    if p.exec:
        partes.append(f"x{EXECUCAO_MULT:g} contra alvo com {int(EXECUCAO_LIMITE * 100)}% de vida ou menos")
    if p.hp_custo:
        partes.append(f"custa {p.hp_custo}% da vida máxima (nunca mata)")
    if p.cura:
        partes.append(f"cura {p.cura}% da vida máxima")
    if p.barr:
        partes.append(f"+{p.barr} de barreira")
    if p.guarda:
        partes.append("ergue a guarda")
    if p.esq:
        partes.append("arma uma esquiva")
    if p.ganho_foco:
        partes.append(f"+{p.ganho_foco} Foco")
    if p.ganho_cargas:
        partes.append(f"+{p.ganho_cargas} cargas de Reação em Cadeia")
    for nome, valor, un in (("queima", p.queimar, "turno(s)"),
                            ("envenena", p.veneno, "acúmulo(s)"),
                            ("causa sangramento", p.sangria, "turno(s)"),
                            ("marca", p.marca, "golpe(s)"),
                            ("enfraquece", p.fraco, "turno(s)")):
        if valor:
            partes.append(f"{nome} ({valor} {un})")
    if p.atordoar:
        partes.append("atordoa (não funciona em chefes e deuses)")
    if p.invocar:
        partes.append(f"invoca uma construção por {p.invocar_turnos} turnos "
                      f"({int(p.invocar * 100)}% do seu ataque)")
    if p.eco_armar:
        partes.append(f"os próximos 2 golpes ecoam ({p.eco_armar}%)")
    if p.dado:
        partes.append("rola o destino: golpe, Foco, cura, barreira ou azar")
    uso = f" · {p.uso}x por combate" if p.uso else ""
    recarga = f" · recarga {p.cd}" if p.cd else ""
    return (f"⚡ {p.foco} Foco{recarga}{uso}: " + "; ".join(partes) + ".")


def texto_no(no: NoSpec) -> str:
    """Texto completo de um nó: história + efeitos mecânicos."""
    linhas = [f"*{no.lore}*"]
    if no.ativa is not None:
        linhas.append(texto_ativa(no.ativa))
    for chave, valor in no.efeitos:
        por_rank = " por nível" if no.max_rank > 1 else ""
        linhas.append(f"• {texto_efeito(chave, valor)}{por_rank}")
    return "\n".join(linhas)


def estado_no(no: NoSpec, spec_id: Optional[str], nos: dict[str, int],
              nivel: int) -> str:
    """adquirido | maximo | disponivel | nivel | prereq | outra | sem_spec"""
    if spec_id is None:
        return "sem_spec"
    if no.spec != spec_id:
        return "outra"
    rank = nos.get(no.id, 0)
    if rank >= no.max_rank:
        return "maximo"
    if any(nos.get(pre, 0) < 1 for pre in no.prereqs):
        return "prereq"
    if nivel < no.nivel_min:
        return "nivel"
    return "disponivel" if rank == 0 else "evoluir"


def arvore_json(classe: str) -> dict:
    """
    Contrato de dados para a futura página web: a mesma árvore, somente
    leitura. O navegador NUNCA define custos nem concede nós; ele envia o
    id do nó e o servidor valida tudo (ver repo.desbloquear).
    """
    return {
        "classe": classe,
        "especializacoes": [
            {"id": e.id, "nome": e.nome, "descricao": e.descricao,
             "nos": [
                 {"id": n.id, "ordem": n.ordem, "nome": n.nome,
                  "tipo": n.tipo, "descricao": texto_no(NOS[n.id]),
                  "custo": custo_no(n), "nivel_min": n.nivel_min,
                  "prereqs": list(n.prereqs), "max_rank": n.max_rank,
                  "suprema": n.suprema}
                 for n in (NOS[i] for i in e.nos)]}
            for e in especs_da_classe(classe)],
    }


# ============================================================
# PERSISTÊNCIA DA BUILD (SQLite, mesmo banco da economia)
# ============================================================

class BuildIndisponivel(RuntimeError):
    """A economia (XpAndCoins) não está carregada ou não tem a API _tx."""


class MercadoIndisponivel(RuntimeError):
    """A economia (XpAndCoins) não está carregada ou não tem a API _tx."""


@dataclass
class ResultadoCompra:
    status: str              # ok | saldo | indisponivel | invalido
    saldo: int = 0
    custo: int = 0
    faltam: int = 0


class MercadoRepo:
    """Compra atômica: débito e item são gravados na MESMA transação.

    Assim como BuildRepo, usa apenas a API *_tx da economia; nunca abre
    uma segunda conexão dentro de ``with eco.transacao()``.
    """

    def __init__(self, obter_economia: Callable[[], object]):
        self._obter_economia = obter_economia

    def _eco(self):
        eco = self._obter_economia()
        if eco is None:
            raise MercadoIndisponivel(
                "O módulo de economia (XpAndCoins) não está carregado.")
        for nome in ("transacao", "obter_saldo_tx", "alterar_coins_tx"):
            if not hasattr(eco, nome):
                raise MercadoIndisponivel(
                    f"A economia não expõe {nome}().")
        return eco

    def movimentar(self, guild_id: int, user_id: int, diferenca: int) -> ResultadoCompra:
        """Debita (ou credita, se diferenca > 0) de forma atômica."""
        eco = self._eco()
        custo = max(0, -diferenca)
        with eco.transacao() as db:
            saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            if diferenca < 0 and saldo < custo:
                return ResultadoCompra("saldo", saldo, custo, custo - saldo)
            saldo = eco.alterar_coins_tx(db, guild_id, user_id, diferenca)
        return ResultadoCompra("ok", saldo, custo)

    def comprar_item(
        self,
        guild_id: int,
        user_id: int,
        chave: str,
        quantidade: int = 1,
        preco_unitario: Optional[int] = None,
        persistir: bool = True,
    ) -> ResultadoCompra:
        """Compra item do catálogo; grava o inventário na mesma transação."""
        item = ITENS.get(chave)
        if item is None or quantidade < 1:
            return ResultadoCompra("invalido")
        custo = (item.preco if preco_unitario is None
                 else preco_unitario) * quantidade
        eco = self._eco()
        with eco.transacao() as db:
            saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            if saldo < custo:
                return ResultadoCompra("saldo", saldo, custo, custo - saldo)
            saldo = eco.alterar_coins_tx(db, guild_id, user_id, -custo)
            if persistir:
                guardar_item_tx(db, guild_id, user_id, chave, quantidade)
        return ResultadoCompra("ok", saldo, custo)


@dataclass
class ResultadoNo:
    status: str              # ok | inexistente | sem_spec | outra | nivel | prereq | maximo | saldo
    no: Optional[NoSpec] = None
    rank: int = 0
    pago_credito: int = 0
    pago_abysmus: int = 0
    saldo: int = 0
    faltam: int = 0


@dataclass
class ResultadoReset:
    status: str              # ok | livre | nada | saldo
    taxa: int = 0
    reembolso: int = 0
    saldo: int = 0
    creditos: int = 0
    nos: int = 0


SCHEMA_BUILD = (
    """
    CREATE TABLE IF NOT EXISTS rt_build_state (
        guild_id  INTEGER NOT NULL,
        user_id   INTEGER NOT NULL,
        class_key TEXT    NOT NULL,
        spec_id   TEXT    NOT NULL,
        chosen_at TEXT    NOT NULL,
        PRIMARY KEY (guild_id, user_id, class_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rt_build_nodes (
        guild_id     INTEGER NOT NULL,
        user_id      INTEGER NOT NULL,
        class_key    TEXT    NOT NULL,
        node_id      TEXT    NOT NULL,
        rank         INTEGER NOT NULL CHECK (rank >= 1),
        paid_credit  INTEGER NOT NULL DEFAULT 0 CHECK (paid_credit >= 0),
        paid_abysmus INTEGER NOT NULL DEFAULT 0 CHECK (paid_abysmus >= 0),
        acquired_at  TEXT    NOT NULL,
        PRIMARY KEY (guild_id, user_id, node_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rt_build_nodes_class "
    "ON rt_build_nodes (guild_id, user_id, class_key)",
    """
    CREATE TABLE IF NOT EXISTS rt_build_credit (
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        credits  INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
        PRIMARY KEY (guild_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rt_build_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        class_key  TEXT,
        action     TEXT    NOT NULL,
        node_id    TEXT,
        abysmus    INTEGER NOT NULL DEFAULT 0,
        credit     INTEGER NOT NULL DEFAULT 0,
        detail     TEXT    NOT NULL DEFAULT '',
        created_at TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rt_build_log_user "
    "ON rt_build_log (guild_id, user_id, id DESC)",
)


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BuildRepo:
    """
    Regras de desbloqueio e persistência. TODAS as operações que mexem em
    Abysmus rodam na MESMA transação da economia (XpAndCoins.transacao):
    débito + nó + histórico são gravados juntos ou nada é gravado.

    Dentro de um bloco "with eco.transacao()" nunca chame métodos da
    economia que abrem a própria transação (obter_dados, alterar_coins):
    use apenas os *_tx.
    """

    def __init__(self, obter_economia: Callable[[], object]):
        self._obter_economia = obter_economia

    def _eco(self):
        eco = self._obter_economia()
        if eco is None:
            raise BuildIndisponivel("O módulo de economia (XpAndCoins) não está carregado.")
        for nome in ("transacao", "obter_saldo_tx", "alterar_coins_tx",
                     "obter_dados"):
            if not hasattr(eco, nome):
                raise BuildIndisponivel(
                    f"O XpAndCoins precisa do método '{nome}'.")
        return eco

    def iniciar_schema(self) -> None:
        """Cria as tabelas (nunca apaga nada)."""
        with self._eco().transacao() as db:
            for comando in SCHEMA_BUILD:
                db.execute(comando)

    # ---------- leitura ----------

    def conta(self, guild_id: int, user_id: int) -> tuple[int, int]:
        """(nível de conta, saldo de Abysmus) pela API pública da economia."""
        dados = self._eco().obter_dados(guild_id, user_id)
        return dados[1], dados[2]

    @staticmethod
    def _ler_classe(db, guild_id, user_id, classe):
        linha = db.execute(
            "SELECT spec_id FROM rt_build_state "
            "WHERE guild_id = ? AND user_id = ? AND class_key = ?",
            (guild_id, user_id, classe)).fetchone()
        nos = {r[0]: r[1] for r in db.execute(
            "SELECT node_id, rank FROM rt_build_nodes "
            "WHERE guild_id = ? AND user_id = ? AND class_key = ?",
            (guild_id, user_id, classe))}
        return (linha[0] if linha else None), nos

    def carregar(self, guild_id, user_id, classe):
        """(spec_id | None, {nó: rank}) de uma classe."""
        with self._eco().transacao() as db:
            return self._ler_classe(db, guild_id, user_id, classe)

    def resumo(self, guild_id, user_id):
        """(pontos de build, {classe: (spec_id | None, {nó: rank})})."""
        with self._eco().transacao() as db:
            linha = db.execute(
                "SELECT credits FROM rt_build_credit "
                "WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)).fetchone()
            estados = {c: self._ler_classe(db, guild_id, user_id, c)
                       for c in CLASSES}
        return (linha[0] if linha else 0), estados

    # ---------- escolha de especialização ----------

    def escolher_spec(self, guild_id, user_id, classe, spec_id,
                      nivel: int) -> str:
        """ok | inexistente | nivel | travada (já gastou nós; use o reset)."""
        espec = ESPECS.get(spec_id)
        if espec is None or espec.classe != classe:
            return "inexistente"
        if nivel < NIVEL_ESPECIALIZACAO:
            return "nivel"

        with self._eco().transacao() as db:
            atual, nos = self._ler_classe(db, guild_id, user_id, classe)
            if nos and atual != spec_id:
                return "travada"
            db.execute(
                "INSERT INTO rt_build_state (guild_id, user_id, class_key,"
                " spec_id, chosen_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (guild_id, user_id, class_key) "
                "DO UPDATE SET spec_id = excluded.spec_id, "
                "chosen_at = excluded.chosen_at",
                (guild_id, user_id, classe, spec_id, _agora_iso()))
            db.execute(
                "INSERT INTO rt_build_log (guild_id, user_id, class_key,"
                " action, detail, created_at) VALUES (?, ?, ?, 'spec', ?, ?)",
                (guild_id, user_id, classe, spec_id, _agora_iso()))
        return "ok"

    # ---------- compra de nós ----------

    def desbloquear(self, guild_id, user_id, node_id: str,
                    nivel: int) -> ResultadoNo:
        """
        Compra o próximo nível de um nó. Valida TUDO aqui (o cliente nunca
        decide custo nem permissão): especialização, nível, pré-requisitos,
        limite de rank e fundos. Usa pontos de build devolvidos primeiro e
        completa com Abysmus. Atômico.
        """
        no = NOS.get(node_id)
        if no is None:
            return ResultadoNo("inexistente")
        eco = self._eco()

        with eco.transacao() as db:
            spec_id, nos = self._ler_classe(db, guild_id, user_id, no.classe)
            if spec_id is None:
                return ResultadoNo("sem_spec", no)
            if spec_id != no.spec:
                return ResultadoNo("outra", no)
            rank = nos.get(no.id, 0)
            if rank >= no.max_rank:
                return ResultadoNo("maximo", no, rank)
            if any(nos.get(pre, 0) < 1 for pre in no.prereqs):
                return ResultadoNo("prereq", no, rank)
            if nivel < no.nivel_min:
                return ResultadoNo("nivel", no, rank)

            custo = custo_no(no)
            linha = db.execute(
                "SELECT credits FROM rt_build_credit "
                "WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)).fetchone()
            credito = linha[0] if linha else 0
            usar_credito = min(credito, custo)
            usar_abysmus = custo - usar_credito

            saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            if saldo < usar_abysmus:
                return ResultadoNo("saldo", no, rank, saldo=saldo,
                                   faltam=usar_abysmus - saldo)

            if usar_abysmus:
                saldo = eco.alterar_coins_tx(db, guild_id, user_id,
                                             -usar_abysmus)
            if usar_credito:
                db.execute(
                    "UPDATE rt_build_credit SET credits = credits - ? "
                    "WHERE guild_id = ? AND user_id = ?",
                    (usar_credito, guild_id, user_id))
            db.execute(
                "INSERT INTO rt_build_nodes (guild_id, user_id, class_key,"
                " node_id, rank, paid_credit, paid_abysmus, acquired_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?, ?) "
                "ON CONFLICT (guild_id, user_id, node_id) DO UPDATE SET "
                " rank = rank + 1,"
                " paid_credit = paid_credit + excluded.paid_credit,"
                " paid_abysmus = paid_abysmus + excluded.paid_abysmus",
                (guild_id, user_id, no.classe, no.id, usar_credito,
                 usar_abysmus, _agora_iso()))
            db.execute(
                "INSERT INTO rt_build_log (guild_id, user_id, class_key,"
                " action, node_id, abysmus, credit, detail, created_at) "
                "VALUES (?, ?, ?, 'unlock', ?, ?, ?, ?, ?)",
                (guild_id, user_id, no.classe, no.id, usar_abysmus,
                 usar_credito, f"rank {rank + 1}", _agora_iso()))

        return ResultadoNo("ok", no, rank + 1, usar_credito, usar_abysmus,
                           saldo)

    # ---------- redefinição ----------

    def previa_reset(self, guild_id, user_id, classe) -> ResultadoReset:
        """Mostra o que o reset faria, sem alterar nada."""
        with self._eco().transacao() as db:
            spec_id, nos = self._ler_classe(db, guild_id, user_id, classe)
            reembolso = db.execute(
                "SELECT COALESCE(SUM(paid_credit + paid_abysmus), 0) "
                "FROM rt_build_nodes WHERE guild_id = ? AND user_id = ? "
                "AND class_key = ?", (guild_id, user_id, classe)
            ).fetchone()[0]
        if spec_id is None and not nos:
            return ResultadoReset("nada")
        if not nos:
            return ResultadoReset("livre")
        return ResultadoReset("ok", CUSTO_RESET_ABYSMUS, reembolso,
                              nos=len(nos))

    def resetar(self, guild_id, user_id, classe) -> ResultadoReset:
        """
        Paga a taxa (CUSTO_RESET_ABYSMUS), devolve os PONTOS gastos como
        pontos de build e apaga a árvore da classe. Atômico: ou tudo
        acontece, ou nada. Sem nós comprados, trocar a especialização é
        grátis.
        """
        eco = self._eco()
        with eco.transacao() as db:
            spec_id, nos = self._ler_classe(db, guild_id, user_id, classe)
            if spec_id is None and not nos:
                return ResultadoReset("nada")

            reembolso = db.execute(
                "SELECT COALESCE(SUM(paid_credit + paid_abysmus), 0) "
                "FROM rt_build_nodes WHERE guild_id = ? AND user_id = ? "
                "AND class_key = ?", (guild_id, user_id, classe)
            ).fetchone()[0]

            taxa = CUSTO_RESET_ABYSMUS if nos else 0
            saldo = eco.obter_saldo_tx(db, guild_id, user_id)
            if saldo < taxa:
                return ResultadoReset("saldo", taxa, reembolso, saldo,
                                      nos=len(nos))
            if taxa:
                saldo = eco.alterar_coins_tx(db, guild_id, user_id, -taxa)

            if reembolso:
                db.execute(
                    "INSERT INTO rt_build_credit (guild_id, user_id, credits)"
                    " VALUES (?, ?, ?) ON CONFLICT (guild_id, user_id) "
                    "DO UPDATE SET credits = credits + excluded.credits",
                    (guild_id, user_id, reembolso))
            db.execute(
                "DELETE FROM rt_build_nodes WHERE guild_id = ? AND user_id = ?"
                " AND class_key = ?", (guild_id, user_id, classe))
            db.execute(
                "DELETE FROM rt_build_state WHERE guild_id = ? AND user_id = ?"
                " AND class_key = ?", (guild_id, user_id, classe))
            db.execute(
                "INSERT INTO rt_build_log (guild_id, user_id, class_key,"
                " action, abysmus, credit, detail, created_at) "
                "VALUES (?, ?, ?, 'reset', ?, ?, ?, ?)",
                (guild_id, user_id, classe, taxa, reembolso,
                 f"{spec_id}; {len(nos)} nó(s)", _agora_iso()))
            linha = db.execute(
                "SELECT credits FROM rt_build_credit "
                "WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)).fetchone()
            creditos = linha[0] if linha else 0

        return ResultadoReset("ok" if taxa else "livre", taxa, reembolso,
                              saldo, creditos, len(nos))

    def historico(self, guild_id, user_id, limite: int = 15):
        with self._eco().transacao() as db:
            return db.execute(
                "SELECT created_at, class_key, action, node_id, abysmus, "
                "credit, detail FROM rt_build_log WHERE guild_id = ? AND "
                "user_id = ? ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, limite)).fetchall()


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

TITULOS_TIPO = {
    "passivo": "⚙️ Passivos — equipados no início da run",
    "consumivel": "🧪 Consumíveis — usados na mochila durante o combate",
    "artefato": "🔮 Artefatos — equipados no início da run",
    "estrategico": "🎯 Estratégicos — 1 uso por run na mochila",
}


def _linha_item_mercado(chave: str, item: ItemSpec) -> str:
    """Linha compacta do mercado, com o limite certo para cada tipo."""
    if item.tipo in ("passivo", "artefato"):
        limite = f" (máx. {item.limite}/run)"
    elif item.limite_run:
        limite = f" (máx. {item.limite_run}/run)"
    else:
        limite = ""
    return (f"`{chave}` **{item.nome}** — {item.preco} 🪙{limite}\n"
            f"{item.descricao}")


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
    if inimigo.acao_pendente is not None:
        acao = inimigo.acao_pendente
        aviso = ("⚡ Guardar ou atordoar interrompe." if acao.interrompivel
                 else "Não pode ser interrompida.")
        return (
            f"👁️ **Intenção:** **{acao.nome}** — {acao.descricao}\n{aviso}"
        )
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
            f"**Técnica:** {tecnica.nome} ({run.custo_tecnica()}⚡)\n"
            f"**Nível da run:** {run.nivel} · **Abates:** {run.abates}\n"
            f"**Vida:** {run.vida}/{run.vida_maxima}\n"
            f"**Foco:** {barra_foco(run)} ({run.foco}/{FOCO_MAX})\n"
            f"**Ataque:** {run.ataque}"
            + (f" (+{run.ataque_bonus} temporário)" if run.ataque_bonus else "")
            + f" · **Defesa:** {run.defesa}\n"
            f"**Status:** {texto_status(run)}\n"
            f"**XP da run:** {run.xp} · **Abysmus:** {run.abysmus}"
        ),
        color=discord.Color.dark_purple(),
    )

    if run.evento_ativo is not None:
        restam = run.evento_restante
        embed.add_field(
            name=f"🌌 Evento: {run.evento_ativo.nome}"
                 + (f" (mais {restam} encontro(s))" if restam else ""),
            value=texto_evento(run.evento_ativo)[:1024], inline=False)

    if inimigo:
        habilidade = inimigo.habilidade
        efeitos_inimigo = []
        if inimigo.queimadura > 0:
            efeitos_inimigo.append(f"🔥 Em chamas ({inimigo.queimadura})")
        if inimigo.veneno > 0:
            efeitos_inimigo.append(f"☠️ Veneno x{inimigo.veneno}")
        if inimigo.sangria > 0:
            efeitos_inimigo.append(f"🩸 Sangrando ({inimigo.sangria})")
        if inimigo.marca > 0:
            efeitos_inimigo.append(f"🎯 Marcado ({inimigo.marca})")
        if inimigo.fraqueza > 0:
            efeitos_inimigo.append(f"📉 Enfraquecido ({inimigo.fraqueza})")
        if inimigo.atordoado:
            efeitos_inimigo.append("💫 Atordoado")
        if inimigo.protecao > 0:
            efeitos_inimigo.append("🛡️ Postura defensiva")
        if inimigo.acao_pendente is not None:
            efeitos_inimigo.append(
                f"⚠️ Preparando {inimigo.acao_pendente.nome}")
        chamas = ("\n**Efeitos:** " + " · ".join(efeitos_inimigo)
                  if efeitos_inimigo else "")
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

    if run.build is not None:
        embed.add_field(name=f"Build: {ESPECS[run.build.spec_id].nome}",
                        value=texto_build_run(run)[:1024], inline=False)

    reliquias = "\n".join(
        f"• {r.nome}: {r.descricao}" for r in run.reliquias
    ) or "Nenhuma relíquia encontrada."
    embed.add_field(name="Relíquias", value=reliquias[:1024], inline=False)

    if run.equipados or run.itens_efeitos:
        linhas_equipados = [f"• {e}" for e in run.equipados]
        linhas_equipados += [
            f"• 🔮 {e.nome} — {e.descricao}" for e in run.itens_efeitos
        ]
        embed.add_field(
            name="Equipado da mochila (esta run)",
            value="\n".join(linhas_equipados)[:1024],
            inline=False,
        )

    if run.consumiveis:
        linhas_mochila = []
        for chave, qtd in sorted(run.consumiveis.items()):
            item = ITENS.get(chave)
            if item is not None and qtd > 0:
                linhas_mochila.append(f"• {item.nome} ×{qtd}")
        if linhas_mochila:
            embed.add_field(
                name="🎒 Mochila de combate",
                value="\n".join(linhas_mochila)[:1024],
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
            f"Concentrar -{CUSTO_CONCENTRAR}⚡ · Técnica -{run.custo_tecnica()}⚡"
        )
    )
    return embed


def criar_embed_mercado() -> discord.Embed:
    """Loja organizada por tipo de item e do mais barato ao mais caro."""
    embed = discord.Embed(
        title="🛒 Mercado da Ruptura",
        description=(
            "Preços em **Abysmus**. **Passivos** e **artefatos** são equipados "
            "automaticamente quando a próxima run começa. **Consumíveis** e "
            "**estratégicos** ficam na mochila de combate: usá-los gasta a "
            "sua ação e o item é consumido."
        ),
        color=discord.Color.gold(),
    )
    for tipo in TIPOS_ITEM:
        if tipo == "passivo":
            for efeito, titulo in TITULOS_ITEM.items():
                itens = sorted(
                    ((k, i) for k, i in ITENS.items()
                     if i.tipo == tipo and i.efeito == efeito),
                    key=lambda par: par[1].preco,
                )
                if not itens:
                    continue
                linhas = [_linha_item_mercado(k, i) for k, i in itens]
                embed.add_field(name=titulo[:256], value="\n".join(linhas)[:1024],
                                inline=False)
            continue
        itens = sorted(
            ((k, i) for k, i in ITENS.items() if i.tipo == tipo),
            key=lambda par: par[1].preco,
        )
        if not itens:
            continue
        linhas = [_linha_item_mercado(k, i) for k, i in itens]
        embed.add_field(name=TITULOS_TIPO[tipo][:256],
                        value="\n".join(linhas)[:1024], inline=False)
    embed.set_footer(
        text="Comprar: s!market comprar CHAVE quantidade · Mochila: s!inventario"
    )
    return embed


def criar_embed_mercador_run(run: RunState) -> discord.Embed:
    """Vitrine do mercador que aparece antes de chefe/deus."""
    mercador = run.mercador
    if mercador is None:
        return criar_embed(run)
    categoria = run.categoria_pendente
    titulo = ("🛒 Mercador do Intervalo"
              + (f" — antes do {rotulo_categoria(categoria)}" if categoria else ""))
    embed = discord.Embed(
        title=titulo,
        description=(
            f"**Nível {run.nivel}** · Saldo: **{mercador.saldo} Abysmus**\n"
            "Consumíveis e estratégicos entram na mochila e ficam no "
            "inventário. **Artefatos** e **forja** valem somente nesta run. "
            "Escolha uma oferta e clique em **Comprar**."
        ),
        color=discord.Color.gold(),
    )
    for tipo, rotulo in (
        ("consumivel", "🧪 Consumíveis"),
        ("estrategico", "🎯 Estratégicos"),
        ("artefato", "🔮 Artefatos"),
        ("forja", "🔥 Forja da run"),
    ):
        linhas = []
        for indice, oferta in enumerate(mercador.ofertas):
            if oferta.categoria != tipo:
                continue
            preco = preco_oferta(run, oferta)
            estado = " · ✅ comprado" if oferta.comprado else ""
            linhas.append(
                f"`{indice + 1}` **{oferta.nome}** — **{preco} Abysmus**"
                f"{estado}\n{oferta.descricao}"
            )
        if linhas:
            embed.add_field(name=rotulo, value="\n".join(linhas)[:1024],
                            inline=False)
    embed.set_footer(
        text=(f"Forja: {run.forja_usos}/{FORJA_LIMITE} aprimoramentos · "
              "as compras são atômicas e debitam Abysmus reais.")
    )
    return embed


def criar_embed_mochila(run: RunState) -> discord.Embed:
    """Mochila de combate: consumíveis e estratégicos disponíveis na run."""
    embed = discord.Embed(
        title="🎒 Mochila de combate",
        description=(
            "Usar um item gasta a sua ação: o inimigo age em seguida. "
            "O item é consumido do inventário."
        ),
        color=discord.Color.dark_gold(),
    )
    linhas = []
    for chave, qtd in sorted(run.consumiveis.items()):
        item = ITENS.get(chave)
        if item is None or qtd <= 0:
            continue
        usados = run.consumiveis_usados.get(chave, 0)
        limite = (f" · usados {usados}/{item.limite_run}"
                  if item.limite_run else "")
        linhas.append(
            f"`{chave}` **{item.nome}** ×{qtd}{limite}\n{item.descricao}")
    if linhas:
        embed.add_field(name="Itens disponíveis", value="\n".join(linhas)[:1024],
                        inline=False)
    else:
        embed.add_field(name="Itens disponíveis",
                        value="A mochila está vazia.", inline=False)
    embed.set_footer(text="Escolha um item no menu abaixo ou volte ao combate.")
    return embed


def criar_embed_escolha(run: RunState) -> discord.Embed:
    """Tela de decisão de um evento dinâmico."""
    evento = run.evento_ativo
    embed = discord.Embed(
        title=f"🌌 {evento.nome if evento else 'Evento'}",
        description=(evento.descricao if evento else ""),
        color=discord.Color.dark_teal(),
    )
    if evento and evento.escolhas:
        linhas = [
            f"**{i + 1}. {e.rotulo}** — {e.descricao}"
            for i, e in enumerate(evento.escolhas)
        ]
        embed.add_field(name="Escolha uma opção", value="\n".join(linhas)[:1024],
                        inline=False)
    embed.set_footer(text="A escolha é definitiva para este evento.")
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


def texto_build_run(run: RunState) -> str:
    """Resumo da build no embed da run: ativas e recursos."""
    b = run.build
    linhas = []
    for no in b.ativas:
        estado = motivo_indisponivel(run, no, curto=True) or "pronta"
        linhas.append(f"• **{no.nome}** — {estado} ({no.ativa.foco}⚡)")
    if b.invocacoes:
        linhas.append("⚙️ Invocações: " + ", ".join(
            f"{i['nome']} ({i['turnos']})" for i in b.invocacoes))
    if b.combo:
        linhas.append(f"🔗 Combo x{b.combo}")
    return "\n".join(linhas) or "Somente passivas."


def motivo_indisponivel(run: RunState, no: NoSpec,
                        curto: bool = False) -> str:
    """Por que a ativa não pode ser usada agora ('' = pode)."""
    p, b = no.ativa, run.build
    if b.cd.get(no.id, 0) > 0:
        return (f"recarga {b.cd[no.id]}" if curto else
                f"⏳ **{no.nome}** está em recarga ({b.cd[no.id]} turno(s)).")
    if p.uso and b.usos.get(no.id, 0) >= p.uso:
        return "usada" if curto else \
            f"⏳ **{no.nome}** só pode ser usada {p.uso}x por combate."
    if run.foco < p.foco:
        return f"Foco {run.foco}/{p.foco}" if curto else \
            f"Foco insuficiente ({run.foco}/{p.foco} ⚡)."
    return ""


class SelecaoAtiva(discord.ui.Select):
    """Menu das habilidades ativas da build durante a run."""

    def __init__(self, tela: "TelaCombate"):
        self.tela = tela
        super().__init__(placeholder="Habilidades da build", min_values=1,
                         max_values=1, options=self._opcoes(), row=1)

    def _opcoes(self) -> list[discord.SelectOption]:
        run = self.tela.run
        return [discord.SelectOption(
            label=f"{no.nome} ({no.ativa.foco}⚡)"[:100], value=no.id,
            description=(motivo_indisponivel(run, no, curto=True)
                         or "pronta")[:100])
            for no in run.build.ativas]

    def atualizar(self) -> None:
        self.options = self._opcoes()

    async def callback(self, interaction: discord.Interaction):
        await self.tela.usar_ativa(interaction, self.values[0])


# ============================================================
# INTERFACE DA BUILD (/build)
# ============================================================

def texto_resultado_no(res: ResultadoNo) -> str:
    """Mensagem amigável para o resultado de uma compra de nó."""
    no = res.no
    nome = no.nome if no else "?"
    if res.status == "ok":
        pago = []
        if res.pago_credito:
            pago.append(f"{res.pago_credito} ponto(s) devolvido(s)")
        if res.pago_abysmus:
            pago.append(f"{res.pago_abysmus} Abysmus")
        rank = f" (nível {res.rank}/{no.max_rank})" if no.max_rank > 1 else ""
        return (f"✅ **{nome}**{rank} desbloqueado por "
                f"{' + '.join(pago) or 'nada'}. Saldo: {res.saldo:,} Abysmus.")
    return {
        "inexistente": "❌ Esse nó não existe.",
        "sem_spec": "❌ Escolha uma especialização antes de comprar nós.",
        "outra": "❌ Esse nó pertence a outra especialização desta classe.",
        "maximo": f"ℹ️ **{nome}** já está no nível máximo.",
        "prereq": f"🔒 Falta um pré-requisito para **{nome}**.",
        "nivel": (f"🔒 **{nome}** exige nível de conta {no.nivel_min if no else '?'}."),
        "saldo": (f"❌ Abysmus insuficiente: faltam {res.faltam:,} "
                  f"(você tem {res.saldo:,})."),
    }.get(res.status, "❌ Não foi possível concluir.")


def texto_resultado_reset(res: ResultadoReset) -> str:
    if res.status == "ok":
        return (f"♻️ Build redefinida. Taxa paga: {res.taxa} Abysmus. "
                f"{res.reembolso} ponto(s) de build devolvido(s) "
                f"(total disponível: {res.creditos}). Saldo: {res.saldo:,}.")
    if res.status == "livre":
        return "♻️ Especialização liberada (sem nós comprados, sem taxa)."
    if res.status == "ativa":
        return "🔒 Termine a run atual antes de redefinir a build."
    if res.status == "saldo":
        return (f"❌ A taxa é de {res.taxa} Abysmus e você tem "
                f"{res.saldo:,}. Nada foi alterado.")
    return "ℹ️ Essa classe ainda não tem build para redefinir."


class BuildHub(discord.ui.View):
    """
    Central da build: escolher especialização, ver a árvore, comprar nós
    com Abysmus, comparar caminhos e redefinir (taxa). Só o dono usa.
    """

    def __init__(self, cog: "RupturaTemporal", interaction: discord.Interaction,
                 classe: Optional[str] = None, modo: Optional[str] = None):
        super().__init__(timeout=300)
        self.cog = cog
        self.origem = interaction
        self.dono_id = interaction.user.id
        self.guild_id = interaction.guild_id
        self.classe = classe
        self.modo = modo or ("geral" if classe is None else "arvore")
        self.no_sel: Optional[str] = None
        self.aviso = ""
        self.nivel = 0
        self.saldo = 0
        self.creditos = 0
        self.estados: dict = {}
        self.previa: Optional[ResultadoReset] = None

    # ---------- dados ----------

    async def carregar(self) -> None:
        """Lê nível, saldo, pontos devolvidos e as builds do banco."""
        self.nivel, self.saldo = await self.cog.build_db(
            self.cog.build_repo.conta, self.guild_id, self.dono_id)
        self.creditos, self.estados = await self.cog.build_db(
            self.cog.build_repo.resumo, self.guild_id, self.dono_id)
        if self.modo == "confirmar_reset" and self.classe:
            self.previa = await self.cog.build_db(
                self.cog.build_repo.previa_reset, self.guild_id,
                self.dono_id, self.classe)
        self._ajustar_modo()
        self._montar()

    def _estado(self):
        return self.estados.get(self.classe, (None, {}))

    def _ajustar_modo(self) -> None:
        """Garante que o modo faça sentido com o estado atual."""
        if self.classe is None:
            self.modo = "geral"
            return
        spec_id, _ = self._estado()
        if spec_id is None and self.modo in ("arvore", "no", "confirmar_no",
                                             "geral"):
            self.modo = "spec"
        elif spec_id is not None and self.modo in ("geral", "spec"):
            self.modo = "arvore"
        if self.modo in ("no", "confirmar_no") and self.no_sel not in NOS:
            self.modo = "arvore"

    def _resumo_classe(self, chave: str) -> str:
        spec_id, nos = self.estados.get(chave, (None, {}))
        if spec_id is None:
            return "sem especialização"
        return f"{ESPECS[spec_id].nome} · {sum(nos.values())} nível(is)"

    # ---------- embeds ----------

    def embed(self) -> discord.Embed:
        embed = {
            "geral": self._embed_geral, "spec": self._embed_spec,
            "arvore": self._embed_arvore, "no": self._embed_no,
            "confirmar_no": self._embed_no, "comparar": self._embed_comparar,
            "confirmar_reset": self._embed_reset,
        }[self.modo]()
        if self.aviso:
            embed.description = f"{self.aviso}\n\n{embed.description or ''}"
        embed.set_footer(
            text=f"Nível de conta {self.nivel} · 🪙 {self.saldo:,} Abysmus · "
                 f"🔷 {self.creditos} ponto(s) de build devolvido(s)")
        return embed

    def _cabecalho(self) -> str:
        return (f"**Abysmus:** {self.saldo:,} · **Nível de conta:** "
                f"{self.nivel} · **Pontos devolvidos:** {self.creditos}")

    def _embed_geral(self) -> discord.Embed:
        emb = discord.Embed(
            title="🌳 BUILD — Ruptura Temporal",
            description=(
                f"{self._cabecalho()}\n\nCada classe tem 3 especializações. "
                f"Escolha uma classe no menu abaixo. Os nós custam "
                f"**Abysmus** e a especialização é escolhida no nível "
                f"{NIVEL_ESPECIALIZACAO} de conta.\n"
                f"Redefinir uma classe custa **{CUSTO_RESET_ABYSMUS} Abysmus** "
                "e devolve os pontos gastos."),
            color=discord.Color.dark_purple())
        linhas = [f"**{c.nome}** — {self._resumo_classe(k)}"
                  for k, c in CLASSES.items()]
        emb.add_field(name="Suas classes", value="\n".join(linhas)[:1024],
                      inline=False)
        return emb

    def _embed_spec(self) -> discord.Embed:
        classe = CLASSES[self.classe]
        emb = discord.Embed(
            title=f"🌳 {classe.nome} — escolha a especialização",
            description=(
                f"{self._cabecalho()}\n\n"
                + ("Escolha no menu abaixo. É grátis e você pode trocar "
                   "enquanto não comprar nenhum nó."
                   if self.nivel >= NIVEL_ESPECIALIZACAO else
                   f"🔒 Disponível a partir do nível de conta "
                   f"{NIVEL_ESPECIALIZACAO}.")),
            color=discord.Color.dark_purple())
        for espec in especs_da_classe(self.classe):
            suprema = NOS[espec.nos[-1]]
            emb.add_field(
                name=espec.nome,
                value=(f"{espec.descricao}\n**Suprema:** {suprema.nome}")[:1024],
                inline=False)
        return emb

    def _icone(self, estado: str) -> str:
        return {"maximo": "✅", "evoluir": "🔼", "disponivel": "🟢",
                "nivel": "🔒", "prereq": "🔒"}.get(estado, "🔒")

    def _embed_arvore(self) -> discord.Embed:
        spec_id, nos = self._estado()
        espec = ESPECS[spec_id]
        emb = discord.Embed(
            title=f"🌳 {espec.nome}",
            description=f"{espec.descricao}\n\n{self._cabecalho()}",
            color=discord.Color.dark_purple())
        for nid in espec.nos:
            no = NOS[nid]
            estado = estado_no(no, spec_id, nos, self.nivel)
            rank = nos.get(nid, 0)
            rank_txt = f" ({rank}/{no.max_rank})" if no.max_rank > 1 else ""
            reqs = ", ".join(NOS[p].nome for p in no.prereqs) or "—"
            motivo = {"nivel": f" · 🔒 nível {no.nivel_min}",
                      "prereq": " · 🔒 falta pré-requisito"}.get(estado, "")
            emb.add_field(
                name=f"{self._icone(estado)} {no.ordem}. {no.nome}{rank_txt}",
                value=(f"{no.tipo} · 🪙 {custo_no(no)} · nv {no.nivel_min}"
                       f"{motivo}\nReq.: {reqs}"),
                inline=False)
        return emb

    def _embed_no(self) -> discord.Embed:
        spec_id, nos = self._estado()
        no = NOS[self.no_sel]
        estado = estado_no(no, spec_id, nos, self.nivel)
        rank = nos.get(no.id, 0)
        custo = custo_no(no)
        credito = min(self.creditos, custo)

        emb = discord.Embed(title=f"{self._icone(estado)} {no.nome}",
                            description=texto_no(no)[:3500],
                            color=discord.Color.dark_purple())
        emb.add_field(name="Tipo", value=no.tipo)
        emb.add_field(name="Nível de conta", value=str(no.nivel_min))
        emb.add_field(
            name="Custo" + (" do próximo nível" if no.max_rank > 1 else ""),
            value=(f"🪙 {custo}" + (f" ({credito} pontos devolvidos + "
                                    f"{custo - credito} Abysmus)"
                                    if credito else "")))
        if no.max_rank > 1:
            emb.add_field(name="Nível do nó", value=f"{rank}/{no.max_rank}")
        reqs = [f"{'✅' if nos.get(p, 0) >= 1 else '❌'} {NOS[p].nome}"
                for p in no.prereqs]
        emb.add_field(name="Pré-requisitos",
                      value="\n".join(reqs) or "Nenhum", inline=False)
        if self.modo == "confirmar_no":
            emb.title = f"Confirmar compra? — {no.nome}"
            emb.add_field(
                name="Você pagará",
                value=(f"🪙 {custo - credito} Abysmus"
                       + (f" + {credito} ponto(s) devolvido(s)" if credito else "")),
                inline=False)
        return emb

    def _embed_comparar(self) -> discord.Embed:
        classe = CLASSES[self.classe]
        emb = discord.Embed(
            title=f"⚖️ Comparar especializações — {classe.nome}",
            description=self._cabecalho(), color=discord.Color.dark_purple())
        for espec in especs_da_classe(self.classe):
            nos = [NOS[i] for i in espec.nos]
            ativas = [n.nome for n in nos if n.ativa is not None]
            custo_total = sum(custo_no(n) * n.max_rank for n in nos)
            emb.add_field(
                name=espec.nome,
                value=(f"{espec.descricao}\n**Ativas:** {', '.join(ativas)}\n"
                       f"**Suprema:** {nos[-1].nome}\n"
                       f"**Custo total:** 🪙 {custo_total}")[:1024],
                inline=False)
        return emb

    def _embed_reset(self) -> discord.Embed:
        classe = CLASSES[self.classe]
        p = self.previa
        emb = discord.Embed(title=f"♻️ Redefinir build — {classe.nome}",
                            color=discord.Color.dark_red())
        if p is None or p.status == "nada":
            emb.description = "Essa classe ainda não tem build."
        elif p.status == "livre":
            emb.description = ("Você escolheu uma especialização mas não "
                               "comprou nós: trocar é grátis.")
        else:
            emb.description = (
                f"Isso apaga **{p.nos}** nó(s) desta classe.\n"
                f"• Taxa: **{p.taxa} Abysmus** (não reembolsável)\n"
                f"• Devolve **{p.reembolso} ponto(s) de build**, usados "
                f"antes do seu saldo nos próximos nós.\n\n{self._cabecalho()}")
        return emb

    # ---------- componentes ----------

    def _montar(self) -> None:
        self.clear_items()

        opcoes = [discord.SelectOption(
            label=c.nome[:100], value=k,
            description=self._resumo_classe(k)[:100],
            default=(k == self.classe)) for k, c in CLASSES.items()]
        menu = discord.ui.Select(placeholder="Escolha a classe…",
                                 options=opcoes, row=0)
        menu.callback = self._ao_classe
        self.add_item(menu)

        if self.classe is None:
            return
        spec_id, nos = self._estado()

        if self.modo == "spec":
            if self.nivel >= NIVEL_ESPECIALIZACAO:
                menu_spec = discord.ui.Select(
                    placeholder="Escolha a especialização…", row=1,
                    options=[discord.SelectOption(
                        label=e.nome[:100], value=e.id,
                        description=e.descricao[:100])
                        for e in especs_da_classe(self.classe)])
                menu_spec.callback = self._ao_spec
                self.add_item(menu_spec)
            self._botao("Comparar", discord.ButtonStyle.secondary,
                        self._ao_comparar, "⚖️")

        elif self.modo == "arvore":
            menu_no = discord.ui.Select(
                placeholder="Inspecione ou compre um nó…", row=1,
                options=[discord.SelectOption(
                    label=f"{NOS[i].ordem}. {NOS[i].nome}"[:100], value=i,
                    description=(f"{NOS[i].tipo} · {custo_no(NOS[i])} Abysmus"
                                 f" · nv {NOS[i].nivel_min}")[:100])
                    for i in ESPECS[spec_id].nos])
            menu_no.callback = self._ao_no
            self.add_item(menu_no)
            self._botao("Comparar", discord.ButtonStyle.secondary,
                        self._ao_comparar, "⚖️")
            self._botao("Redefinir", discord.ButtonStyle.danger,
                        self._ao_reset, "♻️")

        elif self.modo == "no":
            no = NOS[self.no_sel]
            estado = estado_no(no, spec_id, nos, self.nivel)
            self._botao("Comprar", discord.ButtonStyle.success,
                        self._ao_comprar, "🛒",
                        desativado=estado not in ("disponivel", "evoluir"))
            self._botao("Voltar", discord.ButtonStyle.secondary,
                        self._ao_voltar)

        elif self.modo == "confirmar_no":
            self._botao("Confirmar compra", discord.ButtonStyle.success,
                        self._ao_confirmar_no, "✅")
            self._botao("Cancelar", discord.ButtonStyle.secondary,
                        self._ao_cancelar)

        elif self.modo == "comparar":
            self._botao("Voltar", discord.ButtonStyle.secondary,
                        self._ao_voltar)

        elif self.modo == "confirmar_reset":
            p = self.previa
            pode = p is not None and p.status in ("ok", "livre")
            self._botao(
                f"Pagar {p.taxa} e redefinir" if p and p.status == "ok"
                else "Liberar especialização",
                discord.ButtonStyle.danger, self._ao_confirmar_reset, "♻️",
                desativado=not pode)
            self._botao("Cancelar", discord.ButtonStyle.secondary,
                        self._ao_cancelar)

    def _botao(self, rotulo, estilo, callback, emoji=None,
               desativado=False) -> None:
        botao = discord.ui.Button(label=rotulo, style=estilo, emoji=emoji,
                                  disabled=desativado, row=2)
        botao.callback = callback
        self.add_item(botao)

    async def _atualizar(self, interaction: discord.Interaction,
                         recarregar: bool = False) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        if recarregar:
            await self.carregar()
        else:
            self._ajustar_modo()
            self._montar()
        await interaction.edit_original_response(embed=self.embed(), view=self)

    # ---------- callbacks ----------

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.dono_id:
            await interaction.response.send_message(
                "Esta build pertence a outra pessoa. Use /build para abrir a sua.",
                ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        try:
            await self.origem.edit_original_response(view=None)
        except discord.HTTPException:
            pass

    async def _ao_classe(self, interaction: discord.Interaction):
        self.classe = interaction.data["values"][0]
        spec_id, _ = self._estado()
        self.modo = "arvore" if spec_id else "spec"
        self.no_sel, self.aviso = None, ""
        await self._atualizar(interaction)

    async def _ao_spec(self, interaction: discord.Interaction):
        await interaction.response.defer()
        status = await self.cog.escolher_especializacao(
            interaction.guild_id, self.dono_id, self.classe,
            interaction.data["values"][0], self.nivel)
        self.aviso = {
            "ok": "✅ Especialização escolhida.",
            "nivel": f"🔒 Exige nível de conta {NIVEL_ESPECIALIZACAO}.",
            "travada": ("🔒 Você já comprou nós de outra especialização: "
                        "use Redefinir para trocar."),
        }.get(status, "❌ Especialização inválida.")
        await self._atualizar(interaction, recarregar=True)

    async def _ao_no(self, interaction: discord.Interaction):
        self.no_sel = interaction.data["values"][0]
        self.modo, self.aviso = "no", ""
        await self._atualizar(interaction)

    async def _ao_comprar(self, interaction: discord.Interaction):
        self.modo = "confirmar_no"
        await self._atualizar(interaction)

    async def _ao_confirmar_no(self, interaction: discord.Interaction):
        await interaction.response.defer()
        res = await self.cog.comprar_no(interaction.guild_id, self.dono_id,
                                        self.no_sel, self.nivel)
        self.aviso = texto_resultado_no(res)
        self.modo = "arvore"
        await self._atualizar(interaction, recarregar=True)

    async def _ao_comparar(self, interaction: discord.Interaction):
        self.modo, self.aviso = "comparar", ""
        await self._atualizar(interaction)

    async def _ao_voltar(self, interaction: discord.Interaction):
        spec_id, _ = self._estado()
        self.modo, self.aviso = ("arvore" if spec_id else "spec"), ""
        await self._atualizar(interaction)

    async def _ao_cancelar(self, interaction: discord.Interaction):
        spec_id, _ = self._estado()
        self.modo = "arvore" if spec_id else "spec"
        self.aviso = "Cancelado."
        await self._atualizar(interaction)

    async def _ao_reset(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.modo, self.aviso = "confirmar_reset", ""
        await self._atualizar(interaction, recarregar=True)

    async def _ao_confirmar_reset(self, interaction: discord.Interaction):
        await interaction.response.defer()
        res = await self.cog.redefinir_build(interaction.guild_id,
                                             self.dono_id, self.classe)
        self.aviso = texto_resultado_reset(res)
        self.modo = "spec"
        await self._atualizar(interaction, recarregar=True)


class SelecaoConsumivel(discord.ui.Select):
    """Menu de consumíveis/estratégicos da mochila de combate."""

    def __init__(self, tela: "TelaCombate"):
        self.tela = tela
        super().__init__(placeholder="Escolha um item para usar",
                         min_values=1, max_values=1,
                         options=self._opcoes(), row=0)

    def _opcoes(self) -> list[discord.SelectOption]:
        run = self.tela.run
        opcoes = []
        for chave, qtd in sorted(run.consumiveis.items()):
            item = ITENS.get(chave)
            if item is None or qtd <= 0:
                continue
            usado = run.consumiveis_usados.get(chave, 0)
            limite = (f" · {usado}/{item.limite_run} usados"
                      if item.limite_run else "")
            opcoes.append(discord.SelectOption(
                label=f"{item.nome} ×{qtd}"[:100],
                value=chave,
                description=(item.descricao + limite)[:100],
            ))
        return opcoes or [discord.SelectOption(
            label="Mochila vazia", value="__vazio__",
            description="Compre consumíveis no mercado.")]

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__vazio__":
            await interaction.response.send_message(
                "A mochila está vazia.", ephemeral=True)
            return
        await self.tela.executar_item(interaction, self.values[0])


class MochilaView(discord.ui.View):
    """Substitui temporariamente os botões de combate pela mochila."""

    def __init__(self, tela: "TelaCombate"):
        super().__init__(timeout=TIMEOUT_RUN_SEGUNDOS)
        self.tela = tela
        self.add_item(SelecaoConsumivel(tela))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.tela.interaction_check(interaction)

    @discord.ui.button(label="Voltar ao combate", style=discord.ButtonStyle.secondary,
                       emoji="↩️", row=1)
    async def btn_voltar(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await interaction.response.defer()
        self.tela.atualizar_botoes()
        await interaction.edit_original_response(
            embed=criar_embed(self.tela.run), view=self.tela)

    async def on_timeout(self) -> None:
        if self.tela.message is None or self.tela.run.finalizada:
            return
        try:
            await self.tela.message.edit(
                embed=criar_embed(self.tela.run), view=self.tela)
        except discord.HTTPException:
            pass


class BotaoEscolhaEvento(discord.ui.Button):
    """Um botão de decisão de evento dinâmico."""

    def __init__(self, tela: "TelaCombate", indice: int, escolha: EscolhaEvento):
        super().__init__(label=escolha.rotulo[:80],
                         style=(discord.ButtonStyle.primary if indice == 0
                                else discord.ButtonStyle.secondary),
                         row=0)
        self.tela = tela
        self.indice = indice

    async def callback(self, interaction: discord.Interaction):
        await self.tela.escolher_evento(interaction, self.indice)


class EventoEscolhaView(discord.ui.View):
    """Tela de decisão de um evento dinâmico."""

    def __init__(self, tela: "TelaCombate"):
        super().__init__(timeout=TIMEOUT_RUN_SEGUNDOS)
        self.tela = tela
        evento = tela.run.evento_ativo
        if evento is not None:
            for i, escolha in enumerate(evento.escolhas[:4]):
                self.add_item(BotaoEscolhaEvento(tela, i, escolha))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.tela.interaction_check(interaction)

    @discord.ui.button(label="Voltar ao combate", style=discord.ButtonStyle.secondary,
                       emoji="↩️", row=1)
    async def btn_voltar(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await interaction.response.defer()
        self.tela.atualizar_botoes()
        await interaction.edit_original_response(
            embed=criar_embed(self.tela.run), view=self.tela)

    async def on_timeout(self) -> None:
        if self.tela.message is None or self.tela.run.finalizada:
            return
        try:
            await self.tela.message.edit(
                embed=criar_embed(self.tela.run), view=self.tela)
        except discord.HTTPException:
            pass


class SelecaoOferta(discord.ui.Select):
    """Lista de ofertas do mercador; o valor é o índice na vitrine."""

    def __init__(self, tela: "TelaMercador"):
        self.tela = tela
        super().__init__(placeholder="Escolha uma oferta do mercador",
                         min_values=1, max_values=1,
                         options=self._opcoes(), row=0)

    def _opcoes(self) -> list[discord.SelectOption]:
        run = self.tela.run
        mercador = run.mercador
        opcoes = []
        if mercador is not None:
            for indice, oferta in enumerate(mercador.ofertas):
                preco = preco_oferta(run, oferta)
                estado = " · COMPRADO" if oferta.comprado else ""
                opcoes.append(discord.SelectOption(
                    label=f"{oferta.nome} — {preco} Abysmus"[:100],
                    value=str(indice),
                    description=(oferta.categoria + estado + " · "
                                 + oferta.descricao)[:100],
                ))
        return opcoes or [discord.SelectOption(
            label="Nenhuma oferta", value="__vazio__",
            description="O mercador já foi embora.")]

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__vazio__":
            await interaction.response.send_message(
                "Não há ofertas disponíveis.", ephemeral=True)
            return
        await self.tela.comprar(interaction, int(self.values[0]))


class TelaMercador(discord.ui.View):
    """Vitrine entre combates: compra atômica, forja e saída para o chefe."""

    def __init__(self, cog: "RupturaTemporal", run: RunState):
        super().__init__(timeout=TIMEOUT_RUN_SEGUNDOS)
        self.cog = cog
        self.run = run
        self.message: Optional[discord.Message] = None
        self.add_item(SelecaoOferta(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.run.user_id:
            await interaction.response.send_message(
                "Esta run pertence a outro jogador.", ephemeral=True)
            return False
        if self.run.finalizada:
            await interaction.response.send_message(
                "Esta run já terminou.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        async with self.run.action_lock:
            if self.run.finalizada:
                return
            embed = await self.cog.finalizar_run(
                self.run, "Run abandonada no mercador do intervalo.")
            if self.message is not None:
                try:
                    await self.message.edit(content=None, embed=embed, view=None)
                except discord.HTTPException:
                    log.warning("Não foi possível editar a run %s no timeout.",
                                self.run.run_id)

    async def comprar(self, interaction: discord.Interaction,
                      indice: int) -> None:
        run = self.run
        async with run.action_lock:
            if run.mercador is None:
                await interaction.response.send_message(
                    "O mercador já foi embora.", ephemeral=True)
                return
            await interaction.response.defer()
            ok, mensagem = await self.cog.comprar_oferta_mercador(run, indice)
            run.log.clear()
            run.log.append(("✅ " if ok else "⚠️ ") + mensagem)
            nova = TelaMercador(self.cog, run)
            await interaction.edit_original_response(
                content=None, embed=criar_embed_mercador_run(run), view=nova)
            nova.message = await interaction.original_response()
            self.stop()

    @discord.ui.button(label="Continuar para o chefe",
                       style=discord.ButtonStyle.success,
                       emoji="⚔️", row=1)
    async def btn_continuar(self, interaction: discord.Interaction,
                            button: discord.ui.Button):
        run = self.run
        async with run.action_lock:
            if run.mercador is None:
                await interaction.response.send_message(
                    "O mercador já foi embora.", ephemeral=True)
                return
            await interaction.response.defer()
            self.cog.avancar_apos_mercador(run)
            nova = TelaCombate(self.cog, run)
            await interaction.edit_original_response(
                content=None, embed=criar_embed(run), view=nova)
            nova.message = await interaction.original_response()
            self.stop()


class TelaCombate(discord.ui.View):
    """Botões de combate: Atacar / Guardar / Concentrar / Técnica / Encerrar."""

    def __init__(self, cog: "RupturaTemporal", run: RunState):
        super().__init__(timeout=TIMEOUT_RUN_SEGUNDOS)
        self.cog = cog
        self.run = run
        self.message: Optional[discord.Message] = None
        self.menu_ativas: Optional["SelecaoAtiva"] = None
        if run.build is not None and run.build.ativas:
            self.menu_ativas = SelecaoAtiva(self)
            self.add_item(self.menu_ativas)
        self.btn_concentrar.label = f"Concentrar ({CUSTO_CONCENTRAR}⚡)"
        self.atualizar_botoes()

    def atualizar_botoes(self) -> None:
        """Desabilita ações que o Foco atual não paga."""
        custo = self.run.custo_tecnica()
        self.btn_tecnica.label = f"{self.run.classe.tecnica.nome} ({custo}⚡)"[:80]
        self.btn_concentrar.disabled = self.run.foco < CUSTO_CONCENTRAR
        self.btn_tecnica.disabled = self.run.foco < custo
        self.btn_mochila.disabled = not any(
            qtd > 0 for qtd in self.run.consumiveis.values())
        self.btn_evento.disabled = not (
            self.run.evento_ativo is not None
            and bool(self.run.evento_ativo.escolhas)
            and not self.run.evento_escolha_feita
        )
        if self.menu_ativas is not None:
            self.menu_ativas.atualizar()

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

        if run.vida > 0:
            for efeito in run.efeitos():     # ecos, invocações, regeneração
                efeito.ao_fim_turno(run)

        if run.vida <= 0:
            await self._finalizar(
                interaction, "Você foi consumido pela chama negra."
            )
            return

        if inimigo is not None and inimigo.vida <= 0:
            await self.cog.registrar_vitoria(run)

        if run.mercador is not None:
            # A view de combate é encerrada para o timeout dela não competir
            # com o mercador. Ao continuar, uma nova TelaCombate é criada.
            self.stop()
            vitrine = TelaMercador(self.cog, run)
            await interaction.edit_original_response(
                content=None, embed=criar_embed_mercador_run(run),
                view=vitrine,
            )
            vitrine.message = await interaction.original_response()
            return

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
        chave_acao: str = "",
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
            registrar_acao_jogador(run, chave_acao)
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
        await self._executar(interaction, acao, chave_acao="atacar")

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
            for efeito in run.efeitos():
                efeito.ao_defender(run)
        await self._executar(interaction, acao, chave_acao="guardar")

    @discord.ui.button(label="Concentrar", style=discord.ButtonStyle.primary,
                       emoji="✨", row=0)
    async def btn_concentrar(self, interaction: discord.Interaction,
                             button: discord.ui.Button):
        def acao(run: RunState) -> None:
            mult = 1 + run.conc_bonus() / 100
            cura = run.curar(int((12 + min(8, run.nivel // 2)) * mult))
            barreira = int(5 * mult)
            run.barreira += barreira
            run.log.append(
                f"✨ Você recupera {cura} de vida e ganha {barreira} de barreira."
            )
        await self._executar(interaction, acao, custo=CUSTO_CONCENTRAR,
                             chave_acao="concentrar")

    @discord.ui.button(label="Técnica", style=discord.ButtonStyle.success,
                       emoji="💥", row=0)
    async def btn_tecnica(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        custo = self.run.custo_tecnica()

        def acao(run: RunState) -> None:
            if run.ataque_bloqueado:
                run.ataque_bloqueado = False
                run.ganhar_foco(custo)  # a distorção anula a técnica; Foco devolvido
                run.log.append(
                    "⏳ O tempo falha e sua técnica se desfaz. O Foco é devolvido."
                )
                return
            run.golpe_tecnica = True
            run.ultimo_dano_real = 0
            try:
                run.classe.tecnica.acao(run)
            finally:
                run.golpe_tecnica = False
            for efeito in run.efeitos():
                efeito.ao_tecnica(run)
        await self._executar(interaction, acao, custo=custo,
                             chave_acao="tecnica")

    async def usar_ativa(self, interaction: discord.Interaction,
                         node_id: str) -> None:
        """Usa uma habilidade ativa da build (menu da run)."""
        run = self.run
        no = NOS.get(node_id)
        if no is None or no.ativa is None or run.build is None:
            await interaction.response.send_message(
                "Habilidade indisponível.", ephemeral=True)
            return
        motivo = motivo_indisponivel(run, no)
        if motivo:
            await interaction.response.send_message(motivo, ephemeral=True)
            return
        await self._executar(
            interaction, lambda r: executar_ativa(r, no), custo=no.ativa.foco,
            chave_acao="ativa")

    async def executar_item(self, interaction: discord.Interaction,
                            chave: str) -> None:
        """Usa um consumível/estratégico da mochila, gastando a ação."""
        run = self.run
        item = ITENS.get(chave)
        if item is None or item.tipo not in ("consumivel", "estrategico"):
            await interaction.response.send_message(
                "Esse item não pode ser usado em combate.", ephemeral=True)
            return

        async with run.action_lock:
            if run.finalizada:
                await interaction.response.send_message(
                    "Esta run já terminou.", ephemeral=True)
                return
            if run.consumiveis.get(chave, 0) <= 0:
                await interaction.response.send_message(
                    "Você não tem esse item na mochila.", ephemeral=True)
                return
            if (item.limite_run
                    and run.consumiveis_usados.get(chave, 0) >= item.limite_run):
                await interaction.response.send_message(
                    f"{item.nome} só pode ser usado {item.limite_run}x por run.",
                    ephemeral=True)
                return

            await interaction.response.defer()
            ok = await asyncio.to_thread(
                consumir_item, run.guild_id, run.user_id, chave, 1)
            if not ok:
                await interaction.followup.send(
                    "O inventário mudou e o item não pôde ser consumido. "
                    "Nada foi usado.", ephemeral=True)
                if self.message is not None:
                    await self.message.edit(
                        embed=criar_embed_mochila(run),
                        view=MochilaView(self))
                return

            run.log.clear()
            if item.gasta_turno:
                run.turno += 1
            aplicado, mensagem = usar_consumivel(run, chave)
            if not aplicado:
                # Segurança: devolve o item se o efeito não pôde ser aplicado.
                await asyncio.to_thread(
                    guardar_item, run.guild_id, run.user_id, chave, 1)
                await interaction.followup.send(mensagem, ephemeral=True)
                if self.message is not None:
                    await self.message.edit(
                        embed=criar_embed_mochila(run),
                        view=MochilaView(self))
                return

            if item.gasta_turno:
                registrar_acao_jogador(run, "item")
                await self._concluir_acao(interaction)
            else:
                self.atualizar_botoes()
                await interaction.edit_original_response(
                    embed=criar_embed(run), view=self)

    async def escolher_evento(self, interaction: discord.Interaction,
                              indice: int) -> None:
        """Aplica a escolha de um evento dinâmico."""
        run = self.run
        evento = run.evento_ativo
        if (evento is None or not evento.escolhas
                or run.evento_escolha_feita
                or indice < 0 or indice >= len(evento.escolhas)):
            await interaction.response.send_message(
                "Essa escolha não está mais disponível.", ephemeral=True)
            return
        escolha = evento.escolhas[indice]

        async with run.action_lock:
            if run.finalizada:
                await interaction.response.send_message(
                    "Esta run já terminou.", ephemeral=True)
                return
            if run.evento_ativo is not evento or run.evento_escolha_feita:
                await interaction.response.send_message(
                    "Essa escolha não está mais disponível.", ephemeral=True)
                return
            await interaction.response.defer()
            run.log.clear()
            mensagem = escolha.aplicar(run)
            run.evento_escolha_feita = True
            if mensagem:
                run.log.append(mensagem)
            run.evento(f"Escolha de evento: {evento.nome} -> {escolha.rotulo}.")
            verificar_morte(run)
            if run.vida <= 0:
                await self._finalizar(
                    interaction, "O evento cobrou o preço que você aceitou pagar.")
                return
            self.atualizar_botoes()
            await interaction.edit_original_response(
                embed=criar_embed(run), view=self)

    @discord.ui.button(label="Mochila", style=discord.ButtonStyle.secondary,
                       emoji="🎒", row=2)
    async def btn_mochila(self, interaction: discord.Interaction,
                          button: discord.ui.Button):
        run = self.run
        if not any(qtd > 0 for qtd in run.consumiveis.values()):
            await interaction.response.send_message(
                "🎒 Sua mochila de combate está vazia. "
                "Compre consumíveis em `s!market`.",
                ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=criar_embed_mochila(run), view=MochilaView(self))

    @discord.ui.button(label="Evento", style=discord.ButtonStyle.primary,
                       emoji="🌌", row=3)
    async def btn_evento(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        run = self.run
        evento = run.evento_ativo
        if evento is None or not evento.escolhas or run.evento_escolha_feita:
            await interaction.response.send_message(
                "Não há escolha de evento disponível agora.", ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=criar_embed_escolha(run), view=EventoEscolhaView(self))

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

        # Build: repositório (usa a transação da economia) e travas.
        self.build_repo = BuildRepo(lambda: bot.get_cog("XpAndCoins"))
        self._build_schema_ok = False
        self._build_schema_lock = asyncio.Lock()
        self._locks_build: dict[tuple[int, int], asyncio.Lock] = {}

        # Mercado: compras atômicas (débito + inventário juntos) e trava
        # por membro para impedir duas compras simultâneas.
        self.mercado_repo = MercadoRepo(lambda: bot.get_cog("XpAndCoins"))
        self._locks_mercado: dict[tuple[int, int], asyncio.Lock] = {}

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
        equipaveis = []
        mochila_itens = []
        for k, q in inventario.items():
            item = ITENS.get(k)
            if item is None:
                continue
            if item.tipo in ("consumivel", "estrategico"):
                mochila_itens.append(f"{item.nome} ×{q}")
            else:
                equipaveis.append(f"{item.nome} ×{min(q, item.limite)}")

        if equipaveis:
            mochila = ("\n\n⚙️ **Será equipado nesta run:** "
                       + ", ".join(equipaveis))
        else:
            mochila = ("\n\n🛒 Você não tem itens equipáveis. Use `s!market` "
                       "para ver passivos e artefatos.")
        if mochila_itens:
            mochila += ("\n🎒 **Mochila de combate:** "
                        + ", ".join(mochila_itens))

        mochila += ("\n🌳 Use `/build` para gastar Abysmus na "
                    "especialização da sua classe.")
        await ctx.send(
            embed=self._embed_selecao(mochila),
            view=TelaClasse(self, uid),
        )

    async def equipar_itens_passivos(self, run: RunState) -> None:
        """Equipa passivos/artefatos e monta a mochila de combate da run.

        Passivos e artefatos são consumidos do inventário no início da run
        (até item.limite). Consumíveis e estratégicos NÃO são consumidos
        agora: apenas entram no snapshot da run e são descontados quando
        usados na mochila de combate.
        """
        inventario = await asyncio.to_thread(
            listar_inventario, run.guild_id, run.user_id
        )
        for chave, qtd in inventario.items():
            item = ITENS.get(chave)
            if item is None or qtd <= 0:
                continue

            if item.tipo in ("consumivel", "estrategico"):
                run.consumiveis[chave] = run.consumiveis.get(chave, 0) + qtd
                continue

            if item.tipo not in ("passivo", "artefato"):
                continue

            usar = min(qtd, item.limite)
            ok = await asyncio.to_thread(
                consumir_item, run.guild_id, run.user_id, chave, usar
            )
            if not ok:
                continue
            if not equipar_item_da_run(run, chave, vezes=usar):
                # Nunca perde o item se o efeito não pôde ser equipado.
                await asyncio.to_thread(
                    guardar_item, run.guild_id, run.user_id, chave, usar
                )
                continue
            run.equipados.append(
                f"{item.nome} ×{usar} — {item.descricao}")

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
            classe_key=next((k for k, v in CLASSES.items() if v is classe), ""),
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

            try:
                await self.carregar_build_run(run)
            except Exception:
                log.exception("Falha ao carregar a build da run %s.",
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
        xp_evento, moeda_evento = bonus_evento(run)
        xp_ganho = max(1, int(spec.xp * multiplicador_xp * (1 + xp_evento / 100)))

        chance_moeda = {
            "normal": CHANCE_MOEDA_NORMAL,
            "mini_chefe": CHANCE_MOEDA_MINICHEFE,
            "chefe": CHANCE_MOEDA_CHEFE,
            "deus": CHANCE_MOEDA_DEUS,
        }.get(categoria, CHANCE_MOEDA_NORMAL)
        # O evento aumenta a chance, mas o Abysmus continua raro (máx. +10 pp).
        chance_moeda = min(1.0, chance_moeda + min(10.0, moeda_evento) / 100)
        moedas = 0
        if random.random() < chance_moeda:
            limites = {
                "normal": (1, 2), "mini_chefe": (1, 3),
                "chefe": (2, 4), "deus": (3, 6),
            }
            minimo, maximo = limites.get(categoria, (1, 2))
            moedas = random.randint(minimo, maximo)

        run.abates += 1
        chave_abate = f"{categoria}|{spec.nome}"
        run.abatidos[chave_abate] = run.abatidos.get(chave_abate, 0) + 1
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

        # O sorteio da categoria é feito UMA vez e reaproveitado. Sem isso,
        # o mercador poderia anunciar um chefe e criar_inimigo sortear um deus.
        categoria = run.categoria_pendente or categoria_encontro(run.nivel)
        run.categoria_pendente = categoria

        if categoria in ("chefe", "deus"):
            if abrir_mercador(run, categoria, await self.saldo_abysmus(run)):
                run.log.append(
                    f"🛒 **Um mercador surge antes do próximo encontro.** "
                    f"Ele vende consumíveis, estratégicos, artefatos e forja."
                )
                run.evento(
                    f"Mercador antes de {categoria} no nível {run.nivel} | "
                    f"ofertas={len(run.mercador.ofertas)} | "
                    f"saldo={run.mercador.saldo}"
                )
                return

        preparar_combate(run, categoria=categoria)
        proximo = run.inimigo
        run.log.append(
            f"A ruptura avança. Próximo encontro: "
            f"{rotulo_categoria(proximo.spec.categoria)} — {proximo.spec.nome}."
        )

    async def saldo_abysmus(self, run: RunState) -> int:
        """Lê o saldo real para exibir no mercador; 0 se a economia faltar."""
        cog = self.bot.get_cog("XpAndCoins")
        obter = getattr(cog, "obter_dados", None) if cog else None
        if not callable(obter):
            return 0
        try:
            dados = await asyncio.to_thread(
                obter, run.guild_id, run.user_id)
            return int(dados[2])
        except Exception:
            log.exception("Falha ao ler saldo da run %s.", run.run_id)
            return 0

    def avancar_apos_mercador(self, run: RunState) -> None:
        """Fecha o mercador e inicia o chefe/deus já sorteado."""
        categoria = run.categoria_pendente
        run.mercador = None
        preparar_combate(run, categoria=categoria)
        proximo = run.inimigo
        run.log.append(
            f"A ruptura avança. Próximo encontro: "
            f"{rotulo_categoria(proximo.spec.categoria)} — {proximo.spec.nome}."
        )

    async def comprar_oferta_mercador(
        self, run: RunState, indice: int
    ) -> tuple[bool, str]:
        """Compra uma oferta. Valida tudo ANTES do débito e usa transação."""
        mercador = run.mercador
        if mercador is None or not 0 <= indice < len(mercador.ofertas):
            return False, "Essa oferta não está disponível."
        oferta = mercador.ofertas[indice]
        motivo = motivo_bloqueio_oferta(run, oferta)
        if motivo:
            return False, motivo

        preco = preco_oferta(run, oferta)
        try:
            if oferta.categoria in ("consumivel", "estrategico"):
                res = await asyncio.to_thread(
                    self.mercado_repo.comprar_item,
                    run.guild_id, run.user_id, oferta.chave, 1, preco, True)
            elif oferta.categoria == "artefato":
                res = await asyncio.to_thread(
                    self.mercado_repo.movimentar,
                    run.guild_id, run.user_id, -preco)
            else:                          # forja: aplicada só nesta run
                res = await asyncio.to_thread(
                    self.mercado_repo.movimentar,
                    run.guild_id, run.user_id, -preco)
        except MercadoIndisponivel as exc:
            return False, str(exc)

        if res.status == "saldo":
            return False, (f"Abysmus insuficiente. Você precisa de "
                           f"**{res.custo}** Abysmus.")
        if res.status != "ok":
            return False, "A compra não pôde ser concluída."

        mensagem = aplicar_oferta_mercador(run, oferta)
        mercador.saldo = res.saldo
        run.evento(
            f"Mercador: comprou {oferta.chave} por {preco} Abysmus | "
            f"saldo={res.saldo}"
        )
        return True, f"✅ {mensagem} Saldo: **{res.saldo} Abysmus**."

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
            f"| artefatos={[e.nome for e in run.itens_efeitos]} "
            f"| mochila={run.consumiveis} usados={run.consumiveis_usados} "
            f"| duração={duracao}s | recompensa_salva={persistido}"
        )

        # Ranking (SQLite): o cog cogs/ruptura_extras.py escuta este evento.
        self.bot.dispatch(
            "ruptura_run_finalizada",
            {
                "run_id": run.run_id,
                "guild_id": run.guild_id,
                "user_id": run.user_id,
                "user_nome": run.user_nome,
                "classe_key": run.classe_key,
                "classe_nome": run.classe.nome,
                "nivel": run.nivel,
                "abates": run.abates,
                "xp": run.xp,
                "abysmus": run.abysmus,
                "duracao": duracao,
                "motivo": motivo,
                "abatidos": dict(run.abatidos),
            },
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
        """Mostra os itens comprados para a Ruptura, por tipo."""
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
                "**Passivos** e **artefatos** são equipados automaticamente "
                "quando a próxima run começa. **Consumíveis** e "
                "**estratégicos** entram na mochila de combate dessa run."
            ),
            color=discord.Color.dark_gold(),
        )

        def adicionar(titulo: str, linhas: list[str]) -> None:
            if linhas:
                embed.add_field(name=titulo[:256],
                                value="\n".join(linhas)[:1024],
                                inline=False)

        for efeito, titulo in TITULOS_ITEM.items():
            adicionar(titulo, [
                f"• **{ITENS[k].nome}** ×{q} (`{k}`) — {ITENS[k].descricao}"
                for k, q in itens.items()
                if k in ITENS
                and ITENS[k].tipo == "passivo"
                and ITENS[k].efeito == efeito
            ])

        for tipo in ("artefato", "consumivel", "estrategico"):
            adicionar(TITULOS_TIPO[tipo], [
                f"• **{ITENS[k].nome}** ×{q} (`{k}`) — {ITENS[k].descricao}"
                for k, q in itens.items()
                if k in ITENS and ITENS[k].tipo == tipo
            ])

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

        custo = item.preco * quantidade
        try:
            async with self._lock_mercado(ctx.guild.id, ctx.author.id):
                res = await asyncio.to_thread(
                    self.mercado_repo.comprar_item,
                    ctx.guild.id, ctx.author.id, chave, quantidade,
                    None, True,
                )
        except MercadoIndisponivel:
            await ctx.send(
                "Não consegui acessar o sistema de Abysmus "
                "(XpAndCoins não carregado)."
            )
            return
        except Exception:
            log.exception(
                "Falha ao comprar item | guild=%s user=%s item=%s",
                ctx.guild.id, ctx.author.id, chave,
            )
            await ctx.send(
                "A compra falhou e nada foi cobrado. Tente novamente."
            )
            return

        if res.status == "saldo":
            await ctx.send(
                f"Abysmus insuficiente. Você precisa de **{custo}** Abysmus."
            )
            return
        if res.status != "ok":
            await ctx.send("A compra não pôde ser concluída.")
            return
        saldo = res.saldo

        extra = ""
        if item.tipo in ("passivo", "artefato") and quantidade > item.limite:
            extra = (f"\nAtenção: só {item.limite} cópias são equipadas por "
                     "run; o resto fica guardado para as próximas.")
        if item.tipo in ("consumivel", "estrategico"):
            destino = ("Será usável na mochila de combate da próxima run."
                       if item.tipo == "consumivel"
                       else "Poderá ser usado 1x por run na mochila de combate.")
        else:
            destino = "Será equipado automaticamente no início da próxima run."
        await ctx.send(
            f"✅ Comprou **{quantidade}× {item.nome}** por **{custo} Abysmus**. "
            f"Saldo após a compra: **{saldo} Abysmus**.\n"
            f"{destino}{extra}"
        )

    # ========================================================
    # BUILD: serviço (usado pelo hub e pela run) e comandos slash
    # ========================================================

    async def _build_pronto(self) -> None:
        """Cria as tabelas da build uma única vez (na 1ª necessidade)."""
        if self._build_schema_ok:
            return
        async with self._build_schema_lock:
            if not self._build_schema_ok:
                await asyncio.to_thread(self.build_repo.iniciar_schema)
                self._build_schema_ok = True
                log.info("Tabelas da build prontas.")

    async def build_db(self, funcao, *args):
        """Executa uma função síncrona do repositório fora do event loop."""
        await self._build_pronto()
        return await asyncio.to_thread(funcao, *args)

    def _lock_build(self, guild_id: int, user_id: int) -> asyncio.Lock:
        return self._locks_build.setdefault((guild_id, user_id),
                                            asyncio.Lock())

    def _lock_mercado(self, guild_id: int, user_id: int) -> asyncio.Lock:
        return self._locks_mercado.setdefault((guild_id, user_id),
                                              asyncio.Lock())

    async def escolher_especializacao(self, guild_id, user_id, classe,
                                      spec_id, nivel) -> str:
        async with self._lock_build(guild_id, user_id):
            status = await self.build_db(
                self.build_repo.escolher_spec, guild_id, user_id, classe,
                spec_id, nivel)
        if status == "ok":
            log.info("[build] guild=%s user=%s classe=%s spec=%s",
                     guild_id, user_id, classe, spec_id)
        return status

    async def comprar_no(self, guild_id, user_id, node_id, nivel) -> ResultadoNo:
        async with self._lock_build(guild_id, user_id):
            res = await self.build_db(
                self.build_repo.desbloquear, guild_id, user_id, node_id,
                nivel)
        log.info("[build] compra guild=%s user=%s nó=%s -> %s (abysmus=%s, "
                 "pontos=%s)", guild_id, user_id, node_id, res.status,
                 res.pago_abysmus, res.pago_credito)
        return res

    async def redefinir_build(self, guild_id, user_id, classe) -> ResultadoReset:
        # Redefinir no meio de uma run confundiria o estado: bloqueado.
        if user_id in self.runs_ativas:
            return ResultadoReset("ativa")
        async with self._lock_build(guild_id, user_id):
            res = await self.build_db(
                self.build_repo.resetar, guild_id, user_id, classe)
        log.info("[build] reset guild=%s user=%s classe=%s -> %s (taxa=%s, "
                 "pontos devolvidos=%s)", guild_id, user_id, classe,
                 res.status, res.taxa, res.reembolso)
        return res

    async def carregar_build_run(self, run: RunState) -> None:
        """Lê a build salva e a aplica à run (o banco é a fonte oficial)."""
        if not run.guild_id or not run.classe_key:
            return
        spec_id, nos = await self.build_db(
            self.build_repo.carregar, run.guild_id, run.user_id,
            run.classe_key)
        build = montar_build(run.classe_key, spec_id, nos)
        if build is None:
            return
        efeito = EfeitoBuild(build)
        run.build, run.build_efeito = build, efeito
        efeito.ao_obter(run)
        run.evento(
            f"Build carregada | {ESPECS[build.spec_id].nome} | "
            f"{sum(build.nos.values())} nível(is) | ativas="
            f"{[n.nome for n in build.ativas]}")

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if isinstance(original, BuildIndisponivel):
            log.error("Build indisponível: %s", original)
            texto = f"❌ {original}"
        elif isinstance(error, app_commands.CommandOnCooldown):
            texto = f"⏳ Aguarde {error.retry_after:.0f}s."
        else:
            nome = interaction.command.name if interaction.command else "?"
            log.error("Erro inesperado em /%s", nome, exc_info=error)
            texto = ("❌ Ocorreu um erro inesperado. Nada foi cobrado sem "
                     "ser registrado; tente de novo.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(texto, ephemeral=True)
            else:
                await interaction.response.send_message(texto, ephemeral=True)
        except discord.HTTPException:
            pass

    async def _ac_classe(self, interaction: discord.Interaction,
                         current: str):
        termo = current.strip().casefold()
        return [app_commands.Choice(name=c.nome[:100], value=k)
                for k, c in CLASSES.items()
                if termo in k or termo in c.nome.casefold()][:25]

    @app_commands.command(
        name="build",
        description="Gaste Abysmus em especializações e monte a build das suas classes.")
    @app_commands.guild_only()
    @app_commands.describe(classe="Classe que deseja abrir (opcional).")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def build(self, interaction: discord.Interaction,
                    classe: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        if classe is not None and classe not in CLASSES:
            await interaction.followup.send(
                "❌ Classe inválida. Escolha uma da lista.", ephemeral=True)
            return
        hub = BuildHub(self, interaction, classe)
        await hub.carregar()
        await interaction.followup.send(embed=hub.embed(), view=hub,
                                        ephemeral=True)

    @build.autocomplete("classe")
    async def _ac_build(self, interaction: discord.Interaction, current: str):
        return await self._ac_classe(interaction, current)

    @app_commands.command(
        name="build_resetar",
        description=(f"Pague {CUSTO_RESET_ABYSMUS} Abysmus para refazer os "
                     "pontos gastos de uma classe."))
    @app_commands.guild_only()
    @app_commands.describe(classe="Classe cuja build será redefinida.")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def build_resetar(self, interaction: discord.Interaction,
                            classe: str):
        await interaction.response.defer(ephemeral=True)
        if classe not in CLASSES:
            await interaction.followup.send(
                "❌ Classe inválida. Escolha uma da lista.", ephemeral=True)
            return
        if interaction.user.id in self.runs_ativas:
            await interaction.followup.send(
                "🔒 Termine a run atual antes de redefinir a build.",
                ephemeral=True)
            return
        hub = BuildHub(self, interaction, classe, modo="confirmar_reset")
        await hub.carregar()
        await interaction.followup.send(embed=hub.embed(), view=hub,
                                        ephemeral=True)

    @build_resetar.autocomplete("classe")
    async def _ac_resetar(self, interaction: discord.Interaction,
                          current: str):
        return await self._ac_classe(interaction, current)


async def setup(bot: commands.Bot):
    """Ponto de entrada do cog (bot.load_extension)."""
    configurar_log_terminal()
    validar_catalogos()
    problemas = validar_arvores()
    if problemas:
        for problema in problemas:
            log.error("Árvore de builds inválida: %s", problema)
        raise RuntimeError("A árvore de builds tem erros; veja o log.")
    log.info("Builds: %d especializações, %d nós.", len(ESPECS), len(NOS))
    await bot.add_cog(RupturaTemporal(bot))
