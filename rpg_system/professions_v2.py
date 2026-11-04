"""Profissões do RPG Textual.

Cada profissão tem identidade, atividade, requisitos, progressão e
benefícios reais. O jogador pode aprender mais de uma profissão (regra
preservada do sistema original), mas cada uma evolui separadamente.
"""
from __future__ import annotations

import random
import sqlite3
import time
from typing import Any

from .constants import PROFISSOES_DISPONIVEIS
from .database import get_db
from .economy import obter_saldo_tx, alterar_saldo_tx
from .inventory import Inventario
from .progression import adicionar_xp_tx
from .schema import garantir_tabelas

XP_POR_NIVEL_BASE = 60


def xp_necessario(nivel: int) -> int:
    return XP_POR_NIVEL_BASE * max(1, int(nivel))


PROFISSOES: dict[str, dict[str, Any]] = {
    "minerador": {
        "key": "minerador", "nome": "Minerador", "emoji": "⛏️",
        "descricao": "Especialista em extrair minérios. Depende de picaretas e das regiões exploradas.",
        "atividades": ["Minerar com picareta", "Prospecção de veios"],
        "tipo_ganho": "Materiais minerais, Abysmus e XP profissional",
        "requisitos": {"nivel_personagem": 1},
        "cooldown": 300,
        "xp_atividade": 12,
        "beneficios": [
            {"nivel": 2, "nome": "Veios abundantes", "descricao": "+3% de materiais por mineração."},
            {"nivel": 5, "nome": "Faro para moedas", "descricao": "+5% de Abysmus encontrados ao minerar."},
            {"nivel": 10, "nome": "Mestre das profundezas", "descricao": "+10% de chance de materiais raros."},
        ],
        "itens": [{"key": "pedra", "chance": 0.65, "qtd": (1, 2)}, {"key": "carvao", "chance": 0.35, "qtd": (1, 2)}],
        "coins": (0, 2),
    },
    "lenhador": {
        "key": "lenhador", "nome": "Lenhador", "emoji": "🪓",
        "descricao": "Coleta madeira e recursos naturais. Um machado melhora o rendimento.",
        "atividades": ["Cortar madeira", "Coletar recursos da floresta"],
        "tipo_ganho": "Madeira, ervas e XP profissional",
        "requisitos": {"nivel_personagem": 1},
        "cooldown": 300,
        "xp_atividade": 12,
        "beneficios": [
            {"nivel": 2, "nome": "Corte firme", "descricao": "+3% de madeira por coleta."},
            {"nivel": 5, "nome": "Conhecedor da mata", "descricao": "+12% de madeira e +8% de chance de item extra."},
            {"nivel": 10, "nome": "Guardião da floresta", "descricao": "+27% de madeira e +18% de chance de item extra."},
        ],
        "itens": [{"key": "madeira", "chance": 0.80, "qtd": (1, 3)}, {"key": "erva", "chance": 0.20, "qtd": (1, 1)}],
        "coins": (0, 0),
    },
    "cacador": {
        "key": "cacador", "nome": "Caçador", "emoji": "🏹",
        "descricao": "Obtém couro, carne e componentes em atividades de caça e rastreamento.",
        "atividades": ["Rastrear presas", "Coletar componentes"],
        "tipo_ganho": "Couro, carne, penas e XP profissional",
        "requisitos": {"nivel_personagem": 1},
        "cooldown": 300,
        "xp_atividade": 14,
        "beneficios": [
            {"nivel": 2, "nome": "Rastreador", "descricao": "+3% de materiais de caça e +2% de chance de item extra."},
            {"nivel": 5, "nome": "Caçador experiente", "descricao": "+12% de materiais de caça e +8% de chance de item extra."},
            {"nivel": 10, "nome": "Predador do horizonte", "descricao": "+27% de materiais de caça e +18% de chance de item extra."},
        ],
        "itens": [
            {"key": "couro", "chance": 0.55, "qtd": (1, 2)},
            {"key": "carne", "chance": 0.40, "qtd": (1, 2)},
            {"key": "pena", "chance": 0.10, "qtd": (1, 1)},
        ],
        "coins": (0, 0),
    },
    "mercador": {
        "key": "mercador", "nome": "Mercador", "emoji": "🪙",
        "descricao": "Negocia com o mercador e recebe vantagens comerciais progressivas.",
        "atividades": ["Negociar comissões", "Comprar e vender com desconto"],
        "tipo_ganho": "Descontos, bônus de venda e comissões limitadas",
        "requisitos": {"nivel_personagem": 2},
        "cooldown": 300,
        "xp_atividade": 12,
        "beneficios": [
            {"nivel": 2, "nome": "Bom papo", "descricao": "2% de desconto nas compras."},
            {"nivel": 5, "nome": "Negociante", "descricao": "5% de desconto e +5% na venda."},
            {"nivel": 10, "nome": "Mestre do comércio", "descricao": "10% de desconto e +10% na venda."},
        ],
        "itens": [],
        "coins": (3, 8),
    },
    "artesao": {
        "key": "artesao", "nome": "Artesão", "emoji": "🧰",
        "descricao": "Transforma madeira e pedra em artesanato vendável. Possui receita real e consome materiais.",
        "atividades": ["Produzir artesanato"],
        "tipo_ganho": "Itens fabricados e XP profissional",
        "requisitos": {"nivel_personagem": 2},
        "cooldown": 300,
        "xp_atividade": 16,
        "beneficios": [
            {"nivel": 2, "nome": "Mãos firmes", "descricao": "10% de chance de produzir 1 artesanato extra."},
            {"nivel": 5, "nome": "Acabamento fino", "descricao": "25% de chance de produção extra."},
            {"nivel": 10, "nome": "Oficina completa", "descricao": "50% de chance de produção extra."},
        ],
        "itens": [],
        "coins": (0, 0),
        "receita": {"produto": "artesanato", "qtd": 1, "ingredientes": {"madeira": 2, "pedra": 1}},
    },
    "pescador": {
        "key": "pescador", "nome": "Pescador", "emoji": "🎣",
        "descricao": "Pesca peixes e recolhe conchas na Costa de Âmbar ou em qualquer região com água.",
        "atividades": ["Pescar", "Recolher conchas"],
        "tipo_ganho": "Peixes, conchas e XP profissional",
        "requisitos": {"nivel_personagem": 1},
        "cooldown": 300,
        "xp_atividade": 11,
        "beneficios": [
            {"nivel": 2, "nome": "Isca melhor", "descricao": "+3% de materiais aquáticos e +2% de chance de item extra."},
            {"nivel": 5, "nome": "Paciência de pescador", "descricao": "+12% de materiais aquáticos e +8% de chance de item extra."},
            {"nivel": 10, "nome": "Senhor das marés", "descricao": "+27% de materiais aquáticos e +18% de chance de item extra."},
        ],
        "itens": [{"key": "peixe", "chance": 0.75, "qtd": (1, 2)}, {"key": "concha", "chance": 0.25, "qtd": (1, 1)}],
        "coins": (0, 0),
    },
    "ferreiro": {
        "key": "ferreiro", "nome": "Ferreiro", "emoji": "🔨",
        "descricao": "Refina minério de ferro em lingotes. Possui receita real e consome carvão.",
        "atividades": ["Forjar lingotes de ferro"],
        "tipo_ganho": "Lingotes de ferro e XP profissional",
        "requisitos": {"nivel_personagem": 3},
        "cooldown": 300,
        "xp_atividade": 16,
        "beneficios": [
            {"nivel": 2, "nome": "Forja aquecida", "descricao": "10% de chance de produzir 1 lingote extra."},
            {"nivel": 5, "nome": "Martelo preciso", "descricao": "25% de chance de produção extra."},
            {"nivel": 10, "nome": "Mestre ferreiro", "descricao": "50% de chance de produção extra."},
        ],
        "itens": [],
        "coins": (0, 0),
        "receita": {"produto": "lingote_ferro", "qtd": 1, "ingredientes": {"ferro": 2, "carvao": 1}},
    },
    "herbalista": {
        "key": "herbalista", "nome": "Herbalista", "emoji": "🌿",
        "descricao": "Coleta ervas e cogumelos em florestas e vales, abastecendo o mercado.",
        "atividades": ["Colher ervas", "Encontrar cogumelos"],
        "tipo_ganho": "Ervas, cogumelos e XP profissional",
        "requisitos": {"nivel_personagem": 1},
        "cooldown": 300,
        "xp_atividade": 12,
        "beneficios": [
            {"nivel": 2, "nome": "Olhar atento", "descricao": "+3% de materiais de coleta e +2% de chance de item extra."},
            {"nivel": 5, "nome": "Herbário vivo", "descricao": "+12% de materiais de coleta e +8% de chance de item extra."},
            {"nivel": 10, "nome": "Mestre herbalista", "descricao": "+27% de materiais de coleta e +18% de chance de item extra."},
        ],
        "itens": [{"key": "erva", "chance": 0.65, "qtd": (1, 2)}, {"key": "cogumelo", "chance": 0.35, "qtd": (1, 1)}],
        "coins": (0, 0),
    },
    "explorador": {
        "key": "explorador", "nome": "Explorador", "emoji": "🗺️",
        "descricao": "Descobre locais, regiões e recursos. Aprofunda o conhecimento do mundo.",
        "atividades": ["Explorar regiões", "Reconhecer trilhas"],
        "tipo_ganho": "XP, descobertas e Abysmus",
        "requisitos": {"nivel_personagem": 1},
        "cooldown": 300,
        "xp_atividade": 10,
        "beneficios": [
            {"nivel": 2, "nome": "Bússola interna", "descricao": "+5% de XP em exploração."},
            {"nivel": 5, "nome": "Cartógrafo", "descricao": "+20% de XP e +5% de Abysmus em exploração."},
            {"nivel": 10, "nome": "Olhar do horizonte", "descricao": "+30% de XP e +20% de Abysmus em exploração."},
        ],
        "itens": [],
        "coins": (2, 6),
    },
}

