"""Mercador do RPG Textual.

Regras centrais:
- O jogador compra pelo NOME. O ID interno (``key``) continua sendo a
  identidade real e é usado em todas as gravações.
- Nomes são comparados sem diferenciar maiúsculas, minúsculas ou acentos.
- Compras e vendas são transações atômicas no SQLite: ou tudo acontece, ou
  nada acontece. Nunca há cobrança sem entrega do item.
"""
from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from typing import Any

from .database import get_db
from .economy import obter_saldo_tx, alterar_saldo_tx
from .inventory import Inventario
from .items import CATALOGO_ITENS, obter_item
from .tools import PICARETAS, FERRAMENTAS_GERAIS, obter_picareta
from .schema import garantir_tabelas


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.casefold()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _candidatos(item) -> list[str]:
    valores = [item.nome, item.key, *item.aliases]
    return [normalizar(v) for v in valores if v]


class MarketV2:
    def __init__(self, bot, guild_id: int, user_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.inventory = Inventario(guild_id, user_id)
        garantir_tabelas()

    # ---------------- níveis e requisitos ----------------
    def _char_tx(self, db):
        return db.execute(
            "SELECT nivel, xp, regiao FROM rpg_personagem WHERE guild_id = ? AND user_id = ?",
            (self.guild_id, self.user_id),
        ).fetchone()

    def _nivel_profissao_tx(self, db, chave: str) -> int:
        row = db.execute(
            "SELECT nivel FROM rpg_profissoes WHERE guild_id = ? AND user_id = ? AND chave = ?",
            (self.guild_id, self.user_id, chave),
        ).fetchone()
        return int(row[0]) if row else 0

    def _requisitos_ok(self, item, nivel_personagem: int, profs: dict[str, int]) -> tuple[bool, str]:
        req = item.requisitos or {}
        nivel_req = int(req.get("nivel_personagem", 1) or 1)
        if nivel_personagem < nivel_req:
            return False, f"Requer nível de personagem {nivel_req} (atual: {nivel_personagem})."
        prof_req = req.get("profissao")
        if prof_req:
            nivel_prof = int(req.get("nivel_profissao", 1) or 1)
            if profs.get(prof_req, 0) < nivel_prof:
                return False, (
                    f"Requer a profissão {prof_req} no nível {nivel_prof}. "
                    f"Seu nível atual: {profs.get(prof_req, 0)}."
                )
        return True, ""

    # ---------------- busca por nome ----------------
    def resolver_item(self, nome_ou_key: str) -> dict[str, Any]:
        alvo = normalizar(nome_ou_key)
        if not alvo:
            return {"status": "nao_encontrado", "opcoes": []}

        exatos = []
        inicios = []
        contem = []
        for item in CATALOGO_ITENS.values():
            candidatos = _candidatos(item)
            if alvo in candidatos:
                exatos.append(item)
            elif any(c.startswith(alvo) for c in candidatos):
                inicios.append(item)
            elif any(alvo in c for c in candidatos):
                contem.append(item)

        for grupo in (exatos, inicios, contem):
            unicos = {i.key: i for i in grupo}
            if len(unicos) == 1:
                return {"status": "ok", "item": next(iter(unicos.values()))}
            if len(unicos) > 1:
                opcoes = sorted(unicos.values(), key=lambda i: i.nome)
                return {"status": "ambiguo", "opcoes": opcoes}

        return {"status": "nao_encontrado", "opcoes": []}

    def buscar_itens(self, busca: str) -> list:
        alvo = normalizar(busca)
        if not alvo:
            return []
        return [
            item for item in CATALOGO_ITENS.values()
            if any(alvo in c for c in _candidatos(item))
        ]

    def nomes_para_autocomplete(self, current: str = "", apenas_vendaveis: bool = True) -> list[str]:
        alvo = normalizar(current)
        itens = [
            item for item in CATALOGO_ITENS.values()
            if (item.vendavel or not apenas_vendaveis)
            and (not alvo or alvo in normalizar(item.nome) or alvo in normalizar(item.key))
        ]
        return [item.nome for item in sorted(itens, key=lambda i: (i.categoria, i.nome))][:25]

    # ---------------- catálogo ----------------
    def _nivel_mercador_tx(self, db) -> int:
        return self._nivel_profissao_tx(db, "mercador")

    def _preco_unitario(self, item, nivel_mercador: int) -> tuple[int, float]:
        desconto = min(0.15, max(0, nivel_mercador) * 0.01)
        return max(1, int(round(item.preco * (1 - desconto)))), desconto

    def _preco_venda(self, item, quantidade: int, nivel_mercador: int) -> int:
        bonus = min(0.10, max(0, nivel_mercador) * 0.01)
        return max(1, int(round(item.preco * 0.5 * (1 + bonus) * quantidade)))

    def listar_loja(self, categoria: str | None = None, busca: str | None = None) -> list[dict[str, Any]]:
        with self.db.transacao() as db:
            char = self._char_tx(db)
            nivel_personagem = int(char[0]) if char else 1
            profs = {
                row[0]: int(row[1])
                for row in db.execute(
                    "SELECT chave, nivel FROM rpg_profissoes WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.user_id),
                ).fetchall()
            }
            nivel_mercador = profs.get("mercador", 0)

            itens = []
            for item in CATALOGO_ITENS.values():
                if not item.vendavel:
                    continue
                if categoria and categoria not in ("todas", ""):
                    if item.categoria != categoria and item.tipo != categoria:
                        continue
                if busca and normalizar(busca) not in " ".join(_candidatos(item)):
                    continue
                preco, desconto = self._preco_unitario(item, nivel_mercador)
                ok, motivo = self._requisitos_ok(item, nivel_personagem, profs)
                dados = {
                    "key": item.key,
                    "nome": item.nome,
                    "descricao": item.descricao,
                    "utilidade": item.utilidade,
                    "efeito": item.efeito,
                    "tipo": item.tipo,
                    "categoria": item.categoria,
                    "raridade": item.raridade,
                    "nivel": item.nivel,
                    "preco": item.preco,
                    "preco_final": preco,
                    "desconto": desconto,
                    "requisitos": item.requisitos,
                    "disponivel": ok,
                    "motivo_indisponivel": motivo,
                }
                if item.key in PICARETAS:
                    p = PICARETAS[item.key]
                    dados["chance_coins"] = p.chance_coins
                    dados["eficiencia"] = p.eficiencia
                    dados["multiplicador_materiais"] = p.multiplicador_materiais
                itens.append(dados)
            itens.sort(key=lambda x: (x["preco"], x["nome"]))
            return itens

    def listar_picaretas(self) -> list[dict[str, Any]]:
        return self.listar_loja(categoria="picareta")

    def detalhar_item(self, nome_ou_key: str) -> dict[str, Any]:
        resolvido = self.resolver_item(nome_ou_key)
        if resolvido["status"] != "ok":
            return resolvido
        item = resolvido["item"]
        loja = {d["key"]: d for d in self.listar_loja("todas")}
        return {"status": "ok", "item": item, "dados": loja.get(item.key)}

    # ---------------- compra ----------------
    def comprar(self, item_key: str, quantidade: int = 1) -> dict[str, Any]:
        """Compra por key interna (compatibilidade). Prefira comprar_por_nome."""
        return self._comprar_key(item_key, quantidade)

    def comprar_por_nome(self, nome: str, quantidade: int = 1) -> dict[str, Any]:
        resolvido = self.resolver_item(nome)
        if resolvido["status"] == "ambiguo":
            return {
                "sucesso": False,
                "status": "ambiguo",
                "motivo": "Há mais de um item com esse nome. Use um nome mais específico.",
                "opcoes": [i.nome for i in resolvido["opcoes"]],
            }
        if resolvido["status"] != "ok":
            return {
                "sucesso": False,
                "status": "nao_encontrado",
                "motivo": "Item não encontrado no mercador.",
                "opcoes": [],
            }
        return self._comprar_key(resolvido["item"].key, quantidade)

    def _comprar_key(self, item_key: str, quantidade: int = 1) -> dict[str, Any]:
        if quantidade <= 0:
            return {"sucesso": False, "status": "erro", "motivo": "Quantidade inválida."}
        if quantidade > 99:
            return {"sucesso": False, "status": "erro", "motivo": "Quantidade máxima por compra: 99."}

        item = obter_item(item_key)
        if not item:
            return {"sucesso": False, "status": "nao_encontrado", "motivo": "Item não encontrado."}
        if not item.vendavel:
            return {"sucesso": False, "status": "erro", "motivo": "Este item não está à venda."}

        try:
            with self.db.transacao() as db:
                char = self._char_tx(db)
                if not char:
                    return {"sucesso": False, "status": "erro", "motivo": "Crie seu personagem com /rpg primeiro."}
                nivel_personagem = int(char[0])
                profs = {
                    row[0]: int(row[1])
                    for row in db.execute(
                        "SELECT chave, nivel FROM rpg_profissoes WHERE guild_id = ? AND user_id = ?",
                        (self.guild_id, self.user_id),
                    ).fetchall()
                }
                ok, motivo = self._requisitos_ok(item, nivel_personagem, profs)
                if not ok:
                    return {"sucesso": False, "status": "requisito", "motivo": motivo}

                if item.unico and self.inventory.tem_tx(db, item.key, 1):
                    return {"sucesso": False, "status": "erro", "motivo": "Você já possui este item único."}

                nivel_mercador = profs.get("mercador", 0)
                preco_unitario, desconto = self._preco_unitario(item, nivel_mercador)
                preco_total = preco_unitario * quantidade
                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)
                if saldo < preco_total:
                    faltam = preco_total - saldo
                    return {
                        "sucesso": False,
                        "status": "saldo",
                        "motivo": f"Abysmus insuficiente. Faltam {faltam:,} (saldo: {saldo:,}).",
                        "saldo": saldo,
                        "preco": preco_total,
                        "faltam": faltam,
                    }

                # Débito, item e registro na MESMA transação.
                alterar_saldo_tx(db, self.guild_id, self.user_id, -preco_total)
                self.inventory.adicionar_tx(db, item.key, quantidade)
                agora = time.time()
                db.execute(
                    "INSERT INTO rpg_transacoes "
                    "(guild_id, user_id, tipo, item_key, quantidade, preco, status, criado_em) "
                    "VALUES (?, ?, 'compra', ?, ?, ?, 'concluida', ?)",
                    (self.guild_id, self.user_id, item.key, quantidade, preco_total, agora),
                )
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'comprar', ?, ?)",
                    (self.guild_id, self.user_id, f"{item.key}x{quantidade}:{preco_total}", agora),
                )
                saldo_final = obter_saldo_tx(db, self.guild_id, self.user_id)

            return {
                "sucesso": True,
                "status": "ok",
                "item": item.key,
                "item_nome": item.nome,
                "quantidade": quantidade,
                "preco": preco_total,
                "preco_unitario": preco_unitario,
                "desconto": desconto,
                "saldo": saldo_final,
                "utilidade": item.utilidade,
                "efeito": item.efeito,
            }
        except (sqlite3.Error, ValueError) as exc:
            return {"sucesso": False, "status": "erro", "motivo": f"Transação cancelada: {exc}"}

    # ---------------- venda ----------------
    def vender(self, item_key: str, quantidade: int = 1) -> dict[str, Any]:
        return self._vender_key(item_key, quantidade)

    def vender_por_nome(self, nome: str, quantidade: int = 1) -> dict[str, Any]:
        resolvido = self.resolver_item(nome)
        if resolvido["status"] == "ambiguo":
            return {
                "sucesso": False,
                "status": "ambiguo",
                "motivo": "Há mais de um item com esse nome.",
                "opcoes": [i.nome for i in resolvido["opcoes"]],
            }
        if resolvido["status"] != "ok":
            return {"sucesso": False, "status": "nao_encontrado", "motivo": "Item não encontrado."}
        return self._vender_key(resolvido["item"].key, quantidade)

    def _vender_key(self, item_key: str, quantidade: int = 1) -> dict[str, Any]:
        if quantidade <= 0:
            return {"sucesso": False, "status": "erro", "motivo": "Quantidade inválida."}
        item = obter_item(item_key)
        if not item or not item.vendavel:
            return {"sucesso": False, "status": "erro", "motivo": "Este item não pode ser vendido."}

        try:
            with self.db.transacao() as db:
                if not self.inventory.tem_tx(db, item_key, quantidade):
                    return {"sucesso": False, "status": "erro", "motivo": "Item insuficiente na mochila."}
                nivel_mercador = self._nivel_mercador_tx(db)
                recebido = self._preco_venda(item, quantidade, nivel_mercador)
                self.inventory.remover_tx(db, item_key, quantidade)
                alterar_saldo_tx(db, self.guild_id, self.user_id, recebido)

                # Se vendeu a última picareta equipada, remove o equipamento.
                if item_key in PICARETAS:
                    restante = db.execute(
                        "SELECT quantidade FROM ruptura_inventario WHERE guild_id = ? AND user_id = ? AND item_key = ?",
                        (self.guild_id, self.user_id, item_key),
                    ).fetchone()
                    if not restante:
                        db.execute(
                            "DELETE FROM rpg_equipamentos WHERE guild_id = ? AND user_id = ? AND slot = 'picareta' AND item_key = ?",
                            (self.guild_id, self.user_id, item_key),
                        )
                agora = time.time()
                db.execute(
                    "INSERT INTO rpg_transacoes "
                    "(guild_id, user_id, tipo, item_key, quantidade, preco, status, criado_em) "
                    "VALUES (?, ?, 'venda', ?, ?, ?, 'concluida', ?)",
                    (self.guild_id, self.user_id, item_key, quantidade, recebido, agora),
                )
                db.execute(
                    "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                    "VALUES (?, ?, 'vender', ?, ?)",
                    (self.guild_id, self.user_id, f"{item_key}x{quantidade}:{recebido}", agora),
                )
                saldo = obter_saldo_tx(db, self.guild_id, self.user_id)
            return {
                "sucesso": True,
                "status": "ok",
                "item": item.key,
                "item_nome": item.nome,
                "quantidade": quantidade,
                "recebido": recebido,
                "saldo": saldo,
            }
        except (sqlite3.Error, ValueError) as exc:
            return {"sucesso": False, "status": "erro", "motivo": f"Transação cancelada: {exc}"}

    # ---------------- equipamentos ----------------
    def equipar_picareta(self, picareta: str) -> dict[str, Any]:
        resolvido = self.resolver_item(picareta)
        if resolvido["status"] != "ok" or resolvido["item"].key not in PICARETAS:
            return {"sucesso": False, "motivo": "Não é uma picareta válida."}
        key = resolvido["item"].key
        with self.db.transacao() as db:
            if not self.inventory.tem_tx(db, key, 1):
                return {"sucesso": False, "motivo": "Você não possui esta picareta."}
            db.execute(
                "INSERT INTO rpg_equipamentos (guild_id, user_id, slot, item_key) "
                "VALUES (?, ?, 'picareta', ?) "
                "ON CONFLICT(guild_id, user_id, slot) DO UPDATE SET item_key = excluded.item_key",
                (self.guild_id, self.user_id, key),
            )
            db.execute(
                "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                "VALUES (?, ?, 'equipar_picareta', ?, ?)",
                (self.guild_id, self.user_id, key, time.time()),
            )
        p = obter_picareta(key)
        return {"sucesso": True, "picareta": key, "nome": p.nome, "nivel": p.nivel, "chance_coins": p.chance_coins}

    def obter_picareta_equipada(self) -> str | None:
        """Picareta equipada; se não houver, a melhor picareta possuída."""
        with self.db.transacao() as db:
            row = db.execute(
                "SELECT item_key FROM rpg_equipamentos WHERE guild_id = ? AND user_id = ? AND slot = 'picareta'",
                (self.guild_id, self.user_id),
            ).fetchone()
            inv = self.inventory.obter_tx(db)
            if row:
                key = row[0]
                if key in PICARETAS and inv.get(key, 0) > 0:
                    return key
            possuidas = [(PICARETAS[k].nivel, k) for k in PICARETAS if inv.get(k, 0) > 0]
            if not possuidas:
                return None
            return max(possuidas)[1]

    def picareta_em_uso(self) -> dict[str, Any] | None:
        key = self.obter_picareta_equipada()
        if not key:
            return None
        p = PICARETAS[key]
        with self.db.transacao() as db:
            row = db.execute(
                "SELECT item_key FROM rpg_equipamentos WHERE guild_id = ? AND user_id = ? AND slot = 'picareta'",
                (self.guild_id, self.user_id),
            ).fetchone()
        origem = "equipada" if row and row[0] == key else "inventário"
        return {"key": key, "ferramenta": p, "origem": origem}

    def garantir_picareta_inicial(self) -> str | None:
        """Entrega uma Picareta de Madeira uma única vez, se não houver nenhuma."""
        with self.db.transacao() as db:
            inv = self.inventory.obter_tx(db)
            if any(inv.get(k, 0) > 0 for k in PICARETAS):
                db.execute(
                    "INSERT OR IGNORE INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                    "VALUES (?, ?, 'picareta_inicial', 1, ?)",
                    (self.guild_id, self.user_id, time.time()),
                )
                return None
            flag = db.execute(
                "SELECT valor FROM rpg_flags WHERE guild_id = ? AND user_id = ? AND chave = 'picareta_inicial'",
                (self.guild_id, self.user_id),
            ).fetchone()
            if flag and int(flag[0]) > 0:
                return None
            self.inventory.adicionar_tx(db, "picareta_madeira", 1)
            db.execute(
                "INSERT INTO rpg_equipamentos (guild_id, user_id, slot, item_key) "
                "VALUES (?, ?, 'picareta', 'picareta_madeira') "
                "ON CONFLICT(guild_id, user_id, slot) DO UPDATE SET item_key = excluded.item_key",
                (self.guild_id, self.user_id),
            )
            db.execute(
                "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                "VALUES (?, ?, 'picareta_inicial', 1, ?) "
                "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET valor = 1, atualizado_em = excluded.atualizado_em",
                (self.guild_id, self.user_id, time.time()),
            )
            db.execute(
                "INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) "
                "VALUES (?, ?, 'picareta_inicial', 'picareta_madeira', ?)",
                (self.guild_id, self.user_id, time.time()),
            )
            return "picareta_madeira"

    def historico(self, limite: int = 10) -> list[dict[str, Any]]:
        with self.db.transacao() as db:
            rows = db.execute(
                "SELECT tipo, item_key, quantidade, preco, status, criado_em "
                "FROM rpg_transacoes WHERE guild_id = ? AND user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (self.guild_id, self.user_id, max(1, min(50, limite))),
            ).fetchall()
            return [dict(r) for r in rows]
