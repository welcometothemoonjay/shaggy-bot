import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise SystemExit("Falta OPENROUTER_API_KEY no arquivo .env")

client = OpenAI(
    api_key=api_key,
    base_url="https://openrouter.ai/api/v1",
    timeout=60.0,
)


try:
    resposta = client.chat.completions.create(
        model="openrouter/free",
        messages=[
            {
                "role": "system",
                "content": "Você é Shaggy, assistente amigável e engraçado. "
                "Responda em português brasileiro, sempre com "
                "uma resposta útil e completa.",
            },
            {"role": "user", "content": "Responda somente: Olá! Eu sou o Shaggy Bot."},
        ],
        max_tokens=400,
    )

    escolha = resposta.choices[0]
    mensagem = escolha.message

    print("\n=== DIAGNÓSTICO ===")
    print("Modelo:", resposta.model)
    print("Motivo do término:", escolha.finish_reason)
    print("Motivo nativo:", escolha.native_finish_reason)
    print("Conteúdo:", repr(mensagem.content))
    print("Raciocínio disponível:", bool(getattr(mensagem, "reasoning", None)))

    raciocinio = getattr(mensagem, "reasoning", None)
    if raciocinio:
        print("Campo de raciocínio:", repr(raciocinio[:500]))

    if resposta.usage:
        print("Tokens de saída:", resposta.usage.completion_tokens)

except Exception as erro:
    print(f"Erro: {type(erro).__name__}: {erro}")

except Exception as erro:
    print(f"\nFalha na chamada da IA: {type(erro).__name__}: {erro}")
