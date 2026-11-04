"""Ferramentas e tabelas de mineração.

A identidade real de cada ferramenta é a ``key``. O nome é apenas a forma de
interação do jogador. Os atributos abaixo são usados diretamente pelo sistema
de mineração, mercado e interface.
"""
from dataclasses import dataclass, field
from typing import Dict, Any

# Progressão: Madeira(1) -> Pedra(2) -> Cobre(3) -> Ferro(4) -> Aço(5) ->
# Ouro(6) -> Diamante(7) -> Arcano(8) -> Abissal(9) -> Infernal(10).
CHANCES_COINS = {
    1: 0.10,
    2: 0.15,
    3: 0.20,
    4: 0.25,
    5: 0.30,
    6: 0.40,
    7: 0.50,
    8: 0.60,
    9: 0.75,
    10: 1.00,
}

# Materiais que a mineração pode extrair. ``tier`` é a picareta mínima.
MATERIAIS_MINERAIS = {
    "pedra": {"tier": 1, "peso": 40, "qtd": (1, 3)},
    "carvao": {"tier": 1, "peso": 24, "qtd": (1, 2)},
    "cobre": {"tier": 2, "peso": 20, "qtd": (1, 2)},
    "ferro": {"tier": 3, "peso": 18, "qtd": (1, 2)},
    "gema": {"tier": 4, "peso": 10, "qtd": (1, 1)},
    "cristal": {"tier": 5, "peso": 8, "qtd": (1, 1)},
    "aco": {"tier": 5, "peso": 7, "qtd": (1, 1)},
    "ouro": {"tier": 6, "peso": 6, "qtd": (1, 1)},
    "diamante": {"tier": 7, "peso": 4, "qtd": (1, 1)},
    "cristal_arcano": {"tier": 8, "peso": 3, "qtd": (1, 1)},
    "cristal_abissal": {"tier": 9, "peso": 2, "qtd": (1, 1)},
    "essencia_infernal": {"tier": 10, "peso": 1, "qtd": (1, 1)},
}


@dataclass
class Ferramenta:
    key: str
    nome: str
    descricao: str
    categoria: str  # picareta, machado, foice, etc.
    nivel: int      # 1 Madeira -> 10 Infernal
    preco: int
    eficiencia: float = 1.0
    chance_coins: float = 0.0
    multiplicador_materiais: float = 1.0
    bonus: Dict[str, float] = field(default_factory=dict)
    requisitos: Dict[str, Any] = field(default_factory=dict)
    durabilidade: int = 0  # 0 = durabilidade não implementada
    unico: bool = False
    vendavel: bool = True
    utilidade: str = ""
    efeito: str = ""
    aliases: list[str] = field(default_factory=list)


def _picareta(key, nome, nivel, preco, eficiencia, chance, qtd_mult, requisito, descricao, utilidade, efeito):
    return Ferramenta(
        key=key,
        nome=nome,
        descricao=descricao,
        categoria="picareta",
        nivel=nivel,
        preco=preco,
        eficiencia=eficiencia,
        chance_coins=chance,
        multiplicador_materiais=qtd_mult,
        bonus={"mineracao": round(eficiencia - 1.0, 2)},
        requisitos={"nivel_personagem": requisito},
        utilidade=utilidade,
        efeito=efeito,
        aliases=[f"picareta {nome.split()[-1].lower()}"],
    )


