from datetime import timezone, timedelta

FUSO_HORARIO = timezone(timedelta(hours=-3), "BRT")
MOEDA_NOME = "Abysmus"
MOEDA_SIMBOLO = "🪙"
ENERGIA_MAX = 100
# Recuperação automática: a energia volta ao máximo uma vez a cada 24h.
ENERGIA_POR_REGEN = ENERGIA_MAX
INTERVALO_REGEN_MINUTOS = 24 * 60
ENERGIA_REGEN_INTERVALO_SEGUNDOS = 24 * 60 * 60
COMBATE_ENERGIA_CUSTO = 4
XP_BASE_NIVEL = 100
XP_MULTIPLICADOR_NIVEL = 1.1
MINING_COOLDOWN_SEGUNDOS = 300
MINING_ENERGIA_CUSTO = 10
EXPLORATION_COOLDOWN_SEGUNDOS = 120
EXPLORATION_ENERGIA_CUSTO = 5
PROFISSOES_DISPONIVEIS = [
    "minerador", "lenhador", "cacador", "mercador", "artesao",
    "pescador", "ferreiro", "herbalista", "explorador",
]
THEFT_COOLDOWN_SEGUNDOS = 600
THEFT_SUCESSO_BASE = 0.4
CASAS_MAX_POR_JOGADOR = 1
MARRIAGE_COOLDOWN_PROPOSTA = 3600
MISSOES_DIARIAS_LIMITE = 3
TAXA_VENDA = 0.05
ACTIVITY_COOLDOWN_SEGUNDOS = 120

# Progressão de personagem do RPG Textual.
# Nível 1 começa com 0 XP. Para ir do nível N para N+1 são necessários
# (40 * N + 40) XP: 80, 120, 160, 200...
def xp_para_proximo_nivel(nivel: int) -> int:
    if nivel <= 0:
        nivel = 1
    return 40 * nivel + 40
