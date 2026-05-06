import os
from openai import OpenAI

api_key = os.getenv("MIMO_API_KEY") or os.getenv("LABAGENT_LEARNING_API_KEY")
if not api_key:
    raise RuntimeError("Set MIMO_API_KEY or LABAGENT_LEARNING_API_KEY before running this demo.")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.xiaomimimo.com/v1"
)

completion = client.chat.completions.create(
    model="mimo-v2.5-pro",
    messages=[
        {
            "role": "system",
            "content": "You are MiMo, an AI assistant developed by Xiaomi. Today is date: Tuesday, December 16, 2025. Your knowledge cutoff date is December 2024."
        },
        {
            "role": "user",
            "content": "please introduce yourself"
        }
    ],
    max_completion_tokens=1024,
    temperature=1.0,
    top_p=0.95,
    stream=False,
    stop=None,
    frequency_penalty=0,
    presence_penalty=0
)

print(completion.model_dump_json())
