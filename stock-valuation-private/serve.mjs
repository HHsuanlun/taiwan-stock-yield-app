import {createServer} from "node:http";
import {readFile} from "node:fs/promises";
import {createHandler} from "./app.mjs";
const handler = createHandler(await readFile(new URL("./index.html", import.meta.url), "utf8"));
createServer(async (req, res) => {
  const result = await handler(new Request(new URL(req.url, "http://127.0.0.1:8766")));
  res.writeHead(result.status, Object.fromEntries(result.headers));
  res.end(Buffer.from(await result.arrayBuffer()));
}).listen(8766, "127.0.0.1", () => console.log("http://127.0.0.1:8766"));
