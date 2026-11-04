# Sistema Central de Emojis

Gerenciador centralizado em `cogs/ultility.py`: `ShaggyEmojis`, instâncias `emojis`, `EMOJI` e função `get_emoji()`.

## Temas
- `rpg_textual` / `rpg`: identidade medieval/fantástica para RPG Textual
- `ruptura_temporal` / `ruptura`: identidade temporal para Ruptura Temporal (independente)
- `geral`: compartilhado

## Uso
```python
from cogs.ultility import ShaggyEmojis
embed.title = f"{ShaggyEmojis.rpg('missoes')} Missões"
# ou
from cogs.ultility import get_emoji
txt = f"{get_emoji('abysmus', tema='ruptura')} Abysmus"
```

## Regras
- Não espalhar IDs de emojis pelo projeto.
- Usar gerenciador central.
- Fallbacks Unicode caso emojis personalizados não existam.
- Verificação opcional por guild pode ser adicionada futuramente sem quebrar interface.
- Dois RPGs podem compartilhar infraestrutura, mas mantêm conjuntos temáticos independentes.
