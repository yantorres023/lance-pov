// Lance POV — reconstrói um lance a partir de dados de posição e mostra pelos olhos de um jogador.
// Coordenadas do dado: metros, origem no centro do campo, x ao longo do comprimento, y para o lado
// oposto à câmera de TV, z para cima. Na cena (three.js): X = x, Y = z, Z = -y.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (s) => document.querySelector(s);
const HX = 52.5, HY = 34;          // meio comprimento e meia largura do campo
const OLHO = 1.72;                  // altura dos olhos (m)
const SUB = 4;                      // subamostras por frame no cálculo do olhar
const PASSADA = 1.9;                // metros por ciclo de corrida
const PESCOCO = 1.45;               // giro máximo da cabeça em relação ao corpo (rad, ≈ 83°)
const v3 = (x, y, z = 0) => new THREE.Vector3(x, z, -y);
const yawDe = (dx, dy) => Math.atan2(dx, -dy);   // direção (dx, dy) do campo → ângulo em torno do eixo Y da cena (inverso de dirDe)
const dirDe = (yaw, pitch = 0) => new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
const embrulha = (a) => Math.atan2(Math.sin(a), Math.cos(a));
const limita = (v, a, b) => Math.min(b, Math.max(a, v));

const estado = {
  lances: [], lance: null, t: 0, tocando: false, vel: 1,
  sel: null, vista: 'pov', olhar: 'misto', fov: 75,
  rotulos: true, gravando: false, fimEspera: 0,
};

// ---------------------------------------------------------------- renderer e cena
const canvas = $('#cena');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const ANISO = renderer.capabilities.getMaxAnisotropy();

const cena = new THREE.Scene();
cena.background = texCeu();
cena.fog = new THREE.Fog(0xd9e2ec, 160, 380);

const camera = new THREE.PerspectiveCamera(75, 1, 0.05, 700);
const controles = new OrbitControls(camera, canvas);
controles.enabled = false;
controles.enableDamping = true;
controles.maxPolarAngle = Math.PI * 0.49;

cena.add(new THREE.HemisphereLight(0xe3ecff, 0x40603a, 1.25));
const sol = new THREE.DirectionalLight(0xfff6e8, 2.4);
sol.position.set(-45, 85, 35);
sol.castShadow = true;
sol.shadow.mapSize.set(4096, 4096);
Object.assign(sol.shadow.camera, { left: -75, right: 75, top: 60, bottom: -60, near: 10, far: 250 });
sol.shadow.bias = -0.0004;
sol.shadow.normalBias = 0.03;
cena.add(sol);

montarEstadio();

// ---------------------------------------------------------------- texturas
function canvasTex(w, h, desenha, cor = true) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  desenha(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  if (cor) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = ANISO;
  return t;
}

function texCeu() {
  return canvasTex(4, 256, (g, w, h) => {
    const gr = g.createLinearGradient(0, 0, 0, h);
    gr.addColorStop(0, '#7fa6d1');
    gr.addColorStop(0.55, '#c4d5e8');
    gr.addColorStop(1, '#eef2f5');
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
  });
}

function texGramado() {
  return canvasTex(2048, 1024, (g, w, h) => {
    const faixas = 18;
    for (let i = 0; i < faixas; i++) {
      g.fillStyle = i % 2 ? '#3d8537' : '#47953f';
      g.fillRect(Math.floor(i * w / faixas), 0, Math.ceil(w / faixas) + 1, h);
    }
    const img = g.getImageData(0, 0, w, h), d = img.data;
    for (let i = 0; i < d.length; i += 4) {
      const n = (Math.random() - 0.5) * 16;
      d[i] += n; d[i + 1] += n; d[i + 2] += n;
    }
    g.putImageData(img, 0, 0);
  });
}

