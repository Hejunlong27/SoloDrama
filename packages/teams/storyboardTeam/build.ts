import { createTeamConfig } from "@solodrama/teams-scaffold";

await createTeamConfig(import.meta.url, { sync: process.argv.includes("--sync") ? "replace" : "missing" });
