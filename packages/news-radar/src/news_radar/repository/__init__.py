"""Data-access layer: one repository per aggregate, raw SQL via psycopg2, no ORM."""

from news_radar.repository.article_repository import ArticleRepository

__all__ = ["ArticleRepository"]
