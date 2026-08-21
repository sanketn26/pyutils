"""CLI entry point for news-radar."""

from news_radar import __version__


def main() -> None:
    print(f"news-radar {__version__}")


if __name__ == "__main__":
    main()
