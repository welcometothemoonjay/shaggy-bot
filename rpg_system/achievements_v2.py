"""Conquistas persistentes do RPG Textual.

As conquistas são declarativas e idempotentes: a chave é única por jogador
(PK em ``rpg_conquistas``). A recompensa só é creditada quando o INSERT
realmente insere uma linha nova, portanto nunca há concessão duplicada.
"""
from __future__ import annotations

import time
from typing import Any

from .database import get_db
from .economy import obter_saldo_tx, alterar_saldo_tx
from .progression import adicionar_xp_tx
from .schema import garantir_tabelas
from .world import LOCAIS

CATEGORIAS = {
    "exploracao": "🗺️ Exploração",
    "mineracao": "⛏️ Mineração",
    "profissoes": "⚒️ Profissões",
    "economia": "🪙 Economia",
    "combate": "⚔️ Combate",
    "progressao": "🌟 Progressão",
}

# ``condicao`` ausente significa "verificar apenas se o personagem existe".
CONQUISTAS: dict[str, dict[str, Any]] = {
    # -------- Exploração --------
    "primeiro_passo": {
        "nome": "Primeiro Passo", "descricao": "Crie seu personagem.",
        "categoria": "exploracao", "recompensa_xp": 40, "recompensa_coins": 0,
        "condicao": {"tipo": "personagem"},
    },
    "primeira_exploracao": {
        "nome": "Primeira Exploração", "descricao": "Explore pela primeira vez.",
        "categoria": "exploracao", "recompensa_xp": 50, "recompensa_coins": 2,
        "condicao": {"tipo": "acoes", "acao": "explorar", "quantidade": 1},
    },
    "explorador": {
        "nome": "Explorador", "descricao": "Explore 20 vezes.",
        "categoria": "exploracao", "recompensa_xp": 150, "recompensa_coins": 10,
        "condicao": {"tipo": "acoes", "acao": "explorar", "quantidade": 20},
    },
    "viajante": {
        "nome": "Viajante", "descricao": "Explore 50 vezes.",
        "categoria": "exploracao", "recompensa_xp": 300, "recompensa_coins": 25,
        "condicao": {"tipo": "acoes", "acao": "explorar", "quantidade": 50},
    },
    "cartografo": {
        "nome": "Cartógrafo", "descricao": "Explore 100 vezes.",
        "categoria": "exploracao", "recompensa_xp": 500, "recompensa_coins": 50,
        "condicao": {"tipo": "acoes", "acao": "explorar", "quantidade": 100},
    },
    "descobridor": {
        "nome": "Descobridor", "descricao": "Descubra 5 locais diferentes.",
        "categoria": "exploracao", "recompensa_xp": 200, "recompensa_coins": 15,
        "condicao": {"tipo": "descobertas", "quantidade": 5},
    },
    "tres_regioes": {
        "nome": "Três Horizontes", "descricao": "Visite 3 regiões diferentes.",
        "categoria": "exploracao", "recompensa_xp": 250, "recompensa_coins": 20,
        "condicao": {"tipo": "regioes", "quantidade": 3},
    },
    "local_especial": {
        "nome": "Além do Mapa", "descricao": "Descubra um local especial.",
        "categoria": "exploracao", "recompensa_xp": 300, "recompensa_coins": 30,
        "condicao": {"tipo": "local_especial", "quantidade": 1},
    },
    # -------- Mineração --------
    "primeiro_minerio": {
        "nome": "Primeiro Minério", "descricao": "Minere pela primeira vez.",
        "categoria": "mineracao", "recompensa_xp": 40, "recompensa_coins": 2,
        "condicao": {"tipo": "acoes", "acao": "minerar", "quantidade": 1},
    },
    "minerador_iniciante": {
        "nome": "Minerador Iniciante", "descricao": "Minere 10 vezes.",
        "categoria": "mineracao", "recompensa_xp": 100, "recompensa_coins": 8,
        "condicao": {"tipo": "acoes", "acao": "minerar", "quantidade": 10},
    },
    "trabalhador_profundezas": {
        "nome": "Trabalhador das Profundezas", "descricao": "Minere 50 vezes.",
        "categoria": "mineracao", "recompensa_xp": 250, "recompensa_coins": 20,
        "condicao": {"tipo": "acoes", "acao": "minerar", "quantidade": 50},
    },
    "maos_diamante": {
        "nome": "Mãos de Diamante", "descricao": "Minere 100 vezes.",
        "categoria": "mineracao", "recompensa_xp": 500, "recompensa_coins": 40,
        "condicao": {"tipo": "acoes", "acao": "minerar", "quantidade": 100},
    },
    "senhor_profundezas": {
        "nome": "Senhor das Profundezas", "descricao": "Minere 250 vezes.",
        "categoria": "mineracao", "recompensa_xp": 1000, "recompensa_coins": 80,
        "condicao": {"tipo": "acoes", "acao": "minerar", "quantidade": 250},
    },
    "primeira_moeda_mineracao": {
        "nome": "Veio de Abysmus", "descricao": "Encontre Abysmus durante uma mineração.",
        "categoria": "mineracao", "recompensa_xp": 60, "recompensa_coins": 3,
        "condicao": {"tipo": "mineracao_coins", "quantidade": 1},
    },
    "picareta_ferro": {
        "nome": "Ferro nas Mãos", "descricao": "Minere com uma Picareta de Ferro ou superior.",
        "categoria": "mineracao", "recompensa_xp": 120, "recompensa_coins": 10,
        "condicao": {"tipo": "maior_tier", "quantidade": 4},
    },
    "picareta_diamante": {
        "nome": "Coração de Diamante", "descricao": "Minere com uma Picareta de Diamante ou superior.",
        "categoria": "mineracao", "recompensa_xp": 350, "recompensa_coins": 30,
        "condicao": {"tipo": "maior_tier", "quantidade": 7},
    },
    "picareta_infernal": {
        "nome": "Forja Infernal", "descricao": "Minere com a Picareta Infernal.",
        "categoria": "mineracao", "recompensa_xp": 900, "recompensa_coins": 100,
        "condicao": {"tipo": "maior_tier", "quantidade": 10},
    },
    "achado_raro": {
        "nome": "Achado Raro", "descricao": "Encontre um material raro minerando.",
        "categoria": "mineracao", "recompensa_xp": 150, "recompensa_coins": 12,
        "condicao": {"tipo": "acoes", "acao": "minerar_raro", "quantidade": 1},
    },
    "colecionador_minerais": {
        "nome": "Colecionador de Minerais", "descricao": "Colete 100 materiais minerando.",
        "categoria": "mineracao", "recompensa_xp": 300, "recompensa_coins": 25,
        "condicao": {"tipo": "total_materiais", "quantidade": 100},
    },
    # -------- Profissões --------
    "primeiro_oficio": {
        "nome": "Primeiro Ofício", "descricao": "Aprenda uma profissão.",
        "categoria": "profissoes", "recompensa_xp": 60, "recompensa_coins": 5,
        "condicao": {"tipo": "profissoes", "quantidade": 1},
    },
    "especialista": {
        "nome": "Especialista", "descricao": "Alcance nível 5 em uma profissão.",
        "categoria": "profissoes", "recompensa_xp": 200, "recompensa_coins": 15,
        "condicao": {"tipo": "nivel_profissao", "quantidade": 5},
    },
    "mestre_oficio": {
        "nome": "Mestre de Ofício", "descricao": "Alcance nível 10 em uma profissão.",
        "categoria": "profissoes", "recompensa_xp": 500, "recompensa_coins": 40,
        "condicao": {"tipo": "nivel_profissao", "quantidade": 10},
    },
    "polivalente": {
        "nome": "Polivalente", "descricao": "Aprenda 3 profissões diferentes.",
        "categoria": "profissoes", "recompensa_xp": 250, "recompensa_coins": 20,
        "condicao": {"tipo": "profissoes", "quantidade": 3},
    },
    # -------- Economia --------
    "primeiro_negocio": {
        "nome": "Primeiro Negócio", "descricao": "Realize sua primeira compra.",
        "categoria": "economia", "recompensa_xp": 40, "recompensa_coins": 2,
        "condicao": {"tipo": "acoes", "acao": "comprar", "quantidade": 1},
    },
    "comerciante": {
        "nome": "Comerciante", "descricao": "Realize 10 compras.",
        "categoria": "economia", "recompensa_xp": 150, "recompensa_coins": 10,
        "condicao": {"tipo": "acoes", "acao": "comprar", "quantidade": 10},
    },
    "cliente_frequente": {
        "nome": "Cliente Frequente", "descricao": "Realize 50 compras.",
        "categoria": "economia", "recompensa_xp": 400, "recompensa_coins": 30,
        "condicao": {"tipo": "acoes", "acao": "comprar", "quantidade": 50},
    },
    "investidor": {
        "nome": "Investidor", "descricao": "Acumule 2.500 Abysmus.",
        "categoria": "economia", "recompensa_xp": 150, "recompensa_coins": 0,
        "condicao": {"tipo": "saldo", "quantidade": 2500},
    },
    "acumulador": {
        "nome": "Acumulador", "descricao": "Acumule 10.000 Abysmus.",
        "categoria": "economia", "recompensa_xp": 300, "recompensa_coins": 0,
        "condicao": {"tipo": "saldo", "quantidade": 10000},
    },
    # -------- Progressão --------
    "nivel_5": {
        "nome": "Aprendiz", "descricao": "Alcance o nível 5.",
        "categoria": "progressao", "recompensa_xp": 100, "recompensa_coins": 5,
        "condicao": {"tipo": "nivel_personagem", "quantidade": 5},
    },
    "nivel_10": {
        "nome": "Aventureiro", "descricao": "Alcance o nível 10.",
        "categoria": "progressao", "recompensa_xp": 250, "recompensa_coins": 15,
        "condicao": {"tipo": "nivel_personagem", "quantidade": 10},
    },
    "nivel_25": {
        "nome": "Veterano", "descricao": "Alcance o nível 25.",
        "categoria": "progressao", "recompensa_xp": 600, "recompensa_coins": 40,
        "condicao": {"tipo": "nivel_personagem", "quantidade": 25},
    },
    "nivel_50": {
        "nome": "Lenda Viva", "descricao": "Alcance o nível 50.",
        "categoria": "progressao", "recompensa_xp": 1500, "recompensa_coins": 100,
        "condicao": {"tipo": "nivel_personagem", "quantidade": 50},
    },
    # -------- Combate (ativo desde a evolução do combate por turnos) --------
    "primeira_vitoria": {
        "nome": "Primeira Vitória", "descricao": "Vença um combate.",
        "categoria": "combate", "recompensa_xp": 80, "recompensa_coins": 5,
        "condicao": {"tipo": "acoes", "acao": "combate_vitoria", "quantidade": 1},
    },
    "vencedor": {
        "nome": "Vencedor", "descricao": "Vença 10 combates.",
        "categoria": "combate", "recompensa_xp": 250, "recompensa_coins": 20,
        "condicao": {"tipo": "acoes", "acao": "combate_vitoria", "quantidade": 10},
    },
    "cacador_lendas": {
        "nome": "Caçador de Lendas", "descricao": "Derrote um inimigo especial.",
        "categoria": "combate", "recompensa_xp": 500, "recompensa_coins": 50,
        "condicao": {"tipo": "acoes", "acao": "combate_especial", "quantidade": 1},
    },
}


