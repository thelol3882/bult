// Demo app for the bult Express preset.
//
// Preset conventions it follows: dependencies in package.json with a lockfile,
// entry point via `npm start` / `main`, the port comes from $PORT.
// No Dockerfile here on purpose — the preset provides it.
const express = require("express");
const os = require("os");

const app = express();
const port = Number(process.env.PORT) || 3000;
const startedAt = Date.now();

app.get("/", (req, res) => {
  // hostname = container ID: shows which replica answered (handy behind nginx).
  res.json({
    app: "express-hello",
    hostname: os.hostname(),
    port: process.env.PORT ?? null,
    uptime_s: Math.round((Date.now() - startedAt) / 100) / 10,
  });
});

app.get("/healthz", (req, res) => res.json({ status: "ok" }));

const server = app.listen(port, "0.0.0.0", () => {
  console.log(`express-hello listening on :${port}`);
});

// Exit promptly on SIGTERM (docker stop / StopReplica) instead of waiting
// for the 10 s grace period to end in SIGKILL.
process.on("SIGTERM", () => server.close(() => process.exit(0)));
