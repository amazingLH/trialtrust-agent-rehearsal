const test = require("node:test");
const assert = require("node:assert/strict");
const { readMessage, attach } = require("../trialtrust/web/portal_viewport.js");
const parent = {};
const origin = "https://www.modelscope.cn";
const page = (width = 390, height = 844) => ({
  source: parent,
  origin,
  data:
    "[iFrameSizer]pageInfo:" +
    JSON.stringify({ clientWidth: width, clientHeight: height }),
});

test("only the actual trusted parent can supply viewport information", () => {
  assert.equal(
    readMessage({ ...page(), origin: "https://evil.invalid" }, parent),
    null,
  );
  assert.equal(readMessage({ ...page(), source: {} }, parent), null);
  assert.equal(readMessage({ ...page(), origin: undefined }, parent), null);
  assert.deepEqual(readMessage(page(), parent), {
    kind: "viewport",
    width: 390,
    height: 844,
  });
});
test("malformed, unbounded or nonnumeric dimensions are rejected", () => {
  for (const width of [0, -1, 239, Infinity, "390", 20000])
    assert.equal(readMessage(page(width), parent), null);
  assert.equal(
    readMessage({ ...page(), data: "[iFrameSizer]pageInfo:{" }, parent),
    null,
  );
  assert.equal(
    readMessage({ ...page(), data: "x".repeat(9000) }, parent),
    null,
  );
});
test("metadata updates only bounded layout and does not grant execution", () => {
  let handler;
  const sent = [],
    styles = {};
  const p = { postMessage: (data, origin) => sent.push({ data, origin }) };
  const win = {
    parent: p,
    innerWidth: 1280,
    location: { origin: "https://app.example" },
    document: { referrer: origin + "/" },
    addEventListener: (kind, f) => (handler = f),
    removeEventListener: () => {
      handler = null;
    },
  };
  const host = {
    style: { setProperty: (k, v) => (styles[k] = v) },
    dataset: {},
  };
  const stop = attach(win, host);
  handler({ ...page(), source: p });
  assert.deepEqual(styles, {}); // no handshake yet
  handler({ source: p, origin, data: "[iFrameSizer]iFrameResizer0:0:false" });
  handler({ source: p, origin, data: "[iFrameSizer]iFrameResizer0:0:false" });
  assert.equal(sent.filter((v) => v.data.endsWith(":pageInfo")).length, 1);
  handler({ ...page(), source: p });
  assert.equal(styles["--portal-width"], "390px");
  assert.equal(host.dataset.portalPhone, "true");
  handler({ ...page(1440), source: p });
  assert.equal(styles["--portal-width"], "1280px");
  assert.equal(host.dataset.portalPhone, "false");
  assert.ok(sent.every((v) => v.origin === origin && !v.data.includes("run")));
  stop();
  assert.equal(handler, null);
  assert.ok(sent.at(-1).data.endsWith(":pageInfoStop"));
});
