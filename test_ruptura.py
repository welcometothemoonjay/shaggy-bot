"""
Validador da expansão de Ruptura Temporal
=========================================

Roda sem precisar de Discord conectado:

    python -m unittest test_ruptura -v

O arquivo cobre catálogo, curva de dificuldade, janelas sazonais,
eventos dinâmicos, itens (passivos, artefatos, consumíveis e
estratégicos), mochila, inventário SQLite temporário e o filtro de
itens do PvP. Nenhum banco real é tocado: os testes de persistência
usam um DB_PATH temporário.
"""

from __future__ import annotations

import asyncio
import random
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs import ruptura as rt
from cogs import ruptura_pvp as pvp


# ------------------------------------------------------------
# Catálogo declarado pela expansão (mantém o teste legível)
# ------------------------------------------------------------

NOVAS_POR_ERA = {
    "Da'kor": (
        "Lodo Ancestral",
        "Mãe das Raízes",
        "Ceifador de Névoa",
        "Sombra do Peregrino",
        "Devorador de Ecos",
        "Aranha de Ossos",
    ),
    "Era a Vapor": (
        "Caldeireiro Possuído",
        "Boneco de Válvulas",
        "Sentinela de Latão",
        "Maquinista Cego",
        "Fornalha Ambulante",
        "Relojoeiro de Carne",
    ),
    "Futuro Distorcido": (
        "Eco do Primeiro Grito",
        "Caçador de Paradoxos",
        "Tecelã de Possibilidades",
        "Juiz do Fim",
        "Devorador de Nomes",
        "Anjo de Vidro Rachado",
    ),
}

NOVAS_SAZONAIS = {
    "Cavaleiro da Última Colheita": "colheita_de_ecos",
    "Noiva de Cinzas": "semana_dos_mortos",
}

TODAS_NOVAS = {
    nome for nomes in NOVAS_POR_ERA.values() for nome in nomes
} | set(NOVAS_SAZONAIS)

# Expansão 3: 6 mini-chefes + 6 chefes por era.
NOVOS_MINI_POR_ERA = {
    "Da'kor": (
        "Vigia da Ponte Quebrada",
        "Afiador de Ossos",
        "Coro de Afogados",
        "A Costureira de Sombras",
        "Máscara do Primeiro Rosto",
        "Contador de Ossos",
    ),
    "Era a Vapor": (
        "A Caldeira Que Respira",
        "Ladrão de Segundos",
        "Sentinela da Válvula Mestra",
        "Fundidor de Placas",
        "Aranha de Válvulas",
        "Maquinista de Cinzas",
    ),
    "Futuro Distorcido": (
        "Tecelã de Miragens",
        "Devorador de Minutos",
        "Arauto das Palavras Gastas",
        "Sombra do Instante Perdido",
        "Ponteiro Parado",
        "Fome do Amanhã",
    ),
}

NOVOS_CHEFES_POR_ERA = {
    "Da'kor": (
        "O Barqueiro de Ossos",
        "A Mãe das Máscaras",
        "O Coletor de Dívidas",
        "O Pastor de Máscaras",
        "A Viúva do Farol",
        "O Arquivista de Nomes",
    ),
    "Era a Vapor": (
        "O Engenheiro-Chefe",
        "A Fornalha Viva",
        "O Titereiro de Válvulas",
        "A Dama de Latão",
        "O Relojoeiro do Fim",
        "A Catedral de Carvão",
    ),
    "Futuro Distorcido": (
        "O Espelho do Último Dia",
        "A Fenda que Escuta",
        "O Colecionador de Futuros",
        "A Criança que Não Foi",
        "O Devorador de Conclusões",
        "A Última Testemunha",
    ),
}

TODOS_ESPECIAIS = {
    nome for nomes in (*NOVOS_MINI_POR_ERA.values(),
                       *NOVOS_CHEFES_POR_ERA.values()) for nome in nomes
}

NIVEIS_MINI = {"Da'kor": 3, "Era a Vapor": 6, "Futuro Distorcido": 9}
NIVEIS_CHEFE = {
    "Da'kor": {5, 10},
    "Era a Vapor": {10, 15, 20},
    "Futuro Distorcido": {15, 20, 25},
}

# Efeitos esperados por tipo, conforme a expansão aprovada.
QTD_ITENS = {"passivo": 9, "consumivel": 8, "artefato": 5, "estrategico": 5}


def novo_run(classe: str = "guardiao", **campos) -> rt.RunState:
    """RunState mínimo, sem build e sem tocar no banco."""
    spec = rt.CLASSES[classe]
    dados = dict(
        user_id=1,
        guild_id=2,
        user_nome="Teste",
        classe=spec,
        classe_key=classe,
        vida=spec.vida,
        vida_maxima=spec.vida,
        ataque=spec.ataque,
        defesa=spec.defesa,
    )
    dados.update(campos)
    return rt.RunState(**dados)


def inimigo_dummy(nivel: int = 5, vida: int = 500,
                  defesa: int = 0) -> rt.EnemyState:
    """Criatura controlada (sem habilidade) para testes de dano."""
    spec = rt.EnemySpec(
        "Alvo de Teste", "Da'kor", 1, vida, 10, defesa, 1, 0, "",
        "Criatura criada apenas para os testes.",
    )
    return rt.EnemyState(
        spec=spec, nivel=nivel,
        vida=vida, vida_maxima=vida, ataque=10, defesa=defesa,
    )


