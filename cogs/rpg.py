"""RPG PERSISTENTE — Cog orquestrador do RPG Textual.

A lógica de domínio fica em ``rpg_system``. Este arquivo apenas valida a
interação, chama os sistemas atômicos e apresenta o resultado no Discord.
Toda recompensa é calculada e persistida em Python; o OpenRouter só fornece
texto narrativo.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from rpg_system.achievements_v2 import AchievementsV2, CATEGORIAS
from rpg_system.activities import Activities
from rpg_system.combat import INIMIGOS, Combate
from rpg_system.economy import Economy
from rpg_system.energy import Energy
from rpg_system.exploration import Exploration
from rpg_system.goals import obter_objetivos
from rpg_system.houses import Houses
from rpg_system.inventory import Inventario
from rpg_system.items import CATALOGO_ITENS, nome_item, obter_item
from rpg_system.marriage import Marriage
from rpg_system.market_v2 import MarketV2, normalizar
from rpg_system.mining_v2 import MiningV2
from rpg_system.missions import RPGMissions
from rpg_system.professions_v2 import PROFISSOES, ProfessionsV2
from rpg_system.progression import Progression
from rpg_system.tools import CHANCES_COINS, PICARETAS
from rpg_system.views import criar_embed_conquistas, criar_embed_personagem
from rpg_system.world import REGIOES

log = logging.getLogger("shaggy.rpg")


# ---------------------------------------------------------------------------
# Autocomplete (funções de módulo: não dependem de bind de instância)
# ---------------------------------------------------------------------------
def _choices(pares: list[tuple[str, str]]) -> list[app_commands.Choice]:
    vistos: set[str] = set()
    res = []
    for nome, valor in pares:
        valor = (valor or "")[:100]
        if not valor or valor in vistos:
            continue
        vistos.add(valor)
        res.append(app_commands.Choice(name=(nome or valor)[:100], value=valor))
        if len(res) >= 25:
            break
    return res


async def ac_itens_mercador(interaction: discord.Interaction, current: str):
    try:
        market = MarketV2(None, interaction.guild_id, interaction.user_id)
        return _choices([(n, n) for n in market.nomes_para_autocomplete(current)])
    except Exception:
        return []


async def ac_itens_inventario(interaction: discord.Interaction, current: str):
    try:
        inv = Inventario(interaction.guild_id, interaction.user_id).obter()
        alvo = normalizar(current)
        pares = []
        for key in inv:
            nome = nome_item(key)
            if not alvo or alvo in normalizar(nome) or alvo in normalizar(key):
                pares.append((nome, nome))
        pares.sort()
        return _choices(pares)
    except Exception:
        return []


async def ac_picaretas_inventario(interaction: discord.Interaction, current: str):
    try:
        inv = Inventario(interaction.guild_id, interaction.user_id).obter()
        alvo = normalizar(current)
        pares = []
        for key in inv:
            if key not in PICARETAS:
                continue
            nome = PICARETAS[key].nome
            if not alvo or alvo in normalizar(nome):
                pares.append((f"{nome} (tier {PICARETAS[key].nivel})", nome))
        pares.sort(key=lambda p: p[0])
        return _choices(pares)
    except Exception:
        return []


async def ac_profissoes(interaction: discord.Interaction, current: str):
    alvo = normalizar(current)
    pares = []
    for key, info in PROFISSOES.items():
        if not alvo or alvo in normalizar(info["nome"]) or alvo in normalizar(key):
            pares.append((info["nome"], info["nome"]))
    return _choices(sorted(pares))


async def ac_profissoes_aprendidas(interaction: discord.Interaction, current: str):
    try:
        profs = ProfessionsV2(interaction.guild_id, interaction.user_id).obter_todas()
        alvo = normalizar(current)
        pares = []
        for p in profs:
            if not alvo or alvo in normalizar(p["nome"]):
                pares.append((f"{p['nome']} (nível {p['nivel']})", p["nome"]))
        return _choices(sorted(pares))
    except Exception:
        return []


async def ac_regioes(interaction: discord.Interaction, current: str):
    alvo = normalizar(current)
    pares = []
    for key, regiao in sorted(REGIOES.items(), key=lambda item: item[1]["nivel_min"]):
        if alvo and alvo not in normalizar(regiao["nome"]) and alvo not in normalizar(key):
            continue
        nome = f"{regiao['nome']} (Nv. {regiao['nivel_min']})"
        pares.append((nome, key))
    return _choices(pares)


async def ac_inimigos(interaction: discord.Interaction, current: str):
    alvo = normalizar(current)
    pares = []
    for info in INIMIGOS.values():
        campos = [info["nome"], info["key"], *info.get("aliases", [])]
        if alvo and not any(alvo in normalizar(c) for c in campos):
            continue
        rotulo = f"{info['emoji']} {info['nome']} (Nv. {info['nivel_min']})"
        pares.append((rotulo, info["nome"]))
    pares.sort(key=lambda p: p[0])
    return _choices(pares)


async def ac_armas_inventario(interaction: discord.Interaction, current: str):
    try:
        inv = Inventario(interaction.guild_id, interaction.user_id).obter()
        alvo = normalizar(current)
        pares = []
        if not alvo or "mao" in alvo or "punho" in alvo or "desarmado" in alvo:
            pares.append(("Mãos (sem item)", "Mãos"))
        for key in inv:
            item = obter_item(key)
            if not item:
                continue
            if alvo and alvo not in normalizar(item.nome) and alvo not in normalizar(key):
                continue
            if item.poder_combate > 0:
                rotulo = f"{item.nome} (dano {item.poder_combate - 1}-{item.poder_combate + 2})"
            else:
                rotulo = f"{item.nome} (improvisada, dano baixo)"
            pares.append((rotulo, item.nome))
        pares.sort(key=lambda p: p[0])
        return _choices(pares)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Helpers de apresentação
# ---------------------------------------------------------------------------
def _tempo(segundos: int) -> str:
    segundos = max(0, int(segundos))
    if segundos >= 3600:
        return f"{segundos // 3600}h{(segundos % 3600) // 60:02d}m"
    if segundos >= 60:
        return f"{segundos // 60}m{segundos % 60:02d}s"
    return f"{segundos}s"


def _linhas_itens(itens: dict[str, int]) -> str:
    if not itens:
        return "Nenhum material."
    return "\n".join(f"• {nome_item(k)} ×{qtd}" for k, qtd in sorted(itens.items()))


def _barra(atual: int, total: int, tamanho: int = 10) -> str:
    total = max(1, int(total))
    atual = max(0, min(int(atual), total))
    preenchidos = int(round((atual / total) * tamanho))
    return "▰" * preenchidos + "▱" * (tamanho - preenchidos)


class RPG(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------- contexto ----------------
    def _get_ctx(self, guild_id: int, user_id: int) -> dict[str, Any]:
        return {
            "progression": Progression(guild_id, user_id),
            "inventory": Inventario(guild_id, user_id),
            "mining": MiningV2(guild_id, user_id),
            "professions": ProfessionsV2(guild_id, user_id),
            "activities": Activities(self.bot, guild_id, user_id),
            "exploration": Exploration(self.bot, guild_id, user_id),
            "missions": RPGMissions(guild_id, user_id),
            "market": MarketV2(self.bot, guild_id, user_id),
            "economy": Economy(self.bot),
            "energy": Energy(guild_id, user_id),
            "combat": Combate(guild_id, user_id),
            "houses": Houses(self.bot, guild_id, user_id),
            "marriage": Marriage(guild_id, user_id),
            "achievements": AchievementsV2(guild_id, user_id),
        }

    def _novas_conquistas(self, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return ctx["achievements"].verificar()
        except Exception:
            log.exception("Falha ao verificar conquistas")
            return []

    @staticmethod
    def _campo_conquistas(embed: discord.Embed, novas: list[dict[str, Any]]) -> None:
        if not novas:
            return
        linhas = []
        for c in novas[:6]:
            extra = []
            if c.get("recompensa_xp"):
                extra.append(f"+{c['recompensa_xp']} XP")
            if c.get("recompensa_coins"):
                extra.append(f"+{c['recompensa_coins']} 🪙")
            sufixo = f" ({', '.join(extra)})" if extra else ""
            linhas.append(f"🏆 **{c['nome']}** — {c['descricao']}{sufixo}")
        if len(novas) > 6:
            linhas.append(f"… e mais {len(novas) - 6} conquista(s).")
        embed.add_field(name="Conquistas desbloqueadas", value="\n".join(linhas), inline=False)

    def _extras(self, ctx: dict[str, Any], personagem: dict[str, Any]) -> dict[str, Any]:
        try:
            local_key = ctx["exploration"].obter_local_atual()
        except Exception:
            local_key = None
        try:
            profs = ctx["professions"].obter_todas()
        except Exception:
            profs = []
        try:
            casa = ctx["houses"].obter_casa()
        except Exception:
            casa = None
        try:
            todas = ctx["achievements"].obter_todas()
            conquistas = {
                "desbloqueadas": sum(1 for c in todas if c["desbloqueada"]),
                "total": len(todas),
            }
        except Exception:
            conquistas = None
        try:
            energia = ctx["energy"].obter_detalhado()
        except Exception:
            energia = {"valor": 0, "max": 100, "restante": 0}
        try:
            combate = ctx["combat"].resumo()
        except Exception:
            combate = None

        return {
            "saldo": ctx["economy"].obter_saldo(personagem["guild_id"], personagem["user_id"]),
            "energia": int(energia.get("valor", 0)),
            "energia_max": int(energia.get("max", 100)),
            "energia_regen": int(energia.get("restante", 0)),
            "local_key": local_key,
            "regiao": personagem.get("regiao", "dakor"),
            "profissoes": profs,
            "profissoes_vazio": not profs,
            "casa": casa,
            "conquistas": conquistas,
            "combate": combate,
            "objetivos": obter_objetivos(personagem["guild_id"], personagem["user_id"]),
        }

    @staticmethod
    def _embed_combate(res: dict[str, Any], energia: dict[str, Any]) -> discord.Embed:
        estado = res.get("estado")
        nome = res.get("inimigo_nome", "Inimigo")
        emoji = res.get("inimigo_emoji", "⚔️")
        if estado == "vitoria":
            embed = discord.Embed(
                title=f"🏆 Vitória — {emoji} {nome}",
                color=discord.Color.green(),
            )
        elif estado == "derrota":
            embed = discord.Embed(
                title=f"💀 Derrota — {emoji} {nome}",
                color=discord.Color.dark_red(),
            )
        else:
            embed = discord.Embed(
                title=f"⚔️ {emoji} {nome} — turno {res.get('turno', 1)}",
                color=discord.Color.orange(),
            )

        pv_j = int(res.get("pv_jogador", 0))
        pv_j_max = int(res.get("pv_max_jogador", 1))
        pv_i = int(res.get("pv_inimigo", 0))
        pv_i_max = int(res.get("pv_max_inimigo", 1))
        embed.add_field(
            name="Seu PV",
            value=f"{pv_j}/{pv_j_max}\n{_barra(pv_j, pv_j_max)}",
            inline=True,
        )
        embed.add_field(
            name=f"PV do {nome}",
            value=f"{pv_i}/{pv_i_max}\n{_barra(pv_i, pv_i_max)}",
            inline=True,
        )
        embed.add_field(
            name="Dificuldade",
            value=str(res.get("inimigo_dificuldade", "—")),
            inline=True,
        )

        arma = res.get("arma_nome", "Mãos")
        if res.get("arma_improvisada"):
            arma += " (improvisada)"
        linhas = [
            f"**{arma}** causou **{int(res.get('dano_jogador', 0))}** de dano"
            + (" — 💥 CRÍTICO!" if res.get("critico") else ".")
        ]
        if estado == "ativo":
            if res.get("inimigo_errou"):
                linhas.append("O inimigo errou o contra-ataque.")
            else:
                linhas.append(
                    f"O inimigo causou **{int(res.get('dano_inimigo', 0))}** de dano."
                )
            if res.get("furia_ativada"):
                linhas.append("🔥 O inimigo ficou furioso!")
        elif estado == "vitoria":
            linhas.append(
                f"Recompensa: **+{int(res.get('coins', 0))}** 🪙 e "
                f"**+{int(res.get('xp_recompensa', 0))} XP**."
            )
        elif estado == "derrota":
            linhas.append("Você caiu, mas não perdeu nenhuma moeda.")
        embed.add_field(name="Ação", value="\n".join(linhas), inline=False)

        xp = res.get("xp") or {}
        if xp.get("sucesso"):
            texto_xp = f"+{int(xp.get('xp_ganho', 0))} XP nesta ação"
            if xp.get("subiu_nivel"):
                texto_xp += f"\n⬆️ Subiu para o nível {xp.get('nivel_novo')}!"
            embed.add_field(name="Experiência", value=texto_xp, inline=True)

        max_energia = int(energia.get("max", 100))
        energia_atual = int(res.get("energia", energia.get("valor", 0)))
        restante = int(energia.get("restante", 0))
        rodape = (
            f"⚡ {energia_atual}/{max_energia} · cada ação custa "
            f"{int(res.get('custo_energia', 4))} · recarga em {_tempo(restante)}"
        )
        if estado == "ativo":
            rodape += " · /combate ataca novamente"
        embed.set_footer(text=rodape)
        return embed

    @staticmethod
    def _embed_catalogo_combate(catalogo: list[dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(
            title="⚔️ Inimigos de Dakor",
            description=(
                "Comece com `/combate inimigo:Nome`. O primeiro ataque já acontece "
                "no turno 1. Depois, use `/combate` para repetir com a mesma arma ou "
                "`/combate arma:Nome` para trocar."
            ),
            color=discord.Color.dark_red(),
        )
        for info in catalogo:
            moedas = info.get("coins", (0, 0))
            valor = (
                f"{info.get('descricao', '')}\n"
                f"**Nv. {info.get('nivel_min', 1)}** · PV {info.get('pv', 0)} · "
                f"{info.get('xp', 0)} XP · 🪙 {moedas[0]}–{moedas[1]}\n"
                f"💡 {info.get('dica', '')}"
            )
            if info.get("especial"):
                valor = "⭐ **Especial**\n" + valor
            embed.add_field(
                name=f"{info.get('emoji', '⚔️')} {info.get('nome')} — {info.get('dificuldade', '')}",
                value=valor,
                inline=False,
            )
        embed.set_footer(text="Cada ação de combate custa 4 de energia. A energia recarrega 100% a cada 24h.")
        return embed

    # =====================================================================
    # Personagem / inventário
    # =====================================================================
    @app_commands.command(name="rpg", description="Cria o personagem ou abre a ficha completa.")
    @app_commands.guild_only()
    async def rpg(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        char = ctx["progression"].obter_personagem()
        criado = False
        if not char:
            ok = ctx["progression"].criar_personagem(
                interaction.user.display_name or interaction.user.name
            )
            if not ok:
                char = ctx["progression"].obter_personagem()
                if not char:
                    await interaction.response.send_message(
                        "Não foi possível criar o personagem. Tente novamente.", ephemeral=True
                    )
                    return
            else:
                criado = True
                char = ctx["progression"].obter_personagem()

        picareta = ctx["market"].garantir_picareta_inicial()
        novas = self._novas_conquistas(ctx)
        extras = self._extras(ctx, char)
        embed = criar_embed_personagem(char, extras)
        if criado:
            embed.description = "Sua jornada começa em Dakor. Uma Picareta de Madeira foi entregue."
        if picareta:
            p = PICARETAS[picareta]
            embed.add_field(
                name="Picareta inicial",
                value=f"⛏️ **{p.nome}** equipada — {int(p.chance_coins * 100)}% de chance de Abysmus por mineração.",
                inline=False,
            )
        self._campo_conquistas(embed, novas)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="personagem", description="Ficha, progresso e próximos objetivos.")
    @app_commands.guild_only()
    async def personagem(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        char = ctx["progression"].obter_personagem()
        if not char:
            await interaction.response.send_message(
                "Você ainda não tem personagem. Use `/rpg` para criar.", ephemeral=True
            )
            return
        novas = self._novas_conquistas(ctx)
        embed = criar_embed_personagem(char, self._extras(ctx, char))
        self._campo_conquistas(embed, novas)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mochila", description="Inventário, equipamento e itens.")
    @app_commands.guild_only()
    async def mochila(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        inv = ctx["inventory"].obter()
        if not inv:
            await interaction.response.send_message("🎒 Sua mochila está vazia.", ephemeral=True)
            return

        embed = discord.Embed(title="🎒 Mochila", color=discord.Color.dark_green())
        categorias: dict[str, list[str]] = {}
        total = 0
        for key, qtd in sorted(inv.items(), key=lambda item: nome_item(item[0])):
            item = obter_item(key)
            categoria = item.categoria if item else "outro"
            categorias.setdefault(categoria, []).append(f"{nome_item(key)} ×{qtd}")
            total += qtd
        for categoria, linhas in categorias.items():
            embed.add_field(
                name=categoria.title(),
                value="\n".join(linhas)[:1024],
                inline=False,
            )

        equipada = ctx["market"].picareta_em_uso()
        if equipada:
            p = equipada["ferramenta"]
            embed.add_field(
                name="Picareta em uso",
                value=(
                    f"⛏️ **{p.nome}** ({equipada['origem']})\n"
                    f"Eficiência {p.eficiencia}x · {int(p.chance_coins * 100)}% de Abysmus"
                ),
                inline=False,
            )
        embed.set_footer(text=f"{len(inv)} tipo(s) · {total} item(ns) · use /equipar para trocar de picareta")
        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # Mineração
    # =====================================================================
    @app_commands.command(name="mineracao", description="Minere recursos com a picareta em uso.")
    @app_commands.describe(regiao="Região onde minerar (opcional; padrão: região atual)")
    @app_commands.autocomplete(regiao=ac_regioes)
    @app_commands.guild_only()
    async def mineracao(self, interaction: discord.Interaction, regiao: str | None = None):
        await interaction.response.defer()
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["mining"].minerar(regiao)
        if not res.get("sucesso"):
            motivo = res.get("motivo", "Falha na mineração.")
            if res.get("restante"):
                motivo += f" Aguarde {_tempo(res['restante'])}."
            await interaction.followup.send(f"❌ {motivo}", ephemeral=True)
            return

        novas = self._novas_conquistas(ctx)
        embed = discord.Embed(
            title=f"⛏️ Mineração — {res['regiao_nome']}",
            color=discord.Color.dark_gray(),
        )
        embed.add_field(
            name="Picareta",
            value=(
                f"**{res['picareta_nome']}** (tier {res['picareta_nivel']}, {res['origem_picareta']})\n"
                f"Chance de Abysmus: {int(res['chance_coins'] * 100)}%"
            ),
            inline=False,
        )
        embed.add_field(name="Materiais", value=_linhas_itens(res["itens"]), inline=True)
        moedas = f"🪙 +{res['coins']:,}" if res["coins"] else "Nenhum desta vez"
        embed.add_field(name="Abysmus", value=moedas, inline=True)

        xp = res.get("xp_personagem") or {}
        xp_txt = f"+{xp.get('xp_ganho', 0)} XP (total {xp.get('xp_total', 0):,})"
        if xp.get("subiu_nivel"):
            xp_txt += f"\n🌟 Subiu para o nível {xp.get('nivel_novo')}!"
        embed.add_field(name="Personagem", value=xp_txt, inline=False)

        if res.get("xp_profissao"):
            prof = (
                f"+{res['xp_profissao']} XP de Minerador (nível {res.get('profissao_nivel')})\n"
                f"Progresso: {res.get('profissao_xp', 0):,}/{res.get('profissao_xp_necessario', 0):,}"
            )
            if res.get("subiu_profissao"):
                prof += "\n🌟 Nível profissional aumentou!"
            for beneficio in res.get("beneficios_desbloqueados", [])[:3]:
                prof += f"\n🔓 {beneficio['nome']}: {beneficio['descricao']}"
            embed.add_field(name="Profissão", value=prof, inline=False)
        else:
            embed.add_field(
                name="Profissão",
                value="Aprenda Minerador com `/aprender_profissao` para ganhar XP profissional.",
                inline=False,
            )

        if res.get("raros"):
            embed.add_field(
                name="Achado raro",
                value=", ".join(nome_item(k) for k in res["raros"]),
                inline=False,
            )
        self._campo_conquistas(embed, novas)
        embed.set_footer(
            text=f"Saldo: {res.get('saldo', 0):,} Abysmus · próximo uso em {_tempo(res.get('cooldown', 0))}"
        )
        await interaction.followup.send(embed=embed)

    # =====================================================================
    # Profissões
    # =====================================================================
    @app_commands.command(name="trabalhar", description="Trabalhe em uma profissão aprendida.")
    @app_commands.describe(profissao="Profissão (opcional; padrão: a de maior nível)")
    @app_commands.autocomplete(profissao=ac_profissoes_aprendidas)
    @app_commands.guild_only()
    async def trabalhar(self, interaction: discord.Interaction, profissao: str | None = None):
        await interaction.response.defer()
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["professions"].trabalhar(profissao)
        if not res.get("sucesso"):
            motivo = res.get("motivo", "Falha ao trabalhar.")
            if res.get("restante"):
                motivo += f" Aguarde {_tempo(res['restante'])}."
            await interaction.followup.send(f"❌ {motivo}", ephemeral=True)
            return

        novas = self._novas_conquistas(ctx)
        embed = discord.Embed(
            title=f"💼 {res['nome']} — atividade concluída",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Itens", value=_linhas_itens(res.get("itens", {})), inline=True)
        embed.add_field(
            name="Abysmus",
            value=f"🪙 +{res.get('coins', 0):,}" if res.get("coins") else "Sem comissão desta vez",
            inline=True,
        )
        progresso = (
            f"+{res['xp_ganho']} XP profissional\n"
            f"Nível {res['nivel']} · {res.get('xp', 0):,}/{res.get('xp_necessario', 0):,}"
        )
        if res.get("subiu"):
            progresso += f"\n🌟 Subiu do nível {res['nivel_antes']} para {res['nivel']}!"
        for beneficio in res.get("beneficios_desbloqueados", [])[:3]:
            progresso += f"\n🔓 {beneficio['nome']}: {beneficio['descricao']}"
        embed.add_field(name="Profissão", value=progresso, inline=False)
        xp_char = res.get("xp_personagem") or {}
        embed.set_footer(
            text=f"Saldo: {res.get('saldo', 0):,} · personagem +{xp_char.get('xp_ganho', 0)} XP · "
                 f"próxima atividade em {_tempo(res.get('cooldown', 0))}"
        )
        self._campo_conquistas(embed, novas)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="profissoes", description="Catálogo de profissões e seu progresso.")
    @app_commands.describe(profissao="Consultar uma profissão específica")
    @app_commands.autocomplete(profissao=ac_profissoes)
    @app_commands.guild_only()
    async def profissoes(self, interaction: discord.Interaction, profissao: str | None = None):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        profs = ctx["professions"]

        if profissao:
            dados = profs.detalhar(profissao)
            if not dados:
                await interaction.response.send_message(
                    "❌ Profissão não encontrada. Use `/profissoes` para ver o catálogo.",
                    ephemeral=True,
                )
                return
            embed = discord.Embed(
                title=f"{dados.get('emoji', '')} {dados['nome']}",
                description=dados["descricao"],
                color=discord.Color.orange(),
            )
            embed.add_field(name="Atividades", value="\n".join(dados["atividades"]), inline=False)
            embed.add_field(name="Tipo de ganho", value=dados["tipo_ganho"], inline=False)
            req = dados.get("requisitos", {}).get("nivel_personagem", 1)
            embed.add_field(name="Requisito", value=f"Nível de personagem {req}", inline=True)
            estado = dados.get("estado")
            if estado == "adquirida":
                estado_txt = f"Nível {dados['nivel_jogador']} · {dados['xp_jogador']:,}/{dados['xp_necessario']:,} XP"
            elif estado == "bloqueada":
                estado_txt = f"Bloqueada — {dados.get('motivo')}"
            else:
                estado_txt = "Disponível para aprender"
            embed.add_field(name="Estado", value=estado_txt, inline=True)
            if dados.get("beneficios_ativos"):
                embed.add_field(
                    name="Benefícios ativos",
                    value="\n".join(f"• {b['nome']}: {b['descricao']}" for b in dados["beneficios_ativos"]),
                    inline=False,
                )
            if dados.get("proximos_beneficios"):
                embed.add_field(
                    name="Próximos benefícios",
                    value="\n".join(
                        f"• Nível {b['nivel']} — {b['nome']}: {b['descricao']}"
                        for b in dados["proximos_beneficios"][:4]
                    ),
                    inline=False,
                )
            if estado == "disponivel":
                embed.set_footer(text=f"Use /aprender_profissao profissao:{dados['nome']}")
            await interaction.response.send_message(embed=embed)
            return

        catalogo = profs.catalogo()
        embed = discord.Embed(
            title="⚒️ Profissões",
            description="Cada profissão evolui separadamente. Consulte uma para ver benefícios e requisitos.",
            color=discord.Color.orange(),
        )
        for p in catalogo:
            estado = p["estado"]
            if estado == "adquirida":
                valor = f"Nível {p['nivel_jogador']} · {p['xp_jogador']:,}/{p['xp_necessario']:,} XP"
                emoji = "✅"
            elif estado == "bloqueada":
                valor = f"🔒 {p.get('motivo', 'Bloqueada')}"
                emoji = "🔒"
            else:
                valor = f"Disponível · {p['tipo_ganho']}"
                emoji = "🟢"
            embed.add_field(
                name=f"{emoji} {p['nome']}",
                value=f"{p['descricao']}\n{valor}",
                inline=False,
            )
        embed.set_footer(text="Use /profissoes profissao:Nome ou /aprender_profissao")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="aprender_profissao", description="Aprender uma profissão do catálogo.")
    @app_commands.describe(profissao="Nome da profissão")
    @app_commands.autocomplete(profissao=ac_profissoes)
    @app_commands.guild_only()
    async def aprender_profissao(self, interaction: discord.Interaction, profissao: str):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["professions"].aprender(profissao)
        if not res.get("sucesso"):
            await interaction.response.send_message(
                f"❌ {res.get('motivo', 'Não foi possível aprender esta profissão.')}",
                ephemeral=True,
            )
            return
        novas = self._novas_conquistas(ctx)
        info = res["info"]
        embed = discord.Embed(
            title=f"✅ Profissão aprendida — {res['nome']}",
            description=info["descricao"],
            color=discord.Color.green(),
        )
        embed.add_field(name="Atividades", value="\n".join(info["atividades"]), inline=False)
        embed.add_field(name="Tipo de ganho", value=info["tipo_ganho"], inline=False)
        embed.add_field(
            name="Progressão",
            value="\n".join(
                f"• Nível {b['nivel']} — {b['nome']}: {b['descricao']}"
                for b in info["beneficios"][:3]
            ),
            inline=False,
        )
        embed.set_footer(text=f"Use /trabalhar profissao:{res['nome']}")
        self._campo_conquistas(embed, novas)
        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # Mercador
    # =====================================================================
    @app_commands.command(name="mercador", description="Loja do RPG: catálogo, utilidade e requisitos.")
    @app_commands.describe(categoria="Filtrar por categoria", item="Detalhar um item pelo nome")
    @app_commands.autocomplete(item=ac_itens_mercador)
    @app_commands.choices(categoria=[
        app_commands.Choice(name="Todas", value="todas"),
        app_commands.Choice(name="Picaretas", value="picareta"),
        app_commands.Choice(name="Ferramentas", value="ferramenta"),
        app_commands.Choice(name="Materiais", value="material"),
        app_commands.Choice(name="Consumíveis", value="consumivel"),
        app_commands.Choice(name="Machados", value="machado"),
    ])
    @app_commands.guild_only()
    async def mercador(self, interaction: discord.Interaction, categoria: str | None = None,
                       item: str | None = None):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        market = ctx["market"]

        if item:
            detalhe = market.detalhar_item(item)
            if detalhe["status"] == "ambiguo":
                await interaction.response.send_message(
                    "Há mais de um item com esse nome. Opções: "
                    + ", ".join(i.nome for i in detalhe["opcoes"]),
                    ephemeral=True,
                )
                return
            if detalhe["status"] != "ok":
                await interaction.response.send_message("❌ Item não encontrado no mercador.", ephemeral=True)
                return
            dados = detalhe.get("dados") or {}
            it = detalhe["item"]
            embed = discord.Embed(
                title=f"🛒 {it.nome}",
                description=it.descricao,
                color=discord.Color.gold(),
            )
            embed.add_field(name="Categoria", value=it.categoria.title(), inline=True)
            embed.add_field(name="Raridade", value=it.raridade.title(), inline=True)
            embed.add_field(name="Nível", value=str(it.nivel), inline=True)
            preco = dados.get("preco_final", it.preco)
            embed.add_field(name="Preço", value=f"🪙 {preco:,}", inline=True)
            embed.add_field(
                name="Disponibilidade",
                value="✅ Disponível" if dados.get("disponivel", True) else f"🔒 {dados.get('motivo_indisponivel')}",
                inline=True,
            )
            embed.add_field(name="Utilidade", value=it.utilidade or "—", inline=False)
            embed.add_field(name="Efeito real", value=it.efeito or "—", inline=False)
            if it.requisitos:
                req = []
                if it.requisitos.get("nivel_personagem"):
                    req.append(f"Nível de personagem {it.requisitos['nivel_personagem']}")
                if it.requisitos.get("profissao"):
                    req.append(
                        f"Profissão {it.requisitos['profissao']} nível {it.requisitos.get('nivel_profissao', 1)}"
                    )
                embed.add_field(name="Requisitos", value="\n".join(req) or "Nenhum", inline=False)
            if it.key in PICARETAS:
                p = PICARETAS[it.key]
                embed.add_field(
                    name="Atributos de mineração",
                    value=(
                        f"Eficiência {p.eficiencia}x · {int(p.chance_coins * 100)}% de Abysmus · "
                        f"materiais {p.multiplicador_materiais}x"
                    ),
                    inline=False,
                )
            embed.set_footer(text=f"Use /comprar item:{it.nome} quantidade:1")
            await interaction.response.send_message(embed=embed)
            return

        cat = categoria or "todas"
        loja = market.listar_loja(cat)
        if not loja:
            await interaction.response.send_message("Nenhum item nesta categoria.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🛒 Mercador",
            description=(
                f"{len(loja)} item(ns) · compre pelo nome com `/comprar`.\n"
                "Use `/mercador item:Nome` para ver descrição, utilidade, efeito e requisitos."
            ),
            color=discord.Color.gold(),
        )
        limite = 8 if cat in ("todas", "") else 12
        for dados in loja[:limite]:
            estado = "" if dados["disponivel"] else f"\n🔒 {dados['motivo_indisponivel']}"
            desconto = ""
            if dados.get("desconto"):
                desconto = f" (desconto {int(dados['desconto'] * 100)}%)"
            valor = (
                f"{dados['descricao']}\n"
                f"**Utilidade:** {dados['utilidade']}\n"
                f"**Efeito:** {dados['efeito']}{estado}"
            )
            embed.add_field(
                name=f"{dados['nome']} — 🪙 {dados['preco_final']:,}{desconto}",
                value=valor[:1024],
                inline=False,
            )
        if len(loja) > limite:
            embed.set_footer(text=f"Mostrando {limite} de {len(loja)}. Filtre por categoria ou informe um item.")
        else:
            embed.set_footer(text="Preços já incluem seu desconto de Mercador, se houver.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="comprar", description="Comprar item do mercador pelo nome.")
    @app_commands.describe(item="Nome do item", quantidade="Quantidade (1-99)")
    @app_commands.autocomplete(item=ac_itens_mercador)
    @app_commands.guild_only()
    async def comprar(self, interaction: discord.Interaction, item: str, quantidade: int = 1):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["market"].comprar_por_nome(item, quantidade)
        if not res.get("sucesso"):
            motivo = res.get("motivo", "Falha na compra.")
            if res.get("opcoes"):
                motivo += " Opções: " + ", ".join(res["opcoes"][:10])
            await interaction.response.send_message(f"❌ {motivo}", ephemeral=True)
            return
        novas = self._novas_conquistas(ctx)
        it = obter_item(res["item"])
        embed = discord.Embed(
            title="✅ Compra concluída",
            description=(
                f"**{res['quantidade']}× {res['item_nome']}** por 🪙 {res['preco']:,}.\n"
                f"Saldo atual: 🪙 {res['saldo']:,}"
            ),
            color=discord.Color.green(),
        )
        if it:
            embed.add_field(name="Utilidade", value=it.utilidade or "—", inline=False)
            embed.add_field(name="Efeito real", value=it.efeito or "—", inline=False)
            if it.key in PICARETAS:
                p = PICARETAS[it.key]
                embed.add_field(
                    name="Mineração",
                    value=(
                        f"Eficiência {p.eficiencia}x · {int(p.chance_coins * 100)}% de Abysmus · "
                        f"materiais {p.multiplicador_materiais}x"
                    ),
                    inline=False,
                )
                embed.set_footer(text=f"Use /equipar item:{it.nome} para equipar.")
        self._campo_conquistas(embed, novas)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="vender", description="Vender item da mochila pelo nome.")
    @app_commands.describe(item="Nome do item", quantidade="Quantidade")
    @app_commands.autocomplete(item=ac_itens_inventario)
    @app_commands.guild_only()
    async def vender(self, interaction: discord.Interaction, item: str, quantidade: int = 1):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["market"].vender_por_nome(item, quantidade)
        if not res.get("sucesso"):
            motivo = res.get("motivo", "Falha na venda.")
            if res.get("opcoes"):
                motivo += " Opções: " + ", ".join(res["opcoes"][:10])
            await interaction.response.send_message(f"❌ {motivo}", ephemeral=True)
            return
        embed = discord.Embed(
            title="💰 Venda concluída",
            description=(
                f"**{res['quantidade']}× {res['item_nome']}** por 🪙 {res['recebido']:,}.\n"
                f"Saldo atual: 🪙 {res['saldo']:,}"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="A venda paga 50% do preço base, com bônus de Mercador até +10%.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="equipar", description="Equipar uma picareta do inventário.")
    @app_commands.describe(item="Picareta do inventário")
    @app_commands.autocomplete(item=ac_picaretas_inventario)
    @app_commands.guild_only()
    async def equipar(self, interaction: discord.Interaction, item: str):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["market"].equipar_picareta(item)
        if not res.get("sucesso"):
            await interaction.response.send_message(
                f"❌ {res.get('motivo', 'Não foi possível equipar.')}", ephemeral=True
            )
            return
        p = PICARETAS[res["picareta"]]
        embed = discord.Embed(
            title=f"⛏️ {p.nome} equipada",
            description=p.descricao,
            color=discord.Color.dark_gray(),
        )
        embed.add_field(name="Tier", value=str(p.nivel), inline=True)
        embed.add_field(name="Eficiência", value=f"{p.eficiencia}x", inline=True)
        embed.add_field(name="Chance de Abysmus", value=f"{int(p.chance_coins * 100)}%", inline=True)
        embed.add_field(name="Utilidade", value=p.utilidade, inline=False)
        embed.add_field(name="Efeito", value=p.efeito, inline=False)
        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # Exploração e descanso
    # =====================================================================
    @app_commands.command(name="explorar", description="Explore a região atual ou uma região desbloqueada.")
    @app_commands.describe(regiao="Região a explorar (opcional; padrão: região atual)")
    @app_commands.autocomplete(regiao=ac_regioes)
    @app_commands.guild_only()
    async def explorar(self, interaction: discord.Interaction, regiao: str | None = None):
        await interaction.response.defer()
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = await ctx["exploration"].explorar(regiao)
        if not res.get("sucesso"):
            motivo = res.get("motivo", "Falha na exploração.")
            if res.get("restante"):
                motivo += f" Aguarde {_tempo(res['restante'])}."
            await interaction.followup.send(f"❌ {motivo}", ephemeral=True)
            return

        novas = self._novas_conquistas(ctx)
        embed = discord.Embed(
            title=f"🗺️ {res['local']}",
            description=res.get("descricao", "")[:4000],
            color=discord.Color.blue(),
        )
        embed.add_field(name="Região", value=res["regiao"], inline=True)
        if res.get("descoberta_nova"):
            embed.add_field(name="Descoberta", value="📍 Novo local descoberto!", inline=True)
        elif res.get("nova_regiao"):
            embed.add_field(name="Descoberta", value="🌍 Nova região visitada!", inline=True)

        recompensas = []
        if res.get("moedas"):
            recompensas.append(f"🪙 +{res['moedas']:,} Abysmus")
        if res.get("item"):
            recompensas.append(f"📦 {res.get('item_qtd', 1)}× {res.get('item_nome')}")
        recompensas.append(f"✨ +{res['xp']} XP")
        embed.add_field(name="Recompensas", value="\n".join(recompensas), inline=False)

        xp = res.get("xp_personagem") or {}
        if xp.get("subiu_nivel"):
            embed.add_field(
                name="Nível",
                value=f"🌟 Subiu para o nível {xp.get('nivel_novo')}!",
                inline=False,
            )
        if res.get("profissao_xp"):
            prof = (
                f"+{res['profissao_xp']} XP de Explorador (nível {res.get('profissao_nivel')})"
                f"\nProgresso: {res.get('profissao_xp_atual', 0):,}/{res.get('profissao_xp_necessario', 0):,}"
            )
            if res.get("subiu_profissao"):
                prof += "\n🌟 Nível profissional aumentou!"
            embed.add_field(name="Profissão", value=prof, inline=False)

        if res.get("proximos"):
            embed.add_field(name="Na região", value="\n".join(res["proximos"][:3]), inline=False)
        self._campo_conquistas(embed, novas)

        fonte = res.get("fonte", "fallback")
        rodape = "Descrição narrativa: OpenRouter" if fonte == "openrouter" else (
            "Descrição narrativa local" if fonte != "cache" else "Descrição narrativa em cache"
        )
        embed.set_footer(
            text=f"{rodape} · saldo {res.get('saldo', 0):,} · próxima exploração em "
                 f"{_tempo(res.get('cooldown', 0))}"
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="descansar", description="Descanse para recuperar toda a energia.")
    @app_commands.guild_only()
    async def descansar(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["activities"].descansar()
        if not res.get("sucesso"):
            await interaction.response.send_message(
                f"❌ {res.get('motivo', 'Falha ao descansar.')}", ephemeral=True
            )
            return
        energia = ctx["energy"].obter_detalhado()
        embed = discord.Embed(
            title="😴 Descanso concluído",
            description=(
                f"Energia restaurada: ⚡ {energia['valor']}/{energia['max']}.\n"
                "O ciclo de recarga automática de 24h foi reiniciado."
            ),
            color=discord.Color.green(),
        )
        casa = ctx["houses"].obter_casa()
        if casa:
            embed.set_footer(text=f"Você descansou em sua {casa['nome']} (nível {casa['nivel']}).")
        else:
            embed.set_footer(text="Você descansou ao relento. Uma casa pode ser comprada no futuro.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="combate",
        description="Lute contra um inimigo; ataque com as mãos ou com um item.",
    )
    @app_commands.describe(
        inimigo="Inimigo para começar um novo combate",
        arma="Item da mochila para usar no ataque (ou Mãos)",
    )
    @app_commands.autocomplete(inimigo=ac_inimigos, arma=ac_armas_inventario)
    @app_commands.guild_only()
    async def combate(self, interaction: discord.Interaction,
                      inimigo: str | None = None, arma: str | None = None):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)

        if inimigo:
            res = ctx["combat"].iniciar(inimigo, arma)
        else:
            status = ctx["combat"].status()
            if status.get("estado") == "ativo" or arma:
                res = ctx["combat"].atacar(arma)
            else:
                await interaction.response.send_message(
                    embed=self._embed_catalogo_combate(status.get("catalogo", []))
                )
                return

        if not res.get("sucesso"):
            motivo = res.get("motivo", "Não foi possível continuar o combate.")
            if res.get("opcoes"):
                motivo += "\nOpções: " + ", ".join(res["opcoes"][:8])
            await interaction.response.send_message(f"❌ {motivo}", ephemeral=True)
            return

        novas = self._novas_conquistas(ctx)
        energia = ctx["energy"].obter_detalhado()
        embed = self._embed_combate(res, energia)
        self._campo_conquistas(embed, novas)
        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # Missões, conquistas, energia
    # =====================================================================
    @app_commands.command(name="rpgmissoes", description="Missões diárias do RPG.")
    @app_commands.guild_only()
    async def rpgmissoes(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        missoes = ctx["missions"].obter_missoes_diarias()
        if not missoes:
            await interaction.response.send_message("Sem missões disponíveis hoje.", ephemeral=True)
            return
        embed = discord.Embed(title="📜 Missões Diárias", color=discord.Color.blue())
        for m in missoes:
            try:
                dados = json.loads(m.get("dados_json") or "{}")
            except (TypeError, ValueError):
                dados = {}
            status = "✅" if m.get("estado") in ("concluida", "resgatada") else "⏳"
            meta = dados.get("meta", 1)
            embed.add_field(
                name=f"{status} {dados.get('desc', m.get('missao_key'))}",
                value=(
                    f"Progresso: {m.get('progresso', 0)}/{meta} · "
                    f"Recompensa: {dados.get('xp', 0)} XP"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="conquistas", description="Conquistas persistentes por categoria.")
    @app_commands.describe(categoria="Filtrar por categoria")
    @app_commands.choices(categoria=[
        app_commands.Choice(name="Todas", value="todas"),
        app_commands.Choice(name="Exploração", value="exploracao"),
        app_commands.Choice(name="Mineração", value="mineracao"),
        app_commands.Choice(name="Profissões", value="profissoes"),
        app_commands.Choice(name="Economia", value="economia"),
        app_commands.Choice(name="Progressão", value="progressao"),
        app_commands.Choice(name="Combate", value="combate"),
    ])
    @app_commands.guild_only()
    async def conquistas(self, interaction: discord.Interaction, categoria: str | None = None):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        self._novas_conquistas(ctx)
        cat = categoria or "todas"
        lista = ctx["achievements"].obter_todas(None if cat == "todas" else cat)
        resumo = ctx["achievements"].resumo() if cat != "todas" else None
        embed = criar_embed_conquistas(lista, resumo, None if cat == "todas" else cat)
        if cat == "combate":
            embed.set_footer(text="Vença batalhas em /combate. Cérbero é o inimigo especial.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="energia", description="Ver sua energia atual e a recarga automática.")
    @app_commands.guild_only()
    async def energia(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        dados = ctx["energy"].obter_detalhado()
        valor = int(dados["valor"])
        maximo = int(dados["max"])
        embed = discord.Embed(
            title="⚡ Energia",
            description=(
                f"**{valor}/{maximo}**\n{_barra(valor, maximo)}"
            ),
            color=discord.Color.yellow(),
        )
        if valor < maximo:
            embed.add_field(
                name="Recarga automática",
                value=f"⚡ Energia cheia em **{_tempo(int(dados['restante']))}**.",
                inline=False,
            )
        else:
            embed.add_field(
                name="Recarga automática",
                value="Energia cheia. O ciclo de 24h continua e não acumula além do máximo.",
                inline=False,
            )
        embed.set_footer(
            text="Recarrega 100% a cada 24h · /descansar restaura agora · "
                 "mineração 10, exploração 5, combate 4."
        )
        await interaction.response.send_message(embed=embed)

    # =====================================================================
    # Social
    # =====================================================================
    @app_commands.command(name="relacionamento", description="Status do relacionamento.")
    @app_commands.guild_only()
    async def relacionamento(self, interaction: discord.Interaction):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        rel = ctx["marriage"].obter_relacionamento_ativo()
        if not rel:
            await interaction.response.send_message(
                "Você não está em nenhum relacionamento.", ephemeral=True
            )
            return
        parceiro = rel["user_b"] if rel["user_a"] == interaction.user.id else rel["user_a"]
        embed = discord.Embed(title="💖 Relacionamento", color=discord.Color.magenta())
        embed.add_field(name="Tipo", value=rel["tipo"], inline=True)
        embed.add_field(name="Estado", value=rel["estado"], inline=True)
        embed.add_field(name="Parceiro", value=f"<@{parceiro}>", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="propor", description="Propor relacionamento.")
    @app_commands.describe(alvo="Membro", tipo="Tipo (namoro/casamento)")
    @app_commands.guild_only()
    async def propor(self, interaction: discord.Interaction, alvo: discord.Member,
                     tipo: str = "namoro"):
        ctx = self._get_ctx(interaction.guild_id, interaction.user.id)
        res = ctx["marriage"].propor(alvo.id, tipo)
        if not res.get("sucesso"):
            await interaction.response.send_message(
                f"❌ {res.get('motivo', 'Falha na proposta.')}", ephemeral=True
            )
            return
        await interaction.response.send_message(f"💌 Proposta enviada para {alvo.mention}!")


async def setup(bot: commands.Bot):
    await bot.add_cog(RPG(bot))
