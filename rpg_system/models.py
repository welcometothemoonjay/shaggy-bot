from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class Personagem:
    guild_id: int
    user_id: int
    nome: str
    classe_key: str
    nivel: int = 1
    xp: int = 0
    vida: int = 100
    reputacao: int = 0
    regiao: str = "dakor"
    profissao: str = "explorador"
    titulos: List[str] = field(default_factory=list)
    titulo_ativo: str = ""
    criado_em: float = 0.0
    atualizado_em: float = 0.0


@dataclass
class Item:
    key: str
    nome: str
    descricao: str = ""
    tipo: str = "material"
    raridade: str = "comum"
    preco: int = 0
    vendavel: bool = True
    empilhavel: bool = True
    efeitos: Dict[str, Any] = field(default_factory=dict)

    # Campos de apresentação do mercador. São persistidos no próprio
    # catálogo (código), nunca gerados a cada abertura da loja.
    utilidade: str = ""
    efeito: str = ""
    categoria: str = ""
    nivel: int = 1
    requisitos: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    unico: bool = False
    # Poder de combate quando o item é usado como arma. 0 significa arma
    # improvisada (materiais e consumíveis causam dano mínimo).
    poder_combate: int = 0

    def __post_init__(self):
        if not self.categoria:
            self.categoria = self.tipo
