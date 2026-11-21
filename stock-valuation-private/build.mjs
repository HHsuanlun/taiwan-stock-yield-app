import {mkdir, readFile, writeFile} from "node:fs/promises";
const html = await readFile("index.html", "utf8");
const app = await readFile("app.mjs", "utf8");
await mkdir("dist/server", {recursive: true});
await writeFile("dist/server/index.js", app + "\nexport default {fetch: createHandler(" + JSON.stringify(html) + ")};\n");
