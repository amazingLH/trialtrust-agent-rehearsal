/* Read-only legacy iframe-resizer pageInfo interop; no vendor code is bundled. */
const PortalViewport = (() => {
  const origins = new Set([
    "https://www.modelscope.cn",
    "https://modelscope.cn",
  ]);
  const prefix = "[iFrameSizer]";

  function readMessage(event, parent, ownOrigin) {
    const sameOrigin =
      typeof ownOrigin === "string" &&
      /^https?:\/\//.test(ownOrigin) &&
      event.origin === ownOrigin;
    if (event.source !== parent || (!origins.has(event.origin) && !sameOrigin))
      return null;
    if (
      typeof event.data !== "string" ||
      event.data.length > 8192 ||
      !event.data.startsWith(prefix)
    )
      return null;
    const data = event.data.slice(prefix.length);
    if (data.startsWith("pageInfo:")) {
      try {
        const info = JSON.parse(data.slice(9));
        if (
          ![info.clientWidth, info.clientHeight].every(
            (n) =>
              typeof n === "number" &&
              Number.isFinite(n) &&
              n >= 240 &&
              n <= 16384,
          )
        )
          return null;
        return {
          kind: "viewport",
          width: info.clientWidth,
          height: info.clientHeight,
        };
      } catch {
        return null;
      }
    }
    const id = data.split(":", 1)[0];
    return /^iFrameResizer\d{1,4}$/.test(id) ? { kind: "init", id } : null;
  }

  function attach(win, host) {
    if (!host || win.parent === win) return () => {};
    const requested = new Set();
    let remote = null;
    function receive(event) {
      const parsed = readMessage(event, win.parent, win.location.origin);
      if (!parsed) return;
      if (parsed.kind === "init") {
        const key = event.origin + "/" + parsed.id;
        if (!requested.has(key)) {
          requested.add(key);
          remote = { origin: event.origin, id: parsed.id };
          win.parent.postMessage(
            prefix + parsed.id + ":0:0:pageInfo",
            event.origin,
          );
        }
        return;
      }
      if (!remote || event.origin !== remote.origin) return;
      const width = Math.floor(Math.min(parsed.width, win.innerWidth));
      host.style.setProperty("--portal-width", width + "px");
      host.style.setProperty(
        "--portal-height",
        Math.floor(parsed.height) + "px",
      );
      host.dataset.portalViewport = "true";
      host.dataset.portalPhone = String(width <= 560);
    }
    win.addEventListener("message", receive);
    // The containing page only receives a readiness signal and size query.
    // Neither message contains task text, credentials or an action command.
    let referrerOrigin;
    try {
      referrerOrigin = new URL(win.document.referrer).origin;
    } catch {}
    if (origins.has(referrerOrigin) || referrerOrigin === win.location.origin) {
      win.parent.postMessage("[iFrameResizerChild]Ready", referrerOrigin);
    }
    return () => {
      win.removeEventListener("message", receive);
      if (remote)
        win.parent.postMessage(
          prefix + remote.id + ":0:0:pageInfoStop",
          remote.origin,
        );
    };
  }
  return { readMessage, attach };
})();
if (typeof module !== "undefined" && module.exports)
  module.exports = PortalViewport;
