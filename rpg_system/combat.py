"""Combate simples por turnos do RPG Textual.

O combate é curto e direto: o jogador escolhe um inimigo, pode atacar com as
mãos ou com qualquer item da mochila e ganha XP a cada golpe. A vitória rende
Abysmus e XP extras; a derrota encerra o combate sem punição financeira.

Toda a mecânica é decidida em Python. O estado do combate fica em
``rpg_combates`` (um combate ativo por jogador) e as recompensas são gravadas
na mesma transação do turno. O OpenRouter não participa do combate.
"""
from __future__ import annotations

import random
import re
import sqlite3
import time
import unicodedata
from typing import Any

from .constants import COMBATE_ENERGIA_CUSTO, ENERGIA_MAX
from .database import get_db
from .economy import alterar_saldo_tx, obter_saldo_tx
from .energy import Energy
from .inventory import Inventario
from .items import CATALOGO_ITENS, obter_item
from .progression import adicionar_xp_tx
from .schema import garantir_tabelas

PV_BASE_JOGADOR = 60
PV_POR_NIVEL = 10
CHANCE_CRITICO = 0.12
CHANCE_ERRO_INIMIGO = 0.08
MULTIPLICADOR_CRITICO = 1.5

# Cinco inimigos iniciais. ``coins`` é sorteado apenas na vitória.
INIMIGOS: dict[str, dict[str, Any]] = {
    "goblin": {
        "key": "goblin",
        "nome": "Goblin",
        "emoji": "👺",
        "nivel_min": 1,
        "pv": 35,
        "ataque": (4, 7),
        "xp": 28,
        "coins": (8, 18),
        "dificuldade": "Fácil",
        "descricao": "Pequeno, irritadiço e sempre em bandos. Um bom primeiro teste.",
        "aliases": ["duende", "goblin"],
        "especial": False,
        "dica": "Pode ser vencido com as mãos por um aventureiro de nível 1.",
    },
    "mimico": {
        "key": "mimico",
        "nome": "Mímico",
        "emoji": "🧰",
        "nivel_min": 2,
        "pv": 55,
        "ataque": (5, 9),
        "xp": 40,
        "coins": (80, 140),
        "dificuldade": "Média",
        "descricao": "Um baú que morde. Esconde uma fortuna entre madeira e dentes.",
        "aliases": ["mimico", "mímico", "baú", "bau", "mimic"],
        "especial": False,
        "dica": "Recompensa em Abysmus muito acima dos outros inimigos.",
    },
    "diabrete": {
        "key": "diabrete",
        "nome": "Diabrete",
        "emoji": "😈",
        "nivel_min": 3,
        "pv": 70,
        "ataque": (8, 13),
        "xp": 55,
        "coins": (20, 35),
        "dificuldade": "Média",
        "descricao": "Uma criatura travessa que ataca com pequenas chamas e risadas.",
        "aliases": ["diabrete", "diabo", "imp"],
        "especial": False,
        "dica": "Prefira uma ferramenta; mãos nuas sofrem contra o fogo.",
    },
    "orc": {
        "key": "orc",
        "nome": "Orc",
        "emoji": "🪓",
        "nivel_min": 5,
        "pv": 110,
        "ataque": (12, 18),
        "xp": 85,
        "coins": (35, 60),
        "dificuldade": "Difícil",
        "descricao": "Um guerreiro enorme, coberto de cicatrizes e armado com um machado.",
        "aliases": ["orc", "orque"],
        "especial": False,
        "dica": "Uma Picareta de Ferro ou superior já equilibra a luta.",
    },
    "cerbero": {
        "key": "cerbero",
        "nome": "Cérbero",
        "emoji": "🐺",
        "nivel_min": 8,
        "pv": 170,
        "ataque": (14, 20),
        "xp": 180,
        "coins": (120, 200),
        "dificuldade": "Lendário",
        "descricao": "O cão infernal de três cabeças. Seu latido faz o chão tremer.",
        "aliases": ["cerbero", "cérbero", "cao infernal", "cão infernal", "cão do inferno"],
        "especial": True,
        "dica": "Fica furioso abaixo de metade da vida. Leve uma arma forte.",
    },
}