class TestCatalogo(unittest.TestCase):
    def test_validadores_do_jogo(self):
        rt.validar_catalogos()
        rt.validar_arvores()

    def test_expansao_tem_20_criaturas(self):
        nomes = [c.nome for c in rt.CRIATURAS]
        self.assertEqual(len(nomes), len(set(nomes)),
                         "Há criaturas com nome duplicado.")
        presentes = [c for c in rt.CRIATURAS if c.nome in TODAS_NOVAS]
        self.assertEqual(len(presentes), 20)
        self.assertEqual(len(TODAS_NOVAS), 20)

    def test_seis_criaturas_normais_por_era(self):
        for era, nomes in NOVAS_POR_ERA.items():
            criaturas = [c for c in rt.CRIATURAS if c.nome in nomes]
            self.assertEqual(len(criaturas), 6, era)
            for c in criaturas:
                self.assertEqual(c.era, era)
                self.assertEqual(c.categoria, "normal",
                                 f"{c.nome} deveria ser normal")
                self.assertEqual(c.evento, "",
                                 f"{c.nome} não deveria ser sazonal")
                self.assertGreaterEqual(c.nivel_minimo, 1)
                self.assertTrue(c.descricao.strip())

    def test_duas_criaturas_sazonais(self):
        for nome, evento in NOVAS_SAZONAIS.items():
            c = next(c for c in rt.CRIATURAS if c.nome == nome)
            self.assertEqual(c.evento, evento)
            self.assertEqual(c.categoria, "normal")
            self.assertIn(evento, rt.EVENTOS)

    def test_habilidades_sao_exclusivas(self):
        novas = [c for c in rt.CRIATURAS if c.nome in TODAS_NOVAS]
        chaves = [c.habilidade for c in novas]
        self.assertEqual(len(chaves), len(set(chaves)),
                         "Duas criaturas novas compartilham habilidade.")
        for chave in chaves:
            self.assertIn(chave, rt.HABILIDADES)
            hab = rt.HABILIDADES[chave]
            self.assertTrue(hab.nome)
            self.assertTrue(hab.descricao)
            self.assertNotEqual(hab.nome, "Nenhuma")

    def test_curva_nao_aumenta_dificuldade(self):
        """No nível de entrada, nenhuma criatura nova supera as antigas.

        O cálculo replica a escala de criar_inimigo() para categoria
        normal (vida +4/nível, ataque +1/nível).
        """
        def escala(c, nivel):
            extra = max(0, nivel - c.nivel_minimo)
            return (c.vida + extra * 4,
                    c.ataque + extra,
                    c.defesa + extra // 4)

        for c in (c for c in rt.CRIATURAS if c.nome in TODAS_NOVAS):
            antigas = [
                o for o in rt.CRIATURAS
                if o.era == c.era
                and o.categoria == "normal"
                and not o.evento
                and o.nome not in TODAS_NOVAS
            ]
            self.assertTrue(antigas, f"Sem referência antiga para {c.era}")
            ref = [escala(o, c.nivel_minimo) for o in antigas]
            max_vida = max(v[0] for v in ref)
            max_ataque = max(v[1] for v in ref)
            nova = escala(c, c.nivel_minimo)
            self.assertLessEqual(
                nova[0], int(max_vida * 1.25),
                f"{c.nome} tem vida acima da curva da era.")
            self.assertLessEqual(
                nova[1], int(max_ataque * 1.05),
                f"{c.nome} tem ataque acima da curva da era.")

    def test_categorias_especiais_intactas(self):
        categorias = {c.categoria for c in rt.CRIATURAS}
        self.assertTrue({"normal", "mini_chefe", "chefe", "deus"}
                        <= categorias)
        # A Expansão 2 (criaturas normais) não criou chefes nem deuses.
        for c in rt.CRIATURAS:
            if c.nome in TODAS_NOVAS:
                self.assertNotIn(c.categoria, ("mini_chefe", "chefe", "deus"))

    def test_expansao3_tem_seis_mini_e_seis_chefes_por_era(self):
        self.assertEqual(len(TODOS_ESPECIAIS), 36)
        nomes = [c.nome for c in rt.CRIATURAS]
        self.assertEqual(len(nomes), len(set(nomes)))
        for era, mini_nomes in NOVOS_MINI_POR_ERA.items():
            mini = [c for c in rt.CRIATURAS if c.nome in mini_nomes]
            self.assertEqual(len(mini), 6, era)
            self.assertEqual({c.categoria for c in mini}, {"mini_chefe"})
            self.assertEqual({c.era for c in mini}, {era})

        for era, chefe_nomes in NOVOS_CHEFES_POR_ERA.items():
            chefes = [c for c in rt.CRIATURAS if c.nome in chefe_nomes]
            self.assertEqual(len(chefes), 6, era)
            self.assertEqual({c.categoria for c in chefes}, {"chefe"})
            self.assertEqual({c.era for c in chefes}, {era})

        self.assertFalse(TODOS_ESPECIAIS & TODAS_NOVAS)

    def test_expansao3_usa_niveis_e_habilidades_exclusivas(self):
        for era, nomes in NOVOS_MINI_POR_ERA.items():
            for c in (c for c in rt.CRIATURAS if c.nome in nomes):
                self.assertEqual(c.nivel_minimo, NIVEIS_MINI[era])
                self.assertEqual(c.evento, "")
                self.assertTrue(c.descricao.strip())

        for era, nomes in NOVOS_CHEFES_POR_ERA.items():
            for c in (c for c in rt.CRIATURAS if c.nome in nomes):
                self.assertIn(c.nivel_minimo, NIVEIS_CHEFE[era])
                self.assertEqual(c.evento, "")
                self.assertTrue(c.descricao.strip())

        chaves = [c.habilidade for c in rt.CRIATURAS
                  if c.nome in TODOS_ESPECIAIS]
        self.assertEqual(len(chaves), 36)
        self.assertEqual(len(chaves), len(set(chaves)))
        for chave in chaves:
            self.assertIn(chave, rt.HABILIDADES)
            hab = rt.HABILIDADES[chave]
            self.assertIsNot(type(hab), rt.HabilidadeInimiga)
            self.assertTrue(hab.nome.strip())
            self.assertTrue(hab.descricao.strip())

    def test_expansao3_respeita_faixas_de_atributos(self):
        for c in (c for c in rt.CRIATURAS if c.nome in TODOS_ESPECIAIS):
            if c.categoria == "mini_chefe":
                self.assertLessEqual(58, c.vida)
                self.assertLessEqual(c.vida, 100)
                self.assertLessEqual(10, c.ataque)
                self.assertLessEqual(c.ataque, 15)
                self.assertLessEqual(42, c.xp)
                self.assertLessEqual(c.xp, 84)
            else:
                self.assertLessEqual(100, c.vida)
                self.assertLessEqual(c.vida, 245)
                self.assertLessEqual(13, c.ataque)
                self.assertLessEqual(c.ataque, 20)
                self.assertLessEqual(100, c.xp)
                self.assertLessEqual(c.xp, 280)
            self.assertLessEqual(0, c.defesa)
            self.assertLessEqual(c.defesa, 6)
            self.assertGreater(c.abysmus, 0)


class TestEventos(unittest.TestCase):
    def test_janelas_sazonais(self):
        casos = (
            ("halloween", date(2026, 10, 20), True),
            ("halloween", date(2026, 11, 2), True),
            ("halloween", date(2026, 11, 3), False),
            ("natal", date(2026, 12, 15), True),
            ("natal", date(2026, 1, 5), True),
            ("natal", date(2026, 1, 6), False),
            ("equinocio_de_cinzas", date(2026, 3, 18), True),
            ("equinocio_de_cinzas", date(2026, 9, 25), True),
            ("equinocio_de_cinzas", date(2026, 7, 1), False),
            ("solsticio_rachado", date(2026, 6, 18), True),
            ("solsticio_rachado", date(2026, 6, 26), False),
            ("colheita_de_ecos", date(2026, 4, 10), True),
            ("colheita_de_ecos", date(2026, 4, 30), True),
            ("colheita_de_ecos", date(2026, 5, 1), False),
            ("semana_dos_mortos", date(2026, 11, 3), True),
            ("semana_dos_mortos", date(2026, 11, 10), True),
            ("semana_dos_mortos", date(2026, 11, 11), False),
        )
        for chave, hoje, esperado in casos:
            with self.subTest(chave=chave, hoje=hoje):
                self.assertEqual(
                    rt.evento_disponivel(rt.EVENTOS[chave], hoje), esperado)

    def test_eventos_base_sempre_disponiveis(self):
        for chave in ("lua_sangrenta", "mare_de_fuligem", "noite_alien"):
            self.assertTrue(rt.evento_disponivel(
                rt.EVENTOS[chave], date(2026, 7, 1)))

    def test_eventos_dinamicos_tem_escolhas(self):
        dinamicos = [e for e in rt.EVENTOS.values() if e.dinamico]
        self.assertEqual(len(dinamicos), 3)
        for evento in dinamicos:
            self.assertGreaterEqual(len(evento.escolhas), 2)
            self.assertIn("escolha", rt.texto_evento(evento))
            for escolha in evento.escolhas:
                self.assertTrue(escolha.rotulo)
                self.assertTrue(escolha.descricao)
                self.assertTrue(callable(escolha.aplicar))

    def test_dinamico_so_entra_no_nivel_4(self):
        run = novo_run(nivel=3)
        with patch.object(rt, "EVENTOS",
                          {"voz_na_nevoa": rt.EVENTOS["voz_na_nevoa"]}), \
                patch.object(rt.random, "shuffle", lambda _x: None), \
                patch.object(rt.random, "random", return_value=0.0):
            self.assertIsNone(rt.sortear_evento(run))
            run.nivel = 4
            evento = rt.sortear_evento(run)
            self.assertIsNotNone(evento)
            self.assertEqual(evento.chave, "voz_na_nevoa")
            self.assertIn("voz_na_nevoa", run.eventos_dinamicos)
            # Cada dinâmico aparece no máximo uma vez por run.
            self.assertIsNone(rt.sortear_evento(run))

    def test_escolhas_aplicam_efeitos(self):
        run = novo_run(vida=40, vida_maxima=100)
        mensagem = rt._escolha_mercador_agua(run)
        self.assertIn("recupera", mensagem)
        self.assertGreater(run.vida, 40)

        run = novo_run(vida=40, vida_maxima=100, ataque=10)
        rt._escolha_mercador_memoria(run)
        self.assertEqual(run.ataque, 12)
        self.assertEqual(run.vida_maxima, 94)
        self.assertLessEqual(run.vida, run.vida_maxima)

        run = novo_run(foco=1)
        rt._escolha_fenda_atravessar(run)
        self.assertGreater(run.foco, 1)
        run = novo_run(vida=40, vida_maxima=100)
        rt._escolha_fenda_contornar(run)
        self.assertGreater(run.vida, 40)
        self.assertGreaterEqual(run.barreira, 8)

        run = novo_run(ataque=10)
        with patch.object(rt.random, "random", return_value=0.1):
            rt._escolha_voz_responder(run)
        self.assertEqual(run.ataque, 13)

        run = novo_run(vida=50, vida_maxima=100)
        with patch.object(rt.random, "random", return_value=0.9):
            rt._escolha_voz_responder(run)
        self.assertLess(run.vida, 50)

        run = novo_run(defesa=2)
        rt._escolha_voz_silenciar(run)
        self.assertEqual(run.defesa, 4)


class TestItens(unittest.TestCase):
    def test_quantidade_por_tipo(self):
        contagem = {tipo: 0 for tipo in rt.TIPOS_ITEM}
        for item in rt.ITENS.values():
            contagem[item.tipo] += 1
        self.assertEqual(contagem, QTD_ITENS)

    def test_validacao_de_registro(self):
        base = dict(nome="X", descricao="X", efeito="ataque", poder=1)
        with self.assertRaises(ValueError):
            rt.registrar_item("__teste_tipo__", rt.ItemSpec(
                **base, tipo="inexistente"))
        with self.assertRaises(ValueError):
            rt.registrar_item("__teste_passivo__", rt.ItemSpec(
                **{**base, "efeito": "inexistente"}))
        with self.assertRaises(ValueError):
            rt.registrar_item("__teste_artefato__", rt.ItemSpec(
                **base, tipo="artefato", uso="run", efeito_factory=None))
        with self.assertRaises(ValueError):
            rt.registrar_item("__teste_consumivel__", rt.ItemSpec(
                **base, tipo="consumivel", uso="combate", aplicar=None))
        with self.assertRaises(ValueError):
            rt.registrar_item("__teste_uso__", rt.ItemSpec(
                **base, tipo="passivo", uso="combate"))

    def test_tipos_equipaveis_e_de_combate(self):
        for chave, item in rt.ITENS.items():
            with self.subTest(item=chave):
                if item.tipo in ("consumivel", "estrategico"):
                    self.assertEqual(item.uso, "combate")
                    self.assertTrue(callable(item.aplicar))
                    self.assertTrue(item.gasta_turno)
                elif item.tipo == "artefato":
                    self.assertEqual(item.uso, "run")
                    self.assertTrue(callable(item.efeito_factory))
                    instancia = item.efeito_factory()
                    self.assertIsInstance(instancia, rt.Efeito)
                    self.assertTrue(instancia.nome)
                else:
                    self.assertEqual(item.uso, "run")
                    self.assertIn(item.efeito, rt.EFEITOS_ITEM)

    def test_estrategicos_tem_limite_por_run(self):
        for chave, item in rt.ITENS.items():
            if item.tipo == "estrategico":
                self.assertEqual(item.limite_run, 1, chave)

    def test_passivo_e_artefato_equipam(self):
        run = novo_run(ataque=10)
        self.assertTrue(rt.equipar_item_da_run(run, "lamina_rachada"))
        self.assertEqual(run.ataque, 14)

        antes = len(run.itens_efeitos)
        self.assertTrue(rt.equipar_item_da_run(run, "olho_de_vidro"))
        self.assertEqual(len(run.itens_efeitos), antes + 1)
        self.assertIsInstance(run.itens_efeitos[-1], rt.OlhoDeVidro)
        self.assertIn(run.itens_efeitos[-1],
                      run.efeitos())

    def test_usar_item_rejeita_itens_de_combate(self):
        run = novo_run()
        self.assertFalse(rt.usar_item(run, "pocao_de_vida"))
        self.assertFalse(rt.usar_item(run, "olho_de_vidro"))

    def test_consumivel_de_vida(self):
        run = novo_run(vida=10, vida_maxima=100)
        run.consumiveis = {"pocao_de_vida": 1}
        ok, mensagem = rt.usar_consumivel(run, "pocao_de_vida")
        self.assertTrue(ok)
        self.assertIn("recupera", mensagem)
        self.assertEqual(run.vida, 45)
        self.assertEqual(run.consumiveis["pocao_de_vida"], 0)
        self.assertEqual(run.consumiveis_usados["pocao_de_vida"], 1)

    def test_consumivel_de_foco(self):
        run = novo_run(foco=0)
        run.consumiveis = {"pocao_de_foco": 1}
        ok, _ = rt.usar_consumivel(run, "pocao_de_foco")
        self.assertTrue(ok)
        self.assertEqual(run.foco, 2)

    def test_bomba_causa_dano(self):
        run = novo_run()
        run.inimigo = inimigo_dummy(vida=500)
        run.consumiveis = {"bomba_de_fuligem": 1}
        ok, _ = rt.usar_consumivel(run, "bomba_de_fuligem")
        self.assertTrue(ok)
        self.assertLess(run.inimigo.vida, 500)

    def test_escudo_e_lamina(self):
        run = novo_run()
        run.consumiveis = {"escudo_de_campanha": 1}
        ok, _ = rt.usar_consumivel(run, "escudo_de_campanha")
        self.assertTrue(ok)
        self.assertGreaterEqual(run.barreira, 18)
        self.assertTrue(run.guarda)

        run = novo_run()
        run.consumiveis = {"lamina_de_aluguel": 1}
        ok, _ = rt.usar_consumivel(run, "lamina_de_aluguel")
        self.assertTrue(ok)
        self.assertEqual(run.ataque_bonus, 6)

    def test_estrategico_limite_por_run(self):
        run = novo_run()
        run.inimigo = inimigo_dummy()
        run.consumiveis = {"bomba_de_fumaca": 2}
        ok, _ = rt.usar_consumivel(run, "bomba_de_fumaca")
        self.assertTrue(ok)
        ok, mensagem = rt.usar_consumivel(run, "bomba_de_fumaca")
        self.assertFalse(ok)
        self.assertIn("1x por run", mensagem)

    def test_item_sem_estoque_falha(self):
        run = novo_run()
        run.inimigo = inimigo_dummy()
        ok, mensagem = rt.usar_consumivel(run, "bomba_de_fuligem")
        self.assertFalse(ok)
        self.assertIn("não tem", mensagem)

    def test_ataque_bonus_entra_no_dano(self):
        run = novo_run(ataque=20)
        run.inimigo = inimigo_dummy(vida=1000)
        run.bonus_critico_itens = -100   # garante crítico 0

        random.seed(123)
        sem_bonus = rt.executar_ataque(run, nunca_erra=True)
        run.inimigo.vida = 1000
        run.ataque_bonus = 6
        random.seed(123)
        com_bonus = rt.executar_ataque(run, nunca_erra=True)

        self.assertEqual(com_bonus - sem_bonus, 6)

    def test_reset_de_ataque_bonus_entre_combates(self):
        run = novo_run()
        run.ataque_bonus = 99
        # preparar_combate() mexe em random e em criar_inimigo; basta
        # confirmar que a linha de reset existe no fluxo, executando-o.
        rt.preparar_combate(run)
        self.assertEqual(run.ataque_bonus, 0)


class TestInventario(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "teste.db"
        self.patches = [
            patch.object(rt, "DB_PATH", self.db),
            patch.object(rt, "DATA_DIR", Path(self.tmp.name)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        rt.preparar_tabela_inventario()

    def test_guardar_listar_consumir(self):
        rt.guardar_item(10, 20, "lamina_rachada", 3)
        self.assertEqual(rt.listar_inventario(10, 20),
                         {"lamina_rachada": 3})
        self.assertTrue(rt.consumir_item(10, 20, "lamina_rachada", 2))
        self.assertEqual(rt.listar_inventario(10, 20),
                         {"lamina_rachada": 1})
        self.assertFalse(rt.consumir_item(10, 20, "lamina_rachada", 2))
        self.assertEqual(rt.listar_inventario(10, 20),
                         {"lamina_rachada": 1})

    def test_equipar_separa_equipaveis_e_mochila(self):
        rt.guardar_item(2, 1, "lamina_rachada", 5)      # passivo, limite 3
        rt.guardar_item(2, 1, "olho_de_vidro", 2)       # artefato, limite 1
        rt.guardar_item(2, 1, "pocao_de_vida", 4)       # consumível
        rt.guardar_item(2, 1, "bomba_de_fumaca", 2)     # estratégico

        run = novo_run(ataque=10)
        asyncio.run(rt.RupturaTemporal.equipar_itens_passivos(None, run))

        # Passivo e artefato foram consumidos até o limite da run.
        restante = rt.listar_inventario(2, 1)
        self.assertEqual(restante["lamina_rachada"], 2)
        self.assertEqual(restante["olho_de_vidro"], 1)
        self.assertEqual(restante["pocao_de_vida"], 4)
        self.assertEqual(restante["bomba_de_fumaca"], 2)

        # Efeitos e snapshot da mochila.
        self.assertEqual(run.ataque, 10 + 4 * 3)
        self.assertEqual(len(run.itens_efeitos), 1)
        self.assertEqual(run.consumiveis,
                         {"pocao_de_vida": 4, "bomba_de_fumaca": 2})
        self.assertEqual(len(run.equipados), 2)

    def test_limite_de_copias_preserva_excedente(self):
        rt.guardar_item(2, 1, "lamina_rachada", 5)
        run = novo_run()
        asyncio.run(rt.RupturaTemporal.equipar_itens_passivos(None, run))
        self.assertEqual(rt.listar_inventario(2, 1)["lamina_rachada"], 2)


class EconomiaFake:
    """API mínima da economia (_tx) usada por MercadoRepo nos testes."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def transacao(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def obter_saldo_tx(self, db, guild_id: int, user_id: int) -> int:
        db.execute("""
            INSERT OR IGNORE INTO user_stats (guild_id, user_id, coins)
            VALUES (?, ?, 0)
        """, (guild_id, user_id))
        return db.execute("""
            SELECT coins FROM user_stats WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()[0]

    def alterar_coins_tx(self, db, guild_id: int, user_id: int,
                         diferenca: int) -> int:
        self.obter_saldo_tx(db, guild_id, user_id)
        db.execute("""
            UPDATE user_stats SET coins = coins + ?
            WHERE guild_id = ? AND user_id = ?
        """, (diferenca, guild_id, user_id))
        return db.execute("""
            SELECT coins FROM user_stats WHERE guild_id = ? AND user_id = ?
        """, (guild_id, user_id)).fetchone()[0]


class BaseBancoFake(unittest.TestCase):
    """Banco temporário: nenhum teste desta classe toca data/shaggy.db."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "teste.db"
        for p in (
            patch.object(rt, "DB_PATH", self.db),
            patch.object(rt, "DATA_DIR", Path(self.tmp.name)),
        ):
            p.start()
            self.addCleanup(p.stop)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("""
                CREATE TABLE user_stats (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    coins INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            db.execute("CREATE TABLE marcador (id INTEGER PRIMARY KEY, valor TEXT)")
            db.execute("INSERT INTO marcador VALUES (1, 'intacto')")
            db.commit()
        rt.preparar_tabela_inventario()
        self.eco = EconomiaFake(self.db)
        self.repo = rt.MercadoRepo(lambda: self.eco)

    def creditar(self, quantidade: int, guild_id: int = 2, user_id: int = 1):
        with self.eco.transacao() as db:
            self.eco.alterar_coins_tx(db, guild_id, user_id, quantidade)

    def saldo(self, guild_id: int = 2, user_id: int = 1) -> int:
        with self.eco.transacao() as db:
            return self.eco.obter_saldo_tx(db, guild_id, user_id)

    def tabelas(self) -> set[str]:
        with closing(sqlite3.connect(self.db)) as db:
            return {linha[0] for linha in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}


class TestMercadoAtomico(BaseBancoFake):
    def test_compra_grava_saldo_e_item_na_mesma_transacao(self):
        self.creditar(100)
        res = self.repo.comprar_item(2, 1, "pocao_de_vida", 2)

        self.assertEqual(res.status, "ok")
        self.assertEqual(res.custo, 24)
        self.assertEqual(res.saldo, 76)
        self.assertEqual(self.saldo(), 76)
        self.assertEqual(rt.listar_inventario(2, 1),
                         {"pocao_de_vida": 2})

    def test_sem_saldo_nao_cobra_nem_entrega(self):
        self.creditar(10)
        res = self.repo.comprar_item(2, 1, "bomba_de_fuligem", 1)

        self.assertEqual(res.status, "saldo")
        self.assertEqual(res.faltam, 8)
        self.assertEqual(self.saldo(), 10)
        self.assertEqual(rt.listar_inventario(2, 1), {})

    def test_quantidade_invalida_nao_mexe_em_nada(self):
        self.creditar(100)
        self.assertEqual(
            self.repo.comprar_item(2, 1, "pocao_de_vida", 0).status,
            "invalido")
        self.assertEqual(
            self.repo.comprar_item(2, 1, "nao_existe", 1).status,
            "invalido")
        self.assertEqual(self.saldo(), 100)
        self.assertEqual(rt.listar_inventario(2, 1), {})

    def test_falha_ao_gravar_inventario_desfaz_o_debito(self):
        self.creditar(100)
        with patch.object(rt, "guardar_item_tx",
                          side_effect=RuntimeError("falha simulada")):
            with self.assertRaises(RuntimeError):
                self.repo.comprar_item(2, 1, "pocao_de_vida", 1)

        self.assertEqual(self.saldo(), 100)
        self.assertEqual(rt.listar_inventario(2, 1), {})

    def test_movimentar_debita_e_credita(self):
        self.creditar(20)
        self.assertEqual(self.repo.movimentar(2, 1, -15).saldo, 5)
        self.assertEqual(self.repo.movimentar(2, 1, -10).status, "saldo")
        self.assertEqual(self.repo.movimentar(2, 1, 3).saldo, 8)
        self.assertEqual(self.saldo(), 8)

    def test_compras_concorrentes_nao_gastam_duas_vezes(self):
        self.creditar(12)                 # saldo para UMA poção
        with ThreadPoolExecutor(max_workers=2) as pool:
            futuros = [
                pool.submit(self.repo.comprar_item, 2, 1,
                            "pocao_de_vida", 1)
                for _ in range(2)
            ]
            resultados = [f.result() for f in futuros]

        status = sorted(r.status for r in resultados)
        self.assertEqual(status, ["ok", "saldo"])
        self.assertEqual(self.saldo(), 0)
        self.assertEqual(rt.listar_inventario(2, 1),
                         {"pocao_de_vida": 1})

    def test_compra_preserva_restante_do_banco(self):
        self.creditar(100)
        antes = self.tabelas()
        self.repo.comprar_item(2, 1, "pocao_de_vida", 1)

        self.assertEqual(self.tabelas(), antes)
        with closing(sqlite3.connect(self.db)) as db:
            marcador = db.execute("SELECT valor FROM marcador").fetchone()
        self.assertEqual(marcador, ("intacto",))
        self.assertEqual(self.saldo(), 88)

    def test_comando_market_usa_o_repositorio(self):
        self.creditar(100)
        enviadas: list[str] = []

        async def send(mensagem, **kwargs):
            enviadas.append(mensagem)

        cog = rt.RupturaTemporal.__new__(rt.RupturaTemporal)
        cog.mercado_repo = self.repo
        cog._locks_mercado = {}
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=2),
            author=SimpleNamespace(id=1),
            send=send,
        )

        asyncio.run(rt.RupturaTemporal.market.callback(
            cog, ctx, "comprar", "pocao_de_vida", 2))

        self.assertIn("Comprou", enviadas[-1])
        self.assertIn("76 Abysmus", enviadas[-1])
        self.assertEqual(self.saldo(), 76)
        self.assertEqual(rt.listar_inventario(2, 1),
                         {"pocao_de_vida": 2})

    def test_comando_market_sem_saldo_nao_entrega(self):
        enviadas: list[str] = []

        async def send(mensagem, **kwargs):
            enviadas.append(mensagem)

        cog = rt.RupturaTemporal.__new__(rt.RupturaTemporal)
        cog.mercado_repo = self.repo
        cog._locks_mercado = {}
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=2),
            author=SimpleNamespace(id=1),
            send=send,
        )

        asyncio.run(rt.RupturaTemporal.market.callback(
            cog, ctx, "comprar", "bomba_de_fuligem", 1))

        self.assertIn("insuficiente", enviadas[-1])
        self.assertEqual(self.saldo(), 0)
        self.assertEqual(rt.listar_inventario(2, 1), {})


class TestMercador(BaseBancoFake):
    def setUp(self):
        super().setUp()
        self.run = novo_run(nivel=5)
        self.run.mercador = rt.criar_mercador(self.run, saldo=100)
        self.run.categoria_pendente = "chefe"
        self.cog = SimpleNamespace(mercado_repo=self.repo)

    def oferta(self, categoria: str):
        for indice, oferta in enumerate(self.run.mercador.ofertas):
            if oferta.categoria == categoria:
                return indice, oferta
        self.fail(f"O mercador não ofereceu {categoria}.")

    def comprar(self, indice: int):
        return asyncio.run(rt.RupturaTemporal.comprar_oferta_mercador(
            self.cog, self.run, indice))

    def test_oferta_tem_quatro_categorias_sem_duplicatas(self):
        ofertas = self.run.mercador.ofertas
        categorias = {o.categoria for o in ofertas}
        self.assertEqual(categorias, set(rt.MERCADOR_CATEGORIAS))
        chaves = [o.chave for o in ofertas]
        self.assertEqual(len(chaves), len(set(chaves)))
        self.assertEqual(len(ofertas), 8)
        for oferta in ofertas:
            if oferta.categoria == "forja":
                self.assertTrue(oferta.chave.startswith("forja_"))
                self.assertGreater(oferta.preco, 0)

    def test_abrir_mercador_uma_vez_por_nivel(self):
        run = novo_run(nivel=5)
        self.assertTrue(rt.abrir_mercador(run, "chefe", 50))
        primeiro = run.mercador
        self.assertFalse(rt.abrir_mercador(run, "deus", 50))
        self.assertIs(run.mercador, primeiro)
        self.assertEqual(run.mercador_visto, {5})

    def test_vitrine_omite_artefatos_ja_equipados(self):
        run = novo_run(nivel=5)
        for chave, item in rt.ITENS.items():
            if item.tipo == "artefato":
                run.itens_efeitos.append(item.efeito_factory())

        mercador = rt.criar_mercador(run)
        categorias = [oferta.categoria for oferta in mercador.ofertas]
        self.assertNotIn("artefato", categorias)
        self.assertEqual(len(mercador.ofertas), 7)

    def test_mercador_nao_abre_em_mini_chefe_ou_normal(self):
        for categoria in ("normal", "mini_chefe"):
            run = novo_run(nivel=6)
            self.assertFalse(rt.abrir_mercador(run, categoria, 50))
            self.assertIsNone(run.mercador)

        run = novo_run(nivel=10)
        self.assertTrue(rt.abrir_mercador(run, "deus", 50))

    def test_compra_de_consumivel_persiste_e_entra_na_mochila(self):
        self.creditar(100)
        indice, oferta = self.oferta("consumivel")
        ok, mensagem = self.comprar(indice)

        self.assertTrue(ok, mensagem)
        self.assertTrue(oferta.comprado)
        self.assertEqual(self.saldo(), 100 - oferta.preco)
        self.assertEqual(self.run.consumiveis, {oferta.chave: 1})
        self.assertEqual(rt.listar_inventario(2, 1),
                         {oferta.chave: 1})

    def test_compra_de_estrategico_persiste_na_mochila(self):
        self.creditar(100)
        indice, oferta = self.oferta("estrategico")
        ok, mensagem = self.comprar(indice)

        self.assertTrue(ok, mensagem)
        self.assertEqual(self.run.consumiveis, {oferta.chave: 1})
        self.assertEqual(rt.listar_inventario(2, 1),
                         {oferta.chave: 1})

    def test_artefato_vale_so_para_a_run_e_nao_duplica(self):
        self.creditar(100)
        indice, oferta = self.oferta("artefato")
        ok, mensagem = self.comprar(indice)

        self.assertTrue(ok, mensagem)
        self.assertEqual(len(self.run.itens_efeitos), 1)
        self.assertEqual(self.run.itens_efeitos[0].nome, oferta.nome)
        self.assertEqual(rt.listar_inventario(2, 1), {})

        duplicada = rt.MercadorOferta(
            chave=oferta.chave, categoria="artefato", nome=oferta.nome,
            descricao=oferta.descricao, preco=oferta.preco)
        self.assertIn("já equipou",
                      rt.motivo_bloqueio_oferta(self.run, duplicada))

    def test_compra_sem_saldo_nao_aplica_oferta(self):
        indice, oferta = self.oferta("consumivel")
        ok, mensagem = self.comprar(indice)

        self.assertFalse(ok)
        self.assertIn("insuficiente", mensagem)
        self.assertFalse(oferta.comprado)
        self.assertEqual(self.run.consumiveis, {})
        self.assertEqual(self.saldo(), 0)
        self.assertEqual(rt.listar_inventario(2, 1), {})

    def test_forja_limite_total_e_custo_crescente(self):
        self.creditar(40)
        indice_ataque, of_ataque = self.oferta("forja")
        indice_defesa, of_defesa = next(
            (i, o) for i, o in enumerate(self.run.mercador.ofertas)
            if o.chave == "forja_defesa")
        indice_vida, of_vida = next(
            (i, o) for i, o in enumerate(self.run.mercador.ofertas)
            if o.chave == "forja_vida")

        ataque_antes = self.run.ataque
        self.assertEqual(rt.preco_oferta(self.run, of_ataque), 12)
        ok, mensagem = self.comprar(indice_ataque)
        self.assertTrue(ok, mensagem)
        self.assertEqual(self.run.ataque, ataque_antes + 1)
        self.assertEqual(rt.preco_oferta(self.run, of_defesa), 16)

        ok, mensagem = self.comprar(indice_defesa)
        self.assertTrue(ok, mensagem)
        self.assertEqual(self.run.forja_usos, 2)

        motivo = rt.motivo_bloqueio_oferta(self.run, of_vida)
        self.assertIn("máximo", motivo)
        ok, mensagem = self.comprar(indice_vida)
        self.assertFalse(ok)
        self.assertIn("máximo", mensagem)
        self.assertEqual(self.saldo(), 12)

    def test_forja_respeita_teto_por_atributo(self):
        run = novo_run(nivel=5)
        run.forja = {"vida": rt.FORJA_CAP["vida"]}
        run.forja_usos = 1
        oferta = rt.MercadorOferta(
            chave="forja_vida", categoria="forja", nome="Forja",
            descricao="", preco=10)

        self.assertIn("teto", rt.motivo_bloqueio_oferta(run, oferta))

    def test_estrategico_tem_limite_de_um_uso_por_run(self):
        run = novo_run()
        run.consumiveis = {"bomba_de_fumaca": 2}

        ok, _ = rt.usar_consumivel(run, "bomba_de_fumaca")
        self.assertTrue(ok)
        ok, mensagem = rt.usar_consumivel(run, "bomba_de_fumaca")
        self.assertFalse(ok)
        self.assertIn("1x por run", mensagem)
        self.assertEqual(run.consumiveis["bomba_de_fumaca"], 1)
        self.assertEqual(run.consumiveis_usados["bomba_de_fumaca"], 1)


class TestProgressaoMercador(unittest.TestCase):
    def setUp(self):
        self.run = novo_run(nivel=4)
        self.cog = rt.RupturaTemporal.__new__(rt.RupturaTemporal)
        self.cog.bot = SimpleNamespace(get_cog=lambda nome: None)

    def derrotar(self, categoria: str):
        spec = rt.EnemySpec(
            "Derrotado", "Da'kor", 1, 10, 1, 0, 5, 0, "",
            "Criatura criada apenas para os testes.", categoria=categoria,
        )
        self.run.inimigo = rt.EnemyState(
            spec=spec, nivel=self.run.nivel, vida=0, vida_maxima=10,
            ataque=1, defesa=0)

    def test_vitoria_antes_de_chefe_abre_mercador(self):
        self.derrotar("normal")
        with patch.object(rt, "award_rewards", new=AsyncMock(return_value=True)):
            asyncio.run(self.cog.registrar_vitoria(self.run))

        self.assertEqual(self.run.nivel, 5)
        self.assertEqual(self.run.categoria_pendente, "chefe")
        self.assertIsNotNone(self.run.mercador)

        self.cog.avancar_apos_mercador(self.run)
        self.assertIsNone(self.run.mercador)
        self.assertEqual(self.run.inimigo.spec.categoria, "chefe")

    def test_mini_chefe_nao_abre_mercador(self):
        self.run.nivel = 2
        self.derrotar("normal")
        with patch.object(rt, "award_rewards", new=AsyncMock(return_value=True)):
            asyncio.run(self.cog.registrar_vitoria(self.run))

        self.assertEqual(self.run.nivel, 3)
        self.assertIsNone(self.run.mercador)
        self.assertEqual(self.run.inimigo.spec.categoria, "mini_chefe")


class TestCombateTatico(unittest.TestCase):
    def setUp(self):
        self.run = novo_run(vida=200, vida_maxima=200, ataque=20, defesa=0,
                            nivel=5)

    def chefe(self, categoria: str = "chefe", ataque: int = 10):
        spec = rt.EnemySpec(
            "Chefe de Teste", "Da'kor", 1, 100, ataque, 0, 10, 0, "",
            "Criatura criada apenas para os testes.", categoria=categoria,
        )
        inimigo = rt.EnemyState(
            spec=spec, nivel=5, vida=100, vida_maxima=100,
            ataque=ataque, defesa=0,
        )
        self.run.inimigo = inimigo
        return inimigo

    def test_criatura_comum_mantem_golpe_basico(self):
        inimigo = self.chefe(categoria="normal")
        for _ in range(3):
            rt.registrar_acao_jogador(self.run, "atacar")

        self.assertIsNone(rt.selecionar_acao_chefe(self.run, inimigo))
        self.assertFalse(inimigo.memoria.adaptado)

        with patch.object(rt.random, "randint", return_value=0):
            rt.turno_inimigo(self.run)

        self.assertEqual(self.run.vida, 190)
        self.assertIsNone(inimigo.acao_pendente)

    def test_chefe_telegrafa_golpe_a_cada_tres_turnos(self):
        inimigo = self.chefe()
        inimigo.turnos = 2
        self.assertIsNone(rt.selecionar_acao_chefe(self.run, inimigo))

        inimigo.turnos = 3
        self.assertEqual(rt.selecionar_acao_chefe(self.run, inimigo),
                         rt.GOLPE_PESADO)

        rt.preparar_acao_inimiga(self.run, inimigo, rt.GOLPE_PESADO)
        self.assertEqual(inimigo.acao_pendente, rt.GOLPE_PESADO)
        self.assertIn("Golpe Pesado", rt.texto_intencao(self.run, inimigo))
        self.assertIn("Guardar", rt.texto_intencao(self.run, inimigo))

    def test_acao_telegrafada_resolve_no_turno_seguinte(self):
        inimigo = self.chefe()
        rt.preparar_acao_inimiga(self.run, inimigo, rt.GOLPE_PESADO)

        with patch.object(rt.random, "randint", return_value=0):
            rt.turno_inimigo(self.run)

        self.assertEqual(self.run.vida, 185)      # 10 * 1.55
        self.assertIsNone(inimigo.acao_pendente)

    def test_guarda_interrompe_acao_telegrafada(self):
        inimigo = self.chefe()
        rt.preparar_acao_inimiga(self.run, inimigo, rt.GOLPE_PESADO)
        self.run.guarda = True

        rt.turno_inimigo(self.run)

        self.assertEqual(self.run.vida, 200)
        self.assertIsNone(inimigo.acao_pendente)
        self.assertTrue(any("interrompida" in linha for linha in self.run.log))

    def test_atordoamento_interrompe_acao_telegrafada(self):
        inimigo = self.chefe()
        rt.preparar_acao_inimiga(self.run, inimigo, rt.GOLPE_PESADO)
        inimigo.atordoado = True

        rt.turno_inimigo(self.run)

        self.assertEqual(self.run.vida, 200)
        self.assertIsNone(inimigo.acao_pendente)
        self.assertTrue(any("atordoada" in linha for linha in self.run.log))

    def test_guarda_nao_interrompe_acao_nao_interrompivel(self):
        inimigo = self.chefe()
        acao = rt.AcaoInimiga(
            "lenta", "Golpe Lento", "Não pode ser interrompido.",
            prepara=True, interrompivel=False)
        inimigo.acao_pendente = acao
        self.run.guarda = True

        with patch.object(rt.random, "randint", return_value=0):
            rt.turno_inimigo(self.run)

        self.assertEqual(self.run.vida, 195)      # guarda reduz para metade
        self.assertIsNone(inimigo.acao_pendente)

    def test_postura_defensiva_reduz_e_expira(self):
        inimigo = self.chefe()
        self.run.bonus_critico_itens = -100

        with patch.object(rt.random, "randint", return_value=1):
            com_postura = rt.executar_ataque(self.run, nunca_erra=True)
            inimigo.vida = 100
            inimigo.protecao = 1
            reduzido = rt.executar_ataque(self.run, nunca_erra=True)

        self.assertEqual(com_postura, 21)
        self.assertEqual(reduzido, 10)
        self.assertEqual(inimigo.protecao, 1)     # expira no turno dele

        with patch.object(rt.random, "randint", return_value=0):
            rt.turno_inimigo(self.run)
        self.assertEqual(inimigo.protecao, 0)

        inimigo.vida = 100
        with patch.object(rt.random, "randint", return_value=1):
            self.assertEqual(
                rt.executar_ataque(self.run, nunca_erra=True), 21)

    def test_chefe_adapta_uma_unica_vez_ao_padrao(self):
        inimigo = self.chefe()
        for _ in range(3):
            rt.registrar_acao_jogador(self.run, "atacar")

        acao = rt.selecionar_acao_chefe(self.run, inimigo)
        self.assertEqual(acao, rt.POSTURA_DEFENSIVA)
        self.assertTrue(inimigo.memoria.adaptado)
        self.assertEqual(inimigo.memoria.padrao, "atacar")

        # Mesmo mudando o padrão, a adaptação não se repete neste chefe.
        for _ in range(3):
            rt.registrar_acao_jogador(self.run, "tecnica")
        acao = rt.selecionar_acao_chefe(self.run, inimigo)
        self.assertNotEqual(acao, rt.CONTRA_GOLPE)
        self.assertTrue(inimigo.memoria.adaptado)
        self.assertEqual(inimigo.memoria.padrao, "atacar")

    def test_tecnica_gera_contra_golpe(self):
        inimigo = self.chefe()
        for _ in range(3):
            rt.registrar_acao_jogador(self.run, "tecnica")

        self.assertEqual(rt.selecionar_acao_chefe(self.run, inimigo),
                         rt.CONTRA_GOLPE)

    def test_memoria_do_chefe_e_isolada_por_inimigo_e_run(self):
        chefe_a = self.chefe()
        for _ in range(3):
            rt.registrar_acao_jogador(self.run, "atacar")

        chefe_b = self.chefe(categoria="deus")
        self.assertEqual(chefe_b.memoria.observacoes, [])
        self.assertFalse(chefe_b.memoria.adaptado)

        outro_run = novo_run(nivel=5)
        terceiro = self.chefe()
        outro_run.inimigo = terceiro
        rt.registrar_acao_jogador(outro_run, "guardar")
        self.assertEqual(chefe_a.memoria.observacoes, ["atacar"] * 3)
        self.assertEqual(terceiro.memoria.observacoes, ["guardar"])
        self.assertNotEqual(id(chefe_a.memoria), id(terceiro.memoria))

    def test_memoria_mantem_janela_curta(self):
        memoria = rt.MemoriaChefe()
        for _ in range(10):
            memoria.registrar("atacar")

        self.assertEqual(len(memoria.observacoes), 5)
        self.assertEqual(memoria.padrao_detectado(), "atacar")

    def test_preparar_combate_reaproveita_categoria_sorteada(self):
        run = novo_run(nivel=5)
        run.categoria_pendente = "chefe"
        rt.preparar_combate(run)

        self.assertEqual(run.categoria_pendente, "")
        self.assertEqual(run.inimigo.spec.categoria, "chefe")

    def test_pvp_continua_compativel_com_campos_novos(self):
        alvo = pvp.criar_alvo("Oponente")
        self.assertIsNone(alvo.acao_pendente)
        self.assertEqual(alvo.protecao, 0)
        self.assertFalse(alvo.memoria.adaptado)
        self.assertIsNone(rt.selecionar_acao_chefe(novo_run(), alvo))


class TestPvP(unittest.TestCase):
    def test_pvp_equipa_so_passivos_e_artefatos(self):
        inventario = {
            "lamina_rachada": 2,
            "olho_de_vidro": 1,
            "pocao_de_vida": 5,
            "bomba_de_fumaca": 1,
        }
        run = novo_run(ataque=10)
        with patch.object(pvp, "listar_inventario", return_value=inventario):
            asyncio.run(pvp.RupturaDuelo.equipar_itens(None, run))

        self.assertEqual(run.ataque, 18)
        self.assertEqual(len(run.itens_efeitos), 1)
        self.assertEqual(run.consumiveis, {})
        self.assertEqual(len(run.equipados), 2)
        self.assertFalse(any("Poção" in e or "Bomba" in e
                             for e in run.equipados))


class TestGuardaPvEPvP(unittest.TestCase):
    """Impede uma run PvE e um duelo PvP simultâneos para o mesmo jogador."""

    @staticmethod
    def bot_com(runs_ativas=None, ocupados=None):
        cogs = {
            "RupturaTemporal": SimpleNamespace(
                runs_ativas=runs_ativas if runs_ativas is not None else {}),
            "RupturaDuelo": SimpleNamespace(
                ocupados=ocupados if ocupados is not None else set()),
        }
        return SimpleNamespace(get_cog=lambda nome: cogs.get(nome))

    def test_estado_detecta_run_duelo_e_jogador_livre(self):
        bot = self.bot_com(runs_ativas={7: object()})
        self.assertEqual(rt.estado_jogador_ocupado(bot, 7), "run")
        self.assertEqual(rt.estado_jogador_ocupado(bot, 8), "")

        bot = self.bot_com(ocupados={7})
        self.assertEqual(rt.estado_jogador_ocupado(bot, 7), "duelo")

    def test_comando_pve_bloqueia_jogador_em_duelo(self):
        bot = self.bot_com(ocupados={7})
        cog = object.__new__(rt.RupturaTemporal)
        cog.bot = bot
        cog.runs_ativas = {}
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=7),
            guild=SimpleNamespace(id=2),
            send=AsyncMock(),
        )

        asyncio.run(rt.RupturaTemporal.ruptura.callback(cog, ctx))

        ctx.send.assert_awaited_once()
        self.assertIn("convite ou duelo", ctx.send.await_args.args[0])
        self.assertEqual(cog.runs_ativas, {})

    def test_iniciar_run_bloqueia_jogador_em_duelo(self):
        bot = self.bot_com(ocupados={7})
        cog = object.__new__(rt.RupturaTemporal)
        cog.bot = bot
        cog.runs_ativas = {}
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7, display_name="Teste"),
            guild_id=2,
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        asyncio.run(cog.iniciar_run(interaction, rt.CLASSES["guardiao"]))

        interaction.response.send_message.assert_awaited_once()
        self.assertIn(
            "convite ou duelo",
            interaction.response.send_message.await_args.args[0],
        )
        self.assertEqual(cog.runs_ativas, {})

    def test_duelo_bloqueia_jogador_em_run_pve(self):
        bot = self.bot_com(runs_ativas={7: object()})
        cog = object.__new__(pvp.RupturaDuelo)
        cog.bot = bot
        cog.ocupados = set()
        ctx = SimpleNamespace(
            author=SimpleNamespace(id=7, display_name="Autor"),
            guild=SimpleNamespace(id=2),
            send=AsyncMock(),
        )
        oponente = SimpleNamespace(
            id=8, bot=False, display_name="Oponente", mention="<@8>")

        asyncio.run(
            pvp.RupturaDuelo.duelo.callback(cog, ctx, oponente))

        ctx.send.assert_awaited_once()
        self.assertIn("run ativa", ctx.send.await_args.args[0])
        self.assertEqual(cog.ocupados, set())