function texRede() {
  const t = canvasTex(64, 64, (g, w, h) => {
    g.clearRect(0, 0, w, h);
    g.strokeStyle = 'rgba(255,255,255,0.95)';
    g.lineWidth = 3;
    g.beginPath(); g.moveTo(0, 1.5); g.lineTo(w, 1.5); g.moveTo(1.5, 0); g.lineTo(1.5, h); g.stroke();
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

function texTorcida() {
  const t = canvasTex(512, 256, (g, w, h) => {
    g.fillStyle = '#2a2e35'; g.fillRect(0, 0, w, h);
    const cores = ['#c8102e', '#e8e8e8', '#1b1b1b', '#d6b98c', '#8a1b2b', '#f2f2f2', '#3a4a6b', '#b33'];
    for (let y = 4; y < h; y += 9) {
      g.fillStyle = '#1e2127'; g.fillRect(0, y + 6, w, 2);
      for (let x = 2; x < w; x += 6 + Math.random() * 3) {
        if (Math.random() < 0.12) continue;
        g.fillStyle = cores[(Math.random() * cores.length) | 0];
        g.fillRect(x, y + Math.random() * 1.5, 4, 5);
        g.fillStyle = Math.random() < 0.5 ? '#e0b48a' : '#8d5a3b';
        g.fillRect(x + 1, y - 2, 2, 2);
      }
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

function texPlaca() {
  const t = canvasTex(512, 64, (g, w, h) => {
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#ff5a1f'; g.fillRect(0, 0, w / 2, h);
    g.font = 'bold 34px system-ui, sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillStyle = '#ffffff'; g.fillText('LANCE POV', w / 4, h / 2 + 2);
    g.fillStyle = '#1d1f23'; g.fillText('LANCE POV', 3 * w / 4, h / 2 + 2);
  });
  t.wrapS = THREE.RepeatWrapping;
  return t;
}

function texBola() {
  return canvasTex(256, 128, (g, w, h) => {
    g.fillStyle = '#f7f7f7'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#222';
    for (let i = 0; i < 12; i++) {
      const x = (i % 6) * (w / 6) + (i < 6 ? 0 : w / 12), y = i < 6 ? h * 0.3 : h * 0.72;
      g.beginPath();
      for (let k = 0; k < 5; k++) {
        const a = k / 5 * Math.PI * 2;
        g.lineTo(x + Math.cos(a) * 11, y + Math.sin(a) * 11);
      }
      g.fill();
    }
  });
}

function texCamisa(cor, borda, numero) {
  return canvasTex(256, 128, (g, w, h) => {
    g.fillStyle = cor; g.fillRect(0, 0, w, h);
    g.fillStyle = borda; g.fillRect(0, 0, w, 8);
    if (numero != null) {
      g.font = 'bold 60px system-ui, sans-serif';
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(String(numero), w / 2, h / 2 + 6);   // u = 0,5 fica nas costas
      g.font = 'bold 22px system-ui, sans-serif';
      g.fillText(String(numero), w * 0.94, h * 0.35); // pequeno, no peito (u ≈ 0)
    }
  });
}

function texRotulo(texto, destaque) {
  const t = canvasTex(512, 64, (g, w, h) => {
    g.font = '600 30px system-ui, sans-serif';
    const lw = Math.min(w - 4, g.measureText(texto).width + 28);
    g.fillStyle = destaque ? 'rgba(255,90,31,0.95)' : 'rgba(20,22,26,0.62)';
    const x = (w - lw) / 2;
    g.beginPath(); g.roundRect(x, 10, lw, 44, 22); g.fill();
    g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(texto, w / 2, 33);
  });
  return t;
}

// ---------------------------------------------------------------- estádio
function montarEstadio() {
  const solo = new THREE.Mesh(new THREE.PlaneGeometry(170, 130), new THREE.MeshStandardMaterial({ color: 0x3b7d35, roughness: 1 }));
  solo.rotation.x = -Math.PI / 2; solo.position.y = -0.02; solo.receiveShadow = true;
  cena.add(solo);

  const gramado = new THREE.Mesh(new THREE.PlaneGeometry(HX * 2, HY * 2), new THREE.MeshStandardMaterial({ map: texGramado(), roughness: 1 }));
  gramado.rotation.x = -Math.PI / 2; gramado.receiveShadow = true;
  cena.add(gramado);

  const matLinha = new THREE.MeshStandardMaterial({ color: 0xf2f2ee, roughness: 0.9 });
  const L = 0.12;
  const seg = (x1, y1, x2, y2) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(Math.hypot(x2 - x1, y2 - y1) + L, L), matLinha);
    m.rotation.x = -Math.PI / 2; m.rotation.z = Math.atan2(y2 - y1, x2 - x1);
    m.position.copy(v3((x1 + x2) / 2, (y1 + y2) / 2, 0.012)); m.receiveShadow = true;
    cena.add(m);
  };
  const arco = (cx, cy, r, a0, a1) => {
    const m = new THREE.Mesh(new THREE.RingGeometry(r - L / 2, r + L / 2, 96, 1, a0, a1 - a0), matLinha);
    m.rotation.x = -Math.PI / 2; m.position.copy(v3(cx, cy, 0.012)); m.receiveShadow = true;
    cena.add(m);
  };
  const ponto = (x, y) => {
    const m = new THREE.Mesh(new THREE.CircleGeometry(0.15, 20), matLinha);
    m.rotation.x = -Math.PI / 2; m.position.copy(v3(x, y, 0.013)); cena.add(m);
  };

  seg(-HX, -HY, HX, -HY); seg(-HX, HY, HX, HY); seg(-HX, -HY, -HX, HY); seg(HX, -HY, HX, HY); seg(0, -HY, 0, HY);
  arco(0, 0, 9.15, 0, Math.PI * 2); ponto(0, 0);
  const meiaLua = Math.acos(5.5 / 9.15);
  for (const s of [-1, 1]) {
    const gx = s * HX, bx = s * (HX - 16.5), ax = s * (HX - 5.5);
    seg(gx, -20.16, bx, -20.16); seg(gx, 20.16, bx, 20.16); seg(bx, -20.16, bx, 20.16);
    seg(gx, -9.16, ax, -9.16); seg(gx, 9.16, ax, 9.16); seg(ax, -9.16, ax, 9.16);
    ponto(s * (HX - 11), 0);
    if (s > 0) arco(HX - 11, 0, 9.15, Math.PI - meiaLua, Math.PI + meiaLua);
    else arco(-HX + 11, 0, 9.15, -meiaLua, meiaLua);
    for (const sy of [-1, 1]) {
      const a = Math.atan2(-sy, -s);
      arco(s * HX, sy * HY, 1, a - Math.PI / 4, a + Math.PI / 4);
    }
    montarGol(s);
  }

  // placas de publicidade
  const placa = texPlaca();
  const matPlaca = (comp) => { const t = placa.clone(); t.needsUpdate = true; t.repeat.set(comp / 9, 1); return new THREE.MeshStandardMaterial({ map: t, roughness: 0.6 }); };
  const placaEm = (x, y, comp, girar) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(comp, 0.9, 0.08), matPlaca(comp));
    m.position.copy(v3(x, y, 0.45)); if (girar) m.rotation.y = Math.PI / 2; m.castShadow = true;
    cena.add(m);
  };
  placaEm(0, -HY - 5, 118); placaEm(0, HY + 5, 118);
  placaEm(-HX - 5, 0, 76, true); placaEm(HX + 5, 0, 76, true);

  // arquibancadas
  const torcida = texTorcida();
  const bancada = (comp, x, y, giro) => {
    const prof = 32, alt = 20, sl = Math.hypot(prof, alt), incl = Math.atan2(alt, prof);
    const g = new THREE.Group();
    const t = torcida.clone(); t.needsUpdate = true; t.repeat.set(comp / 22, sl / 11);
    const degrau = new THREE.Mesh(new THREE.PlaneGeometry(comp, sl), new THREE.MeshStandardMaterial({ map: t, roughness: 1 }));
    degrau.rotation.x = -Math.PI / 2 + incl; degrau.position.set(0, alt / 2 + 1.2, -prof / 2);
    g.add(degrau);
    const matConc = new THREE.MeshStandardMaterial({ color: 0x9aa0a8, roughness: 1 });
    const muro = new THREE.Mesh(new THREE.BoxGeometry(comp, 1.2, 0.4), matConc); muro.position.set(0, 0.6, 0); g.add(muro);
    const fundo = new THREE.Mesh(new THREE.BoxGeometry(comp, alt + 9, 1), matConc); fundo.position.set(0, (alt + 9) / 2, -prof - 0.5); g.add(fundo);
    const teto = new THREE.Mesh(new THREE.BoxGeometry(comp, 0.6, prof * 0.75), new THREE.MeshStandardMaterial({ color: 0xb4bac2, emissive: 0x30343a, roughness: 0.8 }));
    teto.position.set(0, alt + 8.5, -prof + prof * 0.375); g.add(teto);
    g.position.copy(v3(x, y, 0)); g.rotation.y = giro;
    cena.add(g);
  };
  bancada(128, 0, HY + 9, 0);
  bancada(128, 0, -HY - 9, Math.PI);
  bancada(86, HX + 9, 0, -Math.PI / 2);
  bancada(86, -HX - 9, 0, Math.PI / 2);
}

function montarGol(s) {
  const H = 2.44, W = 7.32 / 2, D = 2.0, r = 0.06, gx = s * HX;
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35 });
  const trave = (comp) => new THREE.Mesh(new THREE.CylinderGeometry(r, r, comp, 14), mat);
  for (const sy of [-1, 1]) {
    const p = trave(H); p.position.copy(v3(gx, sy * (W + r), H / 2)); p.castShadow = true; cena.add(p);
    const b = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, H, 8), mat);
    b.position.copy(v3(gx + s * D, sy * W, H / 2)); cena.add(b);
  }
  const t = trave(2 * W + 4 * r); t.rotation.x = Math.PI / 2; t.position.copy(v3(gx, 0, H)); t.castShadow = true; cena.add(t);

  const base = texRede();
  const rede = (w, h) => {
    const tx = base.clone(); tx.needsUpdate = true; tx.repeat.set(w / 0.14, h / 0.14);
    return new THREE.MeshBasicMaterial({ map: tx, transparent: true, alphaTest: 0.3, side: THREE.DoubleSide, depthWrite: false });
  };
  const fundo = new THREE.Mesh(new THREE.PlaneGeometry(2 * W, H), rede(2 * W, H));
  fundo.rotation.y = Math.PI / 2; fundo.position.copy(v3(gx + s * D, 0, H / 2)); cena.add(fundo);
  for (const sy of [-1, 1]) {
    const lado = new THREE.Mesh(new THREE.PlaneGeometry(D, H), rede(D, H));
    lado.position.copy(v3(gx + s * D / 2, sy * W, H / 2)); cena.add(lado);
  }
  const teto = new THREE.Mesh(new THREE.PlaneGeometry(D, 2 * W), rede(D, 2 * W));
  teto.rotation.x = -Math.PI / 2; teto.position.copy(v3(gx + s * D / 2, 0, H)); cena.add(teto);
}

