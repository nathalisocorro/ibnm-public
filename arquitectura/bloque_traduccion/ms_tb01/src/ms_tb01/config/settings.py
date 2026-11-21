from crewai import LLM
from dotenv import load_dotenv
import os

load_dotenv()

api_llm = LLM(
    model="deepseek/deepseek-v4-flash",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)