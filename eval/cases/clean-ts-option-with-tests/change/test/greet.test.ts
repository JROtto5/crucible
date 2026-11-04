import { greet } from '../src/index';
if (greet('Ada') !== 'Hello, Ada!') throw new Error('greet');
if (greet('Ada', { punctuation: '.' }) !== 'Hello, Ada.') throw new Error('punctuation');
