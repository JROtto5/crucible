import { total } from '../src/cart.js';
import assert from 'node:assert';
assert.strictEqual(total([{ price: 2, qty: 3 }, { price: 1, qty: 1 }]), 7);
