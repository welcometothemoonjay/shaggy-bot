"""Views e embeds compartilhados do RPG Textual."""
from __future__ import annotations

from typing import Any

import discord

from .progression import calcular_nivel
from .world import obter_local, obter_regiao


class RPGMenu(discord.ui.View):
    def __init__(self, user_id: int, timeout: int = 180):
        super().__init__(timeout=timeout)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Este menu não é para você.", ephemeral=True
            )
            return False
        return True


def _nome_regiao(chave: str) -> str:
    regiao = obter_regiao(chave)
    return regiao["nome"] if regiao else (chave or "Dakor")


def _nome_local(chave: str) -> str:
    local = obter_local(chave)
    return local["nome"] if local else (chave or "Desconhecido")


def _barra(atual: int, total: int, tamanho: int = 10) -> str:
    total = max(1, int(total))
    atual = max(0, min(int(atual), total))
    preenchidos = int(round((atual / total) * tamanho))
    return "▰" * preenchidos + "▱" * (tamanho - preenchidos)


def _tempo_curto(segundos: int) -> str:
    segundos = max(0, int(segundos))
    if segundos >= 3600:
        return f"{segundos // 3600}h{(segundos % 3600) // 60:02d}m"
    if segundos >= 60:
        return f"{segundos // 60}m{segundos % 60:02d}s"
    return f"{segundos}s"


def criar_embed_personagem(personagem: dict, extras: dict[str, Any] | None = None) -> discord.Embed:
    extras = extras or {}
    nome = personagem.get("nome") or "Aventureiro"
    nivel, xp_nivel, xp_proximo = calcular_nivel(int(personagem.get("xp", 0) or 0))

    embed = discord.Embed(
        title=f"🧭 Ficha — {nome}",
        color=discord.Color.dark_gold(),
    )
    embed.add_field(name="Nível", value=f"**{nivel}**", inline=True)
    embed.add_field(
        name="XP",
        value=f"{xp_nivel:,}/{xp_proximo:,}\n{_barra(xp_nivel, xp_proximo)}",
        inline=True,
    )
    embed.add_field(name="Reputação", value=f"{personagem.get('reputacao', 0):,}", inline=True)
    embed.add_field(name="Classe", value=str(personagem.get("classe_key", "aventureiro")).title(), inline=True)

    regiao_key = extras.get("regiao") or personagem.get("regiao") or "dakor"
    local_key = extras.get("local_key")
    valor_regiao = _nome_regiao(regiao_key)
    if local_key:
        valor_regiao += f"\n📍 {_nome_local(local_key)}"
    embed.add_field(name="Região", value=valor_regiao, inline=True)

    if "saldo" in extras:
        embed.add_field(name="Abysmus", value=f"🪙 {int(extras['saldo']):,}", inline=True)
    if "energia" in extras:
        maximo = int(extras.get("energia_max", 100))
        atual = int(extras["energia"])
        texto = f"⚡ {atual}/{maximo}"
        if atual < maximo and extras.get("energia_regen"):
            texto += f"\n⏳ recarga em {_tempo_curto(extras['energia_regen'])}"
        embed.add_field(name="Energia", value=texto, inline=True)

    profs = extras.get("profissoes")
    if profs:
        linhas = []
        for p in profs[:6]:
            linhas.append(f"{p.get('nome') or p.get('chave')}: nível {p.get('nivel', 1)}")
        if len(profs) > 6:
            linhas.append(f"… e mais {len(profs) - 6}")
        embed.add_field(name="Profissões", value="\n".join(linhas), inline=False)
    elif extras.get("profissoes_vazio"):
        embed.add_field(
            name="Profissões",
            value="Nenhuma ainda. Use `/profissoes` e `/aprender_profissao`.",
            inline=False,
        )

    casa = extras.get("casa")
    if casa:
        embed.add_field(
            name="Casa",
            value=f"{casa.get('nome', casa.get('tipo', 'Abrigo'))} (nível {casa.get('nivel', 1)})",
            inline=True,
        )
    elif "casa" in extras:
        embed.add_field(name="Casa", value="Sem moradia fixa", inline=True)

    conquistas = extras.get("conquistas")
    if conquistas:
        embed.add_field(
            name="Conquistas",
            value=f"🏆 {conquistas.get('desbloqueadas', 0)}/{conquistas.get('total', 0)}",
            inline=True,
        )

    combate = extras.get("combate")
    if combate:
        texto_combate = (
            f"⚔️ {combate.get('vitorias', 0)} vitórias · "
            f"💀 {combate.get('derrotas', 0)} derrotas"
        )
        if combate.get("ativo"):
            texto_combate += "\n🔥 Combate ativo — use `/combate`."
        embed.add_field(name="Combate", value=texto_combate, inline=False)

    objetivos = extras.get("objetivos") or []
    if objetivos:
        linhas = []
        for obj in objetivos[:4]:
            progresso = ""
            if obj.get("meta"):
                progresso = f" ({obj.get('progresso', 0):,}/{obj['meta']:,})"
            linhas.append(f"• **{obj.get('titulo')}**{progresso} — {obj.get('descricao')}")
        embed.add_field(name="Próximos objetivos", value="\n".join(linhas), inline=False)

    embed.set_footer(text="Use /explorar, /mineracao, /combate, /mercador e /conquistas.")
    return embed


def criar_embed_conquistas(conquistas: list[dict], resumo: dict | None = None,
                           categoria: str | None = None) -> discord.Embed:
    desbloqueadas = sum(1 for c in conquistas if c["desbloqueada"])
    total = len(conquistas)
    embed = discord.Embed(
        title="🏆 Conquistas",
        description=f"**{desbloqueadas}/{total}** desbloqueadas nesta visão.",
        color=discord.Color.purple(),
    )
    if resumo:
        linhas = []
        for chave, dados in resumo.items():
            if dados["total"] <= 0:
                continue
            linhas.append(f"• {chave.title()}: {dados['desbloqueadas']}/{dados['total']}")
        if linhas:
            embed.add_field(name="Resumo", value="\n".join(linhas), inline=False)

    itens = [c for c in conquistas if categoria in (None, "", "todas") or c["categoria"] == categoria]
    linhas = []
    for c in itens:
        if c["desbloqueada"]:
            linhas.append(f"✅ **{c['nome']}** — {c['descricao']}")
        else:
            meta = c.get("meta", 1) or 1
            linhas.append(
                f"🔒 **{c['nome']}** — {c['descricao']} "
                f"`{c.get('progresso', 0):,}/{meta:,}` "
                f"(+{c['recompensa_xp']} XP, +{c['recompensa_coins']} 🪙)"
            )
    texto = "\n".join(linhas)
    if len(texto) > 3900:
        texto = texto[:3890] + "\n…"
    embed.add_field(name="Lista", value=texto or "Nenhuma conquista nesta categoria.", inline=False)
    return embed
