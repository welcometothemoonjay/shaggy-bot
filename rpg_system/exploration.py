"""Exploração do RPG Textual.

A exploração tem continuidade: o jogador possui uma região e um local atuais.
As recompensas são calculadas em Python e gravadas atomicamente. A descrição
narrativa pode vir do OpenRouter, mas a IA nunca altera itens, moedas, XP ou
eventos: ela recebe contexto e devolve apenas texto.
"""
from __future__ import annotations

import random
import sqlite3
import time
from datetime import datetime
from typing import Any

from .ai.narrative import NarrativeAI
from .constants import (
    EXPLORATION_COOLDOWN_SEGUNDOS,
    EXPLORATION_ENERGIA_CUSTO,
    FUSO_HORARIO,
)
from .database import get_db
from .economy import obter_saldo_tx, alterar_saldo_tx
from .inventory import Inventario
from .items import nome_item
from .progression import adicionar_xp_tx
from .schema import garantir_tabelas
from .world import (
    REGIOES, LOCAIS, EVENTOS, obter_local, obter_regiao,
    locais_da_regiao, regioes_disponiveis,
)


def periodo_do_dia() -> str:
    hora = datetime.now(FUSO_HORARIO).hour
    if 5 <= hora < 12:
        return "manhã"
    if 12 <= hora < 18:
        return "tarde"
    if 18 <= hora < 23:
        return "noite"
    return "madrugada"


