// Long-running Lottie preview renderer. One headless Chrome, one page, many renders.
// Protocol: one JSON request per stdin line, one JSON reply per stdout line.
//   {"id":1,"comp":{...normalized IR...},"times":[0,0.5],"out":"/abs/dir","prefix":"p"}
//   -> {"id":1,"files":["/abs/dir/p-t0.png",...],"ms":12.3,"errors":[]}
// Pinned lottie-web (SVG renderer) plus proxy_adapter.js, which holds values exactly as After Effects evaluates them.
import puppeteer from 'puppeteer-core';
import {createInterface} from 'node:readline';
import {writeFileSync, mkdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const browser = await puppeteer.launch({
  executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true, protocolTimeout: 60000,
  args: ['--disable-renderer-backgrounding', '--disable-background-timer-throttling'],
});
const page = await browser.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
await page.setContent('<!doctype html><meta charset="utf-8"><body style="margin:0"><div id="wrap"></div></body>');
await page.addScriptTag({path: join(root, 'node_modules/lottie-web/build/player/lottie.min.js')});
await page.addScriptTag({path: join(here, 'proxy_adapter.js')});
await page.evaluate(() => {
  let anim = null, cv = null, comp = null;
  window.loadComp = async data => {
    if (anim) { anim.destroy(); anim = null; }
    comp = data;
    const wrap = document.getElementById('wrap');
    wrap.innerHTML = ''; wrap.style.width = comp.w + 'px'; wrap.style.height = comp.h + 'px';
    anim = lottie.loadAnimation({container: wrap, renderer: 'svg', loop: false, autoplay: false, animationData: comp,
      rendererSettings: {progressiveLoad: false, preserveAspectRatio: 'xMidYMid meet'}});
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('DOMLoaded timeout')), 20000);
      anim.addEventListener('DOMLoaded', () => { clearTimeout(timer); resolve(); });
      anim.addEventListener('data_failed', () => { clearTimeout(timer); reject(Error('Lottie data_failed')); });
    });
    window.installExactValueAdapter(anim);
    cv = document.createElement('canvas'); cv.width = comp.w; cv.height = comp.h;
  };
  window.renderAt = async t => {
    if (!Number.isFinite(t) || t < 0 || t >= comp.op / comp.fr) throw Error('time outside composition: ' + t);
    anim.goToAndStop(t * anim.frameRate, true);
    const svg = document.querySelector('#wrap svg').cloneNode(true);
    svg.setAttribute('width', cv.width); svg.setAttribute('height', cv.height);
    svg.style.width = cv.width + 'px'; svg.style.height = cv.height + 'px';
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], {type: 'image/svg+xml'}));
    try {
      const image = new Image(); image.src = url; await image.decode();
      const ctx = cv.getContext('2d'); ctx.clearRect(0, 0, cv.width, cv.height); ctx.drawImage(image, 0, 0, cv.width, cv.height);
    } finally { URL.revokeObjectURL(url); }
    return cv.toDataURL('image/png');
  };
});

const tag = t => 't' + Number(t).toFixed(6).replace(/0+$/, '').replace(/\.$/, '').replace('.', '_');
const reply = obj => process.stdout.write(JSON.stringify(obj) + '\n');
reply({ready: true, lottie: await page.evaluate('lottie.version')});

const lines = createInterface({input: process.stdin});
for await (const line of lines) {
  if (!line.trim()) continue;
  let request;
  try { request = JSON.parse(line); } catch (e) { reply({error: 'bad json'}); continue; }
  const start = performance.now();
  errors.length = 0;
  try {
    await page.evaluate(c => window.loadComp(c), request.comp);
    mkdirSync(request.out, {recursive: true});
    const files = [];
    for (const t of request.times) {
      const url = await page.evaluate(t => window.renderAt(t), t);
      const file = join(request.out, `${request.prefix || 'proxy'}-${tag(t)}.png`);
      writeFileSync(file, Buffer.from(url.split(',')[1], 'base64'));
      files.push(file);
    }
    reply({id: request.id, files, ms: performance.now() - start, errors: [...errors]});
  } catch (e) {
    reply({id: request.id, error: String(e.message || e), errors: [...errors]});
  }
}
await browser.close();
