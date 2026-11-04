"""Narração de locais via OpenRouter.

Esta camada é opcional e estritamente narrativa: ela recebe um contexto
estruturado e devolve texto. Nenhuma recompensa, item, moeda, XP, evento ou
estado de jogo é decidido aqui -- tudo isso já foi calculado e persistido
pelo Python antes da chamada.

Garantias:
- Sem ``OPENROUTER_API_KEY`` a exploração continua normalmente com fallback.
- Cache persistente em ``rpg_narrativas`` (não cresce a cada abertura).
- Timeout curto e ``max_tokens`` limitado por variável de ambiente.
- 429/5xx têm backoff exponencial limitado.
- Respostas inválidas ou longas demais caem no fallback local.
- A chave nunca é logada, impressa ou incluída nas respostas.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any

from ..database import get_db
from ..schema import garantir_tabelas

SYSTEM_PROMPT = (
    "Você é um narrador de RPG textual em português do Brasil. "
    "Descreva APENAS o local atual usando os dados fornecidos. "
    "NÃO conceda recompensas, itens, XP, moedas, combates, inimigos ou missões. "
    "NÃO invente mecânicas, números ou resultados. "
    "Seja imersivo, objetivo e fiel ao contexto. "
    "Responda somente com a descrição, em 2 a 4 frases, sem título e sem listas."
)


def _limpar_texto(texto: str) -> str:
    texto = (texto or "").strip()
    texto = texto.strip("\"'` \n\t")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


class NarrativeAI:
    def __init__(self, db=None):
        self.api_key = (os.getenv("OPENROUTER_API_KEY", "") or "").strip()
        self.model = (os.getenv("OPENROUTER_MODEL", "") or "deepseek/deepseek-chat").strip()
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        try:
            self.timeout = float(os.getenv("OPENROUTER_TIMEOUT", "10"))
        except ValueError:
            self.timeout = 10.0
        try:
            self.max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "220"))
        except ValueError:
            self.max_tokens = 220
        self.max_tokens = max(40, min(600, self.max_tokens))
        try:
            self.cache_ttl = int(os.getenv("OPENROUTER_CACHE_TTL", "21600"))
        except ValueError:
            self.cache_ttl = 21600
        try:
            self.retry_base_delay = float(os.getenv("OPENROUTER_RETRY_DELAY", "1.0"))
        except ValueError:
            self.retry_base_delay = 1.0
        self.max_retries = 2
        self.db = db or get_db()
        garantir_tabelas()
        # Último motivo de fallback, útil para diagnóstico e testes.
        self.ultimo_motivo = ""

    # ---------------- configuração ----------------
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        # A chave fica apenas no header em memória. Nunca é logada.
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/shaggy-bot",
            "X-Title": "Shaggy RPG",
        }

    def _cache_key(self, ctx: dict[str, Any]) -> str:
        base = {
            "local_key": ctx.get("local_key") or ctx.get("local"),
            "regiao_key": ctx.get("regiao_key") or ctx.get("regiao"),
            "bioma": ctx.get("bioma"),
            "clima": ctx.get("clima"),
            "periodo": ctx.get("periodo"),
            "model": self.model,
        }
        bruto = json.dumps(base, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()

    # ---------------- fallback ----------------
    @staticmethod
    def _fallback(ctx: dict[str, Any]) -> str:
        local = ctx.get("local") or ctx.get("regiao") or "lugar desconhecido"
        bioma = ctx.get("bioma") or "terreno variado"
        clima = ctx.get("clima") or "clima neutro"
        periodo = ctx.get("periodo")
        caracteristicas = ctx.get("caracteristicas") or []
        extras = ""
        if caracteristicas:
            extras = f" Destacam-se {', '.join(caracteristicas[:3])}."
        if periodo:
            return (
                f"Você está em {local}, durante a {periodo}. "
                f"O bioma é {bioma}, com {clima}.{extras} "
                "O caminho à frente convida a continuar explorando."
            )
        return (
            f"Você está em {local}. O bioma é {bioma}, com {clima}.{extras} "
            "O caminho à frente convida a continuar explorando."
        )

    # ---------------- cache ----------------
    def _ler_cache(self, cache_key: str) -> str | None:
        if self.cache_ttl <= 0:
            return None
        try:
            with self.db.transacao() as db:
                row = db.execute(
                    "SELECT descricao, criado_em FROM rpg_narrativas WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
            if not row:
                return None
            if time.time() - float(row[1]) > self.cache_ttl:
                return None
            return row[0]
        except Exception:
            return None

    def _gravar_cache(self, cache_key: str, ctx: dict[str, Any], descricao: str) -> None:
        try:
            with self.db.transacao() as db:
                db.execute(
                    "INSERT INTO rpg_narrativas (cache_key, local_key, descricao, fonte, criado_em) "
                    "VALUES (?, ?, ?, 'openrouter', ?) "
                    "ON CONFLICT(cache_key) DO UPDATE SET "
                    "descricao = excluded.descricao, fonte = excluded.fonte, criado_em = excluded.criado_em",
                    (cache_key, str(ctx.get("local_key") or ""), descricao, time.time()),
                )
        except Exception:
            # Cache é otimização; falha de cache nunca bloqueia a exploração.
            pass

    # ---------------- validação ----------------
    @staticmethod
    def _validar_resposta(conteudo: str) -> tuple[bool, str]:
        texto = _limpar_texto(conteudo)
        if len(texto) < 25:
            return False, "resposta_curta"
        if len(texto) > 800:
            return False, "resposta_longa"
        if "```" in texto or texto.startswith("{") or texto.startswith("["):
            return False, "resposta_estruturada"
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", texto):
            return False, "caracteres_invalidos"
        return True, texto

    # ---------------- requisição ----------------
    async def _request(self, payload: dict[str, Any]) -> tuple[int, Any]:
        """Executa a chamada HTTP.

        Retorna ``(status, dados)``. É um método separado para permitir testes
        sem rede. Em erro de transporte devolve ``(0, motivo)``.
        """
        try:
            import aiohttp
        except Exception:
            return 0, "sem_aiohttp"

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.base_url,
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status != 200:
                        retry_after = resp.headers.get("Retry-After")
                        return resp.status, retry_after
                    try:
                        return 200, await resp.json()
                    except Exception:
                        return 200, await resp.text()
        except asyncio.TimeoutError:
            return 0, "timeout"
        except Exception:
            # Não inclui detalhes que possam conter a URL ou a chave.
            return 0, "erro_rede"

    async def _tentar(self, payload: dict[str, Any]) -> tuple[bool, str, str]:
        for tentativa in range(self.max_retries + 1):
            status, data = await self._request(payload)
            if status == 200:
                if isinstance(data, dict):
                    choices = data.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        content = (choices[0].get("message") or {}).get("content") or ""
                    else:
                        content = ""
                else:
                    content = ""
                ok, texto = self._validar_resposta(content)
                if ok:
                    return True, texto, "openrouter"
                return False, "", texto  # motivo

            if status in (429, 500, 502, 503, 504) and tentativa < self.max_retries:
                atraso = self.retry_base_delay * (2 ** tentativa)
                if isinstance(data, str):
                    try:
                        atraso = max(atraso, min(5.0, float(data)))
                    except (TypeError, ValueError):
                        pass
                if atraso > 0:
                    await asyncio.sleep(atraso)
                continue

            if status == 0:
                return False, "", str(data)
            return False, "", f"http_{status}"

        return False, "", "tentativas_esgotadas"

    async def describe_location(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Descreve o local. Sempre retorna uma descrição utilizável."""
        ctx = dict(ctx or {})
        fallback = self._fallback(ctx)
        cache_key = self._cache_key(ctx)

        cache = self._ler_cache(cache_key)
        if cache:
            self.ultimo_motivo = ""
            return {"sucesso": True, "descricao": cache, "fonte": "cache", "motivo": ""}

        if not self.is_configured():
            self.ultimo_motivo = "sem_chave"
            return {
                "sucesso": True,
                "descricao": fallback,
                "fonte": "fallback",
                "motivo": "sem_chave",
            }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Dados estruturados do local (use somente isto):\n"
                        f"{json.dumps(ctx, ensure_ascii=False, sort_keys=True)}\n\n"
                        "Descreva o local em 2 a 4 frases."
                    ),
                },
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.7,
        }

        ok, texto, motivo = await self._tentar(payload)
        if ok:
            self._gravar_cache(cache_key, ctx, texto)
            self.ultimo_motivo = ""
            return {"sucesso": True, "descricao": texto, "fonte": "openrouter", "motivo": ""}

        self.ultimo_motivo = motivo or "falha_openrouter"
        return {
            "sucesso": True,
            "descricao": fallback,
            "fonte": "fallback",
            "motivo": self.ultimo_motivo,
        }