class TestLiberacaoEstadoPvP(unittest.TestCase):
    """Falhas de interação não podem deixar jogadores presos em `ocupados`."""

    @staticmethod
    def membro(uid: int):
        return SimpleNamespace(id=uid, display_name=f"Jogador {uid}",
                               mention=f"<@{uid}>")

    def test_aceitar_libera_jogadores_quando_falha_ao_editar(self):
        bot = SimpleNamespace(
            get_cog=lambda nome: SimpleNamespace(runs_ativas={})
            if nome == "RupturaTemporal" else None)
        cog = object.__new__(pvp.RupturaDuelo)
        cog.bot = bot
        cog.ocupados = {7}
        view = pvp.ConviteDuelo(cog, self.membro(7), self.membro(8))
        interaction = SimpleNamespace(
            user=self.membro(8),
            response=SimpleNamespace(
                edit_message=AsyncMock(side_effect=RuntimeError("boom")),
                send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            original_response=AsyncMock(),
        )

        with self.assertLogs("shaggy.ruptura.pvp", level="ERROR"):
            asyncio.run(view.aceitar.callback(interaction))

        self.assertEqual(cog.ocupados, set())
        self.assertTrue(view.resolvido)
        interaction.followup.send.assert_awaited_once()

    def test_aceitar_reserva_alvo_e_abre_escolha(self):
        bot = SimpleNamespace(
            get_cog=lambda nome: SimpleNamespace(runs_ativas={})
            if nome == "RupturaTemporal" else None)
        cog = object.__new__(pvp.RupturaDuelo)
        cog.bot = bot
        cog.ocupados = {7}
        view = pvp.ConviteDuelo(cog, self.membro(7), self.membro(8))
        interaction = SimpleNamespace(
            user=self.membro(8),
            response=SimpleNamespace(
                edit_message=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
            original_response=AsyncMock(),
        )

        asyncio.run(view.aceitar.callback(interaction))

        self.assertEqual(cog.ocupados, {7, 8})
        self.assertTrue(view.resolvido)
        interaction.response.edit_message.assert_awaited_once()

    def test_escolher_libera_jogadores_quando_defer_falha(self):
        cog = object.__new__(pvp.RupturaDuelo)
        cog.bot = SimpleNamespace(get_cog=lambda nome: None)
        cog.ocupados = {7, 8}
        cog.iniciar_duelo = AsyncMock()
        view = pvp.EscolhaClasse(cog, self.membro(7), self.membro(8))
        view.picks[7] = "guardiao"
        interaction = SimpleNamespace(
            user=self.membro(8),
            response=SimpleNamespace(
                defer=AsyncMock(side_effect=RuntimeError("boom")),
                send_message=AsyncMock()),
            message=SimpleNamespace(edit=AsyncMock()),
        )

        with self.assertLogs("shaggy.ruptura.pvp", level="ERROR"):
            asyncio.run(view.escolher(interaction, "guardiao"))

        self.assertEqual(cog.ocupados, set())
        cog.iniciar_duelo.assert_not_awaited()

    def test_dois_iniciar_run_concorrentes_criam_uma_run(self):
        cogs = {
            "RupturaTemporal": SimpleNamespace(runs_ativas={}),
            "RupturaDuelo": SimpleNamespace(ocupados=set()),
        }
        bot = SimpleNamespace(get_cog=lambda nome: cogs.get(nome))
        cog = object.__new__(rt.RupturaTemporal)
        cog.bot = bot
        cog.runs_ativas = cogs["RupturaTemporal"].runs_ativas
        cog.equipar_itens_passivos = AsyncMock()
        cog.carregar_build_run = AsyncMock()
        eventos = []

        async def tentar():
            interaction = SimpleNamespace(
                user=SimpleNamespace(id=7, display_name="Teste"),
                guild_id=2,
                response=SimpleNamespace(
                    send_message=AsyncMock(
                        side_effect=lambda *a, **k: eventos.append(
                            "bloqueado")),
                    edit_message=AsyncMock(
                        side_effect=lambda *a, **k: eventos.append("criado")),
                ),
                original_response=AsyncMock(),
            )
            await cog.iniciar_run(interaction, rt.CLASSES["guardiao"])

        async def cenario():
            await asyncio.gather(tentar(), tentar())

        asyncio.run(cenario())

        self.assertEqual(sorted(eventos), ["bloqueado", "criado"])
        self.assertEqual(list(cog.runs_ativas), [7])


class TestEmbeds(unittest.TestCase):
    def test_embeds_da_expansao(self):
        mercado = rt.criar_embed_mercado()
        nomes = " ".join(f.name for f in mercado.fields)
        self.assertIn("Consumíveis", nomes)
        self.assertIn("Artefatos", nomes)
        self.assertIn("Estratégicos", nomes)

        run = novo_run(vida=50, vida_maxima=100)
        run.consumiveis = {"pocao_de_vida": 2}
        run.itens_efeitos.append(rt.ITENS["olho_de_vidro"].efeito_factory())
        mochila = rt.criar_embed_mochila(run)
        self.assertIn("Poção de Vida", mochila.fields[0].value)
        self.assertIn("Olho de Vidro", str(rt.criar_embed(run).fields))

        run.evento_ativo = rt.EVENTOS["voz_na_nevoa"]
        escolha = rt.criar_embed_escolha(run)
        self.assertIn("Escolha uma opção", [f.name for f in escolha.fields])


class TestHabilidadesExpansao3(unittest.TestCase):
    """Cada nova habilidade precisa mudar o combate e ter contrajogo."""

    def setUp(self):
        self.run = None

    def preparar(self, nome: str):
        spec = next(c for c in rt.CRIATURAS if c.nome == nome)
        self.run = novo_run(
            vida=1000, vida_maxima=1000, ataque=20, defesa=0,
            nivel=spec.nivel_minimo, foco=5,
        )
        self.run.bonus_critico_itens = -100
        with patch.object(rt.random, "choice", return_value=spec):
            inimigo = rt.criar_inimigo(
                spec.nivel_minimo, categoria=spec.categoria)
        self.run.inimigo = inimigo
        return self.run, inimigo

    def golpe(self, **kwargs):
        # randint(a, b) -> a: dano baixo e nunca crítico (bônus -100).
        with patch.object(rt.random, "randint", side_effect=lambda a, b: a):
            return rt.executar_ataque(self.run, nunca_erra=True, **kwargs)

    def turno(self, sem_acao_padrao: bool = True):
        contexto = patch.object(rt.random, "randint", return_value=0)
        with contexto:
            if sem_acao_padrao:
                with patch.object(rt, "escolher_acao_chefe", return_value=None):
                    rt.turno_inimigo(self.run)
            else:
                rt.turno_inimigo(self.run)

    def test_mini_chefes_dakor(self):
        # Pedágio de Névoa: cobra Foco e perde o turno.
        run, ini = self.preparar("Vigia da Ponte Quebrada")
        run.foco = 5
        ini.turnos = 2
        self.turno()
        self.assertEqual(run.foco, 3)
        self.assertEqual(run.vida, 1000)
        self.assertTrue(any("cobra" in linha for linha in run.log))

        # Gume Ritual: fica exposto ao afiar e devolve +4 no golpe seguinte.
        run, ini = self.preparar("Afiador de Ossos")
        ini.turnos = 1
        self.turno()
        self.assertTrue(getattr(ini, "_gume"))
        self.assertEqual(run.vida, 1000)
        self.golpe()
        self.assertTrue(getattr(ini, "_gume"))
        ini.turnos = 2
        self.turno()
        self.assertEqual(run.vida, 1000 - (ini.ataque + 4))
        self.assertFalse(getattr(ini, "_gume", False))

        # Coro Submerso: cura e drena Foco sem atacar.
        run, ini = self.preparar("Coro de Afogados")
        run.foco = 3
        ini.vida = ini.vida_maxima - 5
        ini.turnos = 2
        self.turno()
        self.assertEqual(run.foco, 2)
        self.assertEqual(run.vida, 1000)
        self.assertEqual(ini.vida, ini.vida_maxima - 1)

        # Linha de Seda: três golpes rompem um fio e reduzem a defesa.
        run, ini = self.preparar("A Costureira de Sombras")
        defesa = ini.defesa
        for _ in range(3):
            self.golpe()
        self.assertEqual(getattr(ini, "_seda_fios"), 1)
        self.assertEqual(ini.defesa, max(0, defesa - 2))

        # Rosto Emprestado: a primeira Técnica racha a máscara.
        run, ini = self.preparar("Máscara do Primeiro Rosto")
        run.golpe_tecnica = True
        self.golpe()
        self.assertTrue(getattr(ini, "_rosto_quebrado"))
        run.golpe_tecnica = False
        self.assertEqual(
            ini.habilidade.reduzir_dano_recebido(run, ini, 10), 12)

        # Rancor Contado: três golpes acumulam +1 e descarregam no ataque.
        run, ini = self.preparar("Contador de Ossos")
        for _ in range(3):
            self.golpe()
        self.assertEqual(getattr(ini, "_rancor"), 1)
        self.turno()
        self.assertEqual(run.vida, 1000 - (ini.ataque + 1))
        self.assertFalse(getattr(ini, "_rancor", 0))

    def test_mini_chefes_vapor(self):
        # Purga de Vapor: limpa status e cura, mas perde o turno.
        run, ini = self.preparar("A Caldeira Que Respira")
        ini.queimadura = 2
        ini.veneno = 3
        ini.sangria = 1
        ini.vida = ini.vida_maxima - 5
        ini.turnos = 3
        self.assertTrue(ini.habilidade.ao_turno(run, ini))
        self.assertEqual((ini.queimadura, ini.veneno, ini.sangria), (0, 0, 0))
        self.assertEqual(ini.vida, ini.vida_maxima - 2)
        self.assertEqual(run.vida, 1000)

        # Segundo Roubado: bloqueia o próximo ataque e acelera o corpo.
        run, ini = self.preparar("Ladrão de Segundos")
        ataque = ini.ataque
        ini.turnos = 3
        self.turno()
        self.assertTrue(run.ataque_bloqueado)
        self.assertEqual(ini.ataque, ataque + 1)
        self.assertEqual(run.vida, 1000)

        # Pressão Controlada: defesa inteira, ataque quando abre a válvula.
        run, ini = self.preparar("Sentinela da Válvula Mestra")
        self.assertEqual(
            ini.habilidade.reduzir_dano_recebido(run, ini, 10), 7)
        ini.vida = int(ini.vida_maxima * 0.5)
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 13)

        # Placa Moldada: ganha proteção e cura ao gastar o turno.
        run, ini = self.preparar("Fundidor de Placas")
        ini.vida = ini.vida_maxima - 5
        ini.turnos = 3
        self.turno()
        self.assertEqual(ini.protecao, 1)
        self.assertEqual(ini.vida, ini.vida_maxima - 3)
        self.assertEqual(run.vida, 1000)

        # Fio Escaldante: cada golpe respinga 2 e a queimadura aumenta o dano.
        run, ini = self.preparar("Aranha de Válvulas")
        run.vida = 100
        run.queimadura = 1
        self.golpe()
        self.assertEqual(run.vida, 98)
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 12)

        # Fole de Cinzas: drena Foco e o golpe seguinte causa +2.
        run, ini = self.preparar("Maquinista de Cinzas")
        run.foco = 3
        ini.turnos = 2
        self.turno()
        self.assertEqual(run.foco, 2)
        self.assertEqual(run.vida, 1000 - (ini.ataque + 2))
        self.assertFalse(getattr(ini, "_cinzas_bonus", False))

    def test_mini_chefes_futuro(self):
        # Miragem Tática: golpe básico é reduzido; Técnica dissipa e fere.
        run, ini = self.preparar("Tecelã de Miragens")
        ini.turnos = 3
        self.turno()
        self.assertTrue(getattr(ini, "_miragem"))
        self.assertEqual(ini.protecao, 1)
        run.golpe_tecnica = True
        self.golpe()
        self.assertFalse(getattr(ini, "_miragem", False))
        self.assertEqual(ini.protecao, 0)

        # Minuto Devorado: drena Foco e recupera vida sem atacar.
        run, ini = self.preparar("Devorador de Minutos")
        run.foco = 5
        ini.vida = ini.vida_maxima - 10
        ini.turnos = 2
        self.turno()
        self.assertEqual(run.foco, 3)
        self.assertEqual(ini.vida, ini.vida_maxima - 7)
        self.assertEqual(run.vida, 1000)

        # Palavras Gastas: Técnicas alimentam o próximo golpe dela.
        run, ini = self.preparar("Arauto das Palavras Gastas")
        run.golpe_tecnica = True
        self.golpe()
        self.assertEqual(getattr(ini, "_palavras"), 3)
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 13)
        self.assertEqual(getattr(ini, "_palavras"), 0)

        # Instante Perdido: ausente sofre 1; volta com +2.
        run, ini = self.preparar("Sombra do Instante Perdido")
        ini.turnos = 2
        self.turno()
        self.assertTrue(getattr(ini, "_instante_ausente"))
        self.assertEqual(self.golpe(), 1)
        ini.turnos = 3
        self.turno()
        self.assertFalse(getattr(ini, "_instante_ausente", False))
        self.assertEqual(run.vida, 1000 - (ini.ataque + 2))

        # Ponteiro Parado: bloqueia o ataque e devolve Foco.
        run, ini = self.preparar("Ponteiro Parado")
        run.foco = 3
        ini.turnos = 4
        self.turno()
        self.assertTrue(run.ataque_bloqueado)
        self.assertEqual(run.foco, 4)
        self.assertEqual(run.vida, 1000)

        # Fome do Amanhã: cada golpe alimenta o próximo; Guarda reduz.
        run, ini = self.preparar("Fome do Amanhã")
        ini.habilidade.apos_golpe(run, ini, 5)
        self.assertEqual(getattr(ini, "_fome"), 1)
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 11)
        run.guarda = True
        ini.habilidade.ao_turno(run, ini)
        self.assertEqual(getattr(ini, "_fome"), 0)

    def test_chefes_dakor(self):
        # Travessia Forçada: telegrafada, interrompível e com sangramento.
        run, ini = self.preparar("O Barqueiro de Ossos")
        ini.turnos = 3
        self.turno()
        acao = ini.acao_pendente
        self.assertEqual(acao.chave, "travessia_forcada")
        self.assertTrue(acao.prepara and acao.interrompivel)
        run.guarda = True
        self.turno()
        self.assertIsNone(ini.acao_pendente)
        self.assertEqual(run.vida, 1000)

        run, ini = self.preparar("O Barqueiro de Ossos")
        ini.turnos = 3
        self.turno()
        self.turno()
        self.assertGreater(run.sangramento, 0)
        self.assertLess(run.vida, 1000)

        # Troca de Rosto: alterna defesa e ataque.
        run, ini = self.preparar("A Mãe das Máscaras")
        ini.turnos = 1
        self.turno()
        self.assertFalse(getattr(ini, "_rosto_pedra", True))
        self.assertEqual(run.vida, 1000 - (ini.ataque + 4))
        ini.turnos = 3
        self.turno()
        self.assertTrue(getattr(ini, "_rosto_pedra", False))
        self.assertEqual(
            ini.habilidade.reduzir_dano_recebido(run, ini, 10), 6)

        # Fatura do Colecionador: cobra por bens equipados.
        run, ini = self.preparar("O Coletor de Dívidas")
        run.equipados = ["a", "b"]
        run.itens_efeitos = [object()]
        run.reliquias = [object()]
        ini.turnos = 4
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 16)

        # Máscaras Trocadas: pedra absorve; espinhos devolvem dano.
        run, ini = self.preparar("O Pastor de Máscaras")
        run.vida = 100
        self.golpe()
        self.assertFalse(getattr(ini, "_mascara_pedra", True))
        self.golpe()
        self.assertEqual(run.vida, 98)
        self.assertTrue(getattr(ini, "_mascara_pedra", False))

        # Luz do Farol: marca e causa +5; Guarda encobre a luz.
        run, ini = self.preparar("A Viúva do Farol")
        ini.turnos = 2
        self.turno()
        self.assertEqual(run.vida, 1000 - (ini.ataque + 5))
        self.assertFalse(run.marcado)

        run, ini = self.preparar("A Viúva do Farol")
        ataque = ini.ataque
        ini.turnos = 2
        run.guarda = True
        self.turno()
        self.assertEqual(ini.ataque, ataque - 1)
        self.assertEqual(run.vida, 1000)

        # Página Arrancada: reduz o ataque do jogador; Guarda protege.
        run, ini = self.preparar("O Arquivista de Nomes")
        run.ataque = 20
        ini.vida = ini.vida_maxima - 10
        ini.turnos = 4
        self.turno()
        self.assertEqual(run.ataque, 19)
        self.assertEqual(ini.vida, ini.vida_maxima - 6)
        self.assertEqual(run.vida, 1000)

        run, ini = self.preparar("O Arquivista de Nomes")
        run.ataque = 20
        run.guarda = True
        ini.turnos = 4
        self.turno()
        self.assertEqual(run.ataque, 20)

    def test_chefes_vapor(self):
        # Linha de Montagem: monta peças; Técnica desmonta.
        run, ini = self.preparar("O Engenheiro-Chefe")
        ataque = ini.ataque
        ini.vida = ini.vida_maxima - 10
        ini.turnos = 2
        self.turno()
        self.assertEqual(getattr(ini, "_pecas"), 1)
        self.assertEqual(ini.ataque, ataque + 1)
        self.assertEqual(ini.vida, ini.vida_maxima - 7)
        run.golpe_tecnica = True
        self.golpe()
        self.assertEqual(getattr(ini, "_pecas"), 0)
        self.assertEqual(ini.ataque, ataque)

        # Combustão: consome barreira; sem barreira, queima.
        run, ini = self.preparar("A Fornalha Viva")
        run.barreira = 100
        ini.turnos = 1
        self.turno()
        self.assertEqual(run.barreira, 100 - 3 - ini.ataque)
        self.assertEqual(run.vida, 1000)

        run, ini = self.preparar("A Fornalha Viva")
        run.barreira = 0
        ini.turnos = 1
        self.turno()
        self.assertEqual(run.vida, 1000 - (ini.ataque + 2) - 4)
        self.assertFalse(getattr(ini, "_combustao", False))

        # Fios Cruzados: bloqueia o próximo ataque; Guarda interrompe.
        run, ini = self.preparar("O Titereiro de Válvulas")
        ini.turnos = 2
        self.turno()
        self.assertEqual(ini.acao_pendente.chave, "fios_cruzados")
        run.guarda = True
        self.turno()
        self.assertFalse(run.ataque_bloqueado)

        run, ini = self.preparar("O Titereiro de Válvulas")
        ini.turnos = 2
        self.turno()
        self.turno()
        self.assertTrue(run.ataque_bloqueado)
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 12)

        # Duas Faces do Latão: alterna defesa/remendo e dano.
        run, ini = self.preparar("A Dama de Latão")
        ini.turnos = 2
        self.turno()
        self.assertFalse(getattr(ini, "_fase_latao", True))
        self.assertEqual(run.vida, 1000 - (ini.ataque + 3))

        run, ini = self.preparar("A Dama de Latão")
        ini._fase_latao = False       # estado após a face de Vidro
        ini.turnos = 5
        ini.vida = ini.vida_maxima - 10
        self.turno()
        self.assertTrue(getattr(ini, "_fase_latao", False))
        self.assertEqual(ini.vida, ini.vida_maxima - 8)
        self.assertEqual(run.vida, 1000 - ini.ataque)

        # Hora Final: telegrafada; Guarda interrompe.
        run, ini = self.preparar("O Relojoeiro do Fim")
        ini.turnos = 4
        self.turno()
        self.assertEqual(ini.acao_pendente.chave, "hora_final")
        run.guarda = True
        self.turno()
        self.assertEqual(run.vida, 1000)

        # Oferenda de Carvão: item usado vira cura e ataque.
        run, ini = self.preparar("A Catedral de Carvão")
        ataque = ini.ataque
        ini.vida = ini.vida_maxima - 10
        ini.memoria.observacoes = ["item"]
        ini.turnos = 0
        self.turno()
        self.assertEqual(ini.vida, ini.vida_maxima - 6)
        self.assertEqual(ini.ataque, ataque + 1)
        self.assertEqual(run.vida, 1000)

    def test_chefes_futuro(self):
        # Reflexo do Último Dia: telegrafado, interrompível.
        run, ini = self.preparar("O Espelho do Último Dia")
        ini.turnos = 2
        self.turno()
        self.assertEqual(
            ini.acao_pendente.chave, "reflexo_do_ultimo_dia")
        run.guarda = True
        self.turno()
        self.assertEqual(run.vida, 1000)

        run, ini = self.preparar("O Espelho do Último Dia")
        ini.turnos = 2
        self.turno()
        ini._ultimo_dano = 14
        self.turno()
        self.assertEqual(run.vida, 993)

        # Sussurro do Futuro: telegrafado; fica exposta enquanto pendente.
        run, ini = self.preparar("A Fenda que Escuta")
        ini.turnos = 3
        self.turno()
        self.assertEqual(
            ini.acao_pendente.chave, "sussurro_do_futuro")
        self.assertEqual(
            ini.habilidade.reduzir_dano_recebido(run, ini, 10), 13)
        run.guarda = True
        self.turno()
        self.assertEqual(run.vida, 1000)

        # Possibilidades Colhidas: duas Técnicas disparam a colheita.
        run, ini = self.preparar("O Colecionador de Futuros")
        run.golpe_tecnica = True
        self.golpe()
        self.golpe()
        self.assertEqual(getattr(ini, "_possibilidades"), 2)
        acao = ini.habilidade.escolher_acao(run, ini)
        self.assertEqual(acao.chave, "colheita_de_futuros")
        self.assertTrue(acao.prepara and acao.interrompivel)
        self.assertEqual(getattr(ini, "_possibilidades"), 0)

        # Ausência Planejada: some, dá Foco e volta com +4.
        run, ini = self.preparar("A Criança que Não Foi")
        run.foco = 1
        ini.turnos = 3
        self.turno()
        self.assertTrue(getattr(ini, "_crianca_ausente"))
        self.assertEqual(run.foco, 3)
        dano = self.golpe()
        self.assertLess(dano, 18)
        ini.turnos = 4
        self.turno()
        self.assertFalse(getattr(ini, "_crianca_ausente", False))
        self.assertEqual(run.vida, 1000 - (ini.ataque + 4))

        # Conclusão Antecipada: abaixo de 40% de vida, +2 em todo golpe.
        run, ini = self.preparar("O Devorador de Conclusões")
        run.vida = int(run.vida_maxima * 0.3)
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 12)
        ini.turnos = 3
        self.turno()
        self.assertEqual(
            ini.acao_pendente.chave, "conclusao_antecipada")

        # Espelho do Último Ato: espelha ataque (defesa) e cautela (dano).
        run, ini = self.preparar("A Última Testemunha")
        ini.memoria.observacoes = ["atacar"]
        ini.turnos = 2
        self.turno()
        self.assertTrue(getattr(ini, "_espelho_def"))
        self.assertEqual(
            ini.habilidade.reduzir_dano_recebido(run, ini, 10), 6)

        run, ini = self.preparar("A Última Testemunha")
        ini.memoria.observacoes = ["guardar"]
        ini.turnos = 6
        ini.habilidade.ao_turno(run, ini)
        self.assertTrue(getattr(ini, "_espelho_atk"))
        self.assertEqual(ini.habilidade.modificar_ataque(run, ini, 10), 13)

    def test_acoes_telegrafadas_de_chefes_podem_ser_interrompidas(self):
        casos = (
            ("O Barqueiro de Ossos", 3, "travessia_forcada"),
            ("O Titereiro de Válvulas", 2, "fios_cruzados"),
            ("O Relojoeiro do Fim", 4, "hora_final"),
            ("O Espelho do Último Dia", 2, "reflexo_do_ultimo_dia"),
            ("A Fenda que Escuta", 3, "sussurro_do_futuro"),
            ("O Devorador de Conclusões", 3, "conclusao_antecipada"),
        )
        for nome, turnos, chave in casos:
            with self.subTest(chefe=nome):
                run, ini = self.preparar(nome)
                ini.turnos = turnos
                self.turno()
                self.assertEqual(ini.acao_pendente.chave, chave)
                self.assertTrue(ini.acao_pendente.prepara)
                self.assertTrue(ini.acao_pendente.interrompivel)
                run.guarda = True
                self.turno()
                self.assertIsNone(ini.acao_pendente)
                self.assertEqual(run.vida, 1000)

        # A colheita do Colecionador também é telegrafada e interrompível.
        run, ini = self.preparar("O Colecionador de Futuros")
        ini._possibilidades = 2
        self.turno()
        self.assertEqual(ini.acao_pendente.chave, "colheita_de_futuros")
        run.guarda = True
        self.turno()
        self.assertIsNone(ini.acao_pendente)
        self.assertEqual(run.vida, 1000)

    def test_habilidades_sem_recursos_nao_quebram_o_combate(self):
        for nome in sorted(TODOS_ESPECIAIS):
            with self.subTest(criatura=nome):
                run, ini = self.preparar(nome)
                run.vida = run.vida_maxima = 10000
                run.ataque = 1
                run.foco = 0
                run.barreira = 0
                run.equipados = []
                run.itens_efeitos = []
                run.reliquias = []
                for _ in range(12):
                    with patch.object(
                            rt.random, "randint", return_value=1):
                        rt.executar_ataque(run, nunca_erra=True)
                    self.turno(sem_acao_padrao=False)
                self.assertGreater(run.vida, 0)
                self.assertGreater(ini.vida, 0)


