"""Opt-in live smoke check. Importing this file never spends API credits."""
def main():
    from dotenv import load_dotenv
    from pydantic import BaseModel
    from tools.llm import complete_json
    load_dotenv()

    class Greeting(BaseModel):
        greeting: str

    result = complete_json("Return a short greeting.", {"request": "hello"}, Greeting)
    print(result.greeting)


if __name__ == "__main__":
    main()
