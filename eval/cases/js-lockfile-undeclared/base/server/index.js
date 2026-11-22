const express = require("express");
const notes = require("./notes");

const app = express();
app.use(express.json());
app.use("/notes", notes.router);

const port = Number(process.env.PORT || 3000);
app.listen(port, () => console.log(`[server] listening on ${port}`));
