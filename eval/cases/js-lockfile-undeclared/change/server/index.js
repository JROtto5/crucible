const express = require("express");
const auth = require("./auth");
const notes = require("./notes");
const uploads = require("./uploads");

const app = express();
app.use(express.json());
app.post("/login", auth.login);
app.use("/notes", auth.requireUser, notes.router);
app.use("/uploads", auth.requireUser, uploads.router);

const port = Number(process.env.PORT || 3000);
app.listen(port, () => console.log(`[server] listening on ${port}`));