// ---------------------------------------------------------------- bola e jogadores
const bola = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 16), new THREE.MeshStandardMaterial({ map: texBola(), roughness: 0.45 }));
bola.castShadow = true;
cena.add(bola);

const anelSel = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.72, 40), new THREE.MeshBasicMaterial({ color: 0xff5a1f, transparent: true, opacity: 0.9 }));
anelSel.rotation.x = -Math.PI / 2;
cena.add(anelSel);

const PELES = ['#f1c27d', '#e0ac69', '#c68642', '#8d5524', '#ffdbac', '#a16e4b'];
const G = {
  perna: new THREE.CylinderGeometry(0.075, 0.055, 0.46, 10).translate(0, -0.23, 0),
  canela: new THREE.CylinderGeometry(0.06, 0.045, 0.44, 10).translate(0, -0.68, 0),
  pe: new THREE.BoxGeometry(0.1, 0.07, 0.25).translate(0, -0.9, 0.05),
  braco: new THREE.CylinderGeometry(0.05, 0.038, 0.6, 8).translate(0, -0.3, 0),
  tronco: new THREE.CylinderGeometry(0.21, 0.17, 0.58, 18),
  calcao: new THREE.CylinderGeometry(0.175, 0.19, 0.22, 16),
  cabeca: new THREE.SphereGeometry(0.115, 16, 12),
  cabelo: new THREE.SphereGeometry(0.12, 16, 8, 0, Math.PI * 2, 0, Math.PI * 0.55),
};

function corCss(c, padrao) { try { return '#' + new THREE.Color(c || padrao).getHexString(); } catch { return padrao; } }

