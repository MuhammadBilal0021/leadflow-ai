import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=15.0)

print("Starting Groq request with model:", os.getenv("GROQ_MODEL"))
try:
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL"),
        messages=[{"role": "user", "content": "hello"}],
    )
    print("Success:", response.choices[0].message.content)
except Exception as e:
    print("Error:", repr(e))
