"""Entrypoint for standalone containers and the managed ModelScope iframe."""
import os


def create_managed_app(*, require_accounts=True):
    from trialtrust.webapp import create_app

    # The platform supplies the public origin; FC Host is routing metadata.
    hosts = os.environ.get("TRIALTRUST_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    os.environ["TRIALTRUST_ALLOWED_HOSTS"] = hosts + ",*.cn-beijing-vpc.fcapp.run"
    app = create_app(require_accounts=require_accounts)
    app.state.studio_ui = True

    @app.middleware("http")
    async def strict_managed_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; "
            "frame-ancestors 'self' https://modelscope.cn https://www.modelscope.cn"
        )
        return response

    return app


def main():
    import uvicorn

    target = ("trialtrust.managed:create_managed_app"
              if os.environ.get("TRIALTRUST_MANAGED_STUDIO") == "1"
              else "trialtrust.webapp:create_app")
    uvicorn.run(target, factory=True, host="0.0.0.0", port=7860, workers=1,
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
