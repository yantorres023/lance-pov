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
const FPS_ROTEIRO = 20;
const v3 = (x, y, z = 0) => new THREE.Vector3(x, z, -y);
const yawDe = (dx, dy) => Math.atan2(dx, -dy);   // direção (dx, dy) do campo → ângulo em torno do eixo Y da cena (inverso de dirDe)
const dirDe = (yaw, pitch = 0) => new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
const embrulha = (a) => Math.atan2(Math.sin(a), Math.cos(a));
const limita = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = (v, c = 1) => v.toFixed(c).replace('.', ',');

const estado = {
  lances: [], lance: null, t: 0, tocando: false, vel: 1,
  sel: null, vista: 'pov', olhar: 'misto', fov: 75, estilo: 'realista',
  rotulos: true, sombras: true, gravando: false, fimEspera: 0,
  editor: false, selEditor: null, edZoom: 1, edCentro: [0, 0],
};

// ---------------------------------------------------------------- renderer e cena
const canvas = $('#cena');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const ANISO = renderer.capabilities.getMaxAnisotropy();

const cena = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, 1, 0.05, 700);
const controles = new OrbitControls(camera, canvas);
controles.enabled = false;
controles.enableDamping = true;
controles.maxPolarAngle = Math.PI * 0.49;

const hemi = new THREE.HemisphereLight(0xe3ecff, 0x40603a, 1.25);
cena.add(hemi);
const sol = new THREE.DirectionalLight(0xfff6e8, 2.4);
sol.position.set(-45, 85, 35);
sol.shadow.mapSize.set(4096, 4096);
Object.assign(sol.shadow.camera, { left: -75, right: 75, top: 60, bottom: -60, near: 10, far: 250 });
sol.shadow.bias = -0.0004;
sol.shadow.normalBias = 0.03;
cena.add(sol);

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

function texPixel(w, h, desenha) {
  const t = canvasTex(w, h, desenha);
  t.magFilter = THREE.NearestFilter;
  t.minFilter = THREE.NearestMipmapLinearFilter;
  return t;
}

function repetir(t, rx, ry) {
  const c = t.clone(); c.needsUpdate = true;
  c.wrapS = c.wrapT = THREE.RepeatWrapping; c.repeat.set(rx, ry);
  return c;
}

function texGradiente(stops) {
  return canvasTex(4, 256, (g, w, h) => {
    const gr = g.createLinearGradient(0, 0, 0, h);
    stops.forEach(([p, c]) => gr.addColorStop(p, c));
    g.fillStyle = gr; g.fillRect(0, 0, w, h);
  });
}

function ruido(g, w, h, amp) {
  const img = g.getImageData(0, 0, w, h), d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * amp;
    d[i] += n; d[i + 1] += n; d[i + 2] += n;
  }
  g.putImageData(img, 0, 0);
}

function texGramado() {
  return canvasTex(2048, 1024, (g, w, h) => {
    const faixas = 18;
    for (let i = 0; i < faixas; i++) {
      g.fillStyle = i % 2 ? '#3d8537' : '#47953f';
      g.fillRect(Math.floor(i * w / faixas), 0, Math.ceil(w / faixas) + 1, h);
    }
    ruido(g, w, h, 16);
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
  return canvasTex(512, 256, (g, w, h) => {
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
}

function texPlaca(fundo = '#ff5a1f', pixel = false) {
  const desenha = (g, w, h) => {
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, w, h);
    g.fillStyle = fundo; g.fillRect(0, 0, w / 2, h);
    g.font = `bold ${Math.round(h * 0.53)}px ${pixel ? 'monospace' : 'system-ui, sans-serif'}`;
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillStyle = '#ffffff'; g.fillText('LANCE POV', w / 4, h / 2 + 1);
    g.fillStyle = '#1d1f23'; g.fillText('LANCE POV', 3 * w / 4, h / 2 + 1);
  };
  return pixel ? texPixel(128, 16, desenha) : canvasTex(512, 64, desenha);
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

function texRotulo(texto, destaque, tema) {
  return canvasTex(512, 64, (g, w, h) => {
    g.font = '600 30px system-ui, sans-serif';
    const lw = Math.min(w - 4, g.measureText(texto).width + 28);
    g.fillStyle = destaque ? tema.destaqueRotulo : tema.fundoRotulo;
    const x = (w - lw) / 2;
    g.beginPath(); g.roundRect(x, 10, lw, 44, 22); g.fill();
    g.fillStyle = destaque ? '#fff' : tema.textoRotulo; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(texto, w / 2, 33);
  });
}

// ---------------------------------------------------------------- peças do campo (comuns aos estilos)
function desenharCampo(g, mat, { L = 0.12, y = 0.012, segs = 96 } = {}) {
  const seg = (x1, y1, x2, y2) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(Math.hypot(x2 - x1, y2 - y1) + L, L), mat);
    m.rotation.x = -Math.PI / 2; m.rotation.z = Math.atan2(y2 - y1, x2 - x1);
    m.position.copy(v3((x1 + x2) / 2, (y1 + y2) / 2, y)); m.receiveShadow = true;
    g.add(m);
  };
  const arco = (cx, cy, r, a0, a1) => {
    const m = new THREE.Mesh(new THREE.RingGeometry(r - L / 2, r + L / 2, segs, 1, a0, a1 - a0), mat);
    m.rotation.x = -Math.PI / 2; m.position.copy(v3(cx, cy, y)); m.receiveShadow = true;
    g.add(m);
  };
  const ponto = (x, yy) => {
    const m = new THREE.Mesh(new THREE.CircleGeometry(Math.max(0.15, L * 1.2), 20), mat);
    m.rotation.x = -Math.PI / 2; m.position.copy(v3(x, yy, y + 0.001)); g.add(m);
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
  }
}

function montarGols(g, { matTrave, matRede, quadrada = false, r = 0.06 }) {
  const H = 2.44, W = 7.32 / 2, D = 2.0;
  const trave = (comp) => new THREE.Mesh(quadrada ? new THREE.BoxGeometry(2 * r, comp, 2 * r) : new THREE.CylinderGeometry(r, r, comp, 14), matTrave);
  for (const s of [-1, 1]) {
    const gx = s * HX;
    for (const sy of [-1, 1]) {
      const p = trave(H); p.position.copy(v3(gx, sy * (W + r), H / 2)); p.castShadow = true; g.add(p);
      const b = new THREE.Mesh(quadrada ? new THREE.BoxGeometry(0.05, H, 0.05) : new THREE.CylinderGeometry(0.025, 0.025, H, 8), matTrave);
      b.position.copy(v3(gx + s * D, sy * W, H / 2)); g.add(b);
    }
    const t = trave(2 * W + 4 * r); t.rotation.x = Math.PI / 2; t.position.copy(v3(gx, 0, H)); t.castShadow = true; g.add(t);
    if (!matRede) continue;
    const fundo = new THREE.Mesh(new THREE.PlaneGeometry(2 * W, H), matRede(2 * W, H));
    fundo.rotation.y = Math.PI / 2; fundo.position.copy(v3(gx + s * D, 0, H / 2)); g.add(fundo);
    for (const sy of [-1, 1]) {
      const lado = new THREE.Mesh(new THREE.PlaneGeometry(D, H), matRede(D, H));
      lado.position.copy(v3(gx + s * D / 2, sy * W, H / 2)); g.add(lado);
    }
    const teto = new THREE.Mesh(new THREE.PlaneGeometry(D, 2 * W), matRede(D, 2 * W));
    teto.rotation.x = -Math.PI / 2; teto.position.copy(v3(gx + s * D / 2, 0, H)); g.add(teto);
  }
}

function redeTexturizada(base) {
  return (w, h) => new THREE.MeshBasicMaterial({ map: repetir(base, w / 0.14, h / 0.14), transparent: true, alphaTest: 0.3, side: THREE.DoubleSide, depthWrite: false });
}

function montarPlacas(g, tex, criarMat = (map) => new THREE.MeshStandardMaterial({ map, roughness: 0.6 })) {
  const placa = (x, y, comp, girar) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(comp, 0.9, 0.08), criarMat(repetir(tex, comp / 9, 1)));
    m.position.copy(v3(x, y, 0.45)); if (girar) m.rotation.y = Math.PI / 2; m.castShadow = true;
    g.add(m);
  };
  placa(0, -HY - 5, 118); placa(0, HY + 5, 118);
  placa(-HX - 5, 0, 76, true); placa(HX + 5, 0, 76, true);
}

// arquibancada em degraus (estilos de blocos): giro 0 = lado de y positivo do campo
function bancadaDegraus(g, comp, x, y, giro, matDegrau, { degraus = 9, alto = 2, fundo = 2.6 } = {}) {
  const grupo = new THREE.Group();
  for (let i = 0; i < degraus; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(comp, alto * (i + 1), fundo), matDegrau(i, comp));
    m.position.set(0, alto * (i + 1) / 2, -fundo * i - fundo / 2);
    m.receiveShadow = true;
    grupo.add(m);
  }
  grupo.position.copy(v3(x, y, 0)); grupo.rotation.y = giro;
  g.add(grupo);
}

function quatroBancadas(g, fn) {
  fn(128, 0, HY + 9, 0);
  fn(128, 0, -HY - 9, Math.PI);
  fn(86, HX + 9, 0, -Math.PI / 2);
  fn(86, -HX - 9, 0, Math.PI / 2);
}