class Exploration:
    def __init__(self, bot, guild_id: int, user_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.inventory = Inventario(guild_id, user_id)
        self.ai = NarrativeAI()
        garantir_tabelas()

    # ---------------- localização ----------------
    def _char_tx(self, db):
        return db.execute(
            "SELECT nivel, xp, regiao FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()

    def obter_local_atual(self) -> str:
        with self.db.transacao() as db:
            row = db.execute(
                "SELECT local_key FROM rpg_localizacao WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchone()
            if row and row[0] in LOCAIS:
                return row[0]
            char = self._char_tx(db)
            regiao = char[2] if char and char[2] in REGIOES else "dakor"
            return REGIOES[regiao]["locais"][0]

    def obter_regiao_atual(self) -> str:
        local = obter_local(self.obter_local_atual())
        return local["regiao"] if local else "dakor"

    def definir_local(self, local_key: str) -> bool:
        local = obter_local(local_key)
        if not local:
            return False
        with self.db.transacao() as db:
            agora = time.time()
            db.execute(
                "INSERT INTO rpg_localizacao (guild_id, user_id, local_key, atualizado_em) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET local_key = excluded.local_key, atualizado_em = excluded.atualizado_em",
                (self.guild_id, self.user_id, local_key, agora),
            )
            db.execute(
                "INSERT OR IGNORE INTO rpg_descobertas (guild_id, user_id, local_key, descoberta_em) "
                "VALUES (?, ?, ?, ?)",
                (self.guild_id, self.user_id, local_key, agora),
            )
            db.execute(
                "INSERT OR IGNORE INTO rpg_regioes (guild_id, user_id, regiao, descoberta_em) "
                "VALUES (?, ?, ?, ?)",
                (self.guild_id, self.user_id, local["regiao"], agora),
            )
            db.execute(
                "UPDATE rpg_personagem SET regiao = ?, atualizado_em = ? WHERE guild_id = ? AND user_id = ?",
                (local["regiao"], agora, self.guild_id, self.user_id),
            )
        return True

    def descobertas(self) -> list[str]:
        with self.db.transacao() as db:
            rows = db.execute(
                "SELECT local_key FROM rpg_descobertas WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchall()
            return [r[0] for r in rows]

    def regioes_visitadas(self) -> list[str]:
        with self.db.transacao() as db:
            rows = db.execute(
                "SELECT regiao FROM rpg_regioes WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchall()
            return [r[0] for r in rows]

    def locais_da_regiao(self, regiao: str) -> list[dict]:
        return locais_da_regiao(regiao)

    def info_local(self, local_key: str | None = None) -> dict | None:
        return obter_local(local_key or self.obter_local_atual())

    def regioes_disponiveis(self) -> list[dict]:
        with self.db.transacao() as db:
            char = self._char_tx(db)
            return regioes_disponiveis(int(char[0]) if char else 1)

    # ---------------- exploração ----------------
    def _evento_aleatorio(self, regiao_key: str, rng) -> dict | None:
        eventos = EVENTOS.get(regiao_key, [])
        if not eventos or rng.random() > 0.38:
            return None
        return rng.choice(eventos)

    async def explorar(self, regiao: str | None = None, rng=None) -> dict[str, Any]:
        rng = rng or random
        try:
            with self.db.transacao() as db:
                char = self._char_tx(db)
                if not char:
                    return {"sucesso": False, "motivo": "Crie seu personagem com /rpg primeiro."}
                nivel = int(char[0])

                regiao_atual = self._regiao_atual_tx(db)
                chave_regiao = regiao if regiao in REGIOES else regiao_atual
                regiao_info = REGIOES.get(chave_regiao)
                if not regiao_info:
                    return {"sucesso": False, "motivo": "Região desconhecida."}
                if nivel < regiao_info["nivel_min"]:
                    return {
                        "sucesso": False,
                        "motivo": f"A região {regiao_info['nome']} requer nível {regiao_info['nivel_min']}.",
                    }

                # Cooldown e energia são verificados e consumidos na mesma transação.
                cd = db.execute(
                    "SELECT expira_em FROM rpg_cooldowns WHERE guild_id = ? AND user_id = ? AND chave = 'explorar'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                if cd and time.time() < cd[0]:
                    return {"sucesso": False, "motivo": "Cooldown ativo.", "restante": int(cd[0] - time.time())}

                energia_row = db.execute(
                    "SELECT valor FROM rpg_flags WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                energia = int(energia_row[0]) if energia_row else 100
                if energia < EXPLORATION_ENERGIA_CUSTO:
                    return {
                        "sucesso": False,
                        "motivo": f"Energia insuficiente ({energia}/{EXPLORATION_ENERGIA_CUSTO}).",
                    }

                local_atual = db.execute(
                    "SELECT local_key FROM rpg_localizacao WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchone()
                local_key_atual = local_atual[0] if local_atual and local_atual[0] in LOCAIS else None
                locais_regiao = regiao_info["locais"]

                # Continuidade: na maior parte das vezes o jogador permanece no
                # local atual; às vezes descobre outro local da mesma região.
                if local_key_atual and obter_local(local_key_atual)["regiao"] == chave_regiao and rng.random() < 0.62:
                    local_key = local_key_atual
                else:
                    local_key = rng.choice(locais_regiao)
                local = LOCAIS[local_key]
                indice_regiao = list(REGIOES).index(chave_regiao)

                nova_regiao = not db.execute(
                    "SELECT 1 FROM rpg_regioes WHERE guild_id = ? AND user_id = ? AND regiao = ?",
                    (self.guild_id, self.user_id, chave_regiao),
                ).fetchone()
                descoberta_nova = not db.execute(
                    "SELECT 1 FROM rpg_descobertas WHERE guild_id = ? AND user_id = ? AND local_key = ?",
                    (self.guild_id, self.user_id, local_key),
                ).fetchone()

                evento = self._evento_aleatorio(chave_regiao, rng)

                prof = db.execute(
                    "SELECT nivel FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = 'explorador'",
                    (self.guild_id, self.user_id),
                ).fetchone()
                nivel_explorador = int(prof[0]) if prof else 0
                bonus_xp = min(0.30, 0.05 * max(0, nivel_explorador - 1))
                bonus_coins = min(0.20, 0.05 * max(0, nivel_explorador - 4))

                xp_base = 10 + indice_regiao * 4 + rng.randint(0, 8)
                if descoberta_nova:
                    xp_base += 10
                if nova_regiao:
                    xp_base += 15
                if evento:
                    xp_base += int(evento.get("xp", 0))
                xp_ganho = max(1, int(round(xp_base * (1 + bonus_xp))))

                coins = 0
                if rng.random() < 0.55:
                    coins = rng.randint(0, 2 + indice_regiao * 2)
                if evento:
                    coins += int(evento.get("moedas", 0) or 0)
                if descoberta_nova:
                    coins += 2
                coins = max(0, min(40, int(round(coins * (1 + bonus_coins)))))

                item_ganho = None
                if evento and evento.get("item"):
                    item_ganho = evento["item"]
                elif rng.random() < 0.32:
                    item_ganho = rng.choice(local.get("coletas", []))
                qtd_item = 1
                if item_ganho and rng.random() < 0.12 + min(0.25, 0.02 * nivel_explorador):
                    qtd_item = 2

                # ---- gravação atômica ----
                if energia_row:
                    db.execute(
                        "UPDATE rpg_flags SET valor = valor - ?, atualizado_em = ? "
                        "WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                        (EXPLORATION_ENERGIA_CUSTO, time.time(), self.guild_id, self.user_id),
                    )
                else:
                    db.execute(
                        "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                        "VALUES (?, ?, 'energia', ?, ?)",
                        (self.guild_id, self.user_id, 100 - EXPLORATION_ENERGIA_CUSTO, time.time()),
                    )
                agora = time.time()
                db.execute(
                    "INSERT INTO rpg_cooldowns (guild_id, user_id, chave, expira_em) VALUES (?, ?, 'explorar', ?) "
                    "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET expira_em = excluded.expira_em",
                    (self.guild_id, self.user_id, agora + EXPLORATION_COOLDOWN_SEGUNDOS),
                )
                db.execute(
                    "INSERT INTO rpg_localizacao (guild_id, user_id, local_key, atualizado_em) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(guild_id, user_id) DO UPDATE SET local_key = excluded.local_key, atualizado_em = excluded.atualizado_em",
                    (self.guild_id, self.user_id, local_key, agora),
                )
                db.execute(
                    "INSERT OR IGNORE INTO rpg_descobertas (guild_id, user_id, local_key, descoberta_em) "
                    "VALUES (?, ?, ?, ?)",
                    (self.guild_id, self.user_id, local_key, agora),
                )
                db.execute(
                    "INSERT OR IGNORE INTO rpg_regioes (guild_id, user_id, regiao, descoberta_em) "
                    "VALUES (?, ?, ?, ?)",
                    (self.guild_id, self.user_id, chave_regiao, agora),
                )
                db.execute(
                    "UPDATE rpg_personagem SET regiao = ?, atualizado_em = ? WHERE guild_id = ? AND user_id = ?",
                    (chave_regiao, agora, self.guild_id, self.user_id),
                )
                if coins > 0:
                    alterar_saldo_tx(db, self.guild_id, self.user_id, coins)
                if item_ganho:
                    self.inventory.adicionar_tx(db, item_ganho, qtd_item)
                xp_char = adicionar_xp_tx(db, self.guild_id, self.user_id, xp_ganho)

                progresso_prof = None
                if prof:
                    from .professions_v2 import ProfessionsV2
                    xp_prof = 8 + indice_regiao * 2
                    progresso_prof = ProfessionsV2(self.guild_id, self.user_id)._aplicar_xp_tx(
                        db, "explorador", xp_prof
                    )
                    db.execute(
                        "INSERT INTO rpg_profissoes_log (guild_id, user_id, chave, atividade, xp, nivel, criado_em) "
                        "VALUES (?, ?, 'explorador', 'explorar', ?, ?, ?)",
                        (self.guild_id, self.user_id, xp_prof,
                         progresso_prof["nivel"] if progresso_prof else nivel_explorador, agora),
                    )

                detalhe = f"{local_key}|regiao:{chave_regiao}|xp{xp_ganho}|coins{coins}|item:{item_ganho or '-'}|evento:{(evento or {}).get('key', '-')}"
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'explorar', ?, ?)",
                    (self.guild_id, self.user_id, detalhe, agora),
                )
                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)

            # Contexto para a IA (fora da transação, para não segurar o banco).
            contexto = {
                "local": local["nome"],
                "local_key": local_key,
                "regiao": regiao_info["nome"],
                "regiao_key": chave_regiao,
                "bioma": local["bioma"],
                "clima": local["clima"],
                "periodo": periodo_do_dia(),
                "caracteristicas": local.get("caracteristicas", []),
                "historia": local.get("historia", ""),
                "elementos_ambientais": local.get("elementos", []),
                "situacao_atual": "Explorando em busca de recursos e descobertas.",
                "eventos_ativos": [evento["texto"]] if evento else [],
                "personagem_nivel": nivel,
                "descoberta_nova": descoberta_nova,
            }
            narr = await self.ai.describe_location(contexto)
            descricao = narr.get("descricao") or local["descricao_base"]
            fonte = narr.get("fonte", "fallback")
            if evento:
                descricao = f"{descricao}\n\n{evento['texto']}"

            return {
                "sucesso": True,
                "local_key": local_key,
                "local": local["nome"],
                "regiao_key": chave_regiao,
                "regiao": regiao_info["nome"],
                "bioma": local["bioma"],
                "clima": local["clima"],
                "descricao": descricao,
                "fonte": fonte,
                "descoberta_nova": descoberta_nova,
                "nova_regiao": nova_regiao,
                "evento": evento,
                "xp": xp_ganho,
                "xp_personagem": xp_char,
                "moedas": coins,
                "saldo": saldo,
                "item": item_ganho,
                "item_nome": nome_item(item_ganho) if item_ganho else None,
                "item_qtd": qtd_item,
                "profissao_xp": (8 + indice_regiao * 2) if prof else 0,
                "profissao_nivel": progresso_prof["nivel"] if progresso_prof else None,
                "profissao_xp_atual": progresso_prof["xp"] if progresso_prof else None,
                "profissao_xp_necessario": progresso_prof["xp_necessario"] if progresso_prof else None,
                "subiu_profissao": progresso_prof["subiu_nivel"] if progresso_prof else False,
                "cooldown": EXPLORATION_COOLDOWN_SEGUNDOS,
                "proximos": self._proximos(local),
            }
        except (sqlite3.Error, ValueError) as exc:
            return {"sucesso": False, "motivo": f"Exploração cancelada: {exc}"}

    def _regiao_atual_tx(self, db) -> str:
        row = db.execute(
            "SELECT local_key FROM rpg_localizacao WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        if row:
            local = obter_local(row[0])
            if local:
                return local["regiao"]
        char = self._char_tx(db)
        if char and char[2] in REGIOES:
            return char[2]
        return "dakor"

    def _proximos(self, local: dict) -> list[str]:
        regiao = REGIOES[local["regiao"]]
        return [
            f"Minérios disponíveis: {', '.join(nome_item(m) for m in regiao['materiais'])}.",
            f"Coletas locais: {', '.join(nome_item(m) for m in local.get('coletas', []))}.",
            "Use /mineracao para extrair recursos da região atual.",
        ]
