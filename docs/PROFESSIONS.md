# PROFISSÕES — RPG Textual

Catálogo real implementado em `rpg_system/professions_v2.py`. A identidade
interna é a `key`; o jogador interage pelo nome (sem diferenciar maiúsculas ou
acentos). O catálogo completo pode ser consultado com `/profissoes` e os
detalhes com `/profissoes profissao:Nome`.

## Regras gerais

- O jogador pode aprender **mais de uma profissão**. Cada uma evolui de forma
  independente, com nível, XP e cooldown próprios.
- Aprender não custa moedas; exige apenas o nível de personagem indicado.
- Não há limite de profissões aprendidas.
- `/trabalhar` sem parâmetro usa a profissão aprendida de maior nível.
- Cada atividade tem cooldown de **300 segundos por profissão**.
- XP profissional necessário para subir de nível: `60 × nível atual`.
  Ao subir, o XP excedente permanece e o custo do próximo nível aumenta.
- Toda atividade também concede XP de personagem: `4 + (nível da profissão ÷ 3)`
  (divisão inteira), além de XP profissional
  `xp_atividade + 2 × (nível da profissão − 1)`.
- Os benefícios são aplicados diretamente nos sistemas de mineração,
  exploração, mercado e produção. Não são apenas texto.

## Catálogo

| Key | Profissão | Requisito | Atividades | Ganho principal |
|---|---|---|---|---|
| `minerador` | ⛏️ Minerador | Nível 1 | Minerar com picareta; prospecção | Materiais minerais, Abysmus e XP |
| `lenhador` | 🪓 Lenhador | Nível 1 | Cortar madeira; coletar recursos | Madeira, ervas, itens extras |
| `cacador` | 🏹 Caçador | Nível 1 | Rastrear presas; coletar componentes | Couro, carne, penas |
| `mercador` | 🪙 Mercador | Nível 2 | Negociar comissões; comprar/vender | Desconto, bônus de venda e comissão limitada |
| `artesao` | 🧰 Artesão | Nível 2 | Produzir artesanato | Artesanato (receita real) |
| `pescador` | 🎣 Pescador | Nível 1 | Pescar; recolher conchas | Peixes e conchas |
| `ferreiro` | 🔨 Ferreiro | Nível 3 | Forjar lingotes | Lingote de Ferro (receita real) |
| `herbalista` | 🌿 Herbalista | Nível 1 | Colher ervas; cogumelos | Ervas e cogumelos |
| `explorador` | 🗺️ Explorador | Nível 1 | Explorar; reconhecer trilhas | XP, descobertas e Abysmus |

## Atividades e rendimento

### Minerador

- Itens por atividade: Pedra (65%, 1–2) e Carvão (35%, 1–2).
- Comissão: 0–2 Abysmus + até +10 pelo nível profissional.
- A mineração (`/mineracao`) é a atividade principal e tem regras próprias:
  usa picareta, região, energia e chances de Abysmus por tier. A profissão
  **não é obrigatória** para minerar; sem ela, o jogador apenas não recebe XP
  profissional de mineração.
- Benefícios de mineração:
  - Nível 2 — **Veios abundantes**: +3% de materiais por nível acima de 1
    (limite +30%).
  - Nível 5 — **Faro para moedas**: +5% de Abysmus por nível acima de 4
    (limite +25%).
  - Nível 10 — **Mestre das profundezas**: +10% de chance de material raro
    (tier ≥ 4) por nível acima de 9 (limite +25%).

### Lenhador

- Itens: Madeira (80%, 1–3) e Erva Medicinal (20%, 1).
- Benefícios de coleta:
  - Nível 2 — **Corte firme**: +3% de madeira.
  - Nível 5 — **Conhecedor da mata**: +12% de madeira e +8% de chance de item extra.
  - Nível 10 — **Guardião da floresta**: +27% de madeira e +18% de chance de item extra.

### Caçador

- Itens: Couro (55%, 1–2), Carne (40%, 1–2) e Pena (10%, 1).
- Benefícios de coleta:
  - Nível 2 — **Rastreador**: +3% de materiais e +2% de item extra.
  - Nível 5 — **Caçador experiente**: +12% de materiais e +8% de item extra.
  - Nível 10 — **Predador do horizonte**: +27% de materiais e +18% de item extra.

### Mercador

- Não coleta itens; recebe comissão de 3–8 Abysmus + até +10 pelo nível.
- Benefícios comerciais (aplicados no mercado):
  - Nível 2 — **Bom papo**: 2% de desconto nas compras.
  - Nível 5 — **Negociante**: 5% de desconto e +5% na venda.
  - Nível 10 — **Mestre do comércio**: 10% de desconto e +10% na venda.
- Fórmula real: desconto de compra = `1% × nível`, limitado a **15%**.
  Bônus de venda = `1% × nível`, limitado a **10%**.
- A venda paga 50% do preço base do item. O bônus de Mercador incide sobre
  esses 50%, portanto não existe lucro garantido comprando e revendendo o
  mesmo item.

### Artesão

- Receita real: **1 Artesanato** consome **2 Madeiras + 1 Pedra**.
- A receita falha sem materiais e não cobra nada nesse caso.
- Produção extra: 10% no nível 2, 25% no nível 5 e 50% no nível 10.
- O Artesanato pode ser vendido no mercador.

### Pescador

- Itens: Peixe (75%, 1–2) e Concha (25%, 1).
- Benefícios de coleta:
  - Nível 2 — **Isca melhor**: +3% de materiais e +2% de item extra.
  - Nível 5 — **Paciência de pescador**: +12% de materiais e +8% de item extra.
  - Nível 10 — **Senhor das marés**: +27% de materiais e +18% de item extra.

### Ferreiro

- Receita real: **1 Lingote de Ferro** consome **2 Minérios de Ferro + 1 Carvão**.
- Produção extra: 10% no nível 2, 25% no nível 5 e 50% no nível 10.
- O Lingote de Ferro pode ser vendido no mercador.

### Herbalista

- Itens: Erva Medicinal (65%, 1–2) e Cogumelo (35%, 1).
- Benefícios de coleta:
  - Nível 2 — **Olhar atento**: +3% de materiais e +2% de item extra.
  - Nível 5 — **Herbário vivo**: +12% de materiais e +8% de item extra.
  - Nível 10 — **Mestre herbalista**: +27% de materiais e +18% de item extra.

### Explorador

- Não coleta itens na atividade de trabalho; recebe 2–6 Abysmus + até +10
  pelo nível.
- A exploração (`/explorar`) concede XP, descobertas, itens e moedas.
- Benefícios de exploração:
  - Nível 2 — **Bússola interna**: +5% de XP.
  - Nível 5 — **Cartógrafo**: +20% de XP e +5% de Abysmus.
  - Nível 10 — **Olhar do horizonte**: +30% de XP e +20% de Abysmus.

## Coleta: fórmula aplicada

Para profissões de coleta (Lenhador, Caçador, Pescador, Herbalista):

- Quantidade por drop: `base × (1 + bônus)`, com
  `bônus = 3% × (nível − 1)`, limitado a **40%**.
- Item extra: chance de `2% × (nível − 1)`, limitada a **50%**; quando
  ativada, sorteia um dos drops da profissão e adiciona +1.
- Os itens são persistidos em `ruptura_inventario` na mesma transação da
  atividade.

## Limitações atuais

- Não há árvore de habilidades, classes de profissão ou especializações.
- A durabilidade de ferramentas não está implementada.
- O nível máximo de profissão não é limitado pelo código.
- Cozinha, fundição de outros metais e novas receitas não foram adicionadas.
