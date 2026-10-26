"""Gradio-native presentation for ModelScope's managed public frontend.

Account authentication remains in the shared FastAPI backend.
The standalone Docker entry is python -m trialtrust.managed.
"""
import os
import re
from pathlib import Path

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
if os.name != "nt":
    os.umask(0o077)
    os.environ.setdefault("TRIALTRUST_RUNTIME", "/mnt/workspace/trialtrust/web")


def create_studio_app(*, require_accounts=True):
    import gradio as gr
    # The managed gateway rewrites Host to a new FC service on every deploy.
    # Keep the public Origin fixed; Host is routing metadata, not authentication.
    hosts = os.environ.get("TRIALTRUST_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    os.environ["TRIALTRUST_ALLOWED_HOSTS"] = hosts + ",*.cn-beijing-vpc.fcapp.run"
    from trialtrust.webapp import create_app
    # The external workbench uses the same account routes and persistent store.
    # Exact platform origins only; the standalone factory stays disabled by default.
    browser_origins = tuple(origin.strip() for origin in os.environ.get(
        "TRIALTRUST_BROWSER_ORIGINS",
        "https://render.qmuse.pub,https://qmuse.cn,https://www.qmuse.cn",
    ).split(",") if origin.strip())
    app = create_app(require_accounts=require_accounts, browser_origins=browser_origins)
    assets = Path(__file__).parent / "trialtrust" / "web"
    html = (assets / "index.html").read_text(encoding="utf-8").split("<body>", 1)[1].split("</body>", 1)[0]
    css = (assets / "style.css").read_text(encoding="utf-8").replace(":root", ".trialtrust-root")
    css = re.sub(r"(?<![\w.-])body\s*\{", ".trialtrust-root {", css)
    javascript = (assets / 'portal_viewport.js').read_text(encoding='utf-8') + '\n' + (assets / 'workbench_tools.js').read_text(encoding='utf-8') + '\n' + (assets / 'auth.js').read_text(encoding='utf-8') + '\n' + (assets / "app.js").read_text(encoding="utf-8")
    javascript = javascript.replace("document.getElementById(id)", "root.querySelector('#' + id)")
    javascript = re.sub(r"document\s*\.\s*querySelectorAll\s*\(", "root.querySelectorAll(", javascript)
    with gr.Blocks(analytics_enabled=False, title="试托·Agent委托前试运行工作台") as studio:
        gr.HTML(value='<div class="trialtrust-root">' + html + '</div>',
                css_template=css, js_on_load="(function(root){\n" + javascript + "\n})(element);",
                apply_default_css=False)
    # /config must describe this real UI, since ModelScope renders its own
    # Gradio shell instead of passing our standalone index.html through.
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) not in {"/", "/assets"}]
    app.state.studio_ui = True
    return gr.mount_gradio_app(app, studio, path="/", css=".gradio-container{max-width:none!important;padding:0!important;overflow:visible!important}.gradio-container > main{padding:0!important}.gradio-container footer:not(.site-footer){display:none!important}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_studio_app(), host="0.0.0.0", port=7860, workers=1,
                proxy_headers=True, forwarded_allow_ips="*")