function criarBoneco(j, idx) {
  const cor = corCss(j.cor, '#888888'), borda = corCss(j.borda, '#ffffff');
  const pele = new THREE.MeshStandardMaterial({ color: PELES[idx % PELES.length], roughness: 0.7 });
  const camisa = new THREE.MeshStandardMaterial({ map: texCamisa(cor, borda, j.numero), roughness: 0.85 });
  const calcao = new THREE.MeshStandardMaterial({ color: new THREE.Color(cor).multiplyScalar(0.75), roughness: 0.85 });
  const meiao = new THREE.MeshStandardMaterial({ color: borda, roughness: 0.85 });
  const chuteira = new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 0.5 });
  const cabelo = new THREE.MeshStandardMaterial({ color: 0x1c1410, roughness: 0.9 });

  const g = new THREE.Group();
  const add = (geo, mat, pai = g) => { const m = new THREE.Mesh(geo, mat); m.castShadow = true; m.userData.jogador = j; pai.add(m); return m; };
  const tronco = add(G.tronco, camisa); tronco.position.y = 1.24;
  add(G.calcao, calcao).position.y = 0.92;
  const cab = add(G.cabeca, pele); cab.position.y = 1.67;
  const cb = add(G.cabelo, cabelo); cb.position.y = 1.685;
  const pernas = [-1, 1].map((s) => {
    const p = new THREE.Group(); p.position.set(s * 0.1, 0.94, 0); g.add(p);
    add(G.perna, pele, p); add(G.canela, meiao, p); add(G.pe, chuteira, p);
    return p;
  });
  const bracos = [-1, 1].map((s) => {
    const b = new THREE.Group(); b.position.set(s * 0.26, 1.48, 0); b.rotation.z = s * 0.12; g.add(b);
    add(G.braco, pele, b);
    return b;
  });

  const rotulo = new THREE.Sprite(new THREE.SpriteMaterial({ map: texRotulo(nomeCurto(j), false), depthWrite: false, transparent: true }));
  rotulo.scale.set(4.8, 0.6, 1); rotulo.position.y = 2.25; g.add(rotulo);

  cena.add(g);
  return { g, pernas, bracos, tronco, rotulo };
}

function nomeCurto(j) {
  if (j.nome) return j.numero != null ? `${j.numero} ${j.nome}` : j.nome;
  if (j.numero != null) return `#${j.numero}`;
  return j.rotuloGenerico;
}

// ---------------------------------------------------------------- dados do lance
function amostra(arr, t) {
  const n = arr.length, i = limita(Math.floor(t), 0, n - 1), k = limita(t - i, 0, 1);
  const a = arr[i], b = arr[Math.min(i + 1, n - 1)];
  if (!a) return b ? b.slice() : null;
  if (!b || k === 0) return a.slice();
  return a.map((v, d) => v + (b[d] - v) * k);
}

function amostraNum(arr, t) {
  const n = arr.length, i = limita(Math.floor(t), 0, n - 1), k = limita(t - i, 0, 1);
  return arr[i] + (arr[Math.min(i + 1, n - 1)] - arr[i]) * k;
}

function amostraAngulo(arr, t) {
  const n = arr.length, i = limita(Math.floor(t), 0, n - 1), k = limita(t - i, 0, 1);
  const a = arr[i], b = arr[Math.min(i + 1, n - 1)];
  return a + embrulha(b - a) * k;
}

function suaviza(alvo, fps, taxa, maxVel, inicio) {
  // segue o ângulo-alvo com resposta exponencial e limite de velocidade angular (rad/s)
  const dt = 1 / fps, k = 1 - Math.exp(-dt * taxa), out = new Float32Array(alvo.length);
  let a = inicio ?? alvo[0];
  for (let i = 0; i < alvo.length; i++) {
    a += limita(embrulha(alvo[i] - a) * k, -maxVel * dt, maxVel * dt);
    out[i] = a = embrulha(a);
  }
  return out;
}

function prepararLance(l) {
  const fps = l.fps, n = l.frames;
  // preenche buracos da bola com a última posição conhecida
  let ult = l.bola.find(Boolean) || [0, 0, 0];
  l.bola = l.bola.map((b) => (b ? (ult = b) : ult));

  const contagem = { attack: 0, defense: 0 };
  l.jogadores.forEach((j, idx) => {
    contagem[j.time] = (contagem[j.time] || 0) + 1;
    j.rotuloGenerico = `${j.time === 'attack' ? 'A' : 'D'}${contagem[j.time]}`;
    j.nomeTime = l.times?.[j.time] || (j.time === 'attack' ? 'Ataque' : 'Defesa');
    const vel = [], acum = new Float32Array(n), alvo = new Float32Array(n);
    let dist = 0;
    for (let f = 0; f < n; f++) {
      const a = j.pos[Math.max(0, f - 2)] || j.pos[f], b = j.pos[Math.min(n - 1, f + 2)] || j.pos[f], p = j.pos[f];
      const dtv = (Math.min(n - 1, f + 2) - Math.max(0, f - 2)) / fps;
      const v = a && b && dtv > 0 ? [(b[0] - a[0]) / dtv, (b[1] - a[1]) / dtv] : [0, 0];
      vel.push(v);
      if (f > 0 && p && j.pos[f - 1]) dist += Math.hypot(p[0] - j.pos[f - 1][0], p[1] - j.pos[f - 1][1]);
      acum[f] = dist;
      const veloc = Math.hypot(v[0], v[1]), bl = l.bola[f];
      if (veloc > 1.2) alvo[f] = yawDe(v[0], v[1]);
      else if (p) alvo[f] = yawDe(bl[0] - p[0], bl[1] - p[1]);
      else alvo[f] = f ? alvo[f - 1] : 0;
    }
    j.vel = vel; j.acum = acum;
    j.corpo = suaviza(alvo, fps, 6, 7);
    j.boneco = criarBoneco(j, idx);
  });

  const heuristica = acharFinalizador(l);   // também calcula l.frameGol
  l.finalizador = (l.finalizadorNumero != null && l.jogadores.find((j) => j.time === 'attack' && j.numero === l.finalizadorNumero)) || heuristica;
}

