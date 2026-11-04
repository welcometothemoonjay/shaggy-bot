"""Ferramentas administrativas do RPG Textual.

Estas funções existem para os comandos de prefixo ``s!rpg...`` usados por
desenvolvedores e moderadores. Toda alteração é atômica e limitada ao estado
do RPG Textual:

- Não mexe no saldo global além do delta solicitado.
- Não apaga o inventário, que é compartilhado com a Ruptura Temporal.
- Não altera ``user_stats`` ao resetar um personagem (saldo e XP social
  continuam intactos).
- Registra as ações administrativas em ``rpg_acoes`` quando aplicável.

A autorização (dono do bot, administrador ou moderador) fica no cog
``cogs/rpg.py``. Este módulo não conhece Discord.
"""
from __future__ import annotations

import time
from typing import Any

from .constants import ENERGIA_MAX
from .database import get_db
from .economy import alterar_saldo_tx, obter_saldo_tx
from .energy import CHAVE_ENERGIA, CHAVE_REGEN, Energy
from .inventory import Inventario
from .market_v2 import MarketV2
from .progression import calcular_nivel
from .schema import garantir_tabelas


def _char_tx(db, guild_id: int, user_id: int):
    return db.execute(
        "SELECT nome, nivel, xp, regiao FROM rpg_personagem "
        "WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ).fetchone()


def _sem_personagem() -> dict[str, Any]:
    return {
        "sucesso": False,
        "motivo": "O jogador ainda não possui personagem no RPG.",
    }


def _registrar_acao_tx(db, guild_id: int, user_id: int, tipo: str, detalhe: str) -> None:
    db.execute(
        "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
        "VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, tipo, detalhe[:200], time.time()),
    )


def resumo(guild_id: int, user_id: int) -> dict[str, Any]:
    """Retorna um panorama do jogador para moderação."""
    garantir_tabelas()
    with get_db().transacao() as db:
        char = _char_tx(db, guild_id, user_id)
        saldo = obter_saldo_tx(db, guild_id, user_id)
        energia = Energy(guild_id, user_id).obter_tx(db)
        casa = db.execute(
            "SELECT tipo, nivel FROM rpg_casas WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        combate = db.execute(
            "SELECT inimigo, pv_jogador, pv_inimigo, turno FROM rpg_combates "
            "WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        acoes = {
            row[0]: int(row[1])
            for row in db.execute(
                "SELECT tipo, COUNT(*) FROM rpg_acoes "
                "WHERE guild_id = ? AND user_id = ? "
                "AND tipo IN ('combate_vitoria', 'combate_derrota', "
                "'combate_especial', 'comprar_casa') "
                "GROUP BY tipo",
                (guild_id, user_id),
            ).fetchall()
        }
        itens = sum(
            int(row[0])
            for row in db.execute(
                "SELECT quantidade FROM ruptura_inventario "
                "WHERE guild_id = ? AND user_id = ? AND quantidade > 0",
                (guild_id, user_id),
            ).fetchall()
        )
        profissoes = db.execute(
            "SELECT COUNT(*) FROM rpg_profissoes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()[0]
        conquistas = db.execute(
            "SELECT COUNT(*) FROM rpg_conquistas WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()[0]
    return {
        "personagem": dict(char) if char else None,
        "saldo": int(saldo),
        "energia": int(energia),
        "energia_max": ENERGIA_MAX,
        "casa": dict(casa) if casa else None,
        "combate": dict(combate) if combate else None,
        "vitorias": acoes.get("combate_vitoria", 0),
        "derrotas": acoes.get("combate_derrota", 0),
        "especiais": acoes.get("combate_especial", 0),
        "casas_compradas": acoes.get("comprar_casa", 0),
        "itens": int(itens),
        "profissoes": int(profissoes),
        "conquistas": int(conquistas),
    }


def ranking(guild_id: int, limite: int = 10) -> list[dict[str, Any]]:
    """Top jogadores do servidor por XP de personagem."""
    garantir_tabelas()
    limite = max(1, min(25, int(limite)))
    with get_db().transacao() as db:
        rows = db.execute(
            "SELECT user_id, nome, nivel, xp FROM rpg_personagem "
            "WHERE guild_id = ? ORDER BY xp DESC, nome ASC LIMIT ?",
            (guild_id, limite),
        ).fetchall()
    return [dict(row) for row in rows]


def ajustar_moedas(guild_id: int, user_id: int, delta: int,
                   moderador_id: int = 0) -> dict[str, Any]:
    if delta == 0:
        return {"sucesso": False, "motivo": "Informe um valor diferente de zero."}
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            saldo = alterar_saldo_tx(db, guild_id, user_id, int(delta))
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_moedas",
                f"{delta:+d}:por{moderador_id}",
            )
        return {"sucesso": True, "saldo": saldo, "delta": int(delta)}
    except ValueError:
        return {"sucesso": False, "motivo": "O saldo ficaria negativo."}
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao ajustar moedas: {exc}"}


def definir_moedas(guild_id: int, user_id: int, valor: int,
                   moderador_id: int = 0) -> dict[str, Any]:
    if valor < 0:
        return {"sucesso": False, "motivo": "O saldo não pode ser negativo."}
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            atual = obter_saldo_tx(db, guild_id, user_id)
            saldo = alterar_saldo_tx(db, guild_id, user_id, int(valor) - atual)
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_moedas",
                f"set:{valor}:por{moderador_id}",
            )
        return {"sucesso": True, "saldo": saldo, "anterior": atual}
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao definir moedas: {exc}"}


def ajustar_xp(guild_id: int, user_id: int, delta: int,
               moderador_id: int = 0) -> dict[str, Any]:
    if delta == 0:
        return {"sucesso": False, "motivo": "Informe um valor diferente de zero."}
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            row = _char_tx(db, guild_id, user_id)
            if not row:
                return _sem_personagem()
            xp_antes = int(row[2])
            nivel_antes = int(row[1])
            xp_total = max(0, xp_antes + int(delta))
            nivel_novo, xp_nivel, xp_proximo = calcular_nivel(xp_total)
            db.execute(
                "UPDATE rpg_personagem SET xp = ?, nivel = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ?",
                (xp_total, nivel_novo, time.time(), guild_id, user_id),
            )
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_xp",
                f"{delta:+d}:por{moderador_id}",
            )
        return {
            "sucesso": True,
            "xp_total": xp_total,
            "xp_anterior": xp_antes,
            "xp_nivel": xp_nivel,
            "xp_proximo": xp_proximo,
            "nivel": nivel_novo,
            "nivel_anterior": nivel_antes,
            "delta": int(delta),
        }
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao ajustar XP: {exc}"}


