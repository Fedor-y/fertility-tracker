"""Точка запуска Linux onedir и явная приёмка на временных данных."""
import sys

if __name__ == "__main__":
    if sys.argv[1:] == ["--check-bundle"]:
        from bundle_check import main
    else:
        from healthtracker.bootstrap import main
    raise SystemExit(main())
