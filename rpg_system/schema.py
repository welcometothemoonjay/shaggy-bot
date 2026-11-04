"""Migrações aditivas do RPG Textual.

Todas as tabelas novas usam CREATE TABLE IF NOT EXISTS, portanto rodar este
módulo várias vezes é seguro e nunca apaga dados existentes.
"""
from __future__ import annotations

import time
from pathlib import Path

from .database import caminho_banco

_migrados: set[str] = set()


def garantir_tabelas(db_path: Path | str | None = None) -> None:
    """Cria as tabelas auxiliares usadas pelos sistemas novos."""
    from .database import RPGDatabase

    caminho = str(Path(db_path) if db_path else caminho_banco())
    if caminho in _migrados:
        return

    db = RPGDatabase(caminho)
    with db.transacao() as conn:
        # Tabelas base do RPG. CREATE TABLE IF NOT EXISTS mantém bancos
        # existentes intactos e permite criar um banco limpo em testes.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_personagem (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                classe_key TEXT NOT NULL,
                nivel INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                vida INTEGER NOT NULL DEFAULT 0,
                reputacao INTEGER NOT NULL DEFAULT 0,
                regiao TEXT NOT NULL DEFAULT 'dakor',
                profissao TEXT NOT NULL DEFAULT 'explorador',
                titulos TEXT NOT NULL DEFAULT '[]',
                titulo_ativo TEXT NOT NULL DEFAULT '',
                criado_em REAL NOT NULL,
                atualizado_em REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_profissoes (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chave TEXT NOT NULL,
                nivel INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                atualizado_em REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, chave)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_equipamentos (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                slot TEXT NOT NULL,
                item_key TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, slot)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_acoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                detalhe TEXT NOT NULL DEFAULT '',
                criado_em REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rpg_acoes_usuario
            ON rpg_acoes (guild_id, user_id, id DESC)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_cooldowns (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chave TEXT NOT NULL,
                expira_em REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, chave)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_regioes (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                regiao TEXT NOT NULL,
                descoberta_em REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, regiao)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ruptura_inventario (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, item_key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 0,
                coins INTEGER NOT NULL DEFAULT 0,
                last_xp REAL NOT NULL DEFAULT 0,
                highest_rewarded_level INTEGER NOT NULL DEFAULT 0,
                last_daily TEXT NOT NULL DEFAULT '',
                daily_streak INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_contadores (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                dia TEXT NOT NULL,
                chave TEXT NOT NULL,
                valor INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, dia, chave)
            )
        """)

        # Flags simples por jogador (energia, picareta inicial, etc.).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_flags (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chave TEXT NOT NULL,
                valor INTEGER NOT NULL DEFAULT 0,
                atualizado_em REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id, chave)
            )
        """)

        # Localização atual e descobertas. Não usamos rpg_contadores porque
        # seus valores são INTEGER e a chave inclui o dia.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_localizacao (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                local_key TEXT NOT NULL,
                atualizado_em REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_descobertas (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                local_key TEXT NOT NULL,
                descoberta_em REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, local_key)
            )
        """)

        # Estatísticas de mineração usadas por conquistas e objetivos.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_mineracao_stats (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                total_mineracoes INTEGER NOT NULL DEFAULT 0,
                total_materiais INTEGER NOT NULL DEFAULT 0,
                coins_total INTEGER NOT NULL DEFAULT 0,
                maior_tier INTEGER NOT NULL DEFAULT 0,
                atualizado_em REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Ledger de compras/vendas. A compra em si já é atômica; o ledger
        # serve para auditoria e para o jogador consultar o histórico.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_transacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                tipo TEXT NOT NULL,
                item_key TEXT NOT NULL,
                quantidade INTEGER NOT NULL,
                preco INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'concluida',
                criado_em REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rpg_transacoes_user
            ON rpg_transacoes (guild_id, user_id, id DESC)
        """)

        # Cache persistente das descrições do OpenRouter. A chave é um hash
        # do contexto; descrições não são geradas a cada abertura do mercado
        # nem a cada exploração com o mesmo contexto.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_narrativas (
                cache_key TEXT PRIMARY KEY,
                local_key TEXT NOT NULL DEFAULT '',
                descricao TEXT NOT NULL,
                fonte TEXT NOT NULL DEFAULT 'openrouter',
                criado_em REAL NOT NULL
            )
        """)

        # Casas (substitui o uso de rpg_contadores, que era por dia).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_casas (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'tenda',
                nivel INTEGER NOT NULL DEFAULT 1,
                criado_em REAL NOT NULL DEFAULT 0,
                atualizado_em REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # MariaDB/SQLite antigo: garante a tabela de conquistas mesmo se o
        # banco for criado do zero em testes.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_conquistas (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chave TEXT NOT NULL,
                desbloqueada_em REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id, chave)
            )
        """)

        # Combate por turnos. Cada jogador tem no máximo um combate ativo.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_combates (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                inimigo TEXT NOT NULL,
                pv_jogador INTEGER NOT NULL,
                pv_inimigo INTEGER NOT NULL,
                arma_key TEXT NOT NULL DEFAULT 'maos',
                turno INTEGER NOT NULL DEFAULT 1,
                furia INTEGER NOT NULL DEFAULT 0,
                criado_em REAL NOT NULL DEFAULT 0,
                atualizado_em REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        # Histórico de XP profissional (útil para auditoria e conquistas).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rpg_profissoes_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                chave TEXT NOT NULL,
                atividade TEXT NOT NULL DEFAULT 'trabalhar',
                xp INTEGER NOT NULL DEFAULT 0,
                nivel INTEGER NOT NULL DEFAULT 1,
                criado_em REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rpg_profissoes_log_user
            ON rpg_profissoes_log (guild_id, user_id, id DESC)
        """)

        # Índices que ajudam as consultas de conquistas.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rpg_acoes_user_tipo
            ON rpg_acoes (guild_id, user_id, tipo)
        """)

    _migrados.add(caminho)


def marcar_migrado_reset() -> None:
    """Só para testes: permite recriar o schema em outro caminho."""
    _migrados.clear()


def agora() -> float:
    return time.time()
