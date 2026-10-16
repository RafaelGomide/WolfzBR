// Valida a sintaxe de documentos Power Query M com o parser oficial da
// Microsoft (@microsoft/powerquery-parser). Usado pelo pytest (F0.F5).
//
// Entrada (stdin): JSON com uma lista de documentos M.
// Saída (stdout): JSON com uma lista de {"ok": true} ou {"ok": false, "error": "..."}.
//
// Em lote, para pagar a partida do Node uma vez só.

import { DefaultSettings, TaskUtils } from "@microsoft/powerquery-parser";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const documents = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const results = [];
for (const text of documents) {
    const task = await TaskUtils.tryLexParse(DefaultSettings, text);
    if (TaskUtils.isOk(task)) {
        results.push({ ok: true });
    } else {
        const error = task.error;
        results.push({ ok: false, error: error?.message ?? String(error) });
    }
}
process.stdout.write(JSON.stringify(results));
