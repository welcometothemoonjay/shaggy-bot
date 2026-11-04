"""Mineração do RPG Textual.

Regra única de equipamento: a picareta equipada tem prioridade; se não houver
uma equipada, a melhor picareta possuída é usada automaticamente. Em todos os
casos é obrigatório possuir uma picareta válida.

Toda a mineração (validação, energia, cooldown, recompensas, XP, itens,
estatísticas e histórico) acontece em UMA transação SQLite. Chamadas
simultâneas não duplicam recompensas.
"""
from __future__ import annotations

import random
import sqlite3
import time
from typing import Any

from .constants import (
    MINING_COOLDOWN_SEGUNDOS,
    MINING_ENERGIA_CUSTO,
)
from .database import get_db
from .economy import obter_saldo_tx, alterar_saldo_tx
from .inventory import Inventario
from .items import nome_item
from .progression import adicionar_xp_tx
from .schema import garantir_tabelas
from .tools import PICARETAS, MATERIAIS_MINERAIS, CHANCES_COINS, obter_picareta
from .world import REGIOES, obter_regiao, obter_local


class MiningV2:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.inventory = Inventario(guild_id, user_id)
        garantir_tabelas()

    # ---------------- estado ----------------
    def _picareta_tx(self, db) -> str | None:
        row = db.execute(
            "SELECT item_key FROM rpg_equipamentos WHERE guild_id = ? AND user_id = ? AND slot = 'picareta'",
            (self.guild_id, self.user_id),
        ).fetchone()
        inv = self.inventory.obter_tx(db)
        if row and row[0] in PICARETAS and inv.get(row[0], 0) > 0:
            return row[0]
        possuidas = [(PICARETAS[k].nivel, k) for k in PICARETAS if inv.get(k, 0) > 0]
        return max(possuidas)[1] if possuidas else None

    def obter_regiao_tx(self, db, regiao: str | None = None) -> str | None:
        if regiao and regiao in REGIOES:
            return regiao
        char = db.execute(
            "SELECT regiao FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        if char and char[0] in REGIOES:
            return char[0]
        local = db.execute(
            "SELECT local_key FROM rpg_localizacao WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        if local:
            info = obter_local(local[0])
            if info and info["regiao"] in REGIOES:
                return info["regiao"]
        return "dakor"

    def _regiao_liberada_tx(self, db, regiao_key: str, nivel_personagem: int) -> tuple[bool, str]:
        regiao = obter_regiao(regiao_key)
        if not regiao:
            return False, "Região desconhecida."
        if nivel_personagem < regiao["nivel_min"]:
            return False, f"A região {regiao['nome']} requer nível {regiao['nivel_min']}."
        if regiao_key != "dakor":
            row = db.execute(
                "SELECT 1 FROM rpg_regioes WHERE guild_id = ? AND user_id = ? AND regiao = ?",
                (self.guild_id, self.user_id, regiao_key),
            ).fetchone()
            if not row:
                return False, f"Você ainda não explorou {regiao['nome']}. Use /explorar para descobri-la."
        return True, ""

    def pode_minar(self, regiao: str | None = None) -> bool:
        return self.verificar(regiao).get("pode", False)

    def verificar(self, regiao: str | None = None) -> dict[str, Any]:
        with self.db.transacao() as db:
            char = db.execute(
                "SELECT nivel FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchone()
            if not char:
                return {"pode": False, "motivo": "Crie seu personagem com /rpg primeiro."}
            chave_regiao = self.obter_regiao_tx(db, regiao)
            ok, motivo = self._regiao_liberada_tx(db, chave_regiao, int(char[0]))
            if not ok:
                return {"pode": False, "motivo": motivo}
            pic = self._picareta_tx(db)
            if not pic:
                return {"pode": False, "motivo": "É necessário possuir uma picareta válida para minerar."}
            row = db.execute(
                "SELECT expira_em FROM rpg_cooldowns WHERE guild_id = ? AND user_id = ? AND chave = 'mining'",
                (self.guild_id, self.user_id),
            ).fetchone()
            if row and time.time() < row[0]:
                return {"pode": False, "motivo": "Cooldown ativo.", "restante": int(row[0] - time.time())}
            energia = db.execute(
                "SELECT valor FROM rpg_flags WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                (self.guild_id, self.user_id),
            ).fetchone()
            valor_energia = int(energia[0]) if energia else 100
            if valor_energia < MINING_ENERGIA_CUSTO:
                return {"pode": False, "motivo": f"Energia insuficiente ({valor_energia}/{MINING_ENERGIA_CUSTO})."}
            return {"pode": True, "picareta": pic, "regiao": chave_regiao}

    # ---------------- sorteio (puro, testável) ----------------
    @staticmethod
    def _pool_materiais(tier: int, regiao_key: str) -> list[tuple[str, dict]]:
        regiao = REGIOES.get(regiao_key, REGIOES["dakor"])
        pool = []
        for key in regiao["materiais"]:
            meta = MATERIAIS_MINERAIS.get(key)
            if meta and meta["tier"] <= tier:
                pool.append((key, meta))
        if not pool:
            for key, meta in MATERIAIS_MINERAIS.items():
                if meta["tier"] <= tier:
                    pool.append((key, meta))
        return pool

    @classmethod
    def sortear_materiais(cls, tier: int, regiao_key: str, bonus_qtd: float,
                          rng=None, bonus_raro: float = 0.0) -> dict[str, int]:
        rng = rng or random
        regiao = REGIOES.get(regiao_key, REGIOES["dakor"])
        pool = cls._pool_materiais(tier, regiao_key)
        if not pool:
            return {"pedra": 1}
        rolagens = 1 + (1 if tier >= 4 else 0) + (1 if tier >= 7 else 0) + (1 if tier >= 10 else 0)
        itens: dict[str, int] = {}
        for _ in range(rolagens):
            total = sum(meta["peso"] for _, meta in pool)
            escolha = rng.uniform(0, total)
            acumulado = 0.0
            selecionado = pool[-1]
            for key, meta in pool:
                acumulado += meta["peso"]
                if escolha <= acumulado:
                    selecionado = (key, meta)
                    break
            key, meta = selecionado
            qtd = rng.randint(*meta["qtd"])
            qtd = qtd * 1.0 * regiao.get("qtd_mult", 1.0) * (1 + bonus_qtd)
            qtd = max(1, int(round(qtd)))
            qtd = min(qtd, 25)
            itens[key] = itens.get(key, 0) + qtd

        # Benefício de nível 10 do Minerador: chance extra de um material
        # raro (tier >= 4) disponível na região e na picareta atual.
        if bonus_raro > 0 and rng.random() < bonus_raro:
            raros = [(k, m) for k, m in pool if m["tier"] >= 4]
            if raros:
                total = sum(meta["peso"] for _, meta in raros)
                escolha = rng.uniform(0, total)
                acumulado = 0.0
                selecionado = raros[-1]
                for key, meta in raros:
                    acumulado += meta["peso"]
                    if escolha <= acumulado:
                        selecionado = (key, meta)
                        break
                key = selecionado[0]
                itens[key] = itens.get(key, 0) + 1
        return itens

    @staticmethod
    def calcular_coins(tier: int, regiao_key: str, bonus_coins: float, nivel_personagem: int, rng=None) -> int:
        rng = rng or random
        regiao = REGIOES.get(regiao_key, REGIOES["dakor"])
        base_min = 1 + tier // 2
        base_max = 3 + tier * 2
        mult = regiao.get("coins_mult", 1.0) * (1 + bonus_coins) * (1 + min(50, max(0, nivel_personagem)) * 0.005)
        cmin = max(1, int(round(base_min * mult)))
        cmax = max(cmin, int(round(base_max * mult)))
        return max(1, min(60, rng.randint(cmin, cmax)))

    @staticmethod
    def chance_da_picareta(tier: int) -> float:
        return CHANCES_COINS.get(tier, 0.0)

    # ---------------- ação ----------------
    def minerar(self, regiao: str | None = None, rng=None) -> dict[str, Any]:
        rng = rng or random
        try:
            with self.db.transacao() as db:
                char = db.execute(
                    "SELECT nivel, xp, regiao FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchone()
                if not char:
                    return {"sucesso": False, "motivo": "Crie seu personagem com /rpg primeiro."}
                nivel_personagem = int(char[0])

                chave_regiao = self.obter_regiao_tx(db, regiao)
                ok, motivo = self._regiao_liberada_tx(db, chave_regiao, nivel_personagem)
                if not ok:
                    return {"sucesso": False, "motivo": motivo}
                regiao_info = REGIOES[chave_regiao]
                indice_regiao = list(REGIOES).index(chave_regiao)

                picareta_key = self._picareta_tx(db)
                if not picareta_key:
                    return {"sucesso": False, "motivo": "É necessário possuir uma picareta válida para minerar."}
                picareta = obter_picareta(picareta_key)
                if not picareta:
                    return {"sucesso": False, "motivo": "Picareta inválida."}
                tier = picareta.nivel
                nivel_req = int(picareta.requisitos.get("nivel_personagem", 1) or 1)
                if nivel_personagem < nivel_req:
                    return {"sucesso": False, "motivo": f"A {picareta.nome} requer nível de personagem {nivel_req}."}

                # Cooldown dentro da transação evita recompensa duplicada em
                # chamadas simultâneas.
                cd = db.execute(
                    "SELECT expira_em FROM rpg_cooldowns WHERE guild_id = ? AND user_id = ? AND chave = 'mining'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                if cd and time.time() < cd[0]:
                    return {"sucesso": False, "motivo": "Cooldown ativo.", "restante": int(cd[0] - time.time())}

                energia_row = db.execute(
                    "SELECT valor FROM rpg_flags WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                energia = int(energia_row[0]) if energia_row else 100
                if energia < MINING_ENERGIA_CUSTO:
                    return {"sucesso": False, "motivo": f"Energia insuficiente ({energia}/{MINING_ENERGIA_CUSTO})."}

                prof = db.execute(
                    "SELECT nivel, xp FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = 'minerador'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                nivel_minerador = int(prof[0]) if prof else 0
                bonus_qtd = min(0.30, 0.03 * max(0, nivel_minerador - 1))
                bonus_coins = min(0.25, 0.05 * max(0, nivel_minerador - 4))
                bonus_raro = min(0.25, 0.10 * max(0, nivel_minerador - 9))

                itens = self.sortear_materiais(
                    tier, chave_regiao, bonus_qtd, rng, bonus_raro
                )
                for key in itens:
                    itens[key] = max(1, int(round(itens[key] * picareta.multiplicador_materiais)))
                total_materiais = sum(itens.values())

                coins = 0
                achou_coins = rng.random() < picareta.chance_coins
                if achou_coins:
                    coins = self.calcular_coins(tier, chave_regiao, bonus_coins, nivel_personagem, rng)

                # Consome energia e grava cooldown/estado.
                if energia_row:
                    db.execute(
                        "UPDATE rpg_flags SET valor = valor - ?, atualizado_em = ? "
                        "WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                        (MINING_ENERGIA_CUSTO, time.time(), self.guild_id, self.user_id),
                    )
                else:
                    db.execute(
                        "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                        "VALUES (?, ?, 'energia', ?, ?)",
                        (self.guild_id, self.user_id, 100 - MINING_ENERGIA_CUSTO, time.time()),
                    )
                agora = time.time()
                db.execute(
                    "INSERT INTO rpg_cooldowns (guild_id, user_id, chave, expira_em) VALUES (?, ?, 'mining', ?) "
                    "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET expira_em = excluded.expira_em",
                    (self.guild_id, self.user_id, agora + MINING_COOLDOWN_SEGUNDOS),
                )
                for key, qtd in itens.items():
                    self.inventory.adicionar_tx(db, key, qtd)
                if coins > 0:
                    alterar_saldo_tx(db, self.guild_id, self.user_id, coins)

                # XP de personagem.
                xp_char = adicionar_xp_tx(db, self.guild_id, self.user_id, 5 + tier + indice_regiao * 2)

                # XP profissional apenas para quem aprendeu Minerador.
                progresso = None
                if prof:
                    from .professions_v2 import ProfessionsV2
                    progresso = ProfessionsV2(self.guild_id, self.user_id)._aplicar_xp_tx(
                        db, "minerador", 8 + tier * 2 + indice_regiao * 3
                    )
                    db.execute(
                        "INSERT INTO rpg_profissoes_log (guild_id, user_id, chave, atividade, xp, nivel, criado_em) "
                        "VALUES (?, ?, 'minerador', 'minerar', ?, ?, ?)",
                        (self.guild_id, self.user_id, 8 + tier * 2 + indice_regiao * 3,
                         progresso["nivel"] if progresso else nivel_minerador, agora),
                    )

                # Estatísticas e histórico.
                db.execute("""
                    INSERT INTO rpg_mineracao_stats
                        (guild_id, user_id, total_mineracoes, total_materiais, coins_total, maior_tier, atualizado_em)
                    VALUES (?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                        total_mineracoes = rpg_mineracao_stats.total_mineracoes + 1,
                        total_materiais = rpg_mineracao_stats.total_materiais + excluded.total_materiais,
                        coins_total = rpg_mineracao_stats.coins_total + excluded.coins_total,
                        maior_tier = MAX(rpg_mineracao_stats.maior_tier, excluded.maior_tier),
                        atualizado_em = excluded.atualizado_em
                """, (self.guild_id, self.user_id, total_materiais, coins, tier, agora))

                detalhe = f"picareta:{picareta_key}|tier:{tier}|regiao:{chave_regiao}|coins:{coins}|itens:{','.join(f'{k}x{v}' for k, v in itens.items())}"
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'minerar', ?, ?)",
                    (self.guild_id, self.user_id, detalhe, agora),
                )
                raros = [k for k in itens if MATERIAIS_MINERAIS.get(k, {}).get("tier", 1) >= 4]
                if raros:
                    db.execute(
                        "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                        "VALUES (?, ?, 'minerar_raro', ?, ?)",
                        (self.guild_id, self.user_id, ",".join(raros), agora),
                    )

                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)
                origem = "equipada"
                eq = db.execute(
                    "SELECT item_key FROM rpg_equipamentos WHERE guild_id = ? AND user_id = ? AND slot = 'picareta'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                if not eq or eq[0] != picareta_key:
                    origem = "inventário (melhor possuída)"

            return {
                "sucesso": True,
                "picareta": picareta_key,
                "picareta_nome": picareta.nome,
                "picareta_nivel": tier,
                "origem_picareta": origem,
                "chance_coins": picareta.chance_coins,
                "regiao": chave_regiao,
                "regiao_nome": regiao_info["nome"],
                "itens": itens,
                "materiais": [{"key": k, "nome": nome_item(k), "qtd": v} for k, v in itens.items()],
                "total_materiais": total_materiais,
                "coins": coins,
                "achou_coins": achou_coins,
                "saldo": saldo,
                "xp_personagem": xp_char,
                "xp_profissao": (8 + tier * 2 + indice_regiao * 3) if prof else 0,
                "profissao_nivel": progresso["nivel"] if progresso else None,
                "profissao_xp": progresso["xp"] if progresso else None,
                "profissao_xp_necessario": progresso["xp_necessario"] if progresso else None,
                "subiu_profissao": progresso["subiu_nivel"] if progresso else False,
                "beneficios_desbloqueados": progresso.get("beneficios_desbloqueados", []) if progresso else [],
                "raros": raros,
                "cooldown": MINING_COOLDOWN_SEGUNDOS,
                "durabilidade": None,
            }
        except (sqlite3.Error, ValueError) as exc:
            return {"sucesso": False, "motivo": f"Mineração cancelada: {exc}"}
