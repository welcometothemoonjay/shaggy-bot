"""Mundo do RPG Textual.

Mantém o universo existente de Dakor e o expande de forma coerente. Toda a
mecânica (recompensas, itens, eventos) é decidida em Python; as descrições
podem ser enriquecidas pelo OpenRouter, mas o texto da IA nunca altera o
estado do jogo.
"""

REGIOS = {
    "dakor": {
        "key": "dakor",
        "nome": "Dakor",
        "descricao": "Planícies abertas cortadas por trilhas antigas, o coração do mundo conhecido.",
        "bioma": "planície",
        "clima": "temperado",
        "nivel_min": 1,
        "locais": ["planicies_dakor", "floresta_verde", "mina_abandonada"],
        "materiais": ["pedra", "carvao", "cobre", "ferro"],
        "coins_mult": 0.85,
        "qtd_mult": 1.0,
    },
    "costa_ambar": {
        "key": "costa_ambar",
        "nome": "Costa de Âmbar",
        "descricao": "Praias douradas e grutas marinhas onde o sal se mistura ao cheiro de madeira molhada.",
        "bioma": "litoral",
        "clima": "ameno e salgado",
        "nivel_min": 2,
        "locais": ["praia_ambar", "grutas_costeiros"],
        "materiais": ["pedra", "carvao", "cobre", "gema"],
        "coins_mult": 1.0,
        "qtd_mult": 1.05,
    },
    "picos_gelo": {
        "key": "picos_gelo",
        "nome": "Picos de Gelo",
        "descricao": "Montanhas cobertas por neve eterna, com veios de cristal brilhando sob a camada de gelo.",
        "bioma": "montanha",
        "clima": "frio cortante",
        "nivel_min": 4,
        "locais": ["vale_nevado", "caverna_gelo"],
        "materiais": ["pedra", "ferro", "gema", "cristal"],
        "coins_mult": 1.15,
        "qtd_mult": 1.12,
    },
    "deserto_cinzas": {
        "key": "deserto_cinzas",
        "nome": "Deserto de Cinzas",
        "descricao": "Dunas escuras e ruínas calcinadas guardam metais raros e ecos de um passado violento.",
        "bioma": "deserto vulcânico",
        "clima": "árido e abafado",
        "nivel_min": 6,
        "locais": ["dunas_cinzas", "ruinas_calcificadas"],
        "materiais": ["carvao", "ferro", "ouro", "diamante"],
        "coins_mult": 1.3,
        "qtd_mult": 1.2,
    },
    "abismo_umbral": {
        "key": "abismo_umbral",
        "nome": "Abismo Umbral",
        "descricao": "Fendas profundas onde a luz rareia e a pedra pulsa como se respirasse.",
        "bioma": "subterrâneo",
        "clima": "úmido e opressivo",
        "nivel_min": 9,
        "locais": ["fenda_umbral", "coracao_abissal"],
        "materiais": ["ferro", "cristal", "cristal_abissal", "essencia_infernal", "diamante"],
        "coins_mult": 1.5,
        "qtd_mult": 1.28,
    },
}