// ---------------------------------------------------------------- estilos: ambiente
function ambienteRealista() {
  const g = new THREE.Group();
  const solo = new THREE.Mesh(new THREE.PlaneGeometry(170, 130), new THREE.MeshStandardMaterial({ color: 0x3b7d35, roughness: 1 }));
  solo.rotation.x = -Math.PI / 2; solo.position.y = -0.02; solo.receiveShadow = true; g.add(solo);
  const gramado = new THREE.Mesh(new THREE.PlaneGeometry(HX * 2, HY * 2), new THREE.MeshStandardMaterial({ map: texGramado(), roughness: 1 }));
  gramado.rotation.x = -Math.PI / 2; gramado.receiveShadow = true; g.add(gramado);
  desenharCampo(g, new THREE.MeshStandardMaterial({ color: 0xf2f2ee, roughness: 0.9 }));
  montarGols(g, { matTrave: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35 }), matRede: redeTexturizada(texRede()) });
  montarPlacas(g, texPlaca());
  const torcida = texTorcida();
  quatroBancadas(g, (comp, x, y, giro) => {
    const prof = 32, alt = 20, sl = Math.hypot(prof, alt), incl = Math.atan2(alt, prof);
    const b = new THREE.Group();
    const degrau = new THREE.Mesh(new THREE.PlaneGeometry(comp, sl), new THREE.MeshStandardMaterial({ map: repetir(torcida, comp / 22, sl / 11), roughness: 1 }));
    degrau.rotation.x = -Math.PI / 2 + incl; degrau.position.set(0, alt / 2 + 1.2, -prof / 2); b.add(degrau);
    const matConc = new THREE.MeshStandardMaterial({ color: 0x9aa0a8, roughness: 1 });
    const muro = new THREE.Mesh(new THREE.BoxGeometry(comp, 1.2, 0.4), matConc); muro.position.set(0, 0.6, 0); b.add(muro);
    const fundo = new THREE.Mesh(new THREE.BoxGeometry(comp, alt + 9, 1), matConc); fundo.position.set(0, (alt + 9) / 2, -prof - 0.5); b.add(fundo);
    const teto = new THREE.Mesh(new THREE.BoxGeometry(comp, 0.6, prof * 0.75), new THREE.MeshStandardMaterial({ color: 0xb4bac2, emissive: 0x30343a, roughness: 0.8 }));
    teto.position.set(0, alt + 8.5, -prof + prof * 0.375); b.add(teto);
    b.position.copy(v3(x, y, 0)); b.rotation.y = giro;
    g.add(b);
  });
  return g;
}

function ambientePalitos(tema) {
  const g = new THREE.Group();
  const basica = (cor) => new THREE.MeshBasicMaterial({ color: cor, toneMapped: false });
  // grade discreta a cada 5 m para dar noção de profundidade sobre o fundo liso
  const grade = basica(tema.grade);
  for (let x = -HX + 5.25; x < HX; x += 5.25) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(0.05, HY * 2), grade);
    m.rotation.x = -Math.PI / 2; m.position.set(x, 0.004, 0); g.add(m);
  }
  for (let y = -HY + 5.67; y < HY; y += 5.67) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(HX * 2, 0.05), grade);
    m.rotation.x = -Math.PI / 2; m.position.set(0, 0.004, -y); g.add(m);
  }
  desenharCampo(g, basica(tema.linha), { L: 0.09 });
  const linhaRede = new THREE.LineBasicMaterial({ color: tema.linha, transparent: true, opacity: 0.35 });
  montarGols(g, { matTrave: basica(tema.linha), r: 0.045 });
  for (const s of [-1, 1]) {   // rede em poucas linhas, como um desenho
    const pts = [];
    for (let k = -3; k <= 3; k++) { pts.push(v3(s * HX, k * 1.22, 2.44), v3(s * (HX + 2), k * 1.22, 2.44), v3(s * (HX + 2), k * 1.22, 2.44), v3(s * (HX + 2), k * 1.22, 0)); }
    for (let k = 1; k <= 3; k++) { pts.push(v3(s * (HX + 2), -3.66, k * 0.61 * 1.33), v3(s * (HX + 2), 3.66, k * 0.61 * 1.33)); }
    g.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), linhaRede));
  }
  return g;
}

function ambienteBlocos() {
  const g = new THREE.Group();
  const lamb = (o) => new THREE.MeshLambertMaterial(o);
  // gramado: 8 px por metro, cada metro é um "bloco" de grama com faixas de corte
  const grama = texPixel((HX * 2) * 8, (HY * 2) * 8, (c, w, h) => {
    const img = c.createImageData(w, h), d = img.data;
    for (let py = 0; py < h; py++) for (let px = 0; px < w; px++) {
      const faixa = Math.floor(px / 8 / 5.83) % 2, v = Math.random();
      const base = faixa ? [86, 160, 58] : [98, 174, 66];
      const k = v < 0.15 ? -22 : v < 0.3 ? 14 : 0, i = (py * w + px) * 4;
      d[i] = base[0] + k; d[i + 1] = base[1] + k; d[i + 2] = base[2] + k * 0.5; d[i + 3] = 255;
    }
    c.putImageData(img, 0, 0);
  });
  const solo = new THREE.Mesh(new THREE.PlaneGeometry(170, 130), lamb({ map: repetir(texPixel(16, 16, (c) => {
    for (let x = 0; x < 16; x++) for (let y = 0; y < 16; y++) { const k = Math.random() * 30 - 15; c.fillStyle = `rgb(${80 + k},${140 + k},${52 + k})`; c.fillRect(x, y, 1, 1); }
  }), 170, 130) }));
  solo.rotation.x = -Math.PI / 2; solo.position.y = -0.02; g.add(solo);
  const campo = new THREE.Mesh(new THREE.PlaneGeometry(HX * 2, HY * 2), lamb({ map: grama }));
  campo.rotation.x = -Math.PI / 2; g.add(campo);
  desenharCampo(g, lamb({ color: 0xf4f4f4 }), { L: 0.25, y: 0.02, segs: 28 });
  const redePixel = texPixel(8, 8, (c) => { c.clearRect(0, 0, 8, 8); c.fillStyle = '#f0f0f0'; c.fillRect(0, 0, 8, 1); c.fillRect(0, 0, 1, 8); });
  redePixel.wrapS = redePixel.wrapT = THREE.RepeatWrapping;
  montarGols(g, { matTrave: lamb({ color: 0xf6f6f6 }), matRede: redeTexturizada(redePixel), quadrada: true, r: 0.08 });
  montarPlacas(g, texPlaca('#3c8527', true), (map) => lamb({ map }));
  // degraus de pedra com torcida em pixel
  const torcida = texPixel(32, 16, (c) => {
    c.fillStyle = '#7d7d7d'; c.fillRect(0, 0, 32, 16);
    const cores = ['#b02e26', '#3c44aa', '#f9fffe', '#fed83d', '#1d1d21', '#5e7c16', '#f9801d'];
    for (let x = 0; x < 32; x += 3) {
      if (Math.random() < 0.15) continue;
      c.fillStyle = '#c69c7b'; c.fillRect(x + 1, 3, 2, 2);
      c.fillStyle = cores[(Math.random() * cores.length) | 0]; c.fillRect(x + 1, 5, 2, 4);
    }
    c.fillStyle = '#6b6b6b'; c.fillRect(0, 12, 32, 4);
  });
  const pedra = texPixel(16, 16, (c) => { for (let x = 0; x < 16; x++) for (let y = 0; y < 16; y++) { const k = Math.random() * 40 - 20; c.fillStyle = `rgb(${125 + k},${125 + k},${125 + k})`; c.fillRect(x, y, 1, 1); } });
  quatroBancadas(g, (comp, x, y, giro) => bancadaDegraus(g, comp, x, y, giro, (i, cmp) => [
    lamb({ map: pedra }), lamb({ map: pedra }), lamb({ map: repetir(pedra, cmp / 2, 1.3) }), lamb({ map: pedra }),
    lamb({ map: repetir(torcida, cmp / 4, i + 1) }), lamb({ map: pedra }),   // uma fileira de torcida por degrau
  ]));
  // nuvens quadradas
  const nuvens = new THREE.Group(); nuvens.name = 'nuvens';
  const matNuvem = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 });
  for (let i = 0; i < 26; i++) {
    const w = 12 + Math.random() * 26, d = 8 + Math.random() * 16;
    const n = new THREE.Mesh(new THREE.BoxGeometry(w, 3, d), matNuvem);
    n.position.set(Math.random() * 400 - 200, 75 + Math.random() * 6, Math.random() * 400 - 200);
    nuvens.add(n);
  }
  g.add(nuvens);
  return g;
}