function acharFinalizador(l) {
  let fGol = l.bola.findIndex((b) => Math.abs(b[0]) > HX - 0.2 && Math.abs(b[1]) < 4.2);
  if (fGol < 0) fGol = l.frames - 1;
  l.frameGol = fGol;
  for (let f = fGol; f >= 0; f--) {
    const b = l.bola[f];
    let melhor = null, md = 1.6;
    for (const j of l.jogadores) {
      if (j.time !== 'attack' || !j.pos[f]) continue;
      const d = Math.hypot(j.pos[f][0] - b[0], j.pos[f][1] - b[1]);
      if (d < md) { md = d; melhor = j; }
    }
    if (melhor) return melhor;
  }
  return l.jogadores.find((j) => j.time === 'attack') || l.jogadores[0];
}

function calcularOlhar(l, j, modo) {
  // olhar da cabeça em SUB amostras por frame: yaw (horizontal) e pitch (vertical)
  const fps = l.fps * SUB, n = (l.frames - 1) * SUB + 1;
  const ay = new Float32Array(n), ap = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SUB, p = amostra(j.pos, t) || [0, 0], b = amostra(l.bola, t);
    const corpo = amostraAngulo(j.corpo, t), v = amostra(j.vel, t), veloc = Math.hypot(v[0], v[1]);
    const dx = b[0] - p[0], dy = b[1] - p[1], dist = Math.max(0.3, Math.hypot(dx, dy));
    const yBola = yawDe(dx, dy), pBola = Math.atan2(b[2] + 0.11 - OLHO, dist);
    const yCorrida = veloc > 1.2 ? yawDe(v[0], v[1]) : corpo;
    if (modo === 'bola') { ay[i] = yBola; ap[i] = pBola; }
    else if (modo === 'corrida') { ay[i] = yCorrida; ap[i] = -0.1; }
    else { ay[i] = limita(embrulha(yBola - corpo), -PESCOCO, PESCOCO); ap[i] = -0.04 + (pBola + 0.04) * 0.85; }
    ap[i] = limita(ap[i], -0.75, 0.55);
  }
  // no modo Natural, yaw guarda o desvio da cabeça em relação ao corpo (ver yawOlhar)
  return { relativo: modo === 'misto', yaw: suaviza(ay, fps, 9, 6.5), pitch: suaviza(ap, fps, 7, 4) };
}

function yawOlhar(j, t) {
  if (!olhar.relativo) return amostraAngulo(olhar.yaw, t * SUB);
  return amostraAngulo(j.corpo, t) + limita(amostraNum(olhar.yaw, t * SUB), -PESCOCO, PESCOCO);
}

// ---------------------------------------------------------------- atualização por quadro
const tvAlvo = new THREE.Vector3(), tvPos = new THREE.Vector3(), tmp = new THREE.Vector3();
let olhar = null, ultimoT = -1;

function atualizarCena(t, dtReal) {
  const l = estado.lance;
  const b = amostra(l.bola, t);
  bola.position.copy(v3(b[0], b[1], b[2] + 0.11));
  bola.rotation.x = -t * 0.9; bola.rotation.z = t * 0.4;

  for (const j of l.jogadores) {
    const bo = j.boneco, p = amostra(j.pos, t);
    if (!p) { bo.g.visible = false; continue; }
    const v = amostra(j.vel, t), veloc = Math.hypot(v[0], v[1]);
    const fase = amostraNum(j.acum, t) / PASSADA * Math.PI * 2;
    bo.g.visible = !(estado.vista === 'pov' && j === estado.sel);
    bo.g.position.copy(v3(p[0], p[1], 0));
    bo.g.rotation.y = amostraAngulo(j.corpo, t);
    const amp = Math.min(veloc / 7, 1) * 0.75;
    bo.pernas[0].rotation.x = Math.sin(fase) * amp;
    bo.pernas[1].rotation.x = -Math.sin(fase) * amp;
    bo.bracos[0].rotation.x = -Math.sin(fase) * amp * 0.8;
    bo.bracos[1].rotation.x = Math.sin(fase) * amp * 0.8;
    bo.tronco.rotation.x = Math.min(veloc, 8) * 0.018;
    bo.g.position.y = Math.abs(Math.sin(fase)) * 0.04 * amp;
    bo.rotulo.visible = estado.rotulos && bo.g.visible;
  }

  const s = estado.sel, ps = amostra(s.pos, t);
  anelSel.visible = estado.vista !== 'pov';
  anelSel.position.copy(v3(ps[0], ps[1], 0.02));

  const salto = Math.abs(t - ultimoT) > 3 || ultimoT < 0;
  ultimoT = t;
  const k = salto ? 1 : 1 - Math.exp(-dtReal * 3);
  const yaw = yawOlhar(s, t), pitch = amostraAngulo(olhar.pitch, t * SUB);
  const vs = amostra(s.vel, t), vels = Math.hypot(vs[0], vs[1]);
  camera.up.set(0, 1, 0);
  controles.enabled = estado.vista === 'drone';

  if (estado.vista === 'pov') {
    const fase = amostraNum(s.acum, t) / PASSADA * Math.PI * 2;
    const bob = Math.sin(fase * 2) * 0.03 * Math.min(vels / 6, 1);
    camera.position.copy(v3(ps[0], ps[1], OLHO + bob));
    camera.lookAt(tmp.copy(camera.position).add(dirDe(yaw, pitch)));
    setFov(estado.fov);
  } else if (estado.vista === 'terceira') {
    const dir = dirDe(yaw, 0);
    const alvoPos = v3(ps[0], ps[1], 2.6).addScaledVector(dir, -5.5);
    tvPos.lerp(alvoPos, salto ? 1 : 1 - Math.exp(-dtReal * 5));
    camera.position.copy(tvPos);
    tvAlvo.lerp(v3(ps[0], ps[1], 1.3).addScaledVector(dirDe(yaw, pitch), 8), salto ? 1 : 1 - Math.exp(-dtReal * 5));
    camera.lookAt(tvAlvo);
    setFov(65);
  } else if (estado.vista === 'tv') {
    tvAlvo.lerp(v3(b[0], b[1], 1), k);
    // câmera principal: perto do meio-campo, dentro da arquibancada, sob a cobertura
    camera.position.set(limita(tvAlvo.x * 0.3, -18, 18), 21, HY + 30);
    camera.lookAt(tvAlvo);
    setFov(limita(16 + Math.abs(tvAlvo.x) * 0.12, 16, 24));
  } else if (estado.vista === 'tatica') {
    camera.up.set(0, 0, -1);
    tvAlvo.lerp(v3(limita(b[0] * 0.6, -22, 22), limita(b[1] * 0.4, -8, 8), 0), k);
    camera.position.set(tvAlvo.x, 82, tvAlvo.z + 0.001);
    camera.lookAt(tvAlvo.x, 0, tvAlvo.z);
    setFov(45);
  } else {
    controles.target.lerp(v3(b[0], b[1], 0.5), salto ? 1 : 1 - Math.exp(-dtReal * 1.5));
    controles.update();
    setFov(55);
  }
}

