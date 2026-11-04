"""Energia do RPG Textual.

A energia é persistente e recupera automaticamente **100% a cada 24 horas**.
O instante da última recarga fica em ``rpg_flags`` com a chave
``energia_regen_em``. A verificação é preguiçosa: acontece na primeira leitura
ou consumo após o intervalo, sem depender de uma task em background.

``/descansar`` continua existindo e restaura a energia imediatamente, com
cooldown próprio. Depois de um descanso completo, o relógio das 24h também é
reiniciado para evitar uma recarga duplicada logo em seguida.
"""
from __future__ import annotations

import sqlite3
import time

from .constants import ENERGIA_MAX, ENERGIA_REGEN_INTERVALO_SEGUNDOS
from .database import get_db
from .schema import garantir_tabelas

CHAVE_ENERGIA = "energia"
CHAVE_REGEN = "energia_regen_em"


class Energy:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        garantir_tabelas()

    # ------------------------------------------------------------------
    # helpers transacionais
    # ------------------------------------------------------------------
    def _ler_valor_tx(self, db) -> int:
        row = db.execute(
            "SELECT valor FROM rpg_flags WHERE guild_id = ? AND user_id = ? AND chave = ?",
            (self.guild_id, self.user_id, CHAVE_ENERGIA),
        ).fetchone()
        if row:
            return max(0, min(ENERGIA_MAX, int(row[0])))

        # Migração única dos dados antigos de rpg_contadores.
        valor = ENERGIA_MAX
        try:
            antigo = db.execute(
                "SELECT valor FROM rpg_contadores WHERE guild_id = ? AND user_id = ? "
                "AND chave = 'energia' ORDER BY dia DESC LIMIT 1",
                (self.guild_id, self.user_id),
            ).fetchone()
            if antigo:
                valor = max(0, min(ENERGIA_MAX, int(antigo[0])))
        except sqlite3.OperationalError:
            pass
        db.execute(
            "INSERT OR IGNORE INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.guild_id, self.user_id, CHAVE_ENERGIA, valor, time.time()),
        )
        return valor

    def _definir_regen_tx(self, db, timestamp: int) -> None:
        db.execute(
            "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET "
            "valor = excluded.valor, atualizado_em = excluded.atualizado_em",
            (self.guild_id, self.user_id, CHAVE_REGEN, int(timestamp), time.time()),
        )

    def _regen_tx(self, db) -> dict:
        """Aplica a recarga de 24h, se devida. Retorna o estado resultante."""
        valor = self._ler_valor_tx(db)
        agora = int(time.time())
        row = db.execute(
            "SELECT valor, atualizado_em FROM rpg_flags "
            "WHERE guild_id = ? AND user_id = ? AND chave = ?",
            (self.guild_id, self.user_id, CHAVE_REGEN),
        ).fetchone()

        if not row:
            # Primeira execução após a atualização: usa a última alteração da
            # energia como referência. Quem já estava inativo há mais de 24h
            # recebe a recarga; quem acabou de gastar energia não recebe.
            origem = db.execute(
                "SELECT atualizado_em FROM rpg_flags "
                "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (self.guild_id, self.user_id, CHAVE_ENERGIA),
            ).fetchone()
            ultimo = int(float(origem[0])) if origem and origem[0] else agora
            if valor >= ENERGIA_MAX:
                ultimo = agora
            if valor < ENERGIA_MAX and agora - ultimo >= ENERGIA_REGEN_INTERVALO_SEGUNDOS:
                db.execute(
                    "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
                    "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                    (ENERGIA_MAX, time.time(), self.guild_id, self.user_id, CHAVE_ENERGIA),
                )
                valor = ENERGIA_MAX
                ultimo = agora
            self._definir_regen_tx(db, ultimo)
            return {
                "valor": valor,
                "recuperou": False,
                "recuperado": 0,
                "proximo_em": ultimo + ENERGIA_REGEN_INTERVALO_SEGUNDOS,
            }

        ultimo = int(row[0])
        if agora - ultimo >= ENERGIA_REGEN_INTERVALO_SEGUNDOS:
            recuperado = max(0, ENERGIA_MAX - valor)
            db.execute(
                "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (ENERGIA_MAX, time.time(), self.guild_id, self.user_id, CHAVE_ENERGIA),
            )
            self._definir_regen_tx(db, agora)
            return {
                "valor": ENERGIA_MAX,
                "recuperou": recuperado > 0,
                "recuperado": recuperado,
                "proximo_em": agora + ENERGIA_REGEN_INTERVALO_SEGUNDOS,
            }

        return {
            "valor": valor,
            "recuperou": False,
            "recuperado": 0,
            "proximo_em": ultimo + ENERGIA_REGEN_INTERVALO_SEGUNDOS,
        }

    # ------------------------------------------------------------------
    # API transacional (usada por mineração, combate, etc.)
    # ------------------------------------------------------------------
    def obter_tx(self, db) -> int:
        return int(self._regen_tx(db)["valor"])

    def consumir_tx(self, db, quantidade: int) -> bool:
        if quantidade <= 0:
            return True
        atual = int(self._regen_tx(db)["valor"])
        if atual < quantidade:
            return False
        db.execute(
            "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
            "WHERE guild_id = ? AND user_id = ? AND chave = ?",
            (atual - quantidade, time.time(), self.guild_id, self.user_id, CHAVE_ENERGIA),
        )
        return True

    def recarregar_tx(self, db) -> dict:
        return self._regen_tx(db)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def obter(self) -> int:
        with self.db.transacao() as db:
            return self.obter_tx(db)

    def obter_detalhado(self) -> dict:
        with self.db.transacao() as db:
            estado = self._regen_tx(db)
        estado["max"] = ENERGIA_MAX
        estado["restante"] = max(0, int(estado["proximo_em"] - time.time()))
        return estado

    def tem(self, quantidade: int) -> bool:
        return self.obter() >= quantidade

    def consumir(self, quantidade: int) -> bool:
        if quantidade <= 0:
            return True
        with self.db.transacao() as db:
            return self.consumir_tx(db, quantidade)

    def restaurar(self, quantidade: int) -> int:
        if quantidade <= 0:
            return self.obter()
        with self.db.transacao() as db:
            atual = self._ler_valor_tx(db)
            novo = min(ENERGIA_MAX, atual + quantidade)
            db.execute(
                "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (novo, time.time(), self.guild_id, self.user_id, CHAVE_ENERGIA),
            )
            return novo

    def restaurar_completo(self) -> bool:
        with self.db.transacao() as db:
            self._ler_valor_tx(db)
            db.execute(
                "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (ENERGIA_MAX, time.time(), self.guild_id, self.user_id, CHAVE_ENERGIA),
            )
            # O descanso completo reinicia o ciclo de 24h.
            self._definir_regen_tx(db, int(time.time()))
            return True
