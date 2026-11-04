"""Catálogo único de itens do RPG Textual.

O ``key`` é a identidade interna e nunca muda. O ``nome`` é o que o jogador
vê e pode digitar. Cada item precisa explicar o que é, para que serve e qual
é o seu efeito real no jogo.
"""
from typing import Dict, Optional, List

from .models import Item
from .tools import PICARETAS, FERRAMENTAS_GERAIS

CATALOGO_ITENS: Dict[str, Item] = {}


def _add(item: Item) -> None:
    CATALOGO_ITENS[item.key] = item


def _material(key, nome, descricao, preco, raridade="comum", utilidade="", efeito="", aliases=None):
    _add(Item(
        key=key,
        nome=nome,
        descricao=descricao,
        tipo="material",
        raridade=raridade,
        preco=preco,
        categoria="material",
        utilidade=utilidade or "Pode ser vendido no mercador e usado nas receitas das profissões.",
        efeito=efeito or "Sem efeito de combate; é um recurso de progressão econômica.",
        aliases=aliases or [],
        nivel=1,
    ))


def _consumivel(key, nome, descricao, preco, utilidade, efeito, aliases=None, raridade="comum"):
    _add(Item(
        key=key,
        nome=nome,
        descricao=descricao,
        tipo="consumivel",
        raridade=raridade,
        preco=preco,
        categoria="consumivel",
        utilidade=utilidade,
        efeito=efeito,
        aliases=aliases or [],
        nivel=1,
    ))


# ---------------- Materiais de mineração ----------------
_material("pedra", "Pedra", "Um fragmento comum de rocha, fácil de encontrar em qualquer região.", 5,
          utilidade="Material básico usado para artesanato e vendido por pouco no mercador.")
_material("carvao", "Carvão", "Rocha escura e quebradiça que queima por muito tempo.", 10,
          utilidade="Combustível de forja e ingrediente da receita de lingote de ferro.")
_material("cobre", "Minério de Cobre", "Um minério maleável com veios alaranjados.", 18,
          utilidade="Metal comum usado em ferramentas e vendido por um preço razoável.")
_material("ferro", "Minério de Ferro", "Minério denso e pesado, base de quase toda forja.", 28,
          utilidade="Ingrediente da receita de lingote de ferro e material de venda valioso.")
_material("aco", "Fragmento de Aço", "Uma lasca de aço temperado, dura e afiada nas bordas.", 45, "incomum",
          utilidade="Material incomum obtido com picaretas de aço ou superiores.")
_material("ouro", "Ouro Bruto", "Pepitas douradas incrustadas em rocha escura.", 70, "raro",
          utilidade="Metal raro e valioso; exige picareta de ouro ou superior para ser extraído.")
_material("diamante", "Diamante Bruto", "Um cristal incrivelmente duro que reflete a luz em facas.", 120, "epico",
          utilidade="Material épico de venda e objetivo de conquistas de mineração.")
_material("gema", "Gema Bruta", "Uma pedra preciosa ainda coberta por rocha.", 50, "raro",
          utilidade="Item raro de venda; encontrado em regiões costeiras e montanhosas.")
_material("cristal", "Cristal de Abysmus", "Um cristal que vibra levemente perto de energia antiga.", 80, "raro",
          utilidade="Cristal raro usado como prova de progressão e vendido por bom preço.")
_material("cristal_arcano", "Cristal Arcano", "Um cristal azulado percorrido por runas que mudam de posição.", 180, "epico",
          utilidade="Material épico extraído apenas com Picareta Arcana ou superior.")
_material("cristal_abissal", "Cristal Abissal", "Uma lasca escura que pulsa com luz vermelha e preta.", 320, "epico",
          utilidade="Material épico do Abismo Umbral; exige Picareta Abissal ou superior.")
_material("essencia_infernal", "Essência Infernal", "Uma centelha líquida que queima sem consumir o frasco.", 600, "lendario",
          utilidade="Material lendário extraído somente com a Picareta Infernal.")

