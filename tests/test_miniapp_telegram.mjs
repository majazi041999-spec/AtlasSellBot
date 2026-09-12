import assert from 'node:assert/strict';
import { initData, closeOrReload } from '../web/miniapp/src/telegram.js';

const signed = 'auth_date=1800000000&user=%7B%22id%22%3A123%2C%22first_name%22%3A%22A%2BB%22%7D&hash=test-signature';
let reloads = 0, closes = 0;
global.window = { location: { hash: '#tgWebAppData=' + encodeURIComponent(signed) + '&tgWebAppPlatform=tdesktop', reload() { reloads++; } } };
assert.equal(initData(), signed, 'Blocked SDK must retain exact launch credentials');
closeOrReload();
assert.equal(reloads, 1, 'Missing SDK must not make recovery a no-op');
window.Telegram = { WebApp: { initData: 'fresh-sdk-value', close() { closes++; } } };
assert.equal(initData(), 'fresh-sdk-value', 'Late SDK must be read dynamically');
closeOrReload();
assert.equal(closes, 1);
window.Telegram.WebApp.initData = 'updated';
assert.equal(initData(), 'updated');
delete window.Telegram;
window.location.hash = '';
assert.equal(initData(), '', 'Ordinary browser must not invent credentials');
console.log('Mini App launch transport and recovery passed');
