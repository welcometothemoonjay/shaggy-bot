"""Casas do RPG Textual.

A casa é um marco de progressão cosmético/econômico (não concede bônus
mecânicos de combate). O armazenamento usa ``rpg_casas``, uma tabela estável
por jogador -- o sistema antigo usava ``rpg_contadores`` com a data na chave,
o que fazia a casa "desaparecer" no dia seguinte.
"""
from __future__ import annotations

import time
import unicodedata

from .database import get_db
from .economy import obter_saldo_tx, alterar_saldo_tx
from .schema import garantir_tabelas

TIPOS_CASA = {
    "tenda": {"nome": "Tenda", "preco": 100, "descricao": "Um abrigo simples e portátil."},
    "cabana": {"nome": "Cabana", "preco": 400, "descricao": "Uma cabana de madeira com espaço para guardar mantimentos."},
    "casa_pedra": {"nome": "Casa de Pedra", "preco": 1200, "descricao": "Uma construção sólida, feita para durar invernos rigorosos."},
}

ALIASES_CASA = {
    "tenda": "tenda",
    "cabana": "cabana",
    "casa de pedra": "casa_pedra",
    "pedra": "casa_pedra",
    "casa pedra": "casa_pedra",
}


def resolver_tipo_casa(tipo: str) -> str | None:
    """Aceita key, nome ou apelido sem diferenciar caixa/acentos."""
    texto = unicodedata.normalize("NFKD", str(tipo or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    chave = " ".join(texto.casefold().replace("_", " ").replace("-", " ").split())
    if chave in TIPOS_CASA:
        return chave
    return ALIASES_CASA.get(chave)


class Houses:
    def __init__(self, bot, guild_id: int, user_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        garantir_tabelas()

    def obter_casa(self) -> dict | None:
        with self.db.transacao() as db:
            row = db.execute(
                "SELECT tipo, nivel, criado_em, atualizado_em FROM rpg_casas "
                "WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchone()
            if not row:
                return None
            dados = dict(row)
        info = TIPOS_CASA.get(dados["tipo"], {"nome": dados["tipo"], "descricao": ""})
        dados["nome"] = info["nome"]
        dados["descricao"] = info["descricao"]
        return dados

    def comprar_casa(self, tipo: str = "tenda", preco: int | None = None) -> dict:
        chave = resolver_tipo_casa(tipo)
        info = TIPOS_CASA.get(chave) if chave else None
        if not info:
            return {
                "sucesso": False,
                "motivo": (
                    "Tipo de casa inválido. Use tenda, cabana ou casa de pedra."
                ),
                "opcoes": list(TIPOS_CASA),
            }
        tipo = chave
        custo = int(preco if preco is not None else info["preco"])
        try:
            with self.db.transacao() as db:
                existente = db.execute(
                    "SELECT 1 FROM rpg_casas WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchone()
                if existente:
                    return {"sucesso": False, "motivo": "Você já possui uma casa."}
                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)
                if saldo < custo:
                    return {
                        "sucesso": False,
                        "motivo": f"Abysmus insuficiente. Faltam {custo - saldo:,}.",
                    }
                alterar_saldo_tx(db, self.guild_id, self.user_id, -custo)
                agora = time.time()
                db.execute(
                    "INSERT INTO rpg_casas (guild_id, user_id, tipo, nivel, criado_em, atualizado_em) "
                    "VALUES (?, ?, ?, 1, ?, ?)",
                    (self.guild_id, self.user_id, tipo, agora, agora),
                )
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'comprar_casa', ?, ?)",
                    (self.guild_id, self.user_id, f"{tipo}:{custo}", agora),
                )
            return {"sucesso": True, "tipo": tipo, "nome": info["nome"], "preco": custo}
        except Exception as exc:
            return {"sucesso": False, "motivo": f"Compra cancelada: {exc}"}

    def melhorar_casa(self, preco: int | None = None) -> dict:
        try:
            with self.db.transacao() as db:
                row = db.execute(
                    "SELECT tipo, nivel FROM rpg_casas WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchone()
                if not row:
                    return {"sucesso": False, "motivo": "Você não possui uma casa."}
                if preco is None:
                    preco = 200 * max(1, int(row[1]))
                preco = int(preco)
                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)
                if saldo < preco:
                    return {
                        "sucesso": False,
                        "motivo": f"Abysmus insuficiente. Faltam {preco - saldo:,}.",
                    }
                alterar_saldo_tx(db, self.guild_id, self.user_id, -preco)
                nivel = int(row[1]) + 1
                db.execute(
                    "UPDATE rpg_casas SET nivel = ?, atualizado_em = ? "
                    "WHERE guild_id = ? AND user_id = ?",
                    (nivel, time.time(), self.guild_id, self.user_id),
                )
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'melhorar_casa', ?, ?)",
                    (self.guild_id, self.user_id, f"{row[0]}:{nivel}", time.time()),
                )
            return {"sucesso": True, "nivel": nivel, "preco": preco}
        except Exception as exc:
            return {"sucesso": False, "motivo": f"Melhoria cancelada: {exc}"}