function ambienteBloquinho() {
  const g = new THREE.Group();
  const plast = (cor, o = {}) => new THREE.MeshStandardMaterial({ color: cor, roughness: 0.38, metalness: 0, ...o });
  const base = new THREE.Mesh(new THREE.PlaneGeometry(170, 130), plast(0x4b974b));
  base.rotation.x = -Math.PI / 2; base.position.y = -0.02; base.receiveShadow = true; g.add(base);
  const gramado = new THREE.Mesh(new THREE.PlaneGeometry(HX * 2, HY * 2), new THREE.MeshStandardMaterial({ map: canvasTex(1024, 512, (c, w, h) => {
    for (let i = 0; i < 18; i++) { c.fillStyle = i % 2 ? '#4b974b' : '#58a858'; c.fillRect(Math.floor(i * w / 18), 0, Math.ceil(w / 18) + 1, h); }
  }), roughness: 0.4 }));
  gramado.rotation.x = -Math.PI / 2; gramado.receiveShadow = true; g.add(gramado);
  // pinos ("studs") da base: brilho e sombra em textura repetida, por cima do gramado
  const pinos = canvasTex(64, 64, (c) => {
    c.clearRect(0, 0, 64, 64);
    c.fillStyle = 'rgba(0,0,0,0.16)'; c.beginPath(); c.arc(35, 35, 20, 0, Math.PI * 2); c.fill();
    c.fillStyle = 'rgba(255,255,255,0.22)'; c.beginPath(); c.arc(30, 30, 20, 0, Math.PI * 2); c.fill();
  });
  const sobre = new THREE.Mesh(new THREE.PlaneGeometry(HX * 2 + 20, HY * 2 + 20), new THREE.MeshBasicMaterial({ map: repetir(pinos, (HX * 2 + 20) / 0.8, (HY * 2 + 20) / 0.8), transparent: true, depthWrite: false }));
  sobre.rotation.x = -Math.PI / 2; sobre.position.y = 0.005; g.add(sobre);
  desenharCampo(g, plast(0xf8f8f8), { L: 0.18, y: 0.015 });
  montarGols(g, { matTrave: plast(0xf8f8f8), matRede: redeTexturizada(texRede()), r: 0.08 });
  montarPlacas(g, texPlaca('#0b84ff'), (map) => new THREE.MeshStandardMaterial({ map, roughness: 0.38 }));
  const cores = [0xc4281c, 0x0d69ac, 0xf5cd30, 0x4b974b, 0xa3a2a5, 0xda8541];
  quatroBancadas(g, (comp, x, y, giro) => bancadaDegraus(g, comp, x, y, giro, (i) => plast(cores[i % cores.length]), { degraus: 8, alto: 2.2, fundo: 3 }));
  return g;
}

const ESTILOS = {
  realista: {
    nome: 'Realista', montar: ambienteRealista, fundo: () => texGradiente([[0, '#7fa6d1'], [0.55, '#c4d5e8'], [1, '#eef2f5']]),
    fog: [0xd9e2ec, 160, 380], tone: THREE.ACESFilmicToneMapping, exp: 1.05, luz: [1.25, 2.4], sombras: true,
    tema: { fundoRotulo: 'rgba(20,22,26,0.62)', textoRotulo: '#fff', destaqueRotulo: 'rgba(255,90,31,0.95)', anel: 0xff5a1f },
  },
  'palitos-claro': {
    nome: 'Palitos (claro)', montar: () => ambientePalitos({ linha: 0x1d1f23, grade: 0xeeeeee }), fundo: () => new THREE.Color(0xffffff),
    fog: null, tone: THREE.NoToneMapping, exp: 1, luz: [1, 1], sombras: false,
    palito: { ataque: '#1f4fff', defesa: '#e5212f', destaque: '#f2a900', bola: 0x1d1f23 },
    tema: { fundoRotulo: 'rgba(29,31,35,0.08)', textoRotulo: '#1d1f23', destaqueRotulo: '#f2a900', anel: 0xf2a900 },
  },
  'palitos-escuro': {
    nome: 'Palitos (escuro)', montar: () => ambientePalitos({ linha: 0xf2f2f2, grade: 0x1c1c1e }), fundo: () => new THREE.Color(0x0b0b0c),
    fog: null, tone: THREE.NoToneMapping, exp: 1, luz: [1, 1], sombras: false,
    palito: { ataque: '#4da3ff', defesa: '#ff4d5e', destaque: '#ffc933', bola: 0xf2f2f2 },
    tema: { fundoRotulo: 'rgba(255,255,255,0.12)', textoRotulo: '#f2f2f2', destaqueRotulo: '#e0a800', anel: 0xffc933 },
  },
  blocos: {
    nome: 'Blocos', montar: ambienteBlocos, fundo: () => texGradiente([[0, '#6f9cff'], [0.6, '#9cbcff'], [1, '#c4d8ff']]),
    fog: [0xc4d8ff, 120, 330], tone: THREE.NoToneMapping, exp: 1, luz: [1.35, 1.25], sombras: false,
    tema: { fundoRotulo: 'rgba(0,0,0,0.55)', textoRotulo: '#fff', destaqueRotulo: 'rgba(255,170,0,0.95)', anel: 0xffaa00 },
  },
  bloquinho: {
    nome: 'Bloquinho', montar: ambienteBloquinho, fundo: () => texGradiente([[0, '#5aa9ff'], [0.6, '#a6d4ff'], [1, '#e2f1ff']]),
    fog: null, tone: THREE.NoToneMapping, exp: 1, luz: [1.1, 1.7], sombras: true,
    tema: { fundoRotulo: 'rgba(20,22,26,0.62)', textoRotulo: '#fff', destaqueRotulo: 'rgba(0,162,255,0.95)', anel: 0x00a2ff },
  },
};
const ambientes = {};

// ---------------------------------------------------------------- estilos: bola
function criarBola(estilo) {
  let m;
  if (estilo.startsWith('palitos')) {
    m = new THREE.Mesh(new THREE.SphereGeometry(0.12, 20, 14), new THREE.MeshBasicMaterial({ color: ESTILOS[estilo].palito.bola, toneMapped: false }));
  } else if (estilo === 'blocos') {
    m = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.24, 0.24), new THREE.MeshLambertMaterial({ map: texPixel(8, 8, (c) => {
      c.fillStyle = '#f4f4f4'; c.fillRect(0, 0, 8, 8); c.fillStyle = '#222'; c.fillRect(3, 3, 2, 2); c.fillRect(0, 0, 1, 1); c.fillRect(7, 0, 1, 1); c.fillRect(0, 7, 1, 1); c.fillRect(7, 7, 1, 1);
    }) }));
  } else {
    m = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 16), new THREE.MeshStandardMaterial({ map: texBola(), roughness: estilo === 'bloquinho' ? 0.3 : 0.45 }));
  }
  m.castShadow = true;
  return m;
}
const bolas = {};
let bola = null;

const anelSel = new THREE.Mesh(new THREE.RingGeometry(0.55, 0.72, 40), new THREE.MeshBasicMaterial({ color: 0xff5a1f, transparent: true, opacity: 0.9, toneMapped: false }));
anelSel.rotation.x = -Math.PI / 2;
cena.add(anelSel);

// ---------------------------------------------------------------- estilos: bonecos
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
  // palito
  linhaCorpo: new THREE.CylinderGeometry(0.035, 0.035, 0.5, 8).translate(0, 0.25, 0),
  linhaPerna: new THREE.CylinderGeometry(0.035, 0.035, 0.93, 8).translate(0, -0.465, 0),
  linhaBraco: new THREE.CylinderGeometry(0.03, 0.03, 0.58, 8).translate(0, -0.29, 0),
};

function corCss(c, padrao) { try { return '#' + new THREE.Color(c || padrao).getHexString(); } catch { return padrao; } }

function marcar(g, j) { g.traverse((o) => { if (o.isMesh || o.isSprite) { o.userData.jogador = j; if (o.isMesh) o.castShadow = true; } }); }

function bonecoRealista(j, idx) {
  const cor = corCss(j.cor, '#888888'), borda = corCss(j.borda, '#ffffff');
  const pele = new THREE.MeshStandardMaterial({ color: PELES[idx % PELES.length], roughness: 0.7 });
  const camisa = new THREE.MeshStandardMaterial({ map: texCamisa(cor, borda, j.numero), roughness: 0.85 });
  const calcao = new THREE.MeshStandardMaterial({ color: new THREE.Color(cor).multiplyScalar(0.75), roughness: 0.85 });
  const meiao = new THREE.MeshStandardMaterial({ color: borda, roughness: 0.85 });
  const chuteira = new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 0.5 });
  const cabelo = new THREE.MeshStandardMaterial({ color: 0x1c1410, roughness: 0.9 });
  const g = new THREE.Group();
  const add = (geo, mat, pai = g) => { const m = new THREE.Mesh(geo, mat); pai.add(m); return m; };
  const tronco = add(G.tronco, camisa); tronco.position.y = 1.24;
  add(G.calcao, calcao).position.y = 0.92;
  add(G.cabeca, pele).position.y = 1.67;
  add(G.cabelo, cabelo).position.y = 1.685;
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
  return { g, pernas, bracos, tronco, alturaRotulo: 2.25 };
}

function bonecoPalito(j, idx, estilo) {
  const p = ESTILOS[estilo].palito;
  const cor = j.time === 'attack' ? p.ataque : p.defesa;
  const mat = new THREE.MeshBasicMaterial({ color: cor, toneMapped: false });
  const g = new THREE.Group();
  const tronco = new THREE.Group(); tronco.position.y = 0.95; g.add(tronco);
  tronco.add(new THREE.Mesh(G.linhaCorpo, mat));
  const cabeca = new THREE.Sprite(new THREE.SpriteMaterial({ map: texCirculoVazado(), color: cor, toneMapped: false }));
  cabeca.scale.set(0.36, 0.36, 1); cabeca.position.y = 0.72; tronco.add(cabeca);
  const pernas = [-1, 1].map((s) => { const q = new THREE.Group(); q.position.set(s * 0.03, 0.95, 0); q.add(new THREE.Mesh(G.linhaPerna, mat)); g.add(q); q.rotation.z = s * 0.06; return q; });
  const bracos = [-1, 1].map((s) => { const q = new THREE.Group(); q.position.set(0, 0.43, 0); q.rotation.z = s * 0.45; q.add(new THREE.Mesh(G.linhaBraco, mat)); tronco.add(q); return q; });
  g.userData.materiais = [mat, cabeca.material];
  g.userData.corBase = cor;
  return { g, pernas, bracos, tronco, alturaRotulo: 2.15, palito: true };
}