function setFov(f) {
  if (camera.fov !== f) { camera.fov = f; camera.updateProjectionMatrix(); }
}

// ---------------------------------------------------------------- minimapa
const mm = $('#minimapa'), mg = mm.getContext('2d');
const MM_M = 3; // margem em metros
function mmEscala() { return mm.width / (HX * 2 + MM_M * 2); }
function mmXY(x, y) { const e = mmEscala(); return [(x + HX + MM_M) * e, (HY + MM_M - y) * e]; }

function desenharMinimapa(t) {
  const l = estado.lance, e = mmEscala();
  mg.fillStyle = '#3d8537'; mg.fillRect(0, 0, mm.width, mm.height);
  mg.strokeStyle = 'rgba(255,255,255,0.85)'; mg.lineWidth = 1;
  const [x0, y0] = mmXY(-HX, HY), [x1, y1] = mmXY(HX, -HY);
  mg.strokeRect(x0, y0, x1 - x0, y1 - y0);
  mg.beginPath(); mg.moveTo((x0 + x1) / 2, y0); mg.lineTo((x0 + x1) / 2, y1); mg.stroke();
  mg.beginPath(); mg.arc((x0 + x1) / 2, (y0 + y1) / 2, 9.15 * e, 0, Math.PI * 2); mg.stroke();
  for (const s of [-1, 1]) {
    const [a, c] = mmXY(s * HX, 20.16), [b2, d] = mmXY(s * (HX - 16.5), -20.16);
    mg.strokeRect(Math.min(a, b2), c, Math.abs(b2 - a), d - c);
  }

  const s = estado.sel, ps = amostra(s.pos, t);
  if (ps) {
    const yaw = yawOlhar(s, t);
    const hfov = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(estado.fov) / 2) * camera.aspect);
    const [cx, cy] = mmXY(ps[0], ps[1]);
    mg.fillStyle = 'rgba(255,90,31,0.28)';
    mg.beginPath(); mg.moveTo(cx, cy);
    // yaw → direção no campo: (sin yaw, -cos yaw); na tela, y é invertido
    for (let k = -1; k <= 1; k += 0.1) {
      const a = yaw + k * hfov / 2;
      mg.lineTo(cx + Math.sin(a) * 30 * e, cy + Math.cos(a) * 30 * e);
    }
    mg.closePath(); mg.fill();
  }

  for (const j of l.jogadores) {
    const p = amostra(j.pos, t); if (!p) continue;
    const [x, y] = mmXY(p[0], p[1]);
    mg.beginPath(); mg.arc(x, y, j === s ? 4.5 : 3.3, 0, Math.PI * 2);
    mg.fillStyle = corCss(j.cor, '#888'); mg.fill();
    mg.lineWidth = j === s ? 2.5 : 1; mg.strokeStyle = j === s ? '#ff5a1f' : corCss(j.borda, '#fff'); mg.stroke();
  }
  const b = amostra(l.bola, t), [bx, by] = mmXY(b[0], b[1]);
  mg.beginPath(); mg.arc(bx, by, 2.4 + b[2] * 0.6, 0, Math.PI * 2);
  mg.fillStyle = '#fff'; mg.fill(); mg.lineWidth = 1; mg.strokeStyle = '#111'; mg.stroke();
}

mm.addEventListener('click', (ev) => {
  const r = mm.getBoundingClientRect(), e = mmEscala() * (r.width / mm.width);
  const x = (ev.clientX - r.left) / e - HX - MM_M, y = HY + MM_M - (ev.clientY - r.top) / e;
  let melhor = null, md = 5;
  for (const j of estado.lance.jogadores) {
    const p = amostra(j.pos, estado.t); if (!p) continue;
    const d = Math.hypot(p[0] - x, p[1] - y); if (d < md) { md = d; melhor = j; }
  }
  if (melhor) selecionar(melhor);
});

