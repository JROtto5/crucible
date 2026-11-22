const express = require("express");
const multer = require("multer");
const path = require("path");

const router = express.Router();
const upload = multer({ dest: path.join(__dirname, "data", "uploads"), limits: { fileSize: 5 * 1024 * 1024 } });

router.post("/", upload.single("file"), (req, res) => {
  if (!req.file) return res.status(400).json({ error: "no file" });
  res.status(201).json({ id: req.file.filename, size: req.file.size });
});

module.exports = { router };
