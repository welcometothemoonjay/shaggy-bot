"""Próximos objetivos do jogador.

Os objetivos são derivados do estado real do banco. Não são uma nova
mecânica: apenas transformam nível, profissões, picaretas, saldo, conquistas e
regiões em uma lista curta e acionável para a interface.
"""
from __future__ import annotations

from typing import Any

from .achievements_v2 import AchievementsV2
from .constants import xp_para_proximo_nivel
from .database import get_db
from .economy import obter_saldo_tx
from .progression import calcular_nivel
from .schema import garantir_tabelas
from .tools import PICARETAS
from .world import REGIOES, obter_local


def _objetivo(chave: str, titulo: str, descricao: str, progresso: int = 0,
              meta: int = 0, comando: str = "") -> dict[str, Any]:
    return {
        "chave": chave,
        "titulo": titulo,
        "descricao": descricao,
        "progresso": int(progresso),
        "meta": int(meta),
        "comando": comando,
    }


def obter_objetivos(guild_id: int, user_id: int, limite: int = 5) -> list[dict[str, Any]]:
    garantir_tabelas()
    with get_db().transacao() as db:
        char = db.execute(
            "SELECT nivel, xp, regiao FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if not char:
            return [
                _objetivo(
                    "criar_personagem",
                    "Criar seu personagem",
                    "Use /rpg para começar sua jornada.",
                    0, 1, "/rpg",
                )
            ]
        nivel, xp_total, regiao = int(char[0]), int(char[1]), char[2]
        nivel_atual, xp_nivel, xp_proximo = calcular_nivel(xp_total)

        saldo = obter_saldo_tx(db, guild_id, user_id)
        inv = {
            row[0]: int(row[1])
            for row in db.execute(
                "SELECT item_key, quantidade FROM ruptura_inventario "
                "WHERE guild_id = ? AND user_id = ? AND quantidade > 0",
                (guild_id, user_id),
            ).fetchall()
        }
        profs = {
            row[0]: {"nivel": int(row[1]), "xp": int(row[2])}
            for row in db.execute(
                "SELECT chave, nivel, xp FROM rpg_profissoes WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchall()
        }
        visitadas = {
            row[0] for row in db.execute(
                "SELECT regiao FROM rpg_regioes WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchall()
        }
        local_row = db.execute(
            "SELECT local_key FROM rpg_localizacao WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        local_key = local_row[0] if local_row else None
        acoes = {
            row[0]: int(row[1])
            for row in db.execute(
                "SELECT tipo, COUNT(*) FROM rpg_acoes "
                "WHERE guild_id = ? AND user_id = ? "
                "AND tipo IN ('combate_vitoria', 'combate_derrota') "
                "GROUP BY tipo",
                (guild_id, user_id),
            ).fetchall()
        }
        combate_ativo = db.execute(
            "SELECT 1 FROM rpg_combates WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone() is not None

    objetivos: list[dict[str, Any]] = []

    # 1) Próximo nível do personagem.
    objetivos.append(_objetivo(
        "nivel_personagem",
        f"Alcançar o nível {nivel_atual + 1}",
        f"Faltam {max(0, xp_proximo - xp_nivel):,} XP. Minerar, explorar, trabalhar e combater concedem XP.",
        xp_nivel, xp_proximo, "/personagem",
    ))

    # 2) Próximo passo profissional.
    from .professions_v2 import PROFISSOES, xp_necessario

    if not profs:
        disponiveis = [
            info for info in PROFISSOES.values()
            if nivel_atual >= int(info.get("requisitos", {}).get("nivel_personagem", 1) or 1)
        ]
        if disponiveis:
            info = disponiveis[0]
            objetivos.append(_objetivo(
                "primeira_profissao",
                "Aprender uma profissão",
                f"{info['nome']}: {info['descricao']}",
                0, 1, f"/aprender_profissao profissao:{info['nome']}",
            ))
    else:
        chave, dados = min(
            profs.items(),
            key=lambda item: (
                xp_necessario(item[1]["nivel"]) - item[1]["xp"],
                item[0],
            ),
        )
        info = PROFISSOES.get(chave, {"nome": chave.title()})
        meta = xp_necessario(dados["nivel"])
        objetivos.append(_objetivo(
            f"profissao_{chave}",
            f"{info['nome']} — próximo nível",
            f"Faltam {max(0, meta - dados['xp']):,} XP profissionais.",
            dados["xp"], meta, f"/trabalhar profissao:{info['nome']}",
        ))

    # 3) Próxima picareta.
    owned = [(PICARETAS[k].nivel, k) for k in PICARETAS if inv.get(k, 0) > 0]
    if owned:
        melhor_nivel, _ = max(owned)
        proximas = [p for p in PICARETAS.values() if p.nivel > melhor_nivel]
        if proximas:
            proxima = sorted(proximas, key=lambda p: p.nivel)[0]
            requisito = int(proxima.requisitos.get("nivel_personagem", 1) or 1)
            falta = max(0, proxima.preco - saldo)
            desc = f"Custa {proxima.preco:,} Abysmus."
            if falta:
                desc += f" Faltam {falta:,}."
            if nivel_atual < requisito:
                desc += f" Requer nível {requisito} (atual {nivel_atual})."
            objetivos.append(_objetivo(
                "proxima_picareta",
                f"Próxima picareta: {proxima.nome}",
                desc,
                min(saldo, proxima.preco), proxima.preco,
                f"/comprar item:{proxima.nome}",
            ))
    else:
        madeira = PICARETAS["picareta_madeira"]
        objetivos.append(_objetivo(
            "primeira_picareta",
            "Obter uma picareta",
            "A Picareta de Madeira é entregue ao criar o personagem. Use /rpg.",
            0, 1, "/rpg",
        ))

    # 4) Próxima região.
    candidatas = sorted(REGIOES.values(), key=lambda r: r["nivel_min"])
    nao_visitadas = [r for r in candidatas if r["key"] not in visitadas]
    if nao_visitadas:
        regiao = nao_visitadas[0]
        if nivel_atual >= regiao["nivel_min"]:
            objetivos.append(_objetivo(
                "explorar_regiao",
                f"Explorar {regiao['nome']}",
                regiao["descricao"],
                0, 1, f"/explorar regiao:{regiao['nome']}",
            ))
        else:
            objetivos.append(_objetivo(
                "liberar_regiao",
                f"Desbloquear {regiao['nome']}",
                f"Requer nível {regiao['nivel_min']} (atual {nivel_atual}).",
                nivel_atual, regiao["nivel_min"], "/personagem",
            ))

    # 5) Combate: continuar, primeira vitória ou acumular vitórias.
    vitorias = acoes.get("combate_vitoria", 0)
    if combate_ativo:
        objetivos.append(_objetivo(
            "combate_ativo",
            "Continuar o combate",
            "Você tem uma batalha em andamento. Ataque ou troque de arma.",
            0, 1, "/combate",
        ))
    elif vitorias == 0:
        objetivos.append(_objetivo(
            "primeira_vitoria",
            "Vença seu primeiro combate",
            "Enfrente o Goblin com as mãos ou com um item da mochila.",
            0, 1, "/combate inimigo:Goblin",
        ))
    elif vitorias < 10:
        objetivos.append(_objetivo(
            "combate_vitorias",
            "Vença 10 combates",
            f"Vitórias: {vitorias}/10. Cada golpe também concede XP.",
            vitorias, 10, "/combate",
        ))

    # 6) Próxima conquista com maior progresso relativo.
    try:
        todas = AchievementsV2(guild_id, user_id).obter_todas()
        pendentes = [c for c in todas if not c["desbloqueada"]]
        if pendentes:
            pendentes.sort(
                key=lambda c: (-int(c.get("progresso_pct", 0)), c.get("meta", 1), c["nome"])
            )
            alvo = pendentes[0]
            objetivos.append(_objetivo(
                f"conquista_{alvo['chave']}",
                f"Conquista: {alvo['nome']}",
                alvo["descricao"] + f" (+{alvo['recompensa_xp']} XP, +{alvo['recompensa_coins']} 🪙)",
                alvo.get("progresso", 0), alvo.get("meta", 1), "/conquistas",
            ))
    except Exception:
        pass

    # Remove repetições de chave preservando a ordem.
    vistos: set[str] = set()
    finais = []
    for obj in objetivos:
        if obj["chave"] in vistos:
            continue
        vistos.add(obj["chave"])
        finais.append(obj)
    return finais[:max(1, limite)]
