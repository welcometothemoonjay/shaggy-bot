import time
from typing import Tuple, Dict, Any

from .database import get_db
from .schema import garantir_tabelas
from .constants import xp_para_proximo_nivel


def calcular_nivel(xp_total: int) -> Tuple[int, int, int]:
    """Retorna (nível, xp dentro do nível atual, xp necessário para subir).

    O personagem começa no nível 1 com 0 XP. O nível 2 é alcançado ao
    acumular o custo do nível 1 (80 XP), e assim por diante.
    """
    xp_restante = max(0, int(xp_total))
    nivel = 1
    while True:
        custo = xp_para_proximo_nivel(nivel)
        if xp_restante < custo:
            break
        xp_restante -= custo
        nivel += 1
        if nivel > 10000:
            break
    return nivel, xp_restante, xp_para_proximo_nivel(nivel)


def adicionar_xp_tx(db, guild_id: int, user_id: int, quantidade: int) -> Dict[str, Any]:
    """Adiciona XP de personagem dentro de uma transação já aberta."""
    if quantidade <= 0:
        return {"sucesso": False, "motivo": "XP inválido"}
    row = db.execute(
        "SELECT xp, nivel FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ).fetchone()
    if not row:
        return {"sucesso": False, "motivo": "Personagem não existe"}

    xp_total = int(row[0]) + int(quantidade)
    nivel_antes = int(row[1])
    nivel_novo, xp_nivel, xp_prox = calcular_nivel(xp_total)
    db.execute(
        "UPDATE rpg_personagem SET xp = ?, nivel = ?, atualizado_em = ? "
        "WHERE guild_id = ? AND user_id = ?",
        (xp_total, nivel_novo, time.time(), guild_id, user_id),
    )
    return {
        "sucesso": True,
        "xp_ganho": quantidade,
        "xp_total": xp_total,
        "xp_nivel": xp_nivel,
        "xp_proximo": xp_prox,
        "nivel_antes": nivel_antes,
        "nivel_novo": nivel_novo,
        "subiu_nivel": nivel_novo > nivel_antes,
    }


class Progression:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        garantir_tabelas()

    def obter_personagem(self) -> Dict[str, Any] | None:
        with self.db.transacao() as db:
            row = db.execute(
                "SELECT * FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
                (self.guild_id, self.user_id),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def criar_personagem(self, nome: str, classe_key: str = "aventureiro") -> bool:
        agora = time.time()
        try:
            with self.db.transacao() as db:
                db.execute(
                    "INSERT INTO rpg_personagem "
                    "(guild_id, user_id, nome, classe_key, nivel, xp, vida, reputacao, "
                    " regiao, profissao, titulos, titulo_ativo, criado_em, atualizado_em) "
                    "VALUES (?, ?, ?, ?, 1, 0, 100, 0, 'dakor', 'explorador', '[]', '', ?, ?)",
                    (self.guild_id, self.user_id, nome, classe_key, agora, agora),
                )
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'criar_personagem', ?, ?)",
                    (self.guild_id, self.user_id, classe_key, agora),
                )
            return True
        except Exception:
            return False

    def ganhar_xp(self, quantidade: int) -> Dict[str, Any]:
        """Adiciona XP atomicamente (sem abrir transação aninhada)."""
        if quantidade <= 0:
            return {"sucesso": False}
        with self.db.transacao() as db:
            return adicionar_xp_tx(db, self.guild_id, self.user_id, quantidade)

    def definir_regiao(self, regiao: str) -> bool:
        with self.db.transacao() as db:
            db.execute(
                "UPDATE rpg_personagem SET regiao = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ?",
                (regiao, time.time(), self.guild_id, self.user_id),
            )
        return True