# Aliases aceitos em comandos por nome.
ALIASES = {
    "mineracao": "minerador", "minerar": "minerador", "mineiro": "minerador",
    "lenhador": "lenhador", "lenhar": "lenhador", "madeireiro": "lenhador",
    "cacador": "cacador", "caçador": "cacador", "caca": "cacador",
    "mercador": "mercador", "comerciante": "mercador",
    "artesao": "artesao", "artesão": "artesao", "artifice": "artesao",
    "pescador": "pescador", "pesca": "pescador",
    "ferreiro": "ferreiro", "forja": "ferreiro",
    "herbalista": "herbalista", "ervas": "herbalista",
    "explorador": "explorador", "exploracao": "explorador",
}

# Compatibilidade com código anterior.
PROFISSOES_INFO = {k: {"nome": v["nome"], "desc": v["descricao"], "atividade": v["atividades"][0]} for k, v in PROFISSOES.items()}


class ProfessionsV2:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.inventory = Inventario(guild_id, user_id)
        garantir_tabelas()

    # ---------------- consultas ----------------
    def resolver(self, chave_ou_nome: str) -> str | None:
        from .market_v2 import normalizar

        alvo = normalizar(chave_ou_nome)
        if alvo in PROFISSOES:
            return alvo
        if alvo in ALIASES:
            return ALIASES[alvo]
        for key, info in PROFISSOES.items():
            if normalizar(info["nome"]) == alvo or alvo in normalizar(info["nome"]):
                return key
        return None

    def _char_tx(self, db):
        return db.execute(
            "SELECT nivel, xp FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()

    def _aprendidas_tx(self, db) -> list[dict[str, Any]]:
        cols = [d[0] for d in db.execute("PRAGMA table_info(rpg_profissoes)").fetchall()]
        rows = db.execute(
            "SELECT * FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? ORDER BY chave",
            (self.guild_id, self.user_id),
        ).fetchall()
        return [dict(zip(cols, row)) for row in rows]

    def obter_todas(self) -> list[dict[str, Any]]:
        with self.db.transacao() as db:
            aprendidas = self._aprendidas_tx(db)
        res = []
        for prof in aprendidas:
            info = PROFISSOES.get(prof["chave"])
            if not info:
                continue
            nivel = int(prof["nivel"])
            xp = int(prof["xp"])
            req = xp_necessario(nivel)
            item = dict(prof)
            item.update({
                "info": info,
                "nome": info["nome"],
                "xp_necessario": req,
                "xp_faltante": max(0, req - xp),
                "beneficios_ativos": [b for b in info["beneficios"] if b["nivel"] <= nivel],
                "proximos_beneficios": [b for b in info["beneficios"] if b["nivel"] > nivel],
            })
            res.append(item)
        return res

    def obter(self, chave: str) -> dict[str, Any] | None:
        chave = self.resolver(chave) or chave
        with self.db.transacao() as db:
            row = db.execute(
                "SELECT * FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (self.guild_id, self.user_id, chave),
            ).fetchone()
            if not row:
                return None
            prof = dict(row)
        info = PROFISSOES.get(chave)
        if not info:
            return None
        nivel = int(prof["nivel"])
        xp = int(prof["xp"])
        req = xp_necessario(nivel)
        prof.update({
            "info": info, "nome": info["nome"], "xp_necessario": req,
            "xp_faltante": max(0, req - xp),
            "beneficios_ativos": [b for b in info["beneficios"] if b["nivel"] <= nivel],
            "proximos_beneficios": [b for b in info["beneficios"] if b["nivel"] > nivel],
        })
        return prof

    def nivel(self, chave: str) -> int:
        prof = self.obter(chave)
        return int(prof["nivel"]) if prof else 0

    def catalogo(self) -> list[dict[str, Any]]:
        with self.db.transacao() as db:
            char = self._char_tx(db)
            nivel_personagem = int(char[0]) if char else 1
            aprendidas = {p["chave"]: p for p in self._aprendidas_tx(db)}
        res = []
        for key, info in PROFISSOES.items():
            aprendida = aprendidas.get(key)
            requisito = int(info.get("requisitos", {}).get("nivel_personagem", 1) or 1)
            if aprendida:
                estado = "adquirida"
                motivo = ""
            elif nivel_personagem < requisito:
                estado = "bloqueada"
                motivo = f"Requer nível de personagem {requisito}."
            else:
                estado = "disponivel"
                motivo = ""
            nivel = int(aprendida["nivel"]) if aprendida else 0
            xp = int(aprendida["xp"]) if aprendida else 0
            res.append({
                "key": key,
                **info,
                "estado": estado,
                "motivo": motivo,
                "nivel_jogador": nivel,
                "xp_jogador": xp,
                "xp_necessario": xp_necessario(nivel or 1),
                "xp_faltante": max(0, xp_necessario(nivel or 1) - xp),
                "beneficios_ativos": [b for b in info["beneficios"] if aprendida and b["nivel"] <= nivel],
                "proximos_beneficios": [b for b in info["beneficios"] if not aprendida or b["nivel"] > nivel],
            })
        return res

    def detalhar(self, chave_ou_nome: str) -> dict[str, Any] | None:
        key = self.resolver(chave_ou_nome)
        if not key:
            return None
        for item in self.catalogo():
            if item["key"] == key:
                return item
        return None

    # ---------------- aprender ----------------
    def aprender(self, chave_ou_nome: str) -> dict[str, Any]:
        chave = self.resolver(chave_ou_nome)
        if not chave:
            return {"sucesso": False, "motivo": "Profissão não encontrada no catálogo.", "disponiveis": list(PROFISSOES)}
        info = PROFISSOES[chave]
        with self.db.transacao() as db:
            char = self._char_tx(db)
            if not char:
                return {"sucesso": False, "motivo": "Crie seu personagem com /rpg primeiro."}
            existente = db.execute(
                "SELECT nivel FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (self.guild_id, self.user_id, chave),
            ).fetchone()
            if existente:
                return {"sucesso": False, "motivo": f"Você já aprendeu {info['nome']} (nível {existente[0]})."}
            requisito = int(info.get("requisitos", {}).get("nivel_personagem", 1) or 1)
            if int(char[0]) < requisito:
                return {"sucesso": False, "motivo": f"Requer nível de personagem {requisito} (atual: {char[0]})."}
            agora = time.time()
            db.execute(
                "INSERT INTO rpg_profissoes (guild_id, user_id, chave, nivel, xp, atualizado_em) "
                "VALUES (?, ?, ?, 1, 0, ?)",
                (self.guild_id, self.user_id, chave, agora),
            )
            db.execute(
                "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                "VALUES (?, ?, 'aprender_profissao', ?, ?)",
                (self.guild_id, self.user_id, chave, agora),
            )
            db.execute(
                "INSERT INTO rpg_profissoes_log (guild_id, user_id, chave, atividade, xp, nivel, criado_em) "
                "VALUES (?, ?, ?, 'aprender', 0, 1, ?)",
                (self.guild_id, self.user_id, chave, agora),
            )
        return {"sucesso": True, "chave": chave, "nome": info["nome"], "nivel": 1, "info": info}

    # ---------------- progressão ----------------
    def _aplicar_xp_tx(self, db, chave: str, xp_ganho: int) -> dict[str, Any]:
        row = db.execute(
            "SELECT nivel, xp FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = ?",
            (self.guild_id, self.user_id, chave),
        ).fetchone()
        if not row:
            return {"sucesso": False}
        nivel = int(row[0])
        xp = int(row[1]) + int(xp_ganho)
        nivel_antes = nivel
        subiu = []
        while xp >= xp_necessario(nivel):
            xp -= xp_necessario(nivel)
            nivel += 1
            info = PROFISSOES.get(chave, {})
            for b in info.get("beneficios", []):
                if b["nivel"] == nivel:
                    subiu.append(b)
        db.execute(
            "UPDATE rpg_profissoes SET nivel = ?, xp = ?, atualizado_em = ? "
            "WHERE guild_id = ? AND user_id = ? AND chave = ?",
            (nivel, xp, time.time(), self.guild_id, self.user_id, chave),
        )
        return {
            "nivel": nivel,
            "nivel_antes": nivel_antes,
            "subiu_nivel": nivel > nivel_antes,
            "xp": xp,
            "xp_necessario": xp_necessario(nivel),
            "beneficios_desbloqueados": subiu,
        }

    def adicionar_xp(self, chave: str, xp: int) -> dict[str, Any]:
        chave = self.resolver(chave) or chave
        with self.db.transacao() as db:
            res = self._aplicar_xp_tx(db, chave, xp)
            if res.get("sucesso") is False:
                return res
            db.execute(
                "INSERT INTO rpg_profissoes_log (guild_id, user_id, chave, atividade, xp, nivel, criado_em) "
                "VALUES (?, ?, ?, 'atividade', ?, ?, ?)",
                (self.guild_id, self.user_id, chave, int(xp), res["nivel"], time.time()),
            )
            return res

    # ---------------- benefícios aplicados ----------------
    def bonus_mineracao(self) -> dict[str, float]:
        nivel = self.nivel("minerador")
        return {
            "qtd": min(0.30, 0.03 * max(0, nivel - 1)),
            "coins": min(0.25, 0.05 * max(0, nivel - 4)),
            "raro": min(0.25, 0.10 * max(0, nivel - 9)),
        }

    def bonus_exploracao(self) -> dict[str, float]:
        nivel = self.nivel("explorador")
        return {
            "xp": min(0.30, 0.05 * max(0, nivel - 1)),
            "coins": min(0.20, 0.05 * max(0, nivel - 4)),
        }

    def bonus_coleta(self, chave: str) -> dict[str, float]:
        nivel = self.nivel(chave)
        return {
            "qtd": min(0.40, 0.03 * max(0, nivel - 1)),
            "extra": min(0.50, 0.02 * max(0, nivel - 1)),
        }

    # ---------------- trabalho ----------------
    def trabalhar(self, chave_ou_nome: str | None = None) -> dict[str, Any]:
        if chave_ou_nome:
            chave = self.resolver(chave_ou_nome)
            if not chave:
                return {"sucesso": False, "motivo": "Profissão não encontrada."}
        else:
            with self.db.transacao() as db:
                row = db.execute(
                    "SELECT chave FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? ORDER BY nivel DESC, chave LIMIT 1",
                    (self.guild_id, self.user_id),
                ).fetchone()
            if not row:
                return {"sucesso": False, "motivo": "Você ainda não aprendeu nenhuma profissão."}
            chave = row[0]

        info = PROFISSOES.get(chave)
        if not info:
            return {"sucesso": False, "motivo": "Profissão inválida."}

        try:
            with self.db.transacao() as db:
                prof = db.execute(
                    "SELECT nivel, xp FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = ?",
                    (self.guild_id, self.user_id, chave),
                ).fetchone()
                if not prof:
                    return {"sucesso": False, "motivo": f"Você não aprendeu {info['nome']}."}
                char = self._char_tx(db)
                if not char:
                    return {"sucesso": False, "motivo": "Crie seu personagem com /rpg primeiro."}

                cooldown_key = f"trabalhar_{chave}"
                cd = db.execute(
                    "SELECT expira_em FROM rpg_cooldowns WHERE guild_id = ? AND user_id = ? AND chave = ?",
                    (self.guild_id, self.user_id, cooldown_key),
                ).fetchone()
                if cd and time.time() < cd[0]:
                    return {
                        "sucesso": False,
                        "motivo": "Atividade em cooldown.",
                        "restante": int(cd[0] - time.time()),
                    }

                nivel_prof = int(prof[0])
                # Calculado a partir do nível já lido dentro desta transação.
                # Chamar self.bonus_coleta() aqui abriria uma segunda transação
                # e provocaria "database is locked".
                bonus = {
                    "qtd": min(0.40, 0.03 * max(0, nivel_prof - 1)),
                    "extra": min(0.50, 0.02 * max(0, nivel_prof - 1)),
                }
                itens: dict[str, int] = {}
                receita = info.get("receita")

                if receita:
                    for ing, qtd in receita["ingredientes"].items():
                        if not self.inventory.tem_tx(db, ing, qtd):
                            from .items import nome_item
                            return {
                                "sucesso": False,
                                "motivo": f"Faltam materiais para a receita: {nome_item(ing)} x{qtd}.",
                                "faltando": ing,
                            }
                    for ing, qtd in receita["ingredientes"].items():
                        self.inventory.remover_tx(db, ing, qtd)
                    qtd_produto = int(receita["qtd"])
                    # Coincide com os marcos exibidos: nível 2 = 10%,
                    # nível 5 = 25%, nível 10 = 50%.
                    chance_extra = 0.0
                    if nivel_prof >= 2:
                        chance_extra = min(0.50, 0.10 + 0.05 * (nivel_prof - 2))
                    if random.random() < chance_extra:
                        qtd_produto += 1
                    itens[receita["produto"]] = qtd_produto
                    self.inventory.adicionar_tx(db, receita["produto"], qtd_produto)
                else:
                    for drop in info.get("itens", []):
                        if random.random() < drop["chance"]:
                            base = random.randint(*drop["qtd"])
                            qtd = max(1, int(round(base * (1 + bonus["qtd"]))))
                            itens[drop["key"]] = itens.get(drop["key"], 0) + qtd
                    # Item extra por nível, respeitando o limite.
                    if info.get("itens") and random.random() < bonus["extra"]:
                        drop = random.choice(info["itens"])
                        itens[drop["key"]] = itens.get(drop["key"], 0) + 1
                    for item_key, qtd in itens.items():
                        self.inventory.adicionar_tx(db, item_key, qtd)

                coins = 0
                cmin, cmax = info.get("coins", (0, 0))
                if cmax > 0:
                    # Comissão limitada; nunca gera dinheiro sem cooldown.
                    coins = random.randint(cmin, cmax) + min(10, max(0, nivel_prof - 1))
                    alterar_saldo_tx(db, self.guild_id, self.user_id, coins)

                xp_ganho = int(info.get("xp_atividade", 10)) + max(0, nivel_prof - 1) * 2
                progresso = self._aplicar_xp_tx(db, chave, xp_ganho)
                xp_char = adicionar_xp_tx(db, self.guild_id, self.user_id, 4 + max(0, nivel_prof // 3))

                agora = time.time()
                db.execute(
                    "INSERT INTO rpg_cooldowns (guild_id, user_id, chave, expira_em) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET expira_em = excluded.expira_em",
                    (self.guild_id, self.user_id, cooldown_key, agora + int(info.get("cooldown", 300))),
                )
                detalhe = f"{chave}|xp{xp_ganho}|coins{coins}|itens:{','.join(f'{k}x{v}' for k, v in itens.items())}"
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'trabalhar', ?, ?)",
                    (self.guild_id, self.user_id, detalhe, agora),
                )
                db.execute(
                    "INSERT INTO rpg_profissoes_log (guild_id, user_id, chave, atividade, xp, nivel, criado_em) "
                    "VALUES (?, ?, ?, 'trabalhar', ?, ?, ?)",
                    (self.guild_id, self.user_id, chave, xp_ganho, progresso["nivel"], agora),
                )
                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)

            return {
                "sucesso": True,
                "chave": chave,
                "nome": info["nome"],
                "itens": itens,
                "coins": coins,
                "saldo": saldo,
                "xp_ganho": xp_ganho,
                "nivel": progresso["nivel"],
                "nivel_antes": progresso["nivel_antes"],
                "subiu": progresso["subiu_nivel"],
                "xp": progresso["xp"],
                "xp_necessario": progresso["xp_necessario"],
                "beneficios_desbloqueados": progresso["beneficios_desbloqueados"],
                "xp_personagem": xp_char,
                "cooldown": int(info.get("cooldown", 300)),
            }
        except (sqlite3.Error, ValueError) as exc:
            return {"sucesso": False, "motivo": f"Atividade cancelada: {exc}"}