let _circulo = null;
function texCirculoVazado() {
  return _circulo || (_circulo = canvasTex(128, 128, (c) => {
    c.clearRect(0, 0, 128, 128); c.strokeStyle = '#fff'; c.lineWidth = 12;
    c.beginPath(); c.arc(64, 64, 52, 0, Math.PI * 2); c.stroke();
  }, false));
}

const PX = 0.058; // um "pixel" do boneco de blocos: 32 px de altura ≈ 1,86 m
function bonecoBlocos(j, idx) {
  const cor = corCss(j.cor, '#888888'), borda = corCss(j.borda, '#ffffff'), pele = PELES[idx % PELES.length];
  const cabelo = ['#3b2414', '#1c1410', '#6b4a2b', '#c9a15a'][idx % 4];
  const lamb = (map) => new THREE.MeshLambertMaterial({ map });
  const face = (tipo) => texPixel(8, 8, (c) => {
    c.fillStyle = pele; c.fillRect(0, 0, 8, 8);
    c.fillStyle = cabelo;
    if (tipo === 'topo') { c.fillRect(0, 0, 8, 8); return; }
    if (tipo === 'baixo') return;
    c.fillRect(0, 0, 8, tipo === 'tras' ? 5 : 2);
    if (tipo === 'lado') c.fillRect(0, 0, 3, 4);
    if (tipo === 'frente') {
      c.fillRect(0, 2, 1, 1); c.fillRect(7, 2, 1, 1);
      c.fillStyle = '#fff'; c.fillRect(1, 4, 1, 1); c.fillRect(5, 4, 1, 1);
      c.fillStyle = '#3a4ec4'; c.fillRect(2, 4, 1, 1); c.fillRect(6, 4, 1, 1);
      c.fillStyle = 'rgba(0,0,0,0.18)'; c.fillRect(3, 5, 2, 1);
      c.fillStyle = '#6b3a2a'; c.fillRect(2, 6, 4, 1);
    }
  });
  const camisa = (costas) => texPixel(16, 24, (c) => {
    c.fillStyle = cor; c.fillRect(0, 0, 16, 24);
    c.fillStyle = borda; c.fillRect(0, 0, 16, 2);
    if (costas && j.numero != null) { c.font = 'bold 12px monospace'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(String(j.numero), 8, 12); }
  });
  const membro = (topo, topoPx, meio, fim) => texPixel(4, 12, (c) => {
    c.fillStyle = meio; c.fillRect(0, 0, 4, 12);
    c.fillStyle = topo; c.fillRect(0, 0, 4, topoPx);
    if (fim) { c.fillStyle = fim; c.fillRect(0, 10, 4, 2); }
  });
  const g = new THREE.Group();
  const cab = new THREE.Mesh(new THREE.BoxGeometry(8 * PX, 8 * PX, 8 * PX), [face('lado'), face('lado'), face('topo'), face('baixo'), face('frente'), face('tras')].map(lamb));
  cab.position.y = 28 * PX; g.add(cab);
  const corpoMat = lamb(camisa(false));
  const tronco = new THREE.Mesh(new THREE.BoxGeometry(8 * PX, 12 * PX, 4 * PX), [corpoMat, corpoMat, corpoMat, corpoMat, corpoMat, lamb(camisa(true))]);
  tronco.position.y = 18 * PX; g.add(tronco);
  const matBraco = lamb(membro(cor, 4, pele));
  const matPerna = lamb(membro(new THREE.Color(cor).multiplyScalar(0.7).getStyle(), 5, borda, '#222'));
  const bracos = [-1, 1].map((s) => {
    const q = new THREE.Group(); q.position.set(s * 6 * PX, 24 * PX, 0); g.add(q);
    q.add(new THREE.Mesh(new THREE.BoxGeometry(4 * PX, 12 * PX, 4 * PX).translate(0, -6 * PX + 1 * PX, 0), matBraco));
    return q;
  });
  const pernas = [-1, 1].map((s) => {
    const q = new THREE.Group(); q.position.set(s * 2 * PX, 12 * PX, 0); g.add(q);
    q.add(new THREE.Mesh(new THREE.BoxGeometry(4 * PX, 12 * PX, 4 * PX).translate(0, -6 * PX, 0), matPerna));
    return q;
  });
  return { g, pernas, bracos, tronco: null, alturaRotulo: 2.2 };
}

