# MERCADO — Catálogo real

Fonte: `rpg_system/items.py` (catálogo), `rpg_system/tools.py`
(ferramentas) e `rpg_system/market_v2.py` (regras de compra/venda).

O `key` é a identidade interna permanente. O jogador compra e vende pelo
**nome**, com comparação sem maiúsculas/minúsculas e sem acentos. Nomes
ambíguos nunca são comprados automaticamente: o sistema devolve as opções.

## Regras de compra

1. Resolver o nome informado para um `key` do catálogo.
2. Se houver mais de um item compatível, interromper e listar as opções.
3. Verificar nível de personagem e requisitos de profissão.
4. Verificar saldo.
5. Em uma única transação SQLite: debitar Abysmus, adicionar o item ao
   inventário, registrar em `rpg_transacoes` e em `rpg_acoes`.
6. Se qualquer etapa falhar, a transação inteira é revertida. **Nunca há
   cobrança sem entrega do item.**
7. Quantidade permitida: 1 a 99.

Desconto de Mercador: `1% × nível`, limitado a **15%**.
Venda: `preço base × 50% × (1 + bônus)`, com bônus de Mercador de `1% × nível`,
limitado a **10%**. O preço de venda nunca chega ao preço de compra.

## Ferramentas — picaretas

| Key | Nome | Tier | Preço | Requisito | Eficiência | Materiais | Chance de Abysmus |
|---|---|---:|---:|---|---:|---:|---:|
| `picareta_madeira` | Picareta de Madeira | 1 | 50 | Nível 1 | 0.8x | 1.00x | 10% |
| `picareta_pedra` | Picareta de Pedra | 2 | 120 | Nível 1 | 0.9x | 1.10x | 15% |
| `picareta_cobre` | Picareta de Cobre | 3 | 250 | Nível 2 | 1.0x | 1.25x | 20% |
| `picareta_ferro` | Picareta de Ferro | 4 | 500 | Nível 3 | 1.15x | 1.40x | 25% |
| `picareta_aco` | Picareta de Aço | 5 | 900 | Nível 4 | 1.35x | 1.60x | 30% |
| `picareta_ouro` | Picareta de Ouro | 6 | 1.500 | Nível 5 | 1.5x | 1.80x | 40% |
| `picareta_diamante` | Picareta de Diamante | 7 | 3.000 | Nível 6 | 1.8x | 2.10x | 50% |
| `picareta_arcana` | Picareta Arcana | 8 | 6.000 | Nível 8 | 2.1x | 2.40x | 60% |
| `picareta_abissal` | Picareta Abissal | 9 | 12.000 | Nível 10 | 2.6x | 2.80x | 75% |
| `picareta_infernal` | Picareta Infernal | 10 | 25.000 | Nível 12 | 3.2x | 3.20x | 100% |

Efeitos reais:

- **Eficiência** participa do bônus de mineração e da progressão percebida;
  o multiplicador de materiais é aplicado diretamente à quantidade extraída.
- **Materiais** multiplica a quantidade de cada material sorteado.
- **Chance de Abysmus** é a probabilidade exata de encontrar moedas em uma
  mineração válida. A Picareta Infernal sempre encontra.
- Picaretas de tier maior também habilitam materiais de tier maior e fazem
  mais rolagens de materiais (tier 4+: 2 rolagens; tier 7+: 3; tier 10: 4).
- A picareta equipada tem prioridade; sem equipamento, a melhor picareta
  possuída é usada automaticamente. Sem nenhuma picareta, não é possível
  minerar.
- **Combate**: cada ferramenta tem `poder_combate = 4 + tier × 2`. O dano
  exibido no item é `poder_combate - 1` até `poder_combate + 2`. Machados e
  picaretas podem ser usados em `/combate arma:Nome`.

## Ferramentas — machados

| Key | Nome | Nível | Preço | Requisito | Efeito |
|---|---|---:|---:|---|---|
| `machado_madeira` | Machado de Madeira | 1 | 40 | Nível 1 | +5% na coleta do Lenhador |
| `machado_ferro` | Machado de Ferro | 4 | 450 | Nível 3 | +20% na coleta do Lenhador |

## Materiais

Todos os materiais podem ser vendidos no mercador e usados nas receitas
quando indicado.