def definir_xp(guild_id: int, user_id: int, valor: int,
               moderador_id: int = 0) -> dict[str, Any]:
    if valor < 0:
        return {"sucesso": False, "motivo": "O XP não pode ser negativo."}
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            row = _char_tx(db, guild_id, user_id)
            if not row:
                return _sem_personagem()
            xp_antes = int(row[2])
            nivel_antes = int(row[1])
            nivel_novo, xp_nivel, xp_proximo = calcular_nivel(int(valor))
            db.execute(
                "UPDATE rpg_personagem SET xp = ?, nivel = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ?",
                (int(valor), nivel_novo, time.time(), guild_id, user_id),
            )
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_xp",
                f"set:{valor}:por{moderador_id}",
            )
        return {
            "sucesso": True,
            "xp_total": int(valor),
            "xp_anterior": xp_antes,
            "xp_nivel": xp_nivel,
            "xp_proximo": xp_proximo,
            "nivel": nivel_novo,
            "nivel_anterior": nivel_antes,
        }
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao definir XP: {exc}"}


def definir_energia(guild_id: int, user_id: int, valor: int,
                    moderador_id: int = 0) -> dict[str, Any]:
    valor = max(0, min(ENERGIA_MAX, int(valor)))
    garantir_tabelas()
    try:
        energia = Energy(guild_id, user_id)
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            energia.obter_tx(db)  # garante a migração da linha
            agora = time.time()
            db.execute(
                "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (valor, agora, guild_id, user_id, CHAVE_ENERGIA),
            )
            db.execute(
                "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET "
                "valor = excluded.valor, atualizado_em = excluded.atualizado_em",
                (guild_id, user_id, CHAVE_REGEN, int(agora), agora),
            )
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_energia",
                f"set:{valor}:por{moderador_id}",
            )
        return {"sucesso": True, "energia": valor, "energia_max": ENERGIA_MAX}
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao definir energia: {exc}"}


def ajustar_energia(guild_id: int, user_id: int, delta: int,
                    moderador_id: int = 0) -> dict[str, Any]:
    if delta == 0:
        return {"sucesso": False, "motivo": "Informe um valor diferente de zero."}
    garantir_tabelas()
    try:
        energia = Energy(guild_id, user_id)
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            atual = energia.obter_tx(db)
            novo = max(0, min(ENERGIA_MAX, atual + int(delta)))
            agora = time.time()
            db.execute(
                "UPDATE rpg_flags SET valor = ?, atualizado_em = ? "
                "WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (novo, agora, guild_id, user_id, CHAVE_ENERGIA),
            )
            db.execute(
                "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET "
                "valor = excluded.valor, atualizado_em = excluded.atualizado_em",
                (guild_id, user_id, CHAVE_REGEN, int(agora), agora),
            )
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_energia",
                f"{delta:+d}:por{moderador_id}",
            )
        return {
            "sucesso": True,
            "energia": novo,
            "anterior": atual,
            "energia_max": ENERGIA_MAX,
            "delta": int(delta),
        }
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao ajustar energia: {exc}"}


