import { cp, mkdir, access } from "node:fs/promises";
import path from "node:path";
const root = process.cwd();
await mkdir(path.join(root, ".next/standalone/.next"), { recursive: true });
await cp(
  path.join(root, ".next/static"),
  path.join(root, ".next/standalone/.next/static"),
  { recursive: true },
);
try {
  await access(path.join(root, "public"));
  await cp(
    path.join(root, "public"),
    path.join(root, ".next/standalone/public"),
    { recursive: true },
  );
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
console.log("Standalone server assets prepared.");