class TestIntegracaoExpansao3(unittest.TestCase):
    def test_novos_entram_no_pool_certo(self):
        for spec in (c for c in rt.CRIATURAS
                     if c.nome in TODOS_ESPECIAIS):
            with self.subTest(criatura=spec.nome):
                def escolher(pool, alvo=spec):
                    self.assertIn(alvo, pool)
                    return alvo

                with patch.object(rt.random, "choice", side_effect=escolher):
                    inimigo = rt.criar_inimigo(
                        spec.nivel_minimo, categoria=spec.categoria)
                self.assertIs(inimigo.spec, spec)
                self.assertEqual(inimigo.spec.categoria, spec.categoria)

    def test_cadencia_de_encontros_nao_mudou(self):
        esperado = {
            1: "normal", 2: "normal", 3: "mini_chefe", 4: "normal",
            5: "chefe", 6: "mini_chefe", 7: "normal", 9: "mini_chefe",
            10: "chefe", 12: "mini_chefe", 15: "chefe",
            18: "mini_chefe", 20: "chefe", 25: "chefe", 30: "chefe",
            33: "mini_chefe",
        }
        with patch.object(rt.random, "random", return_value=1.0):
            for nivel, categoria in esperado.items():
                with self.subTest(nivel=nivel):
                    self.assertEqual(
                        rt.categoria_encontro(nivel), categoria)

    def test_inicio_e_fim_de_run_com_conteudo_novo(self):
        for spec in (c for c in rt.CRIATURAS
                     if c.nome in TODOS_ESPECIAIS):
            with self.subTest(criatura=spec.nome):
                run = novo_run(nivel=spec.nivel_minimo)
                with patch.object(rt, "sortear_evento", return_value=None), \
                        patch.object(rt.random, "choice", return_value=spec):
                    rt.preparar_combate(run, categoria=spec.categoria)
                self.assertEqual(run.inimigo.spec.nome, spec.nome)
                self.assertEqual(run.inimigo.spec.categoria, spec.categoria)

        run = novo_run(nivel=5)
        spec = next(c for c in rt.CRIATURAS
                    if c.nome == "O Barqueiro de Ossos")
        with patch.object(rt, "sortear_evento", return_value=None), \
                patch.object(rt.random, "choice", return_value=spec):
            rt.preparar_combate(run, categoria="chefe")
        run.inimigo.vida = 0

        cog = object.__new__(rt.RupturaTemporal)
        cog.bot = SimpleNamespace(dispatch=lambda *a, **k: None)
        cog.runs_ativas = {}
        with patch.object(rt, "award_rewards",
                          new=AsyncMock(return_value=True)):
            embed = asyncio.run(cog.finalizar_run(run, "derrota de teste"))

        self.assertTrue(run.finalizada)
        self.assertNotIn(run.user_id, cog.runs_ativas)
        self.assertIn("Resultado", embed.description)

    def test_recompensas_reutilizam_as_formulas_existentes(self):
        cog = object.__new__(rt.RupturaTemporal)
        cog.bot = SimpleNamespace(get_cog=lambda nome: None)
        multiplicador = {
            "mini_chefe": 1.8, "chefe": 2.7,
        }
        for spec in (c for c in rt.CRIATURAS
                     if c.nome in TODOS_ESPECIAIS):
            with self.subTest(criatura=spec.nome):
                run = novo_run(nivel=1)
                run.inimigo = rt.EnemyState(
                    spec=spec, nivel=spec.nivel_minimo,
                    vida=0, vida_maxima=spec.vida,
                    ataque=spec.ataque, defesa=spec.defesa)
                with patch.object(
                        rt, "award_rewards",
                        new=AsyncMock(return_value=True)), \
                        patch.object(rt, "sortear_evento", return_value=None), \
                        patch.object(rt.random, "random", return_value=1.0):
                    asyncio.run(cog.registrar_vitoria(run))

                self.assertEqual(
                    run.xp, int(spec.xp * multiplicador[spec.categoria]))
                self.assertEqual(run.abysmus, 0)
                self.assertEqual(run.abates, 1)
                self.assertEqual(
                    run.abatidos[f"{spec.categoria}|{spec.nome}"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