LOCAIS = {
    "planicies_dakor": {
        "key": "planicies_dakor",
        "nome": "Planícies de Dakor",
        "regiao": "dakor",
        "bioma": "planície",
        "clima": "temperado",
        "descricao_base": "As planícies de Dakor se estendem ao horizonte. Gramados dourados balançam ao vento e trilhas desgastadas levam a destinos desconhecidos.",
        "caracteristicas": ["gramados dourados", "trilhas de carroça", "marco de pedra antigo"],
        "historia": "Dakor foi o primeiro assentamento a erguer um marco para viajantes perdidos.",
        "elementos": ["vento constante", "pássaros de planície", "poeira dourada"],
        "coletas": ["madeira", "erva", "pedra"],
        "especial": False,
    },
    "floresta_verde": {
        "key": "floresta_verde",
        "nome": "Floresta Verde",
        "regiao": "dakor",
        "bioma": "floresta",
        "clima": "úmido",
        "descricao_base": "Árvores antigas se erguem em volta de você. Raios de sol filtram entre as folhas criando padrões dançantes no chão coberto de musgo.",
        "caracteristicas": ["árvores centenárias", "chão de musgo", "riacho escondido"],
        "historia": "Os lenhadores de Dakor juram que a floresta cresce mais rápido do que conseguem cortar.",
        "elementos": ["canto de aves", "umidade nas folhas", "cogumelos luminosos"],
        "coletas": ["madeira", "erva", "cogumelo", "carvao"],
        "especial": False,
    },
    "mina_abandonada": {
        "key": "mina_abandonada",
        "nome": "Mina Abandonada",
        "regiao": "dakor",
        "bioma": "caverna",
        "clima": "frio e úmido",
        "descricao_base": "Túneis escavados há muito tempo se ramificam nas profundezas. O ar é denso e ecoa com o som distante de goteiras.",
        "caracteristicas": ["vigas de madeira apodrecidas", "veios minerais expostos", "poços verticais"],
        "historia": "A mina foi fechada após um desabamento; dizem que os melhores veios ficaram intactos.",
        "elementos": ["goteiras", "poeira de carvão", "correntes de ar frio"],
        "coletas": ["pedra", "carvao", "ferro", "cobre"],
        "especial": False,
    },
    "praia_ambar": {
        "key": "praia_ambar",
        "nome": "Praia de Âmbar",
        "regiao": "costa_ambar",
        "bioma": "praia",
        "clima": "ameno",
        "descricao_base": "A areia clara brilha sob o sol e ondas tranquilas depositam conchas e fragmentos de âmbar na costa.",
        "caracteristicas": ["areia clara", "recifes rasos", "naufrágio ao longe"],
        "historia": "Mercadores antigos usavam a praia como ponto de troca antes das estradas de Dakor existirem.",
        "elementos": ["brisa salgada", "gaivotas", "maré mansa"],
        "coletas": ["concha", "peixe", "pedra", "erva"],
        "especial": False,
    },
    "grutas_costeiros": {
        "key": "grutas_costeiros",
        "nome": "Grutas Costeiras",
        "regiao": "costa_ambar",
        "bioma": "gruta litorânea",
        "clima": "úmido e fresco",
        "descricao_base": "A água do mar invade pequenas grutas, criando poças cristalinas e paredes cobertas de minerais.",
        "caracteristicas": ["poças de maré", "estalactites salgadas", "passagens alagadas"],
        "historia": "Contrabandistas escondiam cargas nas grutas até que a maré alta os surpreendeu.",
        "elementos": ["eco da água", "sal cristalizado", "caranguejos"],
        "coletas": ["pedra", "cobre", "gema", "concha"],
        "especial": False,
    },
    "vale_nevado": {
        "key": "vale_nevado",
        "nome": "Vale Nevado",
        "regiao": "picos_gelo",
        "bioma": "vale alpino",
        "clima": "frio seco",
        "descricao_base": "Um vale silencioso se abre entre picos brancos. Pegadas antigas somem sob a neve recente.",
        "caracteristicas": ["neve profunda", "pinhais retorcidos", "abrigo de pedra"],
        "historia": "Poucos viajantes atravessam o vale; os que voltam falam de luzes sob o gelo.",
        "elementos": ["vento cortante", "neve fina", "silêncio amplo"],
        "coletas": ["madeira", "erva", "pedra", "gema"],
        "especial": False,
    },
    "caverna_gelo": {
        "key": "caverna_gelo",
        "nome": "Caverna de Gelo",
        "regiao": "picos_gelo",
        "bioma": "caverna glacial",
        "clima": "congelante",
        "descricao_base": "Paredes de gelo azul refletem uma luz fraca. O chão range a cada passo e veios de cristal cruzam a rocha.",
        "caracteristicas": ["gelo azulado", "veios de cristal", "lago congelado"],
        "historia": "A caverna é evitada por mineiros supersticiosos que dizem ouvir a montanha respirar.",
        "elementos": ["ar congelante", "reflexos azuis", "estalos do gelo"],
        "coletas": ["ferro", "gema", "cristal", "pedra"],
        "especial": False,
    },
    "dunas_cinzas": {
        "key": "dunas_cinzas",
        "nome": "Dunas de Cinzas",
        "regiao": "deserto_cinzas",
        "bioma": "deserto vulcânico",
        "clima": "árido",
        "descricao_base": "Dunas de cinza escura se estendem até onde a vista alcança. O calor sobe do chão e distorce o horizonte.",
        "caracteristicas": ["areia cinzenta", "rochas vulcânicas", "ossadas expostas"],
        "historia": "A região já foi fértil antes de uma erupção antiga cobrir tudo com cinzas.",
        "elementos": ["calor seco", "vento carregado de pó", "miragens"],
        "coletas": ["carvao", "ferro", "ouro", "pedra"],
        "especial": False,
    },
    "ruinas_calcificadas": {
        "key": "ruinas_calcificadas",
        "nome": "Ruínas Calcinadas",
        "regiao": "deserto_cinzas",
        "bioma": "ruínas",
        "clima": "árido e abafado",
        "descricao_base": "Colunas quebradas e muros escurecidos pelo fogo formam um labirinto silencioso no meio das dunas.",
        "caracteristicas": ["colunas de basalto", "inscrições apagadas", "fornalhas antigas"],
        "historia": "Uma fortaleza de ferreiros desapareceu na erupção; suas forjas ainda guardam metais raros.",
        "elementos": ["eco entre ruínas", "cheiro de enxofre", "sombras longas"],
        "coletas": ["ferro", "ouro", "diamante", "carvao"],
        "especial": True,
    },
    "fenda_umbral": {
        "key": "fenda_umbral",
        "nome": "Fenda Umbral",
        "regiao": "abismo_umbral",
        "bioma": "subterrâneo",
        "clima": "úmido",
        "descricao_base": "Uma fenda larga desce para o escuro. Veios de luz mineral pulsam nas paredes como veias.",
        "caracteristicas": ["paredes pulsantes", "abismo sem fundo", "ponte natural de pedra"],
        "historia": "Nenhum mapa registra o fim da fenda; apenas o começo de descidas que nunca retornaram.",
        "elementos": ["ar pesado", "pulsos de luz", "gotas distantes"],
        "coletas": ["ferro", "cristal", "cristal_abissal", "pedra"],
        "especial": False,
    },
    "coracao_abissal": {
        "key": "coracao_abissal",
        "nome": "Coração Abissal",
        "regiao": "abismo_umbral",
        "bioma": "câmara abissal",
        "clima": "opressivo e quente",
        "descricao_base": "Uma câmara imensa pulsa com luz vermelha e preta. Cristais abissais crescem como raízes ao redor de uma pedra central.",
        "caracteristicas": ["pedra central pulsante", "cristais abissais", "calor vindo de baixo"],
        "historia": "O Coração é mencionado em sussurros: alguns dizem que é uma ferida do mundo, outros, uma forja adormecida.",
        "elementos": ["batimento lento", "luz vermelha", "calor de forja"],
        "coletas": ["cristal_abissal", "essencia_infernal", "diamante", "cristal"],
        "especial": True,
    },
}