PICARETAS: Dict[str, Ferramenta] = {
    "picareta_madeira": _picareta(
        "picareta_madeira", "Picareta de Madeira", 1, 50, 0.8, CHANCES_COINS[1], 1.00, 1,
        "Uma picareta simples, montada com madeira resistente. Serve para arranhar a superfície e aprender o ofício.",
        "Permite minerar pedra e carvão em Dakor. É a ferramenta inicial do Minerador.",
        "Eficiência 0.8x · 10% de chance de encontrar Abysmus por mineração.",
    ),
    "picareta_pedra": _picareta(
        "picareta_pedra", "Picareta de Pedra", 2, 120, 0.9, CHANCES_COINS[2], 1.10, 1,
        "Lascada em pedra dura e amarrada com cordas, suporta mais impacto que a madeira.",
        "Desbloqueia cobre e melhora a quantidade de materiais extraídos.",
        "Eficiência 0.9x · 15% de chance de Abysmus · extrai cobre.",
    ),
    "picareta_cobre": _picareta(
        "picareta_cobre", "Picareta de Cobre", 3, 250, 1.0, CHANCES_COINS[3], 1.25, 2,
        "O cobre maleável absorve impactos sem trincar facilmente, uma escolha equilibrada.",
        "Desbloqueia minério de ferro e aumenta o rendimento por mineração.",
        "Eficiência 1.0x · 20% de chance de Abysmus · extrai ferro.",
    ),
    "picareta_ferro": _picareta(
        "picareta_ferro", "Picareta de Ferro", 4, 500, 1.15, CHANCES_COINS[4], 1.40, 3,
        "Uma ferramenta resistente, forjada para suportar trabalhos prolongados em rochas densas. Seu peso exige força, mas sua estrutura permite escavações mais eficientes.",
        "Permite extrair materiais intermediários e aumenta a chance de encontrar moedas durante a mineração.",
        "Eficiência 1.15x · 25% de chance de Abysmus · chance de gemas.",
    ),
    "picareta_aco": _picareta(
        "picareta_aco", "Picareta de Aço", 5, 900, 1.35, CHANCES_COINS[5], 1.60, 4,
        "Aço temperado em forjas de Dakor. O fio mantém-se afiado mesmo contra rocha vulcânica.",
        "Desbloqueia fragmentos de aço e cristais, além de render mais materiais por extração.",
        "Eficiência 1.35x · 30% de chance de Abysmus · extrai aço e cristal.",
    ),
    "picareta_ouro": _picareta(
        "picareta_ouro", "Picareta de Ouro", 6, 1500, 1.5, CHANCES_COINS[6], 1.80, 5,
        "O ouro não é o metal mais duro, mas conduz energia com facilidade e encontra veios com precisão estranha.",
        "Aumenta bastante o achado de Abysmus e desbloqueia ouro bruto nas regiões áridas.",
        "Eficiência 1.5x · 40% de chance de Abysmus · extrai ouro.",
    ),
    "picareta_diamante": _picareta(
        "picareta_diamante", "Picareta de Diamante", 7, 3000, 1.8, CHANCES_COINS[7], 2.10, 6,
        "Cristais de diamante formam uma ponta quase indestrutível, capaz de abrir veios profundos.",
        "Extração superior de minerais raros, incluindo diamantes, e 50% de chance de Abysmus.",
        "Eficiência 1.8x · 50% de chance de Abysmus · extrai diamante.",
    ),
    "picareta_arcana": _picareta(
        "picareta_arcana", "Picareta Arcana", 8, 6000, 2.1, CHANCES_COINS[8], 2.40, 8,
        "Runas antigas percorrem a haste e a ponta vibra em ressonância com veios de cristal.",
        "Desbloqueia cristal arcano e melhora muito o rendimento e as moedas encontradas.",
        "Eficiência 2.1x · 60% de chance de Abysmus · extrai cristal arcano.",
    ),
    "picareta_abissal": _picareta(
        "picareta_abissal", "Picareta Abissal", 9, 12000, 2.6, CHANCES_COINS[9], 2.80, 10,
        "Forjada nas profundezas, sua pedra parece respirar e atrair minerais para a ponta.",
        "Acesso a cristais abissais e rendimento muito alto, com 75% de chance de Abysmus.",
        "Eficiência 2.6x · 75% de chance de Abysmus · extrai cristal abissal.",
    ),
    "picareta_infernal": _picareta(
        "picareta_infernal", "Picareta Infernal", 10, 25000, 3.2, CHANCES_COINS[10], 3.20, 12,
        "Forjada no calor infernal, a picareta mantém uma brasa viva na ponta. Nenhuma rocha resiste por muito tempo.",
        "Sempre encontra Abysmus em minerações válidas e desbloqueia a Essência Infernal.",
        "Eficiência 3.2x · 100% de chance de Abysmus · extrai essência infernal.",
    ),
}

FERRAMENTAS_GERAIS: Dict[str, Ferramenta] = {
    "machado_madeira": Ferramenta(
        key="machado_madeira", nome="Machado de Madeira",
        descricao="Um machado simples para cortar galhos e troncos finos.",
        categoria="machado", nivel=1, preco=40, eficiencia=0.8,
        bonus={"lenhador": 0.05},
        utilidade="Aumenta o rendimento de madeira ao trabalhar como Lenhador.",
        efeito="Bônus de +5% na coleta de madeira.",
        aliases=["machado"],
    ),
    "machado_ferro": Ferramenta(
        key="machado_ferro", nome="Machado de Ferro",
        descricao="Lâmina pesada e afiada, feita para derrubar árvores com poucos golpes.",
        categoria="machado", nivel=4, preco=450, eficiencia=1.2,
        bonus={"lenhador": 0.2},
        requisitos={"nivel_personagem": 3},
        utilidade="Aumenta bastante o rendimento de madeira do Lenhador.",
        efeito="Bônus de +20% na coleta de madeira.",
        aliases=["machado de ferro"],
    ),
}

FERRAMENTAS: Dict[str, Ferramenta] = {**PICARETAS, **FERRAMENTAS_GERAIS}


def obter_picareta(key: str) -> Ferramenta | None:
    return PICARETAS.get(key)


def obter_ferramenta(key: str) -> Ferramenta | None:
    return FERRAMENTAS.get(key)


def listar_picaretas():
    return sorted(PICARETAS.values(), key=lambda p: p.nivel)


def chance_moeda(key: str) -> float:
    p = obter_picareta(key)
    return p.chance_coins if p else 0.0


def get_pickaxe_efficiency(key: str) -> float:
    p = obter_picareta(key)
    return p.eficiencia if p else 0.0


def validar_tabela_chances() -> list[str]:
    """Valida a configuração matemática das chances de moeda."""
    erros = []
    esperado = {
        1: 0.10, 2: 0.15, 3: 0.20, 4: 0.25, 5: 0.30,
        6: 0.40, 7: 0.50, 8: 0.60, 9: 0.75, 10: 1.00,
    }
    for tier, chance in esperado.items():
        if CHANCES_COINS.get(tier) != chance:
            erros.append(f"tier {tier}: esperado {chance}, encontrado {CHANCES_COINS.get(tier)}")
    for p in PICARETAS.values():
        if p.chance_coins != CHANCES_COINS.get(p.nivel):
            erros.append(f"{p.key}: chance {p.chance_coins} != tier {p.nivel}")
    if len(PICARETAS) != 10:
        erros.append(f"esperadas 10 picaretas, encontradas {len(PICARETAS)}")
    return erros