| Key | Nome | Preço | Raridade | Utilidade |
|---|---|---:|---|---|
| `pedra` | Pedra | 5 | comum | Material básico de artesanato; vendido barato |
| `carvao` | Carvão | 10 | comum | Combustível de forja e ingrediente de Lingote de Ferro |
| `cobre` | Minério de Cobre | 18 | comum | Metal comum de ferramentas e venda |
| `ferro` | Minério de Ferro | 28 | comum | Ingrediente de Lingote de Ferro; venda valiosa |
| `aco` | Fragmento de Aço | 45 | incomum | Obtido com Picareta de Aço ou superior |
| `ouro` | Ouro Bruto | 70 | raro | Exige Picareta de Ouro ou superior |
| `diamante` | Diamante Bruto | 120 | épico | Exige Picareta de Diamante ou superior |
| `gema` | Gema Bruta | 50 | raro | Encontrada em regiões costeiras e montanhosas |
| `cristal` | Cristal de Abysmus | 80 | raro | Cristal raro de progressão e venda |
| `cristal_arcano` | Cristal Arcano | 180 | épico | Exige Picareta Arcana ou superior |
| `cristal_abissal` | Cristal Abissal | 320 | épico | Exige Picareta Abissal ou superior |
| `essencia_infernal` | Essência Infernal | 600 | lendário | Exige Picareta Infernal |
| `madeira` | Madeira | 8 | comum | Recurso do Lenhador; ingrediente de Artesanato |
| `couro` | Couro | 12 | comum | Material de venda do Caçador |
| `carne` | Carne | 10 | comum | Recurso do Caçador; vendido no mercador |
| `pena` | Pena | 14 | comum | Material incomum de venda |
| `cogumelo` | Cogumelo | 16 | incomum | Recurso do Herbalista |
| `concha` | Concha | 18 | incomum | Item de venda da Costa de Âmbar |
| `lingote_ferro` | Lingote de Ferro | 60 | incomum | Produzido pelo Ferreiro (2 Ferro + 1 Carvão) |
| `artesanato` | Artesanato | 40 | comum | Produzido pelo Artesão (2 Madeira + 1 Pedra) |

Efeito dos materiais: não possuem poder de combate próprio; são recursos de
progressão econômica e de receitas. Se usados como arma improvisada em
`/combate`, causam apenas 2–5 de dano. As descrições acima correspondem ao
comportamento real do código.

## Consumíveis / recursos de coleta

| Key | Nome | Preço | Utilidade | Efeito |
|---|---|---:|---|---|
| `peixe` | Peixe | 12 | Recurso do Pescador; vendável | Sem cura implementada; recurso de venda. Como arma improvisada, causa 2–5 |
| `erva` | Erva Medicinal | 15 | Recurso do Herbalista e de coleta | Sem cura automática; recurso de venda. Como arma improvisada, causa 2–5 |

## Requisitos e disponibilidade

- O mercador mostra `✅ Disponível` ou `🔒 motivo` para cada item.
- Requisitos de nível são verificados tanto na listagem quanto na compra.
- A compra de item bloqueado é recusada antes de qualquer débito.
- Itens únicos usam a flag `unico`; se o jogador já possui, a compra é
  recusada. Nenhum item do catálogo atual usa essa flag.
- O catálogo é definido em código e persistido junto com o projeto. As
  descrições **não são geradas a cada abertura** do mercado.
- O OpenRouter não altera preço, raridade, requisitos, efeitos ou
  disponibilidade.

## Interface

- `/mercador` — lista o catálogo, com descrição, utilidade, efeito e preço.
- `/mercador item:Nome` — detalha um item, incluindo atributos de mineração.
- `/comprar item:Nome quantidade:N` — compra pelo nome.
- `/vender item:Nome quantidade:N` — vende pelo nome.
- `/equipar item:Nome` — equipa uma picareta do inventário.
- `/combate inimigo:Nome` — inicia uma luta e executa o primeiro turno.
- `/combate` — ataca novamente com a arma armazenada.
- `/combate arma:Nome` — troca de arma sem reiniciar a luta.
- `/mochila` — mostra o inventário e a picareta em uso.

O autocomplete do Discord usa os nomes reais do catálogo.
