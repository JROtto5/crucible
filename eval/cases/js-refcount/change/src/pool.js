// Each connection is shared; refs counts its current users. It is closed when refs drops to 0.
export class Pool {
  constructor() { this.conns = new Map(); }
  acquire(key, open) {
    let c = this.conns.get(key);
    if (!c) { c = { conn: open(), refs: 0 }; this.conns.set(key, c); }
    c.refs++;
    return c.conn;
  }
  release(key) {
    const c = this.conns.get(key);
    if (!c) return;
    if (--c.refs === 0) { c.conn.close(); this.conns.delete(key); }
  }
  // Release every connection (e.g. when a worker shuts down).
  releaseAll() {
    for (const c of this.conns.values()) c.conn.close();
    this.conns.clear();
  }
}