def normalizar(texto: str) -> str:
    """Compara nomes sem diferenciar caixa, acentos ou pontuação."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.casefold()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _candidatos_inimigo(info: dict[str, Any]) -> list[str]:
    valores = [info["nome"], info["key"], *info.get("aliases", [])]
    return [normalizar(v) for v in valores if v]


def pv_max_jogador(nivel: int) -> int:
    return PV_BASE_JOGADOR + max(1, int(nivel)) * PV_POR_NIVEL


def perfil_arma(arma_key: str | None, nivel_jogador: int) -> dict[str, Any] | None:
    """Retorna o dano real de uma arma (ou das mãos)."""
    if not arma_key or normalizar(arma_key) in ("maos", "mao", "punhos", "desarmado"):
        base = 4 + max(1, int(nivel_jogador)) // 2
        return {
            "key": "maos",
            "nome": "Mãos",
            "min": base,
            "max": base + 3,
            "improvisada": False,
        }
    item = obter_item(str(arma_key))
    if not item:
        return None
    if item.poder_combate > 0:
        return {
            "key": item.key,
            "nome": item.nome,
            "min": max(1, item.poder_combate - 1),
            "max": item.poder_combate + 2,
            "improvisada": False,
        }
    return {
        "key": item.key,
        "nome": item.nome,
        "min": 2,
        "max": 5,
        "improvisada": True,
    }


class Combate:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.inventory = Inventario(guild_id, user_id)
        self.energy = Energy(guild_id, user_id)
        garantir_tabelas()

    # ------------------------------------------------------------------
    # resolução de nomes
    # ------------------------------------------------------------------
    def resolver_inimigo(self, nome: str) -> dict[str, Any]:
        alvo = normalizar(nome)
        if not alvo:
            return {"status": "nao_encontrado", "opcoes": []}

        exatos: list[dict] = []
        inicios: list[dict] = []
        contem: list[dict] = []
        for info in INIMIGOS.values():
            candidatos = _candidatos_inimigo(info)
            if alvo in candidatos:
                exatos.append(info)
            elif any(c.startswith(alvo) for c in candidatos):
                inicios.append(info)
            elif any(alvo in c for c in candidatos):
                contem.append(info)

        for grupo in (exatos, inicios, contem):
            unicos = {i["key"]: i for i in grupo}
            if len(unicos) == 1:
                return {"status": "ok", "inimigo": next(iter(unicos.values()))}
            if len(unicos) > 1:
                return {
                    "status": "ambiguo",
                    "opcoes": sorted(unicos.values(), key=lambda i: i["nome"]),
                }
        return {"status": "nao_encontrado", "opcoes": []}

    def resolver_arma(self, db, nome: str | None) -> dict[str, Any]:
        """Resolve a arma entre os itens que o jogador realmente possui."""
        if not nome or normalizar(nome) in ("maos", "mao", "punhos", "desarmado"):
            return {"status": "ok", "key": "maos", "nome": "Mãos"}

        alvo = normalizar(nome)
        inv = self.inventory.obter_tx(db)
        exatos: list[Any] = []
        inicios: list[Any] = []
        contem: list[Any] = []
        for item in CATALOGO_ITENS.values():
            if inv.get(item.key, 0) <= 0:
                continue
            candidatos = [normalizar(item.nome), normalizar(item.key)]
            candidatos += [normalizar(a) for a in item.aliases if a]
            if alvo in candidatos:
                exatos.append(item)
            elif any(c.startswith(alvo) for c in candidatos):
                inicios.append(item)
            elif any(alvo in c for c in candidatos):
                contem.append(item)

        for grupo in (exatos, inicios, contem):
            unicos = {i.key: i for i in grupo}
            if len(unicos) == 1:
                item = next(iter(unicos.values()))
                return {"status": "ok", "key": item.key, "nome": item.nome}
            if len(unicos) > 1:
                return {
                    "status": "ambiguo",
                    "opcoes": sorted(i.nome for i in unicos.values()),
                }

        # Diferencia "não existe" de "existe, mas não está na mochila".
        for item in CATALOGO_ITENS.values():
            candidatos = [normalizar(item.nome), normalizar(item.key)]
            candidatos += [normalizar(a) for a in item.aliases if a]
            if alvo in candidatos or any(c.startswith(alvo) for c in candidatos):
                return {
                    "status": "nao_possui",
                    "motivo": f"Você não possui **{item.nome}** na mochila.",
                }
        return {"status": "nao_encontrado", "motivo": "Item não encontrado na mochila."}

    # ------------------------------------------------------------------
    # helpers internos
    # ------------------------------------------------------------------
    def _char_tx(self, db):
        return db.execute(
            "SELECT nivel, xp FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()

    def _estado_tx(self, db) -> dict[str, Any] | None:
        row = db.execute(
            "SELECT inimigo, pv_jogador, pv_inimigo, arma_key, turno, furia "
            "FROM rpg_combates WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()
        if not row:
            return None
        info = INIMIGOS.get(row[0])
        if not info:
            return None
        return {
            "inimigo": info,
            "pv_jogador": int(row[1]),
            "pv_inimigo": int(row[2]),
            "arma_key": row[3] or "maos",
            "turno": int(row[4]),
            "furia": bool(row[5]),
        }

    def _inserir_acao_tx(self, db, tipo: str, detalhe: str) -> None:
        db.execute(
            "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.guild_id, self.user_id, tipo, detalhe[:200], time.time()),
        )

    def _executar_turno_tx(self, db, nivel: int, estado: dict[str, Any],
                           rng, arma_key: str) -> dict[str, Any]:
        info = estado["inimigo"]
        perfil = perfil_arma(arma_key, nivel) or perfil_arma("maos", nivel)
        assert perfil is not None

        critico = rng.random() < CHANCE_CRITICO
        dano_jogador = rng.randint(perfil["min"], perfil["max"])
        if critico:
            dano_jogador = int(round(dano_jogador * MULTIPLICADOR_CRITICO))
        pv_inimigo = max(0, estado["pv_inimigo"] - dano_jogador)

        xp_golpe = 1 + int(info.get("nivel_min", 1)) // 2
        xp_recompensa = 0
        coins = 0
        vitoria = pv_inimigo <= 0
        derrota = False
        dano_inimigo = 0
        inimigo_errou = False
        furia_ativada = False
        saldo = obter_saldo_tx(db, self.guild_id, self.user_id)

        if vitoria:
            xp_recompensa = int(info.get("xp", 0))
            coins = rng.randint(*info.get("coins", (0, 0)))
            if coins > 0:
                saldo = alterar_saldo_tx(db, self.guild_id, self.user_id, coins)
            self._inserir_acao_tx(
                db, "combate_vitoria", f"{info['key']}:turno{estado['turno']}"
            )
            if info.get("especial"):
                self._inserir_acao_tx(
                    db, "combate_especial", f"{info['key']}:turno{estado['turno']}"
                )
            db.execute(
                "DELETE FROM rpg_combates WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            )
        else:
            # Contra-ataque do inimigo.
            furia = estado["furia"] or (
                info.get("especial") and pv_inimigo <= int(info["pv"]) // 2
            )
            if furia and not estado["furia"]:
                furia_ativada = True
            if rng.random() < CHANCE_ERRO_INIMIGO:
                inimigo_errou = True
            else:
                dano_base = rng.randint(*info.get("ataque", (1, 2)))
                dano_inimigo = max(1, dano_base - nivel // 3)
                if furia:
                    dano_inimigo = int(round(dano_inimigo * 1.35))
                if dano_inimigo >= estado["pv_jogador"]:
                    derrota = True
            pv_jogador = max(0, estado["pv_jogador"] - dano_inimigo)
            if derrota:
                self._inserir_acao_tx(
                    db, "combate_derrota", f"{info['key']}:turno{estado['turno']}"
                )
                db.execute(
                    "DELETE FROM rpg_combates WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                )

        xp_resultado = adicionar_xp_tx(
            db, self.guild_id, self.user_id, xp_golpe + xp_recompensa
        )

        if not vitoria and not derrota:
            db.execute(
                "UPDATE rpg_combates SET pv_jogador = ?, pv_inimigo = ?, arma_key = ?, "
                "turno = turno + 1, furia = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ?",
                (
                    pv_jogador, pv_inimigo, perfil["key"], 1 if furia else 0,
                    time.time(), self.guild_id, self.user_id,
                ),
            )

        energia = self.energy.obter_tx(db)
        base = {
            "inimigo_key": info["key"],
            "inimigo_nome": info["nome"],
            "inimigo_emoji": info.get("emoji", "⚔️"),
            "inimigo_dificuldade": info.get("dificuldade", ""),
            "pv_max_jogador": pv_max_jogador(nivel),
            "pv_max_inimigo": int(info["pv"]),
            "dano_jogador": dano_jogador,
            "critico": critico,
            "arma_key": perfil["key"],
            "arma_nome": perfil["nome"],
            "arma_improvisada": bool(perfil["improvisada"]),
            "xp_golpe": xp_golpe,
            "xp_recompensa": xp_recompensa,
            "xp": xp_resultado,
            "coins": coins,
            "saldo": saldo,
            "energia": energia,
            "energia_max": ENERGIA_MAX,
            "custo_energia": COMBATE_ENERGIA_CUSTO,
        }

        if vitoria:
            base.update({
                "sucesso": True,
                "estado": "vitoria",
                "pv_jogador": estado["pv_jogador"],
                "pv_inimigo": 0,
                "turno": estado["turno"],
            })
            return base

        if derrota:
            base.update({
                "sucesso": True,
                "estado": "derrota",
                "pv_jogador": 0,
                "pv_inimigo": pv_inimigo,
                "turno": estado["turno"],
                "dano_inimigo": dano_inimigo,
                "inimigo_errou": inimigo_errou,
                "furia_ativada": furia_ativada,
            })
            return base

        base.update({
            "sucesso": True,
            "estado": "ativo",
            "pv_jogador": pv_jogador,
            "pv_inimigo": pv_inimigo,
            "turno": estado["turno"] + 1,
            "dano_inimigo": dano_inimigo,
            "inimigo_errou": inimigo_errou,
            "furia_ativada": furia_ativada,
            "furia": bool(furia),
        })
        return base

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def catalogo(self) -> list[dict[str, Any]]:
        return [
            {
                "key": info["key"],
                "nome": info["nome"],
                "emoji": info.get("emoji", "⚔️"),
                "nivel_min": int(info["nivel_min"]),
                "pv": int(info["pv"]),
                "xp": int(info["xp"]),
                "coins": info["coins"],
                "dificuldade": info.get("dificuldade", ""),
                "descricao": info.get("descricao", ""),
                "dica": info.get("dica", ""),
                "especial": bool(info.get("especial")),
            }
            for info in sorted(INIMIGOS.values(), key=lambda i: i["nivel_min"])
        ]

    def status(self) -> dict[str, Any]:
        with self.db.transacao() as db:
            estado = self._estado_tx(db)
            if not estado:
                return {"estado": "sem_combate", "catalogo": self.catalogo()}
            nivel = int(self._char_tx(db)[0]) if self._char_tx(db) else 1
            energia = self.energy.obter_tx(db)
        info = estado["inimigo"]
        return {
            "estado": "ativo",
            "inimigo_key": info["key"],
            "inimigo_nome": info["nome"],
            "inimigo_emoji": info.get("emoji", "⚔️"),
            "inimigo_dificuldade": info.get("dificuldade", ""),
            "pv_jogador": estado["pv_jogador"],
            "pv_max_jogador": pv_max_jogador(nivel),
            "pv_inimigo": estado["pv_inimigo"],
            "pv_max_inimigo": int(info["pv"]),
            "arma_key": estado["arma_key"],
            "arma_nome": (perfil_arma(estado["arma_key"], nivel) or {}).get("nome", "Mãos"),
            "turno": estado["turno"],
            "furia": estado["furia"],
            "energia": energia,
            "custo_energia": COMBATE_ENERGIA_CUSTO,
        }

    def resumo(self) -> dict[str, int]:
        with self.db.transacao() as db:
            counts = {
                row[0]: int(row[1])
                for row in db.execute(
                    "SELECT tipo, COUNT(*) FROM rpg_acoes "
                    "WHERE guild_id = ? AND user_id = ? "
                    "AND tipo IN ('combate_vitoria', 'combate_derrota', 'combate_especial') "
                    "GROUP BY tipo",
                    (self.guild_id, self.user_id),
                ).fetchall()
            }
            ativo = self._estado_tx(db) is not None
        return {
            "vitorias": counts.get("combate_vitoria", 0),
            "derrotas": counts.get("combate_derrota", 0),
            "especiais": counts.get("combate_especial", 0),
            "ativo": 1 if ativo else 0,
        }

    def iniciar(self, inimigo: str, arma: str | None = None, rng=None) -> dict[str, Any]:
        rng = rng or random
        resolvido = self.resolver_inimigo(inimigo)
        if resolvido["status"] == "ambiguo":
            return {
                "sucesso": False,
                "status": "ambiguo",
                "motivo": "Há mais de um inimigo com esse nome.",
                "opcoes": [i["nome"] for i in resolvido["opcoes"]],
            }
        if resolvido["status"] != "ok":
            return {
                "sucesso": False,
                "status": "nao_encontrado",
                "motivo": "Inimigo não encontrado.",
                "opcoes": [i["nome"] for i in INIMIGOS.values()],
            }
        info = resolvido["inimigo"]

        try:
            with self.db.transacao() as db:
                char = self._char_tx(db)
                if not char:
                    return {
                        "sucesso": False,
                        "status": "sem_personagem",
                        "motivo": "Crie seu personagem com /rpg primeiro.",
                    }
                nivel = int(char[0])
                if nivel < int(info["nivel_min"]):
                    return {
                        "sucesso": False,
                        "status": "requisito",
                        "motivo": (
                            f"**{info['nome']}** requer nível {info['nivel_min']} "
                            f"(seu nível: {nivel})."
                        ),
                    }
                if self._estado_tx(db):
                    return {
                        "sucesso": False,
                        "status": "em_combate",
                        "motivo": "Você já está em combate. Use `/combate` para atacar.",
                    }
                arma_res = self.resolver_arma(db, arma)
                if arma_res["status"] != "ok":
                    return {
                        "sucesso": False,
                        "status": arma_res["status"],
                        "motivo": arma_res.get("motivo", "Arma inválida."),
                        "opcoes": arma_res.get("opcoes", []),
                    }
                if not self.energy.consumir_tx(db, COMBATE_ENERGIA_CUSTO):
                    return {
                        "sucesso": False,
                        "status": "energia",
                        "motivo": (
                            f"Energia insuficiente. Cada ação de combate custa "
                            f"{COMBATE_ENERGIA_CUSTO}."
                        ),
                    }
                agora = time.time()
                pv_j = pv_max_jogador(nivel)
                db.execute(
                    "INSERT INTO rpg_combates "
                    "(guild_id, user_id, inimigo, pv_jogador, pv_inimigo, arma_key, "
                    " turno, furia, criado_em, atualizado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)",
                    (
                        self.guild_id, self.user_id, info["key"], pv_j,
                        int(info["pv"]), arma_res["key"], agora, agora,
                    ),
                )
                self._inserir_acao_tx(db, "combate_inicio", info["key"])
                estado = {
                    "inimigo": info,
                    "pv_jogador": pv_j,
                    "pv_inimigo": int(info["pv"]),
                    "arma_key": arma_res["key"],
                    "turno": 1,
                    "furia": False,
                }
                return self._executar_turno_tx(db, nivel, estado, rng, arma_res["key"])
        except sqlite3.Error as exc:
            return {
                "sucesso": False,
                "status": "erro",
                "motivo": f"Combate cancelado por erro de transação: {exc}",
            }

    def atacar(self, arma: str | None = None, rng=None) -> dict[str, Any]:
        rng = rng or random
        try:
            with self.db.transacao() as db:
                char = self._char_tx(db)
                if not char:
                    return {
                        "sucesso": False,
                        "status": "sem_personagem",
                        "motivo": "Crie seu personagem com /rpg primeiro.",
                    }
                nivel = int(char[0])
                estado = self._estado_tx(db)
                if not estado:
                    return {
                        "sucesso": False,
                        "status": "sem_combate",
                        "motivo": "Nenhum combate ativo. Use `/combate inimigo:Goblin` para começar.",
                    }
                if arma:
                    arma_res = self.resolver_arma(db, arma)
                    if arma_res["status"] != "ok":
                        return {
                            "sucesso": False,
                            "status": arma_res["status"],
                            "motivo": arma_res.get("motivo", "Arma inválida."),
                            "opcoes": arma_res.get("opcoes", []),
                        }
                    arma_key = arma_res["key"]
                else:
                    arma_key = estado["arma_key"]
                    if arma_key != "maos" and not self.inventory.tem_tx(db, arma_key, 1):
                        arma_key = "maos"
                if not self.energy.consumir_tx(db, COMBATE_ENERGIA_CUSTO):
                    return {
                        "sucesso": False,
                        "status": "energia",
                        "motivo": (
                            f"Energia insuficiente. Cada ação de combate custa "
                            f"{COMBATE_ENERGIA_CUSTO}."
                        ),
                        "energia": self.energy.obter_tx(db),
                    }
                return self._executar_turno_tx(db, nivel, estado, rng, arma_key)
        except sqlite3.Error as exc:
            return {
                "sucesso": False,
                "status": "erro",
                "motivo": f"Combate cancelado por erro de transação: {exc}",
            }
