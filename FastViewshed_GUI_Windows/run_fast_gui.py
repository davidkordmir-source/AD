"""Start the independent GDAL/Qt desktop application."""

if __name__ == "__main__":
    from fast_viewshed.diagnostics import enable_fast_logging, fast_startup_error
    enable_fast_logging()
    try:
        from fast_viewshed.gui import fast_main
        raise SystemExit(fast_main())
    except Exception as exc:
        fast_startup_error(exc)
        raise SystemExit(1)
