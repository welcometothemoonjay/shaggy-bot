import time
from typing import Dict

from .database import get_db
from .schema import garantir_tabelas


class Inventario:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        garantir_tabelas()

    # ---------- helpers transacionais ----------
    def obter_tx(self, db) -> Dict[str, int]:
        cursor = db.execute(
            "SELECT item_key, quantidade FROM ruptura_inventario "
            "WHERE guild_id = ? AND user_id = ? AND quantidade > 0",
            (self.guild_id, self.user_id),
        )
        return {row[0]: int(row[1]) for row in cursor.fetchall()}

    def tem_tx(self, db, item_key: str, quantidade: int = 1) -> bool:
        row = db.execute(
            "SELECT quantidade FROM ruptura_inventario "
            "WHERE guild_id = ? AND user_id = ? AND item_key = ?",
            (self.guild_id, self.user_id, item_key),
        ).fetchone()
        return bool(row and int(row[0]) >= quantidade)

    def adicionar_tx(self, db, item_key: str, quantidade: int = 1) -> bool:
        if quantidade <= 0:
            return False
        db.execute("""
            INSERT INTO ruptura_inventario (guild_id, user_id, item_key, quantidade)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_key)
            DO UPDATE SET quantidade = ruptura_inventario.quantidade + excluded.quantidade
        """, (self.guild_id, self.user_id, item_key, quantidade))
        return True

    def remover_tx(self, db, item_key: str, quantidade: int = 1) -> bool:
        if quantidade <= 0 or not self.tem_tx(db, item_key, quantidade):
            return False
        db.execute(
            "UPDATE ruptura_inventario SET quantidade = quantidade - ? "
            "WHERE guild_id = ? AND user_id = ? AND item_key = ? AND quantidade >= ?",
            (quantidade, self.guild_id, self.user_id, item_key, quantidade),
        )
        db.execute(
            "DELETE FROM ruptura_inventario WHERE guild_id = ? AND user_id = ? "
            "AND item_key = ? AND quantidade <= 0",
            (self.guild_id, self.user_id, item_key),
        )
        return True

    # ---------- API pública ----------
    def obter(self) -> Dict[str, int]:
        with self.db.transacao() as db:
            return self.obter_tx(db)

    def tem(self, item_key: str, quantidade: int = 1) -> bool:
        with self.db.transacao() as db:
            return self.tem_tx(db, item_key, quantidade)

    def adicionar(self, item_key: str, quantidade: int = 1) -> bool:
        with self.db.transacao() as db:
            return self.adicionar_tx(db, item_key, quantidade)

    def remover(self, item_key: str, quantidade: int = 1) -> bool:
        with self.db.transacao() as db:
            return self.remover_tx(db, item_key, quantidade)

    def equipamentos(self) -> Dict[str, str]:
        with self.db.transacao() as db:
            rows = db.execute(
                "SELECT slot, item_key FROM rpg_equipamentos "
                "WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    def equipar(self, slot: str, item_key: str) -> bool:
        with self.db.transacao() as db:
            db.execute(
                "INSERT INTO rpg_equipamentos (guild_id, user_id, slot, item_key) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, slot) DO UPDATE SET item_key = excluded.item_key",
                (self.guild_id, self.user_id, slot, item_key),
            )
            return True

    def desequipar(self, slot: str) -> bool:
        with self.db.transacao() as db:
            db.execute(
                "DELETE FROM rpg_equipamentos WHERE guild_id = ? AND user_id = ? AND slot = ?",
                (self.guild_id, self.user_id, slot),
            )
            return True
