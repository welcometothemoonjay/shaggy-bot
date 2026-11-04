"""RPG System - Adaptado ao padrão do Shaggy Bot"""
from . import constants, database, models, items, inventory, economy, progression, energy, mining, professions, theft, houses, marriage, missions, activities, market, achievements
__all__ = ["constants", "database", "models", "items", "inventory", "economy", "progression", "energy", "mining", "professions", "theft", "houses", "marriage", "missions", "activities", "market", "achievements"]

# Novos módulos
from . import tools, ai
__all__.extend(["tools", "ai"])