def _texto_condicao(info: dict[str, Any]) -> str:
    cond = info.get("condicao") or {}
    tipo = cond.get("tipo")
    qtd = int(cond.get("quantidade", 1) or 1)
    if tipo == "personagem":
        return "Criar personagem"
    if tipo == "acoes":
        return f"{cond.get('acao', 'ação')}: {qtd}"
    if tipo == "nivel_personagem":
        return f"Nível de personagem {qtd}"
    if tipo == "nivel_profissao":
        return f"Nível de profissão {qtd}"
    if tipo == "profissoes":
        return f"{qtd} profissão(ões)"
    if tipo == "saldo":
        return f"Saldo de {qtd:,} Abysmus"
    if tipo == "descobertas":
        return f"{qtd} local(is) descoberto(s)"
    if tipo == "regioes":
        return f"{qtd} região(ões) visitada(s)"
    if tipo == "mineracao_coins":
        return "Encontrar Abysmus minerando"
    if tipo == "maior_tier":
        return f"Picareta de tier {qtd}"
    if tipo == "total_materiais":
        return f"{qtd} materiais minerados"
    if tipo == "local_especial":
        return "Descobrir um local especial"
    return "Condição especial"


class AchievementsV2:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        garantir_tabelas()

    # ---------------- snapshot ----------------
    def _snapshot_tx(self, db) -> dict[str, Any]:
        char = db.execute(
            "SELECT nivel, xp FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        counts = {
            row[0]: int(row[1])
            for row in db.execute(
                "SELECT tipo, COUNT(*) FROM rpg_acoes WHERE guild_id = ? AND user_id = ? GROUP BY tipo",
                (self.guild_id, self.user_id),
            ).fetchall()
        }
        profs = db.execute(
            "SELECT COUNT(*), COALESCE(MAX(nivel), 0) FROM rpg_profissoes WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        stats = db.execute(
            "SELECT coins_total, total_materiais, maior_tier FROM rpg_mineracao_stats "
            "WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        descobertas = db.execute(
            "SELECT local_key FROM rpg_descobertas WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchall()
        locais_especiais = sum(1 for r in descobertas if LOCAIS.get(r[0], {}).get("especial"))
        regioes = db.execute(
            "SELECT COUNT(*) FROM rpg_regioes WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()[0]
        return {
            "char": char,
            "nivel": int(char[0]) if char else 0,
            "xp": int(char[1]) if char else 0,
            "counts": counts,
            "prof_count": int(profs[0]) if profs else 0,
            "max_prof": int(profs[1]) if profs else 0,
            "saldo": obter_saldo_tx(db, self.guild_id, self.user_id),
            "moedas_mineradas": int(stats[0]) if stats else 0,
            "materiais_minerados": int(stats[1]) if stats else 0,
            "maior_tier": int(stats[2]) if stats else 0,
            "descobertas": len(descobertas),
            "local_especial": locais_especiais,
            "regioes": int(regioes or 0),
        }

    def _valor(self, cond: dict[str, Any], snap: dict[str, Any]) -> int:
        tipo = cond.get("tipo")
        if tipo == "personagem":
            return 1 if snap["char"] else 0
        if tipo == "acoes":
            return int(snap["counts"].get(cond.get("acao", ""), 0))
        if tipo == "nivel_personagem":
            return snap["nivel"]
        if tipo == "nivel_profissao":
            return snap["max_prof"]
        if tipo == "profissoes":
            return snap["prof_count"]
        if tipo == "saldo":
            return snap["saldo"]
        if tipo == "descobertas":
            return snap["descobertas"]
        if tipo == "regioes":
            return snap["regioes"]
        if tipo == "mineracao_coins":
            return snap["moedas_mineradas"]
        if tipo == "maior_tier":
            return snap["maior_tier"]
        if tipo == "total_materiais":
            return snap["materiais_minerados"]
        if tipo == "local_especial":
            return snap["local_especial"]
        return 0

    # ---------------- consulta ----------------
    def obter_todas(self, categoria: str | None = None) -> list[dict[str, Any]]:
        with self.db.transacao() as db:
            snap = self._snapshot_tx(db)
            desbloqueadas = {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT chave, desbloqueada_em FROM rpg_conquistas "
                    "WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchall()
            }
        res = []
        for chave, info in CONQUISTAS.items():
            if categoria and categoria not in ("todas", "") and info["categoria"] != categoria:
                continue
            cond = info.get("condicao") or {}
            meta = int(cond.get("quantidade", 1) or 1)
            valor = self._valor(cond, snap) if cond else (1 if snap["char"] else 0)
            desbloqueada = chave in desbloqueadas
            res.append({
                "chave": chave,
                "nome": info["nome"],
                "descricao": info["descricao"],
                "categoria": info["categoria"],
                "recompensa_xp": int(info.get("recompensa_xp", 0)),
                "recompensa_coins": int(info.get("recompensa_coins", 0)),
                "desbloqueada": desbloqueada,
                "desbloqueada_em": desbloqueadas.get(chave),
                "progresso": min(meta, valor),
                "meta": meta,
                "progresso_pct": min(100, int((valor / meta) * 100)) if meta > 0 else 100,
                "condicao_texto": _texto_condicao(info),
            })
        res.sort(key=lambda c: (c["desbloqueada"], c["categoria"], c["nome"]))
        return res

    def resumo(self) -> dict[str, dict[str, int]]:
        res: dict[str, dict[str, int]] = {k: {"total": 0, "desbloqueadas": 0} for k in CATEGORIAS}
        for c in self.obter_todas():
            res.setdefault(c["categoria"], {"total": 0, "desbloqueadas": 0})
            res[c["categoria"]]["total"] += 1
            if c["desbloqueada"]:
                res[c["categoria"]]["desbloqueadas"] += 1
        return res

    # ---------------- verificação / concessão ----------------
    def verificar(self) -> list[dict[str, Any]]:
        agora = time.time()
        novas: list[dict[str, Any]] = []
        with self.db.transacao() as db:
            snap = self._snapshot_tx(db)
            existentes = {
                row[0]
                for row in db.execute(
                    "SELECT chave FROM rpg_conquistas WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchall()
            }

            for chave, info in CONQUISTAS.items():
                if chave in existentes:
                    continue
                cond = info.get("condicao") or {"tipo": "personagem"}
                meta = int(cond.get("quantidade", 1) or 1)
                if self._valor(cond, snap) < meta:
                    continue

                cur = db.execute(
                    "INSERT OR IGNORE INTO rpg_conquistas (guild_id, user_id, chave, desbloqueada_em) "
                    "VALUES (?, ?, ?, ?)",
                    (self.guild_id, self.user_id, chave, agora),
                )
                if cur.rowcount != 1:
                    # Outra chamada simultânea já concedeu.
                    continue

                xp = int(info.get("recompensa_xp", 0) or 0)
                coins = int(info.get("recompensa_coins", 0) or 0)
                if xp > 0:
                    adicionar_xp_tx(db, self.guild_id, self.user_id, xp)
                if coins > 0:
                    alterar_saldo_tx(db, self.guild_id, self.user_id, coins)

                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'conquista', ?, ?)",
                    (self.guild_id, self.user_id, chave, agora),
                )
                novas.append({
                    "chave": chave,
                    "nome": info["nome"],
                    "descricao": info["descricao"],
                    "categoria": info["categoria"],
                    "recompensa_xp": xp,
                    "recompensa_coins": coins,
                })
                existentes.add(chave)
        return novas
