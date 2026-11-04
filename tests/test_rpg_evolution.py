"""Testes do RPG Textual evoluído.

Todos os testes usam SHAGGY_DB_PATH apontando para um diretório temporário.
Nenhum dado real de jogador é lido ou alterado.

Execução:
    .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import os
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Define o banco antes de importar qualquer módulo do RPG.
_BOOT_DIR = tempfile.mkdtemp(prefix="shaggy_rpg_boot_")
os.environ["SHAGGY_DB_PATH"] = str(Path(_BOOT_DIR) / "boot.db")

from rpg_system import admin as rpg_admin  # noqa: E402
from rpg_system.achievements_v2 import AchievementsV2  # noqa: E402
from rpg_system.ai.narrative import NarrativeAI  # noqa: E402
from rpg_system.combat import Combate  # noqa: E402
from rpg_system.constants import (  # noqa: E402
    COMBATE_ENERGIA_CUSTO,
    ENERGIA_MAX,
    ENERGIA_REGEN_INTERVALO_SEGUNDOS,
    xp_para_proximo_nivel,
)
from rpg_system.database import get_db  # noqa: E402
from rpg_system.economy import alterar_saldo_tx, obter_saldo_tx  # noqa: E402
from rpg_system.energy import Energy  # noqa: E402
from rpg_system.exploration import Exploration  # noqa: E402
from rpg_system.goals import obter_objetivos  # noqa: E402
from rpg_system.houses import Houses, TIPOS_CASA, resolver_tipo_casa  # noqa: E402
from rpg_system.inventory import Inventario  # noqa: E402
from rpg_system.items import CATALOGO_ITENS  # noqa: E402
from rpg_system.market_v2 import MarketV2, normalizar  # noqa: E402
from rpg_system.mining_v2 import MiningV2  # noqa: E402
from rpg_system.professions_v2 import PROFISSOES, ProfessionsV2  # noqa: E402
from rpg_system.progression import Progression, calcular_nivel  # noqa: E402
from rpg_system.schema import garantir_tabelas, marcar_migrado_reset  # noqa: E402
from rpg_system.tools import (  # noqa: E402
    CHANCES_COINS,
    MATERIAIS_MINERAIS,
    PICARETAS,
    validar_tabela_chances,
)

GUILD = 100
USER = 200


def _xp_para_nivel(nivel: int) -> int:
    """XP total necessário para chegar ao nível informado."""
    return sum(xp_para_proximo_nivel(n) for n in range(1, max(1, nivel)))


class _RngFixo(random.Random):
    """RNG determinístico: sem crítico, sem erro e sempre dano máximo."""

    def random(self):
        return 0.99

    def randint(self, a, b):
        return b


class BaseRPGTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="shaggy_rpg_test_")
        os.environ["SHAGGY_DB_PATH"] = str(Path(self._tmp.name) / "test.db")
        marcar_migrado_reset()
        garantir_tabelas()
        self.db_path = os.environ["SHAGGY_DB_PATH"]

    def tearDown(self):
        self._tmp.cleanup()

    # ---------------- helpers ----------------
    def criar_char(self, nome="Teste", nivel=1):
        p = Progression(GUILD, USER)
        self.assertTrue(p.criar_personagem(nome))
        if nivel > 1:
            self.definir_xp(_xp_para_nivel(nivel))
        return p.obter_personagem()

    def definir_xp(self, xp_total: int):
        with get_db().transacao() as db:
            db.execute(
                "UPDATE rpg_personagem SET xp = ?, nivel = ? WHERE guild_id = ? AND user_id = ?",
                (xp_total, calcular_nivel(xp_total)[0], GUILD, USER),
            )

    def definir_saldo(self, valor: int):
        with get_db().transacao() as db:
            obter_saldo_tx(db, GUILD, USER)
            db.execute(
                "UPDATE user_stats SET coins = ? WHERE guild_id = ? AND user_id = ?",
                (valor, GUILD, USER),
            )

    def saldo(self) -> int:
        with get_db().transacao() as db:
            return obter_saldo_tx(db, GUILD, USER)

    def energia(self) -> int:
        with get_db().transacao() as db:
            row = db.execute(
                "SELECT valor FROM rpg_flags WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                (GUILD, USER),
            ).fetchone()
            return int(row[0]) if row else 100

    def limpar_cooldown(self, chave: str):
        with get_db().transacao() as db:
            db.execute(
                "DELETE FROM rpg_cooldowns WHERE guild_id = ? AND user_id = ? AND chave = ?",
                (GUILD, USER, chave),
            )

    def adicionar_item(self, key: str, qtd: int = 1):
        Inventario(GUILD, USER).adicionar(key, qtd)


class TestConfiguracao(BaseRPGTest):
    def test_chances_das_picaretas(self):
        self.assertEqual(validar_tabela_chances(), [])
        esperado = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.75, 1.00]
        self.assertEqual(
            [PICARETAS[k].chance_coins for k in [
                "picareta_madeira", "picareta_pedra", "picareta_cobre",
                "picareta_ferro", "picareta_aco", "picareta_ouro",
                "picareta_diamante", "picareta_arcana",
                "picareta_abissal", "picareta_infernal",
            ]],
            esperado,
        )
        self.assertEqual(CHANCES_COINS[10], 1.0)
        self.assertEqual(len(PICARETAS), 10)

    def test_curva_de_nivel(self):
        self.assertEqual(calcular_nivel(0), (1, 0, 80))
        self.assertEqual(calcular_nivel(79), (1, 79, 80))
        self.assertEqual(calcular_nivel(80), (2, 0, 120))
        self.assertEqual(calcular_nivel(200), (3, 0, 160))
        self.assertEqual(calcular_nivel(360), (4, 0, 200))

    def test_catalogo_tem_descricoes_uteis(self):
        for item in CATALOGO_ITENS.values():
            self.assertTrue(item.descricao, item.key)
            self.assertTrue(item.utilidade, item.key)
            self.assertTrue(item.efeito, item.key)


class TestMercado(BaseRPGTest):
    def test_normalizacao_e_busca_por_nome(self):
        self.assertEqual(normalizar("  Picareta   de AÇO "), "picareta de aco")
        self.assertEqual(normalizar("Picareta de Ferro"), "picareta de ferro")
        self.assertEqual(normalizar("Picareta de Ferro"), normalizar("picareta de ferro"))

        self.criar_char()
        market = MarketV2(None, GUILD, USER)
        for nome in ["Picareta de Ferro", "picareta de aco", "PICARETA DE FERRO"]:
            res = market.resolver_item(nome)
            self.assertEqual(res["status"], "ok", nome)
        self.assertEqual(market.resolver_item("Picareta de Ferro")["status"], "ok")
        self.assertEqual(market.resolver_item("item que nao existe")["status"], "nao_encontrado")

        ambiguo = market.resolver_item("picareta")
        self.assertEqual(ambiguo["status"], "ambiguo")
        self.assertGreater(len(ambiguo["opcoes"]), 1)

    def test_compra_por_nome(self):
        self.criar_char(nivel=3)
        self.definir_saldo(1000)
        market = MarketV2(None, GUILD, USER)
        res = market.comprar_por_nome("Picareta de Ferro", 1)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["item"], "picareta_ferro")
        self.assertEqual(self.saldo(), 1000 - PICARETAS["picareta_ferro"].preco)
        self.assertTrue(Inventario(GUILD, USER).tem("picareta_ferro"))

    def test_compra_ambigua_nao_cobra(self):
        self.criar_char()
        self.definir_saldo(1000)
        market = MarketV2(None, GUILD, USER)
        res = market.comprar_por_nome("picareta", 1)
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["status"], "ambiguo")
        self.assertEqual(self.saldo(), 1000)
        self.assertFalse(Inventario(GUILD, USER).tem("picareta_ferro"))

    def test_saldo_insuficiente_nao_entrega(self):
        self.criar_char()
        self.definir_saldo(0)
        market = MarketV2(None, GUILD, USER)
        res = market.comprar_por_nome("Pedra", 1)
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["status"], "saldo")
        self.assertEqual(self.saldo(), 0)
        self.assertFalse(Inventario(GUILD, USER).tem("pedra"))

    def test_rollback_atomico_em_falha_de_entrega(self):
        self.criar_char()
        self.definir_saldo(1000)
        market = MarketV2(None, GUILD, USER)

        def falhar(*args, **kwargs):
            raise ValueError("falha simulada na entrega")

        market.inventory.adicionar_tx = falhar
        res = market._comprar_key("pedra", 1)
        self.assertFalse(res["sucesso"])
        self.assertEqual(self.saldo(), 1000)
        self.assertFalse(Inventario(GUILD, USER).tem("pedra"))

    def test_venda_base_50_por_cento(self):
        self.criar_char()
        self.definir_saldo(0)
        self.adicionar_item("pedra", 2)
        market = MarketV2(None, GUILD, USER)
        res = market.vender_por_nome("Pedra", 2)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["recebido"], 5)  # 5 * 0.5 * 2
        self.assertEqual(self.saldo(), 5)
        self.assertFalse(Inventario(GUILD, USER).tem("pedra", 1))


class TestMineracao(BaseRPGTest):
    def test_sem_picareta_nao_minera(self):
        self.criar_char()
        mining = MiningV2(GUILD, USER)
        res = mining.minerar()
        self.assertFalse(res["sucesso"])
        self.assertIn("picareta", res["motivo"].lower())
        self.assertEqual(self.saldo(), 0)

    def test_picareta_inicial_permite_minerar(self):
        self.criar_char()
        market = MarketV2(None, GUILD, USER)
        self.assertEqual(market.garantir_picareta_inicial(), "picareta_madeira")
        res = MiningV2(GUILD, USER).minerar(rng=random.Random(7))
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["picareta"], "picareta_madeira")
        self.assertGreaterEqual(res["total_materiais"], 1)
        self.assertLessEqual(res["chance_coins"], 0.10)

    def test_picareta_infernal_sempre_encontra_coins(self):
        self.criar_char(nivel=13)
        self.adicionar_item("picareta_infernal", 1)
        market = MarketV2(None, GUILD, USER)
        equip = market.equipar_picareta("Picareta Infernal")
        self.assertTrue(equip["sucesso"], equip)
        res = MiningV2(GUILD, USER).minerar(rng=random.Random(3))
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["picareta"], "picareta_infernal")
        self.assertTrue(res["achou_coins"])
        self.assertGreater(res["coins"], 0)

    def test_cooldown_impede_recompensa_duplicada(self):
        self.criar_char()
        MarketV2(None, GUILD, USER).garantir_picareta_inicial()
        mining = MiningV2(GUILD, USER)
        self.assertTrue(mining.minerar(rng=random.Random(1))["sucesso"])
        segunda = mining.minerar(rng=random.Random(1))
        self.assertFalse(segunda["sucesso"])
        self.assertIn("Cooldown", segunda["motivo"])

    def test_regiao_bloqueada_por_nivel(self):
        self.criar_char()
        MarketV2(None, GUILD, USER).garantir_picareta_inicial()
        res = MiningV2(GUILD, USER).minerar("abismo_umbral", rng=random.Random(1))
        self.assertFalse(res["sucesso"])
        self.assertIn("requer nível", res["motivo"].lower())

    def test_picareta_fraca_nao_extrai_material_superior(self):
        # A picareta de madeira (tier 1) só alcança materiais de tier 1.
        itens = MiningV2.sortear_materiais(1, "dakor", 0, rng=random.Random(5))
        self.assertTrue(itens)
        for key in itens:
            self.assertLessEqual(MATERIAIS_MINERAIS[key]["tier"], 1)

    def test_bonus_raro_do_minerador_nivel_10(self):
        # Com o bônus ativo, uma rolagem extra pode adicionar um material
        # raro (tier >= 4) disponível na região e na picareta.
        class RngFixo:
            def random(self):
                return 0.0

            def uniform(self, a, b):
                return 0.0

            def randint(self, a, b):
                return a

        itens = MiningV2.sortear_materiais(
            7, "picos_gelo", 0, rng=RngFixo(), bonus_raro=0.25
        )
        self.assertTrue(any(MATERIAIS_MINERAIS[k]["tier"] >= 4 for k in itens), itens)

    def test_minerador_ganha_xp_profissional(self):
        self.criar_char()
        MarketV2(None, GUILD, USER).garantir_picareta_inicial()
        profs = ProfessionsV2(GUILD, USER)
        self.assertTrue(profs.aprender("minerador")["sucesso"])
        res = MiningV2(GUILD, USER).minerar(rng=random.Random(9))
        self.assertTrue(res["sucesso"], res)
        self.assertGreater(res["xp_profissao"], 0)
        self.assertIsNotNone(res["profissao_nivel"])

    def test_energia_insuficiente(self):
        self.criar_char()
        MarketV2(None, GUILD, USER).garantir_picareta_inicial()
        with get_db().transacao() as db:
            db.execute(
                "INSERT INTO rpg_flags (guild_id, user_id, chave, valor, atualizado_em) "
                "VALUES (?, ?, 'energia', 0, ?) "
                "ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET valor = 0",
                (GUILD, USER, time.time()),
            )
        res = MiningV2(GUILD, USER).minerar(rng=random.Random(1))
        self.assertFalse(res["sucesso"])
        self.assertIn("Energia", res["motivo"])


class TestProfissoes(BaseRPGTest):
    def test_catalogo_completo_e_requisitos(self):
        self.criar_char()
        profs = ProfessionsV2(GUILD, USER)
        catalogo = profs.catalogo()
        self.assertEqual(len(catalogo), 9)
        self.assertEqual({p["key"] for p in catalogo}, set(PROFISSOES))
        mercador = next(p for p in catalogo if p["key"] == "mercador")
        self.assertEqual(mercador["estado"], "bloqueada")
        self.assertIn("personagem 2", mercador["motivo"].lower())

    def test_aprender_e_duplicidade(self):
        self.criar_char()
        profs = ProfessionsV2(GUILD, USER)
        res = profs.aprender("Minerador")
        self.assertTrue(res["sucesso"], res)
        self.assertFalse(profs.aprender("minerador")["sucesso"])
        self.assertFalse(profs.aprender("mercador")["sucesso"])  # nível insuficiente

    def test_trabalhar_e_cooldown(self):
        self.criar_char()
        profs = ProfessionsV2(GUILD, USER)
        profs.aprender("minerador")
        res = profs.trabalhar("minerador")
        self.assertTrue(res["sucesso"], res)
        self.assertGreater(res["xp_ganho"], 0)
        self.assertEqual(res["nivel"], 1)
        segundo = profs.trabalhar("minerador")
        self.assertFalse(segundo["sucesso"])
        self.assertIn("cooldown", segundo["motivo"].lower())

    def test_receita_artesao_consome_e_produz(self):
        self.criar_char(nivel=2)
        profs = ProfessionsV2(GUILD, USER)
        self.assertTrue(profs.aprender("artesao")["sucesso"])
        sem_materiais = profs.trabalhar("artesao")
        self.assertFalse(sem_materiais["sucesso"])
        self.assertIn("Faltam materiais", sem_materiais["motivo"])

        self.adicionar_item("madeira", 2)
        self.adicionar_item("pedra", 1)
        self.limpar_cooldown("trabalhar_artesao")
        res = profs.trabalhar("artesao")
        self.assertTrue(res["sucesso"], res)
        self.assertGreaterEqual(res["itens"].get("artesanato", 0), 1)
        self.assertFalse(Inventario(GUILD, USER).tem("madeira", 1))
        self.assertFalse(Inventario(GUILD, USER).tem("pedra", 1))


class TestConquistas(BaseRPGTest):
    def test_desbloqueio_unico_e_recompensa(self):
        self.criar_char()
        ach = AchievementsV2(GUILD, USER)
        novas = ach.verificar()
        self.assertTrue(any(c["chave"] == "primeiro_passo" for c in novas))
        saldo_apos_primeira = self.saldo()
        xp_apos_primeira = Progression(GUILD, USER).obter_personagem()["xp"]

        repetidas = ach.verificar()
        self.assertEqual(repetidas, [])
        self.assertEqual(self.saldo(), saldo_apos_primeira)
        self.assertEqual(Progression(GUILD, USER).obter_personagem()["xp"], xp_apos_primeira)

        with get_db().transacao() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM rpg_conquistas WHERE guild_id = ? AND user_id = ? "
                "AND chave = 'primeiro_passo'",
                (GUILD, USER),
            ).fetchone()[0]
        self.assertEqual(total, 1)

    def test_conquista_de_mineracao(self):
        self.criar_char()
        MarketV2(None, GUILD, USER).garantir_picareta_inicial()
        MiningV2(GUILD, USER).minerar(rng=random.Random(2))
        novas = AchievementsV2(GUILD, USER).verificar()
        chaves = {c["chave"] for c in novas}
        self.assertIn("primeiro_minerio", chaves)

    def test_persistencia_entre_instancias(self):
        self.criar_char()
        AchievementsV2(GUILD, USER).verificar()
        todas = AchievementsV2(GUILD, USER).obter_todas()
        passo = next(c for c in todas if c["chave"] == "primeiro_passo")
        self.assertTrue(passo["desbloqueada"])
        self.assertIsNotNone(passo["desbloqueada_em"])


class TestExploracao(BaseRPGTest):
    def test_fallback_sem_chave_e_persistencia(self):
        self.criar_char()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            exp = Exploration(None, GUILD, USER)
            res = asyncio.run(exp.explorar(rng=random.Random(4)))
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["fonte"], "fallback")
        self.assertIn(res["local"], res["descricao"])
        self.assertEqual(exp.obter_local_atual(), res["local_key"])
        self.assertIn(res["local_key"], exp.descobertas())
        self.assertIn(res["regiao_key"], exp.regioes_visitadas())

    def test_cooldown_e_regiao_bloqueada(self):
        self.criar_char()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            exp = Exploration(None, GUILD, USER)
            self.assertTrue(asyncio.run(exp.explorar(rng=random.Random(1)))["sucesso"])
            segunda = asyncio.run(exp.explorar(rng=random.Random(1)))
            self.assertFalse(segunda["sucesso"])
            self.assertIn("Cooldown", segunda["motivo"])

            bloqueada = asyncio.run(exp.explorar("costa_ambar", rng=random.Random(1)))
            self.assertFalse(bloqueada["sucesso"])
            self.assertIn("requer nível", bloqueada["motivo"].lower())

    def test_exploracao_com_narrativa_mockada(self):
        self.criar_char()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "chave-de-teste"}):
            exp = Exploration(None, GUILD, USER)
            exp.ai._request = _mock_request_ok
            res = asyncio.run(exp.explorar(rng=random.Random(2)))
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["fonte"], "openrouter")


async def _mock_request_ok(payload):
    return 200, {
        "choices": [{
            "message": {
                "content": "O vento atravessa as planícies enquanto trilhas antigas se abrem diante de você."
            }
        }]
    }


class AsyncNarrativeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="shaggy_ai_test_")
        os.environ["SHAGGY_DB_PATH"] = str(Path(self._tmp.name) / "test.db")
        marcar_migrado_reset()
        garantir_tabelas()

    def tearDown(self):
        self._tmp.cleanup()

    async def test_sem_chave_usa_fallback(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            ai = NarrativeAI()
        res = await ai.describe_location({"local": "Dakor", "bioma": "planície"})
        self.assertEqual(res["fonte"], "fallback")
        self.assertEqual(res["motivo"], "sem_chave")
        self.assertIn("Dakor", res["descricao"])

    async def test_resposta_valida_e_cache(self):
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "chave-de-teste",
            "OPENROUTER_CACHE_TTL": "3600",
        }):
            ai = NarrativeAI()
        chamadas = {"n": 0}

        async def request(payload):
            chamadas["n"] += 1
            return 200, {
                "choices": [{"message": {
                    "content": "Uma planície dourada se estende sob o céu aberto, com trilhas antigas e marcos de pedra."
                }}]
            }

        ai._request = request
        ctx = {"local_key": "planicies_dakor", "local": "Planícies de Dakor", "bioma": "planície"}
        primeira = await ai.describe_location(ctx)
        self.assertEqual(primeira["fonte"], "openrouter")
        self.assertEqual(chamadas["n"], 1)

        outra = NarrativeAI()
        outra._request = request
        segunda = await outra.describe_location(ctx)
        self.assertEqual(segunda["fonte"], "cache")
        self.assertEqual(chamadas["n"], 1)

    async def test_timeout_usa_fallback(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "chave-de-teste"}):
            ai = NarrativeAI()

        async def request(payload):
            return 0, "timeout"

        ai._request = request
        res = await ai.describe_location({"local": "Vale"})
        self.assertEqual(res["fonte"], "fallback")
        self.assertEqual(res["motivo"], "timeout")

    async def test_rate_limit_com_backoff(self):
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "chave-de-teste",
            "OPENROUTER_RETRY_DELAY": "0",
        }):
            ai = NarrativeAI()
        sequencia = [(429, "0"), (200, {"choices": [{"message": {
            "content": "A maré recua lentamente, revelando conchas e pedras molhadas na areia clara."
        }}]})]

        async def request(payload):
            return sequencia.pop(0)

        ai._request = request
        res = await ai.describe_location({"local": "Praia", "periodo": "tarde"})
        self.assertEqual(res["fonte"], "openrouter")
        self.assertEqual(sequencia, [])

    async def test_erro_http_usa_fallback(self):
        with patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "chave-de-teste",
            "OPENROUTER_RETRY_DELAY": "0",
        }):
            ai = NarrativeAI()

        async def request(payload):
            return 500, None

        ai._request = request
        res = await ai.describe_location({"local": "Caverna"})
        self.assertEqual(res["fonte"], "fallback")
        self.assertEqual(res["motivo"], "http_500")

    async def test_json_invalido_usa_fallback(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "chave-de-teste"}):
            ai = NarrativeAI()

        async def request(payload):
            return 200, "isto não é json"

        ai._request = request
        res = await ai.describe_location({"local": "Floresta"})
        self.assertEqual(res["fonte"], "fallback")
        self.assertEqual(res["motivo"], "resposta_curta")


class TestObjetivosECasa(BaseRPGTest):
    def test_objetivos_sem_personagem(self):
        objetivos = obter_objetivos(GUILD, USER)
        self.assertEqual(objetivos[0]["chave"], "criar_personagem")

    def test_objetivos_com_personagem(self):
        self.criar_char()
        MarketV2(None, GUILD, USER).garantir_picareta_inicial()
        objetivos = obter_objetivos(GUILD, USER)
        self.assertLessEqual(len(objetivos), 5)
        chaves = {o["chave"] for o in objetivos}
        self.assertIn("nivel_personagem", chaves)
        self.assertIn("proxima_picareta", chaves)
        self.assertIn("primeira_vitoria", chaves)
        self.assertTrue(all(o["titulo"] and o["descricao"] for o in objetivos))

    def test_casa_persistente_e_unica(self):
        self.criar_char()
        self.definir_saldo(1000)
        houses = Houses(None, GUILD, USER)
        self.assertIsNone(houses.obter_casa())
        res = houses.comprar_casa("tenda")
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(self.saldo(), 900)
        casa = houses.obter_casa()
        self.assertEqual(casa["tipo"], "tenda")
        self.assertEqual(casa["nivel"], 1)
        self.assertFalse(houses.comprar_casa("tenda")["sucesso"])
        self.assertTrue(houses.melhorar_casa(200)["sucesso"])
        self.assertEqual(houses.obter_casa()["nivel"], 2)
        self.assertEqual(self.saldo(), 700)

    def test_casa_sem_saldo_nao_e_criada(self):
        self.criar_char()
        self.definir_saldo(0)
        houses = Houses(None, GUILD, USER)
        res = houses.comprar_casa("tenda")
        self.assertFalse(res["sucesso"])
        self.assertIsNone(houses.obter_casa())

    def test_casa_aceita_aliases_e_preco_escalona(self):
        self.assertEqual(resolver_tipo_casa("Casa de Pedra"), "casa_pedra")
        self.assertEqual(resolver_tipo_casa("casa_pedra"), "casa_pedra")
        self.assertEqual(resolver_tipo_casa("PEDRA"), "casa_pedra")
        self.assertIsNone(resolver_tipo_casa("castelo"))

        self.criar_char()
        self.definir_saldo(5000)
        houses = Houses(None, GUILD, USER)
        res = houses.comprar_casa("pedra")
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["tipo"], "casa_pedra")
        self.assertEqual(res["preco"], TIPOS_CASA["casa_pedra"]["preco"])

        self.assertTrue(houses.melhorar_casa()["sucesso"])  # nível 1 -> 2: 200
        self.assertTrue(houses.melhorar_casa()["sucesso"])  # nível 2 -> 3: 400
        self.assertTrue(houses.melhorar_casa()["sucesso"])  # nível 3 -> 4: 600
        self.assertEqual(houses.obter_casa()["nivel"], 4)
        self.assertEqual(self.saldo(), 5000 - 1200 - 200 - 400 - 600)

    def test_casa_tipo_invalido_explica_opcoes(self):
        self.criar_char()
        self.definir_saldo(500)
        res = Houses(None, GUILD, USER).comprar_casa("castelo")
        self.assertFalse(res["sucesso"])
        self.assertIn("opcoes", res)
        self.assertEqual(set(res["opcoes"]), set(TIPOS_CASA))


class TestEnergia24h(BaseRPGTest):
    def _mover_regen(self, segundos_atras: int):
        with get_db().transacao() as db:
            db.execute(
                "UPDATE rpg_flags SET valor = ? "
                "WHERE guild_id = ? AND user_id = ? AND chave = 'energia_regen_em'",
                (int(time.time()) - segundos_atras, GUILD, USER),
            )

    def test_recarga_total_somente_apos_24h(self):
        self.criar_char()
        energy = Energy(GUILD, USER)
        self.assertEqual(energy.obter(), ENERGIA_MAX)
        self.assertTrue(energy.consumir(45))
        self.assertEqual(energy.obter(), 55)

        self._mover_regen(3600)
        self.assertEqual(energy.obter(), 55)
        self.assertFalse(energy.obter_detalhado()["recuperou"])

        self._mover_regen(ENERGIA_REGEN_INTERVALO_SEGUNDOS + 1)
        detalhe = energy.obter_detalhado()
        self.assertEqual(detalhe["valor"], ENERGIA_MAX)
        self.assertTrue(detalhe["recuperou"])
        self.assertEqual(detalhe["recuperado"], 45)
        self.assertGreaterEqual(detalhe["restante"], ENERGIA_REGEN_INTERVALO_SEGUNDOS - 5)

    def test_descanso_restaura_e_reinicia_ciclo(self):
        self.criar_char()
        energy = Energy(GUILD, USER)
        self.assertTrue(energy.consumir(70))
        self.assertEqual(energy.obter(), 30)
        self._mover_regen(90000)

        from rpg_system.activities import Activities

        res = Activities(None, GUILD, USER).descansar()
        self.assertTrue(res["sucesso"], res)
        detalhe = energy.obter_detalhado()
        self.assertEqual(detalhe["valor"], ENERGIA_MAX)
        self.assertGreaterEqual(detalhe["restante"], ENERGIA_REGEN_INTERVALO_SEGUNDOS - 5)


class TestCombate(BaseRPGTest):
    def test_configuracao_de_combate(self):
        self.assertEqual(COMBATE_ENERGIA_CUSTO, 4)
        catalogo = Combate(GUILD, USER).catalogo()
        self.assertEqual(len(catalogo), 10)
        nomes = {i["nome"] for i in catalogo}
        self.assertEqual(
            nomes,
            {
                "Goblin", "Rato Gigante", "Mímico", "Diabrete", "Esqueleto",
                "Orc", "Aranha Gigante", "Cérbero", "Troll", "Dragão Ancião",
            },
        )
        especiais = [i for i in catalogo if i["especial"]]
        self.assertEqual([i["nome"] for i in especiais], ["Cérbero"])
        niveis = sorted(i["nivel_min"] for i in catalogo)
        self.assertEqual(niveis[0], 1)
        self.assertEqual(niveis[-1], 15)
        for inimigo in catalogo:
            self.assertTrue(inimigo["descricao"], inimigo["nome"])
            self.assertTrue(inimigo["dica"], inimigo["nome"])
            self.assertGreater(inimigo["pv"], 0, inimigo["nome"])
            self.assertGreater(inimigo["xp"], 0, inimigo["nome"])

    def test_novos_inimigos_tem_aliases_e_resolvem_por_nome(self):
        self.criar_char()
        combat = Combate(GUILD, USER)
        for nome in ["Rato Gigante", "Esqueleto", "Aranha Gigante", "Troll", "Dragão Ancião"]:
            alvo = combat.resolver_inimigo(nome)
            self.assertEqual(alvo["status"], "ok", nome)
            self.assertEqual(alvo["inimigo"]["nome"], nome, nome)
        self.assertEqual(combat.resolver_inimigo("dragao")["inimigo"]["key"], "dragao")
        self.assertEqual(combat.resolver_inimigo("rato")["inimigo"]["key"], "rato_gigante")
        self.assertEqual(combat.resolver_inimigo("spider")["inimigo"]["key"], "aranha_gigante")

    def test_vitoria_concede_xp_moedas_e_limpa_estado(self):
        self.criar_char()
        rng = _RngFixo()
        combat = Combate(GUILD, USER)

        res = combat.iniciar("Goblin", rng=rng)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["estado"], "ativo")
        self.assertEqual(self.energia(), ENERGIA_MAX - COMBATE_ENERGIA_CUSTO)

        acoes = 1
        while res["estado"] == "ativo" and acoes < 20:
            res = combat.atacar(rng=rng)
            acoes += 1
            self.assertTrue(res["sucesso"], res)

        self.assertEqual(res["estado"], "vitoria")
        self.assertEqual(self.energia(), ENERGIA_MAX - acoes * COMBATE_ENERGIA_CUSTO)
        self.assertGreater(res["coins"], 0)
        self.assertEqual(self.saldo(), res["coins"])
        self.assertTrue(res["xp"]["sucesso"])
        self.assertGreater(res["xp"]["xp_total"], 0)
        self.assertEqual(combat.status()["estado"], "sem_combate")

        with get_db().transacao() as db:
            vitorias = db.execute(
                "SELECT COUNT(*) FROM rpg_acoes WHERE guild_id = ? AND user_id = ? "
                "AND tipo = 'combate_vitoria'",
                (GUILD, USER),
            ).fetchone()[0]
        self.assertEqual(vitorias, 1)

        novas = AchievementsV2(GUILD, USER).verificar()
        self.assertIn("primeira_vitoria", {c["chave"] for c in novas})

    def test_derrota_nao_perde_moedas(self):
        self.criar_char()
        self.definir_saldo(250)
        rng = _RngFixo()
        combat = Combate(GUILD, USER)
        res = combat.iniciar("Goblin", rng=rng)
        self.assertTrue(res["sucesso"], res)

        with get_db().transacao() as db:
            db.execute(
                "UPDATE rpg_combates SET pv_jogador = 1 "
                "WHERE guild_id = ? AND user_id = ?",
                (GUILD, USER),
            )

        res = combat.atacar(rng=rng)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["estado"], "derrota")
        self.assertEqual(self.saldo(), 250)
        self.assertEqual(combat.status()["estado"], "sem_combate")
        with get_db().transacao() as db:
            derrotas = db.execute(
                "SELECT COUNT(*) FROM rpg_acoes WHERE guild_id = ? AND user_id = ? "
                "AND tipo = 'combate_derrota'",
                (GUILD, USER),
            ).fetchone()[0]
        self.assertEqual(derrotas, 1)

    def test_mimico_paga_muito_dinheiro(self):
        self.criar_char(nivel=2)
        self.adicionar_item("picareta_infernal", 1)
        rng = _RngFixo()
        combat = Combate(GUILD, USER)
        res = combat.iniciar("Mímico", arma="Picareta Infernal", rng=rng)
        self.assertTrue(res["sucesso"], res)

        acoes = 1
        while res["estado"] == "ativo" and acoes < 20:
            res = combat.atacar(rng=rng)
            acoes += 1

        self.assertEqual(res["estado"], "vitoria")
        self.assertGreaterEqual(res["coins"], 80)
        self.assertLessEqual(res["coins"], 140)
        self.assertEqual(self.saldo(), res["coins"])

    def test_cerbero_exige_nivel_e_ativa_conquista_especial(self):
        self.criar_char(nivel=7)
        combat = Combate(GUILD, USER)
        res = combat.iniciar("Cérbero", rng=_RngFixo())
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["status"], "requisito")
        self.assertEqual(self.energia(), ENERGIA_MAX)
        self.assertEqual(combat.status()["estado"], "sem_combate")

        self.definir_xp(_xp_para_nivel(13))
        self.adicionar_item("picareta_infernal", 1)
        rng = _RngFixo()
        res = combat.iniciar("Cérbero", arma="Picareta Infernal", rng=rng)
        self.assertTrue(res["sucesso"], res)
        acoes = 1
        while res["estado"] == "ativo" and acoes < 20:
            res = combat.atacar(rng=rng)
            acoes += 1

        self.assertEqual(res["estado"], "vitoria")
        self.assertTrue(res["inimigo_key"] == "cerbero")
        novas = AchievementsV2(GUILD, USER).verificar()
        self.assertIn("cacador_lendas", {c["chave"] for c in novas})

    def test_arma_invalida_nao_gasta_energia_nem_altera_estado(self):
        self.criar_char()
        rng = _RngFixo()
        combat = Combate(GUILD, USER)

        res = combat.iniciar("Goblin", arma="Espada Inexistente", rng=rng)
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["status"], "nao_encontrado")
        self.assertEqual(self.energia(), ENERGIA_MAX)
        self.assertEqual(combat.status()["estado"], "sem_combate")

        res = combat.iniciar("Goblin", rng=rng)
        self.assertTrue(res["sucesso"], res)
        pv_antes = res["pv_inimigo"]
        energia_antes = self.energia()

        res = combat.atacar("Espada Inexistente", rng=rng)
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["status"], "nao_encontrado")
        self.assertEqual(self.energia(), energia_antes)
        status = combat.status()
        self.assertEqual(status["estado"], "ativo")
        self.assertEqual(status["pv_inimigo"], pv_antes)

    def test_energia_insuficiente_nao_inicia_combate(self):
        self.criar_char()
        energy = Energy(GUILD, USER)
        energy.obter()
        with get_db().transacao() as db:
            db.execute(
                "UPDATE rpg_flags SET valor = 3 "
                "WHERE guild_id = ? AND user_id = ? AND chave = 'energia'",
                (GUILD, USER),
            )

        combat = Combate(GUILD, USER)
        res = combat.iniciar("Goblin", rng=_RngFixo())
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["status"], "energia")
        self.assertEqual(self.energia(), 3)
        self.assertEqual(combat.status()["estado"], "sem_combate")

    def test_combate_persiste_entre_instancias(self):
        self.criar_char()
        rng = _RngFixo()
        combat = Combate(GUILD, USER)
        res = combat.iniciar("Goblin", rng=rng)
        self.assertEqual(res["estado"], "ativo")
        pv_inimigo = res["pv_inimigo"]

        outro = Combate(GUILD, USER)
        status = outro.status()
        self.assertEqual(status["estado"], "ativo")
        self.assertEqual(status["pv_inimigo"], pv_inimigo)

        res = outro.atacar(rng=rng)
        self.assertTrue(res["sucesso"], res)
        self.assertLess(res["pv_inimigo"], pv_inimigo)


class TestAdminRPG(BaseRPGTest):
    def test_ajustar_e_definir_moedas(self):
        self.criar_char()
        self.definir_saldo(100)
        res = rpg_admin.ajustar_moedas(GUILD, USER, 250, moderador_id=999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["saldo"], 350)
        self.assertEqual(self.saldo(), 350)

        res = rpg_admin.ajustar_moedas(GUILD, USER, -50, moderador_id=999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(self.saldo(), 300)

        res = rpg_admin.definir_moedas(GUILD, USER, 42, moderador_id=999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["anterior"], 300)
        self.assertEqual(self.saldo(), 42)

        self.assertFalse(rpg_admin.ajustar_moedas(GUILD, USER, 0)["sucesso"])
        self.assertFalse(rpg_admin.definir_moedas(GUILD, USER, -1)["sucesso"])

    def test_ajustar_e_definir_xp_recalcula_nivel(self):
        self.criar_char()
        res = rpg_admin.ajustar_xp(GUILD, USER, 100, moderador_id=999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["xp_total"], 100)
        self.assertEqual(res["nivel"], 2)

        res = rpg_admin.definir_xp(GUILD, USER, 0, moderador_id=999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["nivel"], 1)
        self.assertEqual(Progression(GUILD, USER).obter_personagem()["xp"], 0)

        self.assertFalse(rpg_admin.ajustar_xp(GUILD, USER, 0)["sucesso"])
        self.assertFalse(rpg_admin.definir_xp(GUILD, USER, -5)["sucesso"])

    def test_energia_ajustada_e_limitada_ao_maximo(self):
        self.criar_char()
        res = rpg_admin.definir_energia(GUILD, USER, 30)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(self.energia(), 30)

        res = rpg_admin.ajustar_energia(GUILD, USER, 20)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["energia"], 50)

        res = rpg_admin.ajustar_energia(GUILD, USER, 10_000)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["energia"], ENERGIA_MAX)

        res = rpg_admin.ajustar_energia(GUILD, USER, -10_000)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(res["energia"], 0)
        self.assertFalse(rpg_admin.ajustar_energia(GUILD, USER, 0)["sucesso"])

    def test_dar_e_remover_item(self):
        self.criar_char()
        inv = Inventario(GUILD, USER)
        res = rpg_admin.dar_item(GUILD, USER, "Picareta de Ferro", 2, 999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(inv.obter().get("picareta_ferro"), 2)

        res = rpg_admin.remover_item(GUILD, USER, "picareta de ferro", 1, 999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(inv.obter().get("picareta_ferro"), 1)

        res = rpg_admin.remover_item(GUILD, USER, "Picareta de Ferro", 5, 999)
        self.assertFalse(res["sucesso"])
        self.assertFalse(rpg_admin.dar_item(GUILD, USER, "item inexistente", 1)["sucesso"])

    def test_sem_personagem_nao_altera_nada(self):
        res = rpg_admin.ajustar_moedas(GUILD, USER, 10)
        self.assertFalse(res["sucesso"])
        self.assertIn("personagem", res["motivo"].lower())

    def test_limpar_combate(self):
        self.criar_char()
        combat = Combate(GUILD, USER)
        self.assertTrue(combat.iniciar("Goblin", rng=_RngFixo())["sucesso"])
        res = rpg_admin.limpar_combate(GUILD, USER, 999)
        self.assertTrue(res["sucesso"], res)
        self.assertEqual(combat.status()["estado"], "sem_combate")
        self.assertFalse(rpg_admin.limpar_combate(GUILD, USER, 999)["sucesso"])

    def test_reset_preserva_inventario_e_saldo(self):
        self.criar_char()
        self.definir_saldo(777)
        Inventario(GUILD, USER).adicionar("picareta_ferro", 1)
        Houses(None, GUILD, USER).comprar_casa("tenda")

        res = rpg_admin.resetar_personagem(GUILD, USER, 999)
        self.assertTrue(res["sucesso"], res)
        self.assertIsNone(Progression(GUILD, USER).obter_personagem())
        self.assertIsNone(Houses(None, GUILD, USER).obter_casa())
        self.assertEqual(Inventario(GUILD, USER).obter().get("picareta_ferro"), 1)
        self.assertEqual(self.saldo(), 677)

    def test_resumo_e_ranking(self):
        self.criar_char()
        self.definir_saldo(50)
        dados = rpg_admin.resumo(GUILD, USER)
        self.assertEqual(dados["saldo"], 50)
        self.assertEqual(dados["energia_max"], ENERGIA_MAX)
        self.assertEqual(dados["personagem"]["nome"], "Teste")

        ranking = rpg_admin.ranking(GUILD, 10)
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]["user_id"], USER)


class TestComandosDiscord(unittest.TestCase):
    def test_cog_tem_equipar_e_nao_tem_casa(self):
        from cogs.rpg import RPG

        class FakeBot:
            pass

        cog = RPG(FakeBot())
        comandos = cog.get_app_commands()
        nomes = {c.name for c in comandos}
        self.assertIn("equipar", nomes)
        self.assertIn("combate", nomes)
        self.assertNotIn("casa", nomes)
        self.assertEqual(len(nomes), len(comandos), "nomes de comandos duplicados")
        self.assertEqual(len(comandos), 19)
        assinaturas = {c.name: {p.name for p in c.parameters} for c in comandos}
        self.assertIn("item", assinaturas["comprar"])
        self.assertIn("item", assinaturas["vender"])
        self.assertIn("regiao", assinaturas["explorar"])
        self.assertIn("regiao", assinaturas["mineracao"])
        self.assertIn("profissao", assinaturas["profissoes"])
        self.assertIn("inimigo", assinaturas["combate"])
        self.assertIn("arma", assinaturas["combate"])

    def test_comandos_de_prefixo_do_rpg(self):
        from cogs.rpg import RPG

        class FakeBot:
            pass

        cog = RPG(FakeBot())
        prefixos = {c.name for c in cog.get_commands()}
        esperados = {
            "rpg", "mochila", "minerar", "trabalhar", "explorar", "descansar",
            "lutar", "casa", "objetivos", "rankingrpg", "conquistas", "ajudarpg",
        }
        self.assertTrue(esperados.issubset(prefixos), esperados - prefixos)
        admin = {
            "rpggive", "rpgtake", "rpgset", "rpgitem", "rpgitemremover",
            "rpgficha", "rpglimparcombate", "rpgreset",
        }
        self.assertTrue(admin.issubset(prefixos), admin - prefixos)
        aliases = {a for c in cog.get_commands() for a in c.aliases}
        self.assertIn("ficha", aliases)
        self.assertIn("combate", aliases)
        self.assertIn("rphelp", aliases)


if __name__ == "__main__":
    unittest.main()
