"""Economia do RPG Textual.

A moeda é o Abysmus, armazenado em ``user_stats`` (a mesma tabela usada pelo
cog XpAndCoins). Todas as operações abaixo são atômicas. Os helpers ``*_tx``
existem para que mercado, mineração e conquistas debitem/creditem moedas na
mesma transação que grava itens, cooldowns e estatísticas.
"""
from __future__ import annotations

import sqlite3
from typing import Tuple

from .database import get_db
from .schema import garantir_tabelas


def _garantir_usuario(db, guild_id: int, user_id: int) -> None:
    db.execute("""
        INSERT OR IGNORE INTO user_stats
            (guild_id, user_id, xp, level, coins, last_xp,
             highest_rewarded_level, last_daily, daily_streak)
        VALUES (?, ?, 0, 0, 0, 0, 0, '', 0)
    """, (guild_id, user_id))


def obter_saldo_tx(db, guild_id: int, user_id: int) -> int:
    _garantir_usuario(db, guild_id, user_id)
    row = db.execute(
        "SELECT coins FROM user_stats WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ).fetchone()
    return int(row[0]) if row else 0


def alterar_saldo_tx(db, guild_id: int, user_id: int, diferenca: int) -> int:
    saldo = obter_saldo_tx(db, guild_id, user_id)
    novo = saldo + int(diferenca)
    if novo < 0:
        raise ValueError("Saldo insuficiente.")
    db.execute(
        "UPDATE user_stats SET coins = ? WHERE guild_id = ? AND user_id = ?",
        (novo, guild_id, user_id),
    )
    return novo


class Economy:
    def __init__(self, bot=None):
        self.bot = bot
        garantir_tabelas()

    def obter_saldo(self, guild_id: int, user_id: int) -> int:
        with get_db().transacao() as db:
            return obter_saldo_tx(db, guild_id, user_id)

    def adicionar(self, guild_id: int, user_id: int, quantidade: int, motivo: str = "") -> Tuple[bool, int]:
        if quantidade <= 0:
            return False, self.obter_saldo(guild_id, user_id)
        try:
            with get_db().transacao() as db:
                saldo = alterar_saldo_tx(db, guild_id, user_id, int(quantidade))
            return True, saldo
        except sqlite3.Error:
            return False, self.obter_saldo(guild_id, user_id)

    def remover(self, guild_id: int, user_id: int, quantidade: int, motivo: str = "") -> Tuple[bool, int]:
        if quantidade <= 0:
            return False, self.obter_saldo(guild_id, user_id)
        try:
            with get_db().transacao() as db:
                saldo = alterar_saldo_tx(db, guild_id, user_id, -int(quantidade))
            return True, saldo
        except (ValueError, sqlite3.Error):
            return False, self.obter_saldo(guild_id, user_id)
