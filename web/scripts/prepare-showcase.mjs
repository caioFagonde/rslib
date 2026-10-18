import {cpSync, existsSync, mkdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const source = fileURLToPath(new URL('../../docs/showcase/', import.meta.url));
const target = fileURLToPath(new URL('../public/showcase/', import.meta.url));
if (existsSync(source)) {
  mkdirSync(target, {recursive: true});
  cpSync(source, target, {recursive: true});
}
