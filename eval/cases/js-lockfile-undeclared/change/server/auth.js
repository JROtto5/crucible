const jwt = require("jsonwebtoken");

const SECRET = process.env.NOTES_JWT_SECRET;
if (!SECRET) throw new Error("NOTES_JWT_SECRET is not set");

const users = new Map([["admin", process.env.NOTES_ADMIN_PASSWORD]]);

function login(req, res) {
  const { user, password } = req.body || {};
  if (!users.has(user) || !password || users.get(user) !== password) {
    return res.status(401).json({ error: "bad credentials" });
  }
  res.json({ token: jwt.sign({ sub: user }, SECRET, { expiresIn: "1h" }) });
}

function requireUser(req, res, next) {
  const header = req.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  try {
    req.user = jwt.verify(token, SECRET).sub;
    next();
  } catch {
    res.status(401).json({ error: "login required" });
  }
}

module.exports = { login, requireUser };
