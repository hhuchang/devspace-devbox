import dns from "node:dns";
import { syncBuiltinESMExports } from "node:module";
import { isIP } from "node:net";

const example = process.argv[2] ?? "validate-full";
if (!["basic", "validate-full"].includes(example)) {
  throw new Error("Expected example: basic or validate-full");
}

const original = dns.lookup;
const gatewayIp = process.env.DEVBOX_GATEWAY_IP?.trim();
if (gatewayIp) {
  if (!isIP(gatewayIp)) throw new Error("DEVBOX_GATEWAY_IP must be an IP address");
  dns.lookup = function lookup(hostname, ...args) {
    const [label, domain] = hostname.toLowerCase().split(".", 2);
    const matches = domain !== undefined && label.endsWith("-49983");
    return original.call(this, matches ? gatewayIp : hostname, ...args);
  };
  // Change DNS only; preserve the URL, HTTP Host, TLS SNI and certificate verification.
  syncBuiltinESMExports();
  console.log(`Local DNS: *-49983.* -> ${gatewayIp}`);
}

try {
  const entry = await import(`./${example}.mjs`);
  if (entry.main) await entry.main({ args: process.argv.slice(3) });
} finally {
  dns.lookup = original;
  syncBuiltinESMExports();
}
