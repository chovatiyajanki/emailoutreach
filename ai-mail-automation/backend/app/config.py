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

    OPENAI_API_KEY = os.getenv(
        "OPENAI_API_KEY",
    )

    OPENAI_MODEL = os.getenv(
        "OPENAI_MODEL",
        "gpt-5.6-luna",
    )

    SENDER_EMAIL = os.getenv(
        "SENDER_EMAIL",
        "chovatiyajanki1913@gmail.com",
    )

    SENDER_NAME = os.getenv(
        "SENDER_NAME",
        "Janki Chovatiya",
    )

    SMTP_HOST = os.getenv(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

    SMTP_USERNAME = os.getenv(
        "SMTP_USERNAME",
        "chovatiyajanki1913@gmail.com",
    )

    SMTP_PASSWORD = os.getenv(
        "SMTP_PASSWORD",
        "",
    )


settings = Settings()