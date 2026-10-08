import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")
load_dotenv()


class Settings:
    APP_NAME = os.getenv(
        "APP_NAME",
        "AI Mail Automation",
    )

    APP_ENV = os.getenv(
        "APP_ENV",
        "development",
    )

    DATABASE_URL = os.getenv(
        "DATABASE_URL",
    )

    REDIS_URL = os.getenv(
        "REDIS_URL",
        "redis://localhost:6379/0",
    )


    GROQ_API_KEY = os.getenv(
        "GROQ_API_KEY",
        "",
    )

    GROQ_MODEL = os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    )

    GEMINI_API_KEY = os.getenv(
        "GEMINI_API_KEY",
        "",
    )

    GEMINI_MODEL = os.getenv(
        "GEMINI_MODEL",
        "gemini-flash-latest",
    )

    SENDER_EMAIL = os.getenv(
        "SENDER_EMAIL",
        "",
    )

    SENDER_NAME = os.getenv(
        "SENDER_NAME",
        "",
    )

    SMTP_HOST = os.getenv(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

    SMTP_USERNAME = os.getenv(
        "SMTP_USERNAME",
        "",
    )

    SMTP_PASSWORD = os.getenv(
        "SMTP_PASSWORD",
        "",
    )


settings = Settings()