# ---------------- Recursos naturais e de profissões ----------------
_material("madeira", "Madeira", "Tábuas e galhos secos, leves e fáceis de transportar.", 8,
          utilidade="Recurso do Lenhador; ingrediente da receita de artesanato.")
_material("couro", "Couro", "Pele curtida obtida em atividades de caça.", 12,
          utilidade="Material de venda obtido pelo Caçador.")
_material("carne", "Carne", "Carne fresca de caça, própria para consumo ou troca.", 10,
          utilidade="Recurso do Caçador; vendido no mercador.")
_material("pena", "Pena", "Uma pena leve e resistente, útil para pequenos artefatos.", 14,
          utilidade="Material incomum de venda encontrado em explorações e caçadas.")
_material("cogumelo", "Cogumelo", "Um cogumelo de sombra com propriedades medicinais.", 16, "incomum",
          utilidade="Recurso do Herbalista; ingrediente de venda e coleta.")
_material("concha", "Concha", "Uma concha marinha polida pela maré.", 18, "incomum",
          utilidade="Item de venda encontrado na Costa de Âmbar.")
_material("lingote_ferro", "Lingote de Ferro", "Ferro refinado em formato de barra, pronto para uso.", 60, "incomum",
          utilidade="Produzido pelo Ferreiro a partir de 2 Minérios de Ferro e 1 Carvão.")
_material("artesanato", "Artesanato", "Um objeto feito à mão que combina madeira e pedra.", 40,
          utilidade="Produzido pelo Artesão a partir de 2 Madeiras e 1 Pedra; vendido no mercador.")

# ---------------- Consumíveis / recursos de coleta ----------------
_consumivel("peixe", "Peixe", "Um peixe fresco, ainda com escamas brilhantes.", 12,
            "Recurso do Pescador; pode ser vendido no mercador.",
            "Sem efeito de combate implementado; é um recurso de venda.")
_consumivel("erva", "Erva Medicinal", "Folhas verdes com aroma forte, usadas em preparos tradicionais.", 15,
            "Recurso do Herbalista e ingrediente de coleta.",
            "Sem efeito de cura automático; é um recurso de venda e profissão.")

# ---------------- Picaretas e ferramentas ----------------
_RARIDADE_FERRAMENTA = {
    1: "comum", 2: "comum", 3: "comum", 4: "comum",
    5: "incomum", 6: "incomum", 7: "raro", 8: "raro",
    9: "epico", 10: "lendario",
}

for key, ferramenta in {**PICARETAS, **FERRAMENTAS_GERAIS}.items():
    _add(Item(
        key=key,
        nome=ferramenta.nome,
        descricao=ferramenta.descricao,
        tipo="ferramenta",
        raridade=_RARIDADE_FERRAMENTA.get(ferramenta.nivel, "comum"),
        preco=ferramenta.preco,
        categoria=ferramenta.categoria,
        nivel=ferramenta.nivel,
        utilidade=ferramenta.utilidade,
        # O efeito de combate é adicional ao efeito principal da ferramenta
        # e reflete o dano real usado por rpg_system/combat.py.
        efeito=(
            f"{ferramenta.efeito} · Combate: "
            f"{4 + ferramenta.nivel * 2 - 1}–{4 + ferramenta.nivel * 2 + 2} de dano."
        ),
        requisitos=dict(ferramenta.requisitos),
        aliases=list(ferramenta.aliases),
        poder_combate=4 + ferramenta.nivel * 2,
    ))


def obter_item(chave: str) -> Optional[Item]:
    return CATALOGO_ITENS.get(chave)


def listar_itens_por_tipo(tipo: str) -> List[Item]:
    return [item for item in CATALOGO_ITENS.values() if item.tipo == tipo]


def listar_itens_por_categoria(categoria: str) -> List[Item]:
    if categoria in ("todas", "", None):
        return list(CATALOGO_ITENS.values())
    return [item for item in CATALOGO_ITENS.values() if item.categoria == categoria or item.tipo == categoria]


def nome_item(chave: str) -> str:
    item = CATALOGO_ITENS.get(chave)
    return item.nome if item else chave
