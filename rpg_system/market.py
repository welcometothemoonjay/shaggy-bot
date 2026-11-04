from .database import get_db
from .economy import Economy
from .inventory import Inventario
from .items import CATALOGO_ITENS
class Market:
    def __init__(self, bot, guild_id: int, user_id: int):
        self.bot=bot; self.guild_id=guild_id; self.user_id=user_id
        self.db=get_db(); self.economy=Economy(bot); self.inventory=Inventario(guild_id,user_id)
    def listar_loja(self):
        itens=[]
        for key,item in CATALOGO_ITENS.items():
            if item.vendavel: itens.append({"key":key,"nome":item.nome,"descricao":item.descricao,"preco":item.preco,"raridade":item.raridade,"tipo":item.tipo})
        return itens
    def comprar(self,item_key,quantidade=1):
        if quantidade<=0: return {"sucesso":False,"motivo":"Quantidade inválida"}
        item=CATALOGO_ITENS.get(item_key)
        if not item or not item.vendavel: return {"sucesso":False,"motivo":"Item não encontrado"}
        preco_total=item.preco*quantidade
        ok,_=self.economy.remover(self.guild_id,self.user_id,preco_total,f"comprar_{item_key}")
        if not ok: return {"sucesso":False,"motivo":"Abysmus insuficiente"}
        self.inventory.adicionar(item_key,quantidade)
        return {"sucesso":True,"item":item_key,"quantidade":quantidade,"preco":preco_total}
    def vender(self,item_key,quantidade=1):
        if quantidade<=0: return {"sucesso":False,"motivo":"Quantidade inválida"}
        if not self.inventory.tem(item_key,quantidade): return {"sucesso":False,"motivo":"Item insuficiente"}
        item=CATALOGO_ITENS.get(item_key)
        preco_base=item.preco if item else 5
        preco_venda=int(preco_base*0.5*quantidade)
        if preco_venda<1: preco_venda=1
        ok_rem=self.inventory.remover(item_key,quantidade)
        if not ok_rem: return {"sucesso":False,"motivo":"Erro ao remover item"}
        self.economy.adicionar(self.guild_id,self.user_id,preco_venda,f"vender_{item_key}")
        return {"sucesso":True,"item":item_key,"quantidade":quantidade,"recebido":preco_venda}