// clique na cena seleciona o jogador
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
let baixo = null;
canvas.addEventListener('pointerdown', (e) => { baixo = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', (e) => {
  if (!baixo || Math.hypot(e.clientX - baixo[0], e.clientY - baixo[1]) > 5) return;
  const r = canvas.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const alvos = estado.lance.jogadores.filter((j) => j.boneco.g.visible).map((j) => j.boneco.g);
  const hit = ray.intersectObjects(alvos, true).find((h) => h.object.userData.jogador);
  if (hit) selecionar(hit.object.userData.jogador);
});

// ---------------------------------------------------------------- interface
function preencherLances() {
  const sel = $('#sel-lance');
  sel.innerHTML = estado.lances.map((l, i) => `<option value="${i}">${l.titulo}</option>`).join('');
  sel.onchange = () => { if (!estado.gravando) carregarLance(estado.lances[+sel.value]); };
}

function carregarLance(l) {
  if (estado.lance) for (const j of estado.lance.jogadores) cena.remove(j.boneco.g);
  if (!l.preparado) { prepararLance(l); l.preparado = true; }
  else for (const j of l.jogadores) cena.add(j.boneco.g);
  estado.lance = l; estado.t = 0; ultimoT = -1;
  const dur = (l.frames - 1) / l.fps;
  $('#meta').textContent = `${l.contexto ? l.contexto + ' ' : ''}${dur.toFixed(1).replace('.', ',')} s · ${l.jogadores.length} de 22 jogadores no dado.`;
  $('#rng-tempo').max = l.frames - 1;
  $('#marca-gol').style.left = `calc(${(l.frameGol / (l.frames - 1)) * 100}% - 1px)`;
  selecionar(l.finalizador, true);
  estado.tocando = true; atualizarPlay();
  if (estado.vista === 'drone') posicionarDrone();
}

function listarJogadores() {
  const l = estado.lance, caixa = $('#lista-jogadores');
  const grupos = ['attack', 'defense'].map((time) => {
    const js = l.jogadores.filter((j) => j.time === time)
      .sort((a, b) => (b.nome ? 1 : 0) - (a.nome ? 1 : 0) || (a.numero ?? 99) - (b.numero ?? 99));
    if (!js.length) return '';
    return `<div class="grupo">${js[0].nomeTime}</div>` + js.map((j) => {
      const i = l.jogadores.indexOf(j);
      const nome = j.nome || (j.numero != null ? `Camisa ${j.numero}` : `Jogador ${j.rotuloGenerico}`);
      return `<button data-i="${i}" class="${j === estado.sel ? 'ativo' : ''}">
        <span class="camisa" style="background:${corCss(j.cor, '#888')};border-color:${corCss(j.borda, '#fff')};color:${corCss(j.borda, '#fff')}">${j.numero ?? ''}</span>
        ${nome}${j === l.finalizador ? '<span class="gol">gol</span>' : ''}</button>`;
    }).join('');
  });
  caixa.innerHTML = grupos.join('');
  caixa.querySelectorAll('button').forEach((b) => (b.onclick = () => selecionar(l.jogadores[+b.dataset.i])));
}

function selecionar(j, silencioso) {
  const anterior = estado.sel;
  const trocarRotulo = (x, destaque) => {
    const m = x.boneco.rotulo.material;
    m.map.dispose(); m.map = texRotulo(nomeCurto(x), destaque); m.needsUpdate = true;
  };
  if (anterior && anterior.boneco && anterior !== j) trocarRotulo(anterior, false);
  estado.sel = j;
  trocarRotulo(j, true);
  olhar = calcularOlhar(estado.lance, j, estado.olhar);
  ultimoT = -1;
  listarJogadores();
  const ativo = $('#lista-jogadores button.ativo');
  if (ativo && !silencioso) ativo.scrollIntoView({ block: 'nearest' });
}

function segmentado(id, aoMudar) {
  const caixa = $(id);
  caixa.querySelectorAll('button').forEach((b) => (b.onclick = () => {
    caixa.querySelectorAll('button').forEach((x) => x.classList.toggle('ativo', x === b));
    aoMudar(b.dataset.v);
  }));
}

function mudarVista(v) {
  estado.vista = v; ultimoT = -1;
  document.querySelectorAll('#vistas button').forEach((x) => x.classList.toggle('ativo', x.dataset.v === v));
  if (v === 'drone') posicionarDrone();
}

function posicionarDrone() {
  const b = amostra(estado.lance.bola, estado.t);
  camera.position.copy(v3(b[0] - 18, b[1] - 26, 22));
  controles.target.copy(v3(b[0], b[1], 0.5));
}

function atualizarPlay() { $('#btn-play').textContent = estado.tocando ? '❚❚' : '▶'; }

segmentado('#vistas', mudarVista);
segmentado('#seg-olhar', (v) => { estado.olhar = v; olhar = calcularOlhar(estado.lance, estado.sel, v); });
$('#rng-fov').oninput = (e) => { estado.fov = +e.target.value; $('#out-fov').textContent = `${estado.fov}°`; };
$('#chk-rotulos').onchange = (e) => (estado.rotulos = e.target.checked);
$('#chk-sombras').onchange = (e) => { sol.castShadow = e.target.checked; };
$('#btn-finalizador').onclick = () => selecionar(estado.lance.finalizador);
$('#btn-play').onclick = () => {
  if (estado.gravando) return;
  if (!estado.tocando && estado.t >= estado.lance.frames - 1) estado.t = 0;
  estado.tocando = !estado.tocando; atualizarPlay();
};
$('#rng-tempo').oninput = (e) => {
  if (estado.gravando) { e.target.value = estado.t; return; }
  estado.t = +e.target.value; estado.tocando = false; atualizarPlay();
};
$('#sel-vel').onchange = (e) => (estado.vel = +e.target.value);
$('#btn-gravar').onclick = gravar;

