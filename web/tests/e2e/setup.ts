import type { TestProject } from "vitest/node";
import { startAll } from "./harness";

let stop: (() => Promise<void>) | undefined;

export default async function setup(project: TestProject) {
  const env = await startAll();
  stop = env.stop;
  project.provide("e2e", { db: env.db, privateJwk: env.privateJwk });
  return async () => { await stop?.(); };
}

declare module "vitest" {
  export interface ProvidedContext {
    e2e: { db: import("./harness").DbInfo; privateJwk: import("jose").JWK };
  }
}