def resolver_item(nome: str) -> dict[str, Any]:
    """Resolve um item do catálogo por nome, key ou alias."""
    market = MarketV2(None, 0, 0)
    res = market.resolver_item(nome)
    if res["status"] == "ok":
        item = res["item"]
        return {"sucesso": True, "key": item.key, "nome": item.nome}
    if res["status"] == "ambiguo":
        return {
            "sucesso": False,
            "motivo": "Há mais de um item com esse nome.",
            "opcoes": [i.nome for i in res["opcoes"]],
        }
    return {"sucesso": False, "motivo": "Item não encontrado no catálogo."}


def dar_item(guild_id: int, user_id: int, item: str, quantidade: int = 1,
             moderador_id: int = 0) -> dict[str, Any]:
    if quantidade <= 0:
        return {"sucesso": False, "motivo": "A quantidade deve ser positiva."}
    resolvido = resolver_item(item)
    if not resolvido["sucesso"]:
        return resolvido
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            Inventario(guild_id, user_id).adicionar_tx(
                db, resolvido["key"], int(quantidade)
            )
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_item",
                f"+{quantidade} {resolvido['key']}:por{moderador_id}",
            )
        return {
            "sucesso": True,
            "key": resolvido["key"],
            "nome": resolvido["nome"],
            "quantidade": int(quantidade),
        }
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao entregar item: {exc}"}


def remover_item(guild_id: int, user_id: int, item: str, quantidade: int = 1,
                 moderador_id: int = 0) -> dict[str, Any]:
    if quantidade <= 0:
        return {"sucesso": False, "motivo": "A quantidade deve ser positiva."}
    resolvido = resolver_item(item)
    if not resolvido["sucesso"]:
        return resolvido
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            inv = Inventario(guild_id, user_id)
            if not inv.tem_tx(db, resolvido["key"], int(quantidade)):
                return {
                    "sucesso": False,
                    "motivo": f"O jogador não possui {quantidade}x {resolvido['nome']}.",
                }
            inv.remover_tx(db, resolvido["key"], int(quantidade))
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_item",
                f"-{quantidade} {resolvido['key']}:por{moderador_id}",
            )
        return {
            "sucesso": True,
            "key": resolvido["key"],
            "nome": resolvido["nome"],
            "quantidade": int(quantidade),
        }
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao remover item: {exc}"}


def limpar_combate(guild_id: int, user_id: int, moderador_id: int = 0) -> dict[str, Any]:
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            row = db.execute(
                "SELECT inimigo FROM rpg_combates WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if not row:
                return {"sucesso": False, "motivo": "O jogador não está em combate."}
            db.execute(
                "DELETE FROM rpg_combates WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            _registrar_acao_tx(
                db, guild_id, user_id, "admin_limpar_combate",
                f"{row[0]}:por{moderador_id}",
            )
        return {"sucesso": True, "inimigo": row[0]}
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao limpar combate: {exc}"}


def resetar_personagem(guild_id: int, user_id: int,
                       moderador_id: int = 0) -> dict[str, Any]:
    """Apaga apenas o progresso do RPG.

    O inventário (``ruptura_inventario``), o saldo e o XP social em
    ``user_stats`` são compartilhados com outros sistemas e **não** são
    apagados.
    """
    garantir_tabelas()
    try:
        with get_db().transacao() as db:
            if not _char_tx(db, guild_id, user_id):
                return _sem_personagem()
            tabelas = [
                "rpg_profissoes",
                "rpg_profissoes_log",
                "rpg_equipamentos",
                "rpg_combates",
                "rpg_casas",
                "rpg_conquistas",
                "rpg_localizacao",
                "rpg_descobertas",
                "rpg_mineracao_stats",
                "rpg_cooldowns",
                "rpg_acoes",
                "rpg_flags",
            ]
            removidos = {}
            for tabela in tabelas:
                cursor = db.execute(
                    f"DELETE FROM {tabela} WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
                removidos[tabela] = cursor.rowcount
            db.execute(
                "DELETE FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
        return {
            "sucesso": True,
            "removidos": removidos,
            "inventario_preservado": True,
            "saldo_preservado": True,
        }
    except Exception as exc:
        return {"sucesso": False, "motivo": f"Falha ao resetar personagem: {exc}"}