addEventListener('keydown', (e) => {
  if (e.target.tagName === 'SELECT' || estado.gravando) return;
  if (e.code === 'Space') { e.preventDefault(); $('#btn-play').click(); }
  else if (e.key === 'ArrowRight') { estado.t = Math.min(estado.lance.frames - 1, Math.floor(estado.t) + 1); estado.tocando = false; atualizarPlay(); }
  else if (e.key === 'ArrowLeft') { estado.t = Math.max(0, Math.ceil(estado.t) - 1); estado.tocando = false; atualizarPlay(); }
  else if ('12345'.includes(e.key)) mudarVista(['pov', 'terceira', 'tv', 'drone', 'tatica'][+e.key - 1]);
});

// ---------------------------------------------------------------- gravação
function travarDuranteGravacao(travar) {
  for (const id of ['#sel-lance', '#btn-play', '#rng-tempo', '#sel-vel']) $(id).disabled = travar;
}

function gravar() {
  if (estado.gravando) { encerrarGravacao(); return; }   // segundo clique encerra antes do fim
  if (!window.MediaRecorder) return;
  const s = estado.sel;
  const nomeArquivo = `lance-pov_${estado.lance.id}_${(s.nome || s.rotuloGenerico).toLowerCase().replace(/\W+/g, '-')}_${estado.vista}.webm`;
  const tipo = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find((m) => MediaRecorder.isTypeSupported(m));
  const rec = new MediaRecorder(canvas.captureStream(30), { mimeType: tipo, videoBitsPerSecond: 10e6 });
  const partes = [];
  rec.ondataavailable = (e) => e.data.size && partes.push(e.data);
  rec.onstop = () => {
    const url = URL.createObjectURL(new Blob(partes, { type: 'video/webm' }));
    const a = Object.assign(document.createElement('a'), { href: url, download: nomeArquivo });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    estado.gravando = false; estado.gravador = null;
    travarDuranteGravacao(false);
    $('#btn-gravar').classList.remove('gravando'); $('#btn-gravar').textContent = '● Gravar vídeo';
  };
  estado.gravando = true; estado.t = 0; estado.tocando = true; ultimoT = -1; atualizarPlay();
  estado.gravador = rec;
  travarDuranteGravacao(true);
  $('#btn-gravar').classList.add('gravando'); $('#btn-gravar').textContent = '■ Parar gravação';
  rec.start(250);
}

function encerrarGravacao(atraso = 0) {
  const rec = estado.gravador;
  if (!rec || rec.state !== 'recording' || estado.encerrando) return;
  estado.encerrando = true; estado.tocando = false; atualizarPlay();
  setTimeout(() => { estado.encerrando = false; rec.stop(); }, atraso);
}

// ---------------------------------------------------------------- laço principal
function redimensionar() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
}
new ResizeObserver(redimensionar).observe(canvas.parentElement);

let antes = performance.now();
function quadro(agora) {
  requestAnimationFrame(quadro);
  const dt = Math.min(0.1, (agora - antes) / 1000); antes = agora;
  const l = estado.lance; if (!l) return;
  const fim = l.frames - 1;
  if (estado.tocando) {
    if (estado.t < fim) estado.fimEspera = 0;
    estado.t += dt * estado.vel * l.fps;
    if (estado.t >= fim) {
      estado.t = fim;
      if (estado.gravando) encerrarGravacao(400);
      else if ((estado.fimEspera += dt) > 1.2) { estado.t = 0; estado.fimEspera = 0; }
    }
  }
  atualizarCena(estado.t, dt);
  desenharMinimapa(estado.t);
  $('#rng-tempo').value = estado.t;
  $('#tempo').textContent = `${(estado.t / l.fps).toFixed(1).replace('.', ',')} / ${(fim / l.fps).toFixed(1).replace('.', ',')} s`;
  const s = estado.sel, p = amostra(s.pos, estado.t), v = amostra(s.vel, estado.t), b = amostra(l.bola, estado.t);
  $('#hud-nome').textContent = s.nome || (s.numero != null ? `Camisa ${s.numero}` : `Jogador ${s.rotuloGenerico}`);
  $('#hud-dados').textContent = `${s.nomeTime} · ${(Math.hypot(v[0], v[1]) * 3.6).toFixed(0)} km/h · bola a ${Math.hypot(b[0] - p[0], b[1] - p[1]).toFixed(1).replace('.', ',')} m`;
  renderer.render(cena, camera);
}

// ---------------------------------------------------------------- início
fetch('data/lances.json')
  .then((r) => r.json())
  .then((d) => {
    estado.lances = d.lances;
    preencherLances();
    const inicial = Math.max(0, estado.lances.findIndex((l) => l.id === 'liverpool-4-0-barcelona'));
    $('#sel-lance').value = inicial;
    redimensionar();
    carregarLance(estado.lances[inicial]);
    $('#carregando').hidden = true;
    requestAnimationFrame(quadro);
  })
  .catch((e) => { $('#carregando').textContent = `Não consegui carregar os lances: ${e.message}`; });

// gancho de inspeção para testes automatizados (somente leitura)
window.lancePov = { estado, yawOlhar: (t) => yawOlhar(estado.sel, t), corpo: (t) => amostraAngulo(estado.sel.corpo, t), carregarLance, selecionar };
