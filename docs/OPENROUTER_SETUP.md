# OpenRouter — Narração opcional

O OpenRouter é usado **apenas para narrar** o local em `/explorar`. Toda a
mecânica (recompensas, itens, moedas, XP, eventos, descobertas e estado) é
calculada e persistida em Python **antes** da chamada. A resposta da IA é
tratada como texto não confiável e nunca altera o jogo.

Arquivo: `rpg_system/ai/narrative.py`.

## Configuração

Adicione ao `.env` local (nunca versione a chave):

```env
# Obrigatório para usar a IA. Sem ele, a exploração usa fallback local.
OPENROUTER_API_KEY=sk-or-v1-...

# Modelo compatível com a API de chat completions.
OPENROUTER_MODEL=deepseek/deepseek-chat

# Limite de tokens da resposta narrativa (faixa efetiva: 40 a 600).
OPENROUTER_MAX_TOKENS=220

# Timeout HTTP total, em segundos.
OPENROUTER_TIMEOUT=10

# TTL do cache de descrições, em segundos. 0 desativa o cache.
OPENROUTER_CACHE_TTL=21600

# Atraso base do backoff para 429/5xx, em segundos.
OPENROUTER_RETRY_DELAY=1.0
```

`.env.example` contém as mesmas variáveis com valores vazios/padrão e sem
segredos. Valores inválidos caem no padrão: timeout `10`, tokens `220`, TTL
`21600` e atraso `1.0`.

## Funcionamento

- Endpoint: `https://openrouter.ai/api/v1/chat/completions` (compatível com
  OpenAI).
- Prompt de sistema instrui o modelo a descrever apenas o local, em 2–4
  frases, sem conceder recompensas, inimigos, missões ou mecânicas.
- Contexto enviado: local, região, bioma, clima, período do dia,
  características e coletas do local.
- `temperature = 0.7` e `max_tokens` limitado pela variável de ambiente.
- A chave vai apenas no header `Authorization`, em memória. Nunca é logada,
  impressa ou devolvida na resposta.

## Cache persistente

- Tabela: `rpg_narrativas`.
- A chave de cache é um SHA-256 de local, região, bioma, clima, período do dia
  e modelo. O mesmo local no mesmo período reaproveita o texto.
- TTL padrão: **21.600 segundos (6 horas)**. `OPENROUTER_CACHE_TTL=0` desativa
  a leitura e a gravação do cache.
- O cache não cresce a cada abertura: cada combinação atualiza a mesma linha
  (`ON CONFLICT(cache_key) DO UPDATE`).
- Falha de cache nunca bloqueia a exploração.

## Retry e limites

- Até **3 tentativas** no total (`max_retries = 2`).
- Backoff exponencial em `429`, `500`, `502`, `503` e `504`:
  `OPENROUTER_RETRY_DELAY × 2^tentativa` (1 s, 2 s por padrão).
- Se o header `Retry-After` trouxer um número, ele é usado quando for maior,
  limitado a 5 s.
- `timeout` cobre a requisição inteira.
- Resposta aceita somente entre **25 e 800 caracteres**. São rejeitadas:
  resposta curta, resposta longa, blocos de código, JSON/lista no início e
  caracteres de controle.

## Fallback

A exploração **sempre** retorna uma descrição utilizável. O fallback local usa
local, bioma, clima, período e características. Motivos registrados em
`ultimo_motivo`:

| Motivo | Quando ocorre |
|---|---|
| `sem_chave` | `OPENROUTER_API_KEY` ausente ou vazia |
| `sem_aiohttp` | biblioteca `aiohttp` indisponível |
| `timeout` | tempo limite excedido |
| `erro_rede` | falha de transporte/conexão |
| `http_<código>` | erro HTTP não recuperável (ex.: 401, 403) |
| `tentativas_esgotadas` | 429/5xx após todas as tentativas |
| `resposta_curta` | texto com menos de 25 caracteres |
| `resposta_longa` | texto com mais de 800 caracteres |
| `resposta_estruturada` | bloco de código, JSON ou lista |
| `caracteres_invalidos` | caracteres de controle |
| `falha_openrouter` | motivo não classificado |

Sem chave, sem `aiohttp`, com erro HTTP/rede ou resposta inválida, o jogador
continua explorando normalmente. A IA nunca é obrigatória.

## Segurança

- Chave apenas no `.env` local e no header em memória; nunca versionada.
- Nenhum log inclui a chave, a URL assinada ou o corpo do erro de transporte.
- A resposta é validada e exibida como texto; não há execução de código,
  interpretação de comandos nem alteração de estado.
- O prompt proíbe explicitamente conceder recompensas ou inventar mecânicas.
- Limites de tokens, timeout e tentativas reduzem custo e risco de bloqueio.

## Custos

- Configure um limite de gastos no painel do OpenRouter.
- O cache de 6 horas reduz chamadas repetidas para o mesmo local/período.
- Modelos e preços mudam; confira o custo atual no OpenRouter antes de trocar
  `OPENROUTER_MODEL`.
- O sistema não mede nem registra custo por chamada.

## Limitações

- A integração foi validada com **mocks**; não houve chamada real ao OpenRouter
  nesta evolução porque não havia chave válida no ambiente.
- Não há streaming, contagem de tokens usados, métrica de latência nem painel
  de custo interno.
- A qualidade do texto depende do modelo escolhido; o fallback local é
  deliberadamente simples.
- Erros de configuração (chave inválida, modelo inexistente) resultam em
  fallback, não em bloqueio da exploração.
