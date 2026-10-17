/** Local static server with same-origin API forwarding. Production uses Nginx. */
import http from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("./public/", import.meta.url));
const upstream = new URL(process.env.API_UPSTREAM || "http://127.0.0.1:8080");
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};
const server = http.createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (
    pathname.startsWith("/api/") ||
    ["/docs", "/redoc", "/openapi.json", "/healthz"].includes(pathname)
  ) {
    const proxy = http.request(
      new URL(request.url, upstream),
      {
        method: request.method,
        headers: { ...request.headers, host: upstream.host },
      },
      (result) => {
        response.writeHead(result.statusCode, result.headers);
        result.pipe(response);
      },
    );
    proxy.on("error", () => {
      if (!response.headersSent)
        response.writeHead(502, { "Content-Type": "application/json" });
      response.end(
        JSON.stringify({
          detail:
            "Backend is unavailable. Start the backend or set API_UPSTREAM.",
        }),
      );
    });
    request.pipe(proxy);
    return;
  }
  try {
    const filename = path.resolve(
      root,
      "." + decodeURIComponent(pathname === "/" ? "/index.html" : pathname),
    );
    if (!filename.startsWith(root) || !(await stat(filename)).isFile())
      throw new Error("Not found");
    const content = await readFile(filename);
    response.writeHead(200, {
      "Content-Type":
        types[path.extname(filename)] || "text/plain; charset=utf-8",
      "Cache-Control": "no-cache",
    });
    response.end(request.method === "HEAD" ? undefined : content);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain" });
    response.end("Not found");
  }
});
const port = Number(process.env.PORT || 3000);
server.listen(port, "127.0.0.1", () =>
  console.log(`EvalOps frontend: http://127.0.0.1:${port}`),
);
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => {
    server.close();
    server.closeAllConnections();
  });