const ST = 0.36; // um "stud" do boneco de bloquinho
function bonecoBloquinho(j) {
  const cor = corCss(j.cor, '#888888'), borda = corCss(j.borda, '#ffffff');
  const plast = (o) => new THREE.MeshStandardMaterial({ roughness: 0.38, metalness: 0, ...o });
  const amarelo = plast({ color: 0xf5cd30 });
  const rosto = canvasTex(256, 128, (c, w, h) => {
    c.fillStyle = '#f5cd30'; c.fillRect(0, 0, w, h);
    c.fillStyle = '#1b1b1b';
    c.beginPath(); c.ellipse(w / 2 - 16, h * 0.4, 5, 10, 0, 0, Math.PI * 2); c.fill();
    c.beginPath(); c.ellipse(w / 2 + 16, h * 0.4, 5, 10, 0, 0, Math.PI * 2); c.fill();
    c.lineWidth = 5; c.strokeStyle = '#1b1b1b'; c.beginPath(); c.arc(w / 2, h * 0.5, 24, 0.2 * Math.PI, 0.8 * Math.PI); c.stroke();
  });
  const camisa = (costas) => canvasTex(128, 128, (c, w, h) => {
    c.fillStyle = cor; c.fillRect(0, 0, w, h);
    if (costas && j.numero != null) { c.fillStyle = borda; c.font = 'bold 64px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(String(j.numero), w / 2, h / 2 + 4); }
  });
  const g = new THREE.Group();
  const cabGeo = new THREE.CylinderGeometry(0.62 * ST, 0.62 * ST, 1.15 * ST, 28).rotateY(Math.PI); // u = 0,5 (rosto) para a frente
  const cab = new THREE.Mesh(cabGeo, [plast({ map: rosto }), amarelo, amarelo]);
  cab.position.y = 4.6 * ST; g.add(cab);
  const corpo = plast({ map: camisa(false) });
  const tronco = new THREE.Mesh(new THREE.BoxGeometry(2 * ST, 2 * ST, 1 * ST), [corpo, corpo, corpo, corpo, corpo, plast({ map: camisa(true) })]);
  tronco.position.y = 3 * ST; g.add(tronco);
  const bracos = [-1, 1].map((s) => {
    const q = new THREE.Group(); q.position.set(s * 1.5 * ST, 3.9 * ST, 0); g.add(q);
    q.add(new THREE.Mesh(new THREE.BoxGeometry(ST, 2 * ST, ST).translate(0, -0.9 * ST, 0), amarelo));
    return q;
  });
  const matPerna = plast({ color: new THREE.Color(borda).lerp(new THREE.Color(cor), 0.15) });
  const pernas = [-1, 1].map((s) => {
    const q = new THREE.Group(); q.position.set(s * 0.5 * ST, 2 * ST, 0); g.add(q);
    q.add(new THREE.Mesh(new THREE.BoxGeometry(ST, 2 * ST, ST).translate(0, -ST, 0), matPerna));
    return q;
  });
  return { g, pernas, bracos, tronco: null, alturaRotulo: 2.3 };
}

function criarBoneco(j, idx, estilo) {
  const bo = estilo === 'realista' ? bonecoRealista(j, idx)
    : estilo.startsWith('palitos') ? bonecoPalito(j, idx, estilo)
      : estilo === 'blocos' ? bonecoBlocos(j, idx) : bonecoBloquinho(j, idx);
  const tema = ESTILOS[estilo].tema;
  bo.rotulo = new THREE.Sprite(new THREE.SpriteMaterial({ map: texRotulo(nomeCurto(j), false, tema), depthWrite: false, transparent: true, toneMapped: false }));
  bo.rotulo.scale.set(4.8, 0.6, 1); bo.rotulo.position.y = bo.alturaRotulo; bo.g.add(bo.rotulo);
  marcar(bo.g, j);
  bo.rotulo.userData.jogador = null; // o rótulo não conta como clique no jogador
  return bo;
}

function nomeCurto(j) {
  if (j.nome) return j.numero != null ? `${j.numero} ${j.nome}` : j.nome;
  if (j.numero != null) return `#${j.numero}`;
  return j.rotuloGenerico;
}

function nomeLongo(j) { return j.nome || (j.numero != null ? `Camisa ${j.numero}` : `Jogador ${j.rotuloGenerico}`); }

function bonecoAtual(j) {
  j.bonecos ||= {};
  if (!j.bonecos[estado.estilo]) j.bonecos[estado.estilo] = criarBoneco(j, j.idx, estado.estilo);
  return j.bonecos[estado.estilo];
}

function trocarRotulo(j, destaque) {
  const bo = j.bonecos?.[estado.estilo]; if (!bo) return;
  const m = bo.rotulo.material;
  m.map.dispose(); m.map = texRotulo(nomeCurto(j), destaque, ESTILOS[estado.estilo].tema); m.needsUpdate = true;
  if (bo.palito) {
    const cor = destaque ? ESTILOS[estado.estilo].palito.destaque : bo.g.userData.corBase;
    bo.g.userData.materiais.forEach((x) => x.color.set(cor));
  }
}

function mostrarBonecos(l, mostrar) {
  for (const j of l.jogadores) {
    for (const bo of Object.values(j.bonecos || {})) cena.remove(bo.g);
    if (mostrar) { j.boneco = bonecoAtual(j); cena.add(j.boneco.g); }
  }
}

function aplicarEstilo(nome) {
  const e = ESTILOS[nome];
  estado.estilo = nome;
  for (const [k, g] of Object.entries(ambientes)) g.visible = k === nome;
  if (!ambientes[nome]) { ambientes[nome] = e.montar(); cena.add(ambientes[nome]); }
  if (!e._fundo) e._fundo = e.fundo();
  cena.background = e._fundo;
  cena.fog = e.fog ? new THREE.Fog(...e.fog) : null;
  renderer.toneMapping = e.tone; renderer.toneMappingExposure = e.exp;
  hemi.intensity = e.luz[0]; sol.intensity = e.luz[1];
  sol.castShadow = estado.sombras && e.sombras;
  if (bola) cena.remove(bola);
  bola = bolas[nome] ||= criarBola(nome);
  cena.add(bola);
  anelSel.material.color.set(e.tema.anel);
  if (estado.lance) {
    mostrarBonecos(estado.lance, true);
    for (const j of estado.lance.jogadores) trocarRotulo(j, j === estado.sel);
  }
  document.querySelectorAll('#seg-estilo button').forEach((b) => b.classList.toggle('ativo', b.dataset.v === nome));
  $('#chk-sombras').disabled = !e.sombras;
  try { localStorage.setItem('lancepov:estilo', nome); } catch { /* sem armazenamento */ }
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

// Lances em "roteiro" (quadros-chave [t, x, y(, z)]) viram arrays por quadro, como os lances com dados reais.
function expandirChaves(chaves, n, fps, suave) {
  const out = new Array(n);
  const ks = chaves.slice().sort((a, b) => a[0] - b[0]);
  const dims = ks[0].length - 1;
  let i = 0;
  for (let f = 0; f < n; f++) {
    const t = f / fps;
    if (t <= ks[0][0]) { out[f] = ks[0].slice(1); continue; }
    if (t >= ks[ks.length - 1][0]) { out[f] = ks[ks.length - 1].slice(1); continue; }
    while (i < ks.length - 2 && t > ks[i + 1][0]) i++;
    const k1 = ks[i], k2 = ks[i + 1], u = (t - k1[0]) / Math.max(1e-6, k2[0] - k1[0]);
    const v = [];
    for (let d = 1; d <= dims; d++) {
      if (!suave) { v.push(k1[d] + (k2[d] - k1[d]) * u); continue; }
      const k0 = ks[i - 1] || k1, k3 = ks[i + 2] || k2;            // Catmull-Rom
      const p0 = k0[d], p1 = k1[d], p2 = k2[d], p3 = k3[d];
      v.push(0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u));
    }
    out[f] = v;
  }
  return out;
}

function expandirRoteiro(l) {
  l.fps = FPS_ROTEIRO;
  l.frames = Math.round(l.duracao * l.fps) + 1;
  l.bola = expandirChaves(l.chavesBola, l.frames, l.fps, false);
  for (const j of l.jogadores) j.pos = expandirChaves(j.chaves, l.frames, l.fps, true);
}

function derivarJogador(l, j) {
  const fps = l.fps, n = l.frames;
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
}

function prepararLance(l) {
  if (l.roteiro) expandirRoteiro(l);
  let ult = l.bola.find(Boolean) || [0, 0, 0];
  l.bola = l.bola.map((b) => (b ? (ult = b.length === 3 ? b : [b[0], b[1], 0]) : ult));
  const contagem = { attack: 0, defense: 0 };
  l.jogadores.forEach((j, idx) => {
    j.idx = idx;
    contagem[j.time] = (contagem[j.time] || 0) + 1;
    j.rotuloGenerico = `${j.time === 'attack' ? 'A' : 'D'}${contagem[j.time]}`;
    j.nomeTime = l.times?.[j.time] || (j.time === 'attack' ? 'Ataque' : 'Defesa');
    derivarJogador(l, j);
  });
  definirFinalizador(l);
}

function definirFinalizador(l) {
  const heuristica = acharFinalizador(l);   // também calcula l.frameGol
  l.finalizador = (l.finalizadorId != null && l.jogadores.find((j) => String(j.id) === String(l.finalizadorId)))
    || (l.finalizadorNumero != null && l.jogadores.find((j) => j.time === 'attack' && j.numero === l.finalizadorNumero))
    || heuristica;
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

let olhar = null, ultimoT = -1;
function yawOlhar(j, t) {
  if (!olhar.relativo) return amostraAngulo(olhar.yaw, t * SUB);
  return amostraAngulo(j.corpo, t) + limita(amostraNum(olhar.yaw, t * SUB), -PESCOCO, PESCOCO);
}

// ---------------------------------------------------------------- atualização por quadro
const tvAlvo = new THREE.Vector3(), tvPos = new THREE.Vector3(), tmp = new THREE.Vector3();

function atualizarCena(t, dtReal) {
  const l = estado.lance;
  const b = amostra(l.bola, t);
  const raioBola = estado.estilo === 'blocos' ? 0.12 : 0.11;
  bola.position.copy(v3(b[0], b[1], b[2] + raioBola));
  bola.rotation.x = -t * 0.9; bola.rotation.z = t * 0.4;

  for (const j of l.jogadores) {
    const bo = j.boneco, p = amostra(j.pos, t);
    if (!p) { bo.g.visible = false; continue; }
    const v = amostra(j.vel, t), veloc = Math.hypot(v[0], v[1]);
    const fase = amostraNum(j.acum, t) / PASSADA * Math.PI * 2;
    bo.g.visible = !(estado.vista === 'pov' && j === estado.sel && !estado.editor);
    bo.g.position.copy(v3(p[0], p[1], 0));
    bo.g.rotation.y = amostraAngulo(j.corpo, t);
    const amp = Math.min(veloc / 7, 1) * 0.75;
    bo.pernas[0].rotation.x = Math.sin(fase) * amp;
    bo.pernas[1].rotation.x = -Math.sin(fase) * amp;
    bo.bracos[0].rotation.x = -Math.sin(fase) * amp * 0.8;
    bo.bracos[1].rotation.x = Math.sin(fase) * amp * 0.8;
    if (bo.tronco) bo.tronco.rotation.x = Math.min(veloc, 8) * (bo.palito ? 0.03 : 0.018);
    bo.g.position.y = Math.abs(Math.sin(fase)) * 0.04 * amp;
    bo.rotulo.visible = estado.rotulos && bo.g.visible;
  }

  fichas.visible = estado.editor || estado.vista === 'tatica';   // na vista de cima, bonecos viram fichas numeradas
  if (fichas.visible) atualizarFichas(t, b);

  const nuvens = ambientes.blocos?.getObjectByName('nuvens');
  if (nuvens && estado.estilo === 'blocos') nuvens.position.x = (performance.now() / 1000 * 0.8) % 400;

  const s = estado.sel, ps = amostra(s.pos, t);
  const marcado = estado.editor && estado.selEditor === 'bola' ? b : ps;
  anelSel.visible = estado.vista !== 'pov' || estado.editor;
  anelSel.position.copy(v3(marcado[0], marcado[1], 0.03));

  const salto = Math.abs(t - ultimoT) > 3 || ultimoT < 0;
  ultimoT = t;
  const k = salto ? 1 : 1 - Math.exp(-dtReal * 3);
  const yaw = yawOlhar(s, t), pitch = amostraAngulo(olhar.pitch, t * SUB);
  const vs = amostra(s.vel, t), vels = Math.hypot(vs[0], vs[1]);
  const vista = estado.editor ? 'tatica' : estado.vista;
  camera.up.set(0, 1, 0);
  controles.enabled = vista === 'drone';

  if (vista === 'pov') {
    const fase = amostraNum(s.acum, t) / PASSADA * Math.PI * 2;
    const bob = Math.sin(fase * 2) * 0.03 * Math.min(vels / 6, 1);
    camera.position.copy(v3(ps[0], ps[1], OLHO + bob));
    camera.lookAt(tmp.copy(camera.position).add(dirDe(yaw, pitch)));
    setFov(estado.fov);
  } else if (vista === 'terceira') {
    const dir = dirDe(yaw, 0);
    const alvoPos = v3(ps[0], ps[1], 2.6).addScaledVector(dir, -5.5);
    tvPos.lerp(alvoPos, salto ? 1 : 1 - Math.exp(-dtReal * 5));
    camera.position.copy(tvPos);
    tvAlvo.lerp(v3(ps[0], ps[1], 1.3).addScaledVector(dirDe(yaw, pitch), 8), salto ? 1 : 1 - Math.exp(-dtReal * 5));
    camera.lookAt(tvAlvo);
    setFov(65);
  } else if (vista === 'tv') {
    tvAlvo.lerp(v3(b[0], b[1], 1), k);
    // câmera principal: perto do meio-campo, dentro da arquibancada, sob a cobertura
    camera.position.set(limita(tvAlvo.x * 0.3, -18, 18), 21, HY + 30);
    camera.lookAt(tvAlvo);
    setFov(limita(16 + Math.abs(tvAlvo.x) * 0.12, 16, 24));
  } else if (vista === 'tatica') {
    camera.up.set(0, 0, -1);
    if (estado.editor) {
      // campo inteiro (com margem), parado, para editar; a roda do mouse aproxima
      setFov(42);
      const tv = Math.tan(THREE.MathUtils.degToRad(21));
      const h = Math.max(39 / tv, 57 / (tv * camera.aspect)) / estado.edZoom;
      camera.position.set(estado.edCentro[0], h, -estado.edCentro[1] + 0.001);
      camera.lookAt(estado.edCentro[0], 0, -estado.edCentro[1]);
    } else {
      tvAlvo.lerp(v3(limita(b[0] * 0.6, -22, 22), limita(b[1] * 0.4, -8, 8), 0), k);
      camera.position.set(tvAlvo.x, 82, tvAlvo.z + 0.001);
      camera.lookAt(tvAlvo.x, 0, tvAlvo.z);
      setFov(45);
    }
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
    mg.setLineDash(j.estimado ? [2, 2] : []);
    mg.lineWidth = j === s ? 2.5 : 1; mg.strokeStyle = j === s ? '#ff5a1f' : corCss(j.borda, '#fff'); mg.stroke();
    mg.setLineDash([]);
  }
  const b = amostra(l.bola, t), [bx, by] = mmXY(b[0], b[1]);
  mg.beginPath(); mg.arc(bx, by, 2.4 + b[2] * 0.6, 0, Math.PI * 2);
  mg.fillStyle = '#fff'; mg.fill(); mg.lineWidth = 1; mg.strokeStyle = '#111'; mg.stroke();
}

function jogadorMaisPerto(x, y, raio, t = estado.t) {
  let melhor = null, md = raio;
  for (const j of estado.lance.jogadores) {
    const p = amostra(j.pos, t); if (!p) continue;
    const d = Math.hypot(p[0] - x, p[1] - y); if (d < md) { md = d; melhor = j; }
  }
  return { j: melhor, d: md };
}

mm.addEventListener('click', (ev) => {
  const r = mm.getBoundingClientRect(), e = mmEscala() * (r.width / mm.width);
  const x = (ev.clientX - r.left) / e - HX - MM_M, y = HY + MM_M - (ev.clientY - r.top) / e;
  const { j } = jogadorMaisPerto(x, y, 5);
  if (j) selecionar(j);
});

// ---------------------------------------------------------------- clique e arraste na cena
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(), planoChao = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
let baixo = null, arrastando = null;

function pontoNoChao(e) {
  const r = canvas.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const p = new THREE.Vector3();
  return ray.ray.intersectPlane(planoChao, p) ? [p.x, -p.z] : null;
}

canvas.addEventListener('pointerdown', (e) => {
  baixo = [e.clientX, e.clientY];
  if (!estado.editor) return;
  const p = pontoNoChao(e); if (!p) return;
  const b = amostra(estado.lance.bola, estado.t);
  const raio = 2.6 / Math.sqrt(estado.edZoom);
  const { j, d } = jogadorMaisPerto(p[0], p[1], raio);
  const dBola = Math.hypot(b[0] - p[0], b[1] - p[1]);
  const alvo = dBola < raio * 0.7 && dBola <= d ? 'bola' : j;
  if (!alvo) return;
  selecionarNoEditor(alvo);
  arrastando = alvo;
  canvas.setPointerCapture(e.pointerId);
});

canvas.addEventListener('pointermove', (e) => {
  if (!arrastando) return;
  const p = pontoNoChao(e); if (!p) return;
  moverChave(arrastando, limita(p[0], -HX - 6, HX + 6), limita(p[1], -HY - 6, HY + 6));
});

canvas.addEventListener('pointerup', (e) => {
  if (arrastando) { arrastando = null; recalcularDepoisDeEditar(); return; }
  if (!baixo || Math.hypot(e.clientX - baixo[0], e.clientY - baixo[1]) > 5) return;
  const r = canvas.getBoundingClientRect();
  mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const alvos = estado.lance.jogadores.filter((j) => j.boneco.g.visible).map((j) => j.boneco.g);
  const hit = ray.intersectObjects(alvos, true).find((h) => h.object.userData.jogador);
  if (hit) selecionar(hit.object.userData.jogador);
});

// ---------------------------------------------------------------- editor de lance
const fichas = new THREE.Group(); fichas.visible = false; cena.add(fichas);
const geoFicha = new THREE.PlaneGeometry(2.4, 2.4).rotateX(-Math.PI / 2);
function texFicha(j) {
  return canvasTex(128, 128, (c) => {
    c.beginPath(); c.arc(64, 64, 56, 0, Math.PI * 2);
    c.fillStyle = j === 'bola' ? '#ffffff' : corCss(j.cor, '#888'); c.fill();
    c.lineWidth = 9; c.strokeStyle = j === 'bola' ? '#111' : corCss(j.borda, '#fff'); c.stroke();
    if (j !== 'bola') {
      c.fillStyle = corCss(j.borda, '#fff'); c.font = 'bold 58px system-ui, sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText(j.numero != null ? String(j.numero) : j.rotuloGenerico, 64, 68);
    }
  });
}
function ficha(j) {
  const chave = j === 'bola' ? '__bola' : j;
  fichas.userData.mapa ||= new Map();
  let m = fichas.userData.mapa.get(chave);
  if (!m) {
    m = new THREE.Mesh(geoFicha, new THREE.MeshBasicMaterial({ map: texFicha(j), transparent: true, depthTest: false, toneMapped: false }));
    m.renderOrder = 10; if (j === 'bola') m.scale.setScalar(0.6);
    fichas.add(m); fichas.userData.mapa.set(chave, m);
  }
  return m;
}
function atualizarFichas(t, b) {
  const ativos = new Set();
  for (const j of estado.lance.jogadores) {
    const p = amostra(j.pos, t); if (!p) continue;
    const m = ficha(j); m.position.copy(v3(p[0], p[1], 0.05)); m.visible = true; ativos.add(m);
    m.scale.setScalar((estado.editor ? estado.selEditor === j : estado.sel === j) ? 1.25 : 1);
  }
  const mb = ficha('bola'); mb.position.copy(v3(b[0], b[1], 0.06)); mb.visible = true; ativos.add(mb);
  for (const m of fichas.children) if (!ativos.has(m)) m.visible = false;
}
function limparFichas() {
  for (const m of fichas.children) { m.material.map.dispose(); m.material.dispose(); }
  fichas.clear(); fichas.userData.mapa = new Map();
}
canvas.addEventListener('wheel', (e) => {
  if (!estado.editor) return;
  e.preventDefault();
  const p = pontoNoChao(e), z0 = estado.edZoom;
  estado.edZoom = limita(z0 * (e.deltaY < 0 ? 1.15 : 1 / 1.15), 1, 5);
  if (p) {   // aproxima em direção ao ponto sob o mouse
    const k = 1 - z0 / estado.edZoom;
    estado.edCentro = [limita(estado.edCentro[0] + (p[0] - estado.edCentro[0]) * k, -HX, HX), limita(estado.edCentro[1] + (p[1] - estado.edCentro[1]) * k, -HY, HY)];
  }
  if (estado.edZoom === 1) estado.edCentro = [0, 0];
}, { passive: false });

function paraRoteiro(l) {
  // lance com dados por quadro → quadros-chave a cada 0,5 s (jogadores) e 0,1 s (bola)
  if (l.roteiro) return;
  const tPassoJ = 10, tPassoB = 2;
  const chaves = (arr, passo) => {
    const ks = [];
    for (let f = 0; f < arr.length; f += passo) if (arr[f]) ks.push([+(f / l.fps).toFixed(3), ...arr[f].map((v) => +v.toFixed(2))]);
    const u = arr.length - 1; if (u % passo && arr[u]) ks.push([+(u / l.fps).toFixed(3), ...arr[u].map((v) => +v.toFixed(2))]);
    return ks;
  };
  l.chavesBola = chaves(l.bola, tPassoB);
  for (const j of l.jogadores) j.chaves = chaves(j.pos, tPassoJ);
  l.duracao = (l.frames - 1) / l.fps;
  l.roteiro = true; l.editadoDeDados = true;
  expandirRoteiro(l);
  for (const j of l.jogadores) derivarJogador(l, j);
}

function chavesDe(alvo) { return alvo === 'bola' ? estado.lance.chavesBola : alvo.chaves; }

function moverChave(alvo, x, y) {
  const l = estado.lance, t = +(estado.t / l.fps).toFixed(3), ks = chavesDe(alvo);
  let k = ks.find((c) => Math.abs(c[0] - t) < 0.12);
  if (!k) {
    const atual = alvo === 'bola' ? amostra(l.bola, estado.t) : amostra(alvo.pos, estado.t);
    k = [t, ...atual]; ks.push(k); ks.sort((a, b) => a[0] - b[0]);
  }
  k[1] = +x.toFixed(2); k[2] = +y.toFixed(2);
  reexpandir(alvo);
  marcarAlterado();
}

function reexpandir(alvo) {
  const l = estado.lance;
  if (alvo === 'bola') l.bola = expandirChaves(l.chavesBola, l.frames, l.fps, false);
  else { alvo.pos = expandirChaves(alvo.chaves, l.frames, l.fps, true); derivarJogador(l, alvo); }
}

function recalcularDepoisDeEditar() {
  const l = estado.lance;
  for (const j of l.jogadores) derivarJogador(l, j);
  definirFinalizador(l);
  olhar = calcularOlhar(l, estado.sel, estado.olhar);
  ultimoT = -1;
  atualizarEditor();
}

function selecionarNoEditor(alvo) {
  estado.selEditor = alvo;
  if (alvo !== 'bola') selecionar(alvo, true);
  atualizarEditor();
}

function marcarAlterado() {
  const l = estado.lance;
  try { localStorage.setItem(`lancepov:rascunho:${l.id}`, JSON.stringify(exportarRoteiro(l))); $('#ed-status').textContent = 'Rascunho salvo neste navegador.'; }
  catch { $('#ed-status').textContent = 'Não consegui salvar o rascunho neste navegador; exporte o JSON.'; }
}

function exportarRoteiro(l) {
  const campos = ['id', 'titulo', 'subtitulo', 'grupo', 'ordem', 'contexto', 'times', 'finalizadorId', 'fonte'];
  const out = { roteiro: true, aproximado: true, duracao: +l.duracao.toFixed(2) };
  for (const c of campos) if (l[c] != null) out[c] = l[c];
  if (out.finalizadorId == null && l.finalizador) out.finalizadorId = String(l.finalizador.id);
  out.chavesBola = l.chavesBola;
  out.jogadores = l.jogadores.map((j) => ({ id: j.id, time: j.time, numero: j.numero, nome: j.nome, cor: j.cor, borda: j.borda, chaves: j.chaves }));
  return out;
}

function baixarArquivo(nome, conteudo, tipo = 'application/json') {
  const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
  Object.assign(document.createElement('a'), { href: url, download: nome }).click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function alternarEditor(ligar) {
  if (estado.gravando) return;
  estado.editor = ligar;
  document.body.classList.toggle('editando', ligar);
  $('#editor').hidden = !ligar;
  $('#btn-editar').classList.toggle('ativo', ligar);
  limparFichas();
  if (ligar) {
    estado.edZoom = 1; estado.edCentro = [0, 0];
    paraRoteiro(estado.lance);
    estado.tocando = false; atualizarPlay();
    selecionarNoEditor(estado.sel);
  }
  ultimoT = -1;
}

function atualizarEditor() {
  if (!estado.editor) return;
  const l = estado.lance, alvo = estado.selEditor;
  $('#ed-alvo').textContent = alvo === 'bola' ? 'Bola' : nomeLongo(alvo);
  const ks = chavesDe(alvo) || [];
  $('#ed-chaves').textContent = `${ks.length} quadros-chave`;
  const ehBola = alvo === 'bola';
  $('#ed-altura-linha').hidden = !ehBola;
  if (ehBola) $('#ed-altura').value = amostra(l.bola, estado.t)[2];
  $('#ed-duracao').value = fmt(l.duracao, 1).replace(',', '.');
  // marcas dos quadros-chave na linha do tempo
  $('#marcas-chaves').innerHTML = ks.map((k) => `<i style="left:${(k[0] / l.duracao) * 100}%"></i>`).join('');
  const aviso = l.editadoDeDados ? 'Este lance veio de dados reais; ao editar, ele vira quadros-chave a cada 0,5 s.' : '';
  $('#ed-aviso').textContent = aviso;
}

function irParaChave(dir) {
  const l = estado.lance, t = estado.t / l.fps, ks = chavesDe(estado.selEditor);
  const alvo = dir > 0 ? ks.find((k) => k[0] > t + 0.01) : [...ks].reverse().find((k) => k[0] < t - 0.01);
  if (alvo) { estado.t = alvo[0] * l.fps; atualizarEditor(); }
}

function apagarChave() {
  const l = estado.lance, t = estado.t / l.fps, ks = chavesDe(estado.selEditor);
  if (ks.length <= 1) return;
  const i = ks.findIndex((k) => Math.abs(k[0] - t) < 0.12);
  if (i < 0) return;
  ks.splice(i, 1);
  reexpandir(estado.selEditor); marcarAlterado(); recalcularDepoisDeEditar();
}

function lanceEmBranco() {
  const formacao = (time) => {
    const linhas = time === 'attack' ? [[-48, [0]], [-30, [-20, -7, 7, 20]], [-14, [-15, 0, 15]], [-3, [-22, 0, 22]]] : [[48, [0]], [32, [-21, -7, 7, 21]], [18, [-20, -7, 7, 20]], [8, [-6, 6]]];
    const js = []; let n = 1;
    for (const [x, ys] of linhas) for (const y of ys) {
      js.push({ id: `${time === 'attack' ? 'a' : 'd'}${n}`, time, numero: n, nome: null, cor: time === 'attack' ? '#1f4fff' : '#e5212f', borda: '#ffffff', chaves: [[0, x, y]] });
      n++;
    }
    return js;
  };
  return {
    id: `novo-${Date.now().toString(36)}`, titulo: 'Novo lance', subtitulo: 'Criado no editor', grupo: 'meus',
    roteiro: true, aproximado: true, duracao: 10, times: { attack: 'Ataque', defense: 'Defesa' },
    chavesBola: [[0, 0, 0, 0]], jogadores: [...formacao('attack'), ...formacao('defense')],
  };
}

$('#btn-editar').onclick = () => alternarEditor(!estado.editor);
$('#ed-fechar').onclick = () => alternarEditor(false);
$('#ed-bola').onclick = () => selecionarNoEditor('bola');
$('#ed-ant').onclick = () => irParaChave(-1);
$('#ed-prox').onclick = () => irParaChave(1);
$('#ed-apagar').onclick = apagarChave;
$('#ed-altura').oninput = (e) => {
  const l = estado.lance, t = +(estado.t / l.fps).toFixed(3), ks = l.chavesBola;
  let k = ks.find((c) => Math.abs(c[0] - t) < 0.12);
  if (!k) { k = [t, ...amostra(l.bola, estado.t)]; ks.push(k); ks.sort((a, b) => a[0] - b[0]); }
  k[3] = +(+e.target.value).toFixed(2);
  reexpandir('bola'); marcarAlterado(); atualizarEditor();
};
$('#ed-duracao').onchange = (e) => {
  const l = estado.lance, d = limita(parseFloat(String(e.target.value).replace(',', '.')) || l.duracao, 2, 60);
  l.duracao = d; expandirRoteiro(l); recalcularDepoisDeEditar(); marcarAlterado();
  $('#rng-tempo').max = l.frames - 1;
  estado.t = Math.min(estado.t, l.frames - 1);
};
$('#ed-exportar').onclick = () => baixarArquivo(`${estado.lance.id}.json`, JSON.stringify(exportarRoteiro(estado.lance), null, 1));
$('#ed-importar').onclick = () => $('#arquivo-importar').click();
$('#arquivo-importar').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const l = JSON.parse(await f.text());
    if (!l.roteiro || !Array.isArray(l.jogadores) || !Array.isArray(l.chavesBola)) throw new Error('não é um roteiro do Lance POV');
    l.grupo = l.grupo || 'meus';
    const i = estado.lances.findIndex((x) => x.id === l.id);
    if (i >= 0) estado.lances[i] = l; else estado.lances.push(l);
    preencherLances(); $('#sel-lance').value = estado.lances.indexOf(l);
    carregarLance(l);
  } catch (err) { alert(`Não consegui importar: ${err.message}`); }
  e.target.value = '';
};
$('#ed-descartar').onclick = () => {
  const l = estado.lance;
  try { localStorage.removeItem(`lancepov:rascunho:${l.id}`); } catch { /* sem armazenamento */ }
  const original = estado.originais[l.id];
  if (original) {
    const copia = JSON.parse(original); const i = estado.lances.indexOf(l);
    estado.lances[i] = copia; mostrarBonecos(l, false); estado.lance = null; carregarLance(copia, true);
    if (estado.editor) alternarEditor(true);
  }
  $('#ed-status').textContent = 'Rascunho descartado.';
};
$('#ed-novo').onclick = () => {
  const l = lanceEmBranco();
  estado.lances.push(l); preencherLances(); $('#sel-lance').value = estado.lances.indexOf(l);
  carregarLance(l); alternarEditor(true);
};

// ---------------------------------------------------------------- interface
const GRUPOS = [
  ['hypados', 'Os 30 mais hypados'],
  ['brasil', 'Futebol brasileiro'],
  ['meus', 'Meus lances'],
  ['extras', 'Mais lances (Liverpool 2019)'],
];

function preencherLances() {
  const sel = $('#sel-lance');
  const ordenados = (g) => estado.lances.map((l, i) => [l, i]).filter(([l]) => (l.grupo || 'extras') === g).sort((a, b) => (a[0].ordem ?? 999) - (b[0].ordem ?? 999));
  sel.innerHTML = GRUPOS.map(([g, rotulo]) => {
    const itens = ordenados(g);
    if (!itens.length) return '';
    return `<optgroup label="${rotulo}">${itens.map(([l, i]) => `<option value="${i}">${l.ordem && g !== 'extras' ? `${l.ordem}. ` : ''}${l.titulo}</option>`).join('')}</optgroup>`;
  }).join('');
  sel.onchange = () => { if (!estado.gravando) carregarLance(estado.lances[+sel.value]); };
}

function carregarLance(l, ignorarRascunho) {
  if (estado.lance) mostrarBonecos(estado.lance, false);
  limparFichas();
  if (!estado.originais[l.id]) estado.originais[l.id] = JSON.stringify(l);
  let rascunho = false;
  if (!ignorarRascunho && !l.preparado) {
    try {
      const r = localStorage.getItem(`lancepov:rascunho:${l.id}`);
      if (r) { const d = JSON.parse(r); Object.assign(l, d); delete l.bola; l.jogadores = d.jogadores; rascunho = true; }
    } catch { /* sem armazenamento ou rascunho inválido */ }
  }
  if (!l.preparado) { prepararLance(l); l.preparado = true; }
  estado.lance = l; estado.t = 0; ultimoT = -1;
  mostrarBonecos(l, true);
  const dur = (l.frames - 1) / l.fps;
  const partes = [];
  if (l.subtitulo) partes.push(l.subtitulo + '.');
  if (l.contexto) partes.push(l.contexto);
  partes.push(`${fmt(dur)} s · ${l.jogadores.length} de 22 jogadores.`);
  if (l.qualidade) partes.push(`Posições reais da bola e de ${l.qualidade.jogadores_reais} jogadores; ${l.qualidade.jogadores_estimados} com movimento estimado.`);
  $('#meta').textContent = partes.join(' ');
  $('#aviso-aprox').hidden = !l.aproximado;
  $('#aviso-aprox').textContent = rascunho ? 'Usando o seu rascunho salvo neste navegador.' : 'Reconstrução aproximada: não há dados de posição deste gol. Corrija no editor (✎).';
  $('#fonte-lance').textContent = l.fonte ? `Fonte: ${l.fonte}` : '';
  $('#rng-tempo').max = l.frames - 1;
  $('#marca-gol').style.left = `calc(${(l.frameGol / (l.frames - 1)) * 100}% - 1px)`;
  selecionar(l.finalizador, true);
  estado.tocando = !estado.editor; atualizarPlay();
  if (estado.vista === 'drone') posicionarDrone();
  if (estado.editor) { paraRoteiro(l); selecionarNoEditor(estado.sel); }
  try { localStorage.setItem('lancepov:lance', l.id); } catch { /* sem armazenamento */ }
}

function listarJogadores() {
  const l = estado.lance, caixa = $('#lista-jogadores');
  const grupos = ['attack', 'defense'].map((time) => {
    const js = l.jogadores.filter((j) => j.time === time)
      .sort((a, b) => (b.nome ? 1 : 0) - (a.nome ? 1 : 0) || (a.numero ?? 99) - (b.numero ?? 99));
    if (!js.length) return '';
    return `<div class="grupo">${js[0].nomeTime}</div>` + js.map((j) => {
      const i = l.jogadores.indexOf(j);
      return `<button data-i="${i}" class="${j === estado.sel ? 'ativo' : ''}">
        <span class="camisa" style="background:${corCss(j.cor, '#888')};border-color:${corCss(j.borda, '#fff')};color:${corCss(j.borda, '#fff')}">${j.numero ?? ''}</span>
        ${nomeLongo(j)}${j.estimado ? '<span class="est" title="Movimento estimado: o dado só tem a posição dele no chute">estimado</span>' : ''}${j === l.finalizador ? '<span class="gol">gol</span>' : ''}</button>`;
    }).join('');
  });
  caixa.innerHTML = grupos.join('');
  caixa.querySelectorAll('button').forEach((b) => (b.onclick = () => { const j = l.jogadores[+b.dataset.i]; if (estado.editor) selecionarNoEditor(j); else selecionar(j); }));
}

function selecionar(j, silencioso) {
  const anterior = estado.sel;
  if (anterior && anterior !== j) trocarRotulo(anterior, false);
  estado.sel = j;
  trocarRotulo(j, true);
  olhar = calcularOlhar(estado.lance, j, estado.olhar);
  ultimoT = -1;
  listarJogadores();
  if (estado.editor && estado.selEditor !== 'bola') { estado.selEditor = j; atualizarEditor(); }
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
document.querySelectorAll('#seg-estilo button').forEach((b) => (b.onclick = () => aplicarEstilo(b.dataset.v)));
$('#rng-fov').oninput = (e) => { estado.fov = +e.target.value; $('#out-fov').textContent = `${estado.fov}°`; };
$('#chk-rotulos').onchange = (e) => (estado.rotulos = e.target.checked);
$('#chk-sombras').onchange = (e) => { estado.sombras = e.target.checked; sol.castShadow = estado.sombras && ESTILOS[estado.estilo].sombras; };
$('#btn-finalizador').onclick = () => selecionar(estado.lance.finalizador);
$('#btn-play').onclick = () => {
  if (estado.gravando) return;
  if (!estado.tocando && estado.t >= estado.lance.frames - 1) estado.t = 0;
  estado.tocando = !estado.tocando; atualizarPlay();
};
$('#rng-tempo').oninput = (e) => {
  if (estado.gravando) { e.target.value = estado.t; return; }
  estado.t = +e.target.value; estado.tocando = false; atualizarPlay(); atualizarEditor();
};
$('#sel-vel').onchange = (e) => (estado.vel = +e.target.value);
$('#btn-gravar').onclick = gravar;

addEventListener('keydown', (e) => {
  if (['SELECT', 'INPUT'].includes(e.target.tagName) || estado.gravando) return;
  if (e.code === 'Space') { e.preventDefault(); $('#btn-play').click(); }
  else if (e.key === 'ArrowRight') { estado.t = Math.min(estado.lance.frames - 1, Math.floor(estado.t) + 1); estado.tocando = false; atualizarPlay(); atualizarEditor(); }
  else if (e.key === 'ArrowLeft') { estado.t = Math.max(0, Math.ceil(estado.t) - 1); estado.tocando = false; atualizarPlay(); atualizarEditor(); }
  else if (estado.editor && (e.key === 'Delete' || e.key === 'Backspace')) apagarChave();
  else if (!estado.editor && '12345'.includes(e.key)) mudarVista(['pov', 'terceira', 'tv', 'drone', 'tatica'][+e.key - 1]);
});

// ---------------------------------------------------------------- gravação
function travarDuranteGravacao(travar) {
  for (const id of ['#sel-lance', '#btn-play', '#rng-tempo', '#sel-vel', '#btn-editar']) $(id).disabled = travar;
}

function gravar() {
  if (estado.gravando) { encerrarGravacao(); return; }   // segundo clique encerra antes do fim
  if (!window.MediaRecorder || estado.editor) return;
  const s = estado.sel;
  const nomeArquivo = `lance-pov_${estado.lance.id}_${(s.nome || s.rotuloGenerico).toLowerCase().replace(/\W+/g, '-')}_${estado.vista}_${estado.estilo}.webm`;
  const tipo = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find((m) => MediaRecorder.isTypeSupported(m));
  const rec = new MediaRecorder(canvas.captureStream(30), { mimeType: tipo, videoBitsPerSecond: 10e6 });
  const partes = [];
  rec.ondataavailable = (e) => e.data.size && partes.push(e.data);
  rec.onstop = () => {
    baixarArquivo(nomeArquivo, new Blob(partes, { type: 'video/webm' }), 'video/webm');
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
  $('#tempo').textContent = `${fmt(estado.t / l.fps)} / ${fmt(fim / l.fps)} s`;
  const s = estado.sel, p = amostra(s.pos, estado.t), v = amostra(s.vel, estado.t), b = amostra(l.bola, estado.t);
  $('#hud-nome').textContent = nomeLongo(s);
  $('#hud-dados').textContent = `${s.nomeTime} · ${(Math.hypot(v[0], v[1]) * 3.6).toFixed(0)} km/h · bola a ${fmt(Math.hypot(b[0] - p[0], b[1] - p[1]))} m`;
  renderer.render(cena, camera);
}

// ---------------------------------------------------------------- início
estado.originais = {};
async function carregarJson(url) {
  try { const r = await fetch(url); return r.ok ? (await r.json()).lances || [] : []; } catch { return []; }
}

Promise.all([carregarJson('data/hypados.json'), carregarJson('data/brasil.json'), carregarJson('data/lances.json')])
  .then(([hypados, brasil, extras]) => {
    const ids = new Set();
    for (const l of [...hypados, ...brasil, ...extras]) {
      if (ids.has(l.id)) continue;
      ids.add(l.id);
      if (!l.grupo) l.grupo = hypados.includes(l) ? 'hypados' : brasil.includes(l) ? 'brasil' : 'extras';
      estado.lances.push(l);
    }
    if (!estado.lances.length) throw new Error('nenhum lance encontrado');
    preencherLances();
    let salvo = null, estilo = 'realista';
    try { salvo = localStorage.getItem('lancepov:lance'); estilo = localStorage.getItem('lancepov:estilo') || estilo; } catch { /* sem armazenamento */ }
    const param = new URLSearchParams(location.search);
    if (param.get('estilo')) estilo = param.get('estilo');
    if (param.get('lance')) salvo = param.get('lance');
    aplicarEstilo(ESTILOS[estilo] ? estilo : 'realista');
    const primeiro = estado.lances.find((l) => l.id === salvo) || estado.lances.find((l) => l.grupo === 'hypados' && l.ordem === 1) || estado.lances.find((l) => l.id === 'liverpool-4-0-barcelona') || estado.lances[0];
    $('#sel-lance').value = estado.lances.indexOf(primeiro);
    redimensionar();
    carregarLance(primeiro);
    $('#carregando').hidden = true;
    requestAnimationFrame(quadro);
  })
  .catch((e) => { $('#carregando').textContent = `Não consegui carregar os lances: ${e.message}`; });

// gancho de inspeção para testes automatizados (somente leitura)
window.lancePov = {
  estado, yawOlhar: (t) => yawOlhar(estado.sel, t), corpo: (t) => amostraAngulo(estado.sel.corpo, t), carregarLance, selecionar, aplicarEstilo,
  telaDe: (x, y) => { const p = v3(x, y, 0).project(camera), r = canvas.getBoundingClientRect(); return [r.left + (p.x + 1) / 2 * r.width, r.top + (1 - p.y) / 2 * r.height]; },
};
