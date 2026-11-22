const express = require("express");

const router = express.Router();
const notes = new Map();

router.get("/", (req, res) => res.json([...notes.values()]));
router.post("/", (req, res) => {
  const id = String(notes.size + 1);
  notes.set(id, { id, text: String(req.body.text || "") });
  res.status(201).json(notes.get(id));
});

module.exports = { router };