# Eventos são apenas narrativa + bônus pequenos definidos pelo código.
EVENTOS = {
    "dakor": [
        {"key": "viajante", "texto": "Um viajante acena de longe e segue seu caminho, deixando uma moeda caída na trilha.", "xp": 4, "moedas": 2},
        {"key": "ninho", "texto": "Você encontra um ninho abandonado entre as pedras e recolhe penas úteis.", "xp": 3, "item": "pena"},
        {"key": "erva_rara", "texto": "Um tufo de erva medicinal cresce afastado da trilha principal.", "xp": 3, "item": "erva"},
    ],
    "costa_ambar": [
        {"key": "maré", "texto": "A maré baixa revela conchas e pequenos fragmentos de âmbar.", "xp": 4, "item": "concha"},
        {"key": "pescador", "texto": "Um pescador solitário oferece algumas moedas por ajuda com a rede.", "xp": 4, "moedas": 3},
        {"key": "baú", "texto": "Entre as rochas, uma caixa de madeira apodrecida ainda guarda algo útil.", "xp": 5, "item": "cobre"},
    ],
    "picos_gelo": [
        {"key": "abrigo", "texto": "Você encontra um abrigo de pedra seco e recupera o fôlego antes de continuar.", "xp": 5},
        {"key": "cristal", "texto": "Um cristal solto se desprende de uma parede de gelo e cai aos seus pés.", "xp": 5, "item": "cristal"},
        {"key": "pegadas", "texto": "Pegadas antigas levam a uma pequena reserva de ferro esquecida.", "xp": 4, "item": "ferro"},
    ],
    "deserto_cinzas": [
        {"key": "miragem", "texto": "Uma miragem quase o engana, mas o reflexo revela um veio de ouro sob a cinza.", "xp": 6, "item": "ouro"},
        {"key": "forja", "texto": "Uma forja antiga ainda guarda carvão seco o bastante para ser útil.", "xp": 5, "item": "carvao"},
        {"key": "caravana", "texto": "Você encontra restos de uma caravana e recupera moedas espalhadas.", "xp": 5, "moedas": 4},
    ],
    "abismo_umbral": [
        {"key": "pulso", "texto": "A pedra pulsa e uma lasca de cristal abissal se solta da parede.", "xp": 8, "item": "cristal_abissal"},
        {"key": "sussurro", "texto": "Um sussurro distante parece indicar um caminho seguro por alguns metros.", "xp": 7},
        {"key": "calor", "texto": "Uma fenda quente exala uma centelha de essência infernal.", "xp": 8, "item": "essencia_infernal"},
    ],
}


# Compatibilidade: o código novo usa o nome plural correto em português,
# enquanto o módulo original expunha ``REGIOS``. Ambos apontam para o mesmo
# dicionário, sem duplicar dados.
REGIOES = REGIOS


def obter_regiao(chave: str) -> dict | None:
    return REGIOES.get(chave)


def obter_local(chave: str) -> dict | None:
    return LOCAIS.get(chave)


def regiao_do_local(local_key: str) -> dict | None:
    local = LOCAIS.get(local_key)
    if not local:
        return None
    return REGIOES.get(local["regiao"])


def locais_da_regiao(regiao_key: str) -> list[dict]:
    regiao = REGIOES.get(regiao_key)
    if not regiao:
        return []
    return [LOCAIS[k] for k in regiao["locais"] if k in LOCAIS]


def regioes_disponiveis(nivel_personagem: int = 1) -> list[dict]:
    res = []
    for regiao in REGIOES.values():
        item = dict(regiao)
        item["desbloqueada"] = nivel_personagem >= regiao["nivel_min"]
        res.append(item)
    return sorted(res, key=lambda r: r["nivel_min"])
