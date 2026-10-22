"""Segredo Floresta Adentro — duelo de cartas para discord.py 2.x.

Instalação:
    Salve como cogs/GameSFA.py.
    Carregue a extensão cogs.GameSFA no seu bot.

Comando:
    /sfa duelo @adversario

Para adicionar cartas:
    Adicione uma instância de Carta à lista CARTAS.
    Efeitos disponíveis: "dano", "cura", "escudo", "drenagem",
    "ambos", "contra", "aleatorio" e "repetir".

Regras:
    - Cada jogador começa com 10 de vida e 0 de escudo.
    - Cada turno, cada jogador recebe 3 cartas aleatórias.
    - Escolhas secretas; o turno resolve quando ambos escolhem.
    - Combate contínuo até a vida de um jogador chegar a zero.
    - Escudo absorve dano; vida máxima 10; escudo máximo 6.
    - Não há energia, limite de turnos ou sistema de rodadas.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


# ============================================================
# CONFIGURAÇÃO
# ============================================================

VIDA_INICIAL = 10
VIDA_MAXIMA = 10
ESCUDO_MAXIMO = 6
OPCOES_POR_TURNO = 3
TEMPO_MENU_SEGUNDOS = 180
TEMPO_PARTIDA_SEGUNDOS = 3600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("SFA")


def log_game(evento: str, mensagem: str) -> None:
    """Imprime os eventos do jogo no terminal."""
    print(f"[SFA] [{evento}] {mensagem}", flush=True)
    logger.info("[%s] %s", evento, mensagem)


# ============================================================
# CATÁLOGO DE CARTAS
# Para adicionar uma carta, acrescente uma linha nesta lista.
# ============================================================

@dataclass(frozen=True)
class Carta:
    nome: str
    alinhamento: str
    efeito: str
    minimo: int = 0
    maximo: int = 0
    descricao: str = ""



CARTAS: list[Carta] = [
    # ==================================================
    # CAÓTICO — Abismo Eterno, Malachais e corrupção
    # ==================================================

    Carta("Golpe do Abismo", "Caótico", "dano", 2, 4,
          "Causa 2–4 de dano."),

    Carta("Execução Profana", "Caótico", "dano", 3, 5,
          "Causa 3–5 de dano."),

    Carta("Chama da Ruína", "Caótico", "dano", 1, 6,
          "Causa 1–6 de dano."),

    Carta("Maldição Voraz", "Caótico", "drenagem", 2, 3,
          "Causa dano e tenta recuperar a mesma quantidade de vida."),

    Carta("Fúria de Malachais", "Caótico", "dano", 4, 6,
          "Libera a força destrutiva do Guardião das Ruínas."),

    Carta("Cicatriz do Abismo", "Caótico", "dano", 2, 5,
          "Uma ferida alimentada por energia caótica."),

    Carta("Sacrifício Profano", "Caótico", "drenagem", 3, 6,
          "Converte a destruição do inimigo em sobrevivência."),

    Carta("Colapso da Realidade", "Caótico", "aleatorio", 3, 6,
          "A realidade se rompe e manifesta um efeito imprevisível."),

    Carta("Fome do Inominável", "Caótico", "drenagem", 1, 5,
          "Uma presença faminta consome a essência do adversário."),

    Carta("Chave da Ruína", "Caótico", "dano", 3, 4,
          "O poder de uma chave quebrada abre caminho para a destruição."),

    Carta("Incêndio do Abismo", "Caótico", "dano", 2, 6,
          "Uma chama negra devora tudo que encontra."),

    Carta("Última Maldição", "Caótico", "drenagem", 4, 4,
          "Um ataque desesperado que busca prolongar sua existência."),

    # ==================================================
    # LUMINÁRIA — Aurora Templária e Fé da Luminária
    # ==================================================

    Carta("Bênção da Luminária", "Luminária", "cura", 2, 4,
          "Recupera 2–4 de vida."),

    Carta("Luz Restauradora", "Luminária", "cura", 3, 5,
          "Recupera 3–5 de vida."),

    Carta("Último Alento", "Luminária", "cura", 1, 6,
          "Recupera 1–6 de vida."),

    Carta("Escudo Templário", "Luminária", "escudo", 2, 4,
          "Concede 2–4 de escudo sagrado."),

    Carta("Aurora Invicta", "Luminária", "cura", 4, 6,
          "A aurora renova suas forças."),

    Carta("Juramento da Fé", "Luminária", "escudo", 3, 5,
          "A fé ergue uma barreira contra a destruição."),

    Carta("Purificação Radiante", "Luminária", "cura", 2, 5,
          "A luz restaura a vitalidade do combatente."),

    Carta("Martelo da Aurora", "Luminária", "dano", 2, 5,
          "Um golpe consagrado contra as forças da escuridão."),

    Carta("Vigília Eterna", "Luminária", "escudo", 4, 6,
          "A proteção da Luminária permanece firme."),

    Carta("Milagre Improvável", "Luminária", "aleatorio", 2, 5,
          "A intervenção sagrada produz um resultado imprevisível."),

    Carta("Sacrifício da Aurora", "Luminária", "cura", 5, 5,
          "Recupera 5 de vida por meio de um último ato de fé."),

    Carta("Lança da Templária", "Luminária", "dano", 3, 4,
          "Uma arma consagrada perfura as defesas inimigas."),

    # ==================================================
    # NATURAL — Silvestres e forças ancestrais
    # ==================================================

    Carta("Equilíbrio Selvagem", "Natural", "ambos", 1, 3,
          "Causa dano e recupera vida na mesma faixa de valores."),

    Carta("Espinhos Vivos", "Natural", "ambos", 1, 2,
          "A natureza fere o adversário enquanto restaura você."),

    Carta("Casca Ancestral", "Natural", "escudo", 2, 4,
          "Concede 2–4 de escudo."),

    Carta("Muralha de Raízes", "Natural", "escudo", 3, 5,
          "Raízes antigas protegem seu corpo."),

    Carta("Floresta Revida", "Natural", "contra", 1, 3,
          "Concede escudo e causa dano ao adversário."),

    Carta("Coração da Floresta", "Natural", "cura", 3, 5,
          "A energia vital da floresta restaura sua vida."),

    Carta("Garras do Predador", "Natural", "dano", 2, 5,
          "Um ataque instintivo inspirado nos predadores de Da'kor."),

    Carta("Raízes Famintas", "Natural", "drenagem", 2, 4,
          "Raízes absorvem a vitalidade do inimigo."),

    Carta("Ciclo da Existência", "Natural", "ambos", 2, 4,
          "O ciclo natural transforma destruição em renovação."),

    Carta("Despertar Silvestre", "Natural", "aleatorio", 1, 5,
          "A floresta manifesta uma resposta imprevisível."),

    Carta("Pele de Drak'vuh", "Natural", "escudo", 4, 5,
          "A resistência ancestral protege você."),

    Carta("Vingança das Raízes", "Natural", "contra", 3, 4,
          "A natureza reage com violência contra seu adversário."),

    # ==================================================
    # NEUTRO — Véu Neutral, Merjin e paradoxos
    # ==================================================

    Carta("Drenagem de Essência", "Neutro", "drenagem", 1, 3,
          "Causa dano e tenta recuperar a mesma quantidade de vida."),

    Carta("Ordem Imprevista", "Neutro", "aleatorio", 1, 4,
          "Aleatoriamente causa dano, cura ou concede escudo."),

    Carta("Ruptura do Véu", "Neutro", "aleatorio", 2, 5,
          "O Véu se rompe e produz um efeito imprevisível."),

    Carta("Paradoxo de Merjin", "Neutro", "aleatorio", 3, 5,
          "Um erro na realidade altera o resultado do confronto."),

    Carta("Passagem Entre Mundos", "Neutro", "escudo", 2, 5,
          "Uma distorção espacial amortece os ataques recebidos."),

    Carta("Ampulheta Quebrada", "Neutro", "repetir",
          descricao="Repete o último efeito válido que você jogou."),

    Carta("Destino Incerto", "Neutro", "aleatorio", 1, 6,
          "O destino escolhe entre dano, cura ou proteção."),

    Carta("Espelho Negro", "Neutro", "repetir",
          descricao="Reflete o último efeito válido que você jogou, "
                    "conforme as regras de repetição do jogo."),

    Carta("Falha da Criação", "Neutro", "aleatorio", 2, 6,
          "Uma falha na existência gera uma manifestação imprevisível."),

    Carta("Interferência do Véu", "Neutro", "ambos", 1, 5,
          "A instabilidade do Véu afeta ataque e recuperação."),

    Carta("Ecos do Passado", "Neutro", "repetir",
          descricao="Reproduz o último efeito válido que você jogou."),

    Carta("O Instante Impossível", "Neutro", "aleatorio", 3, 4,
          "O tempo falha por um instante e altera o resultado."),

    # ==================================================
    # INDEPENDENTE — efeitos fora dos alinhamentos
    # ==================================================

    Carta("Eco Independente", "Independente", "repetir",
          descricao="Repete o último efeito válido que você jogou."),

    Carta("Roubo de Essência", "Independente", "drenagem", 2, 4,
          "Rouba vitalidade do adversário por meio de drenagem."),

    Carta("Improviso Mortal", "Independente", "aleatorio", 2, 5,
          "Uma ação imprevisível pode mudar o rumo da batalha."),

    Carta("Adaptação Instantânea", "Independente", "escudo", 2, 3,
          "Concede uma proteção improvisada."),

    Carta("Golpe Sem Bandeira", "Independente", "dano", 2, 4,
          "Um ataque sem vínculo com qualquer facção."),

    Carta("Sobrevivência Improvável", "Independente", "cura", 2, 4,
          "Recupera vida usando qualquer recurso disponível."),

    Carta("Quebra de Padrão", "Independente", "aleatorio", 1, 6,
          "Rompe as expectativas e produz um efeito imprevisível."),

    Carta("Imitação Imperfeita", "Independente", "repetir",
          descricao="Repete o último efeito válido que você jogou."),

    Carta("Instinto de Sobrevivência", "Independente", "ambos", 1, 3,
          "Ataca e recupera vida para permanecer na batalha."),

    Carta("Último Recurso", "Independente", "drenagem", 3, 5,
          "Uma tentativa desesperada de sobreviver ao confronto."),
]

EFEITOS_VALIDOS = {
    "dano",
    "cura",
    "escudo",
    "drenagem",
    "ambos",
    "contra",
    "aleatorio",
    "repetir",
}


def validar_catalogo() -> None:
    """Falha cedo no terminal se uma carta for cadastrada incorretamente."""
    if not CARTAS:
        raise RuntimeError("O catálogo CARTAS não pode estar vazio.")

    nomes = [c.nome.casefold() for c in CARTAS]
    if len(nomes) != len(set(nomes)):
        raise ValueError("Existem cartas com nomes duplicados em CARTAS.")

    for carta in CARTAS:
        if carta.efeito not in EFEITOS_VALIDOS:
            raise ValueError(
                f"Efeito inválido na carta {carta.nome}: {carta.efeito}"
            )
        if carta.efeito != "repetir":
            if carta.minimo < 0 or carta.maximo < carta.minimo:
                raise ValueError(
                    f"Intervalo inválido na carta {carta.nome}."
                )


validar_catalogo()


def clamp_vida(valor: int) -> int:
    return max(0, min(VIDA_MAXIMA, valor))


def clamp_escudo(valor: int) -> int:
    return max(0, min(ESCUDO_MAXIMO, valor))


# ============================================================
# MODELOS DO COMBATE
# ============================================================

@dataclass
class Efeito:
    carta: Carta
    tipo: str
    quantidade: int = 0
    quantidade_secundaria: int = 0
    observacao: str = ""


class PartidaSFA:
    def __init__(self, jogador1: discord.Member, jogador2: discord.Member):
        self.jogadores = [jogador1, jogador2]
        self.vida = {j.id: VIDA_INICIAL for j in self.jogadores}
        self.escudo = {j.id: 0 for j in self.jogadores}

        # Guarda a última carta jogada de cada jogador para "repetir".
        self.ultima_carta_valida: dict[int, Optional[Carta]] = {
            j.id: None for j in self.jogadores
        }

        self.opcoes: dict[int, list[Carta]] = {}
        self.escolhas: dict[int, Carta] = {}
        self.turno = 1
        self.ativa = True
        self.lock = asyncio.Lock()
        self.mensagem: Optional[discord.Message] = None
        self.mesa: Optional[MesaView] = None
        self.criada_em = asyncio.get_running_loop().time()

        self.iniciar_turno()

        log_game(
            "PARTIDA",
            f"Partida criada: {jogador1.display_name} vs "
            f"{jogador2.display_name}.",
        )

    def iniciar_turno(self) -> None:
        quantidade = min(OPCOES_POR_TURNO, len(CARTAS))
        self.opcoes = {
            jogador.id: random.sample(CARTAS, k=quantidade)
            for jogador in self.jogadores
        }
        self.escolhas.clear()

        log_game("DISTRIBUIÇÃO", f"Turno {self.turno}: cartas distribuídas.")
        for jogador in self.jogadores:
            nomes = ", ".join(c.nome for c in self.opcoes[jogador.id])
            log_game("CARTAS", f"{jogador.display_name}: {nomes}")

    def adversario(self, jogador: discord.Member) -> discord.Member:
        return next(p for p in self.jogadores if p.id != jogador.id)

    def preparar_efeito(
        self,
        jogador: discord.Member,
        carta: Carta,
        cadeia: bool = False,
    ) -> Efeito:
        """Define aleatoriedade antes de aplicar os efeitos do turno."""
        if carta.efeito == "repetir":
            anterior = self.ultima_carta_valida[jogador.id]
            if anterior is None or anterior.efeito == "repetir" or cadeia:
                return Efeito(
                    carta,
                    "falha",
                    observacao="Não havia uma carta válida para repetir.",
                )
            copiado = self.preparar_efeito(jogador, anterior, cadeia=True)
            copiado.carta = carta
            copiado.observacao = f"Repetiu o efeito de {anterior.nome}."
            return copiado

        valor = random.randint(carta.minimo, carta.maximo) if carta.maximo else 0
        secundario = 0
        tipo = carta.efeito

        if tipo == "aleatorio":
            tipo = random.choice(("dano", "cura", "escudo"))

        if carta.efeito in ("ambos", "contra"):
            secundario = random.randint(carta.minimo, carta.maximo)

        # "Repetir" não substitui a última carta válida.
        if carta.efeito != "repetir":
            self.ultima_carta_valida[jogador.id] = carta

        return Efeito(carta, tipo, valor, secundario)

    def resolver_turno(self) -> str:
        """Resolve os dois efeitos como um único turno simultâneo."""
        if len(self.escolhas) != len(self.jogadores):
            raise RuntimeError("Tentativa de resolver turno sem duas escolhas.")

        log_game("TURNO", f"Iniciando turno {self.turno}.")

        # Sorteia/prepara os efeitos de ambos antes de aplicar qualquer efeito.
        efeitos = {
            jogador.id: self.preparar_efeito(
                jogador, self.escolhas[jogador.id]
            )
            for jogador in self.jogadores
        }
        logs: dict[int, list[str]] = {j.id: [] for j in self.jogadores}

        for jogador in self.jogadores:
            efeito = efeitos[jogador.id]
            log_game(
                "REVELAÇÃO",
                f"{jogador.display_name}: {efeito.carta.nome} "
                f"({efeito.tipo}, {efeito.quantidade}).",
            )

        # Fase 1: escudos são aplicados antes dos ataques.
        for jogador in self.jogadores:
            efeito = efeitos[jogador.id]
            if efeito.tipo in ("escudo", "contra"):
                antes = self.escudo[jogador.id]
                self.escudo[jogador.id] = clamp_escudo(
                    antes + efeito.quantidade
                )
                ganho = self.escudo[jogador.id] - antes
                logs[jogador.id].append(f"ganhou {ganho} de escudo")
                log_game(
                    "ESCUDO",
                    f"{jogador.display_name}: +{ganho}; "
                    f"total {self.escudo[jogador.id]}/{ESCUDO_MAXIMO}.",
                )

        # Fase 2: todos os ataques são executados, mesmo se o atacante
        # também chegar a zero neste turno.
        for jogador in self.jogadores:
            efeito = efeitos[jogador.id]
            if efeito.tipo == "contra":
                dano = efeito.quantidade_secundaria
            elif efeito.tipo in ("dano", "drenagem", "ambos"):
                dano = efeito.quantidade
            else:
                dano = 0

            if efeito.tipo == "falha":
                logs[jogador.id].append(efeito.observacao)
                log_game("FALHA", f"{jogador.display_name}: {efeito.observacao}")

            if dano <= 0:
                continue

            alvo = self.adversario(jogador)
            escudo_antes = self.escudo[alvo.id]
            vida_antes = self.vida[alvo.id]
            absorvido = min(escudo_antes, dano)
            self.escudo[alvo.id] -= absorvido
            dano_vida = dano - absorvido
            self.vida[alvo.id] = max(0, vida_antes - dano_vida)

            logs[jogador.id].append(
                f"causou {dano} de dano; {absorvido} absorvido pelo escudo "
                f"e {dano_vida} aplicado à vida"
            )
            log_game(
                "DANO",
                f"{jogador.display_name} -> {alvo.display_name}: "
                f"dano={dano}, absorvido={absorvido}, "
                f"vida {vida_antes}->{self.vida[alvo.id]}, "
                f"escudo {escudo_antes}->{self.escudo[alvo.id]}.",
            )

        # Fase 3: cura. Um jogador com vida zero não pode ser ressuscitado
        # por uma cura do mesmo turno.
        for jogador in self.jogadores:
            efeito = efeitos[jogador.id]
            cura = 0
            if efeito.tipo in ("cura", "drenagem"):
                cura = efeito.quantidade
            elif efeito.tipo == "ambos":
                cura = efeito.quantidade_secundaria

            if cura and self.vida[jogador.id] > 0:
                antes = self.vida[jogador.id]
                self.vida[jogador.id] = clamp_vida(antes + cura)
                recuperado = self.vida[jogador.id] - antes
                logs[jogador.id].append(f"recuperou {recuperado} de vida")
                log_game(
                    "CURA",
                    f"{jogador.display_name}: +{recuperado}; "
                    f"vida {antes}->{self.vida[jogador.id]}.",
                )

        linhas: list[str] = []
        for jogador in self.jogadores:
            carta = self.escolhas[jogador.id]
            efeito = efeitos[jogador.id]
            resumo = "; ".join(logs[jogador.id]) or "nenhum efeito"
            nota = (
                f" ({efeito.observacao})"
                if efeito.observacao and efeito.tipo != "falha"
                else ""
            )
            linhas.append(
                f"**{jogador.display_name}** revelou **{carta.nome}** "
                f"(*{carta.alinhamento}*): {resumo}.{nota}"
            )

        for jogador in self.jogadores:
            log_game(
                "STATUS",
                f"{jogador.display_name}: vida={self.vida[jogador.id]}/"
                f"{VIDA_MAXIMA}, escudo={self.escudo[jogador.id]}/"
                f"{ESCUDO_MAXIMO}.",
            )

        self.turno += 1
        log_game("TURNO", f"Turno resolvido. Próximo turno: {self.turno}.")
        return "\n".join(linhas)

    def vencedor(self) -> Optional[discord.Member]:
        """Retorna o vencedor; None representa empate ou partida ainda ativa."""
        derrotados = [j for j in self.jogadores if self.vida[j.id] <= 0]
        if not derrotados:
            return None
        vivos = [j for j in self.jogadores if self.vida[j.id] > 0]
        return vivos[0] if vivos else None

    def partida_terminou(self) -> bool:
        return any(self.vida[j.id] <= 0 for j in self.jogadores)

    def embed_status(
        self,
        log: Optional[str] = None,
        aguardando: Optional[str] = None,
    ) -> discord.Embed:
        j1, j2 = self.jogadores
        embed = discord.Embed(
            title="🌑 Segredo Floresta Adentro — Duelo",
            color=discord.Color.dark_purple(),
        )
        embed.description = (
            f"**Turno:** {self.turno}\n\n"
            f"❤️ **{j1.display_name}**: {self.vida[j1.id]}/{VIDA_MAXIMA}  "
            f"🛡️ {self.escudo[j1.id]}/{ESCUDO_MAXIMO}\n"
            f"❤️ **{j2.display_name}**: {self.vida[j2.id]}/{VIDA_MAXIMA}  "
            f"🛡️ {self.escudo[j2.id]}/{ESCUDO_MAXIMO}\n\n"
            "Cada jogador escolhe uma carta no menu privado. "
            "As escolhas são reveladas quando ambos confirmam."
        )
        if aguardando:
            embed.description += f"\n\n🔒 **Confirmações:** {aguardando}"
        if log:
            embed.add_field(
                name="Último turno",
                value=log[:1024],
                inline=False,
            )
        embed.set_footer(
            text="Escolha simultânea • Combate até a morte • Sem energia"
        )
        return embed


# ============================================================
# MENU PRIVADO DE CARTAS
# ============================================================

class EscolhaView(discord.ui.View):
    def __init__(
        self,
        partida: PartidaSFA,
        jogador: discord.Member,
        mesa: "MesaView",
    ):
        super().__init__(timeout=TEMPO_MENU_SEGUNDOS)
        self.partida = partida
        self.jogador = jogador
        self.mesa = mesa
        self.turno_menu = partida.turno
        self.opcoes = list(partida.opcoes[jogador.id])

        for carta in self.opcoes:
            botao = discord.ui.Button(
                label=carta.nome[:80],
                style=discord.ButtonStyle.primary,
            )
            botao.callback = self.callback_carta(carta)
            self.add_item(botao)

    def callback_carta(self, carta: Carta):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.jogador.id:
                await interaction.response.send_message(
                    "Este menu não é seu.",
                    ephemeral=True,
                )
                return

            partida = self.partida
            async with partida.lock:
                if not partida.ativa:
                    await interaction.response.edit_message(
                        content="Esta partida já terminou.",
                        view=None,
                    )
                    return

                # Evita que um menu antigo confirme carta de outro turno.
                if self.turno_menu != partida.turno:
                    await interaction.response.edit_message(
                        content="Este menu é de um turno anterior. "
                                "Abra a mesa e escolha novamente.",
                        view=None,
                    )
                    return

                if self.jogador.id in partida.escolhas:
                    await interaction.response.edit_message(
                        content="Sua carta já foi confirmada. Aguarde o adversário.",
                        view=None,
                    )
                    return

                if carta not in partida.opcoes.get(self.jogador.id, []):
                    await interaction.response.edit_message(
                        content="Esta carta não pertence às opções deste turno.",
                        view=None,
                    )
                    return

                partida.escolhas[self.jogador.id] = carta
                confirmados = len(partida.escolhas)

                log_game(
                    "ESCOLHA",
                    f"{self.jogador.display_name} confirmou {carta.nome}. "
                    f"Confirmações: {confirmados}/2.",
                )

                await interaction.response.edit_message(
                    content=(
                        f"🔒 Carta confirmada em segredo: **{carta.nome}**. "
                        "Aguarde o outro jogador."
                    ),
                    view=None,
                )

                if confirmados == len(partida.jogadores):
                    await self.mesa.resolver_e_atualizar()
                else:
                    await self.mesa.atualizar_status_espera()

        return callback

    async def on_timeout(self):
        log_game(
            "TIMEOUT_MENU",
            f"Menu expirou para {self.jogador.display_name}, "
            f"turno {self.turno_menu}.",
        )


# ============================================================
# MESA PÚBLICA DO DUELO
# ============================================================

class MesaView(discord.ui.View):
    def __init__(self, partida: PartidaSFA, cog: "GameSFA"):
        super().__init__(timeout=TEMPO_PARTIDA_SEGUNDOS)
        self.partida = partida
        self.cog = cog

    @discord.ui.button(
        label="Escolher carta (em segredo)",
        style=discord.ButtonStyle.success,
    )
    async def escolher(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        partida = self.partida

        if not partida.ativa:
            await interaction.response.send_message(
                "Esta partida terminou.",
                ephemeral=True,
            )
            return

        jogador = next(
            (p for p in partida.jogadores if p.id == interaction.user.id),
            None,
        )
        if jogador is None:
            await interaction.response.send_message(
                "Você não participa deste duelo.",
                ephemeral=True,
            )
            return

        async with partida.lock:
            if not partida.ativa:
                await interaction.response.send_message(
                    "Esta partida terminou.",
                    ephemeral=True,
                )
                return

            if jogador.id in partida.escolhas:
                await interaction.response.send_message(
                    "Sua carta já foi confirmada; aguarde o adversário.",
                    ephemeral=True,
                )
                return

            cartas = partida.opcoes[jogador.id]
            texto = "\n\n".join(
                f"**{i + 1}. {c.nome}** — *{c.alinhamento}*\n{c.descricao}"
                for i, c in enumerate(cartas)
            )

            log_game(
                "MENU",
                f"{jogador.display_name} abriu o menu do turno {partida.turno}.",
            )

            await interaction.response.send_message(
                f"**Turno {partida.turno}: escolha uma carta.** "
                "Só você verá estas opções.\n\n" + texto,
                view=EscolhaView(partida, jogador, self),
                ephemeral=True,
            )

    async def atualizar_status_espera(self):
        partida = self.partida
        if not partida.mensagem or not partida.ativa:
            return

        confirmados = len(partida.escolhas)
        nomes = [
            j.display_name
            for j in partida.jogadores
            if j.id in partida.escolhas
        ]
        aguardando = f"{confirmados}/2 jogadores confirmaram"
        if nomes:
            aguardando += f" ({', '.join(nomes)})"

        try:
            await partida.mensagem.edit(
                embed=partida.embed_status(aguardando=aguardando),
                view=self,
            )
            log_game("ESPERA", aguardando)
        except discord.HTTPException as erro:
            log_game("ERRO", f"Falha ao atualizar espera: {erro}")

    async def resolver_e_atualizar(self):
        partida = self.partida
        if not partida.ativa or len(partida.escolhas) != 2:
            return

        # Este método é chamado dentro do lock da partida.
        log_game("CONFIRMAÇÃO", "Ambos confirmaram. Resolvendo o turno.")
        log_game(
            "ESCOLHAS",
            " | ".join(
                f"{j.display_name}: {partida.escolhas[j.id].nome}"
                for j in partida.jogadores
            ),
        )

        try:
            log = partida.resolver_turno()
        except Exception:
            log_game("ERRO", "Exceção ao resolver turno.")
            logger.exception("Erro durante a resolução do turno")
            # Evita deixar o jogo permanentemente preso em um estado inválido.
            partida.ativa = False
            self.cog.liberar_partida(partida)
            self.stop()
            if partida.mensagem:
                try:
                    await partida.mensagem.edit(
                        content="O duelo foi encerrado por um erro interno. "
                                "Consulte o terminal do bot.",
                        view=None,
                    )
                except discord.HTTPException:
                    pass
            return

        if partida.partida_terminou():
            vencedor = partida.vencedor()
            partida.ativa = False
            self.cog.liberar_partida(partida)

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            self.stop()

            if vencedor:
                resultado = (
                    f"\n\n🏆 **{vencedor.display_name} venceu o duelo!**"
                )
                log_game("RESULTADO", f"Vencedor: {vencedor.display_name}.")
            else:
                resultado = "\n\n🤝 **Empate! Ambos foram derrotados.**"
                log_game("RESULTADO", "Empate: ambos chegaram a zero.")

            try:
                await partida.mensagem.edit(
                    embed=partida.embed_status(log + resultado),
                    view=self,
                )
            except discord.HTTPException as erro:
                log_game("ERRO", f"Falha ao publicar resultado: {erro}")
            return

        # Limpa escolhas antigas e sorteia novas cartas para o próximo turno.
        partida.iniciar_turno()
        aguardando = "0/2 jogadores confirmaram"

        try:
            await partida.mensagem.edit(
                embed=partida.embed_status(log=log, aguardando=aguardando),
                view=self,
            )
            log_game(
                "NOVO TURNO",
                f"Turno {partida.turno} pronto; aguardando os dois jogadores.",
            )
        except discord.HTTPException as erro:
            log_game("ERRO", f"Falha ao atualizar a mesa: {erro}")

    async def on_timeout(self):
        partida = self.partida
        async with partida.lock:
            if not partida.ativa:
                return

            partida.ativa = False
            self.cog.liberar_partida(partida)
            log_game(
                "TIMEOUT_PARTIDA",
                "Partida encerrada por inatividade/tempo limite da interface.",
            )
            try:
                if partida.mensagem:
                    await partida.mensagem.edit(
                        content="⌛ Partida encerrada por inatividade.",
                        view=None,
                    )
            except discord.HTTPException as erro:
                log_game("ERRO", f"Falha ao encerrar partida: {erro}")


# ============================================================
# COG / COMANDO SLASH
# ============================================================

class GameSFA(commands.Cog):
    sfa = app_commands.Group(
        name="sfa",
        description="Jogo de cartas de Segredo Floresta Adentro",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.partidas_ativas: set[frozenset[int]] = set()
        self._lock_partidas = asyncio.Lock()

    def liberar_partida(self, partida: PartidaSFA) -> None:
        chave = frozenset(j.id for j in partida.jogadores)
        self.partidas_ativas.discard(chave)
        log_game("LIBERAÇÃO", f"Partida liberada: {chave}.")

    @sfa.command(name="duelo", description="Desafie alguém para um duelo de cartas.")
    @app_commands.guild_only()
    async def duelo(
        self,
        interaction: discord.Interaction,
        adversario: discord.Member,
    ):
        if adversario.bot:
            await interaction.response.send_message(
                "Você não pode desafiar um bot.",
                ephemeral=True,
            )
            return

        if adversario.id == interaction.user.id:
            await interaction.response.send_message(
                "Você não pode desafiar a si mesmo.",
                ephemeral=True,
            )
            return

        ids = frozenset((interaction.user.id, adversario.id))

        async with self._lock_partidas:
            if any(ids.intersection(ativa) for ativa in self.partidas_ativas):
                await interaction.response.send_message(
                    "Um dos jogadores já está em uma partida ativa.",
                    ephemeral=True,
                )
                return
            self.partidas_ativas.add(ids)

        try:
            partida = PartidaSFA(interaction.user, adversario)
            mesa = MesaView(partida, self)
            partida.mesa = mesa

            await interaction.response.send_message(
                content=(
                    f"⚔️ {interaction.user.mention} desafiou "
                    f"{adversario.mention}!\n"
                    "Os dois jogadores devem clicar no botão para escolher "
                    "uma carta em segredo."
                ),
                embed=partida.embed_status(
                    aguardando="0/2 jogadores confirmaram"
                ),
                view=mesa,
            )
            partida.mensagem = await interaction.original_response()
            log_game("PARTIDA", f"Mesa publicada. Turno inicial: {partida.turno}.")

        except Exception:
            self.partidas_ativas.discard(ids)
            logger.exception("Não foi possível criar/publicar a partida.")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Não foi possível iniciar o duelo. Veja o terminal do bot.",
                    ephemeral=True,
                )
            raise


async def setup(bot: commands.Bot):
    await bot.add_cog(GameSFA(bot))
    log_game("COG", "GameSFA carregado com sucesso.")
