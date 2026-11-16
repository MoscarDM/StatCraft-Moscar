import sys


def main():
    if "--smoke-verify" in sys.argv[1:]:
        from .smoke_verify import run_smoke_verify
        return run_smoke_verify()
    from .app import main as _app_main
    return _app_main()


if __name__ == "__main__":
    raise SystemExit(main())
