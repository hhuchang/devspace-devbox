import { DevBox } from "../dist/index.js";

const client = new DevBox();
let sandbox;
try {
  const name = process.env.DEVBOX_TEST_TEMPLATE || "default";
  const templates = await client.templates.list();
  const template = templates.find((item) =>
    [item.name, item.templateId, ...item.aliases].includes(name),
  );
  if (!template) throw new Error(`template ${JSON.stringify(name)} is not available`);
  console.log(`[1/7] Template selected | name=${template.name}, build=${template.buildId}`);
  sandbox = await client.sandboxes.create(template.templateId, {
    buildId: template.buildId,
    timeout: 300,
    envs: { DEMO_MESSAGE: "hello from DevBox" },
    metadata: { example: "javascript-sdk-demo" },
  });
  const info = await sandbox.getInfo();
  console.log(`[2/7] Sandbox created | id=${sandbox.sandboxId}, state=${info.state}`);
  console.log(`      expires_at=${info.endAt?.toISOString()}`);
  const command = await sandbox.commands.run('printf "%s" "$DEMO_MESSAGE"');
  console.log(
    `[3/7] Command executed | exit=${command.exitCode}, stdout=${JSON.stringify(command.stdout)}`,
  );
  const path = "/tmp/devbox-demo.txt";
  await sandbox.files.write(path, "This file must survive a pause.");
  const content = await sandbox.files.read(path);
  console.log(`[4/7] File written and read | path=${path}, content=${JSON.stringify(content)}`);
  const handle = await sandbox.commands.run("cat", {
    background: true,
    stdin: true,
    timeoutMs: 10_000,
  });
  await handle.sendStdin("background input received\n");
  await handle.closeStdin();
  const result = await handle.wait();
  console.log(
    `[5/7] Background stdin -> EOF -> wait | pid=${result.pid}, stdout=${JSON.stringify(result.stdout)}`,
  );
  const started = performance.now();
  await sandbox.pause();
  console.log(
    `[6/7] Paused | state=${(await sandbox.getInfo()).state}, elapsed=${((performance.now() - started) / 1000).toFixed(3)}s`,
  );
  await sandbox.resume({ timeout: 300 });
  const restored = await sandbox.files.read(path);
  if (restored !== content) throw new Error("file changed after resume");
  console.log(
    `[7/7] Resumed | same sandbox=${sandbox.sandboxId}, file preserved=${JSON.stringify(restored)}`,
  );
} finally {
  try {
    await sandbox?.kill();
  } finally {
    await sandbox?.close();
    await client.close();
  }
}
console.log("Demo completed | remote sandbox deleted, local connections closed");
