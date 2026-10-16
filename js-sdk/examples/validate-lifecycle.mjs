import { pathToFileURL } from "node:url";
import { main as validate } from "./validate-full.mjs";

export async function main() {
  await validate({ lifecycleOnly: true });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